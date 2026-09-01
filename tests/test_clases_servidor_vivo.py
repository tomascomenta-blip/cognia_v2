# -*- coding: utf-8 -*-
"""
tests/test_clases_servidor_vivo.py
==================================
El transporte del cuaderno en vivo (cognia/clases/servidor_vivo.py) contra un
servidor DE VERDAD.

NADA DE MOCKS DEL SERVIDOR. En cada test se levanta el `ThreadingHTTPServer`
real en un puerto efimero real y se habla con el por SOCKET CRUDO. Los dos
motivos son operativos, no de gusto:

  - Un test que parcheara el handler comprobaria que el parche funciona, no
    que el guardia responde 403 antes de leer el cuerpo ni que el SSE escribe
    sin Content-Length. Justo eso -- las cabeceras que salen, el orden en que
    salen -- es lo unico que puede fallar aqui.
  - `urllib` (y cualquier cliente decente) NORMALIZA la ruta antes de
    enviarla: colapsa `..` y reescribe el escapado. Los tests de escape de
    directorio necesitan que al servidor le llegue EXACTAMENTE `..%2f..%2f`,
    asi que la peticion se escribe a mano sobre el socket. Con urllib estos
    tests pasarian sin haber probado nada.

AISLAMIENTO. `COGNIA_CLASES_DIR` se desvia a `tmp_path` en un fixture autouse
y se COMPRUEBA el desvio: sin eso, el handshake (`servidor_vivo.json`) y las
jornadas de mentira se escribirian dentro del cuaderno real del duenio
(~/.cognia/clases), y un `setenv` que no coge es indistinguible de un test que
pasa.

Y `parar()` va en el `finally` del fixture SIEMPRE. El servidor es un
singleton de proceso con hilos daemon: uno olvidado seguiria suscrito al bus y
repartiendo los eventos de los tests siguientes.
"""

import json
import socket
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from cognia import events
from cognia.clases import almacen as alm
from cognia.clases import servidor_vivo as sv


# -- aislamiento --------------------------------------------------------------

@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    raiz = tmp_path / "clases"
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(raiz))
    # Verificacion, no fe: si el desvio no cogiera, todos los asserts de abajo
    # seguirian pasando mientras se escribe en el cuaderno de verdad.
    assert alm.raiz() == raiz.resolve() or alm.raiz() == raiz
    sv.fijar_pagina(None)
    sv._ULTIMO_ERROR.clear()
    yield
    sv.fijar_pagina(None)
    sv.parar()
    sv._ULTIMO_ERROR.clear()


@pytest.fixture
def servidor():
    """Un servidor vivo de verdad. Lo apaga el fixture de arriba."""
    return sv.arrancar()


# -- clientes de verdad, escritos a mano --------------------------------------

def _pedir(puerto, ruta, *, token=None, origin=None, host=None,
           metodo="GET", timeout=10.0):
    """Un GET por socket crudo. Devuelve (codigo, cabeceras, cuerpo).

    A mano y no con urllib porque urllib normaliza la ruta antes de mandarla
    (ver la cabecera del fichero): los tests de escape necesitan que llegue lo
    que se teclea. HTTP/1.0 sin `Connection`, asi que el servidor cierra al
    terminar y el `recv` hasta b"" delimita el cuerpo sin parsear nada.
    """
    s = socket.create_connection(("127.0.0.1", puerto), timeout=timeout)
    try:
        lineas = [metodo + " " + ruta + " HTTP/1.0",
                  "Host: " + (host or ("127.0.0.1:%d" % puerto))]
        if token:
            lineas.append("X-Cognia-Token: " + token)
        if origin:
            lineas.append("Origin: " + origin)
        s.sendall(("\r\n".join(lineas) + "\r\n\r\n").encode("utf-8"))
        crudo = b""
        while True:
            trozo = s.recv(65536)
            if not trozo:
                break
            crudo += trozo
    finally:
        s.close()
    cabeceras, _, cuerpo = crudo.partition(b"\r\n\r\n")
    texto = cabeceras.decode("latin-1")
    codigo = int(texto.split("\r\n")[0].split()[1])
    return codigo, texto, cuerpo


def _postear(puerto, cuerpo=None, *, ruta=sv.RUTA_ACCION, token=None,
             origin=None, host=None, cliente=None,
             tipo="application/json", largo=None, crudo=None,
             transfer=None, timeout=20.0):
    """Un POST por socket crudo. Devuelve (codigo, cabeceras, cuerpo).

    A mano por lo mismo que `_pedir`, y ademas porque aqui hace falta MENTIR
    en las cabeceras: `largo` pone un Content-Length que no se corresponde con
    lo que se manda (es como se prueba el tope sin mandar 20 MB por el socket)
    y `crudo` manda un cuerpo que no es el JSON de `cuerpo`.
    """
    if crudo is None:
        crudo = json.dumps(cuerpo if cuerpo is not None else {},
                           ensure_ascii=False).encode("utf-8")
    s = socket.create_connection(("127.0.0.1", puerto), timeout=timeout)
    try:
        lineas = ["POST " + ruta + " HTTP/1.0",
                  "Host: " + (host or ("127.0.0.1:%d" % puerto))]
        if tipo:
            lineas.append("Content-Type: " + tipo)
        if transfer:
            lineas.append("Transfer-Encoding: " + transfer)
        elif largo != "sin":
            lineas.append("Content-Length: %d"
                          % (len(crudo) if largo is None else int(largo)))
        if token:
            lineas.append("X-Cognia-Token: " + token)
        if origin:
            lineas.append("Origin: " + origin)
        if cliente:
            lineas.append("X-Cognia-Cliente: " + cliente)
        s.sendall(("\r\n".join(lineas) + "\r\n\r\n").encode("utf-8") + crudo)
        bruto = b""
        while True:
            trozo = s.recv(65536)
            if not trozo:
                break
            bruto += trozo
    finally:
        s.close()
    cabeceras, _, cuerpo_b = bruto.partition(b"\r\n\r\n")
    texto = cabeceras.decode("latin-1")
    codigo = int(texto.split("\r\n")[0].split()[1])
    return codigo, texto, cuerpo_b


def _json_de(cuerpo: bytes) -> dict:
    """El cuerpo de una respuesta como dict. Que SIEMPRE sea JSON es parte del
    contrato de la puerta: la pagina hace `r.json()` y un HTML de error ahi se
    convierte en 'el servidor contesto algo que no es JSON'."""
    return json.loads(cuerpo.decode("utf-8"))


class _Espia:
    """Un cliente SSE de verdad sobre un socket crudo.

    `drenar=False` es EL CLIENTE LENTO: lee las cabeceras (para saber que el
    flujo arranco) y a partir de ahi no lee mas, que es exactamente lo que
    hace un navegador minimizado o una pestania sin CPU. `rcvbuf` chico
    encoge la ventana TCP para que el servidor se atasque tras unos pocos
    kilobytes en vez de tras el megabyte que aguantarian los buffers por
    defecto: sin eso, provocar el atasco costaria decenas de megas.
    """

    def __init__(self, puerto, token, *, rcvbuf=None, drenar=True,
                 cli=None, timeout=15.0):
        s = socket.socket()
        if rcvbuf:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, int(rcvbuf))
        s.settimeout(timeout)
        s.connect(("127.0.0.1", puerto))
        # `cli` es el identificador de pestania que la pagina lleva incrustado
        # en ctx["eventos"]: aqui se pone a mano para poder probar que el que
        # escribe no recibe su propio cambio.
        ruta = "/eventos?t=" + urllib.parse.quote(token)
        if cli:
            ruta += "&cli=" + urllib.parse.quote(cli)
        s.sendall((("GET " + ruta + " HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n")
                   % puerto).encode("utf-8"))
        crudo = b""
        while b"\r\n\r\n" not in crudo:
            trozo = s.recv(4096)
            if not trozo:
                break
            crudo += trozo
        cabeceras, _, resto = crudo.partition(b"\r\n\r\n")
        self.sock = s
        self.cabeceras = cabeceras.decode("latin-1")
        self._lock = threading.Lock()
        self._buffer = resto
        self.hilo = None
        if drenar:
            self.hilo = threading.Thread(target=self._drenar, daemon=True,
                                         name="espia-sse")
            self.hilo.start()

    def _drenar(self):
        while True:
            try:
                trozo = self.sock.recv(65536)
            except OSError:
                return
            if not trozo:
                return
            with self._lock:
                self._buffer += trozo

    def texto(self):
        with self._lock:
            return self._buffer.decode("utf-8", "replace")

    def esperar(self, subcadena, tope=10.0):
        fin = time.time() + tope
        while time.time() < fin:
            if subcadena in self.texto():
                return True
            time.sleep(0.02)
        return subcadena in self.texto()

    def cerrar(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _esperar_clientes(n, tope=5.0):
    """El handler se suscribe DESPUES de mandar las cabeceras, asi que leer
    las cabeceras no garantiza estar en la lista. Emitir antes de esperar
    aqui daria un test que pasa o falla segun la carga de la maquina."""
    fin = time.time() + tope
    while time.time() < fin:
        if sv.estado()["clientes"] >= n:
            return True
        time.sleep(0.01)
    return sv.estado()["clientes"] >= n


# -- arranque, puerto y pagina ------------------------------------------------

def test_arranca_en_puerto_efimero_y_sirve_la_pagina(servidor):
    # PUERTO 0: el que salga, pero nunca uno de los que ya estan tomados en
    # este equipo (8080 lo ocupa ademas tailscaled en sus interfaces).
    assert servidor["puerto"] > 0
    assert servidor["puerto"] not in (8080, 8765, 8766, 8777, 8899)
    assert servidor["base"] == "http://127.0.0.1:%d" % servidor["puerto"]
    assert servidor["token"] in servidor["url"]

    codigo, cabeceras, cuerpo = _pedir(servidor["puerto"], "/",
                                       token=servidor["token"])
    assert codigo == 200
    assert "text/html" in cabeceras
    assert "nosniff" in cabeceras
    assert b"Cuaderno en vivo" in cuerpo
    # El placeholder trae el SSE cableado con el token: es lo que demuestra a
    # mano que el transporte va antes de que exista la pagina de verdad.
    assert b"EventSource" in cuerpo
    assert servidor["token"].encode() in cuerpo


def test_arrancar_dos_veces_devuelve_el_mismo_servidor(servidor):
    otro = sv.arrancar()
    assert otro["puerto"] == servidor["puerto"]
    assert otro["token"] == servidor["token"]
    assert otro["nuevo"] is False


def test_solo_escucha_en_localhost():
    with pytest.raises(ValueError):
        sv.crear_server(host="0.0.0.0")


# -- el guardia ---------------------------------------------------------------

def test_sin_token_403(servidor):
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/")
    assert codigo == 403
    assert b"token" in cuerpo


def test_token_ajeno_403(servidor):
    codigo, _, _ = _pedir(servidor["puerto"], "/", token="no-es-el-token")
    assert codigo == 403


def test_origen_ajeno_403(servidor):
    """Con el token BUENO: lo que se rechaza es el Origin (DNS rebinding)."""
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/",
                               token=servidor["token"],
                               origin="http://cuaderno.ejemplo.com")
    assert codigo == 403
    assert b"origen" in cuerpo


def test_host_ajeno_403(servidor):
    codigo, _, _ = _pedir(servidor["puerto"], "/", token=servidor["token"],
                          host="cuaderno.ejemplo.com")
    assert codigo == 403


def test_el_403_no_rearma_el_reloj_de_ocio(servidor):
    """El auto-apagado promete que sin credencial no se mantiene vivo esto."""
    peticiones = sv.estado()["peticiones"]
    _pedir(servidor["puerto"], "/")                       # sin token
    _pedir(servidor["puerto"], "/", token="basura")
    assert sv.estado()["peticiones"] == peticiones


@pytest.mark.parametrize("como", ["query", "cabecera"])
def test_token_con_bytes_no_ascii_da_403_y_no_500(servidor, como):
    """El fallo YA PAGADO en el editor de flujos, aqui con un test.

    `secrets.compare_digest` sobre `str` lanza `TypeError` en cuanto hay un
    caracter no-ASCII. Como las cabeceras se decodifican latin-1 y la query se
    desescapa a `str`, un solo byte >127 en el `?t=` tumbaba el guardia ANTES
    de responder. Por eso `_token_ok` compara EN BYTES.

    Que discrimina: quitando el `.encode(...)` de `_token_ok` esto deja de ser
    403 y pasa a ser el 500 de `_fallo` con el TypeError dentro, o sea el
    guardia reventando en vez de negar.
    """
    if como == "query":
        codigo, _, cuerpo = _pedir(servidor["puerto"], "/?t=%C3%A9%80")
    else:
        # El byte >127 va ESCAPADO para que el fichero siga siendo ASCII
        # puro: lo que se prueba es lo que llega por el socket, y eso no
        # cambia por como se teclee aqui.
        codigo, _, cuerpo = _pedir(servidor["puerto"], "/",
                                   token="tok-\u00e9")
    assert codigo == 403, (codigo, cuerpo[:200])
    assert b"token" in cuerpo
    assert b"TypeError" not in cuerpo


def test_el_favicon_se_sirve_antes_del_guardia_y_no_cuenta(servidor):
    """204 vacio SIN token, a proposito: no filtra un byte y evita llenar la
    consola del navegador de 403 que no son del duenio. Y como va ANTES del
    guardia, tampoco puede rearmar el reloj del auto-apagado.
    """
    peticiones = sv.estado()["peticiones"]
    codigo, cabeceras, cuerpo = _pedir(servidor["puerto"], "/favicon.ico")
    assert codigo == 204
    assert cuerpo == b""
    assert "image/x-icon" in cabeceras
    assert sv.estado()["peticiones"] == peticiones


def test_post_sin_token_403_antes_del_motivo(servidor):
    """El 404 explicativo del POST va DETRAS del guardia: sin credencial no se
    contesta nada, ni siquiera para explicar que ruta si escribe."""
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/estado", metodo="POST")
    assert codigo == 403
    assert b"accion" not in cuerpo


def test_post_a_otra_ruta_devuelve_404_con_motivo(servidor):
    """Un 404 mudo no se distingue de una ruta que nadie cableo: el motivo
    dice cual es la puerta de escritura que SI existe."""
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/estado",
                               token=servidor["token"], metodo="POST")
    assert codigo == 404
    assert b"/accion" in cuerpo


# -- la puerta de escritura: POST /accion -------------------------------------
#
# Aqui esta LA PROMESA DEL PRODUCTO: "la IA escribe y yo corrijo encima; lo que
# yo toco queda fijado y la IA no lo pisa". Todo lo de abajo se comprueba
# RELEYENDO EL DISCO con `documento.abrir`, no mirando la respuesta HTTP: una
# puerta que contesta 200 y no guarda nada es exactamente el fallo que estos
# tests existen para cazar.


@pytest.fixture
def guardar(servidor):
    """`POST /accion` con el token puesto. Devuelve (codigo, dict)."""
    def _hacer(cuerpo, **kw):
        kw.setdefault("token", servidor["token"])
        codigo, _, crudo = _postear(servidor["puerto"], cuerpo, **kw)
        return codigo, _json_de(crudo)
    return _hacer


def _doc():
    from cognia.clases import documento
    return documento


def test_guardar_de_verdad_y_releerlo_del_disco(guardar):
    """Que discrimina: con el `do_POST` viejo esto era un 404 'SOLO LECTURA' y
    el disco se quedaba vacio -- que es justo lo que hacia la pagina."""
    codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                         "tipo": "parrafo",
                         "texto": "El MRU es v = e/t"})
    assert codigo == 200, j
    assert j["ok"] is True
    bid = j["id"]

    # EL DISCO, que es lo unico que sobrevive al navegador.
    doc = _doc().abrir("Fisica", crear=False)
    assert [b.id for b in doc.bloques] == [bid]
    assert doc.bloque(bid).texto == "El MRU es v = e/t"
    # Y la respuesta trae el estado nuevo, para que la pagina no tenga que
    # pedirlo aparte.
    assert [b["id"] for b in j["bloques"]] == [bid]
    assert j["materia"] == "Fisica"


def test_la_materia_sin_documento_se_crea_al_escribir(guardar):
    """Requisito 7: el primer bloque de una materia nueva no puede fallar."""
    assert "Latin" not in _doc().documentos()
    codigo, j = guardar({"accion": "aniadir", "materia": "Latin",
                         "tipo": "titulo", "texto": "Declinaciones"})
    assert codigo == 200, j
    assert "Latin" in _doc().documentos()
    bloques = _doc().abrir("Latin", crear=False).bloques
    assert bloques[0].texto == "Declinaciones"


def test_lo_que_el_duenio_toca_queda_fijado_y_la_ia_no_lo_pisa(guardar):
    """LA REGLA DE ORO, de punta a punta y por la puerta HTTP.

    Tres cosas en un solo test porque son UNA sola promesa: lo que el duenio
    escribe nace fijado, la IA no lo reescribe, y el duenio SI puede volver a
    corregirlo cuantas veces quiera.
    """
    doc = _doc()
    codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                         "tipo": "parrafo", "texto": "OJO: el profe dijo X"})
    assert codigo == 200, j
    bid = j["id"]
    bloque = doc.abrir("Fisica", crear=False).bloque(bid)
    assert bloque.fijado is True and bloque.origen == "duenio"

    # La IA lo intenta y se le respeta el bloque (informe, no excepcion).
    informe = doc.escribir_ia("Fisica", bid, texto="LA IA LO PISA")
    assert informe["ok"] is False
    assert doc.abrir("Fisica", crear=False).bloque(bid).texto == \
        "OJO: el profe dijo X"
    assert any(r.get("id") == bid for r in doc.respetados("Fisica"))

    # El duenio si: la correccion entra por la puerta del DUENIO.
    codigo, j = guardar({"accion": "editar", "materia": "Fisica", "id": bid,
                         "texto": "OJO: el profe dijo Y"})
    assert codigo == 200, j
    vuelto = doc.abrir("Fisica", crear=False).bloque(bid)
    assert vuelto.texto == "OJO: el profe dijo Y"
    assert vuelto.fijado is True


def test_mover_borrar_fijar_y_cambiar_tipo_llegan_al_disco(guardar):
    """Las seis operaciones del contrato, comprobadas en el diario."""
    doc = _doc()
    ids = []
    for texto in ("uno", "dos", "tres"):
        codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                             "tipo": "parrafo", "texto": texto})
        assert codigo == 200, j
        ids.append(j["id"])

    assert guardar({"accion": "mover", "materia": "Fisica", "id": ids[2],
                    "al_principio": True})[0] == 200
    assert [b.id for b in doc.abrir("Fisica", crear=False).bloques] == \
        [ids[2], ids[0], ids[1]]

    assert guardar({"accion": "borrar", "materia": "Fisica",
                    "id": ids[1]})[0] == 200
    assert doc.abrir("Fisica", crear=False).bloque(ids[1]) is None

    assert guardar({"accion": "fijar", "materia": "Fisica", "id": ids[0],
                    "valor": False})[0] == 200
    assert doc.abrir("Fisica", crear=False).bloque(ids[0]).fijado is False

    codigo, j = guardar({"accion": "tipo", "materia": "Fisica", "id": ids[0],
                         "tipo": "cita"})
    assert codigo == 200, j
    # 'tipo' se hace aniadiendo y borrando: el id cambia, el texto no.
    bloques = doc.abrir("Fisica", crear=False).bloques
    assert [b.tipo for b in bloques if b.texto == "uno"] == ["cita"]


def test_un_id_inventado_da_error_legible_y_no_una_traza(guardar):
    """Requisito 3: dato invalido -> mensaje para la pantalla, nunca 500.

    Que discrimina: sin `_revisar_documento`, el manejador contesta 'no hay
    ningun bloque' pero SIN decir cuales hay -- y el fallo tipico es tener
    abierta otra materia.
    """
    codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                         "tipo": "parrafo", "texto": "uno"})
    bid = j["id"]
    codigo, j = guardar({"accion": "editar", "materia": "Fisica",
                         "id": "b9999", "texto": "x"})
    assert codigo == 400
    assert j["ok"] is False
    assert "b9999" in j["error"] and bid in j["error"]
    assert "Traceback" not in j["error"] and "Error" not in j["error"]
    # Y no se toco nada.
    assert _doc().abrir("Fisica", crear=False).bloque(bid).texto == "uno"


def test_un_tipo_fuera_de_la_lista_cerrada_se_niega(guardar):
    """Requisito 3: el tipo se valida contra `documento.TIPOS`.

    Un tipo inventado se guardaria en el diario y luego no lo sabria pintar
    nadie: texto que el duenio ve escribirse y despues no encuentra.

    LA SEGUNDA MITAD ES LA QUE DISCRIMINA. `documento.py` tambien rechaza el
    tipo raro, asi que con el manejador de la casa este test pasaria igual sin
    la comprobacion de la puerta. Lo que se prueba aqui es que la PUERTA no
    depende de la diligencia de su manejador: con uno que lo aceptaria todo,
    el dato invalido no llega a llamarlo.
    """
    codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                         "tipo": "cancion", "texto": "x"})
    assert codigo == 400
    assert "cancion" in j["error"] and "parrafo" in j["error"]
    assert _doc().abrir("Fisica", crear=False).bloques == []

    llamadas = []
    sv.fijar_acciones(lambda p: llamadas.append(p) or {"ok": True})
    try:
        codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                             "tipo": "cancion", "texto": "x"})
        assert codigo == 400, j
        assert llamadas == []
        # Y con un tipo de la lista, ese mismo manejador SI se llama: lo que
        # para la peticion es el tipo, no la puerta entera.
        assert guardar({"accion": "aniadir", "materia": "Fisica",
                        "tipo": "cita", "texto": "x"})[0] == 200
        assert len(llamadas) == 1
    finally:
        sv.fijar_acciones(None)


def test_una_materia_que_no_se_resuelve_lo_dice(guardar):
    """Requisito 7. `almacen._seguro('///')` es 'sin-nombre': sin esta
    comprobacion se escribiria en una carpeta que el duenio no pidio y NADIE
    lo diria."""
    codigo, j = guardar({"accion": "aniadir", "materia": "///",
                         "tipo": "parrafo", "texto": "x"})
    assert codigo == 400
    assert "///" in j["error"]
    assert not (alm.raiz() / "documentos" / "sin-nombre").exists()


def test_una_accion_desconocida_se_niega_con_la_lista(guardar):
    codigo, j = guardar({"accion": "formatear_el_disco", "materia": "Fisica"})
    assert codigo == 400
    assert "formatear_el_disco" in j["error"]


def test_el_cuerpo_tiene_que_ser_un_objeto_json(guardar):
    codigo, j = guardar(None, crudo=b"[1, 2, 3]")
    assert codigo == 400
    assert "objeto JSON" in j["error"]
    codigo, j = guardar(None, crudo=b"esto no es json")
    assert codigo == 400
    assert "JSON" in j["error"]


def test_el_cuerpo_exige_content_type_json(guardar):
    """Segundo cerrojo contra CSRF: un formulario de otro sitio solo puede
    mandar tres Content-Type, y ninguno es este (el token ya lo paraba; esto
    es el cinturon del tirante)."""
    codigo, j = guardar({"accion": "aniadir", "materia": "Fisica"},
                        tipo="application/x-www-form-urlencoded")
    assert codigo == 415
    assert "application/json" in j["error"]


def test_sin_content_length_no_se_lee_el_cuerpo(guardar):
    codigo, j = guardar({"accion": "aniadir"}, largo="sin")
    assert codigo == 411
    assert "Content-Length" in j["error"]
    codigo, j = guardar({"accion": "aniadir"}, transfer="chunked")
    assert codigo == 411
    assert "chunked" in j["error"]


def test_un_cuerpo_gigante_se_rechaza_por_la_cabecera(servidor, monkeypatch):
    """Requisito 2: un cuerpo enorme no puede tumbar el proceso que esta
    GRABANDO la clase del duenio.

    Se manda un Content-Length de 40 MB y NI UN BYTE de cuerpo: si el servidor
    contesta 413 sin quedarse esperando, es que rechazo por lo DECLARADO, o
    sea sin reservar memoria. Que discrimina: sin el tope, el handler se queda
    bloqueado leyendo 40 MB que no van a llegar hasta que venza el timeout.
    """
    monkeypatch.setattr(sv, "TOPE_CUERPO", 4096)
    t0 = time.time()
    codigo, _, crudo = _postear(servidor["puerto"], None, crudo=b"",
                                largo=40 * 1024 * 1024,
                                token=servidor["token"], timeout=10.0)
    assert codigo == 413
    j = _json_de(crudo)
    assert "4096" in j["error"]
    assert time.time() - t0 < 5.0     # no se quedo esperando el cuerpo
    # Y el servidor sigue en pie y sirviendo.
    assert _pedir(servidor["puerto"], "/estado",
                  token=servidor["token"])[0] == 200


def test_escribir_sin_token_403_y_sin_tocar_el_disco(servidor):
    """Esto ya no es un mirador: un POST sin credencial no escribe nada."""
    cuerpo = {"accion": "aniadir", "materia": "Fisica", "tipo": "parrafo",
              "texto": "ENTRO SIN LLAMAR"}
    codigo, _, crudo = _postear(servidor["puerto"], cuerpo)
    assert codigo == 403
    assert b"token" in crudo
    assert _doc().abrir("Fisica", crear=False).bloques == []


def test_escribir_con_origen_ajeno_403_y_sin_tocar_el_disco(servidor):
    """DNS rebinding: un dominio del atacante que resuelva a 127.0.0.1 llega
    con SU Origin. Con el token BUENO, lo que para la escritura es el origen.
    """
    cuerpo = {"accion": "aniadir", "materia": "Fisica", "tipo": "parrafo",
              "texto": "ENTRO DESDE OTRO SITIO"}
    codigo, _, crudo = _postear(servidor["puerto"], cuerpo,
                                token=servidor["token"],
                                origin="http://cuaderno.ejemplo.com")
    assert codigo == 403
    assert b"origen" in crudo
    assert _doc().abrir("Fisica", crear=False).bloques == []

    codigo, _, crudo = _postear(servidor["puerto"], cuerpo,
                                token=servidor["token"],
                                host="cuaderno.ejemplo.com")
    assert codigo == 403
    assert _doc().abrir("Fisica", crear=False).bloques == []


def test_el_403_de_escritura_no_rearma_el_reloj_de_ocio(servidor):
    peticiones = sv.estado()["peticiones"]
    _postear(servidor["puerto"], {"accion": "aniadir", "materia": "Fisica"})
    assert sv.estado()["peticiones"] == peticiones


def test_un_manejador_inyectado_recibe_la_peticion(servidor):
    """El gancho `fijar_acciones`: es lo que deja probar el transporte sin
    arrastrar la pagina, y lo que permitira otro consumidor sin tocar esto."""
    visto = []

    def manejador(peticion):
        visto.append(peticion)
        return {"ok": True, "eco": peticion.get("texto")}

    sv.fijar_acciones(manejador)
    try:
        codigo, _, crudo = _postear(servidor["puerto"],
                                    {"accion": "buscar_imagenes",
                                     "consulta": "poleas"},
                                    token=servidor["token"])
        assert codigo == 200
        assert visto and visto[0]["consulta"] == "poleas"
        assert sv.estado()["escritura"]["manejador_inyectado"] is True
    finally:
        sv.fijar_acciones(None)


def test_un_manejador_que_revienta_no_devuelve_la_traza(servidor):
    def manejador(peticion):
        raise RuntimeError("me he roto por dentro")

    sv.fijar_acciones(manejador)
    try:
        codigo, _, crudo = _postear(servidor["puerto"],
                                    {"accion": "buscar_imagenes"},
                                    token=servidor["token"])
        assert codigo == 500
        j = _json_de(crudo)
        assert "me he roto por dentro" in j["error"]
        assert "Traceback" not in j["error"]
        # Y queda anotado en la puerta de diagnostico.
        assert "buscar_imagenes" in sv.estado()["ultimo_error"]["motivo"]
    finally:
        sv.fijar_acciones(None)


def test_fijar_acciones_rechaza_lo_que_no_se_puede_llamar():
    with pytest.raises(TypeError):
        sv.fijar_acciones("aplicar_accion")


def test_la_pagina_recibe_la_ruta_de_escritura_y_su_identificador(servidor):
    """La pagina no sabe nada nuevo: las dos URLs le llegan ya montadas.

    Que discrimina: sin el `cli` en ctx["accion"] y en ctx["eventos"], la
    pagina no puede decir quien escribe y el eco vuelve al autor.
    """
    vistos = []

    def render(ctx):
        vistos.append(dict(ctx))
        return "<html>ok</html>"

    sv.fijar_pagina(render)
    _pedir(servidor["puerto"], "/?materia=Fisica", token=servidor["token"])
    _pedir(servidor["puerto"], "/", token=servidor["token"])
    assert len(vistos) == 2
    uno, dos = vistos
    assert uno["accion"].startswith(sv.RUTA_ACCION + "?t=")
    assert "cli=" + uno["cliente"] in uno["accion"]
    assert "cli=" + uno["cliente"] in uno["eventos"]
    # CADA CARGA su identificador: dos pestanias del mismo navegador tienen
    # que poder distinguirse (una cookie no valdria: la comparten).
    assert uno["cliente"] != dos["cliente"]
    # Y la query viaja, que es de donde la pagina saca `?materia=`.
    assert uno["query"].get("materia") == "Fisica"


def test_el_autor_no_recibe_su_propio_cambio_pero_la_otra_pestania_si(
        servidor, guardar):
    """EL ECO, que es la diferencia entre corregir y pelearse con la pagina.

    Que discrimina: sin la ventana de `_AUTOR` en `_desde_el_bus`, el texto
    aparece TAMBIEN en el flujo del que lo escribio, y su pagina repinta el
    bloque que esta corrigiendo.

    La segunda mitad del test es la que impide el falso verde: se emite un
    evento que NO es del autor y se exige que ese si le llegue. Sin eso, un
    servidor que no mandara nada a nadie pasaria igual.
    """
    autor = _Espia(servidor["puerto"], servidor["token"], cli="pestania-uno")
    otra = _Espia(servidor["puerto"], servidor["token"], cli="pestania-dos")
    try:
        assert _esperar_clientes(2)
        omitidos0 = sv.estado()["omitidos_autor"]
        codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                             "tipo": "parrafo", "texto": "PIZARRA-ECO"},
                            cliente="pestania-uno")
        assert codigo == 200, j

        assert otra.esperar("PIZARRA-ECO", 10.0)
        assert "PIZARRA-ECO" not in autor.texto()
        assert sv.estado()["omitidos_autor"] > omitidos0

        # La otra pestania se entera ADEMAS por el evento de la accion, que
        # dice que paso a nivel de accion y no de linea de diario.
        assert otra.esperar("clase.accion", 5.0)

        # Y el flujo del autor sigue vivo: lo que no es suyo si le llega.
        alm.apendar(alm.dir_jornada("2026-08-31") / alm.ENTRADAS,
                    {"t": 1.0, "texto": "DESDE-LA-CLASE"})
        assert autor.esperar("DESDE-LA-CLASE", 10.0)
        assert "PIZARRA-ECO" not in autor.texto()
    finally:
        autor.cerrar()
        otra.cerrar()


def test_una_pestania_sin_identificador_lo_recibe_todo(servidor, guardar):
    """Un cliente que no dice quien es (un curl, el placeholder viejo) recibe
    hasta su propio eco: suprimirle algo que quiza necesita seria peor."""
    espia = _Espia(servidor["puerto"], servidor["token"])
    try:
        assert _esperar_clientes(1)
        codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                             "tipo": "parrafo", "texto": "SIN-PESTANIA"})
        assert codigo == 200, j
        assert espia.esperar("SIN-PESTANIA", 10.0)
    finally:
        espia.cerrar()


def test_lo_que_escribe_la_ia_llega_a_todas_las_pestanias(servidor, guardar):
    """La supresion es SOLO para el hilo que atiende ese POST.

    El refinado de la IA escribe desde otro hilo y su cambio tiene que llegar
    a todo el mundo, incluida la pestania que acaba de guardar. Que discrimina:
    con un global en vez de un `threading.local`, el autor se quedaria sordo.
    """
    autor = _Espia(servidor["puerto"], servidor["token"], cli="pestania-uno")
    try:
        assert _esperar_clientes(1)
        codigo, j = guardar({"accion": "aniadir", "materia": "Fisica",
                             "tipo": "parrafo", "texto": "MIO"},
                            cliente="pestania-uno")
        assert codigo == 200, j
        bid = j["id"]
        # Desfijar para que la IA pueda escribir encima, y que escriba.
        assert guardar({"accion": "fijar", "materia": "Fisica", "id": bid,
                        "valor": False}, cliente="pestania-uno")[0] == 200
        assert _doc().escribir_ia("Fisica", bid,
                                  texto="LO-ESCRIBE-LA-IA")["ok"] is True
        assert autor.esperar("LO-ESCRIBE-LA-IA", 10.0)
    finally:
        autor.cerrar()


def test_el_estado_publica_la_puerta_de_escritura(servidor):
    """CLAUDE.md: 'no lo cablearon' y 'se rompio' no pueden verse igual."""
    est = sv.estado()
    assert est["escritura"]["ruta"] == "/accion"
    assert est["escritura"]["tope_cuerpo"] == sv.TOPE_CUERPO
    assert "editar" in est["escritura"]["acciones"]
    # Los contadores viven en el MODULO y sobreviven a `parar()` -- es lo que
    # deja mirar que paso despues de un apagado --, asi que se compara el
    # incremento y no el valor absoluto.
    antes = est["escrituras"]
    codigo, _, _ = _postear(servidor["puerto"],
                            {"accion": "aniadir", "materia": "Fisica",
                             "tipo": "parrafo", "texto": "x"},
                            token=servidor["token"])
    assert codigo == 200
    assert sv.estado()["escrituras"] == antes + 1


# -- SSE ----------------------------------------------------------------------

def test_sse_recibe_un_evento_escrito_en_disco(servidor):
    """De punta a punta: se escribe una linea con `almacen.apendar` (que hace
    fsync y emite en el bus) y tiene que salir por el socket del espectador."""
    espia = _Espia(servidor["puerto"], servidor["token"])
    try:
        assert "text/event-stream" in espia.cabeceras
        # Sin Content-Length: el cuerpo es infinito y termina al cerrar.
        assert "Content-Length" not in espia.cabeceras
        assert "no-store" in espia.cabeceras
        assert espia.esperar(": conectado", 5.0)
        assert _esperar_clientes(1)

        ruta = alm.dir_jornada("2026-08-31") / alm.ENTRADAS
        alm.apendar(ruta, {"t": 12.5, "tipo": "nota", "texto": "PIZARRA-42"})

        assert espia.esperar("PIZARRA-42", 10.0)
        texto = espia.texto()
        assert "event: clase.entrada" in texto
        assert "data: {" in texto
        # El payload llega tal cual lo pone almacen: ruta como str + registro.
        crudo = [l for l in texto.splitlines() if l.startswith("data: ")][-1]
        datos = json.loads(crudo[len("data: "):])
        assert datos["evento"] == "clase.entrada"
        assert datos["registro"]["texto"] == "PIZARRA-42"
        assert Path(datos["ruta"]) == ruta
    finally:
        espia.cerrar()


def test_sse_recibe_el_json_de_la_jornada(servidor):
    espia = _Espia(servidor["puerto"], servidor["token"])
    try:
        assert _esperar_clientes(1)
        ruta = alm.dir_jornada("2026-08-31") / alm.JORNADA
        alm.guardar_json(ruta, {"estado": "grabando", "materia": "MATES-7"})
        assert espia.esperar("MATES-7", 10.0)
        assert "event: clase.json" in espia.texto()
    finally:
        espia.cerrar()


def test_sse_manda_las_cabeceras_de_un_flujo_infinito(servidor):
    """Las tres cabeceras que hacen que esto sea un flujo y no una respuesta.

      - `Connection: close` + SIN `Content-Length`: el cuerpo termina cuando
        se cierra el socket, que es lo que corresponde a algo infinito.
      - `X-Accel-Buffering: no`: el dia que esto pase por un proxy (nginx, un
        tunel de Tailscale) sin esa cabecera el proxy acumula y el cuaderno
        "en vivo" llega a rafagas de un minuto.
      - `retry:` en el cuerpo: sin el, un servidor caido tiene al navegador
        reconectando cada 3 s.
    """
    espia = _Espia(servidor["puerto"], servidor["token"])
    try:
        assert "text/event-stream" in espia.cabeceras
        assert "Content-Length" not in espia.cabeceras
        assert "Connection: close" in espia.cabeceras
        assert "X-Accel-Buffering: no" in espia.cabeceras
        assert espia.esperar("retry: ", 5.0)
        # El comentario de apertura: es lo que dispara `onopen` en el acto en
        # vez de al primer evento real (que puede tardar media clase).
        assert ": conectado" in espia.texto()
    finally:
        espia.cerrar()


def test_un_evento_gigante_llega_recortado_con_su_ruta(servidor, monkeypatch):
    """`clase.json` lleva el JSON entero de apuntes.json. Con varios
    espectadores eso se copia N veces a N colas, dentro del hilo que graba.

    El contrato es RECORTAR conservando la ruta -- quien escucha relee el
    fichero del disco, que ya paso por fsync antes del evento -- y NO callarse.
    Que discrimina: sin el recorte de `_formatear`, el marcador de la carga
    llega entero al socket del espectador.
    """
    monkeypatch.setattr(sv, "TOPE_EVENTO", 2048)
    espia = _Espia(servidor["puerto"], servidor["token"])
    try:
        assert _esperar_clientes(1)
        ruta = str(alm.dir_jornada("2026-08-31") / alm.JORNADA)
        events.emit("clase.json", ruta=ruta,
                    datos={"carga": "NO-DEBE-VIAJAR-ENTERO" * 500})
        assert espia.esperar("recortado", 10.0)
        crudo = [l for l in espia.texto().splitlines()
                 if l.startswith("data: ")][-1]
        datos = json.loads(crudo[len("data: "):])
        assert datos["evento"] == "clase.json"
        assert datos["ruta"] == ruta          # con esto se relee del disco
        assert datos["recortado"] > 2048
        assert "NO-DEBE-VIAJAR-ENTERO" not in espia.texto()
    finally:
        espia.cerrar()


def test_sin_nadie_mirando_el_evento_ni_se_serializa(servidor):
    """"Nadie mira" tiene que costar CERO en el hilo que escribe la clase.

    `_desde_el_bus` corre dentro del `apendar` del grabador y almacen denuncia
    al suscriptor que pasa de 0,25 s: serializar un apuntes.json entero para
    no mandarlo a nadie es exactamente el trabajo que no se puede hacer ahi.
    Que discrimina: quitando el `if not _CLIENTES: return`, `enviados` sube.
    """
    assert sv.estado()["clientes"] == 0
    enviados0 = sv.estado()["enviados"]
    alm.apendar(alm.dir_jornada("2026-08-31") / alm.ENTRADAS,
                {"t": 1.0, "texto": "nadie esta mirando esto"})
    assert sv.estado()["enviados"] == enviados0


def test_sse_late_para_que_no_lo_maten(servidor, monkeypatch):
    """El latido es un comentario SSE (no dispara handlers) y es lo que impide
    que un proxy o un antivirus corte una conexion callada. Se baja a 0,2 s
    para no meter una espera de 15 s en la suite: lo que se prueba es el
    camino, no el numero."""
    monkeypatch.setattr(sv, "LATIDO_SSE_S", 0.2)
    espia = _Espia(servidor["puerto"], servidor["token"])
    try:
        assert espia.esperar(": latido", 5.0)
    finally:
        espia.cerrar()


def test_una_pestania_muerta_sale_de_la_lista_aunque_siga_la_clase(servidor):
    """Con la clase EMITIENDO encima, el que cerro tiene que irse igual.

    OJO CON LO QUE ESTE TEST *NO* PRUEBA (y por eso existe el de abajo):
    emitiendo hay DOS caminos que sacan al cliente -- el `finally` del handler
    y `_matar` cuando su cola se llena -- asi que verde aqui no demuestra el
    `finally`. Medido: borrando `finally: _desuscribir(cli)` este test sigue
    pasando. Lo que si cubre es el otro camino: que una tormenta de eventos
    contra un socket muerto termina, y no deja al reparto haciendo `_matar`
    inutiles por evento.
    """
    espia = _Espia(servidor["puerto"], servidor["token"])
    assert _esperar_clientes(1)
    espia.cerrar()
    # El handler despierta con su latido o con el error de escritura; se le da
    # margen, pero tiene que salir de la lista solo.
    fin = time.time() + 10.0
    while time.time() < fin and sv.estado()["clientes"]:
        alm.apendar(alm.dir_jornada("2026-08-31") / alm.ENTRADAS, {"t": 0})
        time.sleep(0.05)
    assert sv.estado()["clientes"] == 0


def test_sse_se_desuscribe_al_cerrar_la_pestania(servidor, monkeypatch):
    """LA FUGA DE SUSCRIPTORES, medida: N pestanias abiertas y cerradas dejan
    la lista EN CERO **sin que nadie emita nada**.

    Esta es la version que DISCRIMINA. Si se emite mientras tanto, `_matar`
    por cola llena saca al cliente aunque el `finally` no exista, y el test
    pasa por el motivo equivocado. Aqui no se emite ni un evento (y se
    comprueba: `enviados` no se mueve), asi que el UNICO codigo que puede
    sacar a esos tres clientes de la lista es
    `_eventos() -> finally: _desuscribir(cli)`.

    POR QUE IMPORTA MAS DE LO QUE PARECE. `_desde_el_bus` corre DENTRO del
    `apendar` que escribe la clase en disco, y recorre `_CLIENTES` entero por
    evento. En una sesion de cinco horas con el duenio abriendo y cerrando el
    cuaderno, una fuga aqui significa cada linea transcrita serializada y
    copiada a cientos de colas muertas en el hilo que esta grabando --
    justo el hilo que almacen denuncia si pasa de 0,25 s.
    """
    # Latido corto para que el handler despierte y descubra su socket muerto
    # en decimas en vez de en 15 s: lo que se prueba es el camino, no el numero.
    monkeypatch.setattr(sv, "LATIDO_SSE_S", 0.05)
    enviados0 = sv.estado()["enviados"]
    n = 3
    espias = [_Espia(servidor["puerto"], servidor["token"]) for _ in range(n)]
    try:
        assert _esperar_clientes(n)
        assert sv.estado()["clientes"] == n, sv.estado()
    finally:
        for espia in espias:
            espia.cerrar()

    fin = time.time() + 15.0
    while time.time() < fin and sv.estado()["clientes"]:
        time.sleep(0.02)
    assert sv.estado()["clientes"] == 0, (
        "fuga de suscriptores: quedan %d colas de pestanias cerradas"
        % sv.estado()["clientes"])
    # Y no se colo ni un evento: lo que los saco fue el `finally`, no `_matar`
    # por cola llena. Sin esta linea el test volveria a pasar por el motivo
    # equivocado el dia que alguien meta una emision aqui arriba.
    assert sv.estado()["enviados"] == enviados0


def test_cliente_lento_se_desconecta_sin_frenar_al_escritor(servidor,
                                                            monkeypatch):
    """EL CASO QUE JUSTIFICA UNA COLA POR CLIENTE.

    El lento se conecta y deja de leer. El escritor (aqui el hilo del test,
    que es el papel que hace el grabador) sigue emitiendo: no puede quedarse
    esperando a nadie, el rapido tiene que seguir recibiendo, y al lento hay
    que echarlo CONTANDOLO.

    El rapido se conecta ANTES de encoger `TOPE_COLA`: la cola se dimensiona
    al suscribirse, asi que cada uno queda con la suya -- que es justo la
    propiedad que se esta probando.
    """
    rapido = _Espia(servidor["puerto"], servidor["token"])
    monkeypatch.setattr(sv, "TOPE_COLA", 4)
    lento = _Espia(servidor["puerto"], servidor["token"], rcvbuf=2048,
                   drenar=False)
    try:
        assert _esperar_clientes(2)
        lentos0 = sv.estado()["desconectados_lentos"]
        carga = "x" * 60000
        ruta = str(alm.dir_jornada("2026-08-31") / alm.ENTRADAS)
        t0 = time.perf_counter()
        for i in range(60):
            events.emit("clase.entrada", ruta=ruta,
                        registro={"i": i, "carga": carga})
            if sv.estado()["desconectados_lentos"] > lentos0:
                break
        tardado = time.perf_counter() - t0

        assert sv.estado()["desconectados_lentos"] > lentos0, (
            "al cliente lento no se le echo: la cola no se lleno")
        # El escritor NO se bloqueo. Si el reparto esperara al socket del
        # lento, esto tardaria lo que el timeout del socket (15 s) por evento.
        assert tardado < 10.0, "el reparto freno al hilo que escribe: %.1f s" % tardado

        # Y el rapido sigue en el directo despues de la tormenta.
        events.emit("clase.entrada", ruta=ruta,
                    registro={"marca": "SIGO-AQUI"})
        assert rapido.esperar("SIGO-AQUI", 10.0)
        assert sv.estado()["ultimo_error"]["donde"] == \
            "clases.servidor_vivo.cliente_lento"
    finally:
        lento.cerrar()
        rapido.cerrar()


# -- adjuntos -----------------------------------------------------------------

def _con_adjunto(jornada="2026-08-31"):
    """Deja un adjunto real en la jornada y devuelve (jornada, nombre)."""
    origen = alm.raiz() / "pizarra.png"
    origen.write_bytes(b"\x89PNG\r\n\x1a\nCONTENIDO-DE-LA-PIZARRA")
    return jornada, alm.copiar_adjunto(jornada, origen, prefijo="img")


def test_adjunto_se_sirve_por_url(servidor):
    jornada, nombre = _con_adjunto()
    codigo, cabeceras, cuerpo = _pedir(
        servidor["puerto"], "/adj/" + jornada + "/" + nombre,
        token=servidor["token"])
    assert codigo == 200
    assert "image/png" in cabeceras
    assert "nosniff" in cabeceras
    assert b"CONTENIDO-DE-LA-PIZARRA" in cuerpo


def test_adjunto_de_tipo_raro_se_sirve_como_descarga(servidor):
    """Un .html metido a mano en adjuntos/ correria con el ORIGEN de este
    servidor, que es el origen que tiene el token. Se sirve como descarga."""
    jornada = "2026-08-31"
    destino = alm.dir_jornada(jornada) / alm.DIR_ADJUNTOS / "trampa.html"
    destino.write_bytes(b"<script>robar()</script>")
    codigo, cabeceras, _ = _pedir(servidor["puerto"],
                                  "/adj/" + jornada + "/trampa.html",
                                  token=servidor["token"])
    assert codigo == 200
    assert "application/octet-stream" in cabeceras
    assert "attachment" in cabeceras
    assert "text/html" not in cabeceras


def test_adjunto_inexistente_404(servidor):
    codigo, _, _ = _pedir(servidor["puerto"], "/adj/2026-08-31/no-existe.png",
                          token=servidor["token"])
    assert codigo == 404


@pytest.mark.parametrize("cola", [
    "..%2f..%2fjornada.json",          # ../../jornada.json escapado
    "..%2F..%2Fjornada.json",          # el mismo en mayusculas
    "..%5c..%5cjornada.json",          # ..\..\ de Windows
    "%2e%2e%2f%2e%2e%2fjornada.json",  # tambien los puntos escapados
    "..%2f..%2f..%2fcuaderno.json",    # dos niveles mas arriba
])
def test_escape_de_ruta_rechazado(servidor, cola):
    """Ni un solo byte del fichero de al lado.

    `jornada.json` vive UN nivel por encima de `adjuntos/`, asi que es el
    objetivo natural de un `../`. Se le mete un marcador y se exige que no
    salga por la ruta de adjuntos pase lo que pase.
    """
    jornada = "2026-08-31"
    secreto = alm.dir_jornada(jornada) / alm.JORNADA
    alm.guardar_json(secreto, {"materia": "NO-DEBE-SALIR-DE-AQUI"})
    (alm.raiz() / "cuaderno.json").write_text(
        json.dumps({"x": "NO-DEBE-SALIR-DE-AQUI"}), encoding="utf-8")

    codigo, _, cuerpo = _pedir(servidor["puerto"],
                               "/adj/" + jornada + "/" + cola,
                               token=servidor["token"])
    assert codigo in (403, 404), codigo
    assert b"NO-DEBE-SALIR-DE-AQUI" not in cuerpo


def test_escape_con_barras_de_verdad_rechazado(servidor):
    """Sin escapar: son mas tramos, y un adjunto no tiene subcarpetas."""
    jornada = "2026-08-31"
    alm.guardar_json(alm.dir_jornada(jornada) / alm.JORNADA,
                     {"materia": "NO-DEBE-SALIR-DE-AQUI"})
    codigo, _, cuerpo = _pedir(servidor["puerto"],
                               "/adj/" + jornada + "/../../jornada.json",
                               token=servidor["token"])
    assert codigo in (403, 404)
    assert b"NO-DEBE-SALIR-DE-AQUI" not in cuerpo


def test_adjunto_no_fabrica_carpetas_de_jornada(servidor):
    """Un GET curioso no puede escribir en el cuaderno: este servidor lee.

    (Por eso no se usa `almacen.ruta_adjunto`, que pasa por `dir_jornada` y
    esa SI crea audio/ y adjuntos/.)
    """
    _pedir(servidor["puerto"], "/adj/jornada-inventada/x.png",
           token=servidor["token"])
    assert not (alm.raiz() / "jornadas" / "jornada-inventada").exists()


def test_adjuntos_exigen_token(servidor):
    jornada, nombre = _con_adjunto()
    codigo, _, cuerpo = _pedir(servidor["puerto"],
                               "/adj/" + jornada + "/" + nombre)
    assert codigo == 403
    assert b"CONTENIDO-DE-LA-PIZARRA" not in cuerpo


# -- /estado ------------------------------------------------------------------

def test_estado_devuelve_json_y_no_filtra_el_token(servidor):
    codigo, cabeceras, cuerpo = _pedir(servidor["puerto"], "/estado",
                                       token=servidor["token"])
    assert codigo == 200
    assert "application/json" in cabeceras
    datos = json.loads(cuerpo.decode("utf-8"))
    # La forma de jornada.estado() (o el aviso de por que no se pudo leer).
    assert "grabando" in datos or datos.get("ok") is False
    assert datos["servidor"]["vivo"] is True
    assert datos["servidor"]["puerto"] == servidor["puerto"]
    # Un /estado acaba pegado en un reporte de fallo: el token no sale.
    assert servidor["token"] not in cuerpo.decode("utf-8")


# -- la pagina inyectada ------------------------------------------------------

def test_gancho_de_pagina(servidor):
    sv.fijar_pagina(lambda ctx: "<h1>PAGINA DE VERDAD</h1>" + ctx["eventos"])
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/",
                               token=servidor["token"])
    assert codigo == 200
    assert b"PAGINA DE VERDAD" in cuerpo
    # Las URLs llegan montadas con el token: la pagina no tiene que saber
    # como viaja la credencial.
    assert b"/eventos?t=" in cuerpo
    assert sv.estado()["pagina_inyectada"] is True


def test_index_html_sirve_la_misma_pagina_que_la_raiz(servidor):
    """El navegador que resuelve `/` a `/index.html` (o un enlace escrito a
    mano) tiene que llegar al cuaderno, no a un 404."""
    sv.fijar_pagina(lambda ctx: "<h1>PAGINA DE VERDAD</h1>")
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/index.html",
                               token=servidor["token"])
    assert codigo == 200
    assert b"PAGINA DE VERDAD" in cuerpo


def test_pagina_rota_no_tumba_el_transporte(servidor):
    """Una pagina que revienta tiene que dar placeholder + AVISO, no un 500:
    "no hay cuaderno" y "el cuaderno esta roto" no pueden verse igual."""
    def _bomba(ctx):
        raise RuntimeError("me falta un dato")

    sv.fijar_pagina(_bomba)
    codigo, _, cuerpo = _pedir(servidor["puerto"], "/",
                               token=servidor["token"])
    assert codigo == 200
    assert b"placeholder" in cuerpo
    assert "me falta un dato" in sv.estado()["aviso"]
    assert sv.estado()["ultimo_error"]["donde"] == \
        "clases.servidor_vivo.pagina"


def test_fijar_pagina_rechaza_lo_que_no_se_puede_llamar():
    with pytest.raises(TypeError):
        sv.fijar_pagina(3)


# -- handshake ----------------------------------------------------------------

def test_handshake_publica_puerto_y_token():
    recibidos = []
    events.subscribe("clase.json", recibidos.append)
    try:
        datos_arranque = sv.arrancar()
        ruta = Path(datos_arranque["handshake"])
        assert ruta.parent == alm.raiz()
        assert ruta.name == sv.HANDSHAKE
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["puerto"] == datos_arranque["puerto"]
        assert datos["token"] == datos_arranque["token"]
        assert datos["url"] == datos_arranque["url"]
        # NO se escribe con almacen.guardar_json: si se hiciera, el servidor
        # se anunciaria a si mismo por su propio SSE como si fuera una linea
        # del cuaderno (el evento mentiria sobre su origen).
        assert recibidos == []
    finally:
        events.unsubscribe("clase.json", recibidos.append)


def test_parar_borra_el_handshake():
    datos = sv.arrancar()
    ruta = Path(datos["handshake"])
    assert ruta.exists()
    sv.parar()
    assert not ruta.exists()
    # Un handshake que sobrevive manda al widget a un puerto muerto.
    assert sv.estado()["vivo"] is False


# -- apagado ------------------------------------------------------------------

def test_parar_no_deja_hilos_vivos():
    """"Cerrar de verdad" es esto y no `shutdown()` a secas.

    Hay tres clases de hilo que sobrevivirian a un apagado descuidado: el del
    bucle, el del vigia (que dormiria sus 20 s) y el de CADA SSE (bloqueado en
    su cola 15 s, o escribiendo). Se levantan los tres y se exige que ninguno
    quede vivo.
    """
    antes = set(threading.enumerate())
    datos = sv.arrancar()
    espia = _Espia(datos["puerto"], datos["token"])
    try:
        assert _esperar_clientes(1)
        codigo, _, _ = _pedir(datos["puerto"], "/estado",
                              token=datos["token"])
        assert codigo == 200

        sv.parar()

        fin = time.time() + 10.0
        nuevos = []
        while time.time() < fin:
            nuevos = [h for h in threading.enumerate()
                      if h not in antes and h.is_alive()
                      and h is not threading.current_thread()]
            if not nuevos:
                break
            time.sleep(0.05)
        assert not nuevos, [h.name for h in nuevos]
        assert sv.estado()["clientes"] == 0
    finally:
        espia.cerrar()


def test_parar_desengancha_el_bus():
    """Un servidor parado no puede seguir escuchando la clase: el suscriptor
    corre en el hilo del grabador."""
    from cognia.events import get_bus
    sv.arrancar()
    assert sv._desde_el_bus in get_bus()._subs.get("clase.entrada", [])
    sv.parar()
    assert sv._desde_el_bus not in get_bus()._subs.get("clase.entrada", [])


def test_parar_es_idempotente():
    sv.arrancar()
    sv.parar()
    sv.parar()          # sin servidor no es un error
    assert sv.estado()["vivo"] is False


def test_parar_sobre_un_servidor_sin_bucle_no_cuelga():
    """`shutdown()` sobre un servidor con bind y SIN bucle espera un Event que
    solo pone el `finally` de `serve_forever()`: para siempre. Y esto corre
    tambien desde el atexit, donde ni Ctrl-C sirve."""
    srv = sv.crear_server()
    t0 = time.perf_counter()
    # El tope se baja para no meter una espera de 5 s en la suite: lo que se
    # prueba es que `_apagar` ACOTA la espera y cierra el socket igual, no el
    # numero concreto del tope.
    sv._apagar(srv, timeout_s=0.5)
    assert time.perf_counter() - t0 < 3.0
    assert srv.fileno() == -1


# -- el vigia de ocio ---------------------------------------------------------
#
# El vigia es el unico subsistema del fichero que decide SOLO apagar el
# cuaderno del duenio, y hasta ahora no lo ejecutaba ni una linea de test: sus
# numeros de produccion son 20 s de latido y VEINTE MINUTOS de ocio, asi que
# el test mas barato posible costaba un minuto de suite. Por eso `_vigilante`
# acepta `latido_s` y `ocio_s`: se prueba EL MISMO codigo en milisegundos.

def _vigia_de_prueba(srv, *, ocio_s=0.05, latido_s=0.01):
    """Arranca el vigia real sobre `srv` con los tiempos en milisegundos."""
    hilo = threading.Thread(target=sv._vigilante, args=(srv,),
                            kwargs={"latido_s": latido_s, "ocio_s": ocio_s},
                            name="vigia-de-prueba", daemon=True)
    hilo.start()
    return hilo


def test_el_vigia_apaga_el_cuaderno_solo_tras_el_ocio(servidor):
    """La primera mitad del contrato: sin nadie mirando, se apaga SOLO.

    Y se comprueba que apaga DE VERDAD -- llamando a `parar()`, no a un
    `shutdown()` a medias -- exigiendo tambien que el handshake desaparezca:
    un handshake que sobrevive manda al widget contra un puerto muerto.
    """
    srv = sv._SERVER
    assert srv is not None
    assert sv.estado()["vivo"] is True
    assert Path(servidor["handshake"]).exists()

    hilo = _vigia_de_prueba(srv, ocio_s=0.05)
    hilo.join(15.0)

    assert not hilo.is_alive(), "el vigia no termino tras apagar"
    assert sv.estado()["vivo"] is False
    assert not Path(servidor["handshake"]).exists()
    # Y NO SE CALLA: un cuaderno que desaparece solo sin decir por que es
    # indistinguible de uno que se rompio.
    assert sv._ULTIMO_ERROR.get("donde") == "clases.servidor_vivo.ocio"
    assert "sin nadie mirando" in sv._ULTIMO_ERROR.get("motivo", "")


def test_un_sse_abierto_cuenta_como_alguien_mirando(servidor):
    """La segunda mitad, y la que separa este vigia del editor de flujos.

    Un espectador que lleva una hora viendo la clase NO hace peticiones
    nuevas: su conexion es una sola, de hace una hora. Un vigia que solo mire
    `ultimo` le cerraria la pagina en la cara justo cuando esta funcionando.

    Que discrimina: quitando el `if _n_clientes() > 0` de `_vigilante`, el
    servidor se apaga aqui con el espectador conectado y mirando.
    """
    srv = sv._SERVER
    espia = _Espia(servidor["puerto"], servidor["token"])
    hilo = None
    try:
        assert _esperar_clientes(1)
        hilo = _vigia_de_prueba(srv, ocio_s=0.05)
        # Veinte periodos de ocio enteros con el SSE abierto y sin una sola
        # peticion nueva: es la hora quieta del espectador, comprimida.
        time.sleep(1.0)
        assert sv.estado()["vivo"] is True, "el vigia echo al espectador"
        assert sv.estado()["clientes"] == 1
        assert hilo.is_alive()
        assert sv._ULTIMO_ERROR.get("donde") != "clases.servidor_vivo.ocio"
    finally:
        # Se le pide salir por el mismo Event que usa `_apagar`: asi el vigia
        # de prueba muere sin apagar nada y el fixture cierra como siempre.
        srv.evento_parada.set()
        if hilo is not None:
            hilo.join(5.0)
        espia.cerrar()


def test_una_peticion_valida_rearma_el_reloj_del_vigia(servidor):
    """Mirar la pagina cuenta: cada GET que pasa el guardia reinicia el ocio.

    Las dos mitades en un solo test para que no quede duda de que la primera
    no pasa por casualidad: mientras hay peticiones el cuaderno sigue vivo
    pasado el ocio; en cuanto paran, el MISMO vigia lo apaga.
    """
    srv = sv._SERVER
    hilo = _vigia_de_prueba(srv, ocio_s=0.3, latido_s=0.02)
    fin = time.time() + 1.0        # mas de tres ocios enteros
    while time.time() < fin:
        try:
            codigo, _, _ = _pedir(servidor["puerto"], "/estado",
                                  token=servidor["token"])
        except OSError as exc:
            # Sin el rearme del reloj el servidor muere A MITAD de la tanda y
            # lo que salta es el socket, no el assert: se traduce para que el
            # fallo diga lo que pasa en vez de un ConnectionReset pelado.
            raise AssertionError("el vigia apago el cuaderno con trafico "
                                 "vivo (%s)" % exc) from exc
        assert codigo == 200
        assert sv.estado()["vivo"] is True, "el vigia apago con trafico vivo"
        time.sleep(0.08)
    # Y ahora se le deja de hablar: el ocio llega y el vigia hace su trabajo.
    hilo.join(15.0)
    assert not hilo.is_alive()
    assert sv.estado()["vivo"] is False


def test_un_ocio_de_cero_desactiva_el_auto_apagado(servidor):
    """`INACTIVIDAD_MIN <= 0` es la valvula de "no me lo cierres nunca" (una
    clase que se graba entera sin mirar el cuaderno). Tiene que seguir
    girando, no apagar ni salirse del bucle."""
    srv = sv._SERVER
    hilo = _vigia_de_prueba(srv, ocio_s=0.0)
    try:
        time.sleep(0.3)
        assert sv.estado()["vivo"] is True
        assert hilo.is_alive()
    finally:
        srv.evento_parada.set()
        hilo.join(5.0)


def test_estado_sin_servidor_no_miente():
    fuera = sv.estado()
    assert fuera["vivo"] is False
    assert fuera["puerto"] == 0
    assert fuera["url"] == ""
    assert fuera["inactividad_min"] == sv.INACTIVIDAD_MIN

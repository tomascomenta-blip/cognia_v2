# -*- coding: utf-8 -*-
"""
tests/test_clases_almacen.py
============================
La capa de disco del cuaderno (cognia/clases/almacen.py) contra disco y red
DE VERDAD.

Nada de mocks: los JSONL se escriben y se releen, y las descargas van contra
un servidor HTTP de la stdlib levantado en un hilo sobre 127.0.0.1. Un test
que parcheara urlopen comprobaria que el parche funciona, no que la funcion
lee cabeceras reales ni que corta antes de escribir; y justo eso (el
Content-Type que llega, el Content-Length que falta) es lo unico que puede
fallar aqui.

AISLAMIENTO. COGNIA_CLASES_DIR se desvia a tmp_path en un fixture autouse y
se COMPRUEBA el desvio antes de dejar correr nada: sin eso estos tests
escribirian jornadas de mentira dentro del cuaderno real del duenio
(~/.cognia/clases), y un setenv que no coge es indistinguible de un test que
pasa.

Los suscriptores del bus se quitan siempre en un finally. El bus es un
singleton de proceso: un callback olvidado seguiria disparando en los tests
que corran despues y les cambiaria el resultado.

LAS RUTAS DE LOS TESTS VAN DENTRO DE alm.raiz(). No es cosmetico: los eventos
solo se emiten para escrituras que caen en el cuaderno de clases (el mismo
apendar lo usa el compilador para otra cosa), asi que un test que escriba en
un tmp_path suelto no veria evento ninguno -- y eso es justo lo que
comprueba, a proposito, test_apendar_fuera_del_cuaderno_no_emite.
"""

import contextlib
import http.server
import json
import tempfile
import threading
import time

import pytest

from cognia import events
from cognia.clases import almacen as alm
from cognia.clases import vista
from cognia.ux import events as ux


# ── aislamiento ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cuaderno_aislado(tmp_path, monkeypatch):
    raiz = tmp_path / "clases"
    monkeypatch.setenv("COGNIA_CLASES_DIR", str(raiz))
    # Verificacion, no fe: si el desvio no cogiera, todos los asserts de abajo
    # seguirian pasando mientras se escribe en el cuaderno de verdad.
    assert alm.raiz() == raiz.resolve() or alm.raiz() == raiz
    # El aviso de degradacion es log-once por via y el estado vive en el
    # MODULO: sin limpiarlo, el primer test que rompa el bus dejaria mudos a
    # los siguientes y estos pasarian sin comprobar nada.
    alm._avisos_dados.clear()
    alm._ultimo_fallo.clear()
    # La cache de fechas se llavea por (ruta, mtime_ns, tamanio) y cada test
    # tiene su tmp_path, asi que no deberia cruzarse; se vacia igual porque el
    # reloj de ficheros de Windows avanza a saltos de ~15 ms y dos escrituras
    # del mismo tamanio dentro del mismo salto compartirian huella.
    alm._CACHE_FECHA.clear()
    yield
    alm._avisos_dados.clear()
    alm._ultimo_fallo.clear()
    alm._CACHE_FECHA.clear()


@contextlib.contextmanager
def _suscrito(evento, callback):
    """Suscribe y DESUSCRIBE pase lo que pase (ver cabecera)."""
    events.subscribe(evento, callback)
    try:
        yield
    finally:
        events.unsubscribe(evento, callback)


@contextlib.contextmanager
def _degradaciones():
    """Recoge los Degradado que salgan por el canal de la casa (cognia.ux),
    que es por donde CLAUDE.md exige que se avise de todo fallo. Tambien
    desuscribe en finally: la lista de suscriptores de ux es global."""
    vistos = []

    def _oir(ev):
        if isinstance(ev, ux.Degradado):
            vistos.append(ev)

    ux.suscribir(_oir)
    try:
        yield vistos
    finally:
        ux.desuscribir(_oir)


@pytest.fixture
def espia_mkstemp(monkeypatch):
    """Apunta cada apertura de fichero de destino SIN impedirla.

    Es lo que permite distinguir "corto por la cabecera" de "corto leyendo":
    los dos acaban en el mismo ValueError y sin fichero en disco, y el unico
    testigo del camino que se tomo es si se llego a abrir el destino."""
    llamadas = []
    real = tempfile.mkstemp

    def _espia(*a, **k):
        llamadas.append(k.get("dir") or (a[0] if a else None))
        return real(*a, **k)

    monkeypatch.setattr(tempfile, "mkstemp", _espia)
    return llamadas


# ── (a) apendar emite, y un suscriptor roto no cuesta la linea ───────────────

def test_apendar_emite_el_registro_escrito(tmp_path):
    ruta = alm.raiz() / "transcripcion.jsonl"
    registro = {"t0": 0.0, "t1": 3.5, "texto": "la derivada de x2", "fuente": "whisper"}

    recibidos = []

    def _cb(ev):
        # Se lee el fichero DENTRO del callback: asi el test no comprueba solo
        # que el evento sale, sino que sale con la linea ya en disco.
        ev = dict(ev)
        ev["en_disco"] = alm.leer_jsonl(alm.raiz() / "transcripcion.jsonl")
        recibidos.append(ev)

    with _suscrito("clase.entrada", _cb):
        alm.apendar(ruta, registro)

    assert len(recibidos) == 1
    ev = recibidos[0]
    assert ev["evento"] == "clase.entrada"
    assert ev["registro"] == registro
    assert ev["ruta"] == str(ruta)
    assert ev["en_disco"] == [registro]


def test_un_suscriptor_que_revienta_no_impide_la_escritura(tmp_path):
    """El punto entero de emitir aqui: la clase se sigue grabando aunque el
    que escucha este roto."""
    ruta = alm.raiz() / "entradas.jsonl"
    registro = {"t": 12.0, "tipo": "nota", "texto": "examen el viernes"}
    llamado = []

    def _revienta(ev):
        llamado.append(ev["evento"])
        raise RuntimeError("suscriptor roto a proposito")

    with _suscrito("clase.entrada", _revienta):
        alm.apendar(ruta, registro)          # no debe lanzar

    assert llamado == ["clase.entrada"]      # el fallo fue REAL, no un no-op
    assert alm.leer_jsonl(ruta) == [registro]


def test_apendar_sin_suscriptores_escribe_igual(tmp_path):
    """Sin nadie escuchando la emision es un no-op silencioso, no un error."""
    ruta = alm.raiz() / "cortes.jsonl"
    alm.apendar(ruta, {"t": 1.0, "materia": "Fisica", "por": "horario"})
    alm.apendar(ruta, {"t": 2.0, "materia": "Latin", "por": "manual"})
    assert [r["materia"] for r in alm.leer_jsonl(ruta)] == ["Fisica", "Latin"]


# ── (a bis) el evento no puede mentir sobre su origen ────────────────────────

def test_apendar_fuera_del_cuaderno_no_emite(tmp_path):
    """apendar NO es privada de este paquete: cognia/compilador/bitacora.py la
    usa para su eventos.jsonl. Sin filtrar por ruta, cada linea del compilador
    se anunciaba como "clase.entrada" y quien escuchara una clase en vivo se
    comia escrituras de otro subsistema."""
    fuera = tmp_path / "compilador" / "eventos.jsonl"
    dentro = alm.raiz() / "jornadas" / "2026-08-31" / alm.ENTRADAS
    vistos = []

    with _suscrito("clase.entrada", vistos.append):
        alm.apendar(fuera, {"t": 1.0, "tipo": "comando_creado"})
        assert vistos == []                      # nada, y no por casualidad:
        alm.apendar(dentro, {"t": 2.0, "tipo": "nota"})

    assert [ev["ruta"] for ev in vistos] == [str(dentro)]
    # La escritura de fuera SI ocurrio: se silencia el aviso, no el fichero.
    assert alm.leer_jsonl(fuera) == [{"t": 1.0, "tipo": "comando_creado"}]


def test_guardar_json_fuera_del_cuaderno_no_emite(tmp_path):
    """Mismo caso para el JSON atomico: bitacora.py escribe su indice.json con
    guardar_json y eso no es una jornada de clase."""
    fuera = tmp_path / "compilador" / "indice.json"
    dentro = alm.raiz() / alm.INDICE
    vistos = []

    with _suscrito("clase.json", vistos.append):
        alm.guardar_json(fuera, {"comandos": ["/foo"]})
        assert vistos == []
        alm.guardar_json(dentro, {"materias": ["Fisica"]})

    assert [ev["ruta"] for ev in vistos] == [str(dentro)]
    assert alm.leer_json(fuera) == {"comandos": ["/foo"]}


# ── (b) guardar_json emite DESPUES del replace ───────────────────────────────

def test_guardar_json_emite_tras_el_replace(tmp_path):
    ruta = alm.raiz() / "jornada.json"
    ruta.write_text(json.dumps({"materia": "viejo"}), encoding="utf-8")
    datos = {"materia": "Historia", "pausado": False}

    vistos = []

    def _cb(ev):
        # Si el evento saliera ANTES del os.replace, aqui se leeria el JSON
        # viejo (o un temporal) y el assert de abajo cazaria el orden mal.
        vistos.append((ev, json.loads(ruta.read_text(encoding="utf-8"))))

    with _suscrito("clase.json", _cb):
        alm.guardar_json(ruta, datos)

    assert len(vistos) == 1
    ev, en_disco = vistos[0]
    assert ev["evento"] == "clase.json"
    assert ev["datos"] == datos
    assert ev["ruta"] == str(ruta)
    assert en_disco == datos


def test_guardar_json_roto_no_emite(tmp_path):
    """Un fallo de escritura no puede anunciarse como un guardado."""
    vistos = []

    def _cb(ev):
        vistos.append(ev)

    class _NoSerializable:
        pass

    with _suscrito("clase.json", _cb):
        with pytest.raises(TypeError):
            alm.guardar_json(alm.raiz() / "apuntes.json",
                             {"x": _NoSerializable()})

    assert vistos == []


# ── (c) leer_jsonl sigue saltando lineas rotas ───────────────────────────────

def test_leer_jsonl_salta_lineas_rotas(tmp_path):
    """La ultima linea de una jornada cortada a mitad no es JSON; reventar ahi
    tiraria la manana entera por medio segundo de audio."""
    ruta = tmp_path / "transcripcion.jsonl"
    ruta.write_text(
        '{"t": 1, "texto": "uno"}\n'
        'esto no es json\n'
        '\n'
        '{"t": 2, "texto": "dos"}\n'
        '{"t": 3, "texto": "tr',          # corte a mitad, como un apagon
        encoding="utf-8")

    leidos = alm.leer_jsonl(ruta)
    assert [r["texto"] for r in leidos] == ["uno", "dos"]


def test_leer_jsonl_inexistente_es_lista_vacia(tmp_path):
    assert alm.leer_jsonl(tmp_path / "no-existe.jsonl") == []


# ── (c bis) el anillo del bus es COMPARTIDO: no se envenena ──────────────────

def test_500_entradas_de_clase_no_desalojan_el_historial(tmp_path):
    """cognia/events.py guarda 200 eventos y cognia/analytics/panel.py los usa
    como UNICA fuente de diagnostico de la sesion. Una clase de cinco horas
    mete decenas de miles de "clase.entrada": si entraran en el anillo, a los
    pocos segundos de grabar el panel estaria ciego para todo lo demas.

    Se entregan a quien escucha (eso es el valor del evento) y NO se guardan
    (releerlos del historial no le sirve a nadie: el dato esta en el JSONL).
    """
    from cognia.analytics import panel

    bus = events.get_bus()
    events.emit("panel.testigo", marca="antes de la clase")

    ruta = alm.raiz() / "jornadas" / "2026-08-31" / alm.TRANSCRIPCION
    recibidos = []
    with _suscrito("clase.entrada", recibidos.append):
        for i in range(500):
            alm.apendar(ruta, {"t": float(i), "texto": "linea %d" % i})

    assert len(recibidos) == 500                  # entregados, uno por linea
    assert len(alm.leer_jsonl(ruta)) == 500       # y en disco

    hist = bus.historial(n=1000)
    assert [e for e in hist if str(e.get("evento")).startswith("clase.")] == []
    # El testigo sobrevive a las 500: con el anillo envenenado seria el primero
    # en salir (500 eventos contra 200 de capacidad).
    assert any(e.get("evento") == "panel.testigo" for e in hist)
    assert "panel.testigo" in panel.resumen_eventos(n=1000)["por_tipo"]


def test_el_comodin_tambien_recibe_los_eventos_de_clase(tmp_path):
    """No entrar en el historial no puede costar suscriptores: el comodin "*"
    es por donde miran analytics y la oficina."""
    ruta = alm.raiz() / "jornadas" / "2026-08-31" / alm.ENTRADAS
    todos = []
    with _suscrito("*", todos.append):
        alm.apendar(ruta, {"t": 1.0, "tipo": "nota", "texto": "hola"})
        alm.guardar_json(alm.raiz() / "cuaderno.json", {"materias": []})

    assert [e["evento"] for e in todos] == ["clase.entrada", "clase.json"]


# ── (c ter) el aviso de fallo es log-once y sale por el canal de la casa ─────

def test_el_bus_roto_avisa_UNA_vez_y_no_para_la_clase(tmp_path, monkeypatch):
    """Antes se logueaba con exc_info=True en CADA emision: con el bus caido,
    una jornada de cinco horas escribia miles de trazas identicas y el fallo
    real quedaba enterrado."""
    def _revienta(*a, **k):
        raise RuntimeError("events.py roto a proposito")

    monkeypatch.setattr(alm, "_publicar_volatil", _revienta)
    monkeypatch.setattr(events, "emit", _revienta)

    ruta = alm.raiz() / "jornadas" / "2026-08-31" / alm.ENTRADAS
    with _degradaciones() as avisos:
        for i in range(5):
            alm.apendar(ruta, {"t": float(i), "tipo": "nota"})

    assert len(avisos) == 1                        # log-once, no cinco
    assert avisos[0].donde == "clases.almacen.bus"
    assert "events.py roto a proposito" in avisos[0].motivo
    # La clase se sigue grabando: el aviso es el que se calla, no el disco.
    assert len(alm.leer_jsonl(ruta)) == 5
    # Y el estado sigue consultable aunque el log no se repita (la puerta de
    # diagnostico del modulo).
    assert alm.ultimo_fallo_bus()["donde"] == "clases.almacen.bus"


def test_un_suscriptor_lento_se_ve(tmp_path, monkeypatch):
    """El modo de fallo real de este bus no es el suscriptor que revienta (ese
    lo aisla el bucle) sino el LENTO: corre en el hilo del escritor, o sea que
    le roba tiempo a la grabacion. No se puede interrumpir un callback en
    Python, pero si medirlo y decirlo."""
    monkeypatch.setattr(alm, "_TOPE_SUSCRIPTOR_S", 0.0)

    def _lento(ev):
        time.sleep(0.01)

    ruta = alm.raiz() / "jornadas" / "2026-08-31" / alm.ENTRADAS
    with _degradaciones() as avisos:
        with _suscrito("clase.entrada", _lento):
            alm.apendar(ruta, {"t": 1.0, "tipo": "nota"})
            alm.apendar(ruta, {"t": 2.0, "tipo": "nota"})

    assert len(avisos) == 1                        # log-once tambien aqui
    assert avisos[0].donde == "clases.almacen.suscriptor_lento"
    assert "frenando la grabacion" in avisos[0].motivo


# ── (d) descargar_adjunto contra un servidor HTTP real ───────────────────────

_CUERPO_GRANDE = b"x" * 4096


class _Manejador(http.server.BaseHTTPRequestHandler):
    """Rutas minimas para los tres casos que importan. HTTP/1.0 a proposito:
    asi la ruta sin Content-Length senaliza el final cerrando la conexion, que
    es justo el caso en el que el tope solo se puede aplicar leyendo."""

    protocol_version = "HTTP/1.0"

    def do_GET(self):                                    # noqa: N802 (stdlib)
        if self.path == "/texto":
            cuerpo = b"<html>no soy una imagen</html>"
            tipo = "text/html; charset=utf-8"
            largo = True
        elif self.path == "/grande-callado":
            cuerpo, tipo, largo = _CUERPO_GRANDE, "image/png", False
        elif self.path == "/foto":
            cuerpo, tipo, largo = b"no-es-un-jpeg-de-verdad", "image/jpeg", True
        elif self.path == "/miente-grande":
            # Declara 9,5 MB y manda 10 bytes: la cabecera tiene que cortar
            # SOLA, porque el conteo real no llegaria nunca al tope.
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", "9999999")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        if largo:
            self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        """Silencio: el log a stderr del http.server ensucia la salida de
        pytest y no aporta nada al diagnostico de estos tests."""


@pytest.fixture
def servidor():
    """Un HTTP de verdad en 127.0.0.1, puerto efimero. Nada sale de la
    maquina: la red externa haria estos tests flaky y lentos sin cubrir ni un
    camino mas."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Manejador)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        hilo.join(timeout=5)


def _adjuntos(jornada):
    return sorted(p.name for p in
                  (alm.dir_jornada(jornada) / alm.DIR_ADJUNTOS).iterdir())


def test_descargar_adjunto_baja_una_imagen(servidor):
    nombre = alm.descargar_adjunto("2026-08-31", servidor + "/foto")
    # La extension sale del Content-Type, no de la url (que no tiene ninguna).
    assert nombre == "img_0001.jpg"
    ruta = alm.ruta_adjunto("2026-08-31", nombre)
    assert ruta.read_bytes() == b"no-es-un-jpeg-de-verdad"
    # Y el segundo no pisa al primero.
    assert alm.descargar_adjunto("2026-08-31", servidor + "/foto") == "img_0002.jpg"


def test_descargar_adjunto_rechaza_lo_que_no_es_imagen(servidor):
    url = servidor + "/texto"
    with pytest.raises(ValueError) as exc:
        alm.descargar_adjunto("2026-08-31", url)
    # Mensaje accionable: tiene que decir QUE url y QUE llego.
    assert url in str(exc.value)
    assert "text/html" in str(exc.value)
    assert _adjuntos("2026-08-31") == []


def test_descargar_adjunto_corta_por_content_length_sin_abrir_el_destino(
        servidor, espia_mkstemp):
    """LOS DOS CORTES SON CAMINOS DISTINTOS Y HAY QUE PROBARLOS POR SEPARADO.

    Con un cuerpo grande de verdad, el corte por conteo tapa al de la cabecera
    y el test pasa por el motivo equivocado. Aqui el servidor DECLARA 9,5 MB y
    manda 10 bytes: si la cabecera no cortase, la descarga terminaria bien.
    Y lo que hace util a este camino es que corta sin tocar el disco, asi que
    se comprueba lo unico que lo distingue del otro: no se abrio el destino.
    """
    url = servidor + "/miente-grande"
    with pytest.raises(ValueError) as exc:
        alm.descargar_adjunto("2026-08-31", url)
    assert url in str(exc.value)
    assert "9.5 MB" in str(exc.value)          # lo DECLARADO, no lo leido
    assert espia_mkstemp == []                 # ni un temporal se llego a abrir
    assert _adjuntos("2026-08-31") == []


def test_descargar_adjunto_corta_leyendo_si_no_hay_content_length(
        servidor, monkeypatch, espia_mkstemp):
    """El otro camino: sin Content-Length el tope solo se puede aplicar con lo
    que se lleva leido. Aqui el destino SI se abre (y por eso el corte tiene
    que limpiar el temporal), que es justo lo contrario del test de arriba."""
    monkeypatch.setattr(vista, "TOPE_ADJUNTO", 1024)
    url = servidor + "/grande-callado"
    with pytest.raises(ValueError) as exc:
        alm.descargar_adjunto("2026-08-31", url)
    assert url in str(exc.value)
    assert "tras leer" in str(exc.value)       # el mensaje del corte por conteo
    assert len(espia_mkstemp) == 1             # se abrio el destino...
    assert _adjuntos("2026-08-31") == []       # ...y no quedo ni el .tmp


def test_descargar_adjunto_rechaza_una_redireccion_a_otro_esquema(servidor,
                                                                  monkeypatch):
    """La guardia de esquema miraba solo la url TECLEADA. urllib sigue las
    redirecciones por su cuenta y su HTTPRedirectHandler admite tambien ftp://,
    donde ademas el Content-Type se ADIVINA del nombre del fichero: un
    servidor podia mandar la descarga a otro esquema y colarse.

    Se envuelve la respuesta REAL (mismo socket, mismas cabeceras, mismo
    cuerpo) y solo se le cambia la url final, que es el unico dato que no se
    puede provocar contra un servidor http de la stdlib.
    """
    import urllib.request

    real = urllib.request.urlopen

    class _RedirigidaAFtp:
        def __init__(self, resp):
            self._resp = resp

        def geturl(self):
            return "ftp://ftp.ejemplo/pizarra.jpg"

        def __getattr__(self, nombre):
            return getattr(self._resp, nombre)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._resp.close()
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _RedirigidaAFtp(real(*a, **k)))

    with pytest.raises(ValueError) as exc:
        alm.descargar_adjunto("2026-08-31", servidor + "/foto")
    assert "ftp://ftp.ejemplo/pizarra.jpg" in str(exc.value)
    assert _adjuntos("2026-08-31") == []


# ── (e) el nombre del adjunto no se puede reutilizar ni escapar ──────────────

def test_el_numero_del_adjunto_sale_del_maximo_no_de_la_cuenta(servidor):
    """Contando ficheros, borrar dos de tres devuelve el contador atras y el
    siguiente adjunto PISA a uno que ya esta referenciado en el cuaderno."""
    for _ in range(3):
        alm.descargar_adjunto("2026-08-31", servidor + "/foto")
    assert _adjuntos("2026-08-31") == ["img_0001.jpg", "img_0002.jpg",
                                       "img_0003.jpg"]

    alm.ruta_adjunto("2026-08-31", "img_0001.jpg").unlink()
    alm.ruta_adjunto("2026-08-31", "img_0002.jpg").unlink()

    # Con la cuenta serian dos ficheros -> img_0002, encima del que quedaba.
    assert alm.descargar_adjunto("2026-08-31", servidor + "/foto") == "img_0004.jpg"
    assert alm.ruta_adjunto("2026-08-31", "img_0003.jpg").exists()


def test_copiar_adjunto_numera_igual_y_no_pisa(tmp_path):
    origen = tmp_path / "pizarra.PNG"
    origen.write_bytes(b"\x89PNG")
    assert alm.copiar_adjunto("2026-08-31", origen) == "adj_0001.png"
    assert alm.copiar_adjunto("2026-08-31", origen) == "adj_0002.png"
    alm.ruta_adjunto("2026-08-31", "adj_0001.png").unlink()
    assert alm.copiar_adjunto("2026-08-31", origen) == "adj_0003.png"


def test_el_prefijo_no_se_sale_de_adjuntos(tmp_path):
    """`prefijo` es argumento y puede venir del usuario: con barras escribiria
    FUERA de adjuntos/ (o fuera del cuaderno entero con ..)."""
    origen = tmp_path / "foto.png"
    origen.write_bytes(b"\x89PNG")
    nombre = alm.copiar_adjunto("2026-08-31", origen, prefijo="../../fuera")
    assert "/" not in nombre and "\\" not in nombre
    assert alm.ruta_adjunto("2026-08-31", nombre).is_file()
    assert not (alm.raiz().parent / "fuera_0001.png").exists()


def test_descargar_adjunto_solo_http(tmp_path):
    """file:// abriria un fichero cualquiera del disco: se corta antes de
    tocar la red."""
    fichero = tmp_path / "secreto.png"
    fichero.write_bytes(b"\x89PNG")
    with pytest.raises(ValueError):
        alm.descargar_adjunto("2026-08-31", fichero.as_uri())


def test_descargar_adjunto_url_muerta_lanza_con_la_url():
    """Nunca None mudo: una entrada del cuaderno apuntando a un adjunto que no
    existe seria peor que el error."""
    url = "http://127.0.0.1:1/no-hay-nadie.png"
    with pytest.raises(OSError) as exc:
        alm.descargar_adjunto("2026-08-31", url)
    assert url in str(exc.value)


def test_extensiones_de_imagen_es_la_tabla_de_vista():
    """La lista de MIME aceptados NO se duplica: si vista deja de embeber un
    formato, aqui deja de descargarse solo."""
    tabla = alm._extensiones_de_imagen(vista._MIME_IMAGEN)
    assert set(tabla) == set(vista._MIME_IMAGEN.values())
    assert tabla["image/jpeg"] == ".jpg"      # gana la primera de la tabla


# ── (f) jornadas() ordena por FECHA, no por nombre ───────────────────────────
#
# El bug: `sorted(nombres, reverse=True)` ordena alfabeticamente, y
# jornadas()[0] es "la ultima jornada" para el panel de /grabar-clase estado,
# para /grabar-clase apuntes, para transcribir y para la pagina viva. Una
# carpeta llamada 'a-b' se ponia delante de la clase que se acababa de cerrar.

def _crear_jornada(nombre, inicio=None, extra=None):
    """Una jornada en disco. Con `inicio=None` NO se escribe jornada.json, que
    es el estado real de una carpeta recien creada (dir_jornada la crea antes
    de que el grabador escriba nada) o importada de otro sitio."""
    d = alm.raiz() / "jornadas" / nombre
    d.mkdir(parents=True, exist_ok=True)
    if inicio is not None:
        datos = {"nombre": nombre, "inicio_epoch": inicio, "estado": "cerrada"}
        datos.update(extra or {})
        (d / alm.JORNADA).write_text(json.dumps(datos), encoding="utf-8")
    return d


def test_jornadas_ordena_por_fecha_aunque_el_nombre_diga_lo_contrario():
    """Nombres que ordenan justo al reves que las fechas: por nombre saldria
    ['zzz', 'mmm', 'aaa'] y por fecha sale al reves."""
    _crear_jornada("aaa", inicio=1_800_000_000.0)      # la mas nueva
    _crear_jornada("mmm", inicio=1_700_000_000.0)
    _crear_jornada("zzz", inicio=1_600_000_000.0)      # la mas vieja

    assert alm.jornadas() == ["aaa", "mmm", "zzz"]


def test_regresion_a_b_no_se_pone_delante_de_la_clase_recien_cerrada():
    """El caso EXACTO que se vio: nada mas cerrar una clase de verdad, el
    estado contestaba 'ultima jornada a-b / duracion 0 min / sesiones 0'."""
    _crear_jornada("2026-08-31", inicio=1_756_600_000.0,
                   extra={"segundos": 5400.0})
    _crear_jornada("a-b")                      # carpeta suelta, sin fecha

    assert alm.jornadas()[0] == "2026-08-31"
    assert "a-b" in alm.jornadas()             # tampoco desaparece


def test_la_jornada_sin_fecha_va_al_final_y_no_desaparece():
    """Sin fecha no es lo mismo que vieja: no puede ser la primera (nadie
    puede probar que lo sea) pero tampoco puede caerse de la lista, que es la
    que recorren el indice de materias, el vocabulario y el olvido."""
    _crear_jornada("2026-08-30", inicio=1_756_500_000.0)
    _crear_jornada("2020-01-01", inicio=1_577_836_800.0)
    _crear_jornada("trastero")                 # ni json ni nombre con fecha
    _crear_jornada("zzz-otra")

    orden = alm.jornadas()
    assert orden[:2] == ["2026-08-30", "2020-01-01"]
    # Las dos sin fecha, al final y entre ellas por nombre descendente.
    assert orden[2:] == ["zzz-otra", "trastero"]


def test_la_jornada_recien_creada_sin_json_se_fecha_por_el_nombre():
    """La carpeta de hoy existe ANTES de que el grabador escriba inicio_epoch
    (dir_jornada la crea; el campo no se pone hasta pulsar grabar). Sin el
    respaldo del nombre se iria al fondo justo el dia que importa.

    Los nombres van a proposito al reves que las fechas: '2026-01-10' es una
    jornada VIEJA con la carpeta renombrada, y por nombre iria delante.
    """
    _crear_jornada("2026-01-02")                       # recien creada, sin json
    _crear_jornada("2026-01-10", inicio=1_577_836_800.0)   # de 2020 de verdad

    assert alm.jornadas() == ["2026-01-02", "2026-01-10"]


def test_fecha_de_prefiere_inicio_epoch_al_nombre():
    """El nombre es una convencion que se rompe al importar o renombrar una
    carpeta; inicio_epoch lo escribio el grabador y viaja con ella."""
    _crear_jornada("2020-01-01-copia", inicio=1_756_600_000.0)

    assert alm.fecha_de("2020-01-01-copia") == 1_756_600_000.0
    # Y esa fecha manda en el orden: la carpeta se llama 2020 pero es de 2026.
    _crear_jornada("2026-08-30", inicio=1_756_500_000.0)
    assert alm.jornadas()[0] == "2020-01-01-copia"


def test_fecha_de_devuelve_none_cuando_no_hay_forma_de_fechar():
    """None es 'no se sabe fechar', que es un estado distinto de 'es vieja' y
    tiene que poder distinguirse desde fuera (lo usa el orden de jornadas)."""
    _crear_jornada("trastero")
    assert alm.fecha_de("trastero") is None
    assert alm.fecha_de("no-existe-esta-jornada") is None


def test_un_jornada_json_ilegible_no_rompe_ni_se_cuela_primero():
    """Un json truncado por un corte de luz: se cae al nombre, y si el nombre
    tampoco fecha, al final. Lo que no puede es lanzar ni ser la primera."""
    d = _crear_jornada("rota")
    (d / alm.JORNADA).write_text('{"inicio_epoch": 17566000', encoding="utf-8")
    _crear_jornada("2026-08-31", inicio=1_756_600_000.0)

    assert alm.jornadas() == ["2026-08-31", "rota"]
    assert alm.fecha_de("rota") is None


def test_un_inicio_epoch_que_no_es_numero_no_lanza():
    """jornada.json lo puede haber escrito una version vieja o una mano."""
    _crear_jornada("2026-08-31", inicio="ayer por la manana")
    assert alm.fecha_de("2026-08-31") == alm._epoch_del_nombre("2026-08-31")


def test_dos_jornadas_del_mismo_dia_la_de_la_tarde_va_delante():
    """'-2' es la sesion de la tarde (ver jornada.nombre_de_hoy). Sin ninguna
    con inicio_epoch, el desempate por nombre descendente la pone delante."""
    _crear_jornada("2026-08-31")
    _crear_jornada("2026-08-31-2")
    assert alm.jornadas() == ["2026-08-31-2", "2026-08-31"]


def test_jornadas_no_relee_los_json_que_no_cambiaron(monkeypatch):
    """El coste: fechar no puede costar leer el curso entero en cada llamada.
    Medido en este disco con 180 jornadas, leerlas y parsearlas son 11,11 ms
    contra 2,30 ms de solo hacer stat. La cache se llavea por huella del
    fichero, asi que la segunda llamada no abre NINGUNO y despues de tocar uno
    abre SOLO ese."""
    for i in range(5):
        _crear_jornada("2026-08-%02d" % (20 + i), inicio=1_756_000_000.0 + i)

    leidos = []
    real = alm.leer_json

    def _espia(ruta, defecto=None):
        leidos.append(str(ruta))
        return real(ruta, defecto)

    monkeypatch.setattr(alm, "leer_json", _espia)

    assert len(alm.jornadas()) == 5
    assert len(leidos) == 5                    # primera vez: se leen todas
    leidos.clear()

    assert len(alm.jornadas()) == 5
    assert leidos == []                        # ya fechadas: cero lecturas

    time.sleep(0.05)                           # que el mtime pueda cambiar
    _crear_jornada("2026-08-22", inicio=1_756_900_000.0, extra={"aviso": "x"})
    assert alm.jornadas()[0] == "2026-08-22"
    assert [r for r in leidos if "2026-08-22" in r]
    assert len(leidos) == 1                    # solo la que cambio


def test_jornadas_no_crea_carpetas_al_listar():
    """Fechar NO puede pasar por dir_jornada: esa crea audio/ y adjuntos/ en
    cada llamada, y jornadas() la llaman el panel, la pagina viva y el olvido.
    Listar es una lectura y tiene que dejar el disco como estaba."""
    d = _crear_jornada("2026-08-31", inicio=1_756_600_000.0)
    antes = sorted(p.name for p in d.iterdir())

    alm.jornadas()
    alm.fecha_de("2026-08-31")

    assert sorted(p.name for p in d.iterdir()) == antes
    assert not (d / alm.DIR_AUDIO).exists()
    assert not (d / alm.DIR_ADJUNTOS).exists()


def test_jornadas_ignora_lo_que_no_es_carpeta():
    """Un fichero suelto en jornadas/ no es una jornada."""
    _crear_jornada("2026-08-31", inicio=1_756_600_000.0)
    (alm.raiz() / "jornadas" / "notas.txt").write_text("hola", encoding="utf-8")
    assert alm.jornadas() == ["2026-08-31"]

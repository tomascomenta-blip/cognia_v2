# -*- coding: utf-8 -*-
"""
tests/test_flujoteca_editor.py
==============================
Tests del servidor local del editor visual de flujos
(`cognia/agent/flujoteca_editor.py`).

DOS REGLAS DURAS DE ESTE FICHERO, las dos por danos ya pagados:

1. La fixture `biblioteca` es AUTOUSE. El editor ESCRIBE en la flujoteca, y
   sin redirigir `COGNIA_FLUJOTECA_DIR` a un tmp_path un test borraria o
   versionaria los flujos reales del dueno. Copiada de tests/test_flujoteca.py.
2. Todo servidor se levanta con el contextmanager `servidor()`, que hace
   `shutdown()` + `server_close()` en un `finally`. Un test que deja el
   servidor vivo deja el PUERTO y el THREAD vivos y contamina a los que vengan
   detras (memoria de la casa: matar el shell no mata el proceso).

Sin modelo y sin red: `flujo_ia.editar` se monkeypatchea, y todo lo demas es
disco + JSON.
"""

import contextlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from cognia.agent import flujo_ia
from cognia.agent import flujoteca as F
from cognia.agent import flujoteca_editor as E


# ---------------------------------------------------------------------------
# Aislamiento
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def biblioteca(tmp_path, monkeypatch):
    """Redirige la biblioteca ENTERA a tmp_path. Autouse por seguridad."""
    d = tmp_path / "flujoteca"
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(d))
    return d


@pytest.fixture(autouse=True)
def sin_singleton():
    """Ningun test hereda ni deja un servidor del singleton de modulo."""
    E.parar()
    yield
    E.parar()


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

class Cliente:
    """Cliente HTTP minimo contra el servidor de un test.

    Devuelve siempre (codigo, json) y NUNCA lanza por un 4xx: el codigo es
    justamente lo que se esta midiendo.
    """

    def __init__(self, srv):
        self.srv = srv
        self.puerto = srv.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.puerto
        self.token = srv.token

    def _pedir(self, req):
        try:
            r = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            cuerpo = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(cuerpo)
            except ValueError:
                return exc.code, {"crudo": cuerpo}
        with r:
            crudo = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(crudo)
        except ValueError:
            return r.status, {"crudo": crudo}

    def get(self, ruta, token=..., cabeceras=None):
        req = urllib.request.Request(self.base + ruta, method="GET")
        tok = self.token if token is ... else token
        if tok is not None:
            req.add_header("X-Cognia-Token", tok)
        for k, v in (cabeceras or {}).items():
            req.add_header(k, v)
        return self._pedir(req)

    def post(self, ruta, obj, token=..., cabeceras=None):
        datos = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + ruta, data=datos,
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        tok = self.token if token is ... else token
        if tok is not None:
            req.add_header("X-Cognia-Token", tok)
        for k, v in (cabeceras or {}).items():
            req.add_header(k, v)
        return self._pedir(req)


@contextlib.contextmanager
def servidor(nombre=""):
    """Un servidor efimero con su bucle en un thread daemon.

    El `finally` es el punto entero de este helper: sin el, cada test dejaria
    un puerto escuchando y un thread vivo hasta el final de la sesion.
    """
    srv = E.crear_server(puerto=0)
    srv.nombre = nombre
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    try:
        yield Cliente(srv)
    finally:
        srv.shutdown()
        srv.server_close()
        hilo.join(timeout=5)


def crudo(puerto, texto, espera=5.0, cerrar=True):
    """Una peticion HTTP A PELO, porque `urllib` no puede escribir lo malo.

    Los tres ataques de este fichero -cabeceras sin terminar, un
    `Content-Length` que miente y un byte no-ASCII en la query- son peticiones
    que ninguna libreria cliente construye por ti.
    """
    s = socket.socket()
    s.settimeout(espera)
    s.connect(("127.0.0.1", int(puerto)))
    s.sendall(texto)
    try:
        return s.recv(600)
    except OSError as exc:
        return b"<sin respuesta: " + str(exc).encode("utf-8", "replace") + b">"
    finally:
        if cerrar:
            s.close()


def flujo_lineal(nombre="informe", args="notas.md"):
    """Un DAG valido con TOOLS reales: el editor valida contra el registro."""
    return {"nombre": nombre, "nodos": [
        {"id": "leer", "tool": "leer_archivo", "args": args,
         "wires": ["escribir"]},
        {"id": "escribir", "tool": "escribir_archivo",
         "args": "salida.md | {{leer}}", "wires": []},
    ]}


def nodo(flujo, nid):
    """El nodo de ese id. NUNCA por posicion.

    Desde que `flujoteca.guardar` llama a `flows.asegurar_prompt` (PLAN2,
    PEDIDO 3), todo flujo guardado estrena un nodo de ENTRADA delante, asi que
    `nodos[0]` ya no es el primer nodo que escribio el test. Un indice fijo
    aqui mide el orden de la lista, que nunca fue lo que estos tests querian
    comprobar.
    """
    for n in (flujo or {}).get("nodos") or ():
        if n.get("id") == nid:
            return n
    raise AssertionError("no hay nodo %r en %s" % (
        nid, [n.get("id") for n in (flujo or {}).get("nodos") or ()]))


def n_versiones_en_disco():
    """Cuantos ficheros vN.json hay en la biblioteca entera."""
    base = F.dir_base()
    if not base.is_dir():
        return 0
    return len(list(base.glob("*/v*.json")))


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def test_get_sin_token_es_403():
    with servidor() as c:
        code, j = c.get("/", token=None)
        assert code == 403
        assert j.get("ok") is False
        # Y con un token que no es el suyo, tampoco.
        code2, _ = c.get("/api/flujos", token="no-es-el-token")
        assert code2 == 403
        # Con el token bueno, la misma ruta responde.
        code3, j3 = c.get("/api/flujos")
        assert code3 == 200 and j3.get("ok") is True


def test_origin_ajeno_es_403():
    """Defensa contra DNS rebinding: el Origin y el Host tienen que ser suyos."""
    with servidor() as c:
        code, j = c.get("/api/flujos",
                        cabeceras={"Origin": "http://evil.example"})
        assert code == 403
        assert "origen" in str(j.get("error", "")).lower()
        # Un Host ajeno es EL vector real del rebinding: el token viaja bien
        # (lo manda el navegador de la victima) y aun asi tiene que caer.
        code2, _ = c.get("/api/flujos",
                         cabeceras={"Host": "malo.example.com"})
        assert code2 == 403
        # El Origin propio pasa.
        code3, _ = c.get("/api/flujos",
                         cabeceras={"Origin": c.base})
        assert code3 == 200


def test_un_token_con_byte_no_ascii_da_403_y_no_revienta_el_guardia(capsys):
    """REGRESION: `compare_digest` sobre `str` LANZA con no-ASCII.

    Las cabeceras HTTP se decodifican como latin-1, asi que un solo byte >127
    en `X-Cognia-Token` tumbaba `_pasa()` -que ademas corria FUERA del
    try/except de las rutas-: la conexion se cerraba sin ningun codigo HTTP y
    el traceback entero salia por el stderr del REPL del dueno, sin necesidad
    de conocer el token.
    """
    with servidor() as c:
        capsys.readouterr()                      # limpia lo previo
        # `chr(0xf1)` y no la letra a pelo: el fuente de la casa se queda en
        # ASCII puro y el byte que viaja sigue siendo el mismo.
        code, j = c.get("/api/flujos", token=chr(0xf1) + "abc")
        assert code == 403
        assert j.get("ok") is False
        # Y por la query, que es la otra puerta del token.
        r = crudo(c.puerto,
                  ("GET /api/flujos?t=%%C3%%B1abc HTTP/1.0\r\n"
                   "Host: 127.0.0.1:%d\r\n\r\n" % c.puerto).encode("ascii"))
        assert b"403" in r.split(b"\r\n")[0], r
        # Un token vacio y uno larguisimo tampoco pueden lanzar.
        assert c.get("/api/flujos", token="")[0] == 403
        assert c.get("/api/flujos", token="a" * 5000)[0] == 403
        err = capsys.readouterr().err
    assert "Traceback" not in err, err
    assert "TypeError" not in err, err


def test_una_peticion_rechazada_no_rearma_el_reloj_del_auto_apagado():
    """REGRESION: `_marcar()` corria ANTES de `_pasa()`.

    Un 403 que reinicia el reloj deja que cualquier proceso local mantenga el
    editor vivo indefinidamente SIN credencial, que es exactamente el control
    que promete el auto-apagado de los 30 minutos.
    """
    with servidor() as c:
        c.srv.ultimo = 0.0
        c.srv.peticiones = 0
        assert c.get("/api/flujos", token="no-es-el-token")[0] == 403
        assert (c.srv.ultimo, c.srv.peticiones) == (0.0, 0)
        assert c.post("/api/guardar", {}, token=None)[0] == 403
        assert (c.srv.ultimo, c.srv.peticiones) == (0.0, 0)
        # Un origen ajeno tampoco cuenta.
        assert c.get("/api/flujos",
                     cabeceras={"Origin": "http://evil.example"})[0] == 403
        assert (c.srv.ultimo, c.srv.peticiones) == (0.0, 0)
        # La que SI pasa el guardia es la unica que rearma.
        assert c.get("/api/flujos")[0] == 200
        assert c.srv.peticiones == 1 and c.srv.ultimo > 0.0


def test_una_conexion_a_medias_no_deja_el_hilo_clavado(monkeypatch):
    """REGRESION: sin `timeout` de handler, 40 conexiones = 40 hilos eternos.

    La linea de peticion se lee ANTES del token, asi que esto era pre-auth:
    cualquier proceso local dejaba hilos bloqueados para siempre dentro del
    proceso del REPL del dueno (medido: `active_count` de 2 a 42, y en 42 diez
    segundos despues). Aqui el timeout se acorta para que el test dure medio
    segundo en vez de los 15 s de produccion.
    """
    assert E._Handler.timeout == E.TIMEOUT_CONEXION_S   # el de produccion
    monkeypatch.setattr(E._Handler, "timeout", 0.5)
    with servidor() as c:
        base = threading.active_count()
        s = socket.socket()
        s.settimeout(10)
        s.connect(("127.0.0.1", c.puerto))
        try:
            s.sendall(b"GET /api/flujos HTTP/1.0\r\n")   # cabeceras SIN cerrar
            # El servidor corta por timeout y cierra: el cliente ve EOF.
            assert s.recv(100) == b""
        finally:
            s.close()
        for _ in range(60):
            if threading.active_count() <= base:
                break
            time.sleep(0.1)
        assert threading.active_count() <= base


def test_un_content_length_que_miente_responde_400_y_suelta_el_hilo(monkeypatch):
    """REGRESION: `rfile.read(n)` con el `Content-Length` que le den.

    Un POST que anuncia 4000 bytes y manda 5 dejaba el hilo clavado para
    siempre dentro del `read`. Ahora la lectura la acotan el timeout del
    socket y `TOPE_LECTURA_S`, y el endpoint contesta su 400.
    """
    monkeypatch.setattr(E._Handler, "timeout", 0.5)
    with servidor() as c:
        base = threading.active_count()
        t0 = time.time()
        r = crudo(c.puerto,
                  ("POST /api/guardar HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n"
                   "X-Cognia-Token: %s\r\nContent-Length: 4000\r\n\r\nabcde"
                   % (c.puerto, c.token)).encode("ascii"), espera=10)
        assert b"400" in r.split(b"\r\n")[0], r
        assert time.time() - t0 < 8.0
        for _ in range(60):
            if threading.active_count() <= base:
                break
            time.sleep(0.1)
        assert threading.active_count() <= base


def test_un_cuerpo_por_encima_del_tope_se_rechaza_sin_leerlo():
    """El tope se mira ANTES de tocar el socket: ni memoria ni espera.

    Un flujo grande son decenas de KB; que el tope sea 1 MB es lo que impide
    que una sola peticion se coma la memoria del REPL.
    """
    assert E.TOPE_CUERPO <= 2 * 1024 * 1024
    with servidor() as c:
        t0 = time.time()
        r = crudo(c.puerto,
                  ("POST /api/guardar HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n"
                   "X-Cognia-Token: %s\r\nContent-Length: %d\r\n\r\n"
                   % (c.puerto, c.token, E.TOPE_CUERPO + 1)).encode("ascii"),
                  espera=10)
        assert b"400" in r.split(b"\r\n")[0], r
        # Sin leer un solo byte del cuerpo: la respuesta es inmediata.
        assert time.time() - t0 < 5.0


def test_el_token_de_la_query_abre_la_pagina():
    """La primera apertura llega por `?t=<token>`, no por cabecera."""
    F.guardar(flujo_lineal("informe"), nota="inicial")
    with servidor("informe") as c:
        code, j = c.get("/?t=" + c.token, token=None)
        assert code == 200
        assert "<!doctype html>" in str(j.get("crudo", "")).lower()


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------

def test_guardar_crea_version_nueva():
    F.guardar(flujo_lineal("informe"), nota="inicial")
    assert n_versiones_en_disco() == 1
    with servidor("informe") as c:
        nuevo = flujo_lineal("informe", args="otras_notas.md")
        code, j = c.post("/api/guardar", {"nombre": "informe", "flujo": nuevo,
                                          "nota": "cambio la fuente",
                                          "pos": {"leer": {"x": 96, "y": 128}}})
    assert code == 200 and j["ok"] is True
    assert j["version"] == 2
    assert (F.dir_base() / F.slugificar("informe") / "v2.json").exists()
    assert nodo(F.cargar("informe"), "leer")["args"] == "otras_notas.md"
    # El `pos` que viaja con el guardado tambien se persiste.
    assert F.leer_ui("informe")["pos"]["leer"] == {"x": 96, "y": 128}


def test_guardar_con_ciclo_devuelve_400_y_no_escribe():
    F.guardar(flujo_lineal("informe"), nota="inicial")
    antes = n_versiones_en_disco()
    ciclo = {"nombre": "informe", "nodos": [
        {"id": "a", "tool": "leer_archivo", "args": "x", "wires": ["b"]},
        {"id": "b", "tool": "leer_archivo", "args": "y", "wires": ["a"]},
    ]}
    with servidor("informe") as c:
        code, j = c.post("/api/guardar", {"nombre": "informe", "flujo": ciclo})
    assert code == 400
    assert j["ok"] is False
    assert "ciclo" in j["error"].lower()
    assert n_versiones_en_disco() == antes   # no se escribio NADA
    assert nodo(F.cargar("informe"), "leer")["args"] == "notas.md"


def test_guardar_con_tool_inexistente_devuelve_400():
    F.guardar(flujo_lineal("informe"), nota="inicial")
    antes = n_versiones_en_disco()
    inventado = {"nombre": "informe", "nodos": [
        {"id": "a", "tool": "tool_que_no_existe_jamas", "args": "x",
         "wires": []},
    ]}
    with servidor("informe") as c:
        code, j = c.post("/api/guardar",
                         {"nombre": "informe", "flujo": inventado})
    assert code == 400
    assert "tool_que_no_existe_jamas" in j["error"]
    assert n_versiones_en_disco() == antes


def test_validar_no_escribe_y_da_el_motivo_real():
    with servidor() as c:
        code, j = c.post("/api/validar", {"flujo": flujo_lineal("x")})
        assert code == 200 and j["ok"] is True
        assert j["orden"] == ["leer", "escribir"]
        colgado = {"nombre": "x", "nodos": [
            {"id": "a", "tool": "leer_archivo", "args": "y", "wires": ["ff"]}]}
        code2, j2 = c.post("/api/validar", {"flujo": colgado})
        # 200 a proposito: un flujo a medias no es un error de la peticion.
        assert code2 == 200 and j2["ok"] is False
        assert "ff" in j2["error"]
    assert n_versiones_en_disco() == 0


# ---------------------------------------------------------------------------
# Posiciones
# ---------------------------------------------------------------------------

def test_pos_no_crea_version():
    F.guardar(flujo_lineal("informe"), nota="inicial")
    with servidor("informe") as c:
        for i in range(20):
            code, j = c.post("/api/pos", {"nombre": "informe", "pos": {
                "leer": {"x": 16 * i, "y": 32}, "escribir": {"x": 240, "y": 32}}})
            assert code == 200 and j["ok"] is True
    assert n_versiones_en_disco() == 1
    pos = F.leer_ui("informe")["pos"]
    assert sorted(pos) == ["escribir", "leer"]
    assert pos["leer"] == {"x": 16 * 19, "y": 32}
    assert len(F.versiones("informe")) == 1


def test_pos_de_flujo_inexistente_es_404():
    with servidor() as c:
        code, j = c.post("/api/pos", {"nombre": "no-existe",
                                      "pos": {"a": {"x": 1, "y": 2}}})
    assert code == 404 and j["ok"] is False


# ---------------------------------------------------------------------------
# Chat con el modelo (flujo_ia monkeypatcheado: ni red ni backend)
# ---------------------------------------------------------------------------

def test_chat_usa_flujo_ia_y_devuelve_el_flujo_saneado(monkeypatch):
    visto = {}
    salida = flujo_lineal("informe", args="ya_editado.md")

    def falso(flujo, mensaje, **kw):
        visto["flujo"] = flujo
        visto["mensaje"] = mensaje
        visto["kw"] = kw
        return flujo_ia.Resultado(ok=True, flujo=salida, motivo="ok",
                                  resumen="cambie la fuente", ms=42,
                                  modelo="pensar-qwen38")

    monkeypatch.setattr(flujo_ia, "editar", falso)
    entrada = flujo_lineal("informe")
    with servidor("informe") as c:
        code, j = c.post("/api/chat", {"nombre": "informe", "flujo": entrada,
                                       "mensaje": "lee otras notas"})
    assert code == 200
    assert j["ok"] is True
    assert j["flujo"] == salida
    assert j["resumen"] == "cambie la fuente"
    assert j["ms"] == 42 and j["modelo"] == "pensar-qwen38"
    assert visto["mensaje"] == "lee otras notas"
    assert visto["flujo"] == entrada
    # El servidor le da el registro REAL de tools, no una lista inventada.
    assert visto["kw"]["tool_existe"]("leer_archivo") is True
    assert visto["kw"]["tool_existe"]("tool_que_no_existe_jamas") is False
    assert "leer_archivo" in visto["kw"]["listar_tools"]()


def test_chat_fallo_devuelve_motivo_y_no_toca_el_flujo(monkeypatch):
    def falso(flujo, mensaje, **kw):
        return flujo_ia.Resultado(ok=False, flujo=dict(flujo),
                                  motivo="el modelo no devolvio JSON")

    monkeypatch.setattr(flujo_ia, "editar", falso)
    F.guardar(flujo_lineal("informe"), nota="inicial")
    entrada = flujo_lineal("informe")
    with servidor("informe") as c:
        code, j = c.post("/api/chat", {"nombre": "informe", "flujo": entrada,
                                       "mensaje": "haz magia"})
    assert code == 200
    assert j["ok"] is False
    assert j["motivo"] == "el modelo no devolvio JSON"
    assert j["flujo"] == entrada          # vuelve EXACTAMENTE como entro
    assert n_versiones_en_disco() == 1    # el chat no guarda nada


def test_chat_sin_mensaje_no_llama_al_modelo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(flujo_ia, "editar",
                        lambda *a, **k: llamadas.append(1))
    with servidor() as c:
        code, j = c.post("/api/chat", {"flujo": flujo_lineal("x"),
                                       "mensaje": "   "})
    assert code == 200 and j["ok"] is False
    assert llamadas == []


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def test_catalogo_trae_las_tools_reales_con_categoria():
    from cognia.agent import tools as _tools
    with servidor() as c:
        code, j = c.get("/api/catalogo")
    assert code == 200 and j["ok"] is True
    nombres = {n["nombre"] for n in j["nodos"]}
    assert "leer_archivo" in nombres
    assert nombres <= set(_tools.TOOLS)
    assert len(nombres) >= 40
    por_nombre = {n["nombre"]: n for n in j["nodos"]}
    assert por_nombre["leer_archivo"]["categoria"] == "lectura"
    assert all(n["categoria"] for n in j["nodos"])
    assert j["categorias"] and all(c2["id"] for c2 in j["categorias"])
    # Las categorias NO repiten los nodos: seria duplicar el catalogo entero.
    assert all("nodos" not in c2 for c2 in j["categorias"])


def test_flujo_trae_layout_versiones_y_pos():
    F.guardar(flujo_lineal("informe"), nota="inicial")
    F.guardar(flujo_lineal("informe", args="v2.md"), nota="segunda")
    F.guardar_ui("informe", {"pos": {"leer": {"x": 500, "y": 700}}})
    with servidor("informe") as c:
        code, j = c.get("/api/flujo?nombre=informe")
        assert code == 200 and j["ok"] is True
        assert j["version"] == 2
        assert nodo(j["flujo"], "leer")["args"] == "v2.md"
        assert j["ui"]["pos"]["leer"] == {"x": 500, "y": 700}
        cajas = {b["id"]: b for b in j["layout"]["cajas"]}
        assert (cajas["leer"]["x"], cajas["leer"]["y"]) == (500, 700)
        assert cajas["leer"]["pos_manual"] is True
        assert cajas["escribir"]["pos_manual"] is False
        assert [v["v"] for v in j["versiones"]] == [2, 1]
        # Una version vieja se pide por ?v=
        code2, j2 = c.get("/api/flujo?nombre=informe&v=1")
        assert code2 == 200 and j2["version"] == 1
        assert nodo(j2["flujo"], "leer")["args"] == "notas.md"
        # Un flujo que no existe es 404 con el motivo real, no un 500.
        code3, j3 = c.get("/api/flujo?nombre=no-existe")
        assert code3 == 404 and j3["ok"] is False
        assert "no-existe" in j3["error"]
        # Y la lista de flujos sale de flujoteca.listar()
        code4, j4 = c.get("/api/flujos")
        assert code4 == 200
        assert [f["nombre"] for f in j4["flujos"]] == ["informe"]


def test_restaurar_crea_una_version_nueva():
    F.guardar(flujo_lineal("informe"), nota="inicial")
    F.guardar(flujo_lineal("informe", args="v2.md"), nota="segunda")
    with servidor("informe") as c:
        code, j = c.post("/api/restaurar", {"nombre": "informe", "version": 1,
                                            "nota": "vuelvo a la primera"})
    assert code == 200 and j["ok"] is True
    assert j["version"] == 3
    assert nodo(F.cargar("informe"), "leer")["args"] == "notas.md"
    assert len(F.versiones("informe")) == 3   # no trunca el historial


# ---------------------------------------------------------------------------
# La via peligrosa que NO esta cableada
# ---------------------------------------------------------------------------

def test_ejecutar_no_existe_y_lo_dice_con_su_motivo():
    with servidor() as c:
        code, j = c.post("/api/ejecutar", {"nombre": "informe"})
    assert code == 404
    assert j["ok"] is False
    # El motivo REAL (no hay canal de confirmacion en un navegador).
    assert "confirmacion" in j["error"]


def test_el_404_de_ejecutar_apunta_al_comando_que_SI_existe():
    """El texto viejo mandaba a poner `COGNIA_EDITOR_EJECUTAR=1`, y esa
    variable NO LA LEE NADIE en todo el repo: el dueno la ponia, reiniciaba y
    seguia con el mismo 404, sin nada que le dijera por donde se ejecuta de
    verdad. Ahora nombra el comando del REPL, que si existe.

    El grep sobre el repo es parte del test a proposito: es lo que convierte
    "ese texto ya no aparece" en "esa promesa no se puede volver a hacer".
    """
    import pathlib

    with servidor() as c:
        code, j = c.post("/api/ejecutar", {"nombre": "informe"})
    assert code == 404
    assert "/flujoteca ejecutar" in j["error"], j["error"]
    assert "COGNIA_EDITOR_EJECUTAR" not in j["error"], j["error"]

    fuente = pathlib.Path(E.__file__).read_text(encoding="utf-8")
    lee = [l for l in fuente.splitlines()
           if "COGNIA_EDITOR_EJECUTAR" in l and "environ" in l]
    assert lee == [], (
        "si alguien cablea de verdad la variable, este test sobra; mientras "
        "no la lea nadie, el modulo no puede prometerla: %s" % lee)


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

def test_el_servidor_se_apaga_y_libera_el_puerto():
    srv = E.crear_server(puerto=0)
    puerto = srv.server_address[1]
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    try:
        assert E._escuchando(puerto, 2) is True
    finally:
        srv.shutdown()
        srv.server_close()
        hilo.join(timeout=5)
    assert not hilo.is_alive()
    # El puerto vuelve a estar libre: si no, cada apertura dejaria uno muerto.
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", puerto))
    finally:
        s.close()


def test_abrir_no_bloquea_y_reusa_el_mismo_servidor(monkeypatch):
    abiertas = []
    monkeypatch.setattr(E.webbrowser, "open", lambda u: abiertas.append(u))
    F.guardar(flujo_lineal("informe"), nota="inicial")
    F.guardar(flujo_lineal("otro"), nota="inicial")
    try:
        a = E.abrir("informe", open_browser=True, timeout_s=5)
        assert a["puerto"] > 0 and a["token"] and a["nuevo"] is True
        assert a["url"].startswith("http://127.0.0.1:%d/?t=" % a["puerto"])
        assert abiertas == [a["url"]]
        assert E.estado()["vivo"] is True
        assert E.estado()["nombre"] == "informe"
        # Abrir otro flujo NO levanta un segundo servidor.
        b = E.abrir("otro", open_browser=False, timeout_s=5)
        assert b["puerto"] == a["puerto"] and b["nuevo"] is False
        assert b["token"] == a["token"]
        assert E.estado()["nombre"] == "otro"
        assert len(abiertas) == 1
        # Y el servidor que quedo sirve de verdad la pagina del flujo abierto.
        req = urllib.request.Request(a["base"] + "/api/flujo?nombre=otro")
        req.add_header("X-Cognia-Token", a["token"])
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
        assert j["ok"] is True and j["nombre"] == "otro"
    finally:
        E.parar()
    assert E.estado()["vivo"] is False
    E.parar()   # idempotente: llamarla dos veces no es un error


def test_cerrar_apaga_el_servidor_QUE_ATENDIO_la_peticion():
    """/api/cerrar cierra ESE servidor, no "el del singleton".

    Un `parar()` a secas dejaria vivo el servidor levantado a mano y mataria
    en su lugar el que estuviera abierto en otra pestana.
    """
    import time as _t
    with servidor() as c:
        code, j = c.post("/api/cerrar", {})
        assert code == 200 and j["ok"] is True
        # El apagado va diferido 0,2 s para que la respuesta salga por el
        # socket: se espera al hecho (deja de atender), no al flag.
        muerto = False
        for _ in range(60):
            try:
                c.get("/api/flujos")
            except OSError:
                muerto = True
                break
            _t.sleep(0.1)
        assert muerto, "el servidor siguio atendiendo despues de /api/cerrar"
        assert c.srv.parando is True


def test_si_el_hilo_del_bucle_no_arranca_ni_miente_ni_cuelga(monkeypatch):
    """REGRESION SEVERA: el `atexit` colgaba el proceso PARA SIEMPRE.

    `abrir()` publicaba `_SERVER = srv` ANTES de `hilo.start()`. Con el hilo
    sin poder arrancar (`RuntimeError: can't start new thread`, por
    agotamiento de hilos o poca memoria), quedaba un servidor con bind+listen
    y SIN bucle: `estado()` decia `vivo: True` -el socket acepta el handshake,
    asi que hasta `_escuchando()` lo confirmaba- y al salir el proceso el
    `atexit` llamaba a `shutdown()`, que en `socketserver` espera un `Event`
    que solo pone el `finally` de `serve_forever()`. Reproducido de punta a
    punta: el proceso no podia salir ni con Ctrl-C (`EXIT=124`).
    """
    creados = []
    real_crear = E.crear_server
    real_start = threading.Thread.start

    def crear_espiado(*a, **k):
        srv = real_crear(*a, **k)
        creados.append(srv)
        return srv

    def start_que_falla(self, *a, **k):
        if self.name == "cognia-editor-flujos":
            raise RuntimeError("can't start new thread")
        return real_start(self, *a, **k)

    monkeypatch.setattr(E, "crear_server", crear_espiado)
    monkeypatch.setattr(threading.Thread, "start", start_que_falla)

    with pytest.raises(RuntimeError):
        E.abrir("informe", open_browser=False, timeout_s=0.2)

    # 1. El singleton NO se publica: `estado()` dice la verdad.
    assert E.estado()["vivo"] is False
    assert E.estado()["puerto"] == 0
    # 2. El socket del servidor fallido queda cerrado, no colgando.
    assert len(creados) == 1
    srv = creados[0]
    assert E._vivo(srv) is False
    assert E._escuchando(int(srv.server_address[1]), 0.3) is False
    # 3. Y el apagado (el mismo que corre en el `atexit`) VUELVE.
    t0 = time.time()
    E.parar()
    tardo = time.time() - t0
    assert tardo < 2.0, "parar() tardo %.1f s" % tardo


def test_apagar_no_pide_shutdown_sobre_un_bucle_que_nunca_arranco():
    """La otra mitad del arreglo: `_apagar` mira el hilo antes de bloquear."""
    srv = E.crear_server(puerto=0)
    puerto = int(srv.server_address[1])
    # Un hilo creado y JAMAS arrancado: `is_alive()` es False, que es la
    # firma exacta de "el bucle no corrio".
    srv.hilo = threading.Thread(target=lambda: None,
                                name="cognia-editor-flujos", daemon=True)
    assert E._bucle_corriendo(srv) is False
    t0 = time.time()
    E._apagar(srv)                 # con el codigo de antes: no volvia nunca
    tardo = time.time() - t0
    assert tardo < 2.0, "_apagar tardo %.1f s" % tardo
    # Y el puerto queda libre igual: `server_close()` va siempre.
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", puerto))
    finally:
        s.close()


def test_apagar_tiene_tope_de_tiempo_aunque_no_sepa_del_hilo():
    """Cinturon y tirantes: un `shutdown()` lento no puede ser eterno.

    Sin `srv.hilo` (un servidor levantado a mano) se asume que el bucle
    corre, asi que la unica defensa es el tope: se pide el `shutdown()` en un
    hilo aparte y se le espera lo justo.
    """
    srv = E.crear_server(puerto=0)
    assert srv.hilo is None and E._bucle_corriendo(srv) is True
    t0 = time.time()
    E._apagar(srv, timeout_s=0.3)
    tardo = time.time() - t0
    assert 0.2 < tardo < 3.0, "_apagar tardo %.2f s" % tardo
    assert E._vivo(srv) is False
    # El hilo aparcado en ese `shutdown()` se suelta aqui: es un daemon y no
    # impide salir, pero este fichero no deja hilos vivos a los que vengan
    # detras (por eso se toca el Event privado, y solo desde el test).
    srv._BaseServer__is_shut_down.set()


def test_el_vigia_apaga_el_editor_tras_la_inactividad(monkeypatch):
    """El auto-apagado no tenia NI UN test: aqui esta el primero."""
    monkeypatch.setattr(E.webbrowser, "open", lambda u: None)
    monkeypatch.setattr(E, "LATIDO_S", 0.1)
    monkeypatch.setattr(E, "INACTIVIDAD_MIN", 0.5 / 60.0)    # medio segundo
    a = E.abrir("informe", open_browser=False, timeout_s=5)
    assert E.estado()["vivo"] is True
    assert E.estado()["aviso"] == ""
    for _ in range(80):
        if not E.estado()["vivo"]:
            break
        time.sleep(0.1)
    assert E.estado()["vivo"] is False
    # Y de verdad: el puerto deja de aceptar conexiones. Se espera al HECHO y
    # no al flag: el vigia vacia el singleton ANTES de apagar, asi que entre
    # `vivo: False` y el `server_close()` caben los ~0,5 s del ultimo latido
    # de `serve_forever`.
    for _ in range(60):
        if not E._escuchando(a["puerto"], 0.1):
            break
        time.sleep(0.1)
    assert E._escuchando(a["puerto"], 0.3) is False


def test_solo_una_peticion_VALIDA_pospone_el_auto_apagado(monkeypatch):
    """El reloj lo rearma quien pasa el guardia, y nadie mas.

    Es el hallazgo de `_marcar()` antes de `_pasa()` visto de punta a punta:
    antes, machacar el puerto con tokens malos mantenia el editor vivo para
    siempre sin credencial.
    """
    monkeypatch.setattr(E.webbrowser, "open", lambda u: None)
    monkeypatch.setattr(E, "LATIDO_S", 0.1)
    monkeypatch.setattr(E, "INACTIVIDAD_MIN", 1.5 / 60.0)    # 1,5 s de ocio
    a = E.abrir("informe", open_browser=False, timeout_s=5)

    def pedir(token):
        req = urllib.request.Request(a["base"] + "/api/flujos")
        req.add_header("X-Cognia-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as exc:
            exc.read()
            return exc.code

    try:
        # 1. Peticiones BUENAS cada 0,2 s durante 2,5 s (mas que el ocio):
        #    el editor sigue vivo porque cada una rearma el reloj.
        fin = time.time() + 2.5
        while time.time() < fin:
            assert pedir(a["token"]) == 200
            time.sleep(0.2)
        assert E.estado()["vivo"] is True

        # 2. Las mismas peticiones con token MALO no cuentan: el editor se
        #    apaga igual, aunque el puerto no pare de recibir golpes.
        muerto = False
        fin = time.time() + 8.0
        while time.time() < fin:
            try:
                assert pedir("no-es-el-token") == 403
            except OSError:
                muerto = True         # ya no atiende: se apago
                break
            if not E.estado()["vivo"]:
                muerto = True
                break
            time.sleep(0.2)
        assert muerto, "los 403 mantuvieron vivo el editor"
        assert E.estado()["vivo"] is False
    finally:
        E.parar()


def test_si_el_vigia_no_arranca_el_editor_sirve_pero_lo_DICE(monkeypatch):
    """Degradar en silencio esta prohibido: el aviso sale en `estado()`."""
    monkeypatch.setattr(E.webbrowser, "open", lambda u: None)
    real_start = threading.Thread.start

    def start_sin_vigia(self, *a, **k):
        if self.name == "cognia-editor-vigia":
            raise RuntimeError("can't start new thread")
        return real_start(self, *a, **k)

    monkeypatch.setattr(threading.Thread, "start", start_sin_vigia)
    try:
        a = E.abrir("informe", open_browser=False, timeout_s=5)
        est = E.estado()
        assert est["vivo"] is True            # el editor sirve igual
        assert "vigilante" in est["aviso"] and "no se apagara solo" in est["aviso"]
        req = urllib.request.Request(a["base"] + "/api/flujos")
        req.add_header("X-Cognia-Token", a["token"])
        with urllib.request.urlopen(req, timeout=10) as r:
            assert json.loads(r.read().decode("utf-8"))["ok"] is True
    finally:
        monkeypatch.undo()
        E.parar()


def test_bind_fuera_de_localhost_se_rechaza():
    with pytest.raises(ValueError):
        E.crear_server(host="0.0.0.0", puerto=0)


def test_cerrar_apaga_el_servidor_del_singleton(monkeypatch):
    monkeypatch.setattr(E.webbrowser, "open", lambda u: None)
    a = E.abrir("", open_browser=False, timeout_s=5)
    try:
        req = urllib.request.Request(a["base"] + "/api/cerrar", data=b"{}",
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Cognia-Token", a["token"])
        with urllib.request.urlopen(req, timeout=10) as r:
            assert json.loads(r.read().decode("utf-8"))["ok"] is True
        # El apagado va diferido en un thread para que la respuesta salga.
        for _ in range(50):
            if not E.estado()["vivo"]:
                break
            import time as _t
            _t.sleep(0.1)
        assert E.estado()["vivo"] is False
    finally:
        E.parar()


# ---------------------------------------------------------------------------
# El chat dice POR DONDE salio (2026-08-29)
#
# `via` no es decoracion: el ROJO C del e2e (5 de 6 casos con "no cupo en el
# presupuesto de tokens" sobre un flujo de 7 nodos) se diagnostico separando
# el coste del JSON del coste del razonamiento. Sin este campo, un turno que
# salio por el respaldo caro y uno que salio por el delta barato se ven
# exactamente igual desde el navegador.
# ---------------------------------------------------------------------------

def test_chat_dice_por_que_via_salio(monkeypatch):
    def falso(flujo, mensaje, **kw):
        return flujo_ia.Resultado(ok=True, flujo=flujo_lineal("informe"),
                                  motivo="ok", resumen="", ms=9,
                                  modelo="m", via="delta")

    monkeypatch.setattr(flujo_ia, "editar", falso)
    with servidor("informe") as c:
        code, j = c.post("/api/chat", {"nombre": "informe",
                                       "flujo": flujo_lineal("informe"),
                                       "mensaje": "anade un paso"})
    assert code == 200 and j["via"] == "delta"


def test_chat_siempre_manda_via_aunque_el_resultado_no_la_traiga(monkeypatch):
    """El cliente lee `via` sin comprobar; un resultado viejo (o de un doble
    de test) no puede dejar la clave sin poner."""
    class _Viejo:
        ok = False
        flujo = {}
        motivo = "el modelo no devolvio JSON"
        resumen = ""
        ms = 3
        modelo = "m"

    monkeypatch.setattr(flujo_ia, "editar", lambda *a, **k: _Viejo())
    entrada = flujo_lineal("informe")
    with servidor("informe") as c:
        code, j = c.post("/api/chat", {"nombre": "informe", "flujo": entrada,
                                       "mensaje": "anade un paso"})
    assert code == 200 and j["via"] == ""
    assert j["flujo"] == entrada


# ---------------------------------------------------------------------------
# La lista de tools que ve el modelo: ACOTADA y CON FIRMA
# ---------------------------------------------------------------------------
# POR QUE (PLAN2 5.1 punto 3). `_listar_tools` devolvia las 70 del registro y
# `flujo_ia._lineas_de_tools` pinta UNA LINEA POR TOOL con su firma y su
# descripcion: ~7,5 KB de prompt en cada turno del chat del editor. Con eso el
# presupuesto del delta se agota antes de escribir el JSON y el turno vuelve
# ok:false -- 5 de los 6 casos del e2e del editor. Estos tests corren contra
# el REGISTRO REAL y el CATALOGO REAL: un fake no mediria el tamano, que es
# justo lo que aqui se mide.

def _flujo_dos_tools():
    return flujo_lineal("informe")


def test_listar_tools_sin_contexto_sigue_devolviendo_el_registro_entero():
    """Quien no da flujo ni mensaje no puede recibir una lista recortada: es
    el contrato viejo, y hay llamadores (el CLI) que no tienen pedido."""
    from cognia.agent import tools as _tools

    assert E._listar_tools() == sorted(_tools.TOOLS)


def test_listar_tools_acota_pero_nunca_pierde_las_que_el_flujo_YA_usa():
    from cognia.agent import tools as _tools

    todas = sorted(_tools.TOOLS)
    assert len(todas) >= 40, "registro demasiado pobre para medir el acotado"

    acotada = E._listar_tools(_flujo_dos_tools(),
                              "anade un paso que copie el informe a informe.bak")
    # 1. Las del flujo, SIEMPRE: "usa SOLO estas" con una tool del flujo
    #    fuera de la lista invita al modelo a reescribir nodos que no tocaba.
    assert "leer_archivo" in acotada
    assert "escribir_archivo" in acotada
    # 2. Acotada de verdad: nunca las 70.
    assert len(acotada) <= 2 + E.TOPE_CANDIDATAS
    assert len(acotada) < len(todas) / 2, len(acotada)
    # 3. Y las candidatas salen del PEDIDO: "copie" trae copiar_archivo.
    assert "copiar_archivo" in acotada, acotada
    # 4. Todo lo que sale existe: una lista con un nombre inventado le ensena
    #    al modelo a usarlo (la leccion del ejemplo con la tool inventada).
    assert not set(acotada) - set(todas)
    # 5. Determinista: el mismo turno, la misma lista.
    assert E._listar_tools(_flujo_dos_tools(),
                           "anade un paso que copie el informe a informe.bak") \
        == acotada


def test_un_pedido_que_no_casa_con_nada_recibe_igual_una_base_util():
    """"hazlo reintentable" no nombra ninguna tool. La lista no puede quedar
    en las dos del flujo: el modelo se quedaria sin con que anadir un paso."""
    acotada = E._listar_tools(_flujo_dos_tools(), "hazlo reintentable")
    assert len(acotada) >= 5, acotada
    assert "escribir_archivo" in acotada and "prompt" in acotada


def test_el_prompt_del_editor_lleva_la_FIRMA_de_cada_tool_y_cabe(monkeypatch):
    """DE PUNTA A PUNTA por la puerta del producto (POST /api/chat), con el
    registro y el catalogo REALES, midiendo lo que de verdad le llega al
    modelo: se intercepta `flujo_ia._generar`, que es el ultimo escalon antes
    del backend.

    Mide las dos mitades del arreglo:
      - que la firma POSICIONAL de cada tool de >=2 params esta en el prompt
        (sin ella el modelo se inventa la forma de los args: es la causa raiz
        de "los workflows no entregan nada"), y
      - que el bloque de tools CABE (antes eran las 70).
    """
    from cognia.agent import catalogo_nodos as cn

    visto = {}

    def _falso_generar(prompt, system, **kw):
        visto["prompt"] = prompt
        visto["system"] = system
        return json.dumps({"resumen": "nada que cambiar", "ops": []})

    monkeypatch.setattr(flujo_ia, "_generar", _falso_generar)

    with servidor("informe") as c:
        code, j = c.post("/api/chat", {
            "nombre": "informe", "flujo": _flujo_dos_tools(),
            "mensaje": "anade un paso que copie el informe a informe.bak"})
    assert code == 200, j
    p = visto["prompt"]

    # -- la firma posicional de TODA tool de >=2 params que salga en el bloque
    bloque = p.split("Tools disponibles (usa SOLO estas):", 1)
    assert len(bloque) == 2, p[:400]
    lineas = [l for l in bloque[1].splitlines() if l.startswith("- ")]
    assert lineas, bloque[1][:300]

    fichas = {e["nombre"]: e for e in cn.catalogo()}
    ofrecidas = [n for n in fichas if any(
        l.startswith("- " + n + "(") or l.startswith("- " + n + " ")
        or l == "- " + n or l.startswith("- " + n + ":") for l in lineas)]
    con_params = [n for n in ofrecidas if len(fichas[n]["params"]) >= 2]
    assert con_params, ("ninguna tool ofrecida declara 2 params: el test no "
                        "estaria midiendo nada. Ofrecidas: %s" % ofrecidas)
    for n in con_params:
        firma = "%s(%s)" % (n, ", ".join(
            pa["nombre"] if pa.get("requerido") else pa["nombre"] + "?"
            for pa in fichas[n]["params"]))
        assert any(l == "- " + firma or l.startswith("- " + firma + ":")
                   for l in lineas), (
            "el prompt no ensena la firma posicional de %s (esperaba %r)"
            % (n, firma))

    # escribir_archivo es la del bug: dos posicionales, y el flujo la usa.
    assert any(l.startswith("- escribir_archivo(path, contenido)")
               for l in lineas), lineas

    # -- y el bloque CABE: antes eran las 70 tools del registro
    from cognia.agent import tools as _tools
    assert len(lineas) <= 2 + E.TOPE_CANDIDATAS, len(lineas)
    assert len(lineas) < len(_tools.TOOLS) / 2, len(lineas)
    assert len(bloque[1]) < 2500, (
        "el bloque de tools ocupa %d chars: con eso vuelve el problema de "
        "presupuesto que costo 5 de 6 casos del e2e" % len(bloque[1]))

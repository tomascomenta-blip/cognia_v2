"""
Tests del STREAMING del bucle del agente (2026-08-26).

LA AVERIA QUE CUBREN
--------------------
`chat_client.completar()` tiene rama SSE desde el 2026-08-17, con 55 tests
verdes en test_chat_client_stream.py... y NADIE la usaba: hasta hoy,
`grep -rn "on_token=" cognia/` devolvia UN solo resultado, la propia firma de
completar(). Todo el agente iba por el camino NO-stream.

Y en el camino no-stream el docstring de completar() ("el timeout es de
INACTIVIDAD, no de pared -- en los DOS caminos") es FALSO: llama-server no
manda un solo byte hasta terminar la generacion entera, asi que la PRIMERA
lectura del socket ya espera la respuesta completa y el timeout de urlopen se
comporta como un deadline de PARED sobre toda la generacion.

Consecuencia MEDIDA en produccion: el 2026-08-26 a las 12:01 una tarea larga
del dueno (una especificacion de videojuego) murio con

    (el agente no pudo hablar con el modelo: TimeoutError: timed out)

y quedo asi en chat_history id 1019. El sintoma que reporto el dueno fue
exactamente "Cognia no responde a tareas largas": las cortas caben en el
presupuesto de pared y las largas no.

El test que lo fija es `test_una_generacion_lenta_no_muere_por_el_reloj`:
server HTTP real (falso, sin modelo) que tarda MAS que el timeout pero nunca
se calla. Sin el fix el bucle vuelve con TimeoutError; con el fix entrega la
respuesta entera.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import (RespuestaChat, completar,
                                      mensaje_assistant, mensaje_tool)
from cognia.agent.tool_schemas import args_legacy, schemas_para


# ── andamio ─────────────────────────────────────────────────────────────────

def _perfil(url="http://127.0.0.1:9", max_tokens=4096):
    return {"nombre": "razonador_nativo", "modelo": "qwen3.8-27b-ridge.gguf",
            "url": url, "tools": "nativo", "n_ctx": 16384,
            "temperature": 0.7, "top_p": 0.8, "reasoning_effort": "",
            "max_tokens": max_tokens}


def _correr(completar_fn, ctx=None, avisos=None, max_turns=4, perfil=None,
            run_tool=None):
    """bucle_nativo con el `completar` que se le pase. Devuelve su dict."""
    def _print(msg, *a, **k):
        if avisos is not None:
            avisos.append(str(msg))

    return loop_mod.bucle_nativo(
        "crea hola.txt", "sos el agente", completar_fn, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool,
        run_tool or (lambda n, a, c: f"RESULTADO {n}: OK"),
        ctx if ctx is not None else {},
        perfil or _perfil(), ["TAREA: crea hola.txt"], [], _print, max_turns)


def _kwargs_de_una_corrida(monkeypatch, env=None, ctx=None):
    """Los kwargs con los que el bucle llamo a completar en su primer paso."""
    for k, v in (env or {}).items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    visto = {}

    def _completar(mensajes, tools=None, **kw):
        visto.update(kw)
        return RespuestaChat(texto="listo", finish_reason="stop")

    _correr(_completar, ctx=ctx)
    return visto


# ── el cableado ─────────────────────────────────────────────────────────────

def test_el_bucle_pide_stream_a_completar(monkeypatch):
    """La regresion nuda: sin estos kwargs, completar() usa el camino
    no-stream y el timeout vuelve a ser de pared."""
    kw = _kwargs_de_una_corrida(monkeypatch, {"COGNIA_STREAM": None})
    assert callable(kw.get("on_token")), kw.keys()
    assert callable(kw.get("on_reasoning")), kw.keys()


def test_COGNIA_STREAM_0_vuelve_al_camino_historico(monkeypatch):
    """El contrafactual: la palanca apaga el stream de verdad."""
    kw = _kwargs_de_una_corrida(monkeypatch, {"COGNIA_STREAM": "0"})
    assert "on_token" not in kw and "on_reasoning" not in kw


def test_el_cancelado_del_ctx_viaja_a_completar(monkeypatch):
    """Con stream, `cancelado` se consulta DURANTE la generacion y no solo
    entre pasos: el Ctrl-C del carril de fondo deja de ser una promesa."""
    corta = lambda: False
    kw = _kwargs_de_una_corrida(monkeypatch, {"COGNIA_STREAM": None},
                                ctx={"_cancelado": corta})
    assert kw.get("cancelado") is corta


def test_sin_cancelado_en_el_ctx_no_se_inventa_uno(monkeypatch):
    kw = _kwargs_de_una_corrida(monkeypatch, {"COGNIA_STREAM": None}, ctx={})
    assert "cancelado" not in kw


# ── el server falso (mismo diseno que el repro de la averia) ────────────────

class _Lento(BaseHTTPRequestHandler):
    """Server que tarda RETRASO segundos. Con stream:true habla cada
    RETRASO/TROZOS segundos (inactividad chica); sin stream se calla hasta el
    final, como llama-server."""
    RETRASO = 3.0
    TROZOS = 10
    SIN_SSE = False        # True = ignora stream:true y contesta 200 pelado
    MUERE_A_MITAD = False  # True = corta el socket tras 3 frames

    def log_message(self, *a):
        pass

    def handle_one_request(self):
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        except Exception:
            self.close_connection = True

    def _cuerpo_no_stream(self):
        return json.dumps({
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": "respuesta larga completa"}}],
            "usage": {"completion_tokens": 10, "prompt_tokens": 5}}).encode()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if not body.get("stream") or self.SIN_SSE:
            time.sleep(self.RETRASO)
            out = self._cuerpo_no_stream()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            self.wfile.flush()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for i in range(self.TROZOS):
            time.sleep(self.RETRASO / self.TROZOS)
            fr = {"choices": [{"index": 0,
                               "delta": {"content": "tok%d " % i}}]}
            self.wfile.write(b"data: " + json.dumps(fr).encode() + b"\n\n")
            self.wfile.flush()
            if self.MUERE_A_MITAD and i == 2:
                self.close_connection = True
                self.wfile.close()
                return
        fin = {"choices": [{"index": 0, "delta": {},
                            "finish_reason": "stop"}],
               "usage": {"completion_tokens": self.TROZOS,
                         "prompt_tokens": 5}}
        self.wfile.write(b"data: " + json.dumps(fin).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


@pytest.fixture
def server_lento():
    """Devuelve (url, clase) para que el test toque los knobs de la clase."""
    class H(_Lento):
        pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1], H
    finally:
        srv.shutdown()
        srv.server_close()


# ── LA REGRESION: el reloj de pared ─────────────────────────────────────────

def test_una_generacion_lenta_no_muere_por_el_reloj(monkeypatch,
                                                    server_lento):
    """EL TEST DE LA AVERIA. Server que tarda 3 s con un presupuesto de 1 s.

    Con stream la inactividad real es de 0,3 s y la respuesta llega entera.
    SIN el fix (COGNIA_STREAM=0) el mismo server mata el turno con
    'TimeoutError: timed out' -- el error literal de chat_history id 1019.
    """
    url, _H = server_lento
    monkeypatch.setenv("COGNIA_CHAT_TIMEOUT", "1")   # presupuesto < RETRASO

    monkeypatch.setenv("COGNIA_STREAM", "1")
    con = _correr(completar, perfil=_perfil(url=url), max_turns=2)

    # max_turns 8 y no 2 en el brazo sin stream: un error de backend gasta
    # vueltas en reintentos (_reint_backend < 2) antes de sellar la causa, y
    # con 2 el turno moria por presupuesto sin llegar a decir el TimeoutError.
    monkeypatch.setenv("COGNIA_STREAM", "0")
    sin = _correr(completar, perfil=_perfil(url=url), max_turns=8)

    # El brazo sin stream muere; el brazo con stream entrega la respuesta.
    assert "timed out" in sin["texto"].lower(), sin["texto"]
    assert sin["ok"] is False
    assert "tok0" in con["texto"], con["texto"]
    assert con["ok"] is True


def test_un_server_que_no_habla_sse_degrada_sin_perder_la_tarea(
        monkeypatch, server_lento):
    """Red de seguridad: si el transporte ignora stream:true, el bucle NO da
    la tarea por perdida -- apaga el stream y repite por el camino
    historico."""
    url, H = server_lento
    H.SIN_SSE = True
    H.RETRASO = 0.0
    monkeypatch.setenv("COGNIA_STREAM", "1")
    monkeypatch.setenv("COGNIA_CHAT_TIMEOUT", "10")
    avisos = []
    out = _correr(completar, avisos=avisos, perfil=_perfil(url=url),
                  max_turns=3)
    assert out["ok"] is True, out["texto"]
    assert "respuesta larga completa" in out["texto"]
    assert any("no respeta stream" in a for a in avisos), avisos


def test_el_texto_parcial_no_se_tira(monkeypatch):
    """Si el socket muere a mitad, lo ya generado se ENTREGA marcado (con
    ok=False) en vez de tirarse. Es el peor caso de una tarea larga: veinte
    minutos de generacion perdidos porque el ultimo tramo no llego."""
    monkeypatch.setenv("COGNIA_STREAM", "1")

    def _completar(mensajes, tools=None, **kw):
        # Lo que devuelve completar() cuando el socket muere a mitad del
        # stream: error Y lo acumulado (contrato de chat_client).
        cb = kw.get("on_token")
        if cb:
            cb("mitad ")
        return RespuestaChat(error="ConnectionResetError: forcibly closed",
                             texto="la mitad de la respuesta")

    out = _correr(_completar, max_turns=8)
    assert out["ok"] is False
    assert "la mitad de la respuesta" in out["texto"], out["texto"]
    assert "ConnectionResetError" in out["texto"]
    # y el corte deja de ser mudo: dice cuantos fragmentos habian llegado
    assert "fragmentos" in out["texto"], out["texto"]


def test_un_error_sin_parcial_sigue_diciendo_la_causa(monkeypatch):
    """No se rompio el caso de siempre: sin nada acumulado, el mensaje es el
    historico (causa visible, sin adornos)."""
    monkeypatch.setenv("COGNIA_STREAM", "1")

    def _completar(mensajes, tools=None, **kw):
        return RespuestaChat(error="TimeoutError: timed out")

    out = _correr(_completar, max_turns=8)
    assert out["ok"] is False
    assert "no pudo hablar con el modelo" in out["texto"]
    assert "TimeoutError" in out["texto"]
    assert "Lo que alcanzo a generar" not in out["texto"]


# ── La racha de fallos y el ciclo escribir/ejecutar/corregir ────────────────

def _llamadas(tools):
    """Una respuesta por tool, con argumentos DISTINTOS -- y con la CLAVE que
    cada tool espera de verdad, porque args_legacy descarta las que no
    conoce: con `{"ruta": ...}` un `ejecutar` serializa a '' y las tres
    llamadas comparten firma, o sea que cortaria GuardiaBucle (otra guarda,
    con su propio test) y este test pasaria por el motivo equivocado."""
    from cognia.agent.chat_client import ToolCall
    clave = {"ejecutar": "comando", "tests": "patron"}
    return [RespuestaChat(
        texto="", finish_reason="tool_calls", usage={},
        tool_calls=[ToolCall(id=f"t{i}", nombre=t,
                             argumentos={clave.get(t, "ruta"):
                                         f"python paso{i}.py"},
                             argumentos_crudos="{}")])
        for i, t in enumerate(tools)]


def _tool_que_falla(n, a, c):
    """Fallo con la convencion del repo: 'ERROR' en la cabeza + exit != 0."""
    return (f"RESULTADO {n} ERROR: exit 1\n"
            "Traceback (most recent call last)")


def test_depurar_no_muere_a_los_3_fallos_de_ejecucion(monkeypatch):
    """El ciclo escribir/ejecutar/corregir produce fallos seguidos POR
    DISENO: el error es la informacion que el agente fue a buscar.

    Regresion MEDIDA: 'razon=bucle_detectado detalle=3 tools seguidas
    fallaron pasos=5' (2026-08-26 11:04:43). Tres intentos de correr algo
    que todavia no compila mataban la tarea."""
    monkeypatch.setenv("COGNIA_STREAM", "0")
    it = iter(_llamadas(["ejecutar"] * 3)
              + [RespuestaChat(texto="Arreglado.", finish_reason="stop",
                               usage={})])
    out = _correr(lambda m, tools=None, **kw: next(it), max_turns=8,
                  run_tool=_tool_que_falla)
    # Lo que se mide es que la tarea NO se corta a la 3ra: llega al 4to paso
    # y entrega la respuesta del modelo. (`ok` sigue False porque la ultima
    # tool fallo de verdad y el cierre lo reporta -- eso es correcto y es
    # otra cosa; asertar sobre `ok` haria pasar este test por el motivo
    # equivocado.)
    assert "Arreglado" in out["texto"], out["texto"]
    assert out["pasos"] == 4, out["pasos"]
    assert "fallaron sin avanzar" not in out["texto"]


def test_la_racha_de_fallos_sigue_cortando_si_no_es_solo_ejecucion(monkeypatch):
    """No se quito el corte: tres fallos de HERRAMIENTA (el agente no sabe
    operar) siguen cerrando el turno."""
    monkeypatch.setenv("COGNIA_STREAM", "0")
    it = iter(_llamadas(["editar_archivo", "escribir_archivo", "leer_archivo"])
              + [RespuestaChat(texto="x", finish_reason="stop", usage={})])
    out = _correr(lambda m, tools=None, **kw: next(it), max_turns=8,
                  run_tool=_tool_que_falla)
    assert not out["ok"], out["texto"]
    assert "fallaron sin avanzar" in out["texto"], out["texto"]


def test_seis_ejecuciones_fallidas_seguidas_si_cortan(monkeypatch):
    """El margen es el DOBLE, no infinito: a la 6ta sigue cerrando."""
    monkeypatch.setenv("COGNIA_STREAM", "0")
    it = iter(_llamadas(["ejecutar"] * 8))
    out = _correr(lambda m, tools=None, **kw: next(it), max_turns=10,
                  run_tool=_tool_que_falla)
    assert not out["ok"], out["texto"]
    assert "fallaron sin avanzar" in out["texto"], out["texto"]


# ── El refund tiene que devolver la vuelta ──────────────────────────────────

def test_el_refund_devuelve_la_vuelta_a_la_tarea(monkeypatch):
    """presupuesto_turno existe para que "la infraestructura no se coma el
    presupuesto de la tarea". Hasta el 2026-08-26 no lo conseguia: la guarda
    real era `pasos`, que nunca baja, asi que `_pres.consume()` no podia
    devolver False jamas y el refund solo movia un numero en el log.

    El turno del voleibol lo enseña: vueltas=5, refunds=3, pasos=2 -- habia
    quemado 5 de sus 8 vueltas para hacer 2 pasos de trabajo real.

    Aca: dos timeouts de backend (que se reintentan y se refundean) no le
    pueden robar pasos a una tarea de presupuesto 3."""
    monkeypatch.setenv("COGNIA_STREAM", "0")
    fallos = [RespuestaChat(error="TimeoutError: timed out")] * 2
    utiles = _llamadas(["ejecutar", "ejecutar"]) + [
        RespuestaChat(texto="Listo.", finish_reason="stop", usage={})]
    it = iter(fallos + utiles)
    n = []

    def _completar(mensajes, tools=None, **kw):
        n.append(1)
        return next(it)

    out = _correr(_completar, max_turns=3)
    assert out["ok"], out["texto"]
    assert "Listo" in out["texto"]
    # 2 vueltas administrativas + 3 pasos REALES de tarea.
    assert len(n) == 5, len(n)


def test_el_fusible_del_techo_bruto_sigue_existiendo(monkeypatch):
    """El corte lo da el contador auditado, pero la guarda del while queda de
    fusible: los refunds no estan acotados globalmente, y sin techo bruto una
    patologia que devolviera una vuelta por vuelta giraria para siempre."""
    monkeypatch.setenv("COGNIA_STREAM", "0")
    n = []

    def _completar(mensajes, tools=None, **kw):
        n.append(1)
        # Siempre error reintentable: el bucle no puede quedarse aqui.
        return RespuestaChat(error="TimeoutError: timed out")

    out = _correr(_completar, max_turns=4)
    assert not out["ok"]
    assert len(n) <= 4 * 3, len(n)      # nunca por encima del fusible


def test_los_reintentos_de_backend_son_una_RACHA_no_un_cupo(monkeypatch):
    """Dos fallos SEGUIDOS son senal de backend caido; dos baches separados
    por trabajo exitoso, no. `_reint_backend` se inicializaba una vez fuera
    del bucle y nunca bajaba: en una tarea larga, tres timeouts sueltos a lo
    largo de media hora la mataban igual que tres seguidos."""
    monkeypatch.setenv("COGNIA_STREAM", "0")
    # El gobernador por progreso corta a las 6 vueltas sin un avance
    # VERIFICADO en disco, y este doble no escribe nada. Es otra guarda, con
    # su propio motivo y su propio test; se apaga para aislar lo que aca se
    # mide (si no, el test pasaria o fallaria por el motivo equivocado).
    monkeypatch.setenv("COGNIA_ESTADO", "0")
    err = RespuestaChat(error="TimeoutError: timed out")
    util = _llamadas(["ejecutar"])[0]
    fin = RespuestaChat(texto="Listo.", finish_reason="stop", usage={})
    # bache - trabajo - bache - trabajo - bache - trabajo - cierre
    it = iter([err, util, err, util, err, util, fin])

    def _completar(mensajes, tools=None, **kw):
        return next(it)

    out = _correr(_completar, max_turns=10)
    assert out["ok"], out["texto"]
    assert "Listo" in out["texto"], out["texto"]


# ── La compactacion no puede comerse un fichero ─────────────────────────────

def test_no_se_escribe_el_marcador_de_truncado_como_contenido(monkeypatch):
    """PASO DE VERDAD, y se reprodujo byte a byte (2026-08-26).

    `_truncar_valores_args` sustituye los valores largos de los assistant
    viejos por `v[:20] + _MARCA_ARG_TRUNCADO` para que el historial no
    arrastre 40 KB de codigo. Ese texto vuelve al modelo dentro de su propio
    tool call, y el modelo lo lee como si fuera el contenido del fichero: lo
    copia y lo reescribe al disco.

    En la corrida del videojuego, `voleibol/game/ai.py` quedo con
    EXACTAMENTE el output de _truncar_valores_args y nada mas -- un modulo
    entero perdido, y en silencio, porque la escritura "salio bien".
    """
    from cognia.agent.chat_client import ToolCall
    from cognia.agent.loop import _truncar_valores_args, _MARCA_ARG_TRUNCADO

    # El veneno se FABRICA con la funcion real, no se escribe a mano: si
    # alguien cambia el marcador, este test sigue midiendo lo que dice.
    envenenado = json.loads(_truncar_valores_args(json.dumps({
        "ruta": "game/ai.py",
        "contenido": "# -*- coding: utf-8 -*-\nclass IA:\n    pass\n" + "x" * 3000,
    })))["contenido"]
    assert _MARCA_ARG_TRUNCADO in envenenado

    monkeypatch.setenv("COGNIA_STREAM", "0")
    crudo = json.dumps({"ruta": "game/ai.py", "contenido": envenenado})
    tc = ToolCall(id="t1", nombre="escribir_archivo",
                  argumentos={"ruta": "game/ai.py", "contenido": envenenado},
                  argumentos_crudos=crudo)
    guion = [
        RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                      tool_calls=[tc]),
        RespuestaChat(texto="Listo.", finish_reason="stop", usage={}),
    ]
    n = []

    def _completar(mensajes, tools=None, **kw):
        n.append(1)
        return guion[min(len(n) - 1, len(guion) - 1)]
    escrituras = []

    def _run_tool(nombre, args, ctx):
        escrituras.append((nombre, args))
        return f"RESULTADO {nombre}: OK"

    avisos = []
    out = _correr(_completar, avisos=avisos, max_turns=6,
                  run_tool=_run_tool)

    assert not escrituras, f"se escribio el marcador al disco: {escrituras}"
    assert any("marcador de truncado" in a for a in avisos), avisos
    # El turno CONTINUA (no lo mata la guarda) y llega a su cierre normal.
    # `ok` queda en False porque una tool fallo de verdad -- eso es correcto y
    # es otra cosa; asertarlo haria pasar el test por el motivo equivocado.
    assert "Listo" in out["texto"], out["texto"]


def test_una_escritura_normal_sigue_pasando(monkeypatch):
    """El contrafactual: la guarda mira el MARCADOR, no el tamano ni la
    tool. Un contenido legitimo se escribe igual que siempre."""
    from cognia.agent.chat_client import ToolCall

    monkeypatch.setenv("COGNIA_STREAM", "0")
    bueno = "# -*- coding: utf-8 -*-\nclass IA:\n    def decidir(self):\n        return 'attack'\n"
    crudo = json.dumps({"ruta": "game/ai.py", "contenido": bueno})
    tc = ToolCall(id="t1", nombre="escribir_archivo",
                  argumentos={"ruta": "game/ai.py", "contenido": bueno},
                  argumentos_crudos=crudo)
    guion = [
        RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                      tool_calls=[tc]),
        RespuestaChat(texto="Listo.", finish_reason="stop", usage={}),
    ]
    n = []

    def _completar(mensajes, tools=None, **kw):
        n.append(1)
        return guion[min(len(n) - 1, len(guion) - 1)]
    escrituras = []

    def _run_tool(nombre, args, ctx):
        escrituras.append((nombre, args))
        return f"RESULTADO {nombre}: OK"

    _correr(_completar, max_turns=6, run_tool=_run_tool)
    assert len(escrituras) == 1, escrituras

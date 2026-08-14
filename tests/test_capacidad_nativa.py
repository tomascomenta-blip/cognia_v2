"""
Tests de LA SONDA (cognia/agent/capacidad.py): ¿este server parsea tool calls?

Estos tests NO usan dobles de urlopen: levantan un servidor HTTP de verdad en
127.0.0.1 (puerto 0) que habla /props y /v1/chat/completions como llama-server.
POR QUE ASI: la sonda existe justo porque declarar una capacidad no es medirla;
verificarla contra un mock de la propia libreria la volveria a declarar. Con un
socket real se ejercita el camino completo (urllib, HTTP, JSON, timeouts).

Los tres casos que decidian mal antes de que existiera la sonda:
  (a) tool_calls bien formados                 -> True
  (b) prosa sin tool_calls (server sin --jinja) -> False
  (c) tool_call con arguments que NO son JSON   -> False
Mas: la contraevidencia (_NATIVO_DESACONSEJADO gana a la sonda), el cache y
que un cache corrupto no rompa nada.

El backend de la maquina (:8080) no se toca: cada test levanta el suyo.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import cognia.backend_activo as ba
from cognia.agent import capacidad


def _respuesta_tool(nombre="ping", arguments='{"x": "hola"}'):
    """Una respuesta de /v1/chat/completions con un tool call."""
    return {"choices": [{"finish_reason": "tool_calls",
                         "message": {"content": "",
                                     "tool_calls": [{
                                         "id": "call_1", "type": "function",
                                         "function": {"name": nombre,
                                                      "arguments": arguments}}]}}],
            "usage": {"completion_tokens": 12}}


_RESPUESTA_PROSA = {
    "choices": [{"finish_reason": "stop",
                 "message": {"content": "Claro, aqui va: ping(x=hola)"}}],
    "usage": {"completion_tokens": 9}}


class _Servidor:
    """llama-server de mentira: /props + /v1/chat/completions. `peticiones`
    lleva la cuenta para poder afirmar que el cache evito la segunda sonda."""

    def __init__(self, respuesta, modelo):
        self.respuesta, self.modelo, self.peticiones = respuesta, modelo, []
        padre = self

        class _H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass                      # sin ruido en la salida de pytest

            def _responder(self, payload):
                cuerpo = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def do_GET(self):
                padre.peticiones.append(("GET", self.path))
                if self.path.rstrip("/") == "/props":
                    self._responder({
                        "model_path": f"C:/modelos/{padre.modelo}",
                        "default_generation_settings": {
                            "n_ctx": 4096,
                            "params": {"temperature": 0.8, "top_p": 0.95}}})
                else:
                    self.send_error(404)

            def do_POST(self):
                padre.peticiones.append(("POST", self.path))
                n = int(self.headers.get("Content-Length") or 0)
                padre.ultimo_cuerpo = json.loads(self.rfile.read(n) or b"{}")
                if self.path.startswith("/v1/chat/completions"):
                    self._responder(padre.respuesta)
                else:
                    self.send_error(404)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def cerrar(self):
        self._srv.shutdown()
        self._srv.server_close()


@pytest.fixture(autouse=True)
def _aislar(monkeypatch, tmp_path):
    """HOME virgen (el cache de la sonda no puede ser el del dueno) y caches
    de proceso limpios."""
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))
    monkeypatch.delenv("COGNIA_LLM_URL", raising=False)
    monkeypatch.setattr(ba, "_props_cache", {})
    monkeypatch.setattr(ba, "_props_sello", {})
    monkeypatch.setattr(capacidad, "_mem", {})


@pytest.fixture()
def servidor():
    creados = []

    def _hacer(respuesta, modelo="modelo-de-prueba-7b.gguf"):
        s = _Servidor(respuesta, modelo)
        creados.append(s)
        return s

    yield _hacer
    for s in creados:
        s.cerrar()


# ── (a)(b)(c): el veredicto ─────────────────────────────────────────────────

def test_tool_calls_validos_dan_NATIVO(servidor):
    s = servidor(_respuesta_tool())
    r = capacidad.sondar(s.url)
    assert r["soporta_tools"] is True
    assert r["finish_reason"] == "tool_calls"
    assert r["argumentos_json"] is True and r["nombre_ok"] is True
    assert r["modelo"] == "modelo-de-prueba-7b.gguf"
    # la sonda pide DE VERDAD una tool, no confia en el nombre del modelo
    assert s.ultimo_cuerpo["tools"][0]["function"]["name"] == "ping"


def test_prosa_sin_tool_calls_da_TEXTO(servidor):
    """El server sin --jinja: el bucle nativo leeria esa prosa como 'fin
    natural' y cerraria la tarea en el paso 1 sin ejecutar nada."""
    s = servidor(_RESPUESTA_PROSA)
    r = capacidad.sondar(s.url)
    assert r["soporta_tools"] is False
    assert "sin tool_calls" in r["motivo"]


def test_arguments_que_no_son_json_dan_TEXTO(servidor):
    s = servidor(_respuesta_tool(arguments="x=hola"))
    r = capacidad.sondar(s.url)
    assert r["soporta_tools"] is False
    assert "arguments" in r["motivo"]


def test_arguments_ya_deserializados_cuentan_igual(servidor):
    """Backends que entregan arguments como dict (no como string JSON)."""
    resp = _respuesta_tool()
    resp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = \
        {"x": "hola"}
    s = servidor(resp)
    assert capacidad.sondar(s.url)["soporta_tools"] is True


def test_desaconsejado_gana_a_la_sonda(servidor):
    """La contraevidencia del barrido 2026-08-13: coder-14b emite tool_calls
    perfectos y aun asi rinde 13/26 en texto contra 0/26 en nativo. Una sonda
    de una peticion no puede ver eso, asi que la medicion en contra manda."""
    s = servidor(_respuesta_tool(), modelo="qwen2.5-coder-14b-instruct-q4.gguf")
    r = capacidad.sondar(s.url)
    assert r["soporta_tools"] is False
    assert "medido en contra" in r["motivo"] and "13/26" in r["motivo"]


def test_server_muerto_no_lanza_y_da_TEXTO():
    """Puerto cerrado: 'no soporta' con motivo legible, jamas una excepcion."""
    r = capacidad.sondar("http://127.0.0.1:9")
    assert r["soporta_tools"] is False and r["motivo"]


def test_http_500_no_lanza(servidor):
    s = servidor(_respuesta_tool())
    s.cerrar()                            # el socket deja de aceptar
    r = capacidad.sondar(s.url)
    assert r["soporta_tools"] is False and r["motivo"]


# ── cache ───────────────────────────────────────────────────────────────────

def test_medicion_cachea_y_forzar_vuelve_a_medir(servidor):
    s = servidor(_respuesta_tool())
    assert capacidad.medicion(s.url)["soporta_tools"] is True
    posts = [p for p in s.peticiones if p[0] == "POST"]
    assert len(posts) == 1
    capacidad.medicion(s.url)             # cache de memoria: sin peticion
    assert len([p for p in s.peticiones if p[0] == "POST"]) == 1
    capacidad.medicion(s.url, forzar=True)
    assert len([p for p in s.peticiones if p[0] == "POST"]) == 2


def test_cache_en_disco_sirve_a_un_proceso_nuevo(servidor):
    s = servidor(_respuesta_tool())
    capacidad.medicion(s.url)
    guardado = json.loads(
        capacidad._path_cache().read_text(encoding="utf-8"))
    clave = f"{s.url}|modelo-de-prueba-7b.gguf"
    assert guardado[clave]["soporta_tools"] is True
    capacidad._mem.clear()                # simula otro proceso
    assert capacidad.soporta_tools(s.url) is True
    assert len([p for p in s.peticiones if p[0] == "POST"]) == 1


def test_cache_corrupto_no_rompe_y_se_reescribe(servidor):
    """Un cache es una optimizacion, jamas una dependencia: con el JSON roto
    la sonda se repite y el fichero queda sano."""
    capacidad._path_cache().parent.mkdir(parents=True, exist_ok=True)
    capacidad._path_cache().write_text("{ esto no es json ][", encoding="utf-8")
    s = servidor(_respuesta_tool())
    assert capacidad._leer_cache() == {}
    assert capacidad.soporta_tools(s.url) is True
    sano = json.loads(capacidad._path_cache().read_text(encoding="utf-8"))
    assert any(v.get("soporta_tools") for v in sano.values())


def test_invalidar_borra_lo_medido(servidor):
    s = servidor(_respuesta_tool())
    capacidad.medicion(s.url)
    capacidad.invalidar(s.url)
    assert capacidad._mem == {} and capacidad._leer_cache() == {}
    capacidad.medicion(s.url)
    assert len([p for p in s.peticiones if p[0] == "POST"]) == 2


def test_diagnostico_es_una_linea_legible(servidor):
    s = servidor(_RESPUESTA_PROSA)
    linea = capacidad.diagnostico(s.url)
    assert linea.startswith("regimen TEXTO con modelo-de-prueba-7b.gguf")
    assert "\n" not in linea

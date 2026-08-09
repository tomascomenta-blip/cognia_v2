"""
Tests del nucleo nativo del agente (WP1, obra 2026-08-09).

Regresiones que cubren:
- El baseline 2026-08-09: el modelo respondia bien en harmony y el loop
  ACCION:/regex lo contaba como "2 pasos sin ACCION valida" -> cierre por
  prosa degradado. bucle_nativo consume message.tool_calls y termina cuando
  no hay tool calls (fin natural) — sin marco ACCION.
- La leccion 'presupuesto-tokens-razonamiento': ningun max_tokens del camino
  agente por debajo de MIN_TOKENS_RAZONADOR con perfil razonador.
- El contrafactual del plan: COGNIA_AGENT_LEGACY=1 fuerza el perfil texto
  aunque el modelo servido sea nativo.
- A6: los auxiliares LLM (budget-rating, wants_more_steps) apagados por
  defecto (solo heuristica; env para reactivar).

Sin modelo real: completar se simula con dobles deterministas. El e2e real
contra :8080 es la verificacion de cierre del paquete (no vive en pytest).
"""
import os

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import (RespuestaChat, ToolCall,
                                      mensaje_assistant, mensaje_tool)
from cognia.agent.model_profiles import (MIN_TOKENS_RAZONADOR,
                                         perfil_del_agente,
                                         verificar_arranque)
from cognia.agent.tool_schemas import args_legacy, schemas_para


# ── model_profiles ──────────────────────────────────────────────────────────

def _con_props(monkeypatch, modelo, n_ctx=16384):
    """Simula backend_activo.props sin red."""
    import cognia.backend_activo as ba
    monkeypatch.setattr(ba, "props",
                        lambda url, forzar=False: {"modelo": modelo,
                                                   "n_ctx": n_ctx,
                                                   "puerto": 8080})


def test_perfil_nativo_para_gpt_oss(monkeypatch):
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    _con_props(monkeypatch, "gpt-oss-20b-MXFP4.gguf")
    p = perfil_del_agente()
    assert p["tools"] == "nativo"
    assert p["temperature"] == 1.0 and p["top_p"] == 1.0
    assert p["max_tokens"] >= MIN_TOKENS_RAZONADOR
    assert verificar_arranque(p) == []


def test_perfil_nativo_para_qwythos(monkeypatch):
    # Cerebro principal desde 2026-08-09: Qwythos hace tool-calling nativo
    # (verificado a mano). Sampling Qwen (0.7/0.8), NO el 1.0/1.0 de harmony,
    # y sin reasoning_effort (no es harmony: lo aceptaba pero era no-op).
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    monkeypatch.delenv("COGNIA_REASONING_EFFORT", raising=False)
    _con_props(monkeypatch,
               "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf")
    p = perfil_del_agente()
    assert p["tools"] == "nativo"
    assert p["temperature"] == 0.7 and p["top_p"] == 0.8
    assert p["reasoning_effort"] == ""       # familia sin effort de harmony
    assert p["max_tokens"] >= MIN_TOKENS_RAZONADOR
    assert verificar_arranque(p) == []


def test_gpt_oss_conserva_su_effort_de_harmony(monkeypatch):
    # El cambio de familia NO toca a gpt-oss: sigue con effort low por defecto.
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    monkeypatch.delenv("COGNIA_REASONING_EFFORT", raising=False)
    _con_props(monkeypatch, "gpt-oss-20b-MXFP4.gguf")
    assert perfil_del_agente()["reasoning_effort"] == "low"


def test_perfil_texto_para_modelo_desconocido(monkeypatch):
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    _con_props(monkeypatch, "qwen2.5-coder-3b-instruct-q4.gguf")
    assert perfil_del_agente()["tools"] == "texto"


def test_perfil_texto_sin_backend(monkeypatch):
    import cognia.backend_activo as ba
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})
    assert perfil_del_agente()["tools"] == "texto"


def test_contrafactual_legacy_forzado(monkeypatch):
    """El contrafactual del plan: legacy forzado sobre el 20B apaga el nativo."""
    _con_props(monkeypatch, "gpt-oss-20b-MXFP4.gguf")
    monkeypatch.setenv("COGNIA_AGENT_LEGACY", "1")
    assert perfil_del_agente()["tools"] == "texto"


def test_verificar_arranque_grita_presupuesto_chico():
    avisos = verificar_arranque({"tools": "nativo", "max_tokens": 256,
                                 "modelo": "gpt-oss-20b.gguf"})
    assert any("max_tokens" in a for a in avisos)


# ── tool_schemas ────────────────────────────────────────────────────────────

def test_schemas_formato_openai_y_sin_responder():
    schemas = schemas_para()
    assert schemas, "el registry TOOLS deberia producir schemas"
    nombres = set()
    for s in schemas:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["name"] and fn["parameters"]["type"] == "object"
        nombres.add(fn["name"])
    # responder NO es tool en regimen nativo: el cierre es prosa sin calls.
    assert "responder" not in nombres
    assert "escribir_archivo" in nombres


def test_schemas_respeta_allowed():
    permitidas = {"leer_archivo", "listar"}
    nombres = {s["function"]["name"] for s in schemas_para(permitidas)}
    assert nombres == permitidas


def test_args_legacy_reconstruye_formato_pipe():
    assert args_legacy("escribir_archivo",
                       {"path": "hola.txt", "contenido": "hola mundo"}) \
        == "hola.txt | hola mundo"
    bloque = args_legacy("editar_archivo", {"path": "m.py", "buscar": "a=1",
                                            "reemplazar": "a=2"})
    assert bloque.startswith("m.py | <<<<<<< SEARCH\na=1\n=======\na=2")
    assert args_legacy("ejecutar", {"comando": "python x.py"}) == "python x.py"
    assert args_legacy("fecha", {}) == ""
    # generico: pasa 'args' tal cual; dict raro no lanza
    assert args_legacy("cuaderno", {"args": "consultar tema"}) == "consultar tema"
    assert args_legacy("desconocida", {"a": "x", "b": "y"}) == "x | y"


# ── chat_client: presupuesto del razonador y mensajes ───────────────────────

def test_completar_clampa_max_tokens_razonador(monkeypatch):
    """Regresion 'presupuesto-tokens-razonamiento': un max_tokens chico en el
    camino del agente se clampa a MIN_TOKENS_RAZONADOR antes de salir."""
    import json as _json
    import urllib.request as _url
    capturado = {}

    class _Resp:
        def read(self):
            return _json.dumps({"choices": [{"finish_reason": "stop",
                                             "message": {"content": "ok"}}],
                                "usage": {}}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        capturado.update(_json.loads(req.data.decode("utf-8")))
        return _Resp()

    monkeypatch.setattr(_url, "urlopen", _fake_urlopen)
    from cognia.agent.chat_client import completar
    resp = completar([{"role": "user", "content": "hola"}], max_tokens=16,
                     razonador=True, url="http://127.0.0.1:9")
    assert resp.ok and resp.texto == "ok"
    assert capturado["max_tokens"] >= MIN_TOKENS_RAZONADOR


def test_mensaje_assistant_preserva_cot_y_calls():
    resp = RespuestaChat(
        texto="", reasoning_content="pienso...",
        tool_calls=[ToolCall(id="abc", nombre="listar",
                             argumentos={"directorio": "."},
                             argumentos_crudos='{"directorio":"."}')])
    m = mensaje_assistant(resp)
    assert m["role"] == "assistant"
    assert m["reasoning_content"] == "pienso..."
    assert m["tool_calls"][0]["function"]["arguments"] == '{"directorio":"."}'
    t = mensaje_tool("abc", "RESULTADO listar: x")
    assert t == {"role": "tool", "tool_call_id": "abc",
                 "content": "RESULTADO listar: x"}


# ── bucle_nativo (la regresion del baseline) ────────────────────────────────

def _perfil_test():
    return {"nombre": "razonador_nativo", "modelo": "gpt-oss-20b.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
            "temperature": 1.0, "top_p": 1.0, "reasoning_effort": "low",
            "max_tokens": 4096}


def _correr(respuestas, run_tool, max_turns=8):
    """Corre bucle_nativo con un `completar` doble que devuelve la lista
    `respuestas` en orden."""
    it = iter(respuestas)

    def _completar(mensajes, tools=None, **kw):
        return next(it)

    history, trace = ["TAREA: crea hola.txt con 'hola mundo'"], []
    out = loop_mod.bucle_nativo(
        "crea hola.txt", "sos el agente", _completar, schemas_para(),
        args_legacy, mensaje_assistant, mensaje_tool, run_tool, {},
        _perfil_test(), history, trace, lambda *a, **k: None, max_turns)
    return out, history, trace


def test_bucle_nativo_tool_call_y_fin_natural():
    """El caso del baseline: tool call bien formado -> se EJECUTA (no '2
    pasos sin ACCION valida'), y la respuesta sin tool calls cierra."""
    ejecutadas = []

    def _run_tool(name, args, ctx):
        ejecutadas.append((name, args))
        return f"RESULTADO {name}: OK (10 chars)"

    r1 = RespuestaChat(
        texto="", finish_reason="tool_calls",
        usage={"completion_tokens": 50, "prompt_tokens": 100},
        tool_calls=[ToolCall(id="t1", nombre="escribir_archivo",
                             argumentos={"path": "hola.txt",
                                         "contenido": "hola mundo"},
                             argumentos_crudos="{}")])
    r2 = RespuestaChat(texto="Listo: hola.txt creado.", finish_reason="stop",
                       usage={"completion_tokens": 10, "prompt_tokens": 200})
    out, history, trace = _correr([r1, r2], _run_tool)
    assert ejecutadas == [("escribir_archivo", "hola.txt | hola mundo")]
    assert out["ok"] and out["texto"] == "Listo: hola.txt creado."
    assert out["pasos"] == 2
    assert out["tokens"] == 60           # usage REAL, no len//4
    assert history[-1] == "RESULTADO escribir_archivo: OK (10 chars)"
    assert trace[0]["ok"] is True


def test_bucle_nativo_error_de_server_degrada_con_causa():
    out, _, _ = _correr([RespuestaChat(error="HTTP 503 de :9")],
                        lambda *a: "no llega")
    assert not out["ok"]
    assert "HTTP 503" in out["texto"]


def test_bucle_nativo_estancamiento_corta_honesto():
    tc = ToolCall(id="t", nombre="listar", argumentos={"directorio": "."},
                  argumentos_crudos="{}")
    paso = RespuestaChat(texto="", finish_reason="tool_calls",
                         usage={}, tool_calls=[tc])
    out, _, trace = _correr([paso, paso, paso, paso],
                            lambda n, a, c: "RESULTADO listar: x")
    assert not out["ok"]
    assert "estancamiento" in out["texto"]
    assert len(trace) == 2               # la 3ra repeticion NO se ejecuta


def test_bucle_nativo_presupuesto_agotado_cierra_con_evidencia():
    tc = ToolCall(id="t", nombre="ejecutar", argumentos={"comando": "x"},
                  argumentos_crudos="{}")
    pasos = [RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                           tool_calls=[ToolCall(id=f"t{i}", nombre="ejecutar",
                                                argumentos={"comando": f"x{i}"},
                                                argumentos_crudos="{}")])
             for i in range(3)]
    out, _, _ = _correr(pasos, lambda n, a, c: f"RESULTADO ejecutar: ok {a}",
                        max_turns=3)
    assert "presupuesto de 3 pasos agotado" in out["texto"]
    assert "RESULTADO ejecutar" in out["texto"]   # evidencia, no volcado vacio


# ── A6: auxiliares LLM apagados por defecto ─────────────────────────────────

class _OrchQueNoDebeInferir:
    def infer(self, *a, **k):
        raise AssertionError("el auxiliar LLM no debe llamarse sin el env")


def test_estimate_step_budget_sin_llm_por_defecto(monkeypatch):
    monkeypatch.delenv("COGNIA_BUDGET_LLM", raising=False)
    n = loop_mod.estimate_step_budget("tarea cualquiera de largo medio",
                                      _OrchQueNoDebeInferir())
    assert 1 <= n <= loop_mod.AGENT_HARD_CAP


def test_wants_more_steps_apagado_por_defecto(monkeypatch):
    monkeypatch.delenv("COGNIA_WANTS_MORE", raising=False)
    assert loop_mod.wants_more_steps("t", "r", _OrchQueNoDebeInferir()) == 0

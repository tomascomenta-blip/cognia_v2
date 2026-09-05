# -*- coding: utf-8 -*-
"""
tests/test_contexto_ventana_nunca_none.py
=========================================
Autopsia del 2026-09-02 (Tank.io, 55 pasos, 23 min): el prompt subio de 6.502
a 65.221 tokens sin UNA sola bajada y el server contesto 400
(exceed_context_size). La compactacion y el recorte no actuaron nunca y sin
decir nada. La unica via muda con esa forma: el perfil de la tarea con
n_ctx=None (backend_activo.props cacheaba 60 s un /props FALLIDO mientras el
27B cargaba) -> umbral 0 -> compactar 'sin n_ctx' -> recorte 0.

Lo que fija cada test (cada uno falla sin su fix):
- props() no cachea un fallo.
- bucle_nativo con perfil sin n_ctx re-sondea el backend, y si no sabe, asume
  una ventana y LO DICE; en ambos casos la compactacion vuelve a funcionar.
- compactar() 'no aplicada' por encima del umbral se ve en pantalla.
- recorte de emergencia: cuando nada bajo el prompt y roza la ventana, se
  recorta a lo bruto (razonamiento de todos, args, mensajes viejos).
- en el 400 por contexto, el n_ctx que dice el server alimenta la emergencia
  y el bucle reintenta en vez de rendirse con "no queda nada recortable".
"""
from __future__ import annotations

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import RespuestaChat, mensaje_assistant, mensaje_tool
from cognia.agent.tool_schemas import args_legacy, schemas_para


class _TC:
    def __init__(self, i, nombre="leer_archivo", args=None):
        self.id = "c%d" % i
        self.nombre = nombre
        self.argumentos = args or {"path": "f%d.txt" % i}
        self.argumentos_rotos = False
        self.argumentos_crudos = ""


def _perfil(n_ctx):
    return {"nombre": "razonador_nativo", "modelo": "qwen.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": n_ctx,
            "temperature": 0.7, "top_p": 0.8, "reasoning_effort": "",
            "max_tokens": 8192}


def _prompt_de(mensajes):
    return sum(len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
               + sum(len(str((tc.get("function") or {}).get("arguments") or ""))
                     for tc in (m.get("tool_calls") or []))
               for m in mensajes) // 4


def _correr(perfil, pasos_tool=12, razon_chars=12000, serie=None, avisos=None,
            completar_extra=None):
    est = {"i": 0}

    def completar(mensajes, tools=None, **kw):
        est["i"] += 1
        i = est["i"]
        p = _prompt_de(mensajes)
        if serie is not None:
            serie.append(p)
        if completar_extra is not None:
            r = completar_extra(i, mensajes, p)
            if r is not None:
                return r
        if i > pasos_tool:
            return RespuestaChat(texto="terminado", finish_reason="stop",
                                 usage={"prompt_tokens": p, "completion_tokens": 50})
        return RespuestaChat(texto="", reasoning_content="razono " * (razon_chars // 7),
                             finish_reason="tool_calls", tool_calls=[_TC(i)],
                             usage={"prompt_tokens": p, "completion_tokens": 3000})

    def _print(msg, *a, **k):
        if avisos is not None:
            avisos.append(str(msg))
    return loop_mod.bucle_nativo(
        "t", "sos el agente", completar, schemas_para(), args_legacy,
        mensaje_assistant, mensaje_tool, lambda n, a, c: "RESULTADO %s: OK" % n,
        {"_pasos_ilimitados": True}, perfil, ["TAREA: t"], [], _print, 40)


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    # Estos tests fijan el camino VIEJO de compactacion/emergencia; la memoria
    # larga (default on desde 2026-09-04) reconstruye antes y los dejaria sin objeto.
    monkeypatch.setenv("COGNIA_MEMORIA_LARGA", "0")
    monkeypatch.delenv("COGNIA_STREAM", raising=False)
    monkeypatch.delenv("COGNIA_COMPACT", raising=False)
    monkeypatch.delenv("COGNIA_PARED_S", raising=False)


# ── props no cachea fallos ─────────────────────────────────────────────────────

def test_props_no_cachea_un_fallo(monkeypatch):
    from cognia import backend_activo as ba
    url = "http://127.0.0.1:9"
    ba._props_cache.pop(url, None)
    ba._props_sello.pop(url, None)
    assert ba.props(url, forzar=True) == {}
    assert url not in ba._props_cache          # el fallo no queda 60 s
    llamadas = {"n": 0}
    import urllib.request
    real = urllib.request.urlopen

    def _falla(*a, **k):
        llamadas["n"] += 1
        raise OSError("cargando")
    monkeypatch.setattr(urllib.request, "urlopen", _falla)
    ba.props(url)
    ba.props(url)
    assert llamadas["n"] == 2                  # cada llamador vuelve a sondear
    monkeypatch.setattr(urllib.request, "urlopen", real)


# ── ventana nunca None en el bucle ─────────────────────────────────────────────

def test_sin_n_ctx_en_el_perfil_el_bucle_resondea_y_compacta(monkeypatch):
    from cognia.agent import model_profiles as mp
    monkeypatch.setattr(mp, "n_ctx_del_backend", lambda url="": 65536)
    serie, avisos = [], []
    r = _correr(_perfil(None), pasos_tool=30, serie=serie, avisos=avisos)
    assert r["texto"] == "terminado"
    assert any("re-sondeada: 65536" in a for a in avisos), avisos
    assert any("compactado por resumen" in a for a in avisos), avisos
    assert max(serie) < 65536 * 0.95           # nunca rozo la ventana
    assert any(serie[i + 1] < serie[i] for i in range(len(serie) - 1))   # hubo bajada


def test_sin_n_ctx_ni_backend_se_asume_una_ventana_y_se_dice(monkeypatch):
    from cognia.agent import model_profiles as mp
    monkeypatch.setattr(mp, "n_ctx_del_backend", lambda url="": None)
    serie, avisos = [], []
    r = _correr(_perfil(None), pasos_tool=30, serie=serie, avisos=avisos)
    assert r["texto"] == "terminado"
    assert any("asume 32768" in a for a in avisos), avisos
    assert max(serie) < 32768 * 0.95, max(serie)


# ── motivo visible y recorte de emergencia ───────────────────────────────────────

def test_compactacion_no_aplicada_se_ve_y_la_emergencia_baja_el_prompt(monkeypatch):
    """Si compactar() dice 'no aplicada' y el recorte normal no libera, el
    bucle lo DICE y el recorte de emergencia baja el prompt igualmente."""
    from cognia.harness import compactacion as comp
    monkeypatch.setattr(comp, "compactar", lambda *a, **k: {
        "aplicada": False, "liberados": 0, "motivo": "nada viejo que fundir",
        "tokens_antes": 0, "tokens_despues": 0, "descartados": 0})
    monkeypatch.setattr(loop_mod, "_recortar_mensajes", lambda *a, **k: 0)
    serie, avisos = [], []
    r = _correr(_perfil(65536), pasos_tool=30, serie=serie, avisos=avisos)
    assert r["texto"] == "terminado"
    assert any("compactacion no aplicada: nada viejo que fundir" in a for a in avisos), avisos
    assert any("recorte de emergencia de contexto" in a for a in avisos), avisos
    assert max(serie) < 65536, max(serie)
    assert any(serie[i + 1] < serie[i] for i in range(len(serie) - 1))


def test_el_recorte_de_emergencia_reduce_todo_lo_reducible():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "TAREA"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": "", "reasoning_content": "r" * 5000,
                     "tool_calls": [{"id": "c%d" % i, "type": "function", "function": {
                         "name": "escribir_archivo",
                         "arguments": '{"path": "x.html", "contenido": "%s"}' % ("h" * 6000)}}]})
        msgs.append({"role": "tool", "tool_call_id": "c%d" % i, "content": "RESULTADO: " + "o" * 3000})
    antes = loop_mod._tokens_prompt(msgs)
    avisos = []
    lib = loop_mod._recorte_de_emergencia(msgs, 16384, avisos.append)
    despues = loop_mod._tokens_prompt(msgs)
    assert lib > 0 and despues < antes
    assert despues <= int(16384 * 0.8) or len(msgs) <= 2 + loop_mod._EMERGENCIA_COLA + 1
    assert msgs[0]["role"] == "system" and msgs[1]["content"] == "TAREA"     # objetivo intacto
    assert all(len(m.get("reasoning_content") or "") <= 201 for m in msgs)
    assert any("recorte de emergencia" in a for a in avisos)


def test_n_ctx_del_error_400():
    e = ('HTTP 400 de http://127.0.0.1:8080: {"error":{"code":400,"message":"request '
         '(65835 tokens) exceeds the available context size (65536 tokens)",'
         '"type":"exceed_context_size_error","n_prompt_tokens":65835,"n_ctx":65536}}')
    assert loop_mod._n_ctx_de_error(e) == 65536
    assert loop_mod._n_ctx_de_error("sin nada") == 0


def test_en_el_400_por_contexto_la_emergencia_permite_reintentar(monkeypatch):
    """Antes: 'contexto excedido y no queda nada recortable: no reintento'.
    Ahora: con el n_ctx del error, la emergencia libera y se reintenta."""
    monkeypatch.setattr(loop_mod, "_recortar_mensajes", lambda *a, **k: 0)
    monkeypatch.setattr(loop_mod, "_compactar_por_resumen", lambda *a, **k: 0)
    err = ('HTTP 400 de http://127.0.0.1:8080: {"error":{"code":400,"message":"request '
           '(65835 tokens) exceeds the available context size (65536 tokens)",'
           '"type":"exceed_context_size_error","n_prompt_tokens":65835,"n_ctx":65536}}')
    estado = {"fallado": False}

    def extra(i, mensajes, p):
        if i >= 6 and not estado["fallado"]:
            estado["fallado"] = True
            return RespuestaChat(texto="", error=err, finish_reason="")
        return None
    avisos = []
    r = _correr(_perfil(65536), pasos_tool=8, razon_chars=20000, avisos=avisos,
                completar_extra=extra)
    assert not any("no queda nada recortable" in a for a in avisos), avisos
    assert any("recorte de emergencia de contexto" in a for a in avisos), avisos
    assert r["texto"] == "terminado", r

# -*- coding: utf-8 -*-
"""
tests/test_chat_client_kv.py — marcar_kv_sucio() y cache_prompt: false
======================================================================
Plan LoRA Qwythos 2026-08-09 (ola 1, agente E). Sin GPU: urlopen mockeado.

POR QUE estos tests: completar() postea DIRECTO a /v1/chat/completions sin
pasar por node/llama_backend, asi que el _consume_lora_dirty del backend NO
cubre el camino nativo. Tras un hot-swap de LoRA la primera request del
agente reutilizaria KV calculado con otros pesos efectivos (llama.cpp no lo
invalida solo — medido 2026-07-07). El contrato: tras marcar_kv_sucio(), la
PROXIMA completar() manda cache_prompt: false UNA sola vez.
"""
from __future__ import annotations

import json

import pytest

from cognia.agent import chat_client
from cognia.agent.chat_client import completar, marcar_kv_sucio

URL = "http://127.0.0.1:9999"   # nunca se abre de verdad: urlopen mockeado
MENSAJES = [{"role": "user", "content": "hola"}]


class _RespuestaFake:
    """Respuesta minima valida de /v1/chat/completions como context manager."""

    def __init__(self):
        self._crudo = {
            "choices": [{"message": {"content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"completion_tokens": 1},
        }

    def read(self):
        return json.dumps(self._crudo).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def cuerpos(monkeypatch):
    """Mockea urlopen capturando el body JSON de cada request, y apaga la
    auditoria de backend_activo (escribe a disco; aca es ruido)."""
    capturados = []

    def _urlopen_fake(req, timeout=None):
        capturados.append(json.loads(req.data.decode("utf-8")))
        return _RespuestaFake()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen_fake)
    from cognia import backend_activo
    monkeypatch.setattr(backend_activo, "registrar",
                        lambda *a, **kw: {}, raising=True)
    # Estado limpio ANTES y DESPUES: el flag es modulo-global y un test que
    # lo deje prendido contaminaria al siguiente (o a otra suite).
    chat_client._KV_SUCIO["v"] = False
    yield capturados
    chat_client._KV_SUCIO["v"] = False


def test_sin_marcar_no_manda_cache_prompt(cuerpos):
    resp = completar(MENSAJES, url=URL)
    assert resp.ok and resp.texto == "ok"
    assert len(cuerpos) == 1
    assert "cache_prompt" not in cuerpos[0]


def test_marcar_manda_false_una_sola_vez(cuerpos):
    marcar_kv_sucio()
    completar(MENSAJES, url=URL)          # 1ra tras el swap: false explicito
    completar(MENSAJES, url=URL)          # 2da: cache normal otra vez
    assert cuerpos[0]["cache_prompt"] is False
    assert "cache_prompt" not in cuerpos[1]


def test_marcar_dos_veces_sigue_siendo_una_request(cuerpos):
    """Idempotente: dos swaps seguidos sin request en el medio siguen
    necesitando UN solo re-prefill (el KV se reconstruye entero igual)."""
    marcar_kv_sucio()
    marcar_kv_sucio()
    completar(MENSAJES, url=URL)
    completar(MENSAJES, url=URL)
    assert cuerpos[0]["cache_prompt"] is False
    assert "cache_prompt" not in cuerpos[1]


def test_el_resto_del_cuerpo_queda_intacto(cuerpos):
    """cache_prompt es ADITIVO: mensajes/tools/sampling no cambian por el
    flag (una regresion aca romperia todos los pasos del agente, no solo el
    post-swap)."""
    tools = [{"type": "function",
              "function": {"name": "t", "parameters": {"type": "object"}}}]
    marcar_kv_sucio()
    completar(MENSAJES, tools=tools, url=URL, temperature=0.5,
              max_tokens=8192)
    c = cuerpos[0]
    assert c["messages"] == MENSAJES
    assert c["tools"] == tools
    assert c["temperature"] == 0.5
    assert c["max_tokens"] == 8192
    assert c["cache_prompt"] is False


def test_estado_es_modulo_global(cuerpos):
    """El que marca (guard A3 en cli.py) y el que consume (loop del agente)
    importan el modulo por caminos distintos: el estado tiene que ser uno."""
    import importlib
    mod = importlib.import_module("cognia.agent.chat_client")
    mod.marcar_kv_sucio()
    completar(MENSAJES, url=URL)
    assert cuerpos[0]["cache_prompt"] is False

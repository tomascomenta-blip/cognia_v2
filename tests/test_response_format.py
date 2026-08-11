# -*- coding: utf-8 -*-
"""
tests/test_response_format.py — kwarg response_format de completar()
====================================================================
Contrato WP1 (motor de workflows 2026-08-11). Sin GPU salvo el humo @red.

POR QUE estos tests: la salida estructurada de los workflows depende de que
completar() pase response_format TAL CUAL al server (llama-server la fuerza
por gramatica desde b9391) y de que sin el kwarg el body quede IDENTICO al
de antes — una regresion aca romperia todos los pasos del agente, no solo
los workflows.
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from cognia.agent import chat_client
from cognia.agent.chat_client import completar

URL = "http://127.0.0.1:9999"   # nunca se abre de verdad: urlopen mockeado
BACKEND = "http://127.0.0.1:8080"
MENSAJES = [{"role": "user", "content": "hola"}]

# Schema trivial para el humo real: alcanza para ver la gramatica actuando.
SCHEMA_X = {"type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"]}


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
    # El flag de KV es modulo-global: limpio antes y despues para no heredar
    # ni contaminar (mismo cuidado que en test_chat_client_kv.py).
    chat_client._KV_SUCIO["v"] = False
    yield capturados
    chat_client._KV_SUCIO["v"] = False


def test_sin_kwarg_el_body_no_trae_response_format(cuerpos):
    resp = completar(MENSAJES, url=URL)
    assert resp.ok and resp.texto == "ok"
    assert len(cuerpos) == 1
    assert "response_format" not in cuerpos[0]


def test_con_kwarg_el_body_lo_trae_tal_cual(cuerpos):
    rf = {"type": "json_schema",
          "json_schema": {"name": "salida", "schema": SCHEMA_X,
                          "strict": True}}
    completar(MENSAJES, url=URL, response_format=rf)
    assert cuerpos[0]["response_format"] == rf


def test_el_resto_del_cuerpo_queda_intacto(cuerpos):
    """response_format es ADITIVO: mensajes/tools/sampling no cambian por
    pasarlo (el kwarg no debe pisar nada del body existente)."""
    tools = [{"type": "function",
              "function": {"name": "t", "parameters": {"type": "object"}}}]
    completar(MENSAJES, tools=tools, url=URL, temperature=0.5,
              max_tokens=8192, response_format={"type": "json_object"})
    c = cuerpos[0]
    assert c["messages"] == MENSAJES
    assert c["tools"] == tools
    assert c["temperature"] == 0.5
    assert c["max_tokens"] == 8192
    assert c["response_format"] == {"type": "json_object"}


def _hay_backend() -> bool:
    """/health en <2s o nada: el humo real jamas cuelga la suite."""
    try:
        with urllib.request.urlopen(BACKEND + "/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.mark.red
def test_humo_real_schema_trivial_contra_8080():
    """Contra el server VIVO: la gramatica tiene que devolver JSON valido
    conforme al schema, no solo aceptar el campo sin quejarse."""
    if not _hay_backend():
        pytest.skip("sin backend en :8080 (/health no respondio en 2s)")
    rf = {"type": "json_schema",
          "json_schema": {"name": "salida", "schema": SCHEMA_X,
                          "strict": True}}
    resp = completar(
        [{"role": "user",
          "content": "Devolve SOLO un JSON con la clave x y un entero."}],
        url=BACKEND, response_format=rf, temperature=0.0, max_tokens=2048)
    assert resp.ok, f"el server fallo: {resp.error}"
    obj = json.loads(resp.texto)   # lanza si no es JSON -> test rojo
    assert isinstance(obj, dict)
    assert "x" in obj, f"falta 'x' (required del schema): {obj}"
    assert isinstance(obj["x"], int) and not isinstance(obj["x"], bool), \
        f"'x' no es entero: {obj['x']!r}"

"""
tests/test_mesh_federated_search.py — Regresión de la búsqueda federada.

Bug cubierto (network/mesh_node.py, cazado 2026-08-01):
  federated_search devolvía [] SIEMPRE por construcción: el emisor
  (_federated_search_async) no enviaba 'query_text' en el payload y el
  respondedor (_on_federated_search) matcheaba contra
  payload.get("query_text", "") == "" → ningún triple matcheaba nunca.

Fix:
  a) federated_search/_federated_search_async aceptan query_text y lo
     incluyen en el payload del mensaje "federated_search".
  b) El respondedor matchea contra predicado + objeto (el subject viaja
     hasheado por privacy.py) con frase completa o palabras >=3 chars.

Incluye el test pedido por la orden de trabajo: dos nodos en loopback,
un triple público, federated_search lo devuelve.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from network.mesh_node import CogniaMeshNode, HAS_WEBSOCKETS


# ── Emisor: query_text DEBE viajar en el payload ──────────────────────────────

def test_emisor_incluye_query_text_en_payload(monkeypatch):
    """Sin el fix, el payload del mensaje federated_search no traía query_text."""
    import network.mesh_node as mesh_mod

    sent: list[str] = []

    class FakeClientWS:
        async def send(self, msg):
            sent.append(msg)

        async def recv(self):
            raise asyncio.TimeoutError

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeClient:
        @staticmethod
        def connect(uri, **kw):
            return FakeClientWS()

    monkeypatch.setattr(mesh_mod, "HAS_WEBSOCKETS", True)
    monkeypatch.setattr(mesh_mod.websockets, "client", FakeClient, raising=False)

    node = CogniaMeshNode(node_id="emisor", port=7678)
    node._peers = {"peer-x": "ws://192.168.1.99:7474"}
    asyncio.run(node._federated_search_async([0.1] * 4, 5, 0.2, "tema buscado"))

    assert sent, "El mensaje federated_search no se envió"
    payload = json.loads(sent[0])["payload"]
    assert payload.get("query_text") == "tema buscado", (
        f"query_text ausente o vacío en el payload: {payload}"
    )


# ── Respondedor: match real contra predicado + objeto ─────────────────────────

def _responder_con_triple():
    node = CogniaMeshNode(node_id="respondedor", port=7679)
    node.crdt.add("python", "es_un", "lenguaje")
    return node


class _CollectWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, msg):
        self.sent.append(msg)


def test_respondedor_devuelve_triple_que_matchea():
    node = _responder_con_triple()
    ws = _CollectWS()
    asyncio.run(node._on_federated_search(
        "peer-x",
        {"embedding": [0.1] * 4, "k": 5, "query_text": "lenguaje"},
        ws,
    ))
    assert ws.sent, "El respondedor no envió search_response"
    payload = json.loads(ws.sent[0])["payload"]
    assert payload["results"], "query_text que matchea el objeto devolvió 0 resultados"
    assert payload["results"][0]["predicate"] == "es_un"
    assert payload["results"][0]["object"] == "lenguaje"


def test_respondedor_sin_query_text_responde_vacio():
    """Sin texto no hay contra qué matchear: respuesta vacía, no silencio."""
    node = _responder_con_triple()
    ws = _CollectWS()
    asyncio.run(node._on_federated_search(
        "peer-x",
        {"embedding": [0.1] * 4, "k": 5},
        ws,
    ))
    assert ws.sent, "Con embedding presente debe responder (aunque vacío)"
    payload = json.loads(ws.sent[0])["payload"]
    assert payload["results"] == []


# ── Integración: dos nodos en loopback, un triple público ─────────────────────

@pytest.mark.skipif(not HAS_WEBSOCKETS, reason="websockets no instalado")
def test_federated_search_loopback_devuelve_triple_publico():
    puerto_a, puerto_b = 7681, 7682
    a = CogniaMeshNode(node_id="nodo-a", port=puerto_a, host="127.0.0.1")
    b = CogniaMeshNode(node_id="nodo-b", port=puerto_b, host="127.0.0.1")
    # Triple PÚBLICO en el CRDT del respondedor (predicado factual → PUBLIC)
    a.crdt.add("python", "es_un", "lenguaje")
    a.start()
    b.start()
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not (
            a._loop and a._loop.is_running() and b._loop and b._loop.is_running()
        ):
            time.sleep(0.05)

        b.connect_peer(f"ws://127.0.0.1:{puerto_a}")
        # El handshake sin respuesta del peer tarda hasta 3s (timeout de recv)
        deadline = time.time() + 6.0
        while time.time() < deadline and not b._peers:
            time.sleep(0.05)
        assert b._peers, "El handshake no registró al peer en loopback"

        results = b.federated_search(
            [0.1] * 8, k=5, timeout_ms=3000, query_text="lenguaje",
        )
        assert results, "federated_search devolvió [] con un triple público que matchea"
        assert results[0]["object"] == "lenguaje"
        assert results[0]["predicate"] == "es_un"
    finally:
        a.stop()
        b.stop()

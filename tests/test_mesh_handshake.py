"""
tests/test_mesh_handshake.py — Regresión del handshake de CogniaMeshNode.

Bug cubierto (network/mesh_node.py):
  _connect_and_handshake anunciaba "uri": ws://{self.host}:{port} donde
  self.host es la dirección de BIND (default "0.0.0.0"). El receptor
  registraba ws://0.0.0.0:PORT en _peers y _broadcast/_sync_all_peers
  conectaban a 0.0.0.0 → los deltas nunca llegaban al peer.

Fix (defensa en profundidad):
  a) Servidor: si la URI anunciada trae host de bind-all (0.0.0.0/::/vacío),
     lo sustituye por la IP real del peer (websocket.remote_address[0]).
  b) Cliente: si self.host es bind-all, anuncia host vacío (ws://:PORT)
     y deja que el servidor derive el host.
"""

from __future__ import annotations

import asyncio
import json
import time

from network.mesh_node import CogniaMeshNode


class FakeWebSocket:
    """Websocket falso con remote_address, como el objeto real de websockets."""
    def __init__(self, remote_ip="192.168.1.50", remote_port=51234):
        self.remote_address = (remote_ip, remote_port)


def _handshake_msg(sender_id: str, uri: str) -> dict:
    return {
        "type":      "handshake",
        "node_id":   sender_id,
        "timestamp": time.time(),
        "payload":   {"uri": uri},
    }


def _dispatch(node, msg, ws):
    asyncio.run(node._dispatch(msg, ws))


# ── Servidor: sustituir host bind-all por la IP real del peer ─────────────────

def test_handshake_replaces_bind_all_host_with_remote_ip():
    node = CogniaMeshNode(node_id="receiver", port=7474)
    ws = FakeWebSocket(remote_ip="192.168.1.50")
    _dispatch(node, _handshake_msg("peer-a", "ws://0.0.0.0:7475"), ws)
    assert node._peers["peer-a"] == "ws://192.168.1.50:7475", (
        f"URI registrada inalcanzable: {node._peers['peer-a']}"
    )


def test_handshake_replaces_empty_host_with_remote_ip():
    node = CogniaMeshNode(node_id="receiver", port=7474)
    ws = FakeWebSocket(remote_ip="10.0.0.7")
    _dispatch(node, _handshake_msg("peer-b", "ws://:7480"), ws)
    assert node._peers["peer-b"] == "ws://10.0.0.7:7480"


def test_handshake_replaces_ipv6_bind_all_host():
    node = CogniaMeshNode(node_id="receiver", port=7474)
    ws = FakeWebSocket(remote_ip="10.0.0.9")
    _dispatch(node, _handshake_msg("peer-c", "ws://[::]:7481"), ws)
    assert node._peers["peer-c"] == "ws://10.0.0.9:7481"


def test_handshake_keeps_concrete_announced_host():
    """Una URI ya alcanzable no se toca (conserva host y puerto anunciados)."""
    node = CogniaMeshNode(node_id="receiver", port=7474)
    ws = FakeWebSocket(remote_ip="192.168.1.50")
    _dispatch(node, _handshake_msg("peer-d", "ws://192.168.1.99:7490"), ws)
    assert node._peers["peer-d"] == "ws://192.168.1.99:7490"


def test_handshake_bind_all_without_remote_address_keeps_uri():
    """Sin remote_address disponible, no inventar nada: registrar tal cual."""
    class NoAddrWS:
        remote_address = None

    node = CogniaMeshNode(node_id="receiver", port=7474)
    _dispatch(node, _handshake_msg("peer-e", "ws://0.0.0.0:7495"), NoAddrWS())
    assert node._peers["peer-e"] == "ws://0.0.0.0:7495"


# ── Cliente: no anunciar 0.0.0.0 en el handshake saliente ─────────────────────

def test_client_does_not_announce_bind_all_host(monkeypatch):
    """_connect_and_handshake no debe anunciar 0.0.0.0 cuando el host es de bind-all."""
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

    node = CogniaMeshNode(node_id="sender", port=7474, host="0.0.0.0")
    asyncio.run(node._connect_and_handshake("ws://192.168.1.99:7474"))

    assert sent, "El handshake no se envió"
    payload = json.loads(sent[0])["payload"]
    assert "0.0.0.0" not in payload.get("uri", ""), (
        f"El cliente sigue anunciando la dirección de bind: {payload}"
    )

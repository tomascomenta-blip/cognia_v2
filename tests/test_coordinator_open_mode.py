"""
tests/test_coordinator_open_mode.py — Regresión del modo permisivo sin key.

Bug cubierto (coordinator/app.py, cazado 2026-08-01):
  Sin COORDINATOR_KEY los endpoints admin (/api/node DELETE,
  /api/shattering/infer, /api/node/pending_sessions, /api/contribution/:id)
  quedaban ABIERTOS para cualquier cliente de la red, con solo un warning
  en el log.

Fix: _reject_open_mode_remote — sin key, el modo permisivo solo vale para
clientes loopback (dev local); a un cliente remoto se le responde 503.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import coordinator.app as app_mod


def _req(host: str):
    """Request mínimo con el atributo .client.host que mira el guard."""
    return SimpleNamespace(client=SimpleNamespace(host=host))


# ── Sin COORDINATOR_KEY ───────────────────────────────────────────────────────

def test_sin_key_cliente_remoto_recibe_503(monkeypatch):
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    with pytest.raises(HTTPException) as exc:
        app_mod.require_admin(_req("192.168.1.20"), x_coordinator_key=None)
    assert exc.value.status_code == 503


def test_sin_key_contributor_remoto_recibe_503(monkeypatch):
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    with pytest.raises(HTTPException) as exc:
        app_mod.require_contributor_or_admin(
            _req("10.0.0.5"), x_coordinator_key=None, x_contributor_token=None,
        )
    assert exc.value.status_code == 503


def test_sin_key_loopback_sigue_pasando(monkeypatch):
    """Dev local: loopback conserva el comportamiento permisivo."""
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    # require_admin no levanta
    app_mod.require_admin(_req("127.0.0.1"), x_coordinator_key=None)
    # require_contributor_or_admin devuelve el contexto anon premium
    ctx = app_mod.require_contributor_or_admin(
        _req("127.0.0.1"), x_coordinator_key=None, x_contributor_token=None,
    )
    assert ctx["role"] == "anon"


def test_sin_key_testclient_sigue_pasando(monkeypatch):
    """El host sintético del TestClient de Starlette no debe romper tests."""
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    app_mod.require_admin(_req("testclient"), x_coordinator_key=None)


# ── Con COORDINATOR_KEY (comportamiento previo intacto) ───────────────────────

def test_con_key_remoto_con_key_valida_pasa(monkeypatch):
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "secreta")
    app_mod.require_admin(_req("192.168.1.20"), x_coordinator_key="secreta")


def test_con_key_remoto_con_key_invalida_403(monkeypatch):
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "secreta")
    with pytest.raises(HTTPException) as exc:
        app_mod.require_admin(_req("192.168.1.20"), x_coordinator_key="mala")
    assert exc.value.status_code == 403


# ── Regresión 2026-08-01 (revisión adversarial): endpoints que NO pasaban
# por require_admin/require_contributor_or_admin y por tanto se saltaban el
# guard de modo permisivo. Reproducido con TestClient desde 192.168.0.99:
#   POST /api/node/leave  -> 200 desregistrando un node_id ARBITRARIO
#   GET  /api/shattering/route -> 200, fingerprinting del router abierto
# Ambos hacían su chequeo dentro de `if COORDINATOR_KEY:` — sin key, nada.

def _cliente_remoto(host: str = "192.168.0.99"):
    """TestClient que se presenta con una IP de LAN (no loopback)."""
    from starlette.testclient import TestClient
    return TestClient(app_mod.app, client=(host, 54321))


def test_node_leave_sin_key_rechaza_cliente_remoto(monkeypatch):
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    r = _cliente_remoto().post("/api/node/leave", json={"node_id": "victima"})
    assert r.status_code == 503, r.text
    assert "COORDINATOR_KEY" in r.json()["detail"]


def test_node_leave_sin_key_loopback_sigue_funcionando(monkeypatch):
    """Dev local no se rompe: el nodo puede salir desde la propia máquina."""
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    r = _cliente_remoto("127.0.0.1").post("/api/node/leave",
                                          json={"node_id": "n-local"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_shattering_route_sin_key_rechaza_cliente_remoto(monkeypatch):
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "")
    r = _cliente_remoto().get("/api/shattering/route", params={"prompt": "hola"})
    assert r.status_code == 503, r.text

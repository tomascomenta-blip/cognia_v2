"""
tests/test_contributor.py — Economía de contribución del enjambre.

Primer test dirigido de coordinator/contributor.py (bbrain.md lo listaba en
"SIN ninguna mención en tests/"). Cubre además los cortes de cadena cerrados
el 2026-08-01:

  1. node_id efímero: cada POST /api/node/register creaba un uuid nuevo, así
     que ningún nodo acumulaba contribución y premium era inalcanzable.
     Fix: re-registro con X-Contributor-Token conserva el node_id.
  2. basic.allowed_models no incluía los sub-modelos Shattering que el único
     endpoint con enforcement construye ("<sub>-3.2-3b-q4") → todo
     contribuidor real recibía 403.
  3. SlidingWindowLimiter.evict_stale era huérfana: _windows crecía sin cota.
     Fix: limpieza oportunista en /api/node/heartbeat.
"""

from __future__ import annotations

from collections import deque

import pytest

import coordinator.app as app_mod
from coordinator.contributor import (
    TIERS,
    ContributorLedger,
    generate_token,
    tier_for_params,
    validate_token,
)
from coordinator.registry import NodeRegistry


# ── tier_for_params ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("params_b, esperado", [
    (0.0,   "none"),
    (0.49,  "none"),
    (0.5,   "basic"),
    (0.775, "basic"),      # cuota real de un shard de 3.1B / 4
    (1.0,   "standard"),
    (2.99,  "standard"),
    (3.0,   "premium"),
    (10.0,  "premium"),
])
def test_tier_for_params(params_b, esperado):
    assert tier_for_params(params_b) == esperado


def test_basic_permite_los_submodelos_shattering():
    """Regresión corte 2: /api/shattering/infer construye '<sub>-3.2-3b-q4';
    si basic no los lista, todo contribuidor real recibe 403 en el único
    endpoint que ejerce la economía."""
    allowed = TIERS["basic"]["allowed_models"]
    for sub in ("logos", "techne", "rhetor"):
        assert f"{sub}-3.2-3b-q4" in allowed


# ── Tokens HMAC ───────────────────────────────────────────────────────────────

def test_token_roundtrip():
    tok = generate_token("clave", "nodo-1")
    assert validate_token("clave", tok) == "nodo-1"


def test_token_adulterado_es_rechazado():
    tok = generate_token("clave", "nodo-1")
    assert validate_token("clave", tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert validate_token("otra-clave", tok) is None
    assert validate_token("clave", "sin-punto") is None
    assert validate_token("", tok) is None


def test_token_sin_clave_lanza():
    with pytest.raises(ValueError):
        generate_token("", "nodo-1")


# ── Ledger ────────────────────────────────────────────────────────────────────

def test_ledger_acumula_sobre_el_mismo_node_id():
    ledger = ContributorLedger(":memory:")
    ledger.record_contribution("n1", 0.775)
    assert ledger.get_tier_for_node("n1") == "basic"
    ledger.record_contribution("n1", 0.775)
    entry = ledger.get_contribution("n1")
    assert entry["total_params_b"] == pytest.approx(1.55)
    assert entry["tier"] == "standard"
    # Cuatro cuotas de shard 3B → premium alcanzable (antes: imposible)
    ledger.record_contribution("n1", 0.775)
    ledger.record_contribution("n1", 0.775)
    assert ledger.get_tier_for_node("n1") == "premium"


def test_ledger_desconocido():
    ledger = ContributorLedger(":memory:")
    assert ledger.get_contribution("fantasma") is None
    assert ledger.get_tier_for_node("fantasma") == "none"


# ── Re-registro con token (corte 1) ───────────────────────────────────────────

@pytest.fixture()
def cliente(monkeypatch):
    """TestClient loopback con key, registry y ledger en memoria."""
    from starlette.testclient import TestClient
    monkeypatch.setattr(app_mod, "COORDINATOR_KEY", "secreta")
    monkeypatch.setattr(app_mod, "registry", NodeRegistry(":memory:"))
    monkeypatch.setattr(app_mod, "ledger", ContributorLedger(":memory:"))
    return TestClient(app_mod.app)


def test_reregistro_con_token_conserva_node_id_y_acumula(cliente):
    r1 = cliente.post("/api/node/register", json={"model_name": "qwen-coder-3b-q4"})
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    token = body1["contributor_token"]
    assert body1["tier"] == "basic"

    r2 = cliente.post(
        "/api/node/register",
        json={"model_name": "qwen-coder-3b-q4"},
        headers={"X-Contributor-Token": token},
    )
    body2 = r2.json()
    assert body2["node_id"] == body1["node_id"]
    entry = app_mod.ledger.get_contribution(body1["node_id"])
    assert entry["total_params_b"] == pytest.approx(2 * (3.1 / 4))
    assert body2["tier"] == "standard"


def test_registro_sin_token_sigue_creando_nodo_nuevo(cliente):
    r1 = cliente.post("/api/node/register", json={"model_name": "qwen-coder-3b-q4"})
    r2 = cliente.post("/api/node/register", json={"model_name": "qwen-coder-3b-q4"})
    assert r1.json()["node_id"] != r2.json()["node_id"]


def test_token_invalido_en_registro_no_hereda_identidad(cliente):
    r = cliente.post(
        "/api/node/register",
        json={"model_name": "qwen-coder-3b-q4"},
        headers={"X-Contributor-Token": "nodo-ajeno.firma-falsa"},
    )
    assert r.status_code == 200
    assert r.json()["node_id"] != "nodo-ajeno"


# ── evict_stale cableado al heartbeat (corte 3) ───────────────────────────────

def test_heartbeat_evicta_ventanas_viejas(cliente, monkeypatch):
    r = cliente.post("/api/node/register", json={"model_name": "qwen-coder-3b-q4"})
    node_id = r.json()["node_id"]

    # Ventana vieja (última request hace >1h en reloj monotónico)
    import time as _time
    vieja = deque([_time.monotonic() - 7200.0])
    app_mod._rate_limiter._windows["nodo-viejo"] = vieja
    app_mod._rate_limiter._windows["nodo-vacio"] = deque()

    hb = cliente.post("/api/node/heartbeat", json={"node_id": node_id})
    assert hb.status_code == 200, hb.text
    assert "nodo-viejo" not in app_mod._rate_limiter._windows
    assert "nodo-vacio" not in app_mod._rate_limiter._windows

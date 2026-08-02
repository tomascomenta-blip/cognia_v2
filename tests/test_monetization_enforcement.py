"""
tests/test_monetization_enforcement.py
======================================
Tests de integracion (TestClient) para la capa de monetizacion del Desktop API:

1. Middleware con validate_key_full (una consulta): 401 para claves
   invalidas/revocadas, user_id/tier correctos para claves validas.
2. PUT /auth/rate-limit/{user_id}: set_limit expuesto, protegido con X-Admin-Key,
   y el override realmente aplica en el middleware.
3. DELETE /auth/keys/{key_id}: resetea la ventana del rate limiter del dueno.
4. Enforcement de tiers: max_keys (POST /auth/keys), max_goals (POST /goals),
   max_webhooks (POST /webhooks), debug_endpoint (GET /debug/state).

Los singletons de cognia_desktop_api se parchean con instancias frescas sobre
DBs temporales para no tocar la DB de produccion ni compartir estado entre tests.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from cognia.auth.api_key_manager import APIKeyManager
from cognia.auth.rate_limiter import DesktopRateLimiter
from storage.db_pool import close_pool

ADMIN_KEY = "test-admin-secret"


def _make_mock_orch():
    orch = MagicMock()
    orch.status.return_value = {"manifest": "cognia_desktop", "mode": "auto", "fragments": {}, "bundles": {}}
    orch.shards_ready.return_value = False
    orch.ainfer = AsyncMock()
    orch._llama = None
    orch._draft = None
    return orch


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """API con manager de keys y rate limiter frescos sobre DB temporal."""
    import cognia_desktop_api as api

    db_file = str(tmp_path / "test_monetizacion.db")
    close_pool(db_file)
    mgr = APIKeyManager(db_path=db_file)
    limiter = DesktopRateLimiter(window_s=60)

    monkeypatch.setattr(api, "_orch", _make_mock_orch())
    monkeypatch.setattr(api, "_api_key_manager", mgr)
    monkeypatch.setattr(api, "_rate_limiter", limiter)
    monkeypatch.setenv("COGNIA_ADMIN_KEY", ADMIN_KEY)

    with TestClient(api.app, raise_server_exceptions=False) as client:
        yield api, client, mgr, limiter
    close_pool(db_file)


# ── 1. Middleware con validate_key_full ───────────────────────────────────


def test_middleware_no_key_is_local(env):
    _, client, _, limiter = env
    resp = client.get("/health")
    assert resp.status_code == 200
    # La request quedo registrada bajo "local"
    assert limiter.get_stats("local")["requests_in_window"] == 1


def test_middleware_invalid_key_401(env):
    _, client, _, _ = env
    resp = client.get("/health", headers={"X-API-Key": "cognia_sk_no_existe_123456"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or revoked API key"


def test_middleware_revoked_key_401(env):
    _, client, mgr, _ = env
    key = mgr.create_key("alice")
    key_id = mgr.list_keys("alice")[0]["id"]
    mgr.revoke_key(key_id)
    resp = client.get("/health", headers={"X-API-Key": key})
    assert resp.status_code == 401


def test_middleware_valid_key_resolves_user(env):
    _, client, mgr, limiter = env
    key = mgr.create_key("alice", tier="pro")
    resp = client.get("/health", headers={"X-API-Key": key})
    assert resp.status_code == 200
    # user_id resuelto por validate_key_full quedo en la ventana del limiter
    assert limiter.get_stats("alice")["requests_in_window"] == 1


def test_middleware_single_query(env, monkeypatch):
    """Regresion: el middleware ya no llama get_key_tier (una sola consulta)."""
    api, client, mgr, _ = env
    key = mgr.create_key("bob", tier="pro")

    def _boom(user_id):
        raise AssertionError("get_key_tier no debe llamarse desde el middleware")

    monkeypatch.setattr(mgr, "get_key_tier", _boom)
    resp = client.get("/health", headers={"X-API-Key": key})
    assert resp.status_code == 200


# ── 2. PUT /auth/rate-limit/{user_id} ─────────────────────────────────────


def test_set_rate_limit_requires_admin_configured(env, monkeypatch):
    _, client, _, _ = env
    monkeypatch.delenv("COGNIA_ADMIN_KEY")
    resp = client.put("/auth/rate-limit/u1", json={"limit": 5})
    assert resp.status_code == 503


def test_set_rate_limit_wrong_admin_key_401(env):
    _, client, _, _ = env
    resp = client.put(
        "/auth/rate-limit/u1", json={"limit": 5}, headers={"X-Admin-Key": "wrong"}
    )
    assert resp.status_code == 401


def test_set_rate_limit_negative_rejected(env):
    _, client, _, _ = env
    resp = client.put(
        "/auth/rate-limit/u1", json={"limit": -1}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert resp.status_code == 422


def test_set_rate_limit_persists_and_reflects_in_stats(env):
    _, client, _, limiter = env
    resp = client.put(
        "/auth/rate-limit/u1", json={"limit": 7}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert resp.status_code == 200
    assert resp.json()["limit"] == 7
    assert limiter.get_custom_limit("u1") == 7
    # GET existente lo refleja tambien
    stats = client.get("/auth/rate-limit/u1").json()
    assert stats["limit"] == 7


def test_custom_limit_overrides_tier_default_in_middleware(env):
    """El override por clave gana sobre el default del tier (local=200)."""
    _, client, _, limiter = env
    resp = client.put(
        "/auth/rate-limit/local", json={"limit": 2}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert resp.status_code == 200
    limiter.reset("local")  # limpiar la request del propio PUT
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    resp = client.get("/health")
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limit_exceeded"


# ── 3. DELETE /auth/keys/{key_id} resetea la ventana ──────────────────────


def test_revoke_key_resets_rate_window(env):
    _, client, mgr, limiter = env
    key = mgr.create_key("carol")
    key_id = mgr.list_keys("carol")[0]["id"]

    for _ in range(3):
        assert client.get("/health", headers={"X-API-Key": key}).status_code == 200
    assert limiter.get_stats("carol")["requests_in_window"] == 3

    resp = client.delete(f"/auth/keys/{key_id}")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": True, "id": key_id}
    # Sin estado fantasma: la ventana de carol quedo limpia
    assert limiter.get_stats("carol")["requests_in_window"] == 0


def test_revoke_unknown_key_still_404(env):
    _, client, _, _ = env
    assert client.delete("/auth/keys/999999").status_code == 404


# ── 4a. max_keys en POST /auth/keys ───────────────────────────────────────


def test_max_keys_free_tier_blocks_fourth_key(env):
    _, client, _, _ = env
    for i in range(3):  # free permite 3
        resp = client.post("/auth/keys", json={"user_id": "dave", "label": f"k{i}"})
        assert resp.status_code == 200, resp.text
    resp = client.post("/auth/keys", json={"user_id": "dave", "label": "k3"})
    assert resp.status_code == 403
    assert "max" in resp.json()["detail"].lower() or "at most" in resp.json()["detail"]


def test_max_keys_counts_only_active(env):
    _, client, mgr, _ = env
    for i in range(3):
        client.post("/auth/keys", json={"user_id": "erin", "label": f"k{i}"})
    key_id = mgr.list_keys("erin")[0]["id"]
    client.delete(f"/auth/keys/{key_id}")
    # Con una revocada quedan 2 activas: se puede crear otra
    resp = client.post("/auth/keys", json={"user_id": "erin", "label": "k3"})
    assert resp.status_code == 200


def test_max_keys_enterprise_unlimited(env):
    """Con tier enterprise (max_keys=-1) el gate no bloquea aunque haya mas de 3.

    Nota: el POST crea keys con tier 'free' y get_key_tier lee la ULTIMA key,
    asi que el tier enterprise se fija con keys pre-existentes via manager.
    """
    _, client, mgr, _ = env
    for _ in range(4):  # ya supera el limite de free (3)
        mgr.create_key("bigcorp", tier="enterprise")
    resp = client.post("/auth/keys", json={"user_id": "bigcorp", "label": "extra"})
    assert resp.status_code == 200, resp.text


# ── 4b. debug_endpoint en GET /debug/state ────────────────────────────────


def test_debug_state_local_tier_200(env):
    """El tier local (la propia maquina, sin API key) CONSERVA /debug/state:
    el curl local esta documentado en COMERCIAL_INVENTORY y gatearlo rompia
    ese uso. El enforcement del campo aplica a free/pro (tests de abajo)."""
    _, client, _, _ = env
    resp = client.get("/debug/state", headers={"X-Admin-Key": ADMIN_KEY})
    assert resp.status_code == 200, resp.text


def test_debug_state_free_tier_403(env):
    _, client, mgr, _ = env
    key = mgr.create_key("freeuser", tier="free")
    resp = client.get(
        "/debug/state", headers={"X-Admin-Key": ADMIN_KEY, "X-API-Key": key}
    )
    assert resp.status_code == 403


def test_debug_state_enterprise_tier_200(env):
    _, client, mgr, _ = env
    key = mgr.create_key("bigcorp", tier="enterprise")
    resp = client.get(
        "/debug/state", headers={"X-Admin-Key": ADMIN_KEY, "X-API-Key": key}
    )
    assert resp.status_code == 200


def test_debug_state_wrong_admin_key_still_401(env):
    _, client, _, _ = env
    resp = client.get("/debug/state", headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 401


# ── 4c. max_goals y max_webhooks ──────────────────────────────────────────


@pytest.fixture()
def goals_env(env, monkeypatch, tmp_path):
    """Suma GoalTracker y WebhookManager frescos sobre DB temporal."""
    api, client, mgr, limiter = env
    from cognia.goals.goal_tracker import GoalTracker
    from cognia.webhooks.webhook_manager import WebhookManager

    db_file = str(tmp_path / "test_goals_webhooks.db")
    close_pool(db_file)
    monkeypatch.setattr(api, "_goal_tracker", GoalTracker(db_path=db_file))
    monkeypatch.setattr(api, "_webhook_manager", WebhookManager(db_path=db_file))
    monkeypatch.setattr(api, "_analytics", None, raising=False)
    yield api, client, mgr, limiter
    close_pool(db_file)


def test_max_goals_free_tier_blocks_eleventh(goals_env):
    _, client, mgr, _ = goals_env
    key = mgr.create_key("alice", tier="free")
    headers = {"X-API-Key": key}
    for i in range(10):  # free permite 10
        resp = client.post(
            "/goals", json={"user_id": "alice", "title": f"meta {i}"}, headers=headers
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(
        "/goals", json={"user_id": "alice", "title": "meta 11"}, headers=headers
    )
    assert resp.status_code == 403
    assert "goals" in resp.json()["detail"]


def test_max_goals_local_tier_unlimited(goals_env):
    api, client, _, _ = goals_env
    for i in range(12):  # sin API key: tier local, ilimitado
        resp = client.post("/goals", json={"user_id": "localuser", "title": f"meta {i}"})
        assert resp.status_code == 200, resp.text


def test_max_webhooks_free_tier_blocks_fourth(goals_env):
    _, client, mgr, _ = goals_env
    key = mgr.create_key("alice", tier="free")
    headers = {"X-API-Key": key}
    for i in range(3):  # free permite 3
        resp = client.post(
            "/webhooks",
            json={"url": f"https://example.com/hook{i}", "events": ["goal.created"]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(
        "/webhooks",
        json={"url": "https://example.com/hook3", "events": ["goal.created"]},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "webhooks" in resp.json()["detail"]


def test_max_webhooks_local_tier_unlimited(goals_env):
    _, client, _, _ = goals_env
    for i in range(5):  # sin API key: tier local, ilimitado
        resp = client.post(
            "/webhooks",
            json={"url": f"https://example.com/local{i}", "events": ["goal.created"]},
        )
        assert resp.status_code == 200, resp.text

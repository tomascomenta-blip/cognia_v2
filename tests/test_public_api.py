"""
Tests for cognia_public_api.

Uses FastAPI's TestClient (sync wrapper over httpx.AsyncClient) so no
pytest-anyio dependency is needed.
"""
import sys
import os
import importlib

import pytest

# ---------------------------------------------------------------------------
# Path setup — make cognia_public_api importable without installing it
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "cognia_public_api")
if _API_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_API_DIR))

# Redirect DB to a temp dir so tests don't pollute /data or cwd
import tempfile
_TMP = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _TMP)

# Import modules after env is set
import key_store  # noqa: E402
import inference_proxy  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    """Each test gets its own isolated DB file."""
    os.environ["DATA_DIR"] = str(tmp_path)
    # Reload key_store so _DB_PATH picks up the new DATA_DIR
    importlib.reload(key_store)
    key_store.init_db()
    # Reload inference_proxy so module-level state is reset
    importlib.reload(inference_proxy)
    yield
    # Cleanup is handled by tmp_path fixture


@pytest.fixture()
def client(_fresh_db):
    # Import app lazily so lifespan doesn't fire on module import
    import app as api_app
    importlib.reload(api_app)
    from fastapi.testclient import TestClient

    # TestClient triggers lifespan by default (with_)
    with TestClient(api_app.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


def test_status(client):
    resp = client.get("/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "shard_loaded" in data


def test_create_key(client):
    resp = client.post("/v1/keys/create")
    assert resp.status_code == 200
    data = resp.json()
    assert "api_key" in data
    key = data["api_key"]
    assert key.startswith("cogn-")
    # format: cogn- + 16 hex chars
    hex_part = key[len("cogn-"):]
    assert len(hex_part) == 16
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_generate_no_auth(client):
    resp = client.post("/v1/generate", json={"prompt": "hello"})
    assert resp.status_code == 401


def test_generate_invalid_key(client):
    resp = client.post(
        "/v1/generate",
        json={"prompt": "hello"},
        headers={"Authorization": "Bearer cogn-0000000000000000"},
    )
    assert resp.status_code == 401


def test_generate_with_auth(client):
    # Create a real key first
    key_resp = client.post("/v1/keys/create")
    assert key_resp.status_code == 200
    key = key_resp.json()["api_key"]

    resp = client.post(
        "/v1/generate",
        json={"prompt": "hello cognia"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "text" in data
    assert "shard_loaded" in data


def test_create_key_rate_limit(client):
    """Create 5 keys (rate limit is 5/h per IP in prod); all must succeed in test env."""
    for _ in range(5):
        resp = client.post("/v1/keys/create")
        assert resp.status_code == 200
        key = resp.json()["api_key"]
        assert key.startswith("cogn-")
        hex_part = key[len("cogn-"):]
        assert len(hex_part) == 16
        assert all(c in "0123456789abcdef" for c in hex_part)


def test_status_has_required_fields(client):
    """GET /v1/status must include status, shard_loaded, coordinator, and version."""
    resp = client.get("/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    for field in ("status", "shard_loaded", "coordinator", "version"):
        assert field in data, f"missing field: {field}"


def test_generate_session_id_optional(client):
    """POST /v1/generate without session_id in body must succeed (field is optional)."""
    key_resp = client.post("/v1/keys/create")
    assert key_resp.status_code == 200
    key = key_resp.json()["api_key"]

    # Deliberately omit session_id
    resp = client.post(
        "/v1/generate",
        json={"prompt": "test optional session"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "text" in data

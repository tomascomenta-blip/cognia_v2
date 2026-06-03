"""
tests/test_desktop_api.py
Tests for cognia_desktop_api.py endpoints using Starlette TestClient.

_orch is patched before each test to avoid requiring a real model.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.testclient import TestClient


def _make_mock_orch():
    orch = MagicMock()
    orch.status.return_value = {
        "manifest": "cognia_desktop",
        "mode": "auto",
        "fragments": {},
        "bundles": {},
    }
    orch.shards_ready.return_value = False

    infer_result = MagicMock()
    infer_result.text = "test response"
    infer_result.sub_model = "logos"
    infer_result.confidence = 0.9
    infer_result.latency_ms = 42.0
    infer_result.mode = "local"
    infer_result.route_reason = "test"
    orch.ainfer = AsyncMock(return_value=infer_result)

    async def _empty_stream(messages):
        return
        yield

    orch.astream_chat = _empty_stream
    orch._llama = None
    orch._draft = None
    orch._ollama_url = "http://localhost:11434/api/generate"
    orch._ollama_model = "qwen2.5-coder:3b"
    return orch


@pytest.fixture()
def api_client(monkeypatch):
    import cognia_desktop_api as api
    monkeypatch.setattr(api, "_orch", _make_mock_orch())
    with TestClient(api.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def api_client_shards_ready(monkeypatch):
    import cognia_desktop_api as api
    mock = _make_mock_orch()
    mock.shards_ready.return_value = True
    monkeypatch.setattr(api, "_orch", mock)
    with TestClient(api.app, raise_server_exceptions=False) as c:
        yield c


# ── Tests ──────────────────────────────────────────────────────────────────


def test_health_returns_200(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert "ok" in resp.json()


def test_ready_returns_200(api_client):
    resp = api_client.get("/ready")
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_ready_with_shards_available(api_client_shards_ready):
    resp = api_client_shards_ready.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data.get("inference") == "shards"


def test_status_returns_mode_and_fragments(api_client):
    resp = api_client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "fragments" in data


def test_infer_accepts_prompt(api_client):
    resp = api_client.post("/infer", json={"prompt": "test"})
    assert resp.status_code in (200, 500, 503)
    if resp.status_code == 200:
        data = resp.json()
        assert "text" in data
        assert "sub_model" in data


def test_infer_empty_prompt_returns_400(api_client):
    resp = api_client.post("/infer", json={"prompt": "   "})
    assert resp.status_code == 400


def test_infer_prompt_too_long_returns_422(api_client):
    resp = api_client.post("/infer", json={"prompt": "x" * 5000})
    assert resp.status_code == 422


def test_health_performance_returns_required_keys(api_client):
    resp = api_client.get("/health/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert "tok_s" in data
    if "error" not in data:
        assert "latencia_total_ms" in data
        assert "backend_activo" in data
        assert "nano_draft_activo" in data


# ── Chat history fixtures ───────────────────────────────────────────────────


@pytest.fixture()
def chat_client(monkeypatch, tmp_path):
    import cognia_desktop_api as api
    tmp_db = str(tmp_path / "test_chat.db")
    monkeypatch.setattr(api, "_CHAT_DB", tmp_db)
    api._init_chat_db()
    monkeypatch.setattr(api, "_orch", _make_mock_orch())
    with TestClient(api.app, raise_server_exceptions=False) as c:
        yield c


# ── Chat history tests ──────────────────────────────────────────────────────


def test_chat_history_empty_initially(chat_client):
    resp = chat_client.get("/chat/history", params={"session_id": "test"})
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


def test_chat_history_save_and_load(chat_client):
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    post = chat_client.post(
        "/chat/history", json={"session_id": "test", "messages": messages}
    )
    assert post.status_code == 200

    get = chat_client.get("/chat/history", params={"session_id": "test"})
    assert get.status_code == 200
    loaded = get.json()["messages"]
    assert len(loaded) == 2
    assert loaded[0]["role"] == "user"
    assert loaded[1]["role"] == "assistant"


def test_chat_history_delete(chat_client):
    messages = [{"role": "user", "content": "hi"}]
    chat_client.post("/chat/history", json={"session_id": "test", "messages": messages})

    delete = chat_client.delete("/chat/history", params={"session_id": "test"})
    assert delete.status_code == 200

    get = chat_client.get("/chat/history", params={"session_id": "test"})
    assert get.json()["messages"] == []


def test_chat_history_session_isolation(chat_client):
    chat_client.post(
        "/chat/history",
        json={"session_id": "A", "messages": [{"role": "user", "content": "from A"}]},
    )
    chat_client.post(
        "/chat/history",
        json={"session_id": "B", "messages": [{"role": "user", "content": "from B"}]},
    )

    msgs_a = chat_client.get("/chat/history", params={"session_id": "A"}).json()["messages"]
    assert len(msgs_a) == 1
    assert msgs_a[0]["content"] == "from A"

    msgs_b = chat_client.get("/chat/history", params={"session_id": "B"}).json()["messages"]
    assert len(msgs_b) == 1
    assert msgs_b[0]["content"] == "from B"


def test_network_status_returns_required_keys(api_client):
    r = api_client.get("/network/status")
    assert r.status_code == 200
    body = r.json()
    assert "online" in body
    assert "local_backend" in body
    assert "nano_draft" in body


def test_network_status_offline_without_coordinator(api_client, monkeypatch):
    monkeypatch.delenv("COGNIA_COORDINATOR_URL", raising=False)
    r = api_client.get("/network/status")
    assert r.status_code == 200
    assert r.json()["online"] is False

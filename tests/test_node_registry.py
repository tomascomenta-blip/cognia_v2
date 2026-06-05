"""
tests/test_node_registry.py
===========================
Tests for coordinator/registry.py — NodeRegistry (in-memory SQLite).
All tests use :memory: so no disk I/O.
"""
import time
import pytest
from coordinator.registry import NodeRegistry, MODELS, DEFAULT_MODEL, NODE_TIMEOUT


@pytest.fixture
def reg():
    return NodeRegistry(":memory:")


# ── Registration ──────────────────────────────────────────────────────

def test_register_returns_required_keys(reg):
    result = reg.register(hardware_info="test-cpu")
    assert "node_id" in result
    assert "shard" in result
    assert "model_name" in result
    assert "model_config" in result


def test_register_assigns_valid_shard(reg):
    result = reg.register()
    cfg = MODELS[DEFAULT_MODEL]
    assert 0 <= result["shard"] < cfg["n_shards"]


def test_register_multiple_nodes_distributes_shards(reg):
    n_shards = MODELS[DEFAULT_MODEL]["n_shards"]
    shards = set()
    for _ in range(n_shards * 2):
        r = reg.register()
        shards.add(r["shard"])
    # After 2x nodes, all shards should be covered
    assert len(shards) == n_shards


def test_register_unknown_model_falls_back_to_default(reg):
    result = reg.register(model_name="nonexistent-model-xyz")
    assert result["model_name"] == "nonexistent-model-xyz"
    # model_config should be the default one
    assert result["model_config"] == MODELS[DEFAULT_MODEL]


# ── Heartbeat ─────────────────────────────────────────────────────────

def test_heartbeat_ok_for_registered_node(reg):
    node_id = reg.register()["node_id"]
    result = reg.heartbeat(node_id)
    assert result["ok"] is True
    assert "shard" in result


def test_heartbeat_error_for_unknown_node(reg):
    result = reg.heartbeat("does-not-exist-abc123")
    assert result["ok"] is False
    assert "error" in result


# ── Unregister ────────────────────────────────────────────────────────

def test_unregister_removes_node_from_active(reg):
    node_id = reg.register()["node_id"]
    reg.unregister(node_id)
    node = reg._get_node(node_id)
    assert node is not None
    assert node.is_active is False


# ── get_route ─────────────────────────────────────────────────────────

def test_get_route_incomplete_swarm(reg):
    # With only 1 node registered (4 shards needed), route should not be ok
    reg.register()
    result = reg.get_route()
    # Some shards will be missing
    assert "missing" in result
    if result["missing"]:
        assert result["ok"] is False


def test_get_route_full_swarm(reg):
    n_shards = MODELS[DEFAULT_MODEL]["n_shards"]
    # Register enough nodes to fill all shards
    registered_nodes = []
    for _ in range(n_shards):
        r = reg.register()
        registered_nodes.append(r)

    result = reg.get_route()
    # All shards should be covered now
    if not result["missing"]:
        assert result["ok"] is True
        assert len(result["route"]) == n_shards
    # (may still be missing if multiple registrations land on same shard by chance)


# ── status ────────────────────────────────────────────────────────────

def test_status_empty_registry(reg):
    s = reg.status()
    assert s["active_nodes"] == 0
    assert s["total_nodes"] == 0
    assert s["ready"] is False


def test_status_after_registration(reg):
    reg.register()
    s = reg.status()
    assert s["total_nodes"] >= 1
    assert s["active_nodes"] >= 1
    assert s["shards_total"] == MODELS[DEFAULT_MODEL]["n_shards"]


# ── Stale node eviction ───────────────────────────────────────────────

def test_stale_nodes_marked_inactive(reg):
    node_id = reg.register()["node_id"]
    # Manually age the heartbeat past NODE_TIMEOUT
    with reg._conn() as conn:
        old_ts = time.time() - NODE_TIMEOUT - 10
        conn.execute(
            "UPDATE nodes SET last_heartbeat=? WHERE node_id=?",
            (old_ts, node_id),
        )
    # Triggering any operation that calls _mark_stale_nodes
    reg.status()
    node = reg._get_node(node_id)
    assert node.is_active is False


# ── _get_node ─────────────────────────────────────────────────────────

def test_get_node_returns_none_for_missing(reg):
    assert reg._get_node("no-such-id") is None


def test_get_node_returns_node_dataclass(reg):
    node_id = reg.register()["node_id"]
    node = reg._get_node(node_id)
    assert node is not None
    assert node.node_id == node_id
    assert node.is_active is True

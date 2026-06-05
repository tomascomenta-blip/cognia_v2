"""
tests/test_federated_store.py
=============================
Unit tests for coordinator/federated_store.py (FedAvg engine).

All tests use in-memory SQLite so no coordinator.db file is created.
"""

import io
import sys
import os

import numpy as np
import pytest

# Ensure project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from coordinator.federated_store import (
    FederatedStore,
    AGGREGATE_EVERY_N,
    MIN_CONTRIBUTORS,
    MAX_BLOB_BYTES,
    _HIDDEN_DIM,
    _KV_PROJ_OUT,
    _effective_delta_embed,
    _semantic_cosine,
    _pad_to_rank,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_adapter_blob(rank: int = 4, scale: float = 0.01) -> bytes:
    """
    Create a valid ELC adapter npz blob with the given rank.
    Uses a small random fill so averaged adapters are non-trivial.
    """
    rng = np.random.default_rng(42 + rank)
    arrays = {
        "k_A": rng.standard_normal((rank, _HIDDEN_DIM)).astype(np.float32) * scale,
        "k_B": rng.standard_normal((_KV_PROJ_OUT, rank)).astype(np.float32) * scale,
        "v_A": rng.standard_normal((rank, _HIDDEN_DIM)).astype(np.float32) * scale,
        "v_B": rng.standard_normal((_KV_PROJ_OUT, rank)).astype(np.float32) * scale,
    }
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def _make_store() -> FederatedStore:
    return FederatedStore(db_path=":memory:")


# ── Tests: helper functions ──────────────────────────────────────────────

def test_effective_delta_embed_unit_norm():
    """_effective_delta_embed should return a unit-norm vector."""
    blob = _make_adapter_blob(rank=4)
    data = np.load(io.BytesIO(blob), allow_pickle=False)
    vec = _effective_delta_embed({k: data[k].astype(np.float32) for k in ("k_A", "k_B", "v_A", "v_B")})
    assert abs(np.linalg.norm(vec) - 1.0) < 1e-5


def test_semantic_cosine_identical():
    """Identical vectors should give cosine similarity = 1.0."""
    blob = _make_adapter_blob(rank=4)
    data = np.load(io.BytesIO(blob), allow_pickle=False)
    vec = _effective_delta_embed({k: data[k].astype(np.float32) for k in ("k_A", "k_B", "v_A", "v_B")})
    assert _semantic_cosine(vec, vec) == pytest.approx(1.0, abs=1e-5)


def test_semantic_cosine_range():
    """Cosine similarity should always be in [-1, 1]."""
    blob_a = _make_adapter_blob(rank=4, scale=0.01)
    blob_b = _make_adapter_blob(rank=4, scale=0.5)
    d_a = np.load(io.BytesIO(blob_a), allow_pickle=False)
    d_b = np.load(io.BytesIO(blob_b), allow_pickle=False)
    keys = ("k_A", "k_B", "v_A", "v_B")
    va = _effective_delta_embed({k: d_a[k].astype(np.float32) for k in keys})
    vb = _effective_delta_embed({k: d_b[k].astype(np.float32) for k in keys})
    cos = _semantic_cosine(va, vb)
    assert -1.0 <= cos <= 1.0


def test_pad_to_rank_shapes():
    """_pad_to_rank should produce correct shapes when rank increases."""
    blob = _make_adapter_blob(rank=4)
    data = np.load(io.BytesIO(blob), allow_pickle=False)
    arrays = {k: data[k] for k in ("k_A", "k_B", "v_A", "v_B")}
    padded = _pad_to_rank(arrays, target_rank=8)
    assert padded["k_A"].shape == (8, _HIDDEN_DIM)
    assert padded["k_B"].shape == (_KV_PROJ_OUT, 8)
    assert padded["v_A"].shape == (8, _HIDDEN_DIM)
    assert padded["v_B"].shape == (_KV_PROJ_OUT, 8)


def test_pad_to_rank_no_change_same_rank():
    """_pad_to_rank with same rank returns original arrays."""
    blob = _make_adapter_blob(rank=4)
    data = np.load(io.BytesIO(blob), allow_pickle=False)
    arrays = {k: data[k] for k in ("k_A", "k_B", "v_A", "v_B")}
    result = _pad_to_rank(arrays, target_rank=4)
    np.testing.assert_array_equal(result["k_A"], arrays["k_A"])


# ── Tests: FederatedStore API ────────────────────────────────────────────

def test_store_init_stats_empty():
    """Fresh store should report zero pending and version 0."""
    store = _make_store()
    s = store.stats()
    assert s["global_version"] == 0
    assert s["pending_contributions"] == 0
    assert s["total_contributions"] == 0


def test_add_contribution_valid_returns_id():
    """Adding a valid blob from a qualifying node returns a UUID string."""
    store = _make_store()
    blob = _make_adapter_blob(rank=4)
    contrib_id = store.add_contribution("node_abc", total_params_b=1.0, adapter_blob=blob)
    assert contrib_id is not None
    assert len(contrib_id) == 36  # UUID format


def test_add_contribution_too_large_rejected():
    """Blobs larger than MAX_BLOB_BYTES should be rejected (returns None)."""
    store = _make_store()
    oversized = b"x" * (MAX_BLOB_BYTES + 1)
    result = store.add_contribution("node_xyz", total_params_b=1.0, adapter_blob=oversized)
    assert result is None


def test_add_contribution_invalid_blob_rejected():
    """Garbage bytes should be rejected (returns None)."""
    store = _make_store()
    result = store.add_contribution("node_xyz", total_params_b=1.0, adapter_blob=b"not_an_npz")
    assert result is None


def test_add_contribution_tier_none_rejected():
    """Nodes with total_params_b = 0.0 (tier='none') should be rejected."""
    store = _make_store()
    blob = _make_adapter_blob(rank=4)
    result = store.add_contribution("node_none", total_params_b=0.0, adapter_blob=blob)
    assert result is None


def test_aggregate_not_triggered_below_threshold():
    """Fewer than AGGREGATE_EVERY_N contributions should not trigger auto-aggregate."""
    store = _make_store()
    blob = _make_adapter_blob(rank=4)
    for i in range(AGGREGATE_EVERY_N - 1):
        store.add_contribution(f"node_{i}", total_params_b=1.0, adapter_blob=blob)
    assert store.get_global_adapter() is None
    assert store.stats()["global_version"] == 0


def test_aggregate_triggered_at_threshold():
    """AGGREGATE_EVERY_N contributions should trigger FedAvg and produce a global adapter."""
    store = _make_store()
    for i in range(AGGREGATE_EVERY_N):
        blob = _make_adapter_blob(rank=4, scale=float(i + 1) * 0.01)
        store.add_contribution(f"node_{i}", total_params_b=1.0, adapter_blob=blob)
    global_blob = store.get_global_adapter()
    assert global_blob is not None
    # Must be loadable as a valid npz
    data = np.load(io.BytesIO(global_blob), allow_pickle=False)
    assert "k_A" in data.files


def test_aggregate_marks_contributions_applied():
    """After aggregation, pending_contributions should drop to zero."""
    store = _make_store()
    for i in range(AGGREGATE_EVERY_N):
        blob = _make_adapter_blob(rank=4)
        store.add_contribution(f"node_{i}", total_params_b=1.0, adapter_blob=blob)
    s = store.stats()
    assert s["pending_contributions"] == 0
    assert s["global_version"] >= 1


def test_aggregate_version_increments():
    """Each successful aggregation should increment the global version."""
    store = _make_store()
    for _round in range(2):
        for i in range(AGGREGATE_EVERY_N):
            blob = _make_adapter_blob(rank=4, scale=float(i + _round + 1) * 0.01)
            store.add_contribution(f"node_{_round}_{i}", total_params_b=1.0, adapter_blob=blob)
    assert store.stats()["global_version"] >= 2


def test_aggregate_mixed_ranks():
    """
    Contributions with different ranks should be padded and aggregated
    without error; global adapter rank equals the max input rank.
    """
    store = _make_store()
    ranks = [4, 4, 6, 8, 4]  # mix of ranks, len == AGGREGATE_EVERY_N
    assert len(ranks) == AGGREGATE_EVERY_N
    for i, rank in enumerate(ranks):
        blob = _make_adapter_blob(rank=rank)
        store.add_contribution(f"node_{i}", total_params_b=1.0, adapter_blob=blob)
    global_blob = store.get_global_adapter()
    assert global_blob is not None
    data = np.load(io.BytesIO(global_blob), allow_pickle=False)
    assert data["k_A"].shape[0] == max(ranks)

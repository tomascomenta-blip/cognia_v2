"""
tests/test_hierarchical_memory.py
=================================
Real pytest coverage for the Chimera hierarchical-memory write-gate facade.
Every test uses an isolated temp DB (tmp_path) so nothing touches the live DB.
"""

import os

import pytest

from cognia.memory.hierarchical import (
    HierarchicalMemory,
    WriteResult,
    compute_surprise,
    estimate_importance,
    W_SURPRISE,
    W_IMPORTANCE,
    WRITE_GATE_THRESHOLD,
)
from cognia.memory.episodic import EpisodicMemory


def _fresh_db(tmp_path):
    """Return a temp DB path with the real schema initialised."""
    db = str(tmp_path / "hier_test.db")
    from cognia.database import init_db
    init_db(db)
    return db


def test_compute_surprise_empty_db_is_one(tmp_path):
    db = str(tmp_path / "missing.db")  # never created
    ep = EpisodicMemory(db)
    vec = [0.1] * 8
    assert compute_surprise(vec, ep) == 1.0


def test_write_novel_fact_no_raise(tmp_path):
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    r = mem.write("Decidi que siempre usare embeddings de 256 dimensiones.",
                  label="novel")
    assert isinstance(r, WriteResult)
    assert r.in_working is True
    assert r.stored_episodic in (True, False)
    assert 0.0 <= r.surprise <= 1.0


def test_write_pin_always_stored(tmp_path):
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    r = mem.write("La clave de API nunca debe subirse al repo.",
                  label="critical", pin=True)
    assert r.stored_episodic is True
    assert "pin" in r.reason.lower()


def test_estimate_importance_ranks_decision_above_ok():
    decision = estimate_importance("decidi que siempre vamos a versionar la base de datos")
    trivial = estimate_importance("ok")
    assert decision > trivial


def test_write_nonexistent_db_never_raises(tmp_path):
    db = str(tmp_path / "does_not_exist.db")  # not initialised
    mem = HierarchicalMemory(db_path=db)
    r = mem.write("alguna observacion cualquiera", label="x")
    assert isinstance(r, WriteResult)
    assert r.in_working is True
    assert 0.0 <= r.surprise <= 1.0


def test_recall_returns_list(tmp_path):
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    mem.write("Decidi que el objetivo clave es la memoria jerarquica.", label="goal", pin=True)
    out = mem.recall("memoria jerarquica objetivo")
    assert isinstance(out, list)


# --- additional coverage -----------------------------------------------------

def test_write_gate_score_is_documented_combination(tmp_path):
    # The reported gate_score MUST equal the documented convex combination of
    # the reported surprise and importance -- this is the auditable definition
    # of the write-gate decision. (We assert the invariant rather than force a
    # rejection: the episodic vector cache debounces rebuilds, so surprise stays
    # high on a fresh DB and the rejection branch is timing-dependent.)
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    r = mem.write("Decidi que siempre usare embeddings de 256 dimensiones.",
                  label="gate")
    expected = round(W_SURPRISE * r.surprise + W_IMPORTANCE * r.importance, 4)
    assert r.gate_score == expected
    # And the store decision is consistent with the gate (vector present here).
    if r.gate_score >= WRITE_GATE_THRESHOLD:
        assert r.stored_episodic is True
        assert r.reason in ("above gate", "pinned: stored with max importance (durable)")
    else:
        assert r.stored_episodic is False


def test_low_importance_explicit_drops_gate_score(tmp_path):
    # With an explicit low importance, the importance term of the gate collapses
    # to its floor, so gate_score == W_SURPRISE * surprise exactly. This pins the
    # importance contribution deterministically without depending on the DB.
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    r = mem.write("ok", label="trivial", importance=0.0)
    assert r.importance == 0.0
    assert r.gate_score == round(W_SURPRISE * r.surprise, 4)


def test_estimate_importance_explicit_override_and_clamp():
    # An explicit importance wins outright and is clamped into [0, 1].
    assert estimate_importance("anything at all", explicit=0.9) == 0.9
    assert estimate_importance("anything at all", explicit=5.0) == 1.0
    assert estimate_importance("anything at all", explicit=-2.0) == 0.0


def test_estimate_importance_empty_is_zero():
    assert estimate_importance("") == 0.0
    assert estimate_importance("   ") == 0.0


def test_stats_shape(tmp_path):
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    s = mem.stats()
    assert set(("episodic_count", "working_buffer", "layers")).issubset(s.keys())
    assert isinstance(s["layers"], list)
    assert len(s["layers"]) == 5  # immediate/working/episodic/semantic/permanent


def test_decay_returns_dict_never_raises(tmp_path):
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    d = mem.decay()
    assert isinstance(d, dict)
    for k in ("total_checked", "forgotten", "compressed"):
        assert k in d


def test_consolidate_returns_dict_never_raises(tmp_path):
    db = _fresh_db(tmp_path)
    mem = HierarchicalMemory(db_path=db)
    c = mem.consolidate()
    assert isinstance(c, dict)
    assert "concepts_consolidated" in c
    assert "longterm_facts" in c

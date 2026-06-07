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

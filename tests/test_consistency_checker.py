"""
tests/test_consistency_checker.py
===================================
5 unit tests for ConsistencyChecker.
"""

import os
import tempfile
import pytest

from cognia.knowledge.consistency_checker import ConsistencyChecker


@pytest.fixture
def checker(tmp_path):
    db = str(tmp_path / "test_kg.db")
    # Pre-populate knowledge_graph table so queries don't fail on missing table
    from storage.db_pool import get_pool
    with get_pool(db).get() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_graph (
                id          INTEGER PRIMARY KEY,
                subject     TEXT,
                predicate   TEXT,
                object      TEXT,
                weight      REAL DEFAULT 1.0,
                last_accessed REAL DEFAULT 0
            )"""
        )
    return ConsistencyChecker(db_path=db)


def test_find_contradictions_returns_list(checker):
    result = checker.find_contradictions()
    assert isinstance(result, list)


def test_store_conflict_returns_int_id(checker):
    cid = checker.store_conflict("A", "is_a", "B", "C")
    assert isinstance(cid, int)
    assert cid > 0


def test_resolve_conflict_returns_true(checker):
    cid = checker.store_conflict("X", "has_property", "fast", "slow")
    ok = checker.resolve_conflict(cid)
    assert ok is True


def test_get_stats_returns_required_keys(checker):
    checker.store_conflict("P", "tipo", "q1", "q2")
    stats = checker.get_stats()
    assert "total" in stats
    assert "unresolved" in stats
    assert "resolved" in stats
    assert stats["total"] >= 1


def test_run_check_returns_int(checker):
    result = checker.run_check()
    assert isinstance(result, int)

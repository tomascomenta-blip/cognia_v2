"""
tests/test_staleness_detector.py
==================================
Tests for StalenessDetector — KG staleness and weight decay.
"""

import os
import sys
import time
import sqlite3
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _create_kg_db(path: str) -> None:
    """Create minimal KG schema including last_accessed column."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_graph (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            subject       TEXT NOT NULL,
            predicate     TEXT NOT NULL,
            object        TEXT NOT NULL,
            weight        REAL DEFAULT 1.0,
            source        TEXT DEFAULT 'learned',
            timestamp     TEXT,
            verified      INTEGER DEFAULT 0,
            last_accessed REAL DEFAULT 0.0,
            UNIQUE(subject, predicate, object)
        )
    """)
    conn.commit()
    conn.close()


def _drain_pool(db_path: str) -> None:
    """Release all pooled connections for db_path (needed on Windows)."""
    try:
        from storage.db_pool import _pools
        pool = _pools.get(db_path)
        if pool is None:
            return
        conns = []
        while True:
            try:
                conns.append(pool._pool.get_nowait())
            except Exception:
                break
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        _pools.pop(db_path, None)
    except Exception:
        pass


def _insert_fact(db_path: str, subject: str, predicate: str, obj: str,
                 weight: float = 1.0, last_accessed: float = 0.0) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR IGNORE INTO knowledge_graph
           (subject, predicate, object, weight, last_accessed)
           VALUES (?, ?, ?, ?, ?)""",
        (subject, predicate, obj, weight, last_accessed),
    )
    conn.commit()
    conn.close()


# ── constants tests ───────────────────────────────────────────────────────────

class TestStalenessConstants:
    def _make_detector(self, db_path):
        from cognia.knowledge.staleness_detector import StalenessDetector
        return StalenessDetector(db_path=db_path)

    def test_decay_factor_less_than_one(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        assert d.DECAY_FACTOR < 1.0
        _drain_pool(db)

    def test_min_weight_greater_than_zero(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        assert d.MIN_WEIGHT > 0.0
        _drain_pool(db)

    def test_stale_days_positive(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        assert d.STALE_DAYS > 0
        _drain_pool(db)


# ── get_stale_facts tests ─────────────────────────────────────────────────────

class TestGetStaleFacts:
    def _make_detector(self, db_path):
        from cognia.knowledge.staleness_detector import StalenessDetector
        return StalenessDetector(db_path=db_path)

    def test_returns_list(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        result = d.get_stale_facts()
        assert isinstance(result, list)
        _drain_pool(db)

    def test_empty_db_returns_empty_list(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        assert d.get_stale_facts() == []
        _drain_pool(db)

    def test_stale_fact_detected(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        # Insert a fact never accessed (last_accessed=0) with weight above MIN
        _insert_fact(db, "python", "is_a", "language", weight=0.8, last_accessed=0.0)
        d = self._make_detector(db)
        facts = d.get_stale_facts()
        assert len(facts) == 1
        assert facts[0]["subject"] == "python"
        _drain_pool(db)

    def test_recently_accessed_fact_not_stale(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        # Insert a fact accessed just now
        _insert_fact(db, "python", "is_a", "language", weight=0.8,
                     last_accessed=time.time())
        d = self._make_detector(db)
        assert d.get_stale_facts() == []
        _drain_pool(db)

    def test_stale_fact_at_min_weight_excluded(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        from cognia.knowledge.staleness_detector import StalenessDetector
        d = StalenessDetector(db_path=db)
        # Insert fact with weight == MIN_WEIGHT (should NOT appear — condition is weight > MIN)
        _insert_fact(db, "x", "related_to", "y", weight=d.MIN_WEIGHT, last_accessed=0.0)
        assert d.get_stale_facts() == []
        _drain_pool(db)

    def test_result_has_expected_keys(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        _insert_fact(db, "algo", "causes", "efecto", weight=1.0, last_accessed=0.0)
        d = self._make_detector(db)
        facts = d.get_stale_facts()
        assert len(facts) >= 1
        keys = {"subject", "predicate", "object", "weight", "last_accessed_days_ago"}
        assert keys.issubset(facts[0].keys())
        _drain_pool(db)


# ── get_stats tests ───────────────────────────────────────────────────────────

class TestGetStats:
    def _make_detector(self, db_path):
        from cognia.knowledge.staleness_detector import StalenessDetector
        return StalenessDetector(db_path=db_path)

    def test_returns_dict_with_expected_keys(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        stats = d.get_stats()
        expected_keys = {
            "total_facts", "stale_facts", "never_accessed_facts",
            "avg_weight", "min_weight_facts",
        }
        assert expected_keys.issubset(stats.keys())
        _drain_pool(db)

    def test_empty_db_stats_all_zero(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        stats = d.get_stats()
        assert stats["total_facts"] == 0
        assert stats["stale_facts"] == 0
        assert stats["never_accessed_facts"] == 0
        assert stats["avg_weight"] == 0.0
        _drain_pool(db)

    def test_stats_count_correctly(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        _insert_fact(db, "a", "is_a", "b", weight=1.0, last_accessed=0.0)
        _insert_fact(db, "c", "is_a", "d", weight=1.0, last_accessed=time.time())
        d = self._make_detector(db)
        stats = d.get_stats()
        assert stats["total_facts"] == 2
        assert stats["never_accessed_facts"] == 1  # only one with last_accessed=0
        _drain_pool(db)


# ── apply_decay tests ─────────────────────────────────────────────────────────

class TestApplyDecay:
    def _make_detector(self, db_path):
        from cognia.knowledge.staleness_detector import StalenessDetector
        return StalenessDetector(db_path=db_path)

    def test_dry_run_does_not_modify_db(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        _insert_fact(db, "x", "related_to", "y", weight=1.0, last_accessed=0.0)
        d = self._make_detector(db)
        result = d.apply_decay(dry_run=True)
        assert result["dry_run"] is True
        # Verify weight unchanged
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT weight FROM knowledge_graph").fetchone()
        conn.close()
        assert row[0] == 1.0
        _drain_pool(db)

    def test_dry_run_returns_correct_count(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        _insert_fact(db, "x", "related_to", "y", weight=1.0, last_accessed=0.0)
        _insert_fact(db, "a", "is_a", "b", weight=1.0, last_accessed=time.time())
        d = self._make_detector(db)
        result = d.apply_decay(dry_run=True)
        # Only the never-accessed one is stale
        assert result["facts_decayed"] == 1
        _drain_pool(db)

    def test_apply_decay_reduces_weight(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        _insert_fact(db, "x", "related_to", "y", weight=1.0, last_accessed=0.0)
        d = self._make_detector(db)
        d.apply_decay(dry_run=False)
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT weight FROM knowledge_graph").fetchone()
        conn.close()
        assert row[0] < 1.0
        _drain_pool(db)

    def test_apply_decay_weight_not_below_min(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        from cognia.knowledge.staleness_detector import StalenessDetector
        d = StalenessDetector(db_path=db)
        # Insert with weight just above MIN_WEIGHT
        initial = d.MIN_WEIGHT + 0.001
        _insert_fact(db, "x", "related_to", "y", weight=initial, last_accessed=0.0)
        d.apply_decay(dry_run=False)
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT weight FROM knowledge_graph").fetchone()
        conn.close()
        assert row[0] >= d.MIN_WEIGHT
        _drain_pool(db)

    def test_apply_decay_returns_dict_keys(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_kg_db(db)
        d = self._make_detector(db)
        result = d.apply_decay(dry_run=False)
        assert "facts_decayed" in result
        assert "facts_already_min" in result
        assert "dry_run" in result
        _drain_pool(db)

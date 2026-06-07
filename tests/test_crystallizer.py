"""
tests/test_crystallizer.py
===========================
Unit tests for KnowledgeCrystallizer.
Uses an in-memory SQLite DB so no file system pollution.
"""

import sqlite3
import tempfile
import os
import pytest

# ---------------------------------------------------------------------------
# Minimal stub so db_connect_pooled works in tests without full pool setup
# ---------------------------------------------------------------------------

import types, sys

# If storage.db_pool is not importable, patch it with a simple connection factory.
try:
    from storage.db_pool import db_connect_pooled  # noqa: F401
except Exception:
    _storage_mod = types.ModuleType("storage")
    _pool_mod = types.ModuleType("storage.db_pool")

    def _db_connect_stub(db_path: str):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    _pool_mod.db_connect_pooled = _db_connect_stub
    sys.modules.setdefault("storage", _storage_mod)
    sys.modules.setdefault("storage.db_pool", _pool_mod)

# Patch cognia.config.DB_PATH before import so crystallizer uses temp DB
import types as _types
_config_mod = sys.modules.get("cognia.config") or sys.modules.get("config")
_TMPFILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPFILE.close()
_TMPDB = _TMPFILE.name


def _setup_test_db(db_path: str) -> None:
    """Create knowledge_graph table with minimum columns."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS knowledge_graph (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            source TEXT DEFAULT 'test',
            timestamp TEXT DEFAULT '',
            last_accessed REAL DEFAULT 0.0
        )"""
    )
    conn.commit()
    conn.close()


_setup_test_db(_TMPDB)

# Now import the module under test
from cognia.knowledge.crystallizer import KnowledgeCrystallizer


@pytest.fixture
def cryst():
    """Fresh crystallizer backed by a temp DB with known data."""
    _setup_test_db(_TMPDB)
    # Insert some test facts
    conn = sqlite3.connect(_TMPDB)
    conn.execute("DELETE FROM knowledge_graph")
    conn.executemany(
        "INSERT INTO knowledge_graph (subject, predicate, object, weight, last_accessed) VALUES (?, ?, ?, ?, ?)",
        [
            ("python", "is_a", "language", 2.0, 0.0),
            ("cognia", "is_a", "ai_system", 1.5, 0.0),
            ("llm", "capable_of", "generation", 0.5, 0.0),
        ],
    )
    conn.commit()
    conn.close()
    return KnowledgeCrystallizer(db_path=_TMPDB)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_crystallize_frequent_returns_int(cryst):
    """crystallize_frequent() must return an integer (>= 0)."""
    result = cryst.crystallize_frequent(min_accesses=5)
    assert isinstance(result, int)
    assert result >= 0


def test_get_crystallized_returns_list(cryst):
    """get_crystallized() must return a list of dicts."""
    cryst.crystallize_frequent(min_accesses=5)
    result = cryst.get_crystallized()
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, dict)
        assert "subject" in item
        assert "predicate" in item
        assert "object" in item
        assert "weight" in item


def test_get_stats_returns_required_keys(cryst):
    """get_stats() must include total_facts, crystallized, crystallization_rate."""
    stats = cryst.get_stats()
    assert isinstance(stats, dict)
    assert "total_facts" in stats
    assert "crystallized" in stats
    assert "crystallization_rate" in stats
    assert isinstance(stats["total_facts"], int)
    assert isinstance(stats["crystallized"], int)
    assert isinstance(stats["crystallization_rate"], float)


def test_decrystallize_stale_returns_int(cryst):
    """decrystallize_stale() must return an integer."""
    # First crystallize, then decrystallize
    cryst.crystallize_frequent(min_accesses=5)
    result = cryst.decrystallize_stale(stale_days=0)
    assert isinstance(result, int)
    assert result >= 0


def test_get_injection_context_empty_when_no_crystallized(cryst):
    """get_injection_context() returns empty string when nothing is crystallized."""
    # Ensure nothing is crystallized by resetting
    conn = sqlite3.connect(_TMPDB)
    conn.execute("UPDATE knowledge_graph SET crystallized = 0")
    conn.commit()
    conn.close()
    result = cryst.get_injection_context(5)
    assert result == ""

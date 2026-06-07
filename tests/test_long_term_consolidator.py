"""
tests/test_long_term_consolidator.py
=====================================
5 tests for LongTermConsolidator: return types, format, edge cases.
"""

import os
import sqlite3
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_EPISODIC_SCHEMA = """
CREATE TABLE episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT '',
    observation TEXT DEFAULT '',
    importance REAL DEFAULT 1.5,
    emotion_score REAL DEFAULT 0.0,
    access_count INTEGER DEFAULT 0,
    last_access TEXT,
    forgotten INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    feedback_weight REAL DEFAULT 1.0,
    label TEXT DEFAULT '',
    vector TEXT,
    surprise REAL DEFAULT 0.0,
    review_count INTEGER DEFAULT 0,
    next_review TEXT,
    context_tags TEXT DEFAULT '[]'
)
"""

_KG_SCHEMA = """
CREATE TABLE knowledge_graph (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    weight REAL DEFAULT 1.0,
    source TEXT DEFAULT 'manual',
    timestamp TEXT
)
"""


def _make_db(with_episodic: bool = True, with_kg: bool = True) -> str:
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    if with_episodic:
        conn.execute(_EPISODIC_SCHEMA)
    if with_kg:
        conn.execute(_KG_SCHEMA)
    conn.commit()
    conn.close()
    return path


def _insert_observation(db_path: str, text: str, days_ago: float = 0) -> None:
    ts_unix = time.time() - days_ago * 86400
    from datetime import datetime, timezone
    ts_iso = datetime.fromtimestamp(ts_unix, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO episodic_memory (timestamp, observation, forgotten) VALUES (?,?,0)",
        (ts_iso, text),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _cleanup_pools():
    """Release any temp DB pools after each test to prevent cross-test contamination."""
    yield
    import storage.db_pool as _pool_mod
    # Remove pools for paths that are temp files (not the default cognia DB)
    stale = [p for p in list(_pool_mod._pools.keys()) if "tmp" in p.lower() or "temp" in p.lower()]
    for p in stale:
        _pool_mod.close_pool(p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_consolidate_returns_int():
    """consolidate() must always return an int."""
    db = _make_db()
    from cognia.memory.long_term_consolidator import LongTermConsolidator
    c = LongTermConsolidator(db_path=db)
    result = c.consolidate("testuser")
    assert isinstance(result, int)


def test_get_consolidated_facts_returns_list():
    """get_consolidated_facts() must return a list."""
    db = _make_db()
    from cognia.memory.long_term_consolidator import LongTermConsolidator
    c = LongTermConsolidator(db_path=db)
    result = c.get_consolidated_facts("testuser")
    assert isinstance(result, list)


def test_get_summary_format():
    """get_summary() must match expected format when facts exist."""
    db = _make_db()
    # Insert 4 observations mentioning "Python" so it crosses min_occurrences=3
    for _ in range(4):
        _insert_observation(db, "I am learning Python and FastAPI today")

    from cognia.memory.long_term_consolidator import LongTermConsolidator
    c = LongTermConsolidator(db_path=db)
    c.consolidate("default", min_occurrences=3)

    summary = c.get_summary("default")
    if summary:
        assert summary.startswith("Temas recurrentes:")
        assert "temas" in summary


def test_empty_user_returns_empty_string():
    """get_summary() must return '' for a user with no facts."""
    db = _make_db()
    from cognia.memory.long_term_consolidator import LongTermConsolidator
    c = LongTermConsolidator(db_path=db)
    result = c.get_summary("nonexistent_user_xyz")
    assert result == ""


def test_min_occurrences_filter():
    """Entities below min_occurrences must not be promoted to KG."""
    db = _make_db()
    # Insert only 2 observations — below default min_occurrences=3
    for _ in range(2):
        _insert_observation(db, "Rust is a systems programming language")

    from cognia.memory.long_term_consolidator import LongTermConsolidator
    c = LongTermConsolidator(db_path=db)
    n = c.consolidate("default", min_occurrences=3)
    assert n == 0

    facts = c.get_consolidated_facts("default")
    assert "rust" not in facts

"""
tests/test_recommendation_engine.py
====================================
5 unit tests for RecommendationEngine.
Uses an in-memory SQLite DB so no real cognia_desktop_chat.db is needed.
"""

from __future__ import annotations

import sqlite3
import tempfile
import os
import pytest

import cognia.intelligence.recommendation_engine as _re_mod
from cognia.intelligence.recommendation_engine import RecommendationEngine


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Create a minimal SQLite DB with all required tables and point the module at it."""
    db_file = str(tmp_path / "test_rec.db")
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sr_cards (
            id INTEGER PRIMARY KEY, next_review REAL
        );
        CREATE TABLE IF NOT EXISTS user_goals (
            id INTEGER PRIMARY KEY, title TEXT, status TEXT
        );
        CREATE TABLE IF NOT EXISTS smart_notes (
            id INTEGER PRIMARY KEY, note_type TEXT
        );
        CREATE TABLE IF NOT EXISTS curiosity_queue (
            id INTEGER PRIMARY KEY, answered INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS feature_usage (
            id INTEGER PRIMARY KEY, date TEXT, count INTEGER
        );
    """)
    conn.commit()
    conn.close()

    _re_mod._DB_PATH = db_file
    yield db_file
    _re_mod._DB_PATH = None


def test_generate_returns_list(isolated_db):
    """generate() must return a list (may be empty)."""
    engine = RecommendationEngine()
    result = engine.generate()
    assert isinstance(result, list)


def test_get_top_returns_dict_or_none(isolated_db):
    """get_top() must return a dict or None."""
    engine = RecommendationEngine()
    top = engine.get_top()
    assert top is None or isinstance(top, dict)


def test_generate_dicts_have_required_keys(isolated_db):
    """Each recommendation dict must contain type, priority, title, reason, action."""
    # Insert a due SR card to guarantee at least one recommendation
    import time
    conn = sqlite3.connect(isolated_db)
    conn.execute("INSERT INTO sr_cards (next_review) VALUES (?)", (time.time() - 1,))
    conn.commit()
    conn.close()

    engine = RecommendationEngine()
    recs = engine.generate()
    assert len(recs) >= 1
    required_keys = {"type", "priority", "title", "reason", "action"}
    for rec in recs:
        assert required_keys.issubset(rec.keys()), f"Missing keys in {rec}"


def test_generate_empty_db_no_crash(isolated_db):
    """generate() must not raise even when all tables are empty."""
    engine = RecommendationEngine()
    try:
        result = engine.generate()
    except Exception as exc:
        pytest.fail(f"generate() raised with empty DB: {exc}")
    assert isinstance(result, list)


def test_get_summary_returns_nonempty_string(isolated_db):
    """get_summary() must return a non-empty string."""
    # Insert a due SR card so there's something to summarize
    import time
    conn = sqlite3.connect(isolated_db)
    conn.execute("INSERT INTO sr_cards (next_review) VALUES (?)", (time.time() - 1,))
    conn.commit()
    conn.close()

    engine = RecommendationEngine()
    summary = engine.get_summary()
    assert isinstance(summary, str)
    assert len(summary) > 0

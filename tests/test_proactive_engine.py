"""
tests/test_proactive_engine.py
==============================
6 tests for ProactiveEngine: generate_suggestions + DB persistence.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from cognia.proactive.proactive_engine import ProactiveEngine
from storage.db_pool import close_pool


@pytest.fixture()
def engine(tmp_path):
    db = str(tmp_path / "test_proactive.db")
    eng = ProactiveEngine(db_path=db)
    yield eng
    close_pool(db)


# 1 — goal match produces goal_reminder suggestion
def test_generate_suggestions_goal_match(engine):
    suggestions = engine.generate_suggestions(
        "necesito aprender python para el trabajo",
        active_goals=["aprender python", "leer mas libros"],
    )
    assert len(suggestions) >= 1
    texts = [s["text"] for s in suggestions]
    assert any("aprender python" in t for t in texts)
    cats = [s["category"] for s in suggestions]
    assert "goal_reminder" in cats


# 2 — question word triggers web_search suggestion
def test_generate_suggestions_question_word(engine):
    suggestions = engine.generate_suggestions(
        "how do neural networks work",
        active_goals=[],
    )
    assert any(s["category"] == "web_search" for s in suggestions)
    assert any("buscar" in s["text"] for s in suggestions)


# 3 — empty text returns a list (possibly empty, never raises)
def test_generate_suggestions_empty_text(engine):
    result = engine.generate_suggestions("", active_goals=[])
    assert isinstance(result, list)


# 4 — queue_suggestion then get_pending returns the queued item
def test_queue_and_get_pending(engine):
    engine.queue_suggestion("Revisa tu objetivo de aprender Python", category="goal_reminder")
    pending = engine.get_pending(limit=5)
    assert len(pending) >= 1
    assert any("Python" in t for t in pending)


# 5 — get_pending marks items as shown (calling twice returns empty second time)
def test_get_pending_marks_shown(engine):
    engine.queue_suggestion("Primera sugerencia", category="general")
    first_call = engine.get_pending(limit=5)
    assert len(first_call) >= 1
    second_call = engine.get_pending(limit=5)
    assert len(second_call) == 0


# 6 — get_stats returns dict with required keys and correct counts
def test_get_stats_returns_required_keys(engine):
    engine.queue_suggestion("Sugerencia A")
    engine.queue_suggestion("Sugerencia B")
    engine.get_pending(limit=1)  # mark 1 shown
    stats = engine.get_stats()
    assert "total_generated" in stats
    assert "shown" in stats
    assert "pending" in stats
    assert stats["total_generated"] == 2
    assert stats["shown"] == 1
    assert stats["pending"] == 1

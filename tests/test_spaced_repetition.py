"""tests/test_spaced_repetition.py — SM-2 SpacedRepetitionEngine tests."""
from __future__ import annotations

import time
import pytest

from cognia.learning.spaced_repetition import SpacedRepetitionEngine


@pytest.fixture
def engine(tmp_path):
    db = str(tmp_path / "sr_test.db")
    return SpacedRepetitionEngine(db_path=db)


def test_add_card_returns_id(engine):
    """add_card must return a positive integer id."""
    card_id = engine.add_card("What is 2+2?", "4", topic="math")
    assert isinstance(card_id, int)
    assert card_id > 0


def test_new_card_is_due_immediately(engine):
    """A freshly added card should appear in get_due_cards."""
    engine.add_card("Capital of France?", "Paris", topic="geo")
    due = engine.get_due_cards(limit=10)
    assert len(due) >= 1
    fronts = [c["front"] for c in due]
    assert "Capital of France?" in fronts


def test_review_quality_ge3_increases_interval(engine):
    """Reviewing with quality >= 3 should increase interval beyond 1 day."""
    card_id = engine.add_card("Python list comprehension?", "[x for x in y]")
    updated = engine.review_card(card_id, quality=4)
    # After first successful review (rep 0->1): interval stays 1, but
    # after second (rep 1->2): interval becomes 6. Test rep 0->1 first,
    # then rep 1->2.
    assert updated["repetitions"] == 1
    assert updated["interval_days"] == 1.0

    updated2 = engine.review_card(card_id, quality=5)
    assert updated2["repetitions"] == 2
    assert updated2["interval_days"] == 6.0


def test_review_quality_lt3_resets_repetitions(engine):
    """Reviewing with quality < 3 must reset repetitions to 0."""
    card_id = engine.add_card("What is entropy?", "Measure of disorder")
    # First pass: succeed
    engine.review_card(card_id, quality=5)
    engine.review_card(card_id, quality=5)
    # Now fail
    updated = engine.review_card(card_id, quality=1)
    assert updated["repetitions"] == 0
    assert updated["interval_days"] == 1.0


def test_ease_factor_never_below_1_3(engine):
    """Ease factor must never drop below 1.3 no matter how many bad reviews."""
    card_id = engine.add_card("Hard concept", "Answer", topic="hard")
    # Repeatedly review with quality=3 (minimum passing) to stress-test ease floor
    for _ in range(10):
        result = engine.review_card(card_id, quality=3)
    assert result["ease_factor"] >= 1.3


def test_get_stats_returns_correct_keys(engine):
    """get_stats must return dict with total, due_today, mastered, topics."""
    engine.add_card("Q1", "A1", topic="science")
    engine.add_card("Q2", "A2", topic="math")
    stats = engine.get_stats()
    assert "total" in stats
    assert "due_today" in stats
    assert "mastered" in stats
    assert "topics" in stats
    assert stats["total"] == 2
    assert stats["due_today"] == 2  # both are newly added, due now
    assert isinstance(stats["topics"], list)
    assert set(stats["topics"]) == {"science", "math"}


def test_search_cards_finds_by_front_text(engine):
    """search_cards must find a card matching front text."""
    engine.add_card("What is recursion?", "A function calling itself", topic="cs")
    engine.add_card("What is iteration?", "A loop construct", topic="cs")
    results = engine.search_cards("recursion")
    assert len(results) == 1
    assert results[0]["front"] == "What is recursion?"

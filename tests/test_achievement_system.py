"""
tests/test_achievement_system.py
=================================
6 tests for AchievementSystem.
"""

import os
import sys
import tempfile

import pytest

# Ensure repo root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.gamification.achievement_system import AchievementSystem


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_achievements.db")


@pytest.fixture
def ach(db_path):
    return AchievementSystem(db_path=db_path)


def test_first_message_unlocked_on_first_event(ach):
    """Sending one message must unlock first_message."""
    unlocked = ach.check_and_unlock("user1", "message_sent", count=1)
    assert "Primera Conversacion" in unlocked


def test_ten_messages_not_unlocked_until_count_10(ach):
    """ten_messages should NOT unlock at count=9, but MUST unlock at count=10."""
    unlocked_9 = ach.check_and_unlock("user2", "message_sent", count=9)
    names_9 = unlocked_9
    # ten_messages requires count>=10
    assert "Conversador" not in names_9

    unlocked_10 = ach.check_and_unlock("user2", "message_sent", count=10)
    assert "Conversador" in unlocked_10


def test_duplicate_unlock_returns_empty(ach):
    """Unlocking the same achievement twice must return empty on the second call."""
    first = ach.check_and_unlock("user3", "note_saved", count=1)
    assert "Primer Apunte" in first

    second = ach.check_and_unlock("user3", "note_saved", count=1)
    assert second == []


def test_get_points_sums_correctly(ach):
    """get_points must sum points for all unlocked achievements."""
    # unlock first_message (10pts) and first_note (15pts)
    ach.check_and_unlock("user4", "message_sent", count=1)
    ach.check_and_unlock("user4", "note_saved", count=1)
    points = ach.get_points("user4")
    assert points == 25


def test_get_stats_returns_correct_keys(ach):
    """get_stats must return a dict with unlocked/total/points/latest keys."""
    ach.check_and_unlock("user5", "search_done", count=1)
    stats = ach.get_stats("user5")
    assert "unlocked" in stats
    assert "total" in stats
    assert "points" in stats
    assert "latest" in stats
    assert stats["unlocked"] == 1
    assert stats["total"] == 10  # catalog has 10 entries
    assert stats["points"] == 20  # first_search = 20pts
    assert stats["latest"] == "Curioso"


def test_get_all_with_status_shows_locked_and_unlocked(ach):
    """get_all_with_status must include both locked and unlocked entries."""
    ach.check_and_unlock("user6", "export_done", count=1)
    all_items = ach.get_all_with_status("user6")

    assert len(all_items) == 10  # full catalog

    unlocked_items = [i for i in all_items if i["unlocked"]]
    locked_items   = [i for i in all_items if not i["unlocked"]]

    assert len(unlocked_items) == 1
    assert len(locked_items) == 9
    assert unlocked_items[0]["id"] == "first_export"

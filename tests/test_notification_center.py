"""
tests/test_notification_center.py
===================================
Unit tests for cognia/notifications/notification_center.py
"""

import os
import tempfile
import pytest

from storage.db_pool import close_pool
from cognia.notifications.notification_center import NotificationCenter


@pytest.fixture
def nc(tmp_path):
    """Return a fresh NotificationCenter backed by a temp SQLite file."""
    db = str(tmp_path / "test_notif.db")
    center = NotificationCenter(db_path=db)
    yield center
    close_pool(db)


class TestCreate:
    def test_returns_dict_with_expected_fields(self, nc):
        n = nc.create("u1", "Hello", body="World", level="info", source="system")
        assert isinstance(n["id"], int)
        assert n["title"] == "Hello"
        assert n["body"] == "World"
        assert n["level"] == "info"
        assert n["read"] is False
        assert n["user_id"] == "u1"
        assert n["source"] == "system"

    def test_invalid_level_raises_value_error(self, nc):
        with pytest.raises(ValueError, match="Invalid level"):
            nc.create("u1", "Bad", level="critical")


class TestUnreadCount:
    def test_increments_after_create(self, nc):
        assert nc.get_unread_count("u1") == 0
        nc.create("u1", "First")
        assert nc.get_unread_count("u1") == 1
        nc.create("u1", "Second")
        assert nc.get_unread_count("u1") == 2

    def test_isolated_per_user(self, nc):
        nc.create("u1", "For u1")
        assert nc.get_unread_count("u2") == 0


class TestMarkRead:
    def test_decrements_unread_count(self, nc):
        n = nc.create("u1", "Test")
        assert nc.get_unread_count("u1") == 1
        ok = nc.mark_read(n["id"], "u1")
        assert ok is True
        assert nc.get_unread_count("u1") == 0

    def test_wrong_user_does_not_mark(self, nc):
        n = nc.create("u1", "Test")
        ok = nc.mark_read(n["id"], "u2")
        assert ok is False
        assert nc.get_unread_count("u1") == 1


class TestMarkAllRead:
    def test_returns_n_greater_than_zero(self, nc):
        nc.create("u1", "A")
        nc.create("u1", "B")
        n = nc.mark_all_read("u1")
        assert n == 2
        assert nc.get_unread_count("u1") == 0

    def test_second_call_returns_zero(self, nc):
        nc.create("u1", "A")
        nc.mark_all_read("u1")
        assert nc.mark_all_read("u1") == 0


class TestGoalNotification:
    def test_progress_100_creates_success_notification(self, nc):
        nc.create_goal_notification("u1", "Learn Python", 100)
        items = nc.get_unread("u1")
        assert len(items) == 1
        assert items[0]["level"] == "success"
        assert "completada" in items[0]["title"].lower()

    def test_progress_50_creates_info_notification(self, nc):
        nc.create_goal_notification("u1", "Learn Python", 50)
        items = nc.get_unread("u1")
        assert len(items) == 1
        assert items[0]["level"] == "info"

    def test_progress_below_50_creates_no_notification(self, nc):
        nc.create_goal_notification("u1", "Learn Python", 30)
        assert nc.get_unread_count("u1") == 0


class TestQualityAlert:
    def test_low_score_creates_warning(self, nc):
        nc.create_quality_alert("u1", 0.3)
        items = nc.get_unread("u1")
        assert len(items) == 1
        assert items[0]["level"] == "warning"
        assert items[0]["source"] == "quality"

    def test_good_score_creates_no_notification(self, nc):
        nc.create_quality_alert("u1", 0.7)
        assert nc.get_unread_count("u1") == 0

    def test_boundary_score_040_creates_no_notification(self, nc):
        nc.create_quality_alert("u1", 0.4)
        assert nc.get_unread_count("u1") == 0

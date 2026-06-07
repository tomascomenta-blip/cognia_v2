"""
tests/test_reminder_manager.py
================================
Tests for ReminderManager.
"""

import time
import tempfile
import os
import pytest

from cognia.reminders.reminder_manager import ReminderManager


@pytest.fixture
def rm(tmp_path):
    """ReminderManager using an isolated temp DB. Checker stopped after test."""
    db = str(tmp_path / "test_reminders.db")
    manager = ReminderManager(db_path=db)
    yield manager
    manager.stop()


# ── Basic CRUD ─────────────────────────────────────────────────────────

def test_create_returns_dict_with_id_and_pending_status(rm):
    r = rm.create("user1", "Test reminder", fire_at=time.time() + 3600)
    assert isinstance(r["id"], int)
    assert r["id"] > 0
    assert r["status"] == "pending"
    assert r["title"] == "Test reminder"
    assert r["user_id"] == "user1"


def test_create_relative_fire_at_is_approx_now_plus_seconds(rm):
    before = time.time()
    r = rm.create_relative("user1", "Relative reminder", minutes=60)
    after = time.time()
    assert before + 3600 - 5 <= r["fire_at"] <= after + 3600 + 5


def test_get_pending_includes_created_reminder(rm):
    rm.create("user2", "Pending one", fire_at=time.time() + 7200)
    pending = rm.get_pending("user2")
    assert len(pending) >= 1
    titles = [p["title"] for p in pending]
    assert "Pending one" in titles


def test_get_pending_excludes_other_users(rm):
    rm.create("user_a", "Only for A", fire_at=time.time() + 3600)
    pending = rm.get_pending("user_b")
    titles = [p["title"] for p in pending]
    assert "Only for A" not in titles


def test_cancel_changes_status_to_cancelled(rm):
    r = rm.create("user3", "To cancel", fire_at=time.time() + 3600)
    result = rm.cancel(r["id"], "user3")
    assert result is True
    # Must not appear in pending anymore
    pending = rm.get_pending("user3")
    ids = [p["id"] for p in pending]
    assert r["id"] not in ids


def test_cancel_wrong_user_returns_false(rm):
    r = rm.create("user4", "Mine", fire_at=time.time() + 3600)
    result = rm.cancel(r["id"], "wrong_user")
    assert result is False


# ── _check_and_fire ────────────────────────────────────────────────────

def test_check_and_fire_does_not_crash_on_empty_db(rm):
    # Should not raise even with empty table
    rm._check_and_fire()


def test_check_and_fire_fires_past_reminder(rm):
    # Create reminder with fire_at in the past
    r = rm.create("user5", "Past reminder", fire_at=time.time() - 1)

    fired_notifications = []

    class FakeNC:
        def create(self, **kwargs):
            fired_notifications.append(kwargs)

    rm.set_notification_center(FakeNC())
    rm._check_and_fire()

    # Reminder should now be fired
    pending = rm.get_pending("user5")
    ids = [p["id"] for p in pending]
    assert r["id"] not in ids

    # Notification was created
    assert len(fired_notifications) >= 1
    assert fired_notifications[0]["title"] == "Past reminder"


def test_check_and_fire_does_not_fire_future_reminder(rm):
    r = rm.create("user6", "Future reminder", fire_at=time.time() + 9999)
    rm._check_and_fire()
    pending = rm.get_pending("user6")
    ids = [p["id"] for p in pending]
    assert r["id"] in ids


def test_check_and_fire_does_not_double_fire(rm):
    fired_count = [0]

    class CountingNC:
        def create(self, **kwargs):
            fired_count[0] += 1

    rm.set_notification_center(CountingNC())
    r = rm.create("user7", "Once", fire_at=time.time() - 1)
    rm._check_and_fire()
    rm._check_and_fire()  # Second call should be a no-op for same reminder
    assert fired_count[0] == 1

"""
tests/test_usage_analytics.py
Tests for UsageAnalytics: record, upsert, top features, streak, stats, daily.
"""

import datetime
import os
import tempfile

import pytest

from cognia.analytics.usage_analytics import UsageAnalytics
from storage.db_pool import close_pool


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_analytics.db")
    ua = UsageAnalytics(db_path=db_path)
    yield ua
    close_pool(db_path)


# ── Tests ────────────────────────────────────────────────────────────────

def test_record_inserts_row(db):
    db.record("infer", user_id="u1")
    top = db.get_top_features(user_id="u1", days=1, limit=5)
    assert len(top) == 1
    assert top[0]["feature"] == "infer"
    assert top[0]["total"] >= 1


def test_record_same_feature_same_day_increments_count(db):
    db.record("infer", user_id="u2")
    db.record("infer", user_id="u2")
    db.record("infer", user_id="u2")
    top = db.get_top_features(user_id="u2", days=1, limit=5)
    # Should have exactly one row for today (not three rows)
    assert len(top) == 1
    # count was incremented: INSERT OR IGNORE gives 1, then 3 UPDATEs → total = 1+3 = 4
    assert top[0]["total"] == 4


def test_get_top_features_returns_sorted_list(db):
    db.record("goals", user_id="u3")
    db.record("goals", user_id="u3")
    db.record("infer", user_id="u3")
    top = db.get_top_features(user_id="u3", days=7, limit=10)
    assert len(top) >= 2
    # First entry should have the highest total
    assert top[0]["total"] >= top[1]["total"]
    features = [t["feature"] for t in top]
    assert "goals" in features
    assert "infer" in features


def test_get_streak_returns_1_for_single_day(db):
    db.record("infer", user_id="u4")
    streak = db.get_streak(user_id="u4")
    assert streak == 1


def test_get_stats_returns_all_required_keys(db):
    db.record("infer", user_id="u5")
    db.record("notes", user_id="u5")
    stats = db.get_stats(user_id="u5")
    assert "total_events" in stats
    assert "active_days" in stats
    assert "streak" in stats
    assert "top_feature" in stats
    assert "today_count" in stats
    assert stats["total_events"] >= 2
    assert stats["active_days"] >= 1
    assert stats["streak"] >= 1
    assert stats["top_feature"] is not None
    assert stats["today_count"] >= 2


def test_get_daily_activity_returns_list_of_dicts_with_day_key(db):
    db.record("infer", user_id="u6")
    db.record("learning", user_id="u6")
    activity = db.get_daily_activity(user_id="u6", days=7)
    assert isinstance(activity, list)
    assert len(activity) >= 1
    for entry in activity:
        assert "day" in entry
        assert "total" in entry

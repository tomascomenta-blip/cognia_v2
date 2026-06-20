"""
tests/test_progress_reporter.py
================================
Unit tests for ProgressReporter — all external dependencies mocked.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reporter(tmp_db: str = ":memory:"):
    from cognia.reports.progress_reporter import ProgressReporter
    return ProgressReporter(db_path=tmp_db)


def _mock_pool(rows=None):
    """Return a context-manager mock that yields a connection returning `rows`."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = rows
    conn.execute.return_value.fetchall.return_value = rows or []
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    pool = MagicMock()
    pool.get.return_value = cm
    return pool


# ---------------------------------------------------------------------------
# 1. generate_report() returns non-empty string
# ---------------------------------------------------------------------------

def test_generate_report_returns_string():
    reporter = _make_reporter()
    with patch("cognia.reports.progress_reporter.ProgressReporter._get_goals_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_conversation_stats", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_curiosity_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_summaries_section", return_value=""):
        result = reporter.generate_report(user_id="local", period_days=7)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 2. Report contains at least one Markdown header ("# ")
# ---------------------------------------------------------------------------

def test_generate_report_has_markdown_headers():
    reporter = _make_reporter()
    with patch("cognia.reports.progress_reporter.ProgressReporter._get_goals_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_conversation_stats", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_curiosity_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_summaries_section", return_value=""):
        result = reporter.generate_report()
    assert "# " in result


# ---------------------------------------------------------------------------
# 3. generate_json_stats() returns dict with all expected keys
# ---------------------------------------------------------------------------

def test_generate_json_stats_keys():
    """generate_json_stats returns all required keys even when dependencies fail."""
    reporter = _make_reporter()
    # All sub-imports will fail gracefully because db_path is ":memory:" with no tables;
    # the method catches exceptions and defaults to zero — that is fine for this test.
    result = reporter.generate_json_stats(user_id="local", period_days=7)
    expected_keys = {
        "period_days", "goals_active", "goals_completed",
        "messages_total", "sessions_total", "insights_count",
    }
    assert expected_keys.issubset(result.keys())
    assert result["period_days"] == 7


# ---------------------------------------------------------------------------
# 4. _get_goals_section() with mock GoalTracker returns "## " header
# ---------------------------------------------------------------------------

def test_get_goals_section_returns_markdown():
    reporter = _make_reporter()
    since = datetime.now(timezone.utc) - timedelta(days=7)

    mock_tracker = MagicMock()
    mock_tracker.get_goals.side_effect = lambda uid, status=None: (
        [{"id": 1, "title": "Learn Python", "description": "", "progress_pct": 42,
          "completed_at": None}]
        if status == "active"
        else []
    )

    # GoalTracker is imported inside the method, so patch at the source module
    with patch("cognia.goals.goal_tracker.GoalTracker", return_value=mock_tracker), \
         patch("cognia.reports.progress_reporter.GoalTracker", mock_tracker, create=True):
        section = reporter._get_goals_section("local", since)

    assert "## " in section
    assert "Learn Python" in section


# ---------------------------------------------------------------------------
# 5. generate_report() with period_days=0 does not raise
# ---------------------------------------------------------------------------

def test_generate_report_zero_days_no_exception():
    reporter = _make_reporter()
    with patch("cognia.reports.progress_reporter.ProgressReporter._get_goals_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_conversation_stats", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_curiosity_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_summaries_section", return_value=""):
        result = reporter.generate_report(period_days=0)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 6. Report contains today's date
# ---------------------------------------------------------------------------

def test_generate_report_contains_today():
    reporter = _make_reporter()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with patch("cognia.reports.progress_reporter.ProgressReporter._get_goals_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_conversation_stats", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_curiosity_section", return_value=""), \
         patch("cognia.reports.progress_reporter.ProgressReporter._get_summaries_section", return_value=""):
        result = reporter.generate_report()
    assert today_str in result

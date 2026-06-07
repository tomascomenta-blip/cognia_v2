"""
tests/test_quality_analyzer.py -- Tests for QualityAnalyzer.
Mocks storage.db_pool so no real DB is needed.
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build fake rows
# ---------------------------------------------------------------------------

def _make_rows(overalls, base_ts=None):
    """Return list of (ts, overall, completeness, coherence, relevance) tuples."""
    if base_ts is None:
        base_ts = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = []
    for i, overall in enumerate(overalls):
        ts = (base_ts + timedelta(minutes=i * 5)).isoformat()
        rows.append((ts, overall, overall, overall, overall))
    return rows


# ---------------------------------------------------------------------------
# _detect_trend unit tests (no DB needed)
# ---------------------------------------------------------------------------

def _get_analyzer():
    from cognia.quality.quality_analyzer import QualityAnalyzer
    return QualityAnalyzer(db_path=":memory:")


def test_detect_trend_empty():
    qa = _get_analyzer()
    assert qa._detect_trend([]) == "stable"


def test_detect_trend_too_few():
    qa = _get_analyzer()
    assert qa._detect_trend([0.5, 0.6, 0.7]) == "stable"


def test_detect_trend_improving():
    qa = _get_analyzer()
    assert qa._detect_trend([0.3, 0.3, 0.8, 0.9]) == "improving"


def test_detect_trend_declining():
    qa = _get_analyzer()
    assert qa._detect_trend([0.9, 0.9, 0.3, 0.3]) == "declining"


def test_detect_trend_stable():
    qa = _get_analyzer()
    assert qa._detect_trend([0.5, 0.5, 0.5, 0.5]) == "stable"


# ---------------------------------------------------------------------------
# get_trends tests (mock DB)
# ---------------------------------------------------------------------------

def _mock_pool_ctx(rows):
    """Return a patched get_pool that yields a conn returning given rows."""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    pool = MagicMock()
    pool.get.return_value.__enter__ = MagicMock(return_value=conn)
    pool.get.return_value.__exit__ = MagicMock(return_value=False)
    return pool


def test_get_trends_returns_required_keys():
    rows = _make_rows([0.5, 0.6, 0.7, 0.8])
    pool = _mock_pool_ctx(rows)
    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_trends(period_days=7, bucket_hours=6)

    assert "buckets" in result
    assert "trend" in result
    assert "total_scored" in result
    assert "overall_avg" in result
    assert "period_days" in result
    assert result["total_scored"] == 4


def test_get_trends_empty_db():
    pool = _mock_pool_ctx([])
    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_trends()

    assert result["total_scored"] == 0
    assert result["buckets"] == []
    assert result["trend"] == "stable"


def test_get_trends_trend_improving():
    rows = _make_rows([0.2, 0.2, 0.8, 0.9])
    pool = _mock_pool_ctx(rows)
    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_trends()

    assert result["trend"] == "improving"


def test_get_trends_buckets_are_list():
    rows = _make_rows([0.5, 0.6])
    pool = _mock_pool_ctx(rows)
    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_trends()

    assert isinstance(result["buckets"], list)


# ---------------------------------------------------------------------------
# get_summary tests (mock DB)
# ---------------------------------------------------------------------------

def test_get_summary_returns_required_keys():
    rows = _make_rows([0.5, 0.6, 0.7])
    pool = _mock_pool_ctx(rows)
    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_summary()

    for key in ("avg_overall", "avg_completeness", "avg_coherence", "avg_relevance",
                "total_scored", "best_hour", "worst_hour"):
        assert key in result, f"missing key: {key}"


def test_get_summary_empty_db():
    pool = _mock_pool_ctx([])
    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_summary()

    assert result["total_scored"] == 0
    assert result["avg_overall"] == 0.0


# ---------------------------------------------------------------------------
# get_low_quality_prompts tests (mock DB)
# ---------------------------------------------------------------------------

def test_get_low_quality_prompts_returns_list():
    # Simulate rows: (prompt_hash, overall, ts)
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        ("abc123", 0.2, "2026-06-01T10:00:00+00:00"),
        ("def456", 0.3, "2026-06-01T11:00:00+00:00"),
    ]
    pool = MagicMock()
    pool.get.return_value.__enter__ = MagicMock(return_value=conn)
    pool.get.return_value.__exit__ = MagicMock(return_value=False)

    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_low_quality_prompts(threshold=0.4, limit=10)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["prompt_hash"] == "abc123"
    assert "overall" in result[0]
    assert "ts" in result[0]


def test_get_low_quality_prompts_empty():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    pool = MagicMock()
    pool.get.return_value.__enter__ = MagicMock(return_value=conn)
    pool.get.return_value.__exit__ = MagicMock(return_value=False)

    with patch("cognia.quality.quality_analyzer.get_pool", return_value=pool):
        from cognia.quality.quality_analyzer import QualityAnalyzer
        qa = QualityAnalyzer(db_path=":memory:")
        result = qa.get_low_quality_prompts()

    assert result == []

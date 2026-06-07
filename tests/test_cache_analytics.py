"""
tests/test_cache_analytics.py
Tests for cognia/cache/cache_analytics.py
"""
import threading
import pytest
from cognia.cache.cache_analytics import CacheAnalytics


def _make_analytics():
    return CacheAnalytics(cache_instance=None)


def test_get_analytics_returns_expected_keys():
    a = _make_analytics()
    result = a.get_analytics()
    expected = {"total_hits", "total_misses", "hit_rate", "top_queries",
                "hourly_stats", "hits_last_hour", "cache_size"}
    assert expected.issubset(set(result.keys()))


def test_hit_rate_calculation():
    a = _make_analytics()
    a.record_hit("python tutorial")
    a.record_miss("x")
    result = a.get_analytics()
    assert result["total_hits"] == 1
    assert result["total_misses"] == 1
    assert result["hit_rate"] == 0.5


def test_top_queries_includes_recorded_hit():
    a = _make_analytics()
    a.record_hit("python tutorial advanced")
    result = a.get_analytics()
    queries = [q["query"] for q in result["top_queries"]]
    # prefix is first 30 chars, lowercased
    assert any("python tutorial" in q for q in queries)


def test_top_queries_max_10():
    a = _make_analytics()
    for i in range(15):
        a.record_hit(f"unique query number {i:03d} extra padding to ensure prefix differs")
    result = a.get_analytics()
    assert len(result["top_queries"]) <= 10


def test_hourly_stats_has_24_entries():
    a = _make_analytics()
    result = a.get_analytics()
    assert len(result["hourly_stats"]) == 24


def test_hourly_stats_hours_cover_0_to_23():
    a = _make_analytics()
    result = a.get_analytics()
    hours = [entry["hour"] for entry in result["hourly_stats"]]
    assert hours == list(range(24))


def test_reset_zeroes_all_counters():
    a = _make_analytics()
    a.record_hit("query one")
    a.record_hit("query two")
    a.record_miss("miss one")
    a.reset()
    result = a.get_analytics()
    assert result["total_hits"] == 0
    assert result["total_misses"] == 0
    assert result["hit_rate"] == 0.0
    assert result["top_queries"] == []
    assert result["hits_last_hour"] == 0


def test_hits_last_hour_counts_recent():
    a = _make_analytics()
    for _ in range(5):
        a.record_hit("recent query")
    result = a.get_analytics()
    assert result["hits_last_hour"] == 5


def test_thread_safety_no_crash():
    a = _make_analytics()
    errors = []

    def worker():
        try:
            for _ in range(10):
                a.record_hit("concurrent query")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread safety errors: {errors}"
    result = a.get_analytics()
    assert result["total_hits"] == 100


def test_cache_size_with_no_cache_instance():
    a = _make_analytics()
    result = a.get_analytics()
    assert result["cache_size"] == 0


def test_hit_rate_zero_with_no_records():
    a = _make_analytics()
    result = a.get_analytics()
    assert result["hit_rate"] == 0.0
    assert result["total_hits"] == 0
    assert result["total_misses"] == 0

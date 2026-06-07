"""Tests for cognia.monitoring.metrics_collector.MetricsCollector."""
import pytest
from cognia.monitoring.metrics_collector import MetricsCollector


def test_get_stats_empty_has_expected_keys():
    mc = MetricsCollector()
    stats = mc.get_stats()
    expected_keys = {
        "uptime_s", "total_requests", "errors",
        "avg_latency_ms", "p95_latency_ms", "avg_tokens",
        "requests_last_100", "error_rate",
    }
    assert expected_keys.issubset(stats.keys())


def test_record_request_increments_total():
    mc = MetricsCollector()
    assert mc.get_stats()["total_requests"] == 0
    mc.record_request(50.0)
    assert mc.get_stats()["total_requests"] == 1
    mc.record_request(30.0)
    assert mc.get_stats()["total_requests"] == 2


def test_avg_latency_correct_after_three_records():
    mc = MetricsCollector()
    mc.record_request(100.0)
    mc.record_request(200.0)
    mc.record_request(300.0)
    stats = mc.get_stats()
    assert stats["avg_latency_ms"] == 200.0


def test_error_rate_correct():
    mc = MetricsCollector()
    mc.record_request(10.0, error=False)
    mc.record_request(20.0, error=False)
    mc.record_request(30.0, error=False)
    mc.record_request(40.0, error=True)
    stats = mc.get_stats()
    assert stats["errors"] == 1
    assert stats["error_rate"] == pytest.approx(0.25, abs=0.001)


def test_p95_latency_zero_below_20_records():
    mc = MetricsCollector()
    for i in range(19):
        mc.record_request(float(i * 10))
    stats = mc.get_stats()
    assert stats["p95_latency_ms"] == 0

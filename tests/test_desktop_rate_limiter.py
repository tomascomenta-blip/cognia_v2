"""
tests/test_desktop_rate_limiter.py
====================================
Unit tests for cognia.auth.rate_limiter.DesktopRateLimiter.
"""
import threading
import time

import pytest

from cognia.auth.rate_limiter import DesktopRateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exhaust(rl: DesktopRateLimiter, key: str, limit: int) -> None:
    """Fire exactly `limit` allowed requests for key."""
    for _ in range(limit):
        allowed, _ = rl.check(key, limit=limit)
        assert allowed, "Expected allowed=True while exhausting quota"


# ---------------------------------------------------------------------------
# Basic allow / deny behaviour
# ---------------------------------------------------------------------------

def test_first_request_allowed():
    rl = DesktopRateLimiter()
    allowed, retry = rl.check("user_a")
    assert allowed is True
    assert retry == 0.0


def test_local_key_limit_5_ok_6th_denied():
    rl = DesktopRateLimiter()
    key = "local"
    limit = 5
    for i in range(limit):
        allowed, retry = rl.check(key, limit=limit)
        assert allowed is True, f"Request {i+1} should be allowed"
        assert retry == 0.0

    allowed, retry = rl.check(key, limit=limit)
    assert allowed is False
    assert retry > 0.0


def test_retry_after_positive_when_blocked():
    rl = DesktopRateLimiter()
    _exhaust(rl, "u1", 3)
    allowed, retry = rl.check("u1", limit=3)
    assert not allowed
    assert retry > 0.0
    assert retry <= 60.0


def test_different_keys_independent():
    rl = DesktopRateLimiter()
    _exhaust(rl, "alice", 3)
    # "bob" should still be fine
    allowed, _ = rl.check("bob", limit=3)
    assert allowed is True


# ---------------------------------------------------------------------------
# set_limit / custom overrides
# ---------------------------------------------------------------------------

def test_set_limit_override():
    rl = DesktopRateLimiter()
    rl.set_limit("premium_user", 10)
    for _ in range(10):
        allowed, _ = rl.check("premium_user")
        assert allowed
    # 11th should be blocked
    allowed, retry = rl.check("premium_user")
    assert not allowed
    assert retry > 0.0


def test_set_limit_lower_than_default():
    rl = DesktopRateLimiter()
    rl.set_limit("restricted", 2)
    rl.check("restricted")
    rl.check("restricted")
    allowed, _ = rl.check("restricted")
    assert not allowed


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

def test_reset_clears_counter():
    rl = DesktopRateLimiter()
    _exhaust(rl, "u2", 3)
    # confirm blocked
    allowed, _ = rl.check("u2", limit=3)
    assert not allowed

    rl.reset("u2")
    # after reset, should be allowed again
    allowed, _ = rl.check("u2", limit=3)
    assert allowed


def test_reset_unknown_key_no_error():
    rl = DesktopRateLimiter()
    rl.reset("nonexistent_key")  # must not raise


# ---------------------------------------------------------------------------
# get_stats()
# ---------------------------------------------------------------------------

def test_get_stats_returns_expected_keys():
    rl = DesktopRateLimiter()
    rl.check("stats_user")
    stats = rl.get_stats("stats_user")
    assert "key" in stats
    assert "requests_in_window" in stats
    assert "limit" in stats
    assert "window_s" in stats


def test_get_stats_requests_count():
    rl = DesktopRateLimiter()
    for _ in range(4):
        rl.check("count_user")
    stats = rl.get_stats("count_user")
    assert stats["requests_in_window"] == 4


def test_get_stats_local_default_limit():
    rl = DesktopRateLimiter()
    stats = rl.get_stats("local")
    assert stats["limit"] == 100


def test_get_stats_authed_default_limit():
    rl = DesktopRateLimiter()
    stats = rl.get_stats("some_user_id")
    assert stats["limit"] == 200


def test_get_stats_custom_limit_reflected():
    rl = DesktopRateLimiter()
    rl.set_limit("vip", 500)
    stats = rl.get_stats("vip")
    assert stats["limit"] == 500


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

def test_thread_safety_no_crash():
    """10 threads hammering check() simultaneously must not raise."""
    rl = DesktopRateLimiter()
    errors = []

    def worker():
        try:
            for _ in range(20):
                rl.check("shared_key", limit=1000)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety errors: {errors}"


def test_thread_safety_count_never_exceeds_limit():
    """Concurrent requests must not exceed the configured limit."""
    limit = 50
    rl = DesktopRateLimiter()
    allowed_count = 0
    lock = threading.Lock()

    def worker():
        nonlocal allowed_count
        for _ in range(10):
            ok, _ = rl.check("race_key", limit=limit)
            if ok:
                with lock:
                    allowed_count += 1

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert allowed_count <= limit, (
        f"allowed_count={allowed_count} exceeded limit={limit}"
    )

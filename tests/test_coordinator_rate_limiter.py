"""
tests/test_coordinator_rate_limiter.py
=======================================
Unit tests for coordinator.rate_limiter.SlidingWindowLimiter.
Pure in-memory, no SQLite, no network. Uses small limits to keep tests fast.
"""
import threading

import pytest

from coordinator.rate_limiter import SlidingWindowLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exhaust(sl: SlidingWindowLimiter, key: str, limit: int) -> None:
    """Fire exactly `limit` allowed requests for key."""
    for i in range(limit):
        allowed, retry = sl.check(key, limit)
        assert allowed, f"Request {i + 1} should be allowed while exhausting quota"
        assert retry == 0.0


# ---------------------------------------------------------------------------
# Basic allow / deny behaviour
# ---------------------------------------------------------------------------

def test_first_request_allowed():
    sl = SlidingWindowLimiter()
    allowed, retry = sl.check("node_a", limit=10)
    assert allowed is True
    assert retry == 0.0


def test_requests_up_to_limit_are_allowed():
    sl = SlidingWindowLimiter()
    limit = 5
    for i in range(limit):
        allowed, retry = sl.check("node_b", limit=limit)
        assert allowed is True, f"Request {i + 1} should be allowed"
        assert retry == 0.0


def test_limit_plus_one_is_denied():
    sl = SlidingWindowLimiter()
    limit = 4
    _exhaust(sl, "node_c", limit)
    allowed, retry = sl.check("node_c", limit=limit)
    assert allowed is False
    assert retry > 0.0


def test_retry_after_positive_when_blocked():
    sl = SlidingWindowLimiter()
    limit = 3
    _exhaust(sl, "node_d", limit)
    allowed, retry = sl.check("node_d", limit=limit)
    assert not allowed
    assert 0.0 < retry <= 60.0


def test_retry_after_zero_when_allowed():
    sl = SlidingWindowLimiter()
    allowed, retry = sl.check("node_e", limit=10)
    assert allowed
    assert retry == 0.0


def test_different_keys_are_independent():
    sl = SlidingWindowLimiter()
    limit = 3
    _exhaust(sl, "alice_node", limit)
    # alice exhausted; bob should still be fine
    allowed, retry = sl.check("bob_node", limit=limit)
    assert allowed is True
    assert retry == 0.0


def test_exact_boundary_window_full():
    """After exactly `limit` requests the window is full; next is denied."""
    sl = SlidingWindowLimiter()
    limit = 6
    for _ in range(limit):
        allowed, _ = sl.check("boundary_node", limit=limit)
        assert allowed
    # window now exactly full
    allowed, retry = sl.check("boundary_node", limit=limit)
    assert allowed is False
    assert retry > 0.0


# ---------------------------------------------------------------------------
# evict_stale()
# ---------------------------------------------------------------------------

def test_evict_stale_removes_empty_key():
    """A key with an empty deque (no recent requests) is treated as stale."""
    sl = SlidingWindowLimiter()
    # Manually inject an empty deque to simulate a key that aged out
    from collections import deque as _deque
    sl._windows["ghost_node"] = _deque()
    evicted = sl.evict_stale(max_idle_s=3600.0)
    assert evicted >= 1
    assert "ghost_node" not in sl._windows


def test_evict_stale_keeps_active_key():
    """A key with a very recent request must NOT be evicted."""
    sl = SlidingWindowLimiter()
    sl.check("active_node", limit=100)
    # Use a tiny max_idle_s so old entries would be evicted — but this one is fresh
    evicted = sl.evict_stale(max_idle_s=3600.0)
    # active_node had a request just now, so it should not be evicted
    assert "active_node" in sl._windows


def test_evict_stale_returns_count():
    """evict_stale() returns the number of keys removed."""
    sl = SlidingWindowLimiter()
    from collections import deque as _deque
    sl._windows["stale1"] = _deque()
    sl._windows["stale2"] = _deque()
    count = sl.evict_stale(max_idle_s=3600.0)
    assert count == 2


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

def test_thread_safety_no_crash():
    """Many threads hammering check() simultaneously must not raise."""
    sl = SlidingWindowLimiter()
    errors = []

    def worker():
        try:
            for _ in range(30):
                sl.check("shared_key", limit=1000)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety errors: {errors}"


def test_thread_safety_count_never_exceeds_limit():
    """Concurrent requests must not allow more than `limit` through."""
    limit = 50
    sl = SlidingWindowLimiter()
    allowed_count = 0
    count_lock = threading.Lock()

    def worker():
        nonlocal allowed_count
        for _ in range(10):
            ok, _ = sl.check("race_key", limit=limit)
            if ok:
                with count_lock:
                    allowed_count += 1

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert allowed_count <= limit, (
        f"allowed_count={allowed_count} exceeded limit={limit}"
    )

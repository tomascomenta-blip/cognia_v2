"""
coordinator/rate_limiter.py
===========================
Sliding-window per-key rate limiter for contributor tier enforcement.

Window: 60 seconds (matching RPM semantics in TIERS).
No external dependencies — threading.Lock + collections.deque.
"""
import threading
import time
from collections import deque
from typing import Tuple


class SlidingWindowLimiter:
    """
    Thread-safe sliding-window rate limiter keyed by node_id.

    Each key maintains a deque of request timestamps in the last 60s.
    check() is O(k) where k = requests in window (bounded by limit).
    """

    _WINDOW_S = 60.0

    def __init__(self) -> None:
        self._windows: dict = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> Tuple[bool, float]:
        """
        Record a request attempt for key.
        Returns (allowed, retry_after_seconds). retry_after is 0.0 when allowed.
        """
        now    = time.monotonic()
        cutoff = now - self._WINDOW_S
        with self._lock:
            if key not in self._windows:
                self._windows[key] = deque()
            window = self._windows[key]
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                retry_after = self._WINDOW_S - (now - window[0])
                return False, round(max(retry_after, 0.1), 1)
            window.append(now)
            return True, 0.0

    def evict_stale(self, max_idle_s: float = 3600.0) -> int:
        """Remove keys with no requests in the last max_idle_s seconds."""
        now    = time.monotonic()
        cutoff = now - max_idle_s
        with self._lock:
            stale = [k for k, w in self._windows.items() if not w or w[-1] < cutoff]
            for k in stale:
                del self._windows[k]
        return len(stale)

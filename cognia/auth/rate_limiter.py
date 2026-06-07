"""
cognia/auth/rate_limiter.py
============================
Sliding-window per-key rate limiter for the Desktop backend (:8765).

Separate from coordinator/rate_limiter.py to avoid circular imports and
because the desktop has different tier semantics:
  - "local" (no API key header): 100 req/min
  - authenticated key: 200 req/min (configurable per key via set_limit)
  - custom override always wins over tier defaults

Uses time.monotonic() for monotonicity safety (no wall-clock jumps).
"""
import time
import threading
from collections import defaultdict, deque

_LOCAL_KEY = "local"
_DEFAULT_AUTHED_LIMIT = 200
_DEFAULT_LOCAL_LIMIT = 100


class DesktopRateLimiter:
    """
    Thread-safe sliding-window rate limiter keyed by user_id.

    check(key, limit=None) -> (allowed: bool, retry_after_s: float)
    Callers pass the user_id resolved by the auth middleware ("local" or
    an actual user_id string).
    """

    def __init__(self, window_s: int = 60) -> None:
        self._window_s = window_s
        self._requests: dict = defaultdict(deque)  # {key: deque of monotonic timestamps}
        self._custom_limits: dict = {}              # {key: int} per-key overrides
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, key: str, limit: int = None) -> tuple:
        """
        Record a request attempt for key and decide whether to allow it.

        Returns (allowed, retry_after_s).  retry_after_s is 0.0 when allowed.
        limit overrides tier defaults when provided explicitly.
        """
        if limit is None:
            limit = self._custom_limits.get(
                key,
                _DEFAULT_LOCAL_LIMIT if key == _LOCAL_KEY else _DEFAULT_AUTHED_LIMIT,
            )

        # limit=0 means unlimited (enterprise tier)
        if limit == 0:
            return True, 0.0

        now = time.monotonic()
        cutoff = now - self._window_s

        with self._lock:
            q = self._requests[key]
            # Purge timestamps outside the sliding window
            while q and q[0] <= cutoff:
                q.popleft()

            if len(q) >= limit:
                retry_after = self._window_s - (now - q[0])
                return False, round(max(retry_after, 0.1), 1)

            q.append(now)
            return True, 0.0

    def set_limit(self, key: str, limit: int) -> None:
        """Configure a per-key custom limit (overrides tier defaults)."""
        with self._lock:
            self._custom_limits[key] = limit

    def get_stats(self, key: str) -> dict:
        """Return current window stats for key."""
        now = time.monotonic()
        cutoff = now - self._window_s
        with self._lock:
            q = self._requests[key]
            count = sum(1 for ts in q if ts > cutoff)
            limit = self._custom_limits.get(
                key,
                _DEFAULT_LOCAL_LIMIT if key == _LOCAL_KEY else _DEFAULT_AUTHED_LIMIT,
            )
        return {
            "key": key,
            "requests_in_window": count,
            "limit": limit,
            "window_s": self._window_s,
        }

    def reset(self, key: str) -> None:
        """Clear all recorded requests for key (useful in tests and admin ops)."""
        with self._lock:
            if key in self._requests:
                self._requests[key].clear()

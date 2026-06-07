import time, threading
from collections import deque


class MetricsCollector:
    def __init__(self, window_size: int = 100):
        self._lock = threading.Lock()
        self._response_times: deque = deque(maxlen=window_size)  # ms
        self._token_counts: deque = deque(maxlen=window_size)
        self._errors: int = 0
        self._total_requests: int = 0
        self._start_time: float = time.time()

    def record_request(self, latency_ms: float, token_count: int = 0, error: bool = False):
        with self._lock:
            self._total_requests += 1
            self._response_times.append(latency_ms)
            if token_count > 0:
                self._token_counts.append(token_count)
            if error:
                self._errors += 1

    def get_stats(self) -> dict:
        with self._lock:
            times = list(self._response_times)
            tokens = list(self._token_counts)
            uptime = int(time.time() - self._start_time)
            return {
                "uptime_s": uptime,
                "total_requests": self._total_requests,
                "errors": self._errors,
                "avg_latency_ms": round(sum(times) / len(times), 1) if times else 0,
                "p95_latency_ms": round(sorted(times)[int(len(times) * 0.95)], 1) if len(times) >= 20 else 0,
                "avg_tokens": round(sum(tokens) / len(tokens), 1) if tokens else 0,
                "requests_last_100": len(times),
                "error_rate": round(self._errors / max(self._total_requests, 1), 3),
            }

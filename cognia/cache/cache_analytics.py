import time
import threading
from collections import Counter, defaultdict, deque


class CacheAnalytics:
    """
    Analytics avanzados para SemanticCache.
    Wraps un SemanticCache existente y anade tracking adicional.
    Thread-safe.
    """

    def __init__(self, cache_instance=None):
        self._cache = cache_instance
        self._lock = threading.Lock()
        self._hit_timestamps: deque = deque(maxlen=1000)   # timestamps de hits
        self._miss_timestamps: deque = deque(maxlen=1000)  # timestamps de misses
        self._query_hits: Counter = Counter()              # query_prefix -> hit_count
        self._hourly_hits: defaultdict = defaultdict(int)  # hour (0-23) -> hits
        self._hourly_misses: defaultdict = defaultdict(int)

    def record_hit(self, query: str) -> None:
        now = time.time()
        hour = int(time.strftime("%H", time.localtime(now)))
        prefix = query[:30].lower().strip()
        with self._lock:
            self._hit_timestamps.append(now)
            self._query_hits[prefix] += 1
            self._hourly_hits[hour] += 1

    def record_miss(self, query: str) -> None:
        now = time.time()
        hour = int(time.strftime("%H", time.localtime(now)))
        with self._lock:
            self._miss_timestamps.append(now)
            self._hourly_misses[hour] += 1

    def get_analytics(self) -> dict:
        """
        Retorna:
        {
          "total_hits": int,
          "total_misses": int,
          "hit_rate": float,          # 0-1
          "top_queries": [{"query": str, "hits": int}],  # top 10
          "hourly_stats": [{"hour": int, "hits": int, "misses": int}],  # 0-23
          "hits_last_hour": int,
          "cache_size": int,          # del cache real si disponible
        }
        """
        now = time.time()
        one_hour_ago = now - 3600

        with self._lock:
            total_hits = sum(self._hourly_hits.values())
            total_misses = sum(self._hourly_misses.values())
            total = total_hits + total_misses

            hit_rate = total_hits / total if total > 0 else 0.0

            top_queries = [
                {"query": q, "hits": c}
                for q, c in self._query_hits.most_common(10)
            ]

            hourly_stats = [
                {"hour": h, "hits": self._hourly_hits.get(h, 0),
                 "misses": self._hourly_misses.get(h, 0)}
                for h in range(24)
            ]

            hits_last_hour = sum(1 for ts in self._hit_timestamps if ts > one_hour_ago)

            cache_size = 0
            if self._cache and hasattr(self._cache, "_entries"):
                try:
                    cache_size = len(self._cache._entries)
                except Exception:
                    pass

        return {
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_rate": round(hit_rate, 3),
            "top_queries": top_queries,
            "hourly_stats": hourly_stats,
            "hits_last_hour": hits_last_hour,
            "cache_size": cache_size,
        }

    def reset(self) -> None:
        with self._lock:
            self._hit_timestamps.clear()
            self._miss_timestamps.clear()
            self._query_hits.clear()
            self._hourly_hits.clear()
            self._hourly_misses.clear()

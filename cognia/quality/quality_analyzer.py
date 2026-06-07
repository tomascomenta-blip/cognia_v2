"""
quality_analyzer.py -- Statistical analysis of Cognia response quality trends.

Reads from the response_quality table populated by ResponseScorer.
No LLM calls -- purely statistical.
"""

from datetime import datetime, timedelta, timezone
from typing import List

from storage.db_pool import get_pool

_DB_PATH = "cognia_memory.db"


class QualityAnalyzer:
    """
    Analyzes quality trends of Cognia responses over time.
    Reads from the response_quality table.
    """

    def __init__(self, db_path: str = _DB_PATH):
        self._db = db_path

    def get_trends(self, period_days: int = 7, bucket_hours: int = 6) -> dict:
        """
        Returns trends in windows of bucket_hours hours over period_days days.

        {
          "period_days": N,
          "buckets": [{"ts": ISO, "avg_overall": float, "avg_completeness": float,
                       "avg_coherence": float, "avg_relevance": float, "count": int}],
          "overall_avg": float,
          "trend": "improving" | "declining" | "stable",
          "total_scored": int
        }
        """
        since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()

        try:
            with get_pool(self._db).get() as conn:
                rows = conn.execute(
                    """
                    SELECT ts, overall, completeness, coherence, relevance
                    FROM response_quality
                    WHERE ts >= ?
                    ORDER BY ts ASC
                    """,
                    (since,),
                ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return {
                "period_days": period_days,
                "buckets": [],
                "overall_avg": 0.0,
                "trend": "stable",
                "total_scored": 0,
            }

        # Group into buckets of bucket_hours hours
        bucket_secs = bucket_hours * 3600
        buckets: dict = {}
        for ts_str, overall, completeness, coherence, relevance in rows:
            try:
                # Parse ISO timestamp; handle both Z and +00:00 suffixes
                ts_clean = ts_str.replace("Z", "+00:00")
                ts_dt = datetime.fromisoformat(ts_clean)
                epoch = ts_dt.timestamp()
            except Exception:
                continue
            bucket_key = int(epoch // bucket_secs) * bucket_secs
            if bucket_key not in buckets:
                buckets[bucket_key] = {
                    "overall": [],
                    "completeness": [],
                    "coherence": [],
                    "relevance": [],
                }
            buckets[bucket_key]["overall"].append(overall)
            buckets[bucket_key]["completeness"].append(completeness)
            buckets[bucket_key]["coherence"].append(coherence)
            buckets[bucket_key]["relevance"].append(relevance)

        bucket_list = []
        for key in sorted(buckets):
            b = buckets[key]
            cnt = len(b["overall"])
            bucket_list.append({
                "ts": datetime.fromtimestamp(key, tz=timezone.utc).isoformat(),
                "avg_overall": round(sum(b["overall"]) / cnt, 4),
                "avg_completeness": round(sum(b["completeness"]) / cnt, 4),
                "avg_coherence": round(sum(b["coherence"]) / cnt, 4),
                "avg_relevance": round(sum(b["relevance"]) / cnt, 4),
                "count": cnt,
            })

        all_overall = [r[1] for r in rows]
        overall_avg = round(sum(all_overall) / len(all_overall), 4) if all_overall else 0.0
        trend = self._detect_trend(all_overall)

        return {
            "period_days": period_days,
            "buckets": bucket_list,
            "overall_avg": overall_avg,
            "trend": trend,
            "total_scored": len(rows),
        }

    def get_summary(self, period_days: int = 7) -> dict:
        """
        {
          "avg_overall": float, "avg_completeness": float, "avg_coherence": float,
          "avg_relevance": float, "total_scored": int, "best_hour": int, "worst_hour": int
        }
        """
        since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()

        try:
            with get_pool(self._db).get() as conn:
                rows = conn.execute(
                    """
                    SELECT ts, overall, completeness, coherence, relevance
                    FROM response_quality
                    WHERE ts >= ?
                    """,
                    (since,),
                ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return {
                "avg_overall": 0.0,
                "avg_completeness": 0.0,
                "avg_coherence": 0.0,
                "avg_relevance": 0.0,
                "total_scored": 0,
                "best_hour": None,
                "worst_hour": None,
            }

        total = len(rows)
        avg_overall = round(sum(r[1] for r in rows) / total, 4)
        avg_completeness = round(sum(r[2] for r in rows) / total, 4)
        avg_coherence = round(sum(r[3] for r in rows) / total, 4)
        avg_relevance = round(sum(r[4] for r in rows) / total, 4)

        # Compute per-hour averages to find best/worst hour (0-23)
        hour_scores: dict = {}
        for ts_str, overall, _, _, _ in rows:
            try:
                ts_clean = ts_str.replace("Z", "+00:00")
                hour = datetime.fromisoformat(ts_clean).hour
            except Exception:
                continue
            if hour not in hour_scores:
                hour_scores[hour] = []
            hour_scores[hour].append(overall)

        best_hour = None
        worst_hour = None
        if hour_scores:
            hour_avgs = {h: sum(v) / len(v) for h, v in hour_scores.items()}
            best_hour = max(hour_avgs, key=hour_avgs.get)
            worst_hour = min(hour_avgs, key=hour_avgs.get)

        return {
            "avg_overall": avg_overall,
            "avg_completeness": avg_completeness,
            "avg_coherence": avg_coherence,
            "avg_relevance": avg_relevance,
            "total_scored": total,
            "best_hour": best_hour,
            "worst_hour": worst_hour,
        }

    def get_low_quality_prompts(self, threshold: float = 0.4, limit: int = 10) -> list:
        """
        Returns prompts with overall < threshold (by hash only -- privacy preserved).
        """
        try:
            with get_pool(self._db).get() as conn:
                rows = conn.execute(
                    """
                    SELECT prompt_hash, overall, ts
                    FROM response_quality
                    WHERE overall < ?
                    ORDER BY overall ASC
                    LIMIT ?
                    """,
                    (threshold, limit),
                ).fetchall()
        except Exception:
            return []

        return [
            {"prompt_hash": r[0], "overall": round(r[1], 4), "ts": r[2]}
            for r in rows
        ]

    def _detect_trend(self, values: List[float]) -> str:
        """
        Divides values into two halves, compares averages.
        If second half > first half + 0.05: "improving"
        If second half < first half - 0.05: "declining"
        Else: "stable"
        """
        if len(values) < 4:
            return "stable"
        mid = len(values) // 2
        first_avg = sum(values[:mid]) / mid
        second_avg = sum(values[mid:]) / max(len(values) - mid, 1)
        if second_avg > first_avg + 0.05:
            return "improving"
        elif second_avg < first_avg - 0.05:
            return "declining"
        return "stable"

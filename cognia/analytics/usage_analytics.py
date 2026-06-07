"""
cognia/analytics/usage_analytics.py
=====================================
Usage Analytics Engine — tracks feature usage per user per day.

Table: feature_usage
  id       INTEGER PRIMARY KEY
  feature  TEXT
  user_id  TEXT DEFAULT 'default'
  count    INTEGER DEFAULT 1
  day      TEXT        (YYYY-MM-DD)
  ts       REAL        (Unix epoch at first insert)

UNIQUE constraint on (feature, user_id, day) enforces daily upsert.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

from storage.db_pool import get_pool


_RETENTION_DAYS = 180   # keep analytics for 6 months


class UsageAnalytics:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db         = db_path
        self._record_cnt = 0
        self._init_db()

    # ── Schema ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS feature_usage ("
                "  id      INTEGER PRIMARY KEY,"
                "  feature TEXT    NOT NULL,"
                "  user_id TEXT    NOT NULL DEFAULT 'default',"
                "  count   INTEGER NOT NULL DEFAULT 1,"
                "  day     TEXT    NOT NULL,"
                "  ts      REAL    NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_usage_unique "
                "ON feature_usage(feature, user_id, day)"
            )

    # ── Maintenance ──────────────────────────────────────────────────────

    def prune_old_records(self) -> int:
        """Delete rows older than RETENTION_DAYS. Returns count of deleted rows."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=_RETENTION_DAYS)).isoformat()
        try:
            with get_pool(self._db).get() as conn:
                cur = conn.execute(
                    "DELETE FROM feature_usage WHERE day < ?", (cutoff,)
                )
                return cur.rowcount
        except Exception:
            return 0

    # ── Write ────────────────────────────────────────────────────────────

    def record(self, feature: str, user_id: str = "default") -> None:
        """Upsert: INSERT OR IGNORE first, then increment count by 1."""
        self._record_cnt += 1
        # Prune once per 1000 record() calls to keep table bounded
        if self._record_cnt % 1000 == 0:
            self.prune_old_records()

        day = datetime.date.today().isoformat()
        now = time.time()
        with get_pool(self._db).get() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO feature_usage (feature, user_id, count, day, ts) "
                "VALUES (?, ?, 1, ?, ?)",
                (feature, user_id, day, now),
            )
            conn.execute(
                "UPDATE feature_usage SET count = count + 1 "
                "WHERE feature = ? AND user_id = ? AND day = ?",
                (feature, user_id, day),
            )

    # ── Read ─────────────────────────────────────────────────────────────

    def get_top_features(
        self,
        user_id: str = "default",
        days: int = 30,
        limit: int = 10,
    ) -> list[dict]:
        """Sum counts per feature over last N days, sorted descending."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT feature, SUM(count) AS total "
                "FROM feature_usage "
                "WHERE user_id = ? AND day >= ? "
                "GROUP BY feature "
                "ORDER BY total DESC "
                "LIMIT ?",
                (user_id, cutoff, limit),
            ).fetchall()
        return [{"feature": r[0], "total": r[1]} for r in rows]

    def get_daily_activity(
        self,
        user_id: str = "default",
        days: int = 14,
    ) -> list[dict]:
        """Total usage per day for last N days, sorted ascending."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT day, SUM(count) AS total "
                "FROM feature_usage "
                "WHERE user_id = ? AND day >= ? "
                "GROUP BY day "
                "ORDER BY day ASC",
                (user_id, cutoff),
            ).fetchall()
        return [{"day": r[0], "total": r[1]} for r in rows]

    def get_streak(self, user_id: str = "default") -> int:
        """Count consecutive days ending today with at least 1 usage."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT DISTINCT day FROM feature_usage "
                "WHERE user_id = ? ORDER BY day DESC",
                (user_id,),
            ).fetchall()
        if not rows:
            return 0

        active_days = {r[0] for r in rows}
        streak = 0
        check = datetime.date.today()
        while check.isoformat() in active_days:
            streak += 1
            check -= datetime.timedelta(days=1)
        return streak

    def get_stats(self, user_id: str = "default") -> dict:
        """Return aggregate stats dict."""
        today = datetime.date.today().isoformat()
        with get_pool(self._db).get() as conn:
            total_events = conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM feature_usage WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]

            active_days = conn.execute(
                "SELECT COUNT(DISTINCT day) FROM feature_usage WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]

            top_row = conn.execute(
                "SELECT feature FROM feature_usage "
                "WHERE user_id = ? "
                "GROUP BY feature ORDER BY SUM(count) DESC LIMIT 1",
                (user_id,),
            ).fetchone()

            today_count = conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM feature_usage "
                "WHERE user_id = ? AND day = ?",
                (user_id, today),
            ).fetchone()[0]

        return {
            "total_events": total_events,
            "active_days": active_days,
            "streak": self.get_streak(user_id),
            "top_feature": top_row[0] if top_row else None,
            "today_count": today_count,
        }

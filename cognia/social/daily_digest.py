"""
cognia/social/daily_digest.py
==============================
DailyDigest — aggregates key metrics into a concise daily status summary.
Reads from existing tables; no new DB table required.
"""

from __future__ import annotations

import time
from typing import Any


class DailyDigest:
    """Aggregate daily metrics from existing Cognia tables."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def generate(self, user_id: str = "default") -> dict[str, Any]:
        from storage.db_pool import get_pool

        now = time.time()
        day_ago = now - 86400

        result: dict[str, Any] = {
            "sr_due": 0,
            "goals_pending": 0,
            "new_notes": 0,
            "achievements_unlocked": 0,
            "streak": 0,
            "crystallized_facts": 0,
            "learning_paths_active": 0,
            "top_recommendation": "",
            "generated_at": now,
        }

        try:
            with get_pool(self._db_path).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sr_cards WHERE next_review <= ?", (now,)
                ).fetchone()
                result["sr_due"] = row[0] if row else 0
        except Exception:
            pass

        try:
            with get_pool(self._db_path).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM user_goals WHERE status='pending'"
                ).fetchone()
                result["goals_pending"] = row[0] if row else 0
        except Exception:
            pass

        try:
            with get_pool(self._db_path).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM smart_notes WHERE ts > ?", (day_ago,)
                ).fetchone()
                result["new_notes"] = row[0] if row else 0
        except Exception:
            pass

        try:
            with get_pool(self._db_path).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM user_achievements WHERE unlocked_at > ?",
                    (day_ago,),
                ).fetchone()
                result["achievements_unlocked"] = row[0] if row else 0
        except Exception:
            pass

        # Streak: count consecutive days with any feature_usage entry ending today
        try:
            with get_pool(self._db_path).get() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT day FROM feature_usage "
                    "WHERE user_id = ? ORDER BY day DESC",
                    (user_id,),
                ).fetchall()
            today_str = time.strftime("%Y-%m-%d", time.localtime(now))
            days = [r[0] for r in rows]
            streak = 0
            from datetime import date, timedelta

            check = date.fromisoformat(today_str)
            for d in days:
                if d == check.isoformat():
                    streak += 1
                    check -= timedelta(days=1)
                else:
                    break
            result["streak"] = streak
        except Exception:
            pass

        try:
            with get_pool(self._db_path).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_graph WHERE crystallized=1"
                ).fetchone()
                result["crystallized_facts"] = row[0] if row else 0
        except Exception:
            pass

        try:
            with get_pool(self._db_path).get() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM learning_paths WHERE completed=0"
                ).fetchone()
                result["learning_paths_active"] = row[0] if row else 0
        except Exception:
            pass

        try:
            from cognia.intelligence.recommendation_engine import RecommendationEngine

            top = RecommendationEngine().get_top(user_id)
            result["top_recommendation"] = (top or {}).get("title", "")
        except Exception:
            pass

        return result

    def format_digest(self, data: dict[str, Any]) -> str:
        rec = data.get("top_recommendation", "")
        rec_line = f"Recomendacion: {rec}" if rec else ""
        lines = [
            "=== Cognia -- Digest del dia ===",
            "",
            f"Aprendizaje espaciado : {data.get('sr_due', 0)} tarjeta(s) para revisar",
            f"Objetivos pendientes  : {data.get('goals_pending', 0)}",
            f"Notas nuevas (24h)    : {data.get('new_notes', 0)}",
            f"Logros desbloqueados  : {data.get('achievements_unlocked', 0)} hoy",
            f"Racha actual          : {data.get('streak', 0)} dia(s)",
            f"Hechos cristalizados  : {data.get('crystallized_facts', 0)}",
            f"Caminos activos       : {data.get('learning_paths_active', 0)}",
            "",
        ]
        if rec_line:
            lines.append(rec_line)
            lines.append("")
        lines.append("==============================")
        return "\n".join(lines)

    def get_digest_text(self, user_id: str = "default") -> str:
        return self.format_digest(self.generate(user_id))

"""
cognia/proactive/proactive_engine.py
=====================================
Surfaces contextually relevant suggestions without being asked.

Table: proactive_suggestions
  id              INTEGER PRIMARY KEY
  text            TEXT
  category        TEXT
  context_trigger TEXT
  shown           INTEGER DEFAULT 0
  ts              REAL
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH = str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")

_STOPWORDS = {
    "el", "la", "los", "las", "de", "que", "en", "y", "a", "es", "un", "una",
    "the", "is", "an", "of", "to", "and", "or",
}

_QUESTION_WORDS = {"como", "cómo", "por que", "que es", "what", "how", "why"}


def _init_db(db_path: str) -> None:
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS proactive_suggestions ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  text TEXT NOT NULL,"
            "  category TEXT NOT NULL DEFAULT 'general',"
            "  context_trigger TEXT NOT NULL DEFAULT '',"
            "  shown INTEGER NOT NULL DEFAULT 0,"
            "  ts REAL NOT NULL"
            ")"
        )


class ProactiveEngine:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db       = db_path or _DB_PATH
        self._queue_cnt = 0
        _init_db(self._db)

    # ------------------------------------------------------------------
    # Core generation — pure in-memory, no DB writes
    # ------------------------------------------------------------------

    def generate_suggestions(
        self,
        recent_text: str,
        active_goals: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Extracts keywords from recent_text and returns up to 3 relevant suggestions.

        Returns list of dicts: [{"text": str, "category": str, "relevance": float}]
        """
        if active_goals is None:
            active_goals = []

        words = recent_text.lower().split()
        keywords = [w for w in words if w not in _STOPWORDS and len(w) > 2]
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_kws: list[str] = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique_kws.append(w)
        keywords = unique_kws[:3]

        suggestions: list[dict] = []

        # Goal reminder suggestions
        for kw in keywords:
            for goal in active_goals:
                if kw in goal.lower():
                    suggestions.append({
                        "text": f"Tienes un objetivo activo relacionado: {goal}",
                        "category": "goal_reminder",
                        "relevance": 0.9,
                    })
                    break
            if len(suggestions) >= 3:
                break

        # Web search suggestions based on question words
        text_lower = recent_text.lower()
        detected_question = any(qw in text_lower for qw in _QUESTION_WORDS)
        if detected_question and keywords and len(suggestions) < 3:
            kw = keywords[0]
            suggestions.append({
                "text": f"Podria buscar en la web sobre: {kw}",
                "category": "web_search",
                "relevance": 0.7,
            })

        # Sort by relevance descending, cap at 3
        suggestions.sort(key=lambda s: s["relevance"], reverse=True)
        return suggestions[:3]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def queue_suggestion(
        self,
        text: str,
        category: str = "general",
        context_trigger: str = "",
    ) -> None:
        """Insert a suggestion into the DB with shown=0."""
        self._queue_cnt += 1
        if self._queue_cnt % 200 == 0:
            self.prune_old_suggestions()

        with get_pool(self._db).get() as conn:
            conn.execute(
                "INSERT INTO proactive_suggestions (text, category, context_trigger, shown, ts)"
                " VALUES (?, ?, ?, 0, ?)",
                (text, category, context_trigger, time.time()),
            )

    def get_pending(self, limit: int = 3) -> list[str]:
        """Return unshown suggestion texts and mark them as shown."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, text FROM proactive_suggestions"
                " WHERE shown = 0 ORDER BY ts ASC LIMIT ?",
                (limit,),
            ).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE proactive_suggestions SET shown = 1 WHERE id IN ({placeholders})",
                    ids,
                )
        return [r[1] for r in rows]

    def prune_old_suggestions(self, shown_max_age_days: int = 7) -> int:
        """Delete suggestions that have been shown and are older than shown_max_age_days."""
        cutoff = time.time() - shown_max_age_days * 86400
        try:
            with get_pool(self._db).get() as conn:
                cur = conn.execute(
                    "DELETE FROM proactive_suggestions WHERE shown = 1 AND ts < ?",
                    (cutoff,),
                )
                return cur.rowcount
        except Exception:
            return 0

    def get_stats(self) -> dict:
        """Return total_generated, shown, pending counts."""
        with get_pool(self._db).get() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM proactive_suggestions"
            ).fetchone()[0] or 0
            shown = conn.execute(
                "SELECT COUNT(*) FROM proactive_suggestions WHERE shown = 1"
            ).fetchone()[0] or 0
            pending = conn.execute(
                "SELECT COUNT(*) FROM proactive_suggestions WHERE shown = 0"
            ).fetchone()[0] or 0
        return {"total_generated": total, "shown": shown, "pending": pending}

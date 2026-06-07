"""
cognia/goals/goal_tracker.py
============================
Persistent goal tracking for Cognia users.

Table: user_goals
  id           INTEGER PRIMARY KEY AUTOINCREMENT
  user_id      TEXT NOT NULL
  title        TEXT NOT NULL
  description  TEXT NOT NULL DEFAULT ''
  status       TEXT NOT NULL DEFAULT 'active'  -- active|completed|paused|abandoned
  progress_pct INTEGER NOT NULL DEFAULT 0      -- 0-100
  created_at   INTEGER NOT NULL
  updated_at   INTEGER NOT NULL
  completed_at INTEGER                         -- NULL until status='completed'
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from storage.db_pool import get_pool

_GOALS_DB = str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")

_VALID_STATUSES = {"active", "completed", "paused", "abandoned"}


def _row_to_dict(row) -> dict:
    return {
        "id":           row[0],
        "user_id":      row[1],
        "title":        row[2],
        "description":  row[3],
        "status":       row[4],
        "progress_pct": row[5],
        "created_at":   row[6],
        "updated_at":   row[7],
        "completed_at": row[8],
    }


class GoalTracker:
    """
    Persists user goals and tracks progress against them.
    Uses storage/db_pool.py — never calls sqlite3.connect() directly.
    """

    def __init__(self, db_path: str = _GOALS_DB):
        self._db = db_path
        self._init_db()

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_goals (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      TEXT    NOT NULL,
                    title        TEXT    NOT NULL,
                    description  TEXT    NOT NULL DEFAULT '',
                    status       TEXT    NOT NULL DEFAULT 'active',
                    progress_pct INTEGER NOT NULL DEFAULT 0,
                    created_at   INTEGER NOT NULL,
                    updated_at   INTEGER NOT NULL,
                    completed_at INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_goals_user ON user_goals(user_id, status)"
            )

    # ── CRUD ──────────────────────────────────────────────────────────

    def create_goal(self, user_id: str, title: str, description: str = "") -> dict:
        """Insert a new active goal and return it as a dict."""
        now = int(time.time())
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                """
                INSERT INTO user_goals
                    (user_id, title, description, status, progress_pct, created_at, updated_at)
                VALUES (?, ?, ?, 'active', 0, ?, ?)
                """,
                (user_id, title, description, now, now),
            )
            goal_id = cur.lastrowid
            row = conn.execute(
                "SELECT id, user_id, title, description, status, progress_pct, "
                "created_at, updated_at, completed_at FROM user_goals WHERE id = ?",
                (goal_id,),
            ).fetchone()
        return _row_to_dict(row)

    def update_progress(
        self, goal_id: int, progress_pct: int, user_id: Optional[str] = None
    ) -> bool:
        """
        Update progress_pct (clamped to 0-100).
        Automatically sets status='completed' and completed_at when progress_pct==100.
        Returns True if a row was updated, False if not found.
        """
        progress_pct = max(0, min(100, progress_pct))
        now = int(time.time())

        if progress_pct == 100:
            sql = (
                "UPDATE user_goals SET progress_pct = ?, status = 'completed', "
                "updated_at = ?, completed_at = ? WHERE id = ?"
            )
            params: tuple = (progress_pct, now, now, goal_id)
        else:
            sql = (
                "UPDATE user_goals SET progress_pct = ?, updated_at = ? WHERE id = ?"
            )
            params = (progress_pct, now, goal_id)

        if user_id is not None:
            sql += " AND user_id = ?"
            params = params + (user_id,)

        with get_pool(self._db).get() as conn:
            cur = conn.execute(sql, params)
            return cur.rowcount > 0

    def get_goals(self, user_id: str, status: Optional[str] = None) -> list[dict]:
        """
        Return goals for user_id, optionally filtered by status.
        Ordered by created_at DESC.
        """
        if status is not None and status not in _VALID_STATUSES:
            return []

        sql = (
            "SELECT id, user_id, title, description, status, progress_pct, "
            "created_at, updated_at, completed_at FROM user_goals WHERE user_id = ?"
        )
        params: tuple = (user_id,)
        if status is not None:
            sql += " AND status = ?"
            params = (user_id, status)
        sql += " ORDER BY created_at DESC"

        with get_pool(self._db).get() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_active_goals_summary(self, user_id: str) -> str:
        """
        Return a one-line string for injecting into language_engine context.
        Format: "Metas activas: [Aprender Python (45%), Leer 12 libros (25%)]"
        Returns "" if the user has no active goals.
        """
        goals = self.get_goals(user_id, status="active")
        if not goals:
            return ""
        parts = [f"{g['title']} ({g['progress_pct']}%)" for g in goals]
        return "Metas activas: [" + ", ".join(parts) + "]"

    def delete_goal(self, goal_id: int, user_id: str) -> bool:
        """Delete a goal. Returns True if deleted, False if not found."""
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "DELETE FROM user_goals WHERE id = ? AND user_id = ?",
                (goal_id, user_id),
            )
            return cur.rowcount > 0

    # ── Heuristic progress detection ──────────────────────────────────

    @staticmethod
    def _keywords(text: str) -> set[str]:
        """Lowercase word tokens, stripped of punctuation, length >= 3."""
        return {w for w in re.findall(r"[a-zA-Z\u00C0-\u024F]{3,}", text.lower())}

    def auto_detect_progress(
        self, user_id: str, conversation_text: str
    ) -> list[dict]:
        """
        Heuristic: find active goals whose title keywords overlap with
        conversation_text (Jaccard >= 0.3).

        Returns list of {goal_id, title, suggested_increment} — does NOT
        update progress; caller decides whether to apply the suggestion.
        suggested_increment is always 5.
        """
        active = self.get_goals(user_id, status="active")
        if not active:
            return []

        conv_kw = self._keywords(conversation_text)
        if not conv_kw:
            return []

        results = []
        for goal in active:
            goal_kw = self._keywords(goal["title"] + " " + goal["description"])
            if not goal_kw:
                continue
            intersection = goal_kw & conv_kw
            union = goal_kw | conv_kw
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard >= 0.3:
                results.append(
                    {
                        "goal_id":            goal["id"],
                        "title":              goal["title"],
                        "suggested_increment": 5,
                    }
                )
        return results

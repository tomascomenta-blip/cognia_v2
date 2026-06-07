"""
cognia/gamification/achievement_system.py
=========================================
Event-driven achievement / gamification engine.

Uses get_pool() from storage/db_pool.py — no direct sqlite3.connect() calls.
No PyTorch, no new abstractions beyond what is described.
"""

from __future__ import annotations

import time
from typing import Optional

from storage.db_pool import get_pool

# Catalog: (id, name, description, icon, points)
_CATALOG = [
    ("first_message",  "Primera Conversacion", "Enviaste tu primer mensaje a Cognia",   "*",  10),
    ("first_note",     "Primer Apunte",        "Guardaste tu primera nota",             "#",  15),
    ("first_goal",     "Primer Objetivo",      "Creaste tu primer objetivo",            ">",  15),
    ("first_card",     "Primera Tarjeta",      "Agregaste tu primera tarjeta de estudio","^", 15),
    ("ten_messages",   "Conversador",          "Enviaste 10 mensajes",                  "~",  25),
    ("five_goals",     "Ambicioso",            "Creaste 5 objetivos",                   "@",  50),
    ("ten_cards",      "Estudioso",            "Tienes 10 tarjetas de estudio",         "=",  50),
    ("week_streak",    "Racha Semanal",        "Usaste Cognia 7 dias seguidos",         "!",  100),
    ("first_search",   "Curioso",              "Realizaste tu primera busqueda web",    "?",  20),
    ("first_export",   "Archivista",           "Exportaste tu historial",               "&",  20),
]

# Event -> list of (achievement_id, min_count)
_EVENT_MAP: dict[str, list[tuple[str, int]]] = {
    "message_sent": [("first_message", 1), ("ten_messages", 10)],
    "note_saved":   [("first_note", 1)],
    "goal_created": [("first_goal", 1), ("five_goals", 5)],
    "card_added":   [("first_card", 1), ("ten_cards", 10)],
    "search_done":  [("first_search", 1)],
    "export_done":  [("first_export", 1)],
}


class AchievementSystem:
    """Manages achievement catalog and per-user unlock state."""

    def __init__(self, db_path: str) -> None:
        self._db = db_path
        self._init_tables()
        self._seed_catalog()

    # ── Internal helpers ───────────────────────────────────────────────

    def _init_tables(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS achievements_catalog ("
                "  id TEXT PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  description TEXT NOT NULL,"
                "  icon TEXT NOT NULL,"
                "  points INTEGER NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS user_achievements ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  achievement_id TEXT NOT NULL,"
                "  user_id TEXT NOT NULL,"
                "  unlocked_at REAL NOT NULL,"
                "  UNIQUE(achievement_id, user_id)"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ua_user "
                "ON user_achievements(user_id)"
            )

    def _seed_catalog(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO achievements_catalog "
                "(id, name, description, icon, points) VALUES (?, ?, ?, ?, ?)",
                _CATALOG,
            )

    def _is_unlocked(self, conn, user_id: str, achievement_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM user_achievements "
            "WHERE achievement_id = ? AND user_id = ?",
            (achievement_id, user_id),
        ).fetchone()
        return row is not None

    def _unlock(self, conn, user_id: str, achievement_id: str) -> Optional[str]:
        """Unlock an achievement; return name if newly unlocked, else None."""
        if self._is_unlocked(conn, user_id, achievement_id):
            return None
        conn.execute(
            "INSERT OR IGNORE INTO user_achievements "
            "(achievement_id, user_id, unlocked_at) VALUES (?, ?, ?)",
            (achievement_id, user_id, time.time()),
        )
        row = conn.execute(
            "SELECT name FROM achievements_catalog WHERE id = ?",
            (achievement_id,),
        ).fetchone()
        return row[0] if row else achievement_id

    # ── Public API ─────────────────────────────────────────────────────

    def check_and_unlock(self, user_id: str, event: str, count: int = 1) -> list[str]:
        """
        Based on event+count, unlock matching achievements.
        Returns list of newly unlocked achievement names.
        """
        candidates = _EVENT_MAP.get(event, [])
        if not candidates:
            return []

        newly_unlocked: list[str] = []
        with get_pool(self._db).get() as conn:
            for achievement_id, min_count in candidates:
                if count >= min_count:
                    name = self._unlock(conn, user_id, achievement_id)
                    if name is not None:
                        newly_unlocked.append(name)
        return newly_unlocked

    def get_user_achievements(self, user_id: str) -> list[dict]:
        """Return unlocked achievements with name/points/unlocked_at."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT c.name, c.points, ua.unlocked_at "
                "FROM user_achievements ua "
                "JOIN achievements_catalog c ON c.id = ua.achievement_id "
                "WHERE ua.user_id = ? "
                "ORDER BY ua.unlocked_at DESC",
                (user_id,),
            ).fetchall()
        return [
            {"name": r[0], "points": r[1], "unlocked_at": r[2]}
            for r in rows
        ]

    def get_all_with_status(self, user_id: str) -> list[dict]:
        """Return all catalog items with unlocked: bool."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT c.id, c.name, c.description, c.icon, c.points, "
                "       CASE WHEN ua.achievement_id IS NOT NULL THEN 1 ELSE 0 END as unlocked,"
                "       ua.unlocked_at "
                "FROM achievements_catalog c "
                "LEFT JOIN user_achievements ua "
                "  ON ua.achievement_id = c.id AND ua.user_id = ? "
                "ORDER BY c.points ASC",
                (user_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "icon": r[3],
                "points": r[4],
                "unlocked": bool(r[5]),
                "unlocked_at": r[6],
            }
            for r in rows
        ]

    def get_points(self, user_id: str) -> int:
        """Sum of points for all unlocked achievements."""
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(c.points), 0) "
                "FROM user_achievements ua "
                "JOIN achievements_catalog c ON c.id = ua.achievement_id "
                "WHERE ua.user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def get_stats(self, user_id: str) -> dict:
        """Return {"unlocked": N, "total": N, "points": N, "latest": name_or_null}."""
        with get_pool(self._db).get() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM achievements_catalog"
            ).fetchone()
            unlocked_row = conn.execute(
                "SELECT COUNT(*) FROM user_achievements WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            points_row = conn.execute(
                "SELECT COALESCE(SUM(c.points), 0) "
                "FROM user_achievements ua "
                "JOIN achievements_catalog c ON c.id = ua.achievement_id "
                "WHERE ua.user_id = ?",
                (user_id,),
            ).fetchone()
            latest_row = conn.execute(
                "SELECT c.name FROM user_achievements ua "
                "JOIN achievements_catalog c ON c.id = ua.achievement_id "
                "WHERE ua.user_id = ? "
                "ORDER BY ua.unlocked_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()

        return {
            "unlocked": int(unlocked_row[0]) if unlocked_row else 0,
            "total":    int(total_row[0]) if total_row else 0,
            "points":   int(points_row[0]) if points_row else 0,
            "latest":   latest_row[0] if latest_row else None,
        }

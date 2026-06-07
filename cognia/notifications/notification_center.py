"""
cognia/notifications/notification_center.py
============================================
In-app notification center.

Table: notifications
  id          INTEGER PRIMARY KEY AUTOINCREMENT
  user_id     TEXT NOT NULL
  title       TEXT NOT NULL
  body        TEXT NOT NULL DEFAULT ''
  level       TEXT NOT NULL DEFAULT 'info'   -- info|success|warning|error
  read        INTEGER NOT NULL DEFAULT 0     -- 0=unread, 1=read
  created_at  REAL NOT NULL                  -- time.time()
  source      TEXT NOT NULL DEFAULT 'system' -- goal_tracker|curiosity|quality|system|webhook
"""

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path

from storage.db_pool import get_pool

_NOTIF_DB = str(Path(__file__).parent.parent.parent / "cognia_desktop_chat.db")

_VALID_LEVELS = {"info", "success", "warning", "error"}
_VALID_SOURCES = {"goal_tracker", "curiosity", "quality", "system", "webhook"}


class NotificationLevel(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


def _row_to_dict(row) -> dict:
    return {
        "id":         row[0],
        "user_id":    row[1],
        "title":      row[2],
        "body":       row[3],
        "level":      row[4],
        "read":       bool(row[5]),
        "created_at": row[6],
        "source":     row[7],
    }


class NotificationCenter:
    """
    Centro de notificaciones in-app.
    Uses storage/db_pool.py -- never calls sqlite3.connect() directly.
    """

    def __init__(self, db_path: str = _NOTIF_DB):
        self._db = db_path
        self._init_db()

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    TEXT NOT NULL,
                    title      TEXT NOT NULL,
                    body       TEXT NOT NULL DEFAULT '',
                    level      TEXT NOT NULL DEFAULT 'info',
                    read       INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    source     TEXT NOT NULL DEFAULT 'system'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notif_user_read "
                "ON notifications(user_id, read, created_at)"
            )

    def create(
        self,
        user_id: str,
        title: str,
        body: str = "",
        level: str = "info",
        source: str = "system",
    ) -> dict:
        """Insert a notification and return its dict."""
        if level not in _VALID_LEVELS:
            raise ValueError(
                f"Invalid level '{level}'. Valid values: {sorted(_VALID_LEVELS)}"
            )
        # Accept but don't strictly enforce source to remain extensible
        now = time.time()
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "INSERT INTO notifications (user_id, title, body, level, read, created_at, source) "
                "VALUES (?, ?, ?, ?, 0, ?, ?)",
                (user_id, title, body, level, now, source),
            )
            row_id = cur.lastrowid
        return {
            "id":         row_id,
            "user_id":    user_id,
            "title":      title,
            "body":       body,
            "level":      level,
            "read":       False,
            "created_at": now,
            "source":     source,
        }

    def get_unread(self, user_id: str, limit: int = 20) -> list[dict]:
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, user_id, title, body, level, read, created_at, source "
                "FROM notifications "
                "WHERE user_id = ? AND read = 0 "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_all(
        self, user_id: str, limit: int = 50, include_read: bool = True
    ) -> list[dict]:
        if include_read:
            sql = (
                "SELECT id, user_id, title, body, level, read, created_at, source "
                "FROM notifications WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT ?"
            )
            params = (user_id, limit)
        else:
            sql = (
                "SELECT id, user_id, title, body, level, read, created_at, source "
                "FROM notifications WHERE user_id = ? AND read = 0 "
                "ORDER BY created_at DESC LIMIT ?"
            )
            params = (user_id, limit)
        with get_pool(self._db).get() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def mark_read(self, notification_id: int, user_id: str) -> bool:
        """Mark a single notification as read. Returns True if a row was updated."""
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
                (notification_id, user_id),
            )
            return cur.rowcount > 0

    def mark_all_read(self, user_id: str) -> int:
        """Mark all unread notifications for user as read. Returns count updated."""
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0",
                (user_id,),
            )
            return cur.rowcount

    def delete(self, notification_id: int, user_id: str) -> bool:
        """Delete a notification scoped to user_id. Returns True if deleted."""
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "DELETE FROM notifications WHERE id = ? AND user_id = ?",
                (notification_id, user_id),
            )
            return cur.rowcount > 0

    def get_unread_count(self, user_id: str) -> int:
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read = 0",
                (user_id,),
            ).fetchone()
        return row[0] if row else 0

    def create_goal_notification(
        self, user_id: str, goal_title: str, progress: int
    ) -> None:
        """Create a contextual notification for goal progress updates."""
        if progress >= 100:
            self.create(
                user_id=user_id,
                title="Meta completada!",
                body=f"Has completado la meta: {goal_title}",
                level="success",
                source="goal_tracker",
            )
        elif progress >= 50:
            self.create(
                user_id=user_id,
                title=f"Meta al {progress}%",
                body=f"Buen avance en: {goal_title}",
                level="info",
                source="goal_tracker",
            )

    def create_quality_alert(self, user_id: str, avg_score: float) -> None:
        """Create a warning notification when average response quality is low."""
        if avg_score < 0.4:
            self.create(
                user_id=user_id,
                title="Calidad de respuestas baja",
                body=f"Puntuacion promedio de calidad: {avg_score:.2f}. Considera revisar las respuestas recientes.",
                level="warning",
                source="quality",
            )

"""
cognia/learning/spaced_repetition.py
======================================
SpacedRepetitionEngine -- SM-2 algorithm for tracking user learning cards.
"""
from __future__ import annotations

import time
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH: Optional[str] = None  # set by cognia_desktop_api.py at startup


def _get_db() -> str:
    if _DB_PATH:
        return _DB_PATH
    return "cognia_spaced_repetition.db"


class SpacedRepetitionEngine:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db = db_path or _get_db()
        self._init_db()

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sr_cards ("
                "  id INTEGER PRIMARY KEY,"
                "  front TEXT NOT NULL,"
                "  back TEXT NOT NULL,"
                "  topic TEXT NOT NULL DEFAULT 'general',"
                "  ease_factor REAL NOT NULL DEFAULT 2.5,"
                "  interval_days REAL NOT NULL DEFAULT 1.0,"
                "  repetitions INTEGER NOT NULL DEFAULT 0,"
                "  next_review REAL NOT NULL,"
                "  last_reviewed REAL,"
                "  created_at REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sr_next_review ON sr_cards(next_review)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sr_topic ON sr_cards(topic)"
            )

    def add_card(self, front: str, back: str, topic: str = "general") -> int:
        """Insert a new card due immediately. Returns the new card id."""
        now = time.time()
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "INSERT INTO sr_cards (front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at) "
                "VALUES (?, ?, ?, 2.5, 1.0, 0, ?, NULL, ?)",
                (front, back, topic, now, now),
            )
            return cur.lastrowid

    def get_due_cards(self, limit: int = 10) -> list[dict]:
        """Return cards with next_review <= now, ordered by next_review ASC."""
        now = time.time()
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at "
                "FROM sr_cards WHERE next_review <= ? ORDER BY next_review ASC LIMIT ?",
                (now, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def review_card(self, card_id: int, quality: int) -> dict:
        """Apply SM-2 update and return the updated card dict.

        quality 0-5: 0=blackout, 3=correct with effort, 5=perfect.
        """
        quality = max(0, min(5, quality))
        now = time.time()

        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT id, front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at "
                "FROM sr_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"card {card_id} not found")

            card = _row_to_dict(row)
            ease = card["ease_factor"]
            reps = card["repetitions"]
            prev_interval = card["interval_days"]

            if quality < 3:
                # Failed: reset
                new_reps = 0
                new_interval = 1.0
                new_ease = ease  # ease unchanged on failure
                next_review = now + 86400.0
            else:
                # SM-2 ease update
                new_ease = ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
                new_ease = max(1.3, new_ease)

                if reps == 0:
                    new_interval = 1.0
                elif reps == 1:
                    new_interval = 6.0
                else:
                    new_interval = round(prev_interval * ease)

                new_reps = reps + 1
                next_review = now + new_interval * 86400.0

            conn.execute(
                "UPDATE sr_cards SET ease_factor=?, interval_days=?, repetitions=?, "
                "next_review=?, last_reviewed=? WHERE id=?",
                (new_ease, new_interval, new_reps, next_review, now, card_id),
            )

        # Fetch updated card
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT id, front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at "
                "FROM sr_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        return _row_to_dict(row)

    def get_stats(self) -> dict:
        """Return {"total": N, "due_today": N, "mastered": N, "topics": [...]}."""
        now = time.time()
        with get_pool(self._db).get() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sr_cards").fetchone()[0]
            due = conn.execute(
                "SELECT COUNT(*) FROM sr_cards WHERE next_review <= ?", (now,)
            ).fetchone()[0]
            mastered = conn.execute(
                "SELECT COUNT(*) FROM sr_cards WHERE repetitions >= 5"
            ).fetchone()[0]
            topic_rows = conn.execute(
                "SELECT DISTINCT topic FROM sr_cards ORDER BY topic"
            ).fetchall()
        topics = [r[0] for r in topic_rows]
        return {"total": total, "due_today": due, "mastered": mastered, "topics": topics}

    def search_cards(self, query: str) -> list[dict]:
        """Return cards whose front or back contains query (case-insensitive LIKE)."""
        pattern = f"%{query}%"
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, front, back, topic, ease_factor, interval_days, "
                "repetitions, next_review, last_reviewed, created_at "
                "FROM sr_cards WHERE front LIKE ? OR back LIKE ? ORDER BY id",
                (pattern, pattern),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "front": row[1],
        "back": row[2],
        "topic": row[3],
        "ease_factor": row[4],
        "interval_days": row[5],
        "repetitions": row[6],
        "next_review": row[7],
        "last_reviewed": row[8],
        "created_at": row[9],
    }

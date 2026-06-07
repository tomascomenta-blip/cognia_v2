"""
cognia/notes/smart_notes.py
============================
Smart Notes Engine — extracts and stores structured notes from assistant responses.
Note types: fact, decision, action, insight, question.
"""
from __future__ import annotations

import time
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH: Optional[str] = None  # set by cognia_desktop_api.py at startup


def _get_db() -> str:
    if _DB_PATH:
        return _DB_PATH
    # fallback for testing
    return "cognia_smart_notes.db"


_DECISION_KEYWORDS = [
    "decidir", "decidimos", "decision", "optamos", "elegimos",
    "decided", "we chose", "i recommend",
]
_ACTION_KEYWORDS = [
    "debes", "deberias", "te recomiendo", "el siguiente paso", "puedes",
    "you should", "next step", "action:",
]
_FACT_KEYWORDS = [
    "es un", "es una", "se llama", "significa",
    "is a", "is called", "means", "defined as",
]
_QUESTION_STARTS = ["como", "por que", "que", "cuando", "how", "why", "what", "when"]


class SmartNotesEngine:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db = db_path or _get_db()
        self._init_db()

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS smart_notes ("
                "  id INTEGER PRIMARY KEY,"
                "  session_id TEXT NOT NULL,"
                "  content TEXT NOT NULL,"
                "  note_type TEXT NOT NULL,"
                "  source TEXT NOT NULL DEFAULT 'manual',"
                "  pinned INTEGER NOT NULL DEFAULT 0,"
                "  ts REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_session ON smart_notes(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_type ON smart_notes(note_type)"
            )

    def extract_from_text(self, text: str, session_id: str) -> list[dict]:
        """Heuristic extraction of up to 2 structured notes from assistant text."""
        stripped = text.strip()
        if not stripped:
            return []

        lower = stripped.lower()
        note_type: Optional[str] = None

        # Decision
        if any(kw in lower for kw in _DECISION_KEYWORDS):
            note_type = "decision"
        # Action
        elif any(kw in lower for kw in _ACTION_KEYWORDS):
            note_type = "action"
        # Fact
        elif any(kw in lower for kw in _FACT_KEYWORDS):
            note_type = "fact"
        # Question — ends with ? or starts with question word
        elif stripped.endswith("?") or any(lower.startswith(qw) for qw in _QUESTION_STARTS):
            note_type = "question"
        # Insight — only if long enough
        elif len(stripped) > 100:
            note_type = "insight"

        if note_type is None:
            return []

        content = stripped[:200]
        return [{"content": content, "note_type": note_type, "session_id": session_id}]

    def add_note(
        self,
        content: str,
        note_type: str = "fact",
        session_id: str = "default",
        source: str = "manual",
    ) -> int:
        """Insert a note; returns the new row id."""
        ts = time.time()
        with get_pool(self._db).get() as conn:
            cur = conn.execute(
                "INSERT INTO smart_notes (session_id, content, note_type, source, pinned, ts)"
                " VALUES (?, ?, ?, ?, 0, ?)",
                (session_id, content, note_type, source, ts),
            )
            return cur.lastrowid

    def get_notes(
        self,
        session_id: Optional[str] = None,
        note_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Return notes with optional session and type filters."""
        conditions: list[str] = []
        params: list = []
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)
        if note_type is not None:
            conditions.append("note_type = ?")
            params.append(note_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                f"SELECT id, session_id, content, note_type, source, pinned, ts"
                f" FROM smart_notes {where}"
                f" ORDER BY ts DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "content": r[2],
                "note_type": r[3],
                "source": r[4],
                "pinned": bool(r[5]),
                "ts": r[6],
            }
            for r in rows
        ]

    def pin_note(self, note_id: int) -> None:
        """Set pinned=1 for the given note."""
        with get_pool(self._db).get() as conn:
            conn.execute("UPDATE smart_notes SET pinned = 1 WHERE id = ?", (note_id,))

    def search_notes(self, query: str, limit: int = 10) -> list[dict]:
        """LIKE search on content field."""
        pattern = f"%{query}%"
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, session_id, content, note_type, source, pinned, ts"
                " FROM smart_notes WHERE content LIKE ?"
                " ORDER BY ts DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "content": r[2],
                "note_type": r[3],
                "source": r[4],
                "pinned": bool(r[5]),
                "ts": r[6],
            }
            for r in rows
        ]

    def get_stats(self) -> dict:
        """Return total count, per-type counts, and pinned count."""
        with get_pool(self._db).get() as conn:
            total_row = conn.execute("SELECT COUNT(*) FROM smart_notes").fetchone()
            pinned_row = conn.execute(
                "SELECT COUNT(*) FROM smart_notes WHERE pinned = 1"
            ).fetchone()
            type_rows = conn.execute(
                "SELECT note_type, COUNT(*) FROM smart_notes GROUP BY note_type"
            ).fetchall()

        by_type: dict[str, int] = {}
        for note_type, count in type_rows:
            by_type[note_type] = count

        return {
            "total": total_row[0] if total_row else 0,
            "by_type": by_type,
            "pinned": pinned_row[0] if pinned_row else 0,
        }

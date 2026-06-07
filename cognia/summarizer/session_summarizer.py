"""
cognia/summarizer/session_summarizer.py
=======================================
Auto-Summarizer: every TRIGGER_TURNS user turns, generates an extractive summary
of the conversation and stores it as a semantic episode (fire-and-forget background
thread). No LLM calls — pure keyword density ranking.
"""

import re
import threading
import time

# _CHAT_DB is injected at startup by cognia_desktop_api.py
_CHAT_DB: str | None = None


class SessionSummarizer:
    """
    Summarizes conversations every TRIGGER_TURNS user turns and stores in episodic memory.
    Summary is extractive (no LLM) — extracts key sentences from user messages ranked
    by unique-token density.
    """

    TRIGGER_TURNS = 10   # every N user turns
    MAX_SUMMARY_LEN = 300

    def __init__(self):
        self._session_counts: dict = {}   # {session_id: turn_count}
        self._lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────────

    def on_message(self, session_id: str, role: str, content: str) -> None:
        """
        Call after each message is saved to DB.
        If role='user' and turn count is a multiple of TRIGGER_TURNS:
        triggers summarize in a background daemon thread.
        """
        if role != "user":
            return

        with self._lock:
            count = self._session_counts.get(session_id, 0) + 1
            self._session_counts[session_id] = count

        if count % self.TRIGGER_TURNS == 0:
            threading.Thread(
                target=self._summarize_and_store,
                args=(session_id, count),
                daemon=True,
            ).start()

    def extract_summary(self, messages: list) -> str:
        """
        Extractive summary from a list of message dicts.
        1. Concatenates user message content.
        2. Tokenizes into sentences (split on . ! ?).
        3. Ranks sentences by unique-token density.
        4. Returns top 3 sentences, capped at MAX_SUMMARY_LEN chars.
        """
        user_text = " ".join(
            m.get("content", "") for m in messages if m.get("role") == "user"
        )
        if not user_text.strip():
            return ""

        sentences = [s.strip() for s in re.split(r"[.!?]", user_text) if len(s.strip()) > 10]
        if not sentences:
            return user_text[: self.MAX_SUMMARY_LEN]

        def density(s: str) -> float:
            tokens = s.lower().split()
            return len(set(tokens)) / max(len(tokens), 1)

        ranked = sorted(sentences, key=density, reverse=True)[:3]
        summary = ". ".join(ranked)
        return summary[: self.MAX_SUMMARY_LEN]

    def get_summaries(self, session_id: str, limit: int = 10) -> list:
        """Return recent summaries for session_id from session_summaries table."""
        db = _CHAT_DB
        if not db:
            return []
        try:
            from storage.db_pool import get_pool
            with get_pool(db).get() as conn:
                rows = conn.execute(
                    "SELECT id, session_id, summary, turn_count, created_at"
                    " FROM session_summaries"
                    " WHERE session_id = ?"
                    " ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            return [
                {
                    "id": r[0],
                    "session_id": r[1],
                    "summary": r[2],
                    "turn_count": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        except Exception:
            return []

    # ── Internal helpers ─────────────────────────────────────────────────

    def _summarize_and_store(self, session_id: str, turn_count: int) -> None:
        """Background thread: load messages, extract summary, store episode."""
        try:
            messages = self._load_recent_messages(
                session_id, limit=self.TRIGGER_TURNS * 2
            )
            if not messages:
                return
            summary = self.extract_summary(messages)
            if not summary:
                return
            self._store_episode(session_id, summary, turn_count)
        except Exception:
            pass  # never crash background thread

    def _load_recent_messages(self, session_id: str, limit: int) -> list:
        """Load recent messages from chat_history via db_pool."""
        db = _CHAT_DB
        if not db:
            return []
        from storage.db_pool import get_pool
        with get_pool(db).get() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_history"
                " WHERE session_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        # Reverse so chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def _ensure_table(self, conn) -> None:
        """Create session_summaries table if it does not exist."""
        conn.execute(
            "CREATE TABLE IF NOT EXISTS session_summaries ("
            "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id  TEXT    NOT NULL,"
            "  summary     TEXT    NOT NULL,"
            "  turn_count  INTEGER NOT NULL,"
            "  created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ss_session"
            " ON session_summaries(session_id, id)"
        )

    def _store_episode(self, session_id: str, summary: str, turn_count: int) -> None:
        """
        1. Try to store in episodic memory via cognia.learn().
        2. Always store in session_summaries table (fallback / audit trail).
        """
        # Attempt episodic memory (best-effort)
        try:
            from cognia.cognia import Cognia
            cog = Cognia()
            cog.learn(summary, label=f"session_summary:{session_id}:{turn_count}")
        except Exception:
            pass

        # Fallback: session_summaries table — always executed
        db = _CHAT_DB
        if not db:
            return
        try:
            from storage.db_pool import get_pool
            with get_pool(db).get() as conn:
                self._ensure_table(conn)
                conn.execute(
                    "INSERT INTO session_summaries (session_id, summary, turn_count)"
                    " VALUES (?, ?, ?)",
                    (session_id, summary, turn_count),
                )
        except Exception:
            pass

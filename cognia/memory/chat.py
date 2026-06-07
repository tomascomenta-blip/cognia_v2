"""
cognia/memory/chat.py
=====================
Historial de conversación y perfil de usuario.
"""

from datetime import datetime
from ..database import db_connect
from ..config import DB_PATH


class ChatHistory:
    """
    Historial de conversación separado de episodic_memory.
    Las preguntas del chat NO contaminan la memoria episódica real.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        # Current session context. Set once at REPL startup via set_session();
        # log() then stamps every row (streaming, agent AND articulated paths,
        # since they all go through this same instance) so /resume can later
        # bring back a session by id or by the directory it ran in.
        self._session_id = None
        self._cwd = None

    def set_session(self, session_id: str, cwd: str):
        """Bind this instance to a session so all subsequent log() rows carry it."""
        self._session_id = session_id
        self._cwd = cwd

    def log(self, role: str, content: str, label_used: str = None,
            confidence: float = 0.0, response_id: str = None,
            session_id: str = None, cwd: str = None):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO chat_history
                (timestamp, role, content, label_used, confidence, response_id,
                 session_id, cwd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), role, content, label_used, confidence,
              response_id, session_id or self._session_id, cwd or self._cwd))
        conn.commit()
        conn.close()

    def add_feedback(self, response_id: str, feedback: int):
        """feedback: 1=correcto, -1=incorrecto, 0=neutro"""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("UPDATE chat_history SET feedback=? WHERE response_id=?", (feedback, response_id))
        conn.commit()
        conn.close()

    def get_recent(self, n: int = 10) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT role, content, label_used, confidence, feedback, timestamp
            FROM chat_history ORDER BY timestamp DESC LIMIT ?
        """, (n,))
        rows = [{"role": r[0], "content": r[1][:80], "label": r[2],
                 "confidence": r[3], "feedback": r[4], "ts": r[5]}
                for r in c.fetchall()]
        conn.close()
        return list(reversed(rows))

    def get_recent_turns(self, n: int = 20) -> list:
        """
        Full-content user/assistant turns for restoring conversation continuity
        across restarts (seeds the REPL's in-memory _history buffer).

        Unlike get_recent(), content is NOT truncated and only user/assistant
        roles are returned, in chronological (oldest-first) order. Ordered by id
        (monotonic autoincrement) rather than the textual timestamp so ties and
        clock quirks can't scramble turn order.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT role, content FROM chat_history
            WHERE role IN ('user', 'assistant')
            ORDER BY id DESC LIMIT ?
        """, (n,))
        rows = [{"role": r[0], "content": r[1]} for r in c.fetchall()]
        conn.close()
        return list(reversed(rows))

    def list_sessions(self, limit: int = 10, cwd: str = None) -> list:
        """
        Recent sessions (those with a session_id), newest activity first.
        If cwd is given, only sessions that ran in that directory (case-insensitive
        so Windows paths match). Each entry: session_id, cwd, count, first_ts,
        last_ts.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        if cwd:
            c.execute("""
                SELECT session_id, cwd, COUNT(*),
                       MIN(timestamp), MAX(timestamp)
                FROM chat_history
                WHERE session_id IS NOT NULL AND cwd = ? COLLATE NOCASE
                GROUP BY session_id
                ORDER BY MAX(id) DESC LIMIT ?
            """, (cwd, limit))
        else:
            c.execute("""
                SELECT session_id, cwd, COUNT(*),
                       MIN(timestamp), MAX(timestamp)
                FROM chat_history
                WHERE session_id IS NOT NULL
                GROUP BY session_id
                ORDER BY MAX(id) DESC LIMIT ?
            """, (limit,))
        rows = [{"session_id": r[0], "cwd": r[1], "count": r[2],
                 "first_ts": r[3], "last_ts": r[4]} for r in c.fetchall()]
        conn.close()
        return rows

    def latest_session_for_dir(self, cwd: str) -> str:
        """session_id of the most recent session that ran in cwd, or None."""
        rows = self.list_sessions(limit=1, cwd=cwd)
        return rows[0]["session_id"] if rows else None

    def resolve_session_prefix(self, prefix: str) -> str:
        """Most recent session_id whose id starts with prefix, or None."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT session_id FROM chat_history
            WHERE session_id LIKE ?
            GROUP BY session_id ORDER BY MAX(id) DESC LIMIT 1
        """, (prefix + "%",))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def get_session_turns(self, session_id: str, limit: int = 40) -> list:
        """
        The most recent user/assistant turns of one session, full content,
        chronological (oldest-first) -- for seeding _history on /resume.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT role, content FROM chat_history
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit))
        rows = [{"role": r[0], "content": r[1]} for r in c.fetchall()]
        conn.close()
        return list(reversed(rows))

    def get_frequent_topics(self, top_k: int = 5) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT label_used, COUNT(*) as freq
            FROM chat_history
            WHERE role='user' AND label_used IS NOT NULL
            GROUP BY label_used ORDER BY freq DESC LIMIT ?
        """, (top_k,))
        rows = [{"label": r[0], "freq": r[1]} for r in c.fetchall()]
        conn.close()
        return rows

    def count(self) -> int:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM chat_history")
        n = c.fetchone()[0]
        conn.close()
        return n


class UserProfile:
    """Perfil simple del usuario: nombre, idioma, estadísticas."""
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def set(self, key: str, value: str):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (key, value, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def get(self, key: str, default: str = None) -> str:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT value FROM user_profile WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default

    def get_all(self) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT key, value FROM user_profile")
        result = dict(c.fetchall())
        conn.close()
        return result

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

    def log(self, role: str, content: str, label_used: str = None,
            confidence: float = 0.0, response_id: str = None):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO chat_history (timestamp, role, content, label_used, confidence, response_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), role, content, label_used, confidence, response_id))
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

"""
cognia/profile/user_profile_builder.py
=======================================
Construye y persiste un perfil estadístico del usuario a partir del historial
de chat. Completamente determinista — sin LLM calls.

Tabla: user_profiles
  user_id       TEXT PRIMARY KEY
  top_topics    TEXT   -- JSON array [{term, count}]
  query_patterns TEXT  -- JSON array de strings
  message_count  INT
  avg_message_len REAL
  updated_at    TEXT   -- ISO datetime
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

_STOPWORDS = {
    # Español
    "el", "la", "los", "las", "un", "una", "de", "del", "al", "que", "en", "es",
    "se", "no", "por", "con", "su", "sus", "lo", "le", "les", "mas", "pero",
    "para", "como", "esta", "esto", "son", "tiene", "tiene", "hacer", "cual",
    "cuando", "donde", "sobre", "desde", "hasta", "entre", "cada", "otro",
    "otra", "este", "esta", "esos", "esas", "unos", "unas", "hay", "ser",
    # Inglés
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or",
    "it", "in", "on", "at", "for", "with", "this", "that", "he", "she", "we",
    "you", "i", "me", "my", "your", "can", "will", "be", "do", "did", "has",
    "have", "not", "from", "they", "them", "their", "what", "which", "who",
    "when", "where", "how", "all", "been", "had", "would", "could", "should",
    "more", "also", "just", "than", "then", "into", "about", "out", "up",
    "if", "its", "so", "but", "by", "as", "get", "use", "our",
}

# DB file used for user profiles — same file as desktop chat to keep things together
_PROFILE_DB = "cognia_desktop_chat.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id         TEXT PRIMARY KEY,
    top_topics      TEXT NOT NULL DEFAULT '[]',
    query_patterns  TEXT NOT NULL DEFAULT '[]',
    message_count   INTEGER NOT NULL DEFAULT 0,
    avg_message_len REAL NOT NULL DEFAULT 0.0,
    updated_at      TEXT NOT NULL
);
"""


def _ensure_schema(db_path: str) -> None:
    from storage.db_pool import get_pool
    with get_pool(db_path).get() as conn:
        conn.execute(_SCHEMA)


class UserProfileBuilder:
    """
    Construye perfil de usuario basado en análisis estadístico del historial de chat.
    Usa la tabla chat_history (role='user') y persiste en user_profiles.
    Sin LLM calls — análisis puramente determinista.
    """

    def __init__(self, db_path: str = _PROFILE_DB):
        self._db = db_path
        _ensure_schema(db_path)

    # ──────────────────────────────────────────────────────────────────────
    # ANÁLISIS
    # ──────────────────────────────────────────────────────────────────────

    def build_profile(self, session_id: str = None, limit: int = 200) -> dict:
        """
        Analiza últimos `limit` mensajes del usuario (role='user').
        Si session_id se provee, filtra solo esa sesión.
        Retorna perfil como dict con keys:
          top_topics, query_patterns, message_count, avg_message_len, dominant_language
        """
        messages = self._load_messages(session_id=session_id, limit=limit)

        if not messages:
            return {
                "top_topics": [],
                "query_patterns": [],
                "message_count": 0,
                "avg_message_len": 0.0,
                "dominant_language": "unknown",
            }

        all_terms: list[str] = []
        for msg in messages:
            all_terms.extend(self._extract_terms(msg))

        term_counts = Counter(all_terms)
        top_topics = [
            {"term": term, "count": count}
            for term, count in term_counts.most_common(20)
        ]

        total_len = sum(len(m) for m in messages)
        avg_len = total_len / len(messages)

        return {
            "top_topics": top_topics,
            "query_patterns": self._detect_patterns(messages),
            "message_count": len(messages),
            "avg_message_len": round(avg_len, 2),
            "dominant_language": self._detect_language(messages),
        }

    def _load_messages(self, session_id: str = None, limit: int = 200) -> list[str]:
        """Carga últimos `limit` mensajes de role='user' desde chat_history."""
        try:
            from storage.db_pool import get_pool
            with get_pool(self._db).get() as conn:
                if session_id:
                    rows = conn.execute(
                        "SELECT content FROM chat_history "
                        "WHERE role = ? AND session_id = ? "
                        "ORDER BY ts DESC LIMIT ?",
                        ("user", session_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT content FROM chat_history "
                        "WHERE role = ? "
                        "ORDER BY ts DESC LIMIT ?",
                        ("user", limit),
                    ).fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []

    def _extract_terms(self, text: str) -> list[str]:
        """Tokeniza, lowercases, filtra stopwords y tokens < 4 chars."""
        # Accept letters including accented characters
        tokens = re.findall(r'\b[a-z\u00e0-\u00fc]{4,}\b', text.lower())
        return [t for t in tokens if t not in _STOPWORDS]

    def _detect_patterns(self, messages: list[str]) -> list[str]:
        """Detecta patrones de consulta en la lista de mensajes."""
        patterns: set[str] = set()
        for m in messages:
            ml = m.lower()
            if any(w in ml for w in ["c\u00f3mo", "como", "how"]):
                patterns.add("asks_how")
            if any(w in ml for w in ["qu\u00e9", "que", "what", "what's"]):
                patterns.add("asks_what")
            if any(w in ml for w in ["c\u00f3digo", "code", "python", "function", "def ", "class ", "import"]):
                patterns.add("asks_code")
            if any(w in ml for w in ["por qu\u00e9", "porque", "why"]):
                patterns.add("asks_why")
            if any(w in ml for w in ["lista", "list", "enumera", "cu\u00e1les", "cuales"]):
                patterns.add("asks_list")
        return sorted(patterns)

    def _detect_language(self, messages: list[str]) -> str:
        """Detecta idioma dominante: 'es', 'en', o 'mixed'."""
        text = " ".join(messages).lower()
        es_signals = len(re.findall(
            r'\b(qu\u00e9|c\u00f3mo|esto|para|tambi\u00e9n|pero)\b', text
        ))
        en_signals = len(re.findall(
            r'\b(what|how|this|also|but|the)\b', text
        ))
        if es_signals > en_signals * 1.5:
            return "es"
        elif en_signals > es_signals * 1.5:
            return "en"
        return "mixed"

    # ──────────────────────────────────────────────────────────────────────
    # PERSISTENCIA
    # ──────────────────────────────────────────────────────────────────────

    def save_profile(self, user_id: str, profile: dict) -> None:
        """Upsert del perfil en user_profiles via db_pool."""
        from storage.db_pool import get_pool
        now = datetime.now(timezone.utc).isoformat()
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles
                    (user_id, top_topics, query_patterns, message_count, avg_message_len, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    top_topics      = excluded.top_topics,
                    query_patterns  = excluded.query_patterns,
                    message_count   = excluded.message_count,
                    avg_message_len = excluded.avg_message_len,
                    updated_at      = excluded.updated_at
                """,
                (
                    user_id,
                    json.dumps(profile.get("top_topics", []), ensure_ascii=False),
                    json.dumps(profile.get("query_patterns", []), ensure_ascii=False),
                    profile.get("message_count", 0),
                    profile.get("avg_message_len", 0.0),
                    now,
                ),
            )

    def get_profile(self, user_id: str) -> Optional[dict]:
        """Carga perfil de BD. Retorna None si no existe."""
        try:
            from storage.db_pool import get_pool
            with get_pool(self._db).get() as conn:
                row = conn.execute(
                    "SELECT top_topics, query_patterns, message_count, avg_message_len, updated_at "
                    "FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            if row is None:
                return None
            return {
                "top_topics": json.loads(row[0]),
                "query_patterns": json.loads(row[1]),
                "message_count": row[2],
                "avg_message_len": row[3],
                "updated_at": row[4],
            }
        except Exception:
            return None

    def get_profile_context(self, user_id: str) -> str:
        """
        Retorna string corto inyectable en contexto del LLM.
        Formato: "Perfil del usuario: intereses en [python, fastapi]; patrones: [asks_code, asks_how]"
        Retorna "" si no hay perfil.
        """
        profile = self.get_profile(user_id)
        if not profile:
            return ""

        top = profile.get("top_topics", [])
        if top:
            terms = ", ".join(t["term"] for t in top[:5])
            interests = f"intereses en [{terms}]"
        else:
            interests = "sin intereses detectados"

        patterns = profile.get("query_patterns", [])
        patterns_str = f"[{', '.join(patterns)}]" if patterns else "[]"

        return f"Perfil del usuario: {interests}; patrones: {patterns_str}"

"""
cognia/adaptive/style_engine.py
"""

import time
import re
from storage.db_pool import get_pool

_CASUAL_TOKENS = re.compile(
    r'\b(lol|btw|idk|ok|haha|jaja|hey)\b', re.IGNORECASE
)
_FORMAL_TOKENS = re.compile(
    r'(please|could you|would you|i would like|kindly|por favor)', re.IGNORECASE
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS style_profile (
    user_id TEXT PRIMARY KEY,
    avg_user_msg_len REAL DEFAULT 0,
    avg_assistant_msg_len REAL DEFAULT 0,
    formality_score REAL DEFAULT 0.5,
    detail_score REAL DEFAULT 0.5,
    turn_count INTEGER DEFAULT 0,
    last_updated REAL DEFAULT 0
)
"""


class StyleEngine:
    """
    Learns user communication preferences from conversation history.
    Signals injected into system prompt to guide response style.
    """

    def __init__(self, db_path: str, user_id: str = "local"):
        self._db_path = db_path
        self._user_id = user_id
        with get_pool(db_path).get() as conn:
            conn.execute(_SCHEMA)

    def _load(self, conn) -> dict:
        row = conn.execute(
            "SELECT avg_user_msg_len, avg_assistant_msg_len, formality_score, "
            "detail_score, turn_count, last_updated FROM style_profile WHERE user_id = ?",
            (self._user_id,),
        ).fetchone()
        if row is None:
            return {
                "avg_user_msg_len": 0.0,
                "avg_assistant_msg_len": 0.0,
                "formality_score": 0.5,
                "detail_score": 0.5,
                "turn_count": 0,
                "last_updated": 0.0,
            }
        return {
            "avg_user_msg_len": row[0],
            "avg_assistant_msg_len": row[1],
            "formality_score": row[2],
            "detail_score": row[3],
            "turn_count": row[4],
            "last_updated": row[5],
        }

    def _save(self, conn, profile: dict) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO style_profile "
            "(user_id, avg_user_msg_len, avg_assistant_msg_len, formality_score, "
            "detail_score, turn_count, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self._user_id,
                profile["avg_user_msg_len"],
                profile["avg_assistant_msg_len"],
                profile["formality_score"],
                profile["detail_score"],
                profile["turn_count"],
                profile["last_updated"],
            ),
        )

    def record_exchange(self, user_msg: str, assistant_msg: str) -> None:
        """Record a conversation turn and update style profile."""
        u_len = len(user_msg)
        a_len = len(assistant_msg)

        with get_pool(self._db_path).get() as conn:
            p = self._load(conn)
            n = p["turn_count"]

            # Running average capped at 20 recent turns (EMA-like for old data)
            weight = min(n, 20)
            if weight == 0:
                p["avg_user_msg_len"] = float(u_len)
                p["avg_assistant_msg_len"] = float(a_len)
            else:
                p["avg_user_msg_len"] = (p["avg_user_msg_len"] * weight + u_len) / (weight + 1)
                p["avg_assistant_msg_len"] = (p["avg_assistant_msg_len"] * weight + a_len) / (weight + 1)

            # Formality: EMA signal
            has_casual = bool(_CASUAL_TOKENS.search(user_msg))
            has_formal = bool(_FORMAL_TOKENS.search(user_msg))
            if has_casual and not has_formal:
                signal = 0.0
            elif has_formal and not has_casual:
                signal = 1.0
            else:
                signal = 0.5  # neutral or mixed — no strong pull
            p["formality_score"] = 0.9 * p["formality_score"] + 0.1 * signal

            # Detail preference
            has_question = "?" in user_msg
            if has_question:
                p["detail_score"] = min(1.0, p["detail_score"] + 0.1)
            elif u_len < 30 and p["avg_assistant_msg_len"] > 200:
                # terse follow-up after a long response — user had enough
                p["detail_score"] = max(0.0, p["detail_score"] - 0.1)

            p["turn_count"] = n + 1
            p["last_updated"] = time.time()
            self._save(conn, p)

    def get_style_hint(self) -> str:
        """Return a short ASCII string to inject into system prompt. Empty string if no data yet."""
        with get_pool(self._db_path).get() as conn:
            p = self._load(conn)

        if p["turn_count"] < 5:
            return ""

        avg_len = p["avg_user_msg_len"]
        if avg_len < 30:
            length_word = "brief"
        elif avg_len <= 150:
            length_word = "moderate"
        else:
            length_word = "detailed"

        fs = p["formality_score"]
        if fs > 0.6:
            formality_word = "formal"
        elif fs < 0.4:
            formality_word = "casual"
        else:
            formality_word = "neutral"

        detail_word = "high-detail" if p["detail_score"] > 0.6 else "concise"

        return f"Style: {length_word}, {formality_word}, {detail_word}"

    def get_profile(self) -> dict:
        """Return current style profile as dict for API/debugging."""
        with get_pool(self._db_path).get() as conn:
            return self._load(conn)

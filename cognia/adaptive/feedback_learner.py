# Learns from implicit and explicit user signals to improve response quality
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH = str(Path(__file__).parent.parent.parent / "cognia_feedback.db")

_POSITIVE_WORDS = frozenset([
    "gracias", "perfecto", "exacto", "bien", "genial",
    "thanks", "perfect", "great", "exactly",
])
_NEGATIVE_WORDS = frozenset([
    "no", "mal", "incorrecto", "wrong", "error", "equivocado",
    "intenta de nuevo", "try again", "no entendiste",
])
# Multi-word negatives checked separately
_NEGATIVE_PHRASES = ("intenta de nuevo", "try again", "no entendiste")


class FeedbackLearner:
    def __init__(self, db_path: str = _DB_PATH) -> None:
        self._db = db_path
        self._setup_db()

    def _setup_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS response_feedback ("
                "  id INTEGER PRIMARY KEY,"
                "  message_id TEXT,"
                "  signal TEXT CHECK(signal IN ('positive','negative','neutral')),"
                "  query_type TEXT,"
                "  ts REAL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS query_type_stats ("
                "  query_type TEXT PRIMARY KEY,"
                "  pos_count INTEGER DEFAULT 0,"
                "  neg_count INTEGER DEFAULT 0,"
                "  last_updated REAL"
                ")"
            )

    def record(self, message_id: str, signal: str, query_type: str = "general") -> None:
        if signal not in ("positive", "negative", "neutral"):
            signal = "neutral"
        ts = time.time()
        with get_pool(self._db).get() as conn:
            conn.execute(
                "INSERT INTO response_feedback (message_id, signal, query_type, ts) VALUES (?,?,?,?)",
                (message_id, signal, query_type, ts),
            )
            if signal == "positive":
                conn.execute(
                    "INSERT INTO query_type_stats (query_type, pos_count, neg_count, last_updated)"
                    " VALUES (?,1,0,?)"
                    " ON CONFLICT(query_type) DO UPDATE SET"
                    "   pos_count=pos_count+1, last_updated=excluded.last_updated",
                    (query_type, ts),
                )
            elif signal == "negative":
                conn.execute(
                    "INSERT INTO query_type_stats (query_type, pos_count, neg_count, last_updated)"
                    " VALUES (?,0,1,?)"
                    " ON CONFLICT(query_type) DO UPDATE SET"
                    "   neg_count=neg_count+1, last_updated=excluded.last_updated",
                    (query_type, ts),
                )

    def detect_signal(self, user_text: str) -> str:
        import re as _re
        text_lower = user_text.lower()
        # Multi-word phrase check first
        for phrase in _NEGATIVE_PHRASES:
            if phrase in text_lower:
                return "negative"
        # Strip punctuation before word-boundary split
        words = _re.sub(r"[^\w\s]", " ", text_lower).split()
        word_set = set(words)
        if word_set & _POSITIVE_WORDS:
            return "positive"
        if word_set & _NEGATIVE_WORDS:
            return "negative"
        return "neutral"

    def get_adjustment_hint(self, query_type: str) -> str:
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT pos_count, neg_count FROM query_type_stats WHERE query_type=?",
                (query_type,),
            ).fetchone()
        if row is None:
            return ""
        pos, neg = row[0], row[1]
        total = pos + neg
        if total < 5:
            return ""
        pos_rate = pos / total
        neg_rate = neg / total
        if pos_rate > 0.7:
            return f"Continue with current approach for {query_type} queries."
        if neg_rate > 0.5:
            return (
                f"User has found {query_type} responses unsatisfactory"
                " -- be more precise and concise."
            )
        return ""

    def get_stats(self) -> dict:
        with get_pool(self._db).get() as conn:
            total = conn.execute("SELECT COUNT(*) FROM response_feedback").fetchone()[0]
            positive = conn.execute(
                "SELECT COUNT(*) FROM response_feedback WHERE signal='positive'"
            ).fetchone()[0]
            negative = conn.execute(
                "SELECT COUNT(*) FROM response_feedback WHERE signal='negative'"
            ).fetchone()[0]
            top_pos = [
                row[0]
                for row in conn.execute(
                    "SELECT query_type FROM query_type_stats ORDER BY pos_count DESC LIMIT 5"
                ).fetchall()
            ]
            top_neg = [
                row[0]
                for row in conn.execute(
                    "SELECT query_type FROM query_type_stats ORDER BY neg_count DESC LIMIT 5"
                ).fetchall()
            ]
        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "top_positive_types": top_pos,
            "top_negative_types": top_neg,
        }

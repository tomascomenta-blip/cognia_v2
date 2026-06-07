"""
curiosity_engine.py — CuriosityEngine
======================================
Genera preguntas de "lo que no sé" cuando Cognia tiene baja confianza
(confidence < 0.4) y las encola en BD para investigación en background.

Tabla: curiosity_queue (cognia_curiosity.db)
  id INTEGER PK AUTOINCREMENT
  question TEXT NOT NULL
  source_prompt_hash TEXT NOT NULL
  status TEXT NOT NULL  -- 'pending' | 'answered' | 'failed'
  created_at INTEGER NOT NULL
  answered_at INTEGER
  answer TEXT
"""

import hashlib
import time
from typing import List, Optional

from storage.db_pool import get_pool

_DB_PATH = "cognia_curiosity.db"
_CONFIDENCE_THRESHOLD = 0.4
_MIN_KEYWORD_LEN = 4
_MAX_QUESTIONS = 2

_STOPWORDS = frozenset({
    "como", "como", "cual", "cuál", "que", "qué", "quien", "quién",
    "cuando", "cuándo", "donde", "dónde", "por", "para", "con", "sin",
    "una", "uno", "los", "las", "del", "the", "what", "how", "why",
    "who", "when", "where", "is", "are", "was", "were", "does", "did",
    "can", "could", "would", "should", "have", "has", "had",
})


def _init_db(db_path: str) -> None:
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS curiosity_queue ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  question TEXT NOT NULL,"
            "  source_prompt_hash TEXT NOT NULL,"
            "  status TEXT NOT NULL DEFAULT 'pending',"
            "  created_at INTEGER NOT NULL,"
            "  answered_at INTEGER,"
            "  answer TEXT"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cq_status "
            "ON curiosity_queue(status, created_at)"
        )


class CuriosityEngine:
    def __init__(self, db_path: str = _DB_PATH):
        self._db = db_path
        _init_db(self._db)

    # ── Keyword extraction ─────────────────────────────────────────────

    def _extract_keywords(self, text: str) -> List[str]:
        tokens = text.lower().split()
        seen: set = set()
        keywords: List[str] = []
        for tok in tokens:
            # Strip punctuation
            clean = "".join(c for c in tok if c.isalnum())
            if (
                len(clean) >= _MIN_KEYWORD_LEN
                and clean not in _STOPWORDS
                and clean not in seen
            ):
                seen.add(clean)
                keywords.append(clean)
        return keywords

    # ── Question generation ────────────────────────────────────────────

    def generate_questions(
        self, prompt: str, response: str, confidence: float
    ) -> List[str]:
        """Return up to 2 curiosity questions; empty list if confidence >= 0.4."""
        if confidence >= _CONFIDENCE_THRESHOLD:
            return []

        keywords = self._extract_keywords(prompt)
        if not keywords:
            return []

        questions: List[str] = []
        templates = [
            "¿Qué no entiendo sobre {kw}?",
            "¿Cuál es el estado del arte en {kw}?",
        ]
        for i, kw in enumerate(keywords[:_MAX_QUESTIONS]):
            questions.append(templates[i % len(templates)].format(kw=kw))

        return questions[:_MAX_QUESTIONS]

    # ── Queue operations ──────────────────────────────────────────────

    def enqueue(self, questions: List[str], source_prompt: str) -> None:
        """Insert pending questions. No-op if questions is empty."""
        if not questions:
            return
        prompt_hash = hashlib.sha256(source_prompt.encode("utf-8")).hexdigest()[:16]
        now = int(time.time())
        with get_pool(self._db).get() as conn:
            conn.executemany(
                "INSERT INTO curiosity_queue "
                "(question, source_prompt_hash, status, created_at) "
                "VALUES (?, ?, 'pending', ?)",
                [(q, prompt_hash, now) for q in questions],
            )

    def get_pending(self, limit: int = 5) -> List[dict]:
        """Return oldest pending questions."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, question, source_prompt_hash, created_at "
                "FROM curiosity_queue "
                "WHERE status = 'pending' "
                "ORDER BY created_at ASC "
                "LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "question": r[1],
                "source_prompt_hash": r[2],
                "created_at": r[3],
            }
            for r in rows
        ]

    def mark_answered(self, question_id: int, answer: str) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "UPDATE curiosity_queue "
                "SET status = 'answered', answered_at = ?, answer = ? "
                "WHERE id = ?",
                (int(time.time()), answer, question_id),
            )

    def mark_failed(self, question_id: int) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "UPDATE curiosity_queue SET status = 'failed' WHERE id = ?",
                (question_id,),
            )

    def get_insights(self, limit: int = 10) -> List[dict]:
        """Return most recent answered questions for use as context."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id, question, answer, answered_at "
                "FROM curiosity_queue "
                "WHERE status = 'answered' "
                "ORDER BY answered_at DESC "
                "LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "question": r[1],
                "answer": r[2],
                "answered_at": r[3],
            }
            for r in rows
        ]

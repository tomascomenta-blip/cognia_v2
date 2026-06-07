"""
cognia/learning/quiz_generator.py
===================================
QuizGenerator -- generates quiz questions from KG facts and SR cards without LLM calls.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH: Optional[str] = None  # injected by cognia_desktop_api.py at startup
_KG_DB_PATH: Optional[str] = None  # KG lives in cognia_memory.db (cognia.config.DB_PATH)


def _get_db() -> str:
    if _DB_PATH:
        return _DB_PATH
    return "cognia_quiz.db"


def _get_kg_db() -> str:
    if _KG_DB_PATH:
        return _KG_DB_PATH
    try:
        from cognia.config import DB_PATH
        return DB_PATH
    except Exception:
        return "cognia_memory.db"


class QuizGenerator:
    def __init__(self, db_path: Optional[str] = None, kg_db_path: Optional[str] = None) -> None:
        self._db = db_path or _get_db()
        self._kg_db = kg_db_path or _get_kg_db()
        self._init_db()

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS quiz_results ("
                "  id INTEGER PRIMARY KEY,"
                "  question TEXT NOT NULL,"
                "  answer TEXT NOT NULL,"
                "  user_answer TEXT NOT NULL,"
                "  correct INTEGER NOT NULL,"
                "  source TEXT NOT NULL DEFAULT 'quiz',"
                "  ts REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quiz_source ON quiz_results(source)"
            )

    def generate_from_kg(self, topic: Optional[str] = None, limit: int = 5) -> list[dict]:
        """Query knowledge_graph facts and build questions. Returns list of question dicts."""
        try:
            if topic:
                query = (
                    "SELECT subject, predicate, object FROM knowledge_graph "
                    "WHERE subject LIKE ? ORDER BY weight DESC LIMIT ?"
                )
                params = (f"%{topic}%", limit)
            else:
                query = (
                    "SELECT subject, predicate, object FROM knowledge_graph "
                    "ORDER BY weight DESC LIMIT ?"
                )
                params = (limit,)

            with get_pool(self._kg_db).get() as conn:
                rows = conn.execute(query, params).fetchall()
        except Exception:
            return []

        questions = []
        for subject, predicate, obj in rows:
            # Alternate between two question templates
            if len(questions) % 2 == 0:
                questions.append({
                    "id": None,
                    "question": f"Cual es la relacion de '{subject}' con '{obj}'?",
                    "answer": predicate,
                    "source": "kg",
                    "subject": subject,
                })
            else:
                questions.append({
                    "id": None,
                    "question": f"Que '{predicate}' tiene '{subject}'?",
                    "answer": obj,
                    "source": "kg",
                    "subject": subject,
                })
        return questions

    def generate_from_sr(self, limit: int = 5) -> list[dict]:
        """Query sr_cards and build questions from front/back. Returns list of question dicts."""
        try:
            with get_pool(self._db).get() as conn:
                rows = conn.execute(
                    "SELECT front, back, topic FROM sr_cards LIMIT ?",
                    (limit,),
                ).fetchall()
        except Exception:
            return []

        return [
            {
                "question": front,
                "answer": back,
                "source": "sr",
                "topic": topic,
            }
            for front, back, topic in rows
        ]

    def generate_mixed(self, topic: Optional[str] = None, limit: int = 10) -> list[dict]:
        """Combine KG and SR questions, shuffled."""
        half = max(1, limit // 2)
        kg_qs = self.generate_from_kg(topic=topic, limit=half)
        sr_qs = self.generate_from_sr(limit=half)
        combined = kg_qs + sr_qs
        random.shuffle(combined)
        return combined

    def record_answer(
        self,
        question: str,
        answer: str,
        user_answer: str,
        source: str = "quiz",
    ) -> bool:
        """Insert result into quiz_results. Returns True if user_answer matches answer."""
        correct = int(user_answer.lower().strip() == answer.lower().strip())
        with get_pool(self._db).get() as conn:
            conn.execute(
                "INSERT INTO quiz_results (question, answer, user_answer, correct, source, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (question, answer, user_answer, correct, source, time.time()),
            )
        return bool(correct)

    def get_stats(self) -> dict:
        """Return aggregate accuracy stats."""
        with get_pool(self._db).get() as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(correct) FROM quiz_results"
            ).fetchone()
            total = row[0] or 0
            correct_total = int(row[1] or 0)

            by_source: dict[str, dict] = {}
            rows = conn.execute(
                "SELECT source, COUNT(*), SUM(correct) FROM quiz_results GROUP BY source"
            ).fetchall()
            for src, cnt, corr in rows:
                by_source[src] = {"correct": int(corr or 0), "total": cnt}

        accuracy = round(correct_total / total, 4) if total > 0 else 0.0
        return {
            "total_attempts": total,
            "correct": correct_total,
            "accuracy": accuracy,
            "by_source": by_source,
        }

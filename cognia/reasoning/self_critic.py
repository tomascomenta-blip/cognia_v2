"""
self_critic.py -- Heuristic response quality scorer and self-critique engine.
No LLM calls. Pure deterministic analysis stored in SQLite via db_pool.
"""

import hashlib
import re
import time
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH = "cognia_desktop_chat.db"
_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS response_critiques (
    id INTEGER PRIMARY KEY,
    response_hash TEXT UNIQUE,
    critique TEXT,
    length_score REAL,
    clarity_score REAL,
    completeness_score REAL,
    overall_score REAL,
    ts REAL
)
"""
_RETENTION_DAYS = 30
_PRUNE_EVERY_N  = 50   # prune once every N critique() calls to avoid per-call overhead


class SelfCritic:
    def __init__(self, db_path: str = _DB_PATH) -> None:
        self._db_path   = db_path
        self._call_count = 0
        with get_pool(self._db_path).get() as conn:
            conn.execute(_TABLE_DDL)

    def _prune_old_records(self) -> None:
        cutoff = time.time() - _RETENTION_DAYS * 86400
        try:
            with get_pool(self._db_path).get() as conn:
                conn.execute(
                    "DELETE FROM response_critiques WHERE ts < ?", (cutoff,)
                )
        except Exception:
            pass

    # ── scoring helpers ───────────────────────────────────────────────────

    def _hash(self, text: str) -> str:
        return hashlib.md5(text[:500].encode("utf-8", errors="replace")).hexdigest()

    def _score_length(self, text: str) -> float:
        n = len(text)
        if n < 50:
            return 0.3
        if n < 100:
            return 0.6
        if n <= 800:
            return 1.0
        if n <= 2000:
            return 0.8
        return 0.5

    def _score_clarity(self, text: str) -> float:
        score = 0.0
        # has_sentences: ends with . ? or !
        if re.search(r"[.?!]\s*$", text.strip()):
            score += 0.3
        # no_excessive_caps: less than 20% uppercase alpha chars
        alpha = [c for c in text if c.isalpha()]
        if alpha:
            upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
            if upper_ratio < 0.20:
                score += 0.3
        else:
            score += 0.3  # no alpha — treat as OK
        # varied_vocabulary: unique_words/total_words > 0.4
        words = re.findall(r"\w+", text.lower())
        if words:
            if len(set(words)) / len(words) > 0.4:
                score += 0.4
        else:
            score += 0.4  # no words — treat as OK
        return round(score, 4)

    def _score_completeness(self, text: str, question: str = "") -> float:
        if not question:
            return 0.7
        if "?" in question and len(text) > 50:
            # check word overlap
            q_words = set(re.findall(r"\w+", question.lower()))
            r_words = set(re.findall(r"\w+", text.lower()))
            if q_words:
                overlap = len(q_words & r_words) / len(q_words)
                if overlap > 0.30:
                    return 1.0
            return 0.8
        return 0.6

    def _generate_critique(
        self, length_s: float, clarity_s: float, completeness_s: float
    ) -> str:
        overall = round((length_s + clarity_s + completeness_s) / 3, 4)
        if overall < 0.5:
            return "La respuesta podria ser mas completa y clara."
        if length_s < 0.6:
            return "La respuesta es demasiado corta o larga para el contexto."
        if clarity_s < 0.6:
            return "La respuesta podria mejorar en claridad y variedad de vocabulario."
        if completeness_s < 0.7:
            return "La respuesta no aborda completamente la pregunta planteada."
        return "La respuesta es adecuada."

    # ── public API ────────────────────────────────────────────────────────

    def critique(self, response: str, question: str = "") -> dict:
        self._call_count += 1
        if self._call_count % _PRUNE_EVERY_N == 0:
            self._prune_old_records()

        length_s = self._score_length(response)
        clarity_s = self._score_clarity(response)
        completeness_s = self._score_completeness(response, question)
        overall = round((length_s + clarity_s + completeness_s) / 3, 4)
        critique_text = self._generate_critique(length_s, clarity_s, completeness_s)
        h = self._hash(response)
        try:
            with get_pool(self._db_path).get() as conn:
                conn.execute(_TABLE_DDL)
                conn.execute(
                    "INSERT OR IGNORE INTO response_critiques "
                    "(response_hash, critique, length_score, clarity_score, "
                    "completeness_score, overall_score, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (h, critique_text, length_s, clarity_s, completeness_s, overall, time.time()),
                )
        except Exception:
            pass
        return {
            "critique": critique_text,
            "scores": {
                "length": length_s,
                "clarity": clarity_s,
                "completeness": completeness_s,
                "overall": overall,
            },
        }

    def get_recent_critiques(self, limit: int = 5) -> list:
        try:
            with get_pool(self._db_path).get() as conn:
                conn.execute(_TABLE_DDL)
                rows = conn.execute(
                    "SELECT id, response_hash, critique, length_score, clarity_score, "
                    "completeness_score, overall_score, ts "
                    "FROM response_critiques ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "id": r[0],
                    "response_hash": r[1],
                    "critique": r[2],
                    "length_score": r[3],
                    "clarity_score": r[4],
                    "completeness_score": r[5],
                    "overall_score": r[6],
                    "ts": r[7],
                }
                for r in rows
            ]
        except Exception:
            return []

    def get_avg_score(self, days: int = 7) -> float:
        cutoff = time.time() - days * 86400
        try:
            with get_pool(self._db_path).get() as conn:
                conn.execute(_TABLE_DDL)
                row = conn.execute(
                    "SELECT AVG(overall_score) FROM response_critiques WHERE ts >= ?",
                    (cutoff,),
                ).fetchone()
            if row and row[0] is not None:
                return round(float(row[0]), 4)
        except Exception:
            pass
        return 0.0

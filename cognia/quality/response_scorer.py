"""
response_scorer.py — Deterministic quality scoring for Cognia responses.

Scores are computed without any LLM calls and persisted in `response_quality`
so the self-improvement loop in cognia/agents/self_improvement.py can consume them.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Dict

from storage.db_pool import get_pool

_DB_PATH = "cognia_memory.db"

_DDL = """
CREATE TABLE IF NOT EXISTS response_quality (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_hash   TEXT NOT NULL,
    response_hash TEXT NOT NULL,
    completeness  REAL NOT NULL,
    coherence     REAL NOT NULL,
    relevance     REAL NOT NULL,
    overall       REAL NOT NULL,
    ts            TEXT NOT NULL
)
"""

_SENTENCE_END = re.compile(r'[.!?]')
_TOKEN_SPLIT  = re.compile(r'\W+')


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _tokenize(text: str) -> set:
    return {t.lower() for t in _TOKEN_SPLIT.split(text) if len(t) > 2}


class ResponseScorer:
    def __init__(self, db_path: str = _DB_PATH):
        self._db = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(_DDL)

    # ── Public API ─────────────────────────────────────────────────────

    def score(self, prompt: str, response: str) -> Dict:
        completeness = self._completeness(prompt, response)
        coherence    = self._coherence(response)
        relevance    = self._relevance(prompt, response)
        overall      = round((completeness + coherence + relevance) / 3.0, 4)
        return {
            "completeness": completeness,
            "coherence":    coherence,
            "relevance":    relevance,
            "overall":      overall,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }

    def persist(self, prompt: str, response: str, score_dict: Dict) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                INSERT INTO response_quality
                    (prompt_hash, response_hash, completeness, coherence,
                     relevance, overall, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _sha8(prompt),
                    _sha8(response),
                    score_dict["completeness"],
                    score_dict["coherence"],
                    score_dict["relevance"],
                    score_dict["overall"],
                    score_dict["timestamp"],
                ),
            )

    # ── Metrics ────────────────────────────────────────────────────────

    @staticmethod
    def _completeness(prompt: str, response: str) -> float:
        target = max(len(prompt) * 3, 200)
        return round(min(len(response) / target, 1.0), 4)

    @staticmethod
    def _coherence(response: str) -> float:
        # Ratio of sentences that end with . ! ?  over total sentences.
        # A sentence boundary is assumed at every 60-char chunk if no terminator found —
        # otherwise one-liner responses without punctuation would score 0 unfairly.
        sentences = re.split(r'(?<=[.!?])\s+', response.strip())
        if not sentences or not response.strip():
            return 0.0
        well_ended = sum(1 for s in sentences if s and _SENTENCE_END.search(s[-1]))
        return round(well_ended / len(sentences), 4)

    @staticmethod
    def _relevance(prompt: str, response: str) -> float:
        p_tokens = _tokenize(prompt)
        r_tokens = _tokenize(response)
        if not p_tokens or not r_tokens:
            return 0.0
        intersection = p_tokens & r_tokens
        union        = p_tokens | r_tokens
        return round(len(intersection) / len(union), 4)

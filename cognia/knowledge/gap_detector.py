"""
gap_detector.py -- Knowledge Gap Auto-Detector (KGAD) — Phase 60

Records knowledge gaps when responses are low quality (score < QUALITY_THRESHOLD).
Enqueues gap topics into CuriosityEngine for future background research.
Closes the self-improvement loop: Cognia learns what it doesn't know.

Table: knowledge_gaps
  id INTEGER PK AUTOINCREMENT
  topic TEXT NOT NULL
  question TEXT NOT NULL
  quality_score REAL NOT NULL
  timestamp REAL NOT NULL
  resolved INTEGER DEFAULT 0
"""

import time
from typing import Optional

from storage.db_pool import get_pool

_QUESTION_WORDS = frozenset({
    "what", "how", "why", "when", "where", "who",
    "is", "are", "do", "does", "can",
})

_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
})


def _init_db(db_path: str) -> None:
    with get_pool(db_path).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_gaps ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  topic TEXT NOT NULL,"
            "  question TEXT NOT NULL,"
            "  quality_score REAL NOT NULL,"
            "  timestamp REAL NOT NULL,"
            "  resolved INTEGER DEFAULT 0"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kg_topic_ts "
            "ON knowledge_gaps(topic, timestamp)"
        )


class KnowledgeGapDetector:
    """
    Records knowledge gaps when responses are low quality.
    Enqueues gap topics into CuriosityEngine for future research.
    """

    QUALITY_THRESHOLD = 0.4
    MAX_GAPS_PER_DAY = 10

    def __init__(self, db_path: str, curiosity_engine=None):
        self._db = db_path
        self._curiosity_engine = curiosity_engine
        _init_db(self._db)

    # ── Topic extraction ──────────────────────────────────────────────

    def _extract_topic(self, query: str) -> str:
        """Extract main topic from query (2-4 word noun phrase). Pure heuristic."""
        tokens = query.lower().split()
        filtered = []
        for tok in tokens:
            clean = "".join(c for c in tok if c.isalnum())
            if not clean:
                continue
            if clean in _QUESTION_WORDS or clean in _STOP_WORDS:
                continue
            filtered.append(clean)
        if not filtered:
            return query[:30]
        return " ".join(filtered[:3])

    # ── Core logic ────────────────────────────────────────────────────

    def maybe_record_gap(
        self, query: str, response: str, quality_score: float
    ) -> bool:
        """
        If quality_score < QUALITY_THRESHOLD, extract topic from query,
        record gap in DB, and enqueue in curiosity_engine.
        Returns True if gap was recorded.
        """
        if quality_score >= self.QUALITY_THRESHOLD:
            return False

        topic = self._extract_topic(query)
        now = time.time()
        day_start = now - 86400.0  # 24-hour window

        with get_pool(self._db).get() as conn:
            # Check daily cap
            row = conn.execute(
                "SELECT COUNT(*) FROM knowledge_gaps WHERE timestamp >= ?",
                (day_start,),
            ).fetchone()
            if row and row[0] >= self.MAX_GAPS_PER_DAY:
                return False

            # Deduplicate by topic in 24h window
            dup = conn.execute(
                "SELECT id FROM knowledge_gaps "
                "WHERE topic = ? AND timestamp >= ?",
                (topic, day_start),
            ).fetchone()
            if dup:
                return False

            question = f"What do you know about {topic}?"
            conn.execute(
                "INSERT INTO knowledge_gaps "
                "(topic, question, quality_score, timestamp, resolved) "
                "VALUES (?, ?, ?, ?, 0)",
                (topic, question, quality_score, now),
            )

        if self._curiosity_engine is not None:
            try:
                self._curiosity_engine.enqueue([question], query)
            except Exception:
                pass  # enqueue failure never blocks gap recording

        return True

    # ── Query API ─────────────────────────────────────────────────────

    def get_gaps(self, limit: int = 20) -> list:
        """Return recent gaps: [{topic, question, quality_score, timestamp, resolved}]"""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT topic, question, quality_score, timestamp, resolved "
                "FROM knowledge_gaps "
                "ORDER BY timestamp DESC "
                "LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "topic": r[0],
                "question": r[1],
                "quality_score": r[2],
                "timestamp": r[3],
                "resolved": bool(r[4]),
            }
            for r in rows
        ]

    def mark_resolved(self, topic: str) -> None:
        """Mark a gap as resolved when new facts are added to KG about that topic."""
        with get_pool(self._db).get() as conn:
            conn.execute(
                "UPDATE knowledge_gaps SET resolved = 1 "
                "WHERE topic = ? AND resolved = 0",
                (topic,),
            )

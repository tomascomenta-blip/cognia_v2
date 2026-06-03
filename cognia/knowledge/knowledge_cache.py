"""
cognia/knowledge/knowledge_cache.py
=====================================
SQLite-backed cache for pre-fetched knowledge facts.

Table: knowledge_cache(topic TEXT PRIMARY KEY, facts TEXT, fetched_at REAL, hit_count INT)
Uses storage/db_pool.py — NUNCA sqlite3.connect() directo.
"""

import time
from typing import Optional

from storage.db_pool import get_pool

# Default DB path — overridden at construction time by KnowledgeCache(db_path=...)
_DEFAULT_DB = None


def _get_default_db() -> str:
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        try:
            from cognia.config import DB_PATH
            _DEFAULT_DB = DB_PATH
        except ImportError:
            _DEFAULT_DB = "cognia_memory.db"
    return _DEFAULT_DB


class KnowledgeCache:
    """
    Fast read/write cache for factual knowledge fetched from external sources.

    Topics are stored as lowercase normalized strings.
    hit_count is incremented on every get() to track popularity for prefetch.
    """

    TABLE_DDL = """
        CREATE TABLE IF NOT EXISTS knowledge_cache (
            topic      TEXT PRIMARY KEY,
            facts      TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            hit_count  INTEGER NOT NULL DEFAULT 0
        )
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _get_default_db()
        self._ensure_table()

    def _ensure_table(self) -> None:
        pool = get_pool(self.db_path)
        with pool.get() as conn:
            conn.execute(self.TABLE_DDL)

    # ── Public API ────────────────────────────────────────────────────

    def get(self, topic: str) -> Optional[str]:
        """Return cached facts for topic, or None if not cached."""
        key = topic.lower().strip()
        pool = get_pool(self.db_path)
        with pool.get() as conn:
            row = conn.execute(
                "SELECT facts FROM knowledge_cache WHERE topic = ?", (key,)
            ).fetchone()
        if row:
            self.increment_hit(key)
            return row[0]
        return None

    def store(self, topic: str, facts: str) -> None:
        """Upsert facts for topic with current timestamp."""
        key = topic.lower().strip()
        now = time.time()
        pool = get_pool(self.db_path)
        with pool.get() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_cache (topic, facts, fetched_at, hit_count)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(topic) DO UPDATE SET
                    facts      = excluded.facts,
                    fetched_at = excluded.fetched_at
                """,
                (key, facts, now),
            )

    def increment_hit(self, topic: str) -> None:
        """Increment hit_count for analytics / prefetch prioritization."""
        key = topic.lower().strip()
        pool = get_pool(self.db_path)
        with pool.get() as conn:
            conn.execute(
                "UPDATE knowledge_cache SET hit_count = hit_count + 1 WHERE topic = ?",
                (key,),
            )

    def top_topics(self, n: int = 10) -> list:
        """Return n most-hit topics for sleep prefetch."""
        pool = get_pool(self.db_path)
        with pool.get() as conn:
            rows = conn.execute(
                "SELECT topic FROM knowledge_cache ORDER BY hit_count DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [r[0] for r in rows]

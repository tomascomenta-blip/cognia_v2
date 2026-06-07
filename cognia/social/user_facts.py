"""
cognia/social/user_facts.py
===========================
UserFactsMemory: stores declared and inferred facts about the user,
injects top facts into the system prompt so Cognia feels like it
truly knows who it is talking to.

DB: user_facts table in a dedicated SQLite file (cognia_user_facts.db).
Uses storage/db_pool.py — never sqlite3.connect() directly.
"""

import re
import time
from typing import Optional

from storage.db_pool import get_pool

_DB_PATH = "cognia_user_facts.db"

# ── Auto-inference patterns ───────────────────────────────────────────
# Each tuple: (compiled_regex, template_string)
# Template placeholders: {1} = first capture group, {2} = second capture group
_INFERENCE_PATTERNS = [
    (
        re.compile(r'\b(soy|trabajo como|me llamo|mi nombre es)\s+([A-Za-z][a-z]+)', re.IGNORECASE),
        "El usuario {1}: {2}",
    ),
    (
        re.compile(r'\b(uso|trabajo con|prefiero)\s+([A-Za-z+#]+)', re.IGNORECASE),
        "El usuario usa/prefiere: {2}",
    ),
    (
        re.compile(r'\b(vivo en|estoy en|soy de)\s+([A-Za-z\s]+)', re.IGNORECASE),
        "El usuario esta en: {2}",
    ),
    (
        re.compile(r'\b(tengo|llevo)\s+(\d+)\s+(anos|meses|años)\s+(de experiencia|trabajando)', re.IGNORECASE),
        "El usuario tiene {2} {3} de experiencia",
    ),
]


class UserFactsMemory:
    """Persistent store for user-specific facts with injection into system prompt."""

    def __init__(self, db_path: str = _DB_PATH) -> None:
        self._db = db_path
        self._init_db()

    def _init_db(self) -> None:
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_facts (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact             TEXT    UNIQUE NOT NULL,
                    source           TEXT    NOT NULL
                                             CHECK(source IN ('declared','inferred','system')),
                    confidence       REAL    NOT NULL DEFAULT 1.0,
                    times_referenced INTEGER NOT NULL DEFAULT 0,
                    created_at       REAL    NOT NULL,
                    last_seen        REAL    NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_uf_confidence ON user_facts(confidence)"
            )

    # ── Core write operations ─────────────────────────────────────────

    def add_fact(self, fact: str, source: str = "declared", confidence: float = 1.0) -> int:
        """Insert a fact; silently ignores duplicates. Returns the row id."""
        now = time.time()
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_facts (fact, source, confidence, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (fact.strip(), source, float(confidence), now, now),
            )
            row = conn.execute(
                "SELECT id FROM user_facts WHERE fact = ?", (fact.strip(),)
            ).fetchone()
        return int(row[0]) if row else -1

    def forget_fact(self, fact_id: int) -> bool:
        """Delete a fact by id. Returns True if a row was removed."""
        with get_pool(self._db).get() as conn:
            cur = conn.execute("DELETE FROM user_facts WHERE id = ?", (fact_id,))
        return cur.rowcount > 0

    def reference_fact(self, fact_id: int) -> None:
        """Increment times_referenced and update last_seen for a fact."""
        now = time.time()
        with get_pool(self._db).get() as conn:
            conn.execute(
                """
                UPDATE user_facts
                SET times_referenced = times_referenced + 1, last_seen = ?
                WHERE id = ?
                """,
                (now, fact_id),
            )

    # ── Inference ────────────────────────────────────────────────────

    def infer_from_text(self, text: str) -> list[str]:
        """Apply _INFERENCE_PATTERNS to text and return a list of inferred fact strings.

        Does NOT persist anything — call infer_and_store() for that.
        """
        results: list[str] = []
        for pattern, template in _INFERENCE_PATTERNS:
            m = pattern.search(text)
            if m:
                fact = template
                for i, group in enumerate(m.groups(), start=1):
                    fact = fact.replace(f"{{{i}}}", (group or "").strip())
                results.append(fact.strip())
        return results

    def infer_and_store(self, text: str) -> int:
        """Infer facts from text and persist them with source='inferred', confidence=0.7.

        Returns the count of new facts stored.
        """
        inferred = self.infer_from_text(text)
        stored = 0
        for fact in inferred:
            row_id = self.add_fact(fact, source="inferred", confidence=0.7)
            if row_id != -1:
                # check if it was truly new (times_referenced == 0 means just inserted)
                with get_pool(self._db).get() as conn:
                    row = conn.execute(
                        "SELECT times_referenced FROM user_facts WHERE id = ?", (row_id,)
                    ).fetchone()
                if row and row[0] == 0:
                    stored += 1
        return stored

    # ── Read operations ───────────────────────────────────────────────

    def get_facts(self, limit: int = 10, min_confidence: float = 0.5) -> list[dict]:
        """Return top facts ordered by times_referenced desc, then created_at desc."""
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                """
                SELECT id, fact, source, confidence, times_referenced, created_at, last_seen
                FROM user_facts
                WHERE confidence >= ?
                ORDER BY times_referenced DESC, created_at DESC
                LIMIT ?
                """,
                (float(min_confidence), int(limit)),
            ).fetchall()
        return [
            {
                "id": r[0],
                "fact": r[1],
                "source": r[2],
                "confidence": r[3],
                "times_referenced": r[4],
                "created_at": r[5],
                "last_seen": r[6],
            }
            for r in rows
        ]

    def get_context(self, limit: int = 5) -> str:
        """Return a formatted string for injection into the system prompt.

        Returns "" if no facts are stored.
        """
        facts = self.get_facts(limit=limit, min_confidence=0.5)
        if not facts:
            return ""
        lines = "\n".join(f"  - {f['fact']}" for f in facts)
        return f"Lo que Cognia sabe de ti:\n{lines}"

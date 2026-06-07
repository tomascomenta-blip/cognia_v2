"""
cognia/knowledge/crystallizer.py
=================================
KnowledgeCrystallizer — promotes frequently-accessed KG facts to
"crystallized" status for preferential injection into the system prompt.

Usage:
    from cognia.knowledge.crystallizer import KnowledgeCrystallizer, CrystallizationWorker
    c = KnowledgeCrystallizer()
    n = c.crystallize_frequent(min_accesses=5)
    ctx = c.get_injection_context(5)
"""

import time
import threading
from typing import List, Dict

from storage.db_pool import db_connect_pooled as db_connect

try:
    from cognia.config import DB_PATH
except ImportError:
    DB_PATH = "cognia_memory.db"

_CRYSTALLIZATION_INTERVAL = 600  # seconds between daemon runs


class KnowledgeCrystallizer:
    """Promotes high-access KG facts to crystallized status."""

    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        self._migrate()

    def _migrate(self) -> None:
        """Idempotent: add crystallized column if not present."""
        conn = db_connect(self.db)
        try:
            conn.execute(
                "ALTER TABLE knowledge_graph ADD COLUMN crystallized INTEGER DEFAULT 0"
            )
            conn.commit()
        except Exception:
            pass  # already exists
        conn.close()

    def crystallize_frequent(self, min_accesses: int = 5) -> int:
        """
        Promote facts to crystallized=1.

        Uses weight > 0.8 as proxy for access frequency because the
        knowledge_graph table lacks an explicit access_count column —
        add_triple() reinforces weight on each access.

        Returns count of newly crystallized facts.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        # Facts that meet threshold but are not yet crystallized
        c.execute(
            "SELECT COUNT(*) FROM knowledge_graph WHERE weight > ? AND crystallized = 0",
            (min_accesses * 0.1,),  # heuristic: weight > min_accesses * 0.1
        )
        count = c.fetchone()[0]
        if count:
            c.execute(
                "UPDATE knowledge_graph SET crystallized = 1 WHERE weight > ? AND crystallized = 0",
                (min_accesses * 0.1,),
            )
            conn.commit()
        conn.close()
        return count

    def get_crystallized(self, limit: int = 10) -> List[Dict]:
        """Return up to `limit` crystallized facts as list of dicts."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute(
            """SELECT subject, predicate, object, weight
               FROM knowledge_graph
               WHERE crystallized = 1
               ORDER BY weight DESC
               LIMIT ?""",
            (limit,),
        )
        rows = c.fetchall()
        conn.close()
        return [
            {"subject": r[0], "predicate": r[1], "object": r[2], "weight": r[3]}
            for r in rows
        ]

    def decrystallize_stale(self, stale_days: int = 30) -> int:
        """
        Remove crystallized status from facts not accessed in stale_days days.
        Uses last_accessed column (epoch float). Returns count affected.
        """
        cutoff = time.time() - stale_days * 86400
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute(
            """UPDATE knowledge_graph
               SET crystallized = 0
               WHERE crystallized = 1 AND last_accessed < ? AND last_accessed > 0""",
            (cutoff,),
        )
        affected = c.rowcount
        conn.commit()
        conn.close()
        return affected

    def get_stats(self) -> Dict:
        """Return total_facts, crystallized count, and crystallization_rate."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM knowledge_graph")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM knowledge_graph WHERE crystallized = 1")
        cryst = c.fetchone()[0]
        conn.close()
        rate = round(cryst / total, 4) if total else 0.0
        return {
            "total_facts": total,
            "crystallized": cryst,
            "crystallization_rate": rate,
        }

    def get_injection_context(self, limit: int = 5) -> str:
        """
        Return crystallized facts as a formatted string for system prompt injection.
        Returns empty string when no facts are crystallized.
        """
        facts = self.get_crystallized(limit)
        if not facts:
            return ""
        lines = [
            f"  - {f['subject']} {f['predicate']} {f['object']}"
            for f in facts
        ]
        return "Hechos cristalizados:\n" + "\n".join(lines)


class CrystallizationWorker:
    """Daemon thread that periodically calls crystallize_frequent()."""

    def __init__(
        self,
        crystallizer: KnowledgeCrystallizer = None,
        interval: int = _CRYSTALLIZATION_INTERVAL,
    ):
        self._crystallizer = crystallizer or KnowledgeCrystallizer()
        self._interval = interval
        self._thread: threading.Thread = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="CrystallizationWorker"
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            time.sleep(self._interval)
            try:
                self._crystallizer.crystallize_frequent()
            except Exception:
                pass  # non-fatal — never crash the daemon

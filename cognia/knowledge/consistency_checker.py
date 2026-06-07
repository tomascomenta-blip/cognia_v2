"""
cognia/knowledge/consistency_checker.py
=========================================
Detects contradictory facts in the knowledge graph.

Contradiction types detected:
  - multiple_values: same subject+predicate, different objects
  - circular_isa: A is_a B AND B is_a A
"""

import time
from storage.db_pool import get_pool
from cognia.config import DB_PATH

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_conflicts (
    id          INTEGER PRIMARY KEY,
    subject     TEXT    NOT NULL,
    predicate   TEXT    NOT NULL,
    fact_a      TEXT    NOT NULL,
    fact_b      TEXT    NOT NULL,
    detected_at REAL    NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0
)
"""

_IDX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_kc_subject_pred "
    "ON knowledge_conflicts(subject, predicate)"
)


class ConsistencyChecker:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_table()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        with get_pool(self.db_path).get() as conn:
            conn.execute(_TABLE_DDL)
            conn.execute(_IDX_DDL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_contradictions(self, limit: int = 20) -> list:
        """
        Query knowledge_graph for contradictions.
        Returns list of dicts with keys: subject, predicate, values, conflict_type.
        """
        results = []

        with get_pool(self.db_path).get() as conn:
            # --- multiple_values: same subject+predicate, different objects ---
            rows = conn.execute(
                """
                SELECT subject, predicate,
                       GROUP_CONCAT(DISTINCT object) AS objs,
                       COUNT(DISTINCT object) AS cnt
                FROM   knowledge_graph
                GROUP  BY subject, predicate
                HAVING cnt > 1
                LIMIT  ?
                """,
                (limit,),
            ).fetchall()

            for subject, predicate, objs_csv, _ in rows:
                values = [v.strip() for v in objs_csv.split(",") if v.strip()]
                results.append({
                    "subject": subject,
                    "predicate": predicate,
                    "values": values,
                    "conflict_type": "multiple_values",
                })

            # --- circular_isa: A is_a B AND B is_a A ---
            if len(results) < limit:
                isa_rows = conn.execute(
                    """
                    SELECT a.subject, a.object
                    FROM   knowledge_graph a
                    JOIN   knowledge_graph b
                           ON a.subject = b.object
                          AND a.object  = b.subject
                    WHERE  a.predicate = 'is_a'
                      AND  b.predicate = 'is_a'
                      AND  a.subject < a.object
                    LIMIT  ?
                    """,
                    (limit - len(results),),
                ).fetchall()

                for node_a, node_b in isa_rows:
                    results.append({
                        "subject": node_a,
                        "predicate": "is_a",
                        "values": [node_b, node_a],
                        "conflict_type": "circular_isa",
                    })

        return results

    def store_conflict(
        self, subject: str, predicate: str, fact_a: str, fact_b: str
    ) -> int:
        """Insert a conflict record and return its id."""
        with get_pool(self.db_path).get() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_conflicts
                    (subject, predicate, fact_a, fact_b, detected_at, resolved)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (subject, predicate, fact_a, fact_b, time.time()),
            )
            return cur.lastrowid

    def resolve_conflict(self, conflict_id: int) -> bool:
        """Mark a conflict as resolved. Returns True if a row was updated."""
        with get_pool(self.db_path).get() as conn:
            cur = conn.execute(
                "UPDATE knowledge_conflicts SET resolved = 1 WHERE id = ?",
                (conflict_id,),
            )
            return cur.rowcount > 0

    def get_unresolved(self, limit: int = 10) -> list:
        """Return unresolved conflicts as list of dicts."""
        with get_pool(self.db_path).get() as conn:
            rows = conn.execute(
                """
                SELECT id, subject, predicate, fact_a, fact_b, detected_at
                FROM   knowledge_conflicts
                WHERE  resolved = 0
                ORDER  BY detected_at DESC
                LIMIT  ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "id": row[0],
                "subject": row[1],
                "predicate": row[2],
                "fact_a": row[3],
                "fact_b": row[4],
                "detected_at": row[5],
            }
            for row in rows
        ]

    def get_stats(self) -> dict:
        """Return total / unresolved / resolved counts."""
        with get_pool(self.db_path).get() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM knowledge_conflicts"
            ).fetchone()[0]
            unresolved = conn.execute(
                "SELECT COUNT(*) FROM knowledge_conflicts WHERE resolved = 0"
            ).fetchone()[0]

        return {
            "total": total,
            "unresolved": unresolved,
            "resolved": total - unresolved,
        }

    def run_check(self) -> int:
        """
        Find contradictions, store new ones (skip duplicates for same
        subject+predicate already stored), return count of new conflicts.
        """
        contradictions = self.find_contradictions()
        if not contradictions:
            return 0

        # Load already-stored (subject, predicate) pairs to avoid duplication
        with get_pool(self.db_path).get() as conn:
            existing = set(
                conn.execute(
                    "SELECT subject, predicate FROM knowledge_conflicts"
                ).fetchall()
            )

        new_count = 0
        for c in contradictions:
            key = (c["subject"], c["predicate"])
            if key in existing:
                continue
            values = c["values"]
            fact_a = values[0] if len(values) > 0 else ""
            fact_b = values[1] if len(values) > 1 else ""
            self.store_conflict(c["subject"], c["predicate"], fact_a, fact_b)
            existing.add(key)
            new_count += 1

        return new_count

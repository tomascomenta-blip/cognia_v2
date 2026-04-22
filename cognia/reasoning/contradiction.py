"""
cognia/reasoning/contradiction.py
==================================
Detector y registro de contradicciones cognitivas.
"""

from datetime import datetime, timedelta
from typing import Optional
from storage.db_pool import db_connect_pooled as db_connect
from ..vectors import cosine_similarity
from ..config import DB_PATH


class ContradictionDetector:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def check(self, observation: str, label: str, vector: list,
              semantic) -> Optional[dict]:
        related = semantic.find_related(vector, top_k=3)
        for item in related:
            if item["concept"] != label and item["similarity"] > 0.85 and item["confidence"] > 0.6:
                return {
                    "type": "label_conflict",
                    "observation": observation[:60],
                    "new_label": label,
                    "existing_label": item["concept"],
                    "similarity": item["similarity"],
                    "message": (f"Esto parece '{item['concept']}' (sim={item['similarity']:.2f}) "
                                f"pero lo estás etiquetando como '{label}'")
                }
        return None

    def log_contradiction(self, concept: str, claim_a: str, claim_b: str):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO contradictions (timestamp, concept, claim_a, claim_b)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), concept, claim_a, claim_b))
        conn.commit()
        conn.close()

    def list_unresolved(self) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT concept, claim_a, claim_b, timestamp
            FROM contradictions WHERE resolved=0
            ORDER BY timestamp DESC LIMIT 10
        """)
        rows = [{"concept": r[0], "claim_a": r[1], "claim_b": r[2], "at": r[3]}
                for r in c.fetchall()]
        conn.close()
        return rows

    def auto_resolve_old(self, max_age_days: int = 30) -> int:
        """
        Resuelve automáticamente contradicciones antiguas o duplicadas.
        Retorna el número de contradicciones resueltas.
        """
        conn = db_connect(self.db)
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()

        c.execute("""
            UPDATE contradictions SET resolved=1, resolution='auto:expired'
            WHERE resolved=0 AND timestamp < ?
        """, (cutoff,))
        expired = c.rowcount

        c.execute("""
            SELECT concept, COUNT(*) as cnt FROM contradictions
            WHERE resolved=0 GROUP BY concept HAVING cnt > 3
        """)
        heavy = c.fetchall()
        for concept, cnt in heavy:
            c.execute("""
                UPDATE contradictions SET resolved=1, resolution='auto:deduplicated'
                WHERE resolved=0 AND concept=?
                AND id NOT IN (
                    SELECT id FROM contradictions
                    WHERE resolved=0 AND concept=?
                    ORDER BY timestamp DESC LIMIT 2
                )
            """, (concept, concept))

        resolved_total = expired + sum(cnt - 2 for _, cnt in heavy if cnt > 2)
        conn.commit()
        conn.close()
        return resolved_total

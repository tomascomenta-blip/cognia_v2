"""
cognia/knowledge/staleness_detector.py
========================================
Detecta y aplica decaimiento de peso en hechos del KG poco referenciados.

Decay: si un hecho no se accede en STALE_DAYS dias, reducir weight *= DECAY_FACTOR
No elimina hechos — solo reduce peso. Hechos con weight < MIN_WEIGHT quedan
marcados como "stale" por sus estadisticas.
"""

import time
from storage.db_pool import db_connect_pooled as db_connect
from cognia.config import DB_PATH


class StalenessDetector:
    STALE_DAYS = 14     # dias sin acceso para considerar stale
    DECAY_FACTOR = 0.9  # reduccion de peso por ciclo de mantenimiento
    MIN_WEIGHT = 0.05   # umbral minimo de peso (no reducir mas)

    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def _stale_threshold(self) -> float:
        return time.time() - self.STALE_DAYS * 86400

    def get_stale_facts(self, limit: int = 100) -> list:
        """
        Retorna hechos con last_accessed < ahora - STALE_DAYS*86400 Y weight > MIN_WEIGHT.
        [{subject, predicate, object, weight, last_accessed_days_ago}]
        """
        threshold = self._stale_threshold()
        now = time.time()
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute(
            """SELECT subject, predicate, object, weight, last_accessed
               FROM knowledge_graph
               WHERE last_accessed < ? AND weight > ?
               ORDER BY last_accessed ASC
               LIMIT ?""",
            (threshold, self.MIN_WEIGHT, limit),
        )
        rows = c.fetchall()
        conn.close()
        result = []
        for subj, pred, obj, weight, last_acc in rows:
            days_ago = (now - last_acc) / 86400 if last_acc > 0 else None
            result.append({
                "subject": subj,
                "predicate": pred,
                "object": obj,
                "weight": weight,
                "last_accessed_days_ago": round(days_ago, 1) if days_ago is not None else None,
            })
        return result

    def apply_decay(self, dry_run: bool = False) -> dict:
        """
        Aplica DECAY_FACTOR a todos los hechos stale.
        Si dry_run=True: solo retorna que se haria sin modificar.
        Retorna: {"facts_decayed": N, "facts_already_min": N, "dry_run": bool}
        """
        threshold = self._stale_threshold()
        conn = db_connect(self.db)
        c = conn.cursor()

        # Hechos stale con peso suficiente para decaer
        c.execute(
            """SELECT id, weight FROM knowledge_graph
               WHERE last_accessed < ? AND weight > ?""",
            (threshold, self.MIN_WEIGHT),
        )
        to_decay = c.fetchall()

        # Hechos stale ya en minimo (no se pueden reducir mas)
        c.execute(
            """SELECT COUNT(*) FROM knowledge_graph
               WHERE last_accessed < ? AND weight <= ?""",
            (threshold, self.MIN_WEIGHT),
        )
        already_min = c.fetchone()[0]

        if not dry_run and to_decay:
            updates = [
                (max(self.MIN_WEIGHT, row[1] * self.DECAY_FACTOR), row[0])
                for row in to_decay
            ]
            c.executemany(
                "UPDATE knowledge_graph SET weight=? WHERE id=?",
                updates,
            )
            conn.commit()

        conn.close()
        return {
            "facts_decayed": len(to_decay),
            "facts_already_min": already_min,
            "dry_run": dry_run,
        }

    def get_stats(self) -> dict:
        """
        Retorna estadisticas del KG:
        {
          "total_facts": int,
          "stale_facts": int,
          "never_accessed_facts": int,  # last_accessed == 0
          "avg_weight": float,
          "min_weight_facts": int       # weight <= MIN_WEIGHT
        }
        """
        threshold = self._stale_threshold()
        conn = db_connect(self.db)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM knowledge_graph")
        total = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(*) FROM knowledge_graph WHERE last_accessed < ?",
            (threshold,),
        )
        stale = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(*) FROM knowledge_graph WHERE last_accessed = 0.0 OR last_accessed IS NULL"
        )
        never_accessed = c.fetchone()[0]

        c.execute("SELECT AVG(weight) FROM knowledge_graph")
        avg_w = c.fetchone()[0] or 0.0

        c.execute(
            "SELECT COUNT(*) FROM knowledge_graph WHERE weight <= ?",
            (self.MIN_WEIGHT,),
        )
        min_weight_facts = c.fetchone()[0]

        conn.close()
        return {
            "total_facts": total,
            "stale_facts": stale,
            "never_accessed_facts": never_accessed,
            "avg_weight": round(avg_w, 4),
            "min_weight_facts": min_weight_facts,
        }

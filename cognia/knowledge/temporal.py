"""
cognia/knowledge/temporal.py
==============================
Memoria predictiva inspirada en HTM.
Aprende transiciones A→B→C y predice qué sigue.
"""

import time
from collections import deque, defaultdict
from datetime import datetime
from typing import Dict
from ..database import db_connect
from ..config import DB_PATH


class TemporalMemory:
    """
    Memoria predictiva inspirada en Hierarchical Temporal Memory (HTM).

    Aprende transiciones entre conceptos (A → B → C).
    Si aparece A, predice B. Sin matrices densas ni modelos neurales —
    solo contadores y probabilidades condicionales.
    """

    WINDOW_SIZE = 5

    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        self._context: deque = deque(maxlen=self.WINDOW_SIZE)
        self._last_time: float = time.time()

    def observe_concept(self, concept: str):
        now = time.time()
        gap = now - self._last_time
        self._last_time = now

        if not concept or len(concept) < 2:
            return

        for prev_concept in self._context:
            if prev_concept != concept:
                self._update_transition(prev_concept, concept, gap)

        self._context.append(concept)

    def _update_transition(self, from_c: str, to_c: str, gap_sec: float):
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, count, avg_gap_sec FROM temporal_sequences
            WHERE from_concept=? AND to_concept=?
        """, (from_c, to_c))
        row = c.fetchone()
        now = datetime.now().isoformat()

        if row:
            new_count = row[1] + 1
            new_avg = (row[2] * row[1] + gap_sec) / new_count
            c.execute("""
                UPDATE temporal_sequences SET count=?, avg_gap_sec=?, last_seen=? WHERE id=?
            """, (new_count, new_avg, now, row[0]))
        else:
            c.execute("""
                INSERT INTO temporal_sequences (from_concept, to_concept, count, avg_gap_sec, last_seen)
                VALUES (?, ?, 1, ?, ?)
            """, (from_c, to_c, gap_sec, now))

        conn.commit()
        conn.close()

    def predict_next(self, concept: str, top_k: int = 3) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT to_concept, count, avg_gap_sec FROM temporal_sequences
            WHERE from_concept=? ORDER BY count DESC LIMIT ?
        """, (concept, top_k * 2))
        rows = c.fetchall()

        total = sum(r[1] for r in rows) or 1
        predictions = [
            {"concept": r[0], "probability": r[1] / total,
             "avg_gap_sec": r[2], "count": r[1]}
            for r in rows
        ]
        conn.close()
        return predictions[:top_k]

    def predict_from_context(self) -> list:
        if not self._context:
            return []

        combined: Dict[str, float] = defaultdict(float)
        decay = 1.0

        for concept in reversed(self._context):
            preds = self.predict_next(concept, top_k=5)
            for p in preds:
                combined[p["concept"]] += p["probability"] * decay
            decay *= 0.6

        sorted_preds = sorted(combined.items(), key=lambda x: -x[1])
        return [{"concept": c, "score": round(s, 3)} for c, s in sorted_preds[:5]]

    def get_sequences(self, min_count: int = 2) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT from_concept, to_concept, count, avg_gap_sec
            FROM temporal_sequences WHERE count >= ? ORDER BY count DESC LIMIT 20
        """, (min_count,))
        rows = [{"from": r[0], "to": r[1], "count": r[2], "avg_gap_sec": r[3]}
                for r in c.fetchall()]
        conn.close()
        return rows

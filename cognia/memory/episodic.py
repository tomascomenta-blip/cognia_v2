"""
cognia/memory/episodic.py
=========================
Memoria episódica: almacenamiento y recuperación de experiencias.

PASO 1: Logging estructurado — eliminados todos los except: pass
"""

import json
import time
from datetime import datetime
from typing import Optional

from ..database import db_connect
from ..vectors import cosine_similarity
from ..config import DB_PATH
from logger_config import get_logger, log_db_error, log_slow, safe_execute

logger = get_logger(__name__)


class EpisodicMemory:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def store(self, observation: str, label: str, vector: list,
              confidence: float = 0.5, importance: float = 1.0,
              emotion: dict = None, surprise: float = 0.0,
              context_tags: list = None) -> int:

        emotion = emotion or {"score": 0.0, "label": "neutral", "intensity": 0.0}
        context_tags = context_tags or []
        emotion_boost = abs(emotion["score"]) * emotion["intensity"] * 0.5
        surprise_boost = surprise * 0.4
        final_importance = min(3.0, importance + emotion_boost + surprise_boost)
        next_review = self._next_review_date(review_count=0)

        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("""
                INSERT INTO episodic_memory
                (timestamp, observation, label, vector, confidence, last_access,
                 importance, emotion_score, emotion_label, surprise,
                 review_count, next_review, context_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (now, observation, label, json.dumps(vector), confidence, now,
                  final_importance, emotion["score"], emotion["label"], surprise,
                  next_review, json.dumps(context_tags)))
            ep_id = c.lastrowid
            conn.commit()
            conn.close()
            logger.debug(
                "Episodio almacenado",
                extra={"op": "episodic.store", "context": f"ep_id={ep_id} label={label}"},
            )
            return ep_id
        except Exception as exc:
            log_db_error(logger, "episodic.store", exc,
                         extra_ctx=f"label={label} obs_len={len(observation)}")
            return -1

    def _next_review_date(self, review_count: int) -> str:
        intervals = [1, 3, 7, 14, 30, 60, 120]
        idx = min(review_count, len(intervals) - 1)
        hours = intervals[idx] * 24
        future = time.time() + hours * 3600
        return datetime.fromtimestamp(future).isoformat()

    def retrieve_similar(self, query_vector: list, top_k: int = 5,
                         include_forgotten: bool = False,
                         emotion_filter: str = None) -> list:
        t0 = time.perf_counter()
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            cond = "" if include_forgotten else "WHERE forgotten = 0"
            if emotion_filter:
                sep = "AND" if cond else "WHERE"
                cond += f" {sep} emotion_label = '{emotion_filter}'"
            c.execute(f"""
                SELECT id, observation, label, vector, confidence, importance,
                       emotion_score, emotion_label, surprise,
                       COALESCE(feedback_weight, 1.0) AS feedback_weight
                FROM episodic_memory {cond}
            """)
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "episodic.retrieve_similar", exc,
                         extra_ctx=f"top_k={top_k} emotion_filter={emotion_filter}")
            return []

        scored = []
        for row in rows:
            try:
                ep_id, obs, label, vec_str, conf, imp, emo_score, emo_label, surprise, fb_weight = row
                vec = json.loads(vec_str)
                sim = cosine_similarity(query_vector, vec)
                emo_boost = abs(emo_score) * 0.1
                # PASO 5: feedback_weight pondera el score final.
                # Episodios bien valorados (+1) tienen peso > 1.0 → suben en ranking.
                # Episodios mal valorados (-1) tienen peso < 1.0 → bajan en ranking.
                # Se aplica como multiplicador suave con atenuación: 0.7 base + 0.3 feedback
                _fw = float(fb_weight) if fb_weight is not None else 1.0
                _fw_factor = 0.70 + 0.30 * _fw   # rango: [0.76, 1.30] para pesos [0.2, 2.0]
                score = (0.55 * sim + 0.2 * conf + 0.15 * min(imp, 2.0) / 2.0 + emo_boost) * _fw_factor
                scored.append({
                    "id": ep_id, "observation": obs, "label": label,
                    "similarity": sim, "confidence": conf, "score": score,
                    "emotion": {"score": emo_score, "label": emo_label},
                    "surprise": surprise,
                    "feedback_weight": round(_fw, 3),   # exponer para diagnóstico
                })
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Fila episódica corrupta, ignorando",
                    extra={"op": "episodic.retrieve_similar",
                           "context": f"ep_id={row[0] if row else '?'} err={exc}"},
                )
                continue

        scored.sort(key=lambda x: x["score"], reverse=True)

        if scored:
            top_ids = [s["id"] for s in scored[:top_k]]
            try:
                conn = db_connect(self.db)
                c = conn.cursor()
                now = datetime.now().isoformat()
                for ep_id in top_ids:
                    c.execute("""
                        UPDATE episodic_memory
                        SET access_count = access_count + 1, last_access = ?
                        WHERE id = ?
                    """, (now, ep_id))
                conn.commit()
                conn.close()
            except Exception as exc:
                log_db_error(logger, "episodic.update_access_count", exc,
                             extra_ctx=f"ep_ids={top_ids[:3]}")

        log_slow(logger, "episodic.retrieve_similar", t0, threshold_ms=200)
        return scored[:top_k]

    def get_due_for_review(self) -> list:
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("""
                SELECT id, observation, label, confidence, review_count
                FROM episodic_memory
                WHERE forgotten = 0 AND next_review <= ? AND review_count < 7
                ORDER BY importance DESC LIMIT 10
            """, (now,))
            rows = [{"id": r[0], "observation": r[1], "label": r[2],
                     "confidence": r[3], "review_count": r[4]}
                    for r in c.fetchall()]
            conn.close()
            return rows
        except Exception as exc:
            log_db_error(logger, "episodic.get_due_for_review", exc)
            return []

    def mark_reviewed(self, ep_id: int, correct: bool):
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT review_count, confidence FROM episodic_memory WHERE id=?", (ep_id,))
            row = c.fetchone()
            if not row:
                conn.close()
                logger.warning(
                    "Episodio no encontrado para marcar revisión",
                    extra={"op": "episodic.mark_reviewed", "context": f"ep_id={ep_id}"},
                )
                return
            count, conf = row
            new_count = (count + 1) if correct else 0
            delta_conf = 0.1 if correct else -0.05
            new_conf = max(0.1, min(1.0, conf + delta_conf))
            next_rev = self._next_review_date(new_count)
            c.execute("""
                UPDATE episodic_memory
                SET review_count=?, confidence=?, next_review=?
                WHERE id=?
            """, (new_count, new_conf, next_rev, ep_id))
            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "episodic.mark_reviewed", exc,
                         extra_ctx=f"ep_id={ep_id} correct={correct}")

    def count(self, include_forgotten: bool = False) -> int:
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            cond = "" if include_forgotten else "WHERE forgotten = 0"
            c.execute(f"SELECT COUNT(*) FROM episodic_memory {cond}")
            n = c.fetchone()[0]
            conn.close()
            return n
        except Exception as exc:
            log_db_error(logger, "episodic.count", exc,
                         extra_ctx=f"include_forgotten={include_forgotten}")
            return 0



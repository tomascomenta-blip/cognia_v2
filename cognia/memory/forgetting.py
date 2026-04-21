"""
cognia/memory/forgetting.py
===========================
Módulo de olvido (decaimiento) y consolidación tipo sueño.
"""

import json
import time
from datetime import datetime
from ..database import db_connect
from ..vectors import cosine_similarity, vec_norm
from ..config import DB_PATH
from .semantic import SemanticMemory


class ForgettingModule:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path
        self.base_decay = 0.05
        self.forgetting_threshold = 0.12
        self.compression_threshold = 0.30

    def decay_cycle(self) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("""SELECT id, importance, access_count, last_access, confidence,
                            emotion_score, surprise, review_count
                    FROM episodic_memory WHERE forgotten = 0""")
        rows = c.fetchall()

        to_forget = []
        to_compress = []
        for row in rows:
            ep_id, importance, access_count, last_access, confidence, emo_score, surprise, review_count = row
            if last_access:
                try:
                    last_dt = datetime.fromisoformat(last_access)
                    hours_since = (datetime.now() - last_dt).total_seconds() / 3600
                except Exception:
                    hours_since = 0.0
            else:
                hours_since = 0.0
            emo_factor = 1.0 + abs(emo_score or 0) * 0.5
            surp_factor = 1.0 + (surprise or 0) * 0.3
            review_factor = 1.0 + (review_count or 0) * 0.2
            effective_decay = self.base_decay / (emo_factor * surp_factor * review_factor)
            retention = importance * (1 - effective_decay) ** (hours_since / 24)
            if retention < self.forgetting_threshold:
                to_forget.append((retention, ep_id))
            elif retention < self.compression_threshold:
                to_compress.append((importance * (1 - effective_decay), ep_id))

        if to_forget:
            c.executemany("UPDATE episodic_memory SET forgotten=1, importance=? WHERE id=?", to_forget)
        if to_compress:
            c.executemany("UPDATE episodic_memory SET importance=?, compressed=1 WHERE id=?", to_compress)

        conn.commit()
        conn.close()
        return {"total_checked": len(rows), "forgotten": len(to_forget),
                "compressed": len(to_compress), "timestamp": now}

    def reactivate(self, query_vector: list, top_k: int = 3) -> list:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("SELECT id, observation, label, vector, confidence, emotion_score FROM episodic_memory WHERE forgotten = 1")
        rows = c.fetchall()

        recovered = []
        ids_to_reactivate = []
        for ep_id, obs, label, vec_str, conf, emo_score in rows:
            vec = json.loads(vec_str)
            sim = cosine_similarity(query_vector, vec)
            threshold = 0.55 if abs(emo_score or 0) > 0.3 else 0.65
            if sim > threshold:
                recovered.append({"id": ep_id, "observation": obs, "label": label,
                                   "similarity": sim, "emotion_score": emo_score})
                ids_to_reactivate.append((ep_id,))

        if ids_to_reactivate:
            c.executemany("UPDATE episodic_memory SET forgotten=0, importance=importance+0.3 WHERE id=?",
                          ids_to_reactivate)
            conn.commit()
        conn.close()
        recovered.sort(key=lambda x: x["similarity"], reverse=True)
        return recovered[:top_k]


class ConsolidationModule:
    def __init__(self, db_path: str = DB_PATH, semantic: SemanticMemory = None):
        self.db = db_path
        self.semantic = semantic or SemanticMemory(db_path)

    def sleep_consolidation(self, min_support: int = 2) -> dict:
        start = time.time()
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT label, COUNT(*) as cnt, AVG(confidence) as avg_conf,
                   AVG(emotion_score) as avg_emo,
                   GROUP_CONCAT(vector, '|') as vecs
            FROM episodic_memory
            WHERE forgotten = 0 AND label IS NOT NULL
            GROUP BY label HAVING cnt >= ?
        """, (min_support,))
        rows = c.fetchall()
        conn.close()

        consolidated = 0
        all_labels = []

        for label, cnt, avg_conf, avg_emo, vecs_str in rows:
            vec_list = [json.loads(v) for v in vecs_str.split("|") if v.strip()]
            if not vec_list:
                continue
            dim = len(vec_list[0])
            mean_vec = [sum(v[i] for v in vec_list) / len(vec_list) for i in range(dim)]
            norm = vec_norm(mean_vec)
            if norm > 0:
                mean_vec = [x / norm for x in mean_vec]
            desc = f"Consolidado de {cnt} experiencias (confianza media: {avg_conf:.2f})"
            self.semantic.update_concept(label, mean_vec, desc,
                                          confidence_delta=0.05,
                                          emotion_score=avg_emo or 0.0)
            all_labels.append((label, mean_vec))
            consolidated += 1

        assoc_created = 0
        if len(all_labels) >= 2:
            sample = all_labels[-150:] if len(all_labels) > 150 else all_labels
            MAX_ASSOC = 500
            for i in range(len(sample)):
                if assoc_created >= MAX_ASSOC:
                    break
                for j in range(i + 1, len(sample)):
                    if assoc_created >= MAX_ASSOC:
                        break
                    label_a, vec_a = sample[i]
                    label_b, vec_b = sample[j]
                    sim = cosine_similarity(vec_a, vec_b)
                    if sim > 0.5:
                        self.semantic.add_association(label_a, label_b, sim)
                        self.semantic.add_association(label_b, label_a, sim)
                        assoc_created += 1

        duration_ms = int((time.time() - start) * 1000)
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            INSERT INTO sleep_log (timestamp, episodes_in, concepts_out, duration_ms)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), len(rows), consolidated, duration_ms))
        conn.commit()
        conn.close()

        return {"concepts_consolidated": consolidated,
                "associations_created": assoc_created,
                "duration_ms": duration_ms}

    def consolidate(self, min_support: int = 2) -> int:
        result = self.sleep_consolidation(min_support)
        return result["concepts_consolidated"]

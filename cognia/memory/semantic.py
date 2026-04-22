"""
cognia/memory/semantic.py
=========================
Memoria semántica: conceptos abstractos y spreading activation.

PASO 1: Logging estructurado — eliminados todos los except: pass
"""

import json
from datetime import datetime
from typing import Optional

from storage.db_pool import db_connect_pooled as db_connect
from ..vectors import cosine_similarity, vec_norm
from ..config import DB_PATH
from logger_config import get_logger, log_db_error, safe_execute

logger = get_logger(__name__)


class SemanticMemory:
    def __init__(self, db_path: str = DB_PATH):
        self.db = db_path

    def update_concept(self, concept: str, vector: list,
                       description: str = "", confidence_delta: float = 0.1,
                       emotion_score: float = 0.0):
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("SELECT id, vector, confidence, support, emotion_avg, associations "
                      "FROM semantic_memory WHERE concept = ?", (concept,))
            row = c.fetchone()

            if row:
                try:
                    old_vec = json.loads(row[1])
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "Vector corrupto en concepto existente, reinicializando",
                        extra={"op": "semantic.update_concept",
                               "context": f"concept={concept} err={exc}"},
                    )
                    old_vec = vector  # no mezclar — usar el nuevo directamente

                old_conf = row[2]
                support  = row[3] + 1
                old_emo  = row[4] or 0.0
                alpha    = 1.0 / support
                new_vec  = [alpha * n + (1 - alpha) * o for n, o in zip(vector, old_vec)]
                new_conf = min(1.0, old_conf + confidence_delta)
                new_emo  = (old_emo * (support - 1) + emotion_score) / support
                c.execute("""
                    UPDATE semantic_memory
                    SET vector=?, confidence=?, support=?, last_updated=?,
                        description=?, emotion_avg=?
                    WHERE id=?
                """, (json.dumps(new_vec), new_conf, support, now,
                      description or row[1], new_emo, row[0]))
                logger.debug(
                    "Concepto semántico actualizado",
                    extra={"op": "semantic.update_concept",
                           "context": f"concept={concept} support={support} conf={new_conf:.2f}"},
                )
            else:
                c.execute("""
                    INSERT INTO semantic_memory
                    (concept, description, vector, confidence, support, last_updated, emotion_avg, associations)
                    VALUES (?, ?, ?, ?, 1, ?, ?, '{}')
                """, (concept, description, json.dumps(vector), 0.5, now, emotion_score))
                logger.info(
                    "Nuevo concepto semántico creado",
                    extra={"op": "semantic.update_concept",
                           "context": f"concept={concept}"},
                )

            conn.commit()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "semantic.update_concept", exc,
                         extra_ctx=f"concept={concept}")

    def add_association(self, concept_a: str, concept_b: str, strength: float = 0.5):
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT associations FROM semantic_memory WHERE concept=?", (concept_a,))
            row = c.fetchone()
            if row:
                try:
                    assoc = json.loads(row[0] or "{}")
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "Asociaciones corruptas, reinicializando a vacío",
                        extra={"op": "semantic.add_association",
                               "context": f"concept_a={concept_a} err={exc}"},
                    )
                    assoc = {}
                old = assoc.get(concept_b, 0.0)
                assoc[concept_b] = min(1.0, old + strength * 0.3)
                c.execute("UPDATE semantic_memory SET associations=? WHERE concept=?",
                          (json.dumps(assoc), concept_a))
                conn.commit()
            else:
                logger.warning(
                    "Intento de asociar concepto inexistente",
                    extra={"op": "semantic.add_association",
                           "context": f"concept_a={concept_a} concept_b={concept_b}"},
                )
            conn.close()
        except Exception as exc:
            log_db_error(logger, "semantic.add_association", exc,
                         extra_ctx=f"concept_a={concept_a} concept_b={concept_b}")

    def spreading_activation(self, concept: str, depth: int = 2) -> list:
        try:
            visited = {}
            queue   = [(concept, 1.0)]
            conn    = db_connect(self.db)
            c       = conn.cursor()

            for _ in range(depth):
                if not queue:
                    break
                nodes = [n for n, _ in queue if n not in visited]
                if not nodes:
                    break
                placeholders = ",".join("?" * len(nodes))
                c.execute(
                    f"SELECT concept, associations FROM semantic_memory "
                    f"WHERE concept IN ({placeholders})", nodes
                )
                rows = {r[0]: r[1] for r in c.fetchall()}
                next_queue = []
                for node, activation in queue:
                    if node in visited:
                        continue
                    visited[node] = activation
                    assoc_str = rows.get(node)
                    if assoc_str:
                        try:
                            for neighbor, strength in json.loads(assoc_str).items():
                                if neighbor not in visited:
                                    next_queue.append((neighbor, activation * strength * 0.7))
                        except (json.JSONDecodeError, TypeError) as exc:
                            logger.warning(
                                "Asociaciones de nodo corruptas en spreading activation",
                                extra={"op": "semantic.spreading_activation",
                                       "context": f"node={node} err={exc}"},
                            )
                queue = next_queue

            conn.close()
            return [{"concept": k, "activation": v}
                    for k, v in sorted(visited.items(), key=lambda x: -x[1])
                    if k != concept][:8]

        except Exception as exc:
            log_db_error(logger, "semantic.spreading_activation", exc,
                         extra_ctx=f"concept={concept} depth={depth}")
            return []

    def find_related(self, vector: list, top_k: int = 5) -> list:
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT concept, vector, confidence, emotion_avg FROM semantic_memory")
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            log_db_error(logger, "semantic.find_related", exc,
                         extra_ctx=f"top_k={top_k}")
            return []

        scored = []
        for concept, vec_str, conf, emo in rows:
            try:
                vec = json.loads(vec_str)
                sim = cosine_similarity(vector, vec)
                scored.append({"concept": concept, "similarity": sim,
                                "confidence": conf, "emotion_avg": emo})
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "Vector de concepto corrupto en find_related",
                    extra={"op": "semantic.find_related",
                           "context": f"concept={concept} err={exc}"},
                )
                continue

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def get_concept(self, concept: str) -> Optional[dict]:
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT concept, description, vector, confidence, support, emotion_avg "
                      "FROM semantic_memory WHERE concept=?", (concept,))
            row = c.fetchone()
            conn.close()
            if row:
                try:
                    return {"concept": row[0], "description": row[1],
                            "vector": json.loads(row[2]), "confidence": row[3],
                            "support": row[4], "emotion_avg": row[5]}
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "Vector de concepto corrupto en get_concept",
                        extra={"op": "semantic.get_concept",
                               "context": f"concept={concept} err={exc}"},
                    )
                    return None
            return None
        except Exception as exc:
            log_db_error(logger, "semantic.get_concept", exc,
                         extra_ctx=f"concept={concept}")
            return None

    def list_all(self) -> list:
        try:
            conn = db_connect(self.db)
            c = conn.cursor()
            c.execute("SELECT concept, confidence, support, emotion_avg "
                      "FROM semantic_memory ORDER BY confidence DESC")
            rows = [{"concept": r[0], "confidence": r[1],
                     "support": r[2], "emotion_avg": r[3]}
                    for r in c.fetchall()]
            conn.close()
            return rows
        except Exception as exc:
            log_db_error(logger, "semantic.list_all", exc)
            return []

    def detect_contradiction(self, concept: str, new_label: str, vector: list) -> Optional[dict]:
        existing = self.get_concept(concept)
        if not existing:
            return None
        try:
            existing_sim = cosine_similarity(existing["vector"], vector)
        except Exception as exc:
            logger.warning(
                "Error calculando similitud para detección de contradicción",
                extra={"op": "semantic.detect_contradiction",
                       "context": f"concept={concept} err={exc}"},
            )
            return None

        if existing_sim < 0.2 and existing["confidence"] > 0.6:
            logger.info(
                "Contradicción detectada en memoria semántica",
                extra={"op": "semantic.detect_contradiction",
                       "context": f"concept={concept} sim={existing_sim:.2f} conf={existing['confidence']:.2f}"},
            )
            return {
                "concept": concept,
                "existing_confidence": existing["confidence"],
                "contradiction_score": 1.0 - existing_sim,
                "description": f"'{concept}' parece contradecir conocimiento previo (sim={existing_sim:.2f})"
            }
        return None

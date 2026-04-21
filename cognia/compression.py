"""
cognia/compression.py
======================
ConceptCompressor: abstracción conceptual via clustering de embeddings.
GraphEpisodicBridge: integración episodios → knowledge graph (durante sueño).
"""

import json
from datetime import datetime
from typing import List, Tuple
from .database import db_connect
from .vectors import cosine_similarity, vec_norm
from .config import DB_PATH
from .memory.semantic import SemanticMemory
from .knowledge.graph import KnowledgeGraph


class ConceptCompressor:
    """
    Abstracción conceptual mediante clustering de embeddings.

    1. Toma episodios con el mismo label
    2. Calcula centroide de sus embeddings
    3. Detecta outliers (episodios muy distintos al centroide)
    4. Fusiona episodios muy similares en uno solo
    5. Crea/actualiza el concepto semántico abstracto
    """

    def __init__(self, db_path: str = DB_PATH, semantic: SemanticMemory = None):
        self.db = db_path
        self.semantic = semantic or SemanticMemory(db_path)

    def compress_label(self, label: str, similarity_threshold: float = 0.92) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, observation, vector, confidence, emotion_score, importance
            FROM episodic_memory WHERE label=? AND forgotten=0 AND compressed=0
        """, (label,))
        episodes = [{"id": r[0], "observation": r[1], "vector": json.loads(r[2]),
                     "confidence": r[3], "emotion_score": r[4], "importance": r[5]}
                    for r in c.fetchall()]
        conn.close()

        if len(episodes) < 3:
            return {"label": label, "compressed": 0, "reason": "Pocos episodios"}

        dim = len(episodes[0]["vector"])
        centroid = [sum(ep["vector"][i] for ep in episodes) / len(episodes) for i in range(dim)]
        norm = vec_norm(centroid)
        if norm > 0:
            centroid = [x / norm for x in centroid]

        to_compress = [ep["id"] for ep in episodes
                       if cosine_similarity(ep["vector"], centroid) > similarity_threshold]

        if to_compress:
            conn = db_connect(self.db)
            c = conn.cursor()
            placeholders = ",".join("?" * len(to_compress))
            c.execute(f"UPDATE episodic_memory SET compressed=1 WHERE id IN ({placeholders})", to_compress)
            conn.commit()
            conn.close()

        avg_emo = sum(ep["emotion_score"] for ep in episodes) / len(episodes)
        self.semantic.update_concept(
            label, centroid,
            description=f"Concepto abstracto de {len(episodes)} experiencias (comprimidas: {len(to_compress)})",
            confidence_delta=0.08,
            emotion_score=avg_emo
        )

        outliers = [{"id": ep["id"], "observation": ep["observation"][:50],
                     "sim": cosine_similarity(ep["vector"], centroid)}
                    for ep in episodes if cosine_similarity(ep["vector"], centroid) < 0.4]

        return {
            "label": label,
            "total_episodes": len(episodes),
            "compressed": len(to_compress),
            "outliers": len(outliers),
            "centroid_quality": round(
                sum(cosine_similarity(ep["vector"], centroid) for ep in episodes) / len(episodes), 3
            )
        }

    def compress_all(self, min_episodes: int = 3, batch_size: int = 80) -> dict:
        """Comprime labels con suficientes episodios sin comprimir (en batch)."""
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT label, COUNT(*) as cnt FROM episodic_memory
            WHERE forgotten=0 AND label IS NOT NULL AND compressed=0
            GROUP BY label HAVING cnt >= ? ORDER BY cnt DESC LIMIT ?
        """, (min_episodes, batch_size))
        labels = [r[0] for r in c.fetchall()]
        conn.close()

        total_compressed = 0
        results = []
        for label in labels:
            result = self.compress_label(label)
            total_compressed += result.get("compressed", 0)
            results.append(result)

        return {"labels_processed": len(labels), "total_compressed": total_compressed, "details": results}


class GraphEpisodicBridge:
    """
    Integra automáticamente episodios con el knowledge graph durante el sueño.
    """

    def __init__(self, db_path: str = DB_PATH, kg: KnowledgeGraph = None):
        self.db = db_path
        self.kg = kg or KnowledgeGraph(db_path)

    def _is_valid_node(self, node: str) -> bool:
        if not node or not node.strip():
            return False
        node = node.strip()
        if len(node) < 2 or node.isdigit():
            return False
        stopwords = {"el", "la", "los", "las", "un", "una", "de", "en",
                     "a", "y", "o", "que", "es", "se", "no", "si",
                     "the", "an", "is", "it", "of", "in", "to"}
        return node.lower() not in stopwords

    def process_episode(self, observation: str, label: str) -> List[Tuple]:
        if not label:
            return []
        triples = self.kg.extract_triples_from_text(observation, label)
        added = []
        for subj, pred, obj in triples:
            if subj and obj and self._is_valid_node(subj) and self._is_valid_node(obj):
                is_new = self.kg.add_triple(subj, pred, obj, weight=0.6)
                if is_new:
                    added.append((subj, pred, obj))
        return added

    def process_recent_episodes(self, limit: int = 20) -> dict:
        conn = db_connect(self.db)
        c = conn.cursor()
        c.execute("""
            SELECT id, observation, label FROM episodic_memory
            WHERE forgotten=0 AND label IS NOT NULL ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        episodes = c.fetchall()
        conn.close()

        total_triples = 0
        processed = 0
        for ep_id, observation, label in episodes:
            triples = self.process_episode(observation, label)
            total_triples += len(triples)
            processed += 1

        return {"episodes_processed": processed, "triples_added": total_triples}

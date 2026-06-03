"""
cognia/memory/memory_compressor.py
===================================
Semantic Memory Compression — clusters similar episodes and merges them
into macro-episodes, keeping total count bounded.

Inspired by synaptic homeostasis theory (Tononi): the brain consolidates
similar memories to free capacity while preserving information.

Algorithm:
1. Load all episodes with embeddings from the DB
2. Group by label (concept anchor)
3. Within each label group, find clusters of episodes with cosine_sim > CLUSTER_THRESHOLD
4. For clusters with >= MIN_CLUSTER_SIZE episodes:
   a. Compute centroid embedding (mean of normalized embeddings)
   b. Create a macro-episode with:
      - content: most important sentence from each member (by importance score)
      - embedding: centroid
      - importance: max(member importances) * 0.9  (slight decay)
      - label: same label
      - metadata: {'merged_from': [ep_ids], 'compression_ratio': N}
   c. DELETE the original episodes
   d. INSERT the macro-episode
5. Run when total episodes > COMPRESS_THRESHOLD

WHY greedy clustering (not k-means): episodes arrive incrementally, no N
known in advance, and we prefer small dense clusters over large sparse ones.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

import numpy as np

from storage.db_pool import db_connect_pooled as db_connect

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────
CLUSTER_THRESHOLD  = 0.90   # cosine similarity to consider episodes "same cluster"
MIN_CLUSTER_SIZE   = 4      # minimum episodes to merge
COMPRESS_THRESHOLD = 800    # trigger compression when over this many episodes
TARGET_EPISODES    = 600    # aim to reduce to this many after compression


class MemoryCompressor:
    """
    Compresses episodic memory by clustering semantically similar episodes
    into macro-episodes, keeping total episode count bounded.

    Requires a cognia instance (or any object with .db attribute pointing
    to the SQLite DB path used by EpisodicMemory).
    """

    def __init__(self, cognia_instance) -> None:
        self._cognia = cognia_instance

    # ── Public API ──────────────────────────────────────────────────────

    def should_compress(self) -> bool:
        """Return True if active episode count exceeds COMPRESS_THRESHOLD."""
        try:
            conn = db_connect(self._cognia.db)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten = 0")
            count = c.fetchone()[0]
            conn.close()
            return count > COMPRESS_THRESHOLD
        except Exception as exc:
            logger.warning("memory_compressor.should_compress error: %s", exc)
            return False

    def compress(self) -> dict:
        """
        Run one compression pass.

        Returns:
            dict with keys: episodes_before, episodes_after, merged_clusters, freed
        """
        episodes_before = self._count_active()
        merged_clusters = 0

        episodes = self._load_episodes_with_embeddings()
        if not episodes:
            return {
                "episodes_before": episodes_before,
                "episodes_after": episodes_before,
                "merged_clusters": 0,
                "freed": 0,
            }

        # Group by label — cluster only within same concept anchor
        by_label: dict[str, list[dict]] = {}
        for ep in episodes:
            lbl = ep.get("label") or "__no_label__"
            by_label.setdefault(lbl, []).append(ep)

        for label, group in by_label.items():
            if len(group) < MIN_CLUSTER_SIZE:
                continue

            clusters = self._find_clusters(group)
            for cluster in clusters:
                macro = self._merge_cluster(cluster)
                ep_ids = [ep["id"] for ep in cluster]
                self._delete_episodes(ep_ids)
                self._insert_macro_episode(macro)
                merged_clusters += 1

            # Stop early once we reach TARGET_EPISODES
            if self._count_active() <= TARGET_EPISODES:
                break

        episodes_after = self._count_active()

        # Invalidate VectorCache so next retrieval picks up macro-episodes
        try:
            from cognia.memory.episodic_fast import get_vector_cache
            get_vector_cache(self._cognia.db).mark_dirty()
        except Exception:
            pass

        result = {
            "episodes_before": episodes_before,
            "episodes_after": episodes_after,
            "merged_clusters": merged_clusters,
            "freed": max(0, episodes_before - episodes_after),
        }
        logger.info(
            "MemoryCompressor: compression complete "
            "before=%d after=%d clusters=%d freed=%d",
            result["episodes_before"], result["episodes_after"],
            result["merged_clusters"], result["freed"],
        )
        return result

    # ── Internal helpers ────────────────────────────────────────────────

    def _count_active(self) -> int:
        try:
            conn = db_connect(self._cognia.db)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM episodic_memory WHERE forgotten = 0")
            n = c.fetchone()[0]
            conn.close()
            return n
        except Exception:
            return 0

    def _load_episodes_with_embeddings(self) -> list[dict]:
        """
        Load active episodes that have non-null vector embeddings.
        Returns list of dicts: id, content, embedding (np.ndarray), importance, label.
        """
        try:
            conn = db_connect(self._cognia.db)
            c = conn.cursor()
            c.execute("""
                SELECT id, observation, label, vector, importance
                FROM episodic_memory
                WHERE forgotten = 0
                  AND vector IS NOT NULL
                  AND vector != 'null'
                  AND vector != '[]'
                ORDER BY importance DESC
            """)
            rows = c.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("memory_compressor._load_episodes error: %s", exc)
            return []

        result = []
        for ep_id, observation, label, vec_str, importance in rows:
            try:
                vec = json.loads(vec_str)
                if not vec or not isinstance(vec, list):
                    continue
                arr = np.array(vec, dtype=np.float32)
                if arr.ndim != 1 or arr.size == 0:
                    continue
                result.append({
                    "id":        ep_id,
                    "content":   observation or "",
                    "label":     label or "",
                    "embedding": arr,
                    "importance": float(importance) if importance is not None else 1.0,
                })
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        return result

    def _find_clusters(self, episodes: list[dict]) -> list[list[dict]]:
        """
        Greedy clustering: for each unvisited episode, find all episodes
        with cosine similarity > CLUSTER_THRESHOLD.
        Only returns clusters with >= MIN_CLUSTER_SIZE members.
        """
        if len(episodes) < MIN_CLUSTER_SIZE:
            return []

        # Pre-normalise all embeddings for fast cosine via dot product
        arrs = np.stack([ep["embedding"] for ep in episodes])  # (N, D)
        norms = np.linalg.norm(arrs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normed = arrs / norms                                   # (N, D)

        visited = [False] * len(episodes)
        clusters: list[list[dict]] = []

        for i in range(len(episodes)):
            if visited[i]:
                continue

            # Cosine similarities from episode i to all others
            sims = normed @ normed[i]       # (N,) — dot product with normalised vectors

            # Collect all members with sim > threshold (including i itself)
            members = [
                episodes[j]
                for j in range(len(episodes))
                if not visited[j] and float(sims[j]) > CLUSTER_THRESHOLD
            ]

            if len(members) >= MIN_CLUSTER_SIZE:
                clusters.append(members)
                # Mark all members as visited to avoid double-clustering
                member_ids = {ep["id"] for ep in members}
                for j in range(len(episodes)):
                    if episodes[j]["id"] in member_ids:
                        visited[j] = True
            else:
                # Only skip this one episode — don't mark others
                visited[i] = True

        return clusters

    def _merge_cluster(self, cluster: list[dict]) -> dict:
        """
        Create a macro-episode from a cluster.

        Content: taken from the highest-importance member.
        Embedding: mean of L2-normalised member embeddings (centroid), re-normalised.
        Importance: max(importances) * 0.9 (slight decay — consolidated memories fade a little).
        """
        # Pick content from highest-importance member
        best = max(cluster, key=lambda ep: ep["importance"])
        content = best["content"]
        label   = best["label"]

        # Centroid: mean of normalised embeddings, then re-normalise
        arrs = np.stack([ep["embedding"] for ep in cluster])   # (N, D)
        norms = np.linalg.norm(arrs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normed = arrs / norms
        centroid = normed.mean(axis=0)
        c_norm = np.linalg.norm(centroid)
        if c_norm > 0:
            centroid = centroid / c_norm

        max_importance = max(ep["importance"] for ep in cluster)
        ep_ids = [ep["id"] for ep in cluster]

        return {
            "content":    content,
            "label":      label,
            "embedding":  centroid,
            "importance": round(max_importance * 0.9, 4),
            "metadata":   {
                "merged_from":        ep_ids,
                "compression_ratio":  len(cluster),
                "compressed_at":      datetime.now().isoformat(),
            },
        }

    def _delete_episodes(self, ep_ids: list[int]) -> None:
        """
        Soft-delete (forgotten=1) the original episodes that were merged.
        Using soft-delete for consistency with the rest of the consolidation pipeline.
        """
        if not ep_ids:
            return
        try:
            conn = db_connect(self._cognia.db)
            now = datetime.now().isoformat()
            conn.cursor().executemany(
                "UPDATE episodic_memory SET forgotten = 1, last_access = ? WHERE id = ?",
                [(now, ep_id) for ep_id in ep_ids],
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(
                "memory_compressor._delete_episodes error ids=%s: %s",
                ep_ids[:5], exc,
            )

    def _insert_macro_episode(self, macro: dict) -> None:
        """
        Insert the macro-episode into episodic_memory using the same schema
        as EpisodicMemory.store().
        """
        try:
            conn = db_connect(self._cognia.db)
            c = conn.cursor()
            now = datetime.now().isoformat()
            vec_json = json.dumps(macro["embedding"].tolist())
            meta_str = json.dumps(macro["metadata"])
            c.execute("""
                INSERT INTO episodic_memory
                (timestamp, observation, label, vector, confidence, last_access,
                 importance, emotion_score, emotion_label, surprise,
                 review_count, next_review, context_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                macro["content"],
                macro["label"],
                vec_json,
                0.7,           # reasonable starting confidence for a macro-episode
                now,
                macro["importance"],
                0.0,           # neutral emotion for compressed macro
                "neutral",
                0.0,
                0,
                now,           # next_review = now (eligible for review immediately)
                meta_str,      # context_tags stores compression metadata as JSON
            ))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("memory_compressor._insert_macro_episode error: %s", exc)

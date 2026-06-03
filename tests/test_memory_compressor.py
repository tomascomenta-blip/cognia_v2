"""
tests/test_memory_compressor.py
================================
Unit tests for MemoryCompressor.

Uses an in-memory SQLite DB instead of mocking db_pool, so tests are
self-contained and don't need a real cognia instance.
"""

import json
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# ---------------------------------------------------------------------------
# Minimal in-memory SQLite setup that mirrors episodic_memory schema
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS episodic_memory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT,
    observation   TEXT,
    label         TEXT,
    vector        TEXT,
    confidence    REAL DEFAULT 0.5,
    last_access   TEXT,
    importance    REAL DEFAULT 1.0,
    emotion_score REAL DEFAULT 0.0,
    emotion_label TEXT DEFAULT 'neutral',
    surprise      REAL DEFAULT 0.0,
    review_count  INTEGER DEFAULT 0,
    next_review   TEXT,
    context_tags  TEXT,
    feedback_weight REAL DEFAULT 1.0,
    access_count  INTEGER DEFAULT 0,
    forgotten     INTEGER DEFAULT 0
)
"""


def _make_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the episodic_memory table."""
    conn = sqlite3.connect(":memory:")
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def _insert_episode(conn, observation, label, vector, importance=1.0, forgotten=0):
    now = "2026-06-02T00:00:00"
    conn.execute("""
        INSERT INTO episodic_memory
        (timestamp, observation, label, vector, confidence, last_access,
         importance, emotion_score, emotion_label, surprise,
         review_count, next_review, context_tags, forgotten)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now, observation, label, json.dumps(vector), 0.6, now,
          importance, 0.0, "neutral", 0.0, 0, now, "[]", forgotten))
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# ---------------------------------------------------------------------------
# Patch db_connect to return our in-memory connection
# ---------------------------------------------------------------------------

class _FakeCognia:
    """Minimal stand-in for a Cognia instance."""
    def __init__(self, db_conn: sqlite3.Connection):
        self._conn = db_conn
        self.db = ":memory:"


class _NoCloseConn:
    """
    Thin wrapper around sqlite3.Connection that suppresses close() calls.
    Needed because in-memory SQLite DBs are destroyed on close(), which
    breaks tests that patch db_connect to return the same connection object
    across multiple calls.
    """
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def close(self):
        pass  # intentionally a no-op

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _make_compressor(conn: sqlite3.Connection):
    """Return a MemoryCompressor patched to use the provided in-memory connection."""
    from cognia.memory.memory_compressor import MemoryCompressor
    fake_cognia = _FakeCognia(conn)
    wrapped = _NoCloseConn(conn)

    with patch("cognia.memory.memory_compressor.db_connect", return_value=wrapped):
        compressor = MemoryCompressor(fake_cognia)

    return compressor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestShouldCompress(unittest.TestCase):

    def test_should_compress_above_threshold(self):
        """801 active episodes -> should_compress() returns True."""
        conn = _make_db()
        vec = [0.1, 0.2, 0.3]
        for i in range(801):
            _insert_episode(conn, f"obs {i}", "label_a", vec)

        from cognia.memory.memory_compressor import MemoryCompressor
        fake = _FakeCognia(conn)
        wrapped = _NoCloseConn(conn)

        with patch("cognia.memory.memory_compressor.db_connect", return_value=wrapped):
            compressor = MemoryCompressor(fake)
            result = compressor.should_compress()

        self.assertTrue(result, "Expected True for 801 episodes (threshold=800)")

    def test_should_compress_below_threshold(self):
        """799 active episodes -> should_compress() returns False."""
        conn = _make_db()
        vec = [0.1, 0.2, 0.3]
        for i in range(799):
            _insert_episode(conn, f"obs {i}", "label_a", vec)

        from cognia.memory.memory_compressor import MemoryCompressor
        fake = _FakeCognia(conn)
        wrapped = _NoCloseConn(conn)

        with patch("cognia.memory.memory_compressor.db_connect", return_value=wrapped):
            compressor = MemoryCompressor(fake)
            result = compressor.should_compress()

        self.assertFalse(result, "Expected False for 799 episodes (threshold=800)")


class TestFindClusters(unittest.TestCase):

    def _make_similar_episodes(self, n: int, base_vec=None):
        """Create n episodes with very similar (high cosine sim) vectors."""
        if base_vec is None:
            base_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        episodes = []
        for i in range(n):
            # Tiny perturbation — sim will be > 0.90
            noise = np.random.default_rng(i).uniform(-0.001, 0.001, size=base_vec.shape).astype(np.float32)
            vec = base_vec + noise
            episodes.append({
                "id": i,
                "content": f"obs {i}",
                "label": "test",
                "embedding": vec.astype(np.float32),
                "importance": 1.0,
            })
        return episodes

    def test_find_clusters_groups_similar(self):
        """5 nearly-identical episodes -> 1 cluster of 5."""
        from cognia.memory.memory_compressor import MemoryCompressor
        fake = MagicMock()
        fake.db = ":memory:"
        compressor = MemoryCompressor(fake)

        episodes = self._make_similar_episodes(5)
        clusters = compressor._find_clusters(episodes)

        self.assertEqual(len(clusters), 1, "Expected exactly 1 cluster")
        self.assertEqual(len(clusters[0]), 5, "Cluster should contain all 5 episodes")

    def test_find_clusters_rejects_small(self):
        """3 similar episodes -> no cluster returned (< MIN_CLUSTER_SIZE=4)."""
        from cognia.memory.memory_compressor import MemoryCompressor
        fake = MagicMock()
        fake.db = ":memory:"
        compressor = MemoryCompressor(fake)

        episodes = self._make_similar_episodes(3)
        clusters = compressor._find_clusters(episodes)

        self.assertEqual(len(clusters), 0, "Expected no clusters for 3 episodes (min=4)")


class TestMergeCluster(unittest.TestCase):

    def test_merge_cluster_centroid(self):
        """Merged embedding should be the normalised mean of normalised input vectors."""
        from cognia.memory.memory_compressor import MemoryCompressor
        fake = MagicMock()
        fake.db = ":memory:"
        compressor = MemoryCompressor(fake)

        # Four orthogonally-similar vectors in 3D
        vecs = [
            np.array([1.0, 0.1, 0.0], dtype=np.float32),
            np.array([1.0, 0.0, 0.1], dtype=np.float32),
            np.array([0.9, 0.1, 0.1], dtype=np.float32),
            np.array([1.0, 0.05, 0.05], dtype=np.float32),
        ]
        cluster = [
            {"id": i, "content": f"c{i}", "label": "lbl",
             "embedding": v, "importance": 1.0}
            for i, v in enumerate(vecs)
        ]
        macro = compressor._merge_cluster(cluster)

        # Verify the macro embedding is a unit vector (normalised centroid)
        emb = macro["embedding"]
        norm = float(np.linalg.norm(emb))
        self.assertAlmostEqual(norm, 1.0, places=5,
                               msg="Macro embedding should be unit-normalised")

        # Verify it matches manually computed centroid
        normed = np.array([v / np.linalg.norm(v) for v in vecs])
        centroid = normed.mean(axis=0)
        centroid /= np.linalg.norm(centroid)
        np.testing.assert_allclose(emb, centroid, atol=1e-5)

    def test_merge_takes_highest_importance_content(self):
        """Cluster member with highest importance should provide the content."""
        from cognia.memory.memory_compressor import MemoryCompressor
        fake = MagicMock()
        fake.db = ":memory:"
        compressor = MemoryCompressor(fake)

        cluster = [
            {"id": 0, "content": "low importance content", "label": "lbl",
             "embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32), "importance": 0.3},
            {"id": 1, "content": "HIGH IMPORTANCE CONTENT", "label": "lbl",
             "embedding": np.array([0.99, 0.1, 0.0], dtype=np.float32), "importance": 0.9},
            {"id": 2, "content": "medium importance content", "label": "lbl",
             "embedding": np.array([0.98, 0.0, 0.1], dtype=np.float32), "importance": 0.5},
            {"id": 3, "content": "another low content", "label": "lbl",
             "embedding": np.array([0.97, 0.1, 0.1], dtype=np.float32), "importance": 0.2},
        ]
        macro = compressor._merge_cluster(cluster)

        self.assertEqual(macro["content"], "HIGH IMPORTANCE CONTENT",
                         "Macro content should come from the highest-importance member")
        # Importance should be max * 0.9
        self.assertAlmostEqual(macro["importance"], 0.9 * 0.9, places=3)


if __name__ == "__main__":
    unittest.main()

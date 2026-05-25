"""
tests/test_attention_integration.py
=====================================
Integration tests for VectorCache (episodic_fast) and CompressedKVCache (mla).
Pattern: mock db_connect with shared-memory URI, verify RLock safety and TTL eviction.
"""

import json
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np


# ── helpers ─────────────────────────────────────────────────────────────────

DIM = 8  # tiny dim for speed
_SHARED_URI = "file:test_episodic_shared?mode=memory&cache=shared"


def _shared_conn() -> sqlite3.Connection:
    """Open a new connection to the shared in-memory DB (survives close())."""
    conn = sqlite3.connect(_SHARED_URI, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _vec(seed: int, dim: int = DIM) -> list:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()


def _create_episodic_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            observation     TEXT    NOT NULL,
            label           TEXT    DEFAULT '',
            vector          BLOB,
            confidence      REAL    DEFAULT 0.5,
            importance      REAL    DEFAULT 1.0,
            emotion_score   REAL    DEFAULT 0.0,
            emotion_label   TEXT    DEFAULT '',
            surprise        REAL    DEFAULT 0.0,
            feedback_weight REAL    DEFAULT 1.0,
            forgotten       INTEGER DEFAULT 0,
            timestamp       REAL    DEFAULT 0.0
        )
    """)
    conn.commit()


def _insert_episode(conn, obs, seed, importance=1.0, forgotten=0):
    v = json.dumps(_vec(seed))
    conn.execute(
        """INSERT INTO episodic_memory
           (observation, label, vector, confidence, importance, forgotten, timestamp)
           VALUES (?,?,?,?,?,?,?)""",
        (obs, "test", v, 0.8, importance, forgotten, time.time()),
    )
    conn.commit()


# ── Test 1: build + search ───────────────────────────────────────────────────

class TestVectorCacheBuildAndSearch(unittest.TestCase):

    def setUp(self):
        self._setup = _shared_conn()
        self._setup.execute("DROP TABLE IF EXISTS episodic_memory")
        self._setup.commit()
        _create_episodic_schema(self._setup)

    def tearDown(self):
        self._setup.close()

    def test_build_and_top1_correct(self):
        from cognia.memory.episodic_fast import VectorCache

        _insert_episode(self._setup, "alpha", seed=1)
        _insert_episode(self._setup, "beta",  seed=2)
        _insert_episode(self._setup, "gamma", seed=3)

        cache = VectorCache(_SHARED_URI)
        with patch("cognia.memory.episodic_fast.db_connect", side_effect=lambda p: _shared_conn()):
            cache.build()
            results = cache.search(_vec(1), top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["observation"], "alpha")

    def test_forgotten_excluded(self):
        from cognia.memory.episodic_fast import VectorCache

        _insert_episode(self._setup, "visible",   seed=10)
        _insert_episode(self._setup, "forgotten", seed=11, forgotten=1)

        cache = VectorCache(_SHARED_URI)
        with patch("cognia.memory.episodic_fast.db_connect", side_effect=lambda p: _shared_conn()):
            cache.build()
            results = cache.search(_vec(10), top_k=5)

        obs = [r["observation"] for r in results]
        self.assertIn("visible", obs)
        self.assertNotIn("forgotten", obs)


# ── Test 2: concurrent reads (RLock safety) ───────────────────────────────────

class TestVectorCacheConcurrentReads(unittest.TestCase):

    def setUp(self):
        self._setup = _shared_conn()
        self._setup.execute("DROP TABLE IF EXISTS episodic_memory")
        self._setup.commit()
        _create_episodic_schema(self._setup)
        for i in range(10):
            _insert_episode(self._setup, f"ep_{i}", seed=i)

    def tearDown(self):
        self._setup.close()

    def test_no_deadlock_under_parallel_search(self):
        from cognia.memory.episodic_fast import VectorCache

        cache = VectorCache(_SHARED_URI)
        errors = []

        # Apply patch once outside threads — patch() is not thread-safe when
        # used inside concurrent workers (threads race on the module attribute,
        # leaving a stale mock after one thread's __exit__ wins).
        with patch("cognia.memory.episodic_fast.db_connect", side_effect=lambda p: _shared_conn()):
            cache.build()

            def _worker(seed):
                try:
                    cache.search(_vec(seed), top_k=3)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=_worker, args=(s,)) for s in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Errors under concurrent reads: {errors}")


# ── Test 3: mark_dirty triggers rebuild ──────────────────────────────────────

class TestVectorCacheDirtyRebuild(unittest.TestCase):

    def setUp(self):
        self._setup = _shared_conn()
        self._setup.execute("DROP TABLE IF EXISTS episodic_memory")
        self._setup.commit()
        _create_episodic_schema(self._setup)

    def tearDown(self):
        self._setup.close()

    def test_dirty_flag_causes_rebuild_on_next_search(self):
        from cognia.memory.episodic_fast import VectorCache, DEBOUNCE_S

        _insert_episode(self._setup, "first", seed=20)

        cache = VectorCache(_SHARED_URI)
        with patch("cognia.memory.episodic_fast.db_connect", side_effect=lambda p: _shared_conn()):
            cache.build()
            initial_count = len(cache._meta)

            _insert_episode(self._setup, "second", seed=21)
            cache.mark_dirty()
            cache._dirty_since = time.monotonic() - (DEBOUNCE_S + 1)

            cache.search(_vec(20), top_k=5)
            self.assertGreater(len(cache._meta), initial_count)


# ── Test 4: CompressedKVCache evict_stale ────────────────────────────────────

class TestCompressedKVCacheEviction(unittest.TestCase):

    def test_evict_stale_removes_old_sessions(self):
        from shattering.mla import CompressedKVCache

        cache = CompressedKVCache()
        c_kv = np.zeros((4, 512), dtype=np.float32)

        cache.put("session_fresh", 0, c_kv, 4)
        cache.put("session_stale", 0, c_kv, 4)

        cache._last_access["session_stale"] = time.monotonic() - 4001

        evicted = cache.evict_stale(max_age_seconds=4000)

        self.assertEqual(evicted, 1)
        self.assertIn("session_fresh", cache._cache)
        self.assertNotIn("session_stale", cache._cache)

    def test_active_session_not_evicted(self):
        from shattering.mla import CompressedKVCache

        cache = CompressedKVCache()
        c_kv = np.zeros((2, 512), dtype=np.float32)
        cache.put("live", 0, c_kv, 2)

        evicted = cache.evict_stale(max_age_seconds=3600)
        self.assertEqual(evicted, 0)
        self.assertIn("live", cache._cache)


if __name__ == "__main__":
    unittest.main()

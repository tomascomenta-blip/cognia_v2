"""
tests/test_semantic_cache.py — unit tests for SemanticResponseCache (SRC)
Uses a temp SQLite file + real db_pool to avoid touching production DB.
"""

import os
import sys
import tempfile
import threading
import time

import pytest

# Ensure repo root is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from storage.db_pool import SQLitePool, close_pool
from cognia.semantic_cache import SemanticResponseCache


@pytest.fixture()
def cache(tmp_path):
    db_file = str(tmp_path / "test_src.db")
    pool = SQLitePool(db_file)

    src = SemanticResponseCache(
        db_pool=pool,
        ttl_days=7,
        sim_threshold=0.92,
        max_entries=500,
    )
    yield src, pool, db_file

    # cleanup — drain pool so Windows can delete the temp file
    close_pool(db_file)


def test_store_and_lookup_exact(cache):
    """Store a response, look it up with the exact same question — must be a HIT."""
    src, pool, _ = cache
    q = "What is the capital of France?"
    r = "The capital of France is Paris."

    src.store(q, r, model="test")
    result = src.lookup(q)
    assert result == r


def test_normalization_hit(cache):
    """Storing 'what is python' and looking up 'what is Python?' should be a HIT."""
    src, pool, _ = cache
    q_store  = "what is python"
    q_lookup = "What is Python?"
    r = "Python is a high-level programming language."

    src.store(q_store, r, model="test")
    result = src.lookup(q_lookup)
    assert result == r


def test_different_question_miss(cache):
    """A completely unrelated question must be a MISS."""
    src, pool, _ = cache
    src.store("what is python", "Python is a programming language.", model="test")

    result = src.lookup("how do I bake chocolate cake")
    assert result is None


def test_expired_entry_miss(cache):
    """An entry whose timestamp is beyond TTL must not be returned."""
    src, pool, _ = cache
    q = "what is the speed of light"
    r = "The speed of light is approximately 299,792,458 m/s."
    src.store(q, r, model="test")

    # Back-date the entry so it exceeds the TTL
    with pool.get() as conn:
        past_ts = time.time() - (8 * 86400)   # 8 days ago, TTL is 7
        conn.execute("UPDATE semantic_cache SET timestamp = ?", (past_ts,))

    result = src.lookup(q)
    assert result is None


def test_stats_after_stores(cache):
    """stats() must return a valid dict with entries > 0 after storing."""
    src, pool, _ = cache
    src.store("what is machine learning", "ML is a subset of AI.", model="test")
    src.store("what is deep learning", "DL uses neural networks.", model="test")

    s = src.stats()
    assert isinstance(s, dict)
    assert s["entries"] >= 2
    assert "total_hits" in s
    assert "hit_rate" in s
    assert 0.0 <= s["hit_rate"] <= 1.0


def test_hit_survives_vocab_drift(cache):
    """An early-cached question must STILL hit after later stores drift the
    TF-IDF vocabulary. Regression for the stale-vector bug: lookup() used to
    deserialize the persisted tfidf_vector (computed against the store-time
    vocab snapshot) and compare it against qvec built from the current vocab —
    a different basis — so any entry stored before the vocab last changed turned
    into a silent MISS. The fix recomputes the candidate vector from its stored
    tokens against the current vocab (same approach as thought_cache)."""
    src, pool, _ = cache
    q1 = "what is the capital of france paris europe"
    r1 = "Paris is the capital of France."
    src.store(q1, r1, model="test")
    assert src.lookup(q1) == r1  # hits before any drift

    # Store unrelated questions to grow + re-order the vocabulary
    for o in (
        "how do neural networks learn weights gradient descent backpropagation",
        "what is photosynthesis chlorophyll plants sunlight energy conversion",
        "explain quantum entanglement particles superposition measurement physics",
        "best recipe chocolate cake flour sugar eggs butter baking oven heat",
        "history of the roman empire caesar augustus senate legions conquest",
    ):
        src.store(o, "resp " + o[:15], model="test")

    # The exact same early question must still be a HIT despite vocab drift
    assert src.lookup(q1) == r1


def test_max_entries_eviction(tmp_path):
    """When entries exceed max_entries, oldest entries are pruned."""
    db_file = str(tmp_path / "eviction_test.db")
    pool = SQLitePool(db_file)
    # Use a small max_entries to trigger eviction quickly
    src = SemanticResponseCache(db_pool=pool, ttl_days=7, sim_threshold=0.92, max_entries=5)

    # Store more entries than max_entries
    for i in range(8):
        src.store(f"unique question number {i} about topic", f"Response {i}", model="test")

    s = src.stats()
    # After eviction, entries should be <= max_entries
    assert s["entries"] <= 5

    close_pool(db_file)


def test_thread_safety(tmp_path):
    """10 concurrent threads doing reads and writes must not crash or corrupt."""
    db_file = str(tmp_path / "thread_test.db")
    pool = SQLitePool(db_file)
    src = SemanticResponseCache(db_pool=pool, ttl_days=7, sim_threshold=0.92, max_entries=500)

    errors = []

    def worker(i):
        try:
            q = f"thread question {i} about python programming language"
            r = f"Thread response {i} about Python."
            src.store(q, r, model="test")
            result = src.lookup(q)
            # result may be None (vocab not yet built for first store) or the response
            _ = src.stats()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Thread errors: {errors}"

    close_pool(db_file)

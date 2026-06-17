"""
tests/test_response_cache.py
============================
Direct tests for cognia_v3.interfaces.response_cache.ResponseCache (PRODUCTION
module, imported by cognia/language_engine + cognia_v3/interfaces/language_engine).
It had no test coverage; this file adds it so the db_pool migration (FASE 0b) is
verified.

Includes a REGRESSION guard for the db_pool migration gotcha: _db_delete_concept
and _db_clear_expired used conn.total_changes, which is CUMULATIVE on a reused
pooled connection. Post-migration they must read cursor.rowcount so the returned
delete count is exact. The exact-count asserts below fail if total_changes leaks.
"""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia_v3.interfaces.response_cache import ResponseCache, CacheEntry
from storage.db_pool import close_pool


def _unlink_db(path: str) -> None:
    try:
        _c = sqlite3.connect(path)
        _c.execute("PRAGMA wal_checkpoint(FULL)")
        _c.execute("PRAGMA journal_mode=DELETE")
        _c.close()
    except Exception:
        pass
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


@pytest.fixture()
def cache():
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    path = tf.name
    rc = ResponseCache(db_path=path)   # __init__ runs _init_db (CREATE TABLE)
    yield rc, path
    close_pool(path)
    _unlink_db(path)


def _vec(seed=0.0):
    # 64-dim vector; identical seed -> cosine 1.0 (hit)
    return [1.0, seed] + [0.0] * 62


def test_store_then_get_hit(cache):
    rc, _ = cache
    v = _vec()
    rc.store("que es python", "Python es un lenguaje", v, concept="python",
             confidence=0.8, used_llm=False)
    hit = rc.get("que es python?", v)
    assert hit is not None
    assert "Python" in hit.response


def test_get_miss_on_dissimilar(cache):
    rc, _ = cache
    rc.store("q1", "r1", [1.0, 0.0] + [0.0] * 62, concept="c1", used_llm=False)
    hit = rc.get("q2", [0.0, 1.0] + [0.0] * 62)   # orthogonal -> miss
    assert hit is None


def _persist(rc, *, concept="c", ts=None, ttl=99999.0):
    """Insert one row through the POOLED write path (_persist_to_db)."""
    e = CacheEntry(question="q", response="r", vector=[0.0],
                   concept=concept, confidence=0.5, used_llm=False,
                   timestamp=ts if ts is not None else time.time(), ttl=ttl)
    rc._persist_to_db(e)


def test_db_delete_concept_returns_exact_count(cache):
    """REGRESSION (db_pool): count must be rows-deleted (cursor.rowcount), NOT
    conn.total_changes — cumulative on a reused pooled connection.

    Writing 6 'dup' rows through the pool guarantees every pooled connection has
    prior INSERT changes, so the DELETE's connection carries leftover total_changes;
    only a rowcount-based count returns the exact 6."""
    rc, _ = cache
    for _ in range(6):
        _persist(rc, concept="dup")
    _persist(rc, concept="other")     # must NOT be counted
    n = rc._db_delete_concept("dup")
    assert n == 6


def test_db_clear_expired_returns_exact_count(cache):
    """REGRESSION (db_pool): same total_changes-vs-rowcount guard for clear_expired."""
    rc, _ = cache
    old = time.time() - 10_000
    for _ in range(6):
        _persist(rc, ts=old, ttl=1.0)     # 6 expired rows (pooled writes)
    _persist(rc, ts=time.time(), ttl=99999.0)   # 1 fresh row, must survive
    removed = rc._db_clear_expired()
    assert removed == 6


def test_stats_shape(cache):
    rc, _ = cache
    rc.store("q", "r", _vec(), used_llm=False)
    rc.get("q", _vec())          # one hit
    rc.get("zzz", [0.0, 1.0] + [0.0] * 62)  # one miss
    s = rc.stats()
    assert {"ram_entries", "hits", "misses", "hit_rate"} <= set(s.keys())
    assert s["hits"] >= 1

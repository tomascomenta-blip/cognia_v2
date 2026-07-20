"""
tests/test_db_pool_gc_reclaim.py
================================
Regression for the CRITICO pool-leak gotcha (vault Gotchas.md): a call-site with
close() INSIDE a try block leaks the pooled connection when an exception skips the
close(). Without a safety net, 5 such leaks drain the Queue(maxsize=5) and every
later acquire() stalls 10s. The fix is _PooledConnection.__del__, which returns the
connection to the pool on GC (rollback first). This test proves leaked connections
are reclaimed and pool_stats exposes the gc_reclaimed counter.
"""

import gc
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.db_pool import (
    SQLitePool, _PooledConnection, db_connect_pooled, get_pool, pool_stats, close_pool,
)


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "pool.db")
    yield path
    close_pool(path)
    for s in ("", "-wal", "-shm"):
        try:
            os.unlink(path + s)
        except FileNotFoundError:
            pass


def test_leaked_connection_reclaimed_on_gc(db):
    pool = get_pool(db)
    size = pool.size
    # Leak MORE than the pool size: acquire via db_connect_pooled and drop the ref
    # WITHOUT close() (simulating an exception that skipped close()).
    for _ in range(size + 2):
        c = db_connect_pooled(db)
        c.execute("SELECT 1")     # use it (read; no open txn)
        del c                      # no close() -> __del__ must reclaim
        gc.collect()

    stats = pool_stats()[db]
    # All pooled connections back; pool not permanently shrunk.
    assert stats["available"] == size
    # Every leaked wrapper was reclaimed (>= the leaks; temps over capacity are closed).
    assert stats["gc_reclaimed"] >= size + 2


def test_explicit_close_is_not_double_counted(db):
    pool = get_pool(db)
    before = pool_stats()[db]["gc_reclaimed"]
    c = db_connect_pooled(db)
    c.execute("SELECT 1")
    c.close()                      # happy path: returns to pool, _closed=True
    del c
    gc.collect()
    after = pool_stats()[db]["gc_reclaimed"]
    assert after == before         # __del__ is a no-op after an explicit close()
    assert pool_stats()[db]["available"] == pool.size


def test_pool_survives_many_leaks_without_stalling(db):
    # If reclaim worked, the pool never empties, so acquire() never hits the 10s
    # Queue timeout. 20 leaked acquires must complete fast.
    import time
    pool = get_pool(db)
    t0 = time.perf_counter()
    for _ in range(20):
        c = db_connect_pooled(db)
        c.execute("SELECT 1")
        del c
        gc.collect()
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0           # nowhere near 10s-per-stall behaviour
    assert pool_stats()[db]["available"] == pool.size

"""
tests/test_db_pool_leak_on_error.py
===================================
Regression tests for the connection-pool leak that previously caused a
permanent 30s/query deadlock (see CLAUDE_NOTES 2026-06-07).

Root cause was the close-on-success pattern:
    conn = db_connect(self.db)
    rows = conn.execute(...).fetchall()   # raises on uninitialized DB
    conn.close()                          # SKIPPED -> connection leaked

After enough leaked connections the SQLitePool Queue(maxsize=5) empties and
every acquire() blocks the full 10s timeout.

These tests exercise the high-traffic memory/KG modules against an EMPTY
(uninitialized) DB so every query raises "no such table", then assert the
pool is fully replenished WITHOUT relying on the GC __del__ safety net
(gc_reclaimed must NOT grow -- the modules must close explicitly via
try/finally).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.db_pool import get_pool, pool_stats, close_pool, MAX_CONNS
from cognia.knowledge.graph import KnowledgeGraph
from cognia.memory.semantic import SemanticMemory
from cognia.memory.episodic import EpisodicMemory
from cognia.memory.chat import ChatHistory, UserProfile


@pytest.fixture
def empty_db(tmp_path):
    """A DB file with NO tables created. Every query will raise OperationalError."""
    db = str(tmp_path / "empty.db")
    # Prime the pool for this path so available starts at MAX_CONNS.
    get_pool(db)
    yield db
    close_pool(db)


def _available(db):
    return pool_stats()[db]["available"]


def _gc_reclaimed():
    return pool_stats()["gc_reclaimed"]


def test_graph_methods_dont_leak_on_missing_table(empty_db):
    kg = KnowledgeGraph(db_path=empty_db)
    gc_before = _gc_reclaimed()

    # All of these hit a non-existent knowledge_graph table.
    # add_triple raises (no table) but must still release the connection.
    for _ in range(MAX_CONNS * 3):
        try:
            kg.add_triple("a", "is_a", "b")
        except Exception:
            pass
        # Read methods swallow nothing -- they let the error propagate or return.
        try:
            kg.get_facts("a")
        except Exception:
            pass
        try:
            kg.stats()
        except Exception:
            pass

    # Pool fully replenished and no GC reclamation needed (explicit close).
    assert _available(empty_db) == MAX_CONNS
    assert _gc_reclaimed() == gc_before


def test_semantic_methods_dont_leak_on_missing_table(empty_db):
    sm = SemanticMemory(db_path=empty_db)
    gc_before = _gc_reclaimed()

    for _ in range(MAX_CONNS * 3):
        # semantic.py swallows exceptions internally (returns [] / None).
        sm.update_concept("c", [0.1, 0.2, 0.3])
        sm.get_concept("c")
        sm.find_related([0.1, 0.2, 0.3])
        sm.list_all()
        sm.spreading_activation("c")

    assert _available(empty_db) == MAX_CONNS
    assert _gc_reclaimed() == gc_before


def test_episodic_methods_dont_leak_on_missing_table(empty_db):
    em = EpisodicMemory(db_path=empty_db)
    gc_before = _gc_reclaimed()

    for _ in range(MAX_CONNS * 3):
        em.store("obs", "label", [0.1, 0.2, 0.3])
        em.get_due_for_review()
        em.count()
        em.get_in_window("2026-06-08T00:00:00")
        # retrieve_similar drives the episodic_fast VectorCache, whose
        # _get_db_hash() + _build_locked() also query the (missing) table.
        em.retrieve_similar([0.1, 0.2, 0.3])

    assert _available(empty_db) == MAX_CONNS
    assert _gc_reclaimed() == gc_before


def test_chat_methods_dont_leak_on_missing_table(empty_db):
    ch = ChatHistory(db_path=empty_db)
    up = UserProfile(db_path=empty_db)
    gc_before = _gc_reclaimed()

    for _ in range(MAX_CONNS * 3):
        # chat.py does NOT swallow -- methods raise on missing table.
        for fn in (
            lambda: ch.log("user", "hi"),
            lambda: ch.get_recent(),
            lambda: ch.count(),
            lambda: up.get("name"),
            lambda: up.set("name", "x"),
            lambda: up.get_all(),
        ):
            try:
                fn()
            except Exception:
                pass

    assert _available(empty_db) == MAX_CONNS
    assert _gc_reclaimed() == gc_before


def test_pool_stays_usable_after_error_storm(empty_db):
    """End-to-end: after a storm of failing queries the pool must not be
    starved -- a subsequent acquire must be instant, not block 10s."""
    import time

    kg = KnowledgeGraph(db_path=empty_db)
    for _ in range(50):
        try:
            kg.get_facts("x")
        except Exception:
            pass

    pool = get_pool(empty_db)
    t0 = time.perf_counter()
    conn = pool.acquire()
    elapsed = time.perf_counter() - t0
    pool.release(conn, commit=False)

    assert elapsed < 1.0, f"acquire blocked {elapsed:.1f}s -- pool was starved"
    assert _available(empty_db) == MAX_CONNS


# ══════════════════════════════════════════════════════════════════════
# release() con commit fallido: debe PROPAGAR (no éxito silencioso)
# y aun así devolver la conexión al pool (no filtrar el handle).
# Regresión: antes tragaba la excepción del commit -> el caller creía
# que su escritura persistió cuando en realidad se hizo rollback.
# ══════════════════════════════════════════════════════════════════════

def test_release_propagates_commit_failure_and_returns_conn(empty_db):
    import sqlite3

    pool = get_pool(empty_db)
    conn = pool.acquire()
    assert _available(empty_db) == MAX_CONNS - 1

    # Cerrar la conexión física por debajo: commit() sobre una conexión
    # cerrada lanza ProgrammingError (simula disk full / database is locked).
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        pool.release(conn, commit=True)

    # La conexión volvió al pool ANTES de propagar (sin fuga de handle).
    assert _available(empty_db) == MAX_CONNS


def test_pooled_connection_del_never_propagates():
    """__del__ no debe propagar ni aunque el release subyacente explote
    (una excepción viva en __del__ es ruido de GC, nunca señal útil)."""
    from storage.db_pool import _PooledConnection

    class _ExplodingPool:
        def release(self, conn, commit=True):
            raise RuntimeError("boom en release")

    class _FakeConn:
        def rollback(self):
            pass

    pc = _PooledConnection(_FakeConn(), _ExplodingPool())
    # No usar `del pc` (CPython suprime excepciones de __del__ via
    # unraisablehook): llamar __del__ directo para verificar que traga.
    pc.__del__()  # must not raise
    assert pc._closed is True

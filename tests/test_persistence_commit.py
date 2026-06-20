"""
tests/test_persistence_commit.py
================================
Real-DB regression tests for the pooled-write-without-commit bug class.

Several modules saved to SQLite via `db_connect_pooled(...).execute(INSERT)`
then `.close()` WITHOUT `.commit()`. The pool's release() uses commit=False,
so the write was silently rolled back -- the method returned True but no data
persisted. Existing unit tests mocked db_connect_pooled, so they never caught
this.

These tests use a REAL temp DB and force a `close_pool()` between save and
load so a load cannot accidentally read an uncommitted transaction lingering
on the same physical connection.

Covered:
  - cognia/learning/style_engine.py    StyleEngine.save/load
  - cognia/user_profile.py             UserProfileManager.save/delete/load
  (PersonalIndex is covered in test_personal_index.py)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.db_pool import close_pool, pool_stats, MAX_CONNS
from cognia.database import init_db


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "persist.db")
    init_db(path)
    yield path
    close_pool(path)


# ── StyleEngine ────────────────────────────────────────────────────────

def test_style_engine_save_persists(db):
    from cognia.learning.style_engine import StyleEngine
    se = StyleEngine("u1")
    se.observe("hello world this is a reasonably long test message about python")
    assert se.save(db) is True

    close_pool(db)  # drop pooled connections -> only committed data survives

    se2 = StyleEngine.load("u1", db)
    assert se2._messages, "StyleEngine.save did not persist (missing commit)"


def test_style_engine_load_missing_returns_fresh(db):
    from cognia.learning.style_engine import StyleEngine
    se = StyleEngine.load("does_not_exist", db)
    assert se.user_id == "does_not_exist"
    assert se._messages == []


def test_style_engine_save_load_no_pool_leak(db):
    from cognia.learning.style_engine import StyleEngine
    se = StyleEngine("u1")
    se.observe("a message here for testing the pool")
    for _ in range(MAX_CONNS * 3):
        se.save(db)
        StyleEngine.load("u1", db)
    assert pool_stats()[db]["available"] == MAX_CONNS


# ── UserProfileManager ─────────────────────────────────────────────────

def test_user_profile_save_persists(db):
    from cognia.user_profile import UserProfileManager
    mgr = UserProfileManager(db)
    p = mgr.load("bob")
    p.response_style = "formal"
    assert mgr.save(p) is True

    close_pool(db)

    mgr2 = UserProfileManager(db)  # fresh manager -> empty cache
    p2 = mgr2.load("bob")
    assert p2.response_style == "formal", "UserProfile.save did not persist (missing commit)"


def test_user_profile_delete_persists(db):
    from cognia.user_profile import UserProfileManager
    mgr = UserProfileManager(db)
    p = mgr.load("bob")
    mgr.save(p)
    close_pool(db)

    mgr2 = UserProfileManager(db)
    assert "bob" in mgr2.list_users()
    assert mgr2.delete("bob") is True
    close_pool(db)

    mgr3 = UserProfileManager(db)
    assert "bob" not in mgr3.list_users(), "UserProfile.delete did not persist (missing commit)"


def test_user_profile_save_delete_no_pool_leak(db):
    from cognia.user_profile import UserProfileManager
    mgr = UserProfileManager(db)
    for i in range(MAX_CONNS * 2):
        p = mgr.load(f"u{i}")
        mgr.save(p)
    for i in range(MAX_CONNS * 2):
        mgr.delete(f"u{i}")
    mgr.list_users()
    assert pool_stats()[db]["available"] == MAX_CONNS

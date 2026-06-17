"""
Regression: writes to the `user_profile` table go through db_connect_pooled,
whose _PooledConnection.close() releases the connection with commit=False.
Without an explicit conn.commit() the INSERT/DELETE is silently rolled back, so
profiles/styles/indexes never persisted across a pool reset (or app restart).

These tests prove each save() is durable by reopening with a fresh pool.
"""
import sqlite3

import pytest

from storage.db_pool import close_pool


def _make_db(tmp_path):
    db = str(tmp_path / "profiles.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE user_profile (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    )
    conn.commit()
    conn.close()
    return db


def test_user_profile_manager_persists(tmp_path):
    from cognia.user_profile import UserProfileManager, CognitiveProfile
    db = _make_db(tmp_path)

    mgr = UserProfileManager(db)
    p = CognitiveProfile(user_id="alice")
    p.response_style = "socratic"
    assert mgr.save(p) is True

    close_pool(db)  # drop pooled conns -> only committed data survives
    mgr2 = UserProfileManager(db)
    assert "alice" in mgr2.list_users()
    assert mgr2.load("alice").response_style == "socratic"

    assert mgr2.delete("alice") is True
    close_pool(db)
    mgr3 = UserProfileManager(db)
    assert "alice" not in mgr3.list_users()
    close_pool(db)


def test_style_engine_persists(tmp_path):
    from cognia.learning.style_engine import StyleEngine
    db = _make_db(tmp_path)

    eng = StyleEngine(user_id="bob")
    eng.observe("hola que tal como estas hoy amigo mio")
    assert eng.save(db) is True

    close_pool(db)
    loaded = StyleEngine.load("bob", db)
    assert loaded.user_id == "bob"
    assert loaded._messages, "messages should survive a pool reset"
    close_pool(db)


def test_personal_index_persists(tmp_path):
    from cognia.memory.personal_index import PersonalIndex
    db = _make_db(tmp_path)

    idx = PersonalIndex(user_id="carol")
    idx.add("python", importance=0.9)
    assert idx.save(db) is True

    close_pool(db)
    loaded = PersonalIndex.load("carol", db)
    assert "python" in loaded._entries
    close_pool(db)

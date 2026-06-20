"""
tests/test_personal_index.py
============================
Unit tests for PersonalIndex (cognia/memory/personal_index.py).

Includes a regression for the save()-without-commit bug: PersonalIndex.save()
used the pooled connection but never called commit(); since the pool's
release() uses commit=False, the INSERT was silently rolled back and the data
never persisted. save() returned True regardless, hiding the data loss.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.db_pool import db_connect_pooled, close_pool
from cognia.memory.personal_index import PersonalIndex, PersonalEntry


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "pi.db")
    conn = db_connect_pooled(path)
    conn.execute(
        "CREATE TABLE user_profile (key TEXT UNIQUE, value TEXT, updated_at TEXT)"
    )
    conn.commit()
    conn.close()
    yield path
    close_pool(path)


def test_add_and_get():
    idx = PersonalIndex("u1")
    e = idx.add("Python", importance=0.9, emotions=["joy"], note="lang")
    assert e.concept == "python"  # normalized lowercase
    got = idx.get("python")
    assert got is not None
    assert got.access_count == 1  # get() increments


def test_add_reinforces_existing():
    idx = PersonalIndex("u1")
    idx.add("python", importance=0.5)
    before = idx.get("python").importance
    idx.add("python", emotions=["curiosity"])
    after = idx.get("python")
    assert after.importance > before
    assert "curiosity" in after.emotion_tags


def test_save_persists_across_pool_reset(db):
    """REGRESSION: save() must commit so data survives a fresh connection."""
    idx = PersonalIndex("u1")
    idx.add("python", importance=0.9, emotions=["joy"])
    idx.add("rust", importance=0.7)
    assert idx.save(db) is True

    # Drop all pooled connections so load() cannot see an uncommitted txn
    # lingering on the same physical connection.
    close_pool(db)

    loaded = PersonalIndex.load("u1", db)
    assert set(loaded._entries.keys()) == {"python", "rust"}
    assert loaded._entries["python"].importance == pytest.approx(0.9)


def test_load_missing_returns_empty(db):
    loaded = PersonalIndex.load("nonexistent_user", db)
    assert loaded._entries == {}
    assert loaded.user_id == "nonexistent_user"


def test_save_load_does_not_leak_pool(db):
    from storage.db_pool import pool_stats, MAX_CONNS
    idx = PersonalIndex("u1")
    idx.add("python", 0.9)
    for _ in range(MAX_CONNS * 3):
        idx.save(db)
        PersonalIndex.load("u1", db)
    assert pool_stats()[db]["available"] == MAX_CONNS


def test_empty_concept_rejected():
    idx = PersonalIndex("u1")
    with pytest.raises(ValueError):
        idx.add("   ")


def test_evict_weakest_at_capacity():
    idx = PersonalIndex("u1")
    idx.MAX_ENTRIES = 3
    idx.add("a", importance=0.9)
    idx.add("b", importance=0.8)
    idx.add("c", importance=0.1)  # weakest
    idx.add("d", importance=0.5)  # triggers eviction of weakest
    assert len(idx._entries) == 3
    assert "c" not in idx._entries


def test_search_ranks_by_score():
    idx = PersonalIndex("u1")
    idx.add("python programming", importance=0.9)
    idx.add("cooking recipes", importance=0.9)
    results = idx.search("python", top_k=5)
    assert results
    assert results[0][0].concept == "python programming"


def test_to_dict_from_dict_roundtrip():
    idx = PersonalIndex("u1")
    idx.add("python", 0.9, ["joy"], note="n")
    d = idx.to_dict()
    idx2 = PersonalIndex.from_dict(d)
    assert idx2.user_id == "u1"
    assert idx2._entries["python"].note == "n"

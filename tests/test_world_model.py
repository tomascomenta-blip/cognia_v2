"""
tests/test_world_model.py -- Unit tests for WorldModelModule.
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.db_pool import db_connect_pooled, close_pool
from cognia.reasoning.world_model import WorldModelModule

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS world_model (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_a TEXT,
    relation TEXT,
    entity_b TEXT,
    strength REAL
)
"""


@pytest.fixture
def wm(tmp_path):
    db = str(tmp_path / "wm_test.db")
    # Create the table in the temp DB before WorldModelModule uses it
    conn = db_connect_pooled(db)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    conn.close()
    mod = WorldModelModule(db_path=db)
    yield mod
    close_pool(db)


def test_add_relation_new(wm):
    wm.add_relation("cat", "is_a", "animal", strength=0.6)
    rels = wm.get_relations("cat")
    assert len(rels) == 1
    r = rels[0]
    assert r["entity"] == "animal"
    assert r["relation"] == "is_a"
    assert abs(r["strength"] - 0.6) < 1e-9


def test_add_relation_strength_increases(wm):
    wm.add_relation("dog", "likes", "bone", strength=0.5)
    first = wm.get_relations("dog")[0]["strength"]
    wm.add_relation("dog", "likes", "bone", strength=0.5)
    second = wm.get_relations("dog")[0]["strength"]
    # strength increases: new = min(1.0, old + 0.5*0.2) = min(1.0, 0.5+0.1)
    assert second > first
    assert second <= 1.0


def test_add_relation_strength_caps_at_1(wm):
    # Add many times so accumulated strength would exceed 1.0
    for _ in range(30):
        wm.add_relation("x", "rel", "y", strength=0.9)
    rels = wm.get_relations("x")
    assert len(rels) == 1
    assert rels[0]["strength"] <= 1.0


def test_get_relations_empty(wm):
    result = wm.get_relations("nonexistent_entity_xyz")
    assert result == []


def test_get_relations_returns_top5(wm):
    for i in range(6):
        wm.add_relation("hub", f"rel_{i}", f"target_{i}", strength=0.1 * (i + 1))
    rels = wm.get_relations("hub")
    assert len(rels) == 5


def test_get_relations_ordered_by_strength(wm):
    wm.add_relation("node", "a", "low", strength=0.2)
    wm.add_relation("node", "b", "high", strength=0.9)
    wm.add_relation("node", "c", "mid", strength=0.5)
    rels = wm.get_relations("node")
    strengths = [r["strength"] for r in rels]
    assert strengths == sorted(strengths, reverse=True)

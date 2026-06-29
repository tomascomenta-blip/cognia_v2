"""Cycle 3 — fetch index-first: ContextMap.query ranks pointers by cosine
similarity and packs raw spans up to a small, parametrizable token budget.

Vectors here are deterministic (no real model), so ranking is exact.
"""

import pytest

from cognia.context.context_map import ContextMap
from storage.db_pool import close_pool


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "ctxmap_query_test.db")
    yield path
    close_pool(path)


def test_query_ranks_by_similarity(db_path):
    cm = ContextMap(db_path=db_path, project="p")
    cm.add_pointer("text", "", inline_text="span cercano", vector=[1.0, 0.0, 0.0])
    cm.add_pointer("text", "", inline_text="span lejano", vector=[0.0, 1.0, 0.0])

    res = cm.query([1.0, 0.0, 0.0], budget_tokens=4000)

    assert len(res) == 2
    assert res[0]["text"] == "span cercano"
    assert res[0]["score"] >= res[1]["score"]


def test_query_respects_budget(db_path):
    cm = ContextMap(db_path=db_path, project="p")
    # Each span: 400 chars -> est_tokens = 400 // 4 = 100.
    for i in range(5):
        cm.add_pointer("text", "", inline_text="x" * 400,
                       vector=[1.0, 0.0, 0.0])

    res = cm.query([1.0, 0.0, 0.0], budget_tokens=150)

    total = sum(len(r["text"]) // 4 for r in res)
    assert total <= 150
    assert len(res) >= 1


def test_query_empty_vector(db_path):
    cm = ContextMap(db_path=db_path, project="p")
    cm.add_pointer("text", "", inline_text="algo", vector=[1.0, 0.0, 0.0])
    assert cm.query([]) == []
    assert cm.query(None) == []


def test_query_skips_pointers_without_vector(db_path):
    cm = ContextMap(db_path=db_path, project="p")
    cm.add_pointer("text", "", inline_text="sin vector")  # vector=None
    cm.add_pointer("text", "", inline_text="con vector", vector=[1.0, 0.0, 0.0])

    res = cm.query([1.0, 0.0, 0.0], budget_tokens=4000)

    assert len(res) == 1
    assert res[0]["text"] == "con vector"


def test_query_text_uses_embed_fn(db_path):
    cm = ContextMap(db_path=db_path, project="p")
    cm.add_pointer("text", "", inline_text="cerca", vector=[1.0, 0.0])
    cm.add_pointer("text", "", inline_text="lejos", vector=[0.0, 1.0])

    embed_fn = lambda t: [1.0, 0.0]
    res = cm.query_text("q", embed_fn, budget_tokens=4000)

    assert len(res) == 2
    assert res[0]["text"] == "cerca"

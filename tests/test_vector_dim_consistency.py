"""
Regression test for the 64-vs-384 episodic vector dimension bug.

Bug (fixed this session):
    config.VECTOR_DIM was `384 if sentence_transformers installed else 64`.
    Uninstalling sentence-transformers flipped new vectors AND every query to
    dim 64 while the DB still held 384-dim rows. The VectorCache builds its
    matrix on the dominant dim (384), so a 64-dim query hit `(N,384) @ (64,)`
    -> matmul crash -> ~6s Python slow-path on EVERY search.

Fix:
    VECTOR_DIM is pinned to 384 unconditionally (the n-gram fallback takes any
    dim, and all-MiniLM-L6-v2 is also 384), so the embedder's output dimension
    can never diverge from what the cache builds on. scripts/migrate_vector_dim.py
    re-embeds legacy 64-dim rows.

These tests pin the invariant at the root cause: the query embedder and the
cache must agree on dimension. If anyone reintroduces a conditional dim, the
first three tests fail immediately -- long before a user sees a 6s search.
"""

import numpy as np

from cognia.config import VECTOR_DIM
from cognia.vectors import text_to_vector
from cognia.cognia_embedding import _ngram_vector
from cognia.memory.episodic_fast import VectorCache

EXPECTED_DIM = 384


def test_vector_dim_pinned_to_384():
    assert VECTOR_DIM == EXPECTED_DIM, (
        f"VECTOR_DIM must be {EXPECTED_DIM} regardless of sentence-transformers; "
        f"got {VECTOR_DIM}. A conditional dim reintroduces the 64/384 cache crash."
    )


def test_query_embedder_matches_cache_dim():
    """Every query vector the app produces must be 384-dim (the cache's dim)."""
    for text in ("hola", "un texto cualquiera de prueba", "", "x" * 500):
        vec = text_to_vector(text)
        assert len(vec) == EXPECTED_DIM, f"text_to_vector({text!r}) -> dim {len(vec)}"


def test_ngram_fallback_default_is_384():
    # The fallback's default must match VECTOR_DIM so an ST outage can't shrink it.
    assert len(_ngram_vector("cualquier cosa")) == EXPECTED_DIM
    assert len(_ngram_vector("cualquier cosa", EXPECTED_DIM)) == EXPECTED_DIM


def test_cache_search_with_matching_dim_returns_results():
    """A 384-dim query against a 384-dim matrix must search without crashing."""
    cache = VectorCache(":memory:")
    # Inject a tiny normalized 384-dim matrix and bypass the DB-backed rebuild.
    rng = np.arange(3 * EXPECTED_DIM, dtype=np.float32).reshape(3, EXPECTED_DIM)
    norms = np.linalg.norm(rng, axis=1, keepdims=True)
    cache._matrix = rng / norms
    cache._meta = [
        {"id": i, "observation": f"obs{i}", "label": "l", "confidence": 0.5,
         "importance": 1.0, "emotion_score": 0.0, "emotion_label": "neutral",
         "surprise": 0.0, "feedback_weight": 1.0}
        for i in range(3)
    ]
    cache._db_hash = 777
    cache._get_db_hash = lambda: 777  # freeze hash so search() won't rebuild

    query = text_to_vector("consulta de prueba")
    assert len(query) == EXPECTED_DIM
    results = cache.search(query, top_k=2)
    assert len(results) == 2
    assert all("similarity" in r for r in results)

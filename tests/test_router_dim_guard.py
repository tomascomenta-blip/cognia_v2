"""
Regression tests for the GlobalRouter / _EmbeddingIndex dimension-mismatch bug.

Bug (fixed this session):
    `_EmbeddingIndex.similarities()` embedded the prompt with a different encoder
    than the one that built the centroids. When the async ST embedding queue (a
    singleton fixed at e.g. 64 dims) produced the prompt vector while the centroids
    were still 384-dim n-gram vectors, `np.dot(pv, c)` raised
    `ValueError: shapes (64,) and (384,) not aligned`, crashing routing.

Fix:
    similarities() now (a) embeds the prompt with the SAME encoder stored in
    `self._embed_fn` that built the current centroids, and (b) keeps a final guard:
        out[domain] = float(np.dot(pv, c)) if pv.shape == c.shape else 0.0
    so a dimension mismatch yields a neutral 0.0 instead of raising.

These tests exercise the REAL code (no mocks of the logic under test) and FAIL if
either part of the fix is reverted.
"""

import numpy as np
import pytest

from shattering.model_constants import ROUTER_EMBEDDING_DIM
from shattering.router import (
    GlobalRouter,
    RouteDecision,
    _DOMAIN_KEYWORDS,
    _EmbeddingIndex,
)


def test_similarities_survives_dim_mismatch_returns_neutral_zero():
    """
    Force a centroid/prompt dimension mismatch and assert similarities() returns
    a dict of floats without raising, with the mismatched domains scoring 0.0.

    This directly reproduces the (64,) vs (384,) np.dot crash the fix guards against.
    """
    idx = _EmbeddingIndex()
    # Build real n-gram centroids (synchronous Phase-1 build) at the canonical dim.
    idx.build(_DOMAIN_KEYWORDS)

    centroid_dim = ROUTER_EMBEDDING_DIM  # 384 — dim of the real centroids
    prompt_dim = 64                      # different dim — reproduces the singleton-queue case

    # Force the stored centroids to a known dimension (centroid_dim).
    forced_centroids = {
        domain: np.ones(centroid_dim, dtype=np.float32) / np.sqrt(centroid_dim)
        for domain in _DOMAIN_KEYWORDS
    }
    # Make the prompt encoder used by similarities() emit a DIFFERENT dim.
    # similarities() pulls self._embed_fn under the lock, so patch that one.
    bad_encoder = lambda text: [0.1] * prompt_dim
    idx._centroids = forced_centroids
    idx._embed_fn = bad_encoder
    # Also break the n-gram fallback dim so the except-branch can't accidentally
    # paper over the mismatch with a 384-dim vector: keep it mismatched too.
    idx._ngram = bad_encoder

    assert centroid_dim != prompt_dim  # sanity: the mismatch is real

    # The pre-fix code raised ValueError here; the fixed code must not.
    sims = idx.similarities("hola mundo")

    assert isinstance(sims, dict)
    assert set(sims.keys()) == set(_DOMAIN_KEYWORDS.keys())
    for domain, val in sims.items():
        assert isinstance(val, float), f"{domain} similarity is not a float: {val!r}"
        # Mismatched shapes must degrade to the neutral 0.0 sentinel.
        assert val == 0.0, f"{domain} should be neutral 0.0 on dim mismatch, got {val}"


def test_similarities_matched_dims_compute_real_dot_product():
    """When centroid and prompt dims agree, similarities() must compute a real
    (non-sentinel) cosine value — proves the guard does not short-circuit the
    normal path."""
    idx = _EmbeddingIndex()
    idx.build(_DOMAIN_KEYWORDS)

    # Real n-gram encoder produces ROUTER_EMBEDDING_DIM vectors that match centroids.
    sims = idx.similarities("escribe una funcion en python")
    assert isinstance(sims, dict)
    assert set(sims.keys()) == set(_DOMAIN_KEYWORDS.keys())
    assert all(isinstance(v, float) for v in sims.values())
    # With matched dims at least one domain should produce a non-zero similarity.
    assert any(v != 0.0 for v in sims.values())


def test_global_router_route_end_to_end_no_crash():
    """Real end-to-end route() must return a RouteDecision without raising
    (n-gram mode is fine in CI)."""
    router = GlobalRouter()
    decision = router.route("escribe una funcion en python")
    assert isinstance(decision, RouteDecision)
    assert decision.sub_model in ("logos", "techne", "rhetor")
    assert 0.0 <= decision.confidence <= 1.0
    assert isinstance(decision.scores, dict)

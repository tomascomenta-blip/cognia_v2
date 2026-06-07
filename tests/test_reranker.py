"""
tests/test_reranker.py
======================
Tests for the HYDRA GLOBAL-band retrieval re-ranker (cognia/memory/reranker.py).

Pure, offline, deterministic: builds raw episodic/semantic dicts that mirror the
REAL fields returned by EpisodicMemory.retrieve_similar and
SemanticMemory.find_related, and asserts the fusion + dedup + top-k behavior.
"""

from datetime import datetime, timedelta

from cognia.memory.reranker import (
    rerank,
    format_ranked,
    RankedItem,
    W_SIM,
    W_RECENCY,
    W_IMPORTANCE,
)


def _ep(label, similarity, importance=1.0, timestamp=None):
    # Mirrors EpisodicMemory.retrieve_similar item shape (real keys).
    d = {"label": label, "observation": label, "similarity": similarity,
         "confidence": 0.5, "score": similarity}
    if importance is not None:
        d["importance"] = importance
    if timestamp is not None:
        d["timestamp"] = timestamp
    return d


def _sem(concept, similarity, confidence=0.5):
    # Mirrors SemanticMemory.find_related item shape (real keys).
    return {"concept": concept, "similarity": similarity,
            "confidence": confidence, "emotion_avg": 0.0}


def test_dedup_keeps_higher_score():
    # Same label from two episodic hits with different similarity -> the
    # higher-scoring one survives, only one item remains for that label.
    low = _ep("shard routing", 0.20)
    high = _ep("shard routing", 0.90)
    result = rerank([low, high], [], top_k=5)
    labels = [r.label for r in result]
    assert labels.count("shard routing") == 1
    survivor = next(r for r in result if r.label == "shard routing")
    assert abs(survivor.similarity - 0.90) < 1e-9


def test_higher_similarity_higher_score():
    # All else equal, the higher-similarity item scores higher.
    res = rerank([_ep("a", 0.30), _ep("b", 0.80)], [], top_k=5)
    by_label = {r.label: r for r in res}
    assert by_label["b"].score > by_label["a"].score


def test_more_recent_higher_score():
    # All else equal (same similarity, same importance), a more recent
    # timestamp yields higher recency and thus a higher fused score.
    now = datetime.now()
    recent = (now - timedelta(hours=1)).isoformat()
    old = (now - timedelta(days=20)).isoformat()
    res = rerank(
        [_ep("recent", 0.50, importance=1.0, timestamp=recent),
         _ep("old", 0.50, importance=1.0, timestamp=old)],
        [], top_k=5,
    )
    by_label = {r.label: r for r in res}
    assert by_label["recent"].recency > by_label["old"].recency
    assert by_label["recent"].score > by_label["old"].score


def test_returns_at_most_top_k_sorted_desc():
    eps = [_ep("e%d" % i, 0.1 * i) for i in range(8)]
    sems = [_sem("s%d" % i, 0.05 * i) for i in range(8)]
    res = rerank(eps, sems, top_k=5)
    assert len(res) <= 5
    scores = [r.score for r in res]
    assert scores == sorted(scores, reverse=True)


def test_never_raises_on_missing_keys_and_empty():
    # Empty inputs.
    assert rerank([], [], top_k=5) == []
    # Garbage / partial items must not raise and must be skipped or defaulted.
    junk = [{}, {"label": ""}, {"label": None}, "not a dict", 42,
            {"similarity": "x"}, {"concept": "ok"}]
    res = rerank(junk, junk, top_k=5)
    assert isinstance(res, list)
    for r in res:
        assert isinstance(r, RankedItem)
        assert 0.0 <= r.recency <= 1.0
        assert 0.0 <= r.importance <= 1.0


def test_weights_sum_to_one():
    # Documented invariant: fusion weights sum to ~1 so score stays in [0,1].
    assert abs((W_SIM + W_RECENCY + W_IMPORTANCE) - 1.0) < 1e-9


def test_format_ranked_is_ascii():
    res = rerank([_ep("arquitectura de shards", 0.40, importance=1.5)],
                 [_sem("routing semantico", 0.30)], top_k=5)
    lines = format_ranked(res)
    assert isinstance(lines, list)
    for line in lines:
        # ASCII-only and carries the expected score breakdown tokens.
        assert line == line.encode("ascii", "replace").decode("ascii")
        assert "score=" in line and "sim=" in line
        assert "rec=" in line and "imp=" in line


def test_negative_similarity_clamped():
    # Semantic cosine similarity can be negative; it must not produce a
    # negative score contribution (clamped to 0 for scoring).
    res = rerank([], [_sem("neg", -0.5, confidence=0.0)], top_k=5)
    assert len(res) == 1
    assert res[0].score >= 0.0

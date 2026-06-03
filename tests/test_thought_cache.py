"""
tests/test_thought_cache.py — Thought-Chain Persistence (TCP) unit tests
7 tests covering: store/lookup, similarity, miss, TTL, MAX_ENTRIES, hit counter, stats.
"""

import os
import time
import tempfile
import pytest

from cognia.reasoning.thought_cache import ThoughtCache


def _make_cache(tmp_path=None) -> ThoughtCache:
    if tmp_path is None:
        tmp_path = tempfile.mktemp(suffix=".db")
    tc = ThoughtCache(db_path=tmp_path)
    return tc


def _sample_chain(**kwargs) -> dict:
    base = {
        "reasoning_context": "Python is a high-level interpreted language.",
        "confidence": 0.75,
        "has_contradiction": False,
        "sub_questions": ["What is Python?", "How is it used?"],
        "hypothesis": None,
        "task_type": "definicion",
        "plan_steps": [],
    }
    base.update(kwargs)
    return base


# ── Test 1: store and exact-match lookup ─────────────────────────────────────

def test_store_and_exact_hit():
    tc = _make_cache()
    chain = _sample_chain()
    tc.store("what is python", chain)
    result = tc.lookup("what is python")
    assert result is not None, "Expected a cache hit for identical question"
    assert result["reasoning_context"] == chain["reasoning_context"]
    assert abs(result["confidence"] - chain["confidence"]) < 1e-6


# ── Test 2: similar question should hit ──────────────────────────────────────

def test_similar_question_hit():
    tc = _make_cache()
    chain = _sample_chain()
    # Store a multi-token question; lookup with extra words that share the core tokens.
    # After stopword removal both questions share the dominant tokens "python language"
    # → cosine sim well above 0.88.
    tc.store("python language programming", chain)
    result = tc.lookup("python language programming guide")
    # Stored tokens: [python, language, programming]
    # Lookup tokens: [python, language, programming, guide]
    # Shared weighted overlap → cosine ~ 0.97
    assert result is not None, "Expected a hit for question with very similar token set"


# ── Test 3: unrelated question should miss ───────────────────────────────────

def test_different_question_miss():
    tc = _make_cache()
    chain = _sample_chain()
    tc.store("what is python", chain)
    result = tc.lookup("how does photosynthesis work in plants")
    assert result is None, "Expected None for an unrelated question"


# ── Test 4: TTL expiry returns None ──────────────────────────────────────────

def test_ttl_expiry(monkeypatch):
    tc = _make_cache()
    chain = _sample_chain()
    tc.store("what is python", chain)

    # Patch time.time to return a value 4 days in the future
    _real_time = time.time
    monkeypatch.setattr(time, "time", lambda: _real_time() + 4 * 86400)

    result = tc.lookup("what is python")
    assert result is None, "Expected None after TTL expiry"


# ── Test 5: MAX_ENTRIES cap is enforced ──────────────────────────────────────

def test_max_entries():
    tc = _make_cache()
    tc.MAX_ENTRIES = 300  # explicit (default value, but be clear)
    # Store 310 distinct questions
    for i in range(310):
        q = f"question about topic number {i} in the dataset"
        tc.store(q, _sample_chain(reasoning_context=f"context for topic {i}"))

    # DB should not exceed MAX_ENTRIES + small prune batch (20)
    total = tc.stats()["total"]
    assert total <= tc.MAX_ENTRIES, f"Expected <= {tc.MAX_ENTRIES} entries, got {total}"


# ── Test 6: similarity_hits counter increments on each hit ───────────────────

def test_hits_counter_increments():
    tc = _make_cache()
    chain = _sample_chain()
    tc.store("what is python", chain)

    # 3 lookups
    for _ in range(3):
        r = tc.lookup("what is python")
        assert r is not None

    s = tc.stats()
    assert s["hits"] == 3, f"Expected hits=3, got {s['hits']}"


# ── Test 7: stats accuracy after stores + hits ───────────────────────────────

def test_stats_accuracy():
    tc = _make_cache()

    # Store 5 distinct chains
    questions = [
        "what is machine learning",
        "how does deep learning work",
        "explain neural networks",
        "what is gradient descent",
        "how to train a model",
    ]
    for q in questions:
        tc.store(q, _sample_chain(reasoning_context=f"context for: {q}"))

    # 3 lookups on the same question
    for _ in range(3):
        tc.lookup("what is machine learning")

    s = tc.stats()
    assert s["total"] == 5,  f"Expected total=5, got {s['total']}"
    assert s["hits"]  == 3,  f"Expected hits=3, got {s['hits']}"
    assert s["avg_reuse"] == pytest.approx(3 / 5, abs=1e-4)

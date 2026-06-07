"""tests/test_injection_prioritizer.py — Unit tests for InjectionPrioritizer."""

import sys
import os

# Ensure repo root is on the path for direct pytest runs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.context.injection_prioritizer import InjectionPrioritizer


def _make_prioritizer() -> InjectionPrioritizer:
    return InjectionPrioritizer()


# ── Test 1: score_block returns a float in [0, 1] ──────────────────────────

def test_score_block_returns_float_in_range():
    p = _make_prioritizer()
    for block_type in ["user_facts", "crystallized_kg", "goals", "feedback",
                        "autocritica", "long_term_memory", "curiosity", "adaptive"]:
        score = p.score_block(block_type, "some content about Python", "Python")
        assert isinstance(score, float), f"score for {block_type} is not float"
        assert 0.0 <= score <= 1.0, f"score {score} out of [0, 1] for {block_type}"


# ── Test 2: score_block gives boost when query word appears in content ──────

def test_score_block_boost_on_query_match():
    p = _make_prioritizer()
    # "python" (>3 chars) appears in content -> boost 1.5
    score_with_match = p.score_block("user_facts", "user likes python programming", "python")
    # no query word in content
    score_without = p.score_block("user_facts", "user likes cooking", "python")
    assert score_with_match > score_without, (
        f"Expected boost on match ({score_with_match}) > no match ({score_without})"
    )


# ── Test 3: prioritize respects max_blocks limit ────────────────────────────

def test_prioritize_respects_max_blocks():
    p = _make_prioritizer()
    blocks = [
        {"type": "user_facts",       "content": "fact about user"},
        {"type": "crystallized_kg",  "content": "kg fact"},
        {"type": "goals",            "content": "user goal"},
        {"type": "feedback",         "content": "feedback hint"},
        {"type": "curiosity",        "content": "curiosity insight"},
        {"type": "adaptive",         "content": "adaptive note"},
    ]
    selected = p.prioritize(blocks, query="test", max_blocks=3, max_total_chars=10000)
    assert len(selected) <= 3, f"Expected <= 3 blocks, got {len(selected)}"


# ── Test 4: prioritize respects max_total_chars limit ───────────────────────

def test_prioritize_respects_max_total_chars():
    p = _make_prioritizer()
    # Each block is 100 chars; budget is 250 -> at most 2 full + partial or 2 full
    content_100 = "x" * 100
    blocks = [
        {"type": "user_facts",      "content": content_100},
        {"type": "crystallized_kg", "content": content_100},
        {"type": "goals",           "content": content_100},
        {"type": "feedback",        "content": content_100},
    ]
    selected = p.prioritize(blocks, query="anything", max_blocks=10, max_total_chars=250)
    total_chars = sum(len(b["content"]) for b in selected)
    assert total_chars <= 250, f"Total chars {total_chars} exceeded budget of 250"


# ── Test 5: build_context_string joins content with newlines ────────────────

def test_build_context_string_joins_correctly():
    p = _make_prioritizer()
    blocks = [
        {"type": "user_facts",  "content": "line one"},
        {"type": "goals",       "content": "line two"},
        {"type": "curiosity",   "content": "line three"},
    ]
    result = p.build_context_string(blocks)
    assert result == "line one\nline two\nline three", f"Unexpected result: {result!r}"

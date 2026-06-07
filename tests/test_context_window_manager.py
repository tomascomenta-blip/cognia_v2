"""
tests/test_context_window_manager.py — Phase 56 CWM tests
==========================================================
20+ tests covering scoring, selection, dedup, budget, and formatting.
"""

from __future__ import annotations

import time
import math
import pytest

from cognia.context.context_window_manager import (
    ContextBlock,
    ContextWindowManager,
    _estimate_tokens,
    get_context_window_manager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block(text: str, source: str = "memory", relevance: float = 0.8,
           age_hours: float = 0.0) -> ContextBlock:
    ts = time.time() - age_hours * 3600
    return ContextBlock(text=text, source=source, relevance=relevance, timestamp=ts)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def test_token_estimation_basic():
    text = "hello world"  # 2 words
    assert _estimate_tokens(text) == int(2 * 1.3)  # 2


def test_token_estimation_scales():
    text = " ".join(["word"] * 100)
    assert _estimate_tokens(text) == int(100 * 1.3)  # 130


def test_token_estimation_empty():
    assert _estimate_tokens("") == 0


def test_context_block_auto_tokens():
    b = _block("one two three four five")
    assert b.tokens == int(5 * 1.3)  # 6


# ---------------------------------------------------------------------------
# score_block — recency_factor
# ---------------------------------------------------------------------------

def test_score_block_recency_fresh():
    cwm = ContextWindowManager()
    b = _block("test", age_hours=0.0, relevance=1.0, source="kg")
    score = cwm.score_block("test", b)
    # recency ~ 1.0, source_weight=1.0, relevance=1.0
    assert abs(score - 1.0) < 0.02


def test_score_block_recency_10h():
    cwm = ContextWindowManager()
    b = _block("test", age_hours=10.0, relevance=1.0, source="kg")
    score = cwm.score_block("test", b)
    # recency_factor = 1/(1+10*0.1) = 1/2 = 0.5
    assert abs(score - 0.5) < 0.02


def test_score_block_recency_100h():
    cwm = ContextWindowManager()
    b = _block("test", age_hours=100.0, relevance=1.0, source="kg")
    score = cwm.score_block("test", b)
    # recency_factor = 1/(1+100*0.1) = 1/11 ~ 0.0909
    assert abs(score - (1.0 / 11.0)) < 0.01


# ---------------------------------------------------------------------------
# score_block — source weights
# ---------------------------------------------------------------------------

def test_score_block_source_kg():
    cwm = ContextWindowManager()
    b = _block("fact", age_hours=0.0, relevance=1.0, source="kg")
    score = cwm.score_block("", b)
    assert abs(score - 1.0) < 0.02


def test_score_block_source_memory():
    cwm = ContextWindowManager()
    b = _block("fact", age_hours=0.0, relevance=1.0, source="memory")
    score = cwm.score_block("", b)
    assert abs(score - 0.9) < 0.02


def test_score_block_source_notes():
    cwm = ContextWindowManager()
    b = _block("fact", age_hours=0.0, relevance=1.0, source="notes")
    score = cwm.score_block("", b)
    assert abs(score - 0.8) < 0.02


def test_score_block_source_web():
    cwm = ContextWindowManager()
    b = _block("fact", age_hours=0.0, relevance=1.0, source="web")
    score = cwm.score_block("", b)
    assert abs(score - 0.7) < 0.02


def test_score_block_source_system():
    cwm = ContextWindowManager()
    b = _block("fact", age_hours=0.0, relevance=1.0, source="system")
    score = cwm.score_block("", b)
    assert abs(score - 0.5) < 0.02


def test_score_block_relevance_multiplied():
    cwm = ContextWindowManager()
    b1 = _block("fact", age_hours=0.0, relevance=0.5, source="kg")
    b2 = _block("fact", age_hours=0.0, relevance=1.0, source="kg")
    s1 = cwm.score_block("", b1)
    s2 = cwm.score_block("", b2)
    assert abs(s1 - s2 * 0.5) < 0.02


# ---------------------------------------------------------------------------
# select — basic behavior
# ---------------------------------------------------------------------------

def test_select_empty_blocks():
    cwm = ContextWindowManager()
    assert cwm.select("query", []) == []


def test_select_respects_token_budget():
    cwm = ContextWindowManager()
    # Create blocks that together exceed MAX_TOKENS=800
    big_text = " ".join(["word"] * 1000)  # ~1300 tokens
    b = _block(big_text, relevance=1.0)
    result = cwm.select("query", [b])
    total_tokens = sum(bl.tokens for bl in result)
    assert total_tokens <= ContextWindowManager.MAX_TOKENS


def test_select_sorts_by_score_descending():
    cwm = ContextWindowManager()
    b_low = _block("low score block", age_hours=50.0, relevance=0.1, source="web")
    b_high = _block("high score block", age_hours=0.0, relevance=1.0, source="kg")
    result = cwm.select("query", [b_low, b_high])
    assert result[0].text == "high score block"


def test_select_deduplicates_by_fingerprint():
    cwm = ContextWindowManager()
    text = "A" * 200  # same first 100 chars
    b1 = _block(text + "X", relevance=1.0)
    b2 = _block(text + "Y", relevance=0.9)
    result = cwm.select("query", [b1, b2])
    # Both have same fingerprint (first 100 chars identical)
    assert len(result) == 1


def test_select_different_fingerprints_both_included():
    cwm = ContextWindowManager()
    b1 = _block("Block one short", relevance=0.8, source="kg")
    b2 = _block("Block two short", relevance=0.7, source="kg")
    result = cwm.select("query", [b1, b2])
    assert len(result) == 2


def test_select_high_score_beats_low_score():
    cwm = ContextWindowManager()
    b_high = _block("important fact", age_hours=0.0, relevance=0.95, source="kg")
    b_low = _block("old web result", age_hours=200.0, relevance=0.3, source="web")
    result = cwm.select("query", [b_low, b_high])
    assert result[0].text == "important fact"


def test_select_recent_beats_old_at_same_relevance():
    cwm = ContextWindowManager()
    b_recent = _block("info A", age_hours=0.0, relevance=0.8, source="memory")
    b_old = _block("info B", age_hours=200.0, relevance=0.8, source="memory")
    result = cwm.select("query", [b_old, b_recent])
    assert result[0].text == "info A"


def test_select_kg_beats_web_at_same_recency_relevance():
    cwm = ContextWindowManager()
    b_kg = _block("fact from KG", age_hours=0.0, relevance=0.8, source="kg")
    b_web = _block("fact from web", age_hours=0.0, relevance=0.8, source="web")
    result = cwm.select("query", [b_web, b_kg])
    assert result[0].text == "fact from KG"


def test_select_whitespace_only_block_ignored():
    cwm = ContextWindowManager()
    b_empty = ContextBlock(text="   ", source="memory", relevance=1.0)
    b_real = _block("real content", relevance=0.5)
    result = cwm.select("query", [b_empty, b_real])
    assert len(result) == 1
    assert result[0].text == "real content"


# ---------------------------------------------------------------------------
# format_context
# ---------------------------------------------------------------------------

def test_format_context_empty_list():
    cwm = ContextWindowManager()
    assert cwm.format_context([]) == ""


def test_format_context_source_prefix():
    cwm = ContextWindowManager()
    b = _block("some fact", source="kg")
    result = cwm.format_context([b])
    assert "[KG]" in result
    assert "some fact" in result


def test_format_context_groups_by_source():
    cwm = ContextWindowManager()
    b1 = _block("mem fact 1", source="memory")
    b2 = _block("kg fact 1", source="kg")
    b3 = _block("mem fact 2", source="memory")
    result = cwm.format_context([b1, b2, b3])
    assert "[MEMORY]" in result
    assert "[KG]" in result


def test_format_context_hard_truncation():
    cwm = ContextWindowManager()
    char_limit = ContextWindowManager.MAX_TOKENS * 5
    b = ContextBlock(text="x " * (char_limit + 1000), source="memory", relevance=1.0)
    result = cwm.format_context([b])
    assert len(result) <= char_limit


def test_format_context_newline_separator():
    cwm = ContextWindowManager()
    b1 = _block("first block", source="memory")
    b2 = _block("second block", source="kg")
    result = cwm.format_context([b1, b2])
    assert "\n" in result


# ---------------------------------------------------------------------------
# select with near-full budget
# ---------------------------------------------------------------------------

def test_select_fills_budget_completely():
    cwm = ContextWindowManager()
    # Each block ~10 tokens; pack 80 of them so they should total 800 tokens max
    blocks = [_block(f"word{i} " * 8, relevance=1.0, source="kg") for i in range(100)]
    result = cwm.select("query", blocks)
    total_tokens = sum(b.tokens for b in result)
    assert total_tokens <= ContextWindowManager.MAX_TOKENS
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_get_context_window_manager_singleton():
    cwm1 = get_context_window_manager()
    cwm2 = get_context_window_manager()
    assert cwm1 is cwm2


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_updated_after_select():
    cwm = ContextWindowManager()
    b = _block("test block")
    cwm.select("q", [b])
    stats = cwm.get_stats()
    assert stats["select_calls"] == 1
    assert stats["avg_blocks_selected"] >= 1

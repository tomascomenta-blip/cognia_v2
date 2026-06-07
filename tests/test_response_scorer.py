"""
tests/test_response_scorer.py — Unit tests for ResponseScorer.

Uses a temp SQLite file so no real DB is touched.
"""

import os
import tempfile
import pytest

from cognia.quality.response_scorer import ResponseScorer


@pytest.fixture()
def scorer(tmp_path):
    db = str(tmp_path / "test_quality.db")
    return ResponseScorer(db_path=db)


def test_score_returns_required_keys(scorer):
    result = scorer.score("What is Python?", "Python is a programming language.")
    for key in ("completeness", "coherence", "relevance", "overall", "timestamp"):
        assert key in result, f"Missing key: {key}"


def test_completeness_between_0_and_1(scorer):
    result = scorer.score("hi", "A" * 500)
    assert 0.0 <= result["completeness"] <= 1.0


def test_completeness_caps_at_1(scorer):
    long_response = "word " * 1000
    result = scorer.score("short", long_response)
    assert result["completeness"] == 1.0


def test_relevance_identical_prompt_and_response(scorer):
    text = "neural networks deep learning model training"
    result = scorer.score(text, text)
    assert result["relevance"] > 0.5


def test_coherence_no_punctuation_below_threshold(scorer):
    # A block of text with no sentence-ending punctuation should score < 0.8
    result = scorer.score("test", "this has no terminating punctuation at all just words")
    assert result["coherence"] < 0.8


def test_coherence_well_punctuated_text(scorer):
    result = scorer.score(
        "explain something",
        "Python is a language. It supports OOP. It is widely used.",
    )
    assert result["coherence"] >= 0.8


def test_overall_is_average_of_three(scorer):
    result = scorer.score("hello world test", "hello world test sentence.")
    expected = round(
        (result["completeness"] + result["coherence"] + result["relevance"]) / 3.0, 4
    )
    assert abs(result["overall"] - expected) < 1e-6


def test_persist_does_not_raise(scorer):
    s = scorer.score("Does this work?", "Yes, it works fine.")
    scorer.persist("Does this work?", "Yes, it works fine.", s)


def test_persist_stores_row(scorer, tmp_path):
    db = str(tmp_path / "test_quality.db")
    sc = ResponseScorer(db_path=db)
    prompt   = "What is 2 + 2?"
    response = "The answer is 4."
    sc.persist(prompt, response, sc.score(prompt, response))

    from storage.db_pool import get_pool
    with get_pool(db).get() as conn:
        row = conn.execute("SELECT COUNT(*) FROM response_quality").fetchone()
    assert row[0] == 1

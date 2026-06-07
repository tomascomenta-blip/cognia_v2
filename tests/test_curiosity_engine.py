"""
tests/test_curiosity_engine.py
Tests for CuriosityEngine.
"""

import os
import tempfile
import pytest

from cognia.reasoning.curiosity_engine import CuriosityEngine


@pytest.fixture
def engine(tmp_path):
    """Return a CuriosityEngine backed by a temp DB."""
    db = str(tmp_path / "test_curiosity.db")
    return CuriosityEngine(db_path=db)


# ── generate_questions ─────────────────────────────────────────────────

def test_generate_questions_low_confidence_returns_questions(engine):
    qs = engine.generate_questions(
        prompt="transformers attention mechanism",
        response="some answer",
        confidence=0.2,
    )
    assert isinstance(qs, list)
    assert len(qs) > 0


def test_generate_questions_high_confidence_returns_empty(engine):
    qs = engine.generate_questions(
        prompt="transformers attention mechanism",
        response="some answer",
        confidence=0.6,
    )
    assert qs == []


def test_generate_questions_exactly_at_threshold_returns_empty(engine):
    qs = engine.generate_questions(
        prompt="neural network training",
        response="some answer",
        confidence=0.4,
    )
    assert qs == []


def test_generate_questions_max_two(engine):
    # Even with many keywords, max 2 questions returned
    qs = engine.generate_questions(
        prompt="deep learning transformers attention neural network training epochs",
        response="some answer",
        confidence=0.1,
    )
    assert len(qs) <= 2


def test_generate_questions_empty_prompt_returns_empty(engine):
    qs = engine.generate_questions(
        prompt="",
        response="some answer",
        confidence=0.1,
    )
    assert qs == []


# ── enqueue / get_pending ──────────────────────────────────────────────

def test_enqueue_then_get_pending(engine):
    questions = ["¿Qué no entiendo sobre transformers?", "¿Cuál es el estado del arte en attention?"]
    engine.enqueue(questions, source_prompt="tell me about transformers")
    pending = engine.get_pending(limit=10)
    pending_texts = [p["question"] for p in pending]
    for q in questions:
        assert q in pending_texts


def test_enqueue_empty_list_no_error(engine):
    # Should not raise
    engine.enqueue([], source_prompt="some prompt")
    assert engine.get_pending() == []


def test_get_pending_respects_limit(engine):
    for i in range(5):
        engine.enqueue([f"¿Qué no entiendo sobre topic{i}?"], source_prompt=f"prompt{i}")
    pending = engine.get_pending(limit=3)
    assert len(pending) <= 3


# ── mark_answered ─────────────────────────────────────────────────────

def test_mark_answered_removes_from_pending(engine):
    engine.enqueue(["¿Qué no entiendo sobre python?"], source_prompt="python question")
    pending = engine.get_pending(limit=10)
    assert len(pending) == 1
    qid = pending[0]["id"]

    engine.mark_answered(qid, "Python is a programming language.")
    pending_after = engine.get_pending(limit=10)
    assert all(p["id"] != qid for p in pending_after)


def test_mark_answered_appears_in_insights(engine):
    engine.enqueue(["¿Cuál es el estado del arte en rust?"], source_prompt="rust question")
    pending = engine.get_pending(limit=10)
    qid = pending[0]["id"]

    engine.mark_answered(qid, "Rust is a systems programming language.")
    insights = engine.get_insights(limit=10)
    assert any(i["id"] == qid for i in insights)
    matched = next(i for i in insights if i["id"] == qid)
    assert "Rust" in matched["answer"]


# ── mark_failed ───────────────────────────────────────────────────────

def test_mark_failed_removes_from_pending(engine):
    engine.enqueue(["¿Qué no entiendo sobre kubernetes?"], source_prompt="k8s question")
    pending = engine.get_pending(limit=10)
    qid = pending[0]["id"]

    engine.mark_failed(qid)
    pending_after = engine.get_pending(limit=10)
    assert all(p["id"] != qid for p in pending_after)

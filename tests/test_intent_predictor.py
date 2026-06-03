"""
tests/test_intent_predictor.py — Tests for Conversational Intent Predictor (CIP)

7 tests:
  1. test_what_is_generates_how_does
  2. test_task_request_generates_refinement
  3. test_uncertain_response_generates_clarification
  4. test_max_n_returned
  5. test_deduplicate_similar
  6. test_empty_query_no_crash
  7. test_predictions_are_strings
"""

import pytest
from cognia.reasoning.intent_predictor import IntentPredictor


@pytest.fixture
def predictor():
    return IntentPredictor()


def test_what_is_generates_how_does(predictor):
    """'what is Python?' should produce at least one follow-up containing 'how'."""
    followups = predictor.predict_followups("what is Python?", "Python is a programming language.")
    assert len(followups) > 0, "Expected at least one follow-up"
    texts = " ".join(followups).lower()
    assert "how" in texts, f"Expected a 'how' follow-up; got: {followups}"


def test_task_request_generates_refinement(predictor):
    """'write code for sorting' should suggest refinement or explanation."""
    followups = predictor.predict_followups(
        "write code for sorting a list",
        "```python\ndef sort_list(lst): return sorted(lst)\n```",
    )
    assert len(followups) > 0, "Expected at least one follow-up"
    texts = " ".join(followups).lower()
    # Accept any of: efficient, error, explain, improve, detailed
    assert any(kw in texts for kw in ("efficient", "error", "explain", "improve", "detail")), (
        f"Expected refinement/explanation follow-up; got: {followups}"
    )


def test_uncertain_response_generates_clarification(predictor):
    """Response with 'I'm not certain' should produce clarification follow-ups."""
    followups = predictor.predict_followups(
        "when was the Eiffel Tower built?",
        "I'm not certain about the exact date, but I think it was around 1889.",
    )
    assert len(followups) > 0, "Expected at least one follow-up"
    texts = " ".join(followups).lower()
    assert any(kw in texts for kw in ("sure", "specific", "certain")), (
        f"Expected clarification follow-up; got: {followups}"
    )


def test_max_n_returned(predictor):
    """predict(n=3) should return at most 3 results."""
    followups = predictor.predict_followups(
        "what is machine learning?",
        "Machine learning is a subset of AI that enables computers to learn from data.",
        n=3,
    )
    assert len(followups) <= 3, f"Expected at most 3 follow-ups, got {len(followups)}: {followups}"


def test_deduplicate_similar(predictor):
    """Returned follow-ups should not be near-identical to each other."""
    followups = predictor.predict_followups(
        "what is a neural network?",
        "A neural network is a computational model inspired by the brain.",
        n=3,
    )
    # Check pairwise: no two results should have token overlap >= 0.75
    from cognia.reasoning.intent_predictor import _token_sim
    for i, a in enumerate(followups):
        for j, b in enumerate(followups):
            if i >= j:
                continue
            sim = _token_sim(a, b)
            assert sim < 0.75, (
                f"Follow-ups too similar (sim={sim:.2f}): '{a}' vs '{b}'"
            )


def test_empty_query_no_crash(predictor):
    """Empty query string should return an empty list without raising."""
    result = predictor.predict_followups("", "Some response text here.")
    assert result == [], f"Expected [] for empty query, got: {result}"

    result2 = predictor.predict_followups("   ", "Another response.")
    assert result2 == [], f"Expected [] for whitespace query, got: {result2}"


def test_predictions_are_strings(predictor):
    """All returned predictions must be non-empty strings."""
    followups = predictor.predict_followups(
        "explain recursion",
        "Recursion is when a function calls itself to solve sub-problems.",
        n=3,
    )
    for item in followups:
        assert isinstance(item, str), f"Expected str, got {type(item)}: {item!r}"
        assert item.strip(), f"Expected non-empty string, got: {item!r}"

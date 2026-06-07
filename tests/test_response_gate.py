"""
test_response_gate.py -- 20+ unit tests for ResponseGate.
"""

import sys
import os

_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest
from cognia.quality.response_gate import ResponseGate


@pytest.fixture
def gate():
    return ResponseGate()


# ---- score: edge cases -------------------------------------------------

def test_empty_response_scores_zero(gate):
    assert gate.score("What is Python?", "") == 0.0


def test_whitespace_only_scores_zero(gate):
    assert gate.score("What is Python?", "   ") == 0.0


def test_very_short_response_scores_low(gate):
    s = gate.score("What is machine learning?", "ok")
    assert s < 0.35, f"Expected <0.35, got {s}"


def test_short_response_below_20_chars_scores_low(gate):
    s = gate.score("Explain quantum computing", "Too short")
    assert s < 0.35


def test_long_relevant_response_scores_high(gate):
    question = "What is machine learning?"
    response = (
        "Machine learning is a branch of artificial intelligence that enables "
        "computers to learn from data and improve their performance on tasks "
        "without being explicitly programmed. It uses statistical techniques "
        "to identify patterns in large datasets."
    )
    s = gate.score(question, response)
    assert s > 0.7, f"Expected >0.7, got {s}"


def test_score_returns_float_in_range(gate):
    s = gate.score("Hello world", "This is a test response that has some content.")
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


# ---- length sub-score --------------------------------------------------

def test_length_below_20_gives_zero_length_subscore(gate):
    # length_s = 0.0 for <20 chars; with keywords in question, relevance also low
    s = gate.score("Explain artificial intelligence thoroughly", "nope")
    assert s < 0.35


def test_length_50_to_200_gives_07_length_subscore(gate):
    question = "What is Python?"
    response = "Python is a programming language known for simplicity and power in data work."
    s = gate.score(question, response)
    assert s > 0.5


def test_length_over_200_chars(gate):
    question = "Tell me about Python"
    response = "Python is great. " * 15
    s = gate.score(question, response)
    assert s >= 0.5


# ---- relevance sub-score -----------------------------------------------

def test_off_topic_response_scores_lower_than_relevant(gate):
    question = "Explain neural networks and deep learning"
    off_topic = "The weather is sunny today and the sky is blue and birds are flying."
    relevant  = (
        "Neural networks are computational models inspired by the human brain. "
        "Deep learning uses many layers of neural networks to learn complex patterns."
    )
    assert gate.score(question, off_topic) < gate.score(question, relevant)


def test_keyword_matching_is_case_insensitive(gate):
    question = "What is PYTHON used for?"
    response = "python is widely used for data science, automation, and web development."
    s = gate.score(question, response)
    assert s > 0.5


def test_stopwords_not_counted_as_keywords(gate):
    # Question has only stopwords -> keywords list empty -> neutral relevance 0.5
    question = "what is the"
    response = "This does not address the question in any useful way."
    s = gate.score(question, response)
    assert s > 0.3


def test_question_echo_triggers_retry(gate):
    # Echo kills the refusal sub-score (0.0) and should trigger a retry
    question = "What is artificial intelligence?"
    retry, reason = gate.should_retry(question, question)
    assert retry is True


# ---- refusal detection -------------------------------------------------

def test_i_cannot_short_response_triggers_retry(gate):
    retry, reason = gate.should_retry(
        "Help me write a cover letter",
        "I cannot help with that."
    )
    assert retry is True


def test_i_cant_short_response_triggers_retry(gate):
    retry, reason = gate.should_retry(
        "Explain gradient descent",
        "I can't answer that question."
    )
    assert retry is True


def test_no_puedo_spanish_refusal_triggers_retry(gate):
    retry, reason = gate.should_retry(
        "Explica el aprendizaje automatico",
        "No puedo responder eso."
    )
    assert retry is True


def test_no_se_spanish_triggers_retry(gate):
    retry, reason = gate.should_retry(
        "Que es Python?",
        "No se la respuesta."
    )
    assert retry is True


def test_error_marker_gives_low_score(gate):
    s = gate.score("Run the code", "Error: module not found. Please check your imports.")
    assert s < 0.7


def test_exception_marker_gives_low_score(gate):
    s = gate.score("What happened?", "Exception: NullPointerException occurred at line 42.")
    assert s < 0.7


# ---- should_retry ------------------------------------------------------

def test_good_response_no_retry(gate):
    question = "What is supervised learning?"
    response = (
        "Supervised learning is a type of machine learning where the model "
        "is trained on labeled data. The algorithm learns to map inputs to "
        "outputs using example pairs provided during training."
    )
    retry, reason = gate.should_retry(question, response)
    assert retry is False
    assert reason == ""


def test_retry_reason_is_ascii(gate):
    retry, reason = gate.should_retry("Explain AI", "Ok.")
    assert retry is True
    assert reason.isascii()


def test_retry_reason_for_short_response(gate):
    # Use a question with keywords so relevance is also low for a 2-char response
    retry, reason = gate.should_retry("Explain artificial intelligence concepts", "Hi")
    assert retry is True
    assert reason == "response too short"


def test_retry_reason_for_refusal(gate):
    retry, reason = gate.should_retry(
        "What is machine learning?",
        "I cannot provide information on that topic."
    )
    assert retry is True
    assert reason == "incomplete response"


# ---- build_retry_prompt ------------------------------------------------

def test_build_retry_prompt_contains_original_question(gate):
    question = "What is reinforcement learning?"
    prompt = gate.build_retry_prompt(question, "I cannot help.", "incomplete response")
    assert question in prompt


def test_build_retry_prompt_contains_reason(gate):
    prompt = gate.build_retry_prompt(
        "Explain backpropagation",
        "Too short",
        "response too short"
    )
    assert "response too short" in prompt


def test_build_retry_prompt_starts_with_template(gate):
    prompt = gate.build_retry_prompt(
        "How does backpropagation work?",
        "bad",
        "response too short"
    )
    assert prompt.startswith("The previous answer was response too short.")


def test_build_retry_prompt_ends_with_question(gate):
    q = "How does backpropagation work?"
    p = gate.build_retry_prompt(q, "bad", "response too short")
    assert p.endswith(q)


# ---- weighted score correctness ----------------------------------------

def test_combined_score_weighting_correct(gate):
    """Weighted combination: length(0.3)+relevance(0.4)+refusal(0.3)."""
    question = "neural network"
    response = "neural " * 40  # >200 chars, "neural" keyword present
    s = gate.score(question, response)
    # length_s = 1.0, refusal_s = 1.0, relevance > 0
    # min score = 0.6 + 0 = 0.6 (even with zero relevance on 1 keyword)
    assert s >= 0.6


def test_score_is_clamped_to_0_1(gate):
    """Score must always be in [0.0, 1.0]."""
    cases = [
        ("", ""),
        ("x", "x" * 1000),
        (
            "A very detailed technical question about deep learning architectures",
            "Deep learning architectures such as transformers and CNNs are widely used "
            "in computer vision and natural language processing applications today.",
        ),
    ]
    for question, response in cases:
        s = gate.score(question, response)
        assert 0.0 <= s <= 1.0, f"Score out of range: {s}"

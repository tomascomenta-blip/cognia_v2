"""
Tests for cognia/tools/tool_router.py and cognia/adaptive/feedback_learner.py.
Uses tmp_path for FeedbackLearner so tests are hermetic and leave no DB files.
"""
import os
import sys
import pytest

# Ensure project root is on sys.path so storage.db_pool resolves
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cognia.tools.tool_router import ToolChoice, ToolRouter
from cognia.adaptive.feedback_learner import FeedbackLearner
from storage.db_pool import close_pool


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def router():
    return ToolRouter()


@pytest.fixture
def learner(tmp_path):
    db = str(tmp_path / "feedback_test.db")
    fl = FeedbackLearner(db_path=db)
    yield fl
    close_pool(db)


# ─────────────────────────────────────────────────────────────────────────────
# ToolChoice enum
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_choice_enum_values():
    assert ToolChoice.WEB_SEARCH.value == "web_search"
    assert ToolChoice.KNOWLEDGE_GRAPH.value == "knowledge_graph"
    assert ToolChoice.LLM_ONLY.value == "llm_only"
    assert ToolChoice.CURIOSITY_INSIGHTS.value == "curiosity_insights"


# ─────────────────────────────────────────────────────────────────────────────
# ToolRouter.route()
# ─────────────────────────────────────────────────────────────────────────────

def test_route_web_signal_hoy(router):
    assert router.route("que paso hoy en el mundo") == ToolChoice.WEB_SEARCH


def test_route_web_signal_today(router):
    assert router.route("What is the price today?") == ToolChoice.WEB_SEARCH


def test_route_web_signal_news(router):
    assert router.route("latest news about AI") == ToolChoice.WEB_SEARCH


def test_route_kg_signal_what_is(router):
    assert router.route("what is machine learning") == ToolChoice.KNOWLEDGE_GRAPH


def test_route_kg_signal_define(router):
    assert router.route("define recursion in computer science") == ToolChoice.KNOWLEDGE_GRAPH


def test_route_llm_fallback(router):
    assert router.route("write me a poem about autumn") == ToolChoice.LLM_ONLY


def test_route_llm_fallback_code(router):
    assert router.route("help me refactor this function") == ToolChoice.LLM_ONLY


# Web signals take priority over KG signals
def test_route_web_priority_over_kg(router):
    # "today" (web) + "what is" (kg) → web wins because web is checked first
    result = router.route("what is happening today")
    assert result == ToolChoice.WEB_SEARCH


# ─────────────────────────────────────────────────────────────────────────────
# ToolRouter.route_with_confidence()
# ─────────────────────────────────────────────────────────────────────────────

def test_route_with_confidence_no_signals(router):
    tool, conf = router.route_with_confidence("tell me a joke")
    assert tool == ToolChoice.LLM_ONLY
    assert conf == 0.0


def test_route_with_confidence_web_wins(router):
    tool, conf = router.route_with_confidence("latest news today")
    assert tool == ToolChoice.WEB_SEARCH
    assert 0.0 < conf <= 1.0


def test_route_with_confidence_kg_wins(router):
    tool, conf = router.route_with_confidence("what is the concept of relativity")
    assert tool == ToolChoice.KNOWLEDGE_GRAPH
    assert 0.0 < conf <= 1.0


def test_route_with_confidence_clamped(router):
    # Confidence must never exceed 1.0
    tool, conf = router.route_with_confidence(
        "hoy today ahora now latest recent precio price noticias news"
    )
    assert conf <= 1.0
    assert conf >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ToolRouter.execute()
# ─────────────────────────────────────────────────────────────────────────────

def test_execute_returns_dict_shape(router):
    result = router.execute("write me a haiku")
    assert isinstance(result, dict)
    assert "tool" in result
    assert "confidence" in result
    assert "result" in result
    assert "error" in result


def test_execute_tool_value_is_string(router):
    result = router.execute("tell me about machine learning")
    assert isinstance(result["tool"], str)


def test_execute_confidence_is_float(router):
    result = router.execute("hoy es un buen dia")
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0


def test_execute_result_is_dict(router):
    result = router.execute("help me debug this code")
    assert isinstance(result["result"], dict)


# ─────────────────────────────────────────────────────────────────────────────
# FeedbackLearner.detect_signal()
# ─────────────────────────────────────────────────────────────────────────────

def test_feedback_detect_signal_positive(learner):
    assert learner.detect_signal("gracias, muy util") == "positive"


def test_feedback_detect_signal_positive_english(learner):
    assert learner.detect_signal("Thanks! That was great.") == "positive"


def test_feedback_detect_signal_negative(learner):
    assert learner.detect_signal("eso esta incorrecto") == "negative"


def test_feedback_detect_signal_negative_phrase(learner):
    assert learner.detect_signal("intenta de nuevo por favor") == "negative"


def test_feedback_detect_neutral(learner):
    assert learner.detect_signal("hello world") == "neutral"


def test_feedback_detect_neutral_empty(learner):
    assert learner.detect_signal("") == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# FeedbackLearner.record() + get_stats()
# ─────────────────────────────────────────────────────────────────────────────

def test_feedback_record_and_stats(learner):
    learner.record("msg1", "positive", "general")
    learner.record("msg2", "positive", "general")
    learner.record("msg3", "positive", "general")
    learner.record("msg4", "negative", "general")
    stats = learner.get_stats()
    assert stats["total"] == 4
    assert stats["positive"] == 3
    assert stats["negative"] == 1
    assert isinstance(stats["top_positive_types"], list)
    assert isinstance(stats["top_negative_types"], list)


def test_feedback_invalid_signal_becomes_neutral(learner):
    learner.record("msg_x", "unknown_signal", "test")
    stats = learner.get_stats()
    assert stats["total"] == 1
    assert stats["positive"] == 0
    assert stats["negative"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# FeedbackLearner.get_adjustment_hint()
# ─────────────────────────────────────────────────────────────────────────────

def test_feedback_adjustment_hint_below_threshold(learner):
    # < 5 total entries → empty hint
    learner.record("a", "positive", "code")
    learner.record("b", "positive", "code")
    hint = learner.get_adjustment_hint("code")
    assert hint == ""


def test_feedback_adjustment_hint_positive(learner):
    for i in range(10):
        learner.record(f"pos_{i}", "positive", "code")
    hint = learner.get_adjustment_hint("code")
    assert "Continue" in hint


def test_feedback_adjustment_hint_negative(learner):
    for i in range(10):
        learner.record(f"neg_{i}", "negative", "math")
    hint = learner.get_adjustment_hint("math")
    assert "unsatisfactory" in hint or "precise" in hint


def test_feedback_adjustment_hint_unknown_type(learner):
    # No records for this query_type → empty hint
    hint = learner.get_adjustment_hint("nonexistent_type")
    assert hint == ""


def test_feedback_top_positive_types(learner):
    for i in range(6):
        learner.record(f"p{i}", "positive", "science")
    stats = learner.get_stats()
    assert "science" in stats["top_positive_types"]


def test_feedback_top_negative_types(learner):
    for i in range(6):
        learner.record(f"n{i}", "negative", "history")
    stats = learner.get_stats()
    assert "history" in stats["top_negative_types"]

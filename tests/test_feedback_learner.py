"""Tests for cognia.adaptive.feedback_learner.FeedbackLearner."""
import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.adaptive.feedback_learner import FeedbackLearner


@pytest.fixture
def learner(tmp_path):
    db = str(tmp_path / "feedback_test.db")
    return FeedbackLearner(db_path=db)


def test_record_inserts_row(learner):
    learner.record("msg-001", "positive", "general")
    stats = learner.get_stats()
    assert stats["total"] == 1
    assert stats["positive"] == 1


def test_detect_signal_positive(learner):
    assert learner.detect_signal("Gracias, exacto!") == "positive"
    assert learner.detect_signal("perfect answer") == "positive"
    assert learner.detect_signal("genial, thanks") == "positive"


def test_detect_signal_negative(learner):
    assert learner.detect_signal("eso esta mal") == "negative"
    assert learner.detect_signal("incorrecto, intenta de nuevo") == "negative"
    assert learner.detect_signal("that is wrong") == "negative"


def test_detect_signal_neutral(learner):
    assert learner.detect_signal("Hola, como estas?") == "neutral"
    assert learner.detect_signal("Cuéntame sobre Python") == "neutral"


def test_get_adjustment_hint_empty_when_few_signals(learner):
    for i in range(4):
        learner.record(f"msg-{i}", "positive", "tech")
    hint = learner.get_adjustment_hint("tech")
    assert hint == ""


def test_get_stats_returns_required_keys(learner):
    learner.record("a", "positive", "general")
    learner.record("b", "negative", "code")
    stats = learner.get_stats()
    assert "total" in stats
    assert "positive" in stats
    assert "negative" in stats
    assert "top_positive_types" in stats
    assert "top_negative_types" in stats
    assert stats["total"] == 2

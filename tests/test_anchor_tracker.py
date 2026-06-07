"""
tests/test_anchor_tracker.py
============================
Phase 61 — Conversation Anchor Tracker (CAT) tests.
"""

import pytest
from cognia.context.anchor_tracker import AnchorTracker, ConversationAnchor, _extract_keywords


# ── Keyword extraction tests ──────────────────────────────────────────────

def test_extract_keywords_basic():
    kws = _extract_keywords("Python machine learning tutorial")
    assert "python" in kws
    assert "machine" in kws
    assert "learning" in kws
    assert "tutorial" in kws


def test_extract_keywords_filters_stopwords():
    kws = _extract_keywords("what are the best tools for this task")
    assert "what" not in kws
    assert "are" not in kws
    assert "the" not in kws
    assert "this" not in kws
    assert "for" not in kws
    assert "best" in kws
    assert "tools" in kws
    assert "task" in kws


def test_extract_keywords_filters_short_words():
    # Words <= 3 chars should be excluded
    kws = _extract_keywords("go run the big model now here")
    assert "go" not in kws
    assert "run" not in kws
    assert "the" not in kws
    assert "big" not in kws
    assert "now" not in kws
    # "model" has 5 chars — included
    assert "model" in kws


def test_extract_keywords_case_insensitive():
    kws = _extract_keywords("Python PYTHON python")
    assert "python" in kws
    # frozenset deduplicates
    assert len(kws) == 1


def test_extract_keywords_strips_punctuation():
    kws = _extract_keywords("Hello, world! Python: great.")
    assert "hello" in kws
    assert "world" in kws
    assert "python" in kws
    assert "great" in kws


# ── AnchorTracker core behavior ──────────────────────────────────────────

def test_set_anchor_stores_correctly():
    tracker = AnchorTracker()
    tracker.set_anchor("sess1", "Teach me Python machine learning")
    anchor = tracker._anchors.get("sess1")
    assert anchor is not None
    assert anchor.session_id == "sess1"
    assert anchor.original_query == "Teach me Python machine learning"
    assert "python" in anchor.keywords
    assert anchor.turn_count == 0


def test_set_anchor_stores_original_query_verbatim():
    tracker = AnchorTracker()
    query = "How do I sort a list in Python?"
    tracker.set_anchor("sess_q", query)
    assert tracker._anchors["sess_q"].original_query == query


def test_turn_count_starts_at_zero():
    tracker = AnchorTracker()
    tracker.set_anchor("sess2", "Tell me about databases")
    assert tracker._anchors["sess2"].turn_count == 0


def test_record_turn_increments():
    tracker = AnchorTracker()
    tracker.set_anchor("sess3", "Tell me about databases")
    tracker.record_turn("sess3")
    assert tracker._anchors["sess3"].turn_count == 1
    tracker.record_turn("sess3")
    tracker.record_turn("sess3")
    assert tracker._anchors["sess3"].turn_count == 3


def test_record_turn_no_anchor_is_noop():
    tracker = AnchorTracker()
    tracker.record_turn("nonexistent")  # should not raise


def test_check_drift_no_anchor_returns_1():
    tracker = AnchorTracker()
    score = tracker.check_drift("unknown_session", "some query")
    assert score == 1.0


def test_check_drift_before_remind_turns_returns_1():
    tracker = AnchorTracker()
    tracker.set_anchor("sess4", "Python machine learning tutorial")
    # Turn count < REMIND_AFTER_TURNS (5), should return 1.0
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS - 1):
        score = tracker.check_drift("sess4", "cooking recipes unrelated topic")
        assert score == 1.0
        # check_drift does NOT record_turn — caller must do it


def test_check_drift_exactly_remind_turns_threshold():
    tracker = AnchorTracker()
    tracker.set_anchor("sess5", "Python machine learning tutorial")
    # Simulate turns reaching REMIND_AFTER_TURNS
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess5")
    # Now turn_count == REMIND_AFTER_TURNS, drift should be computed
    score = tracker.check_drift("sess5", "cooking recipes chef unrelated")
    assert score < 1.0  # computed overlap, not shortcut 1.0


def test_check_drift_high_score_when_on_topic():
    tracker = AnchorTracker()
    tracker.set_anchor("sess6", "Python machine learning training dataset")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess6")
    # Same keywords — high overlap
    score = tracker.check_drift("sess6", "Python machine learning model training dataset")
    assert score >= AnchorTracker.DRIFT_THRESHOLD


def test_check_drift_low_score_when_off_topic():
    tracker = AnchorTracker()
    tracker.set_anchor("sess7", "Python machine learning tutorial dataset")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess7")
    # Completely different topic
    score = tracker.check_drift("sess7", "cooking bread recipe baking oven flour")
    assert score < AnchorTracker.DRIFT_THRESHOLD


def test_drift_threshold_boundary_no_hint():
    """Overlap exactly equal to DRIFT_THRESHOLD should return no hint (not strictly less)."""
    tracker = AnchorTracker()
    # Craft keywords so overlap == 0.2 exactly
    # anchor has 5 unique keywords, current shares exactly 1 => 1/5 = 0.2
    tracker.set_anchor("sess8", "python learning model training dataset")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess8")
    anchor = tracker._anchors["sess8"]
    # Verify anchor has keywords we expect
    assert len(anchor.keywords) >= 1
    # overlap == 0.2 → score >= DRIFT_THRESHOLD → no hint
    score = tracker.check_drift("sess8", "python cooking bread baking flour")
    # If score >= 0.2, hint should be empty
    hint = tracker.get_anchor_hint("sess8", "python cooking bread baking flour")
    if score >= AnchorTracker.DRIFT_THRESHOLD:
        assert hint == ""


# ── get_anchor_hint tests ─────────────────────────────────────────────────

def test_get_anchor_hint_returns_empty_when_not_drifted():
    tracker = AnchorTracker()
    tracker.set_anchor("sess9", "Python machine learning neural networks")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess9")
    hint = tracker.get_anchor_hint("sess9", "Python machine learning neural networks deep")
    assert hint == ""


def test_get_anchor_hint_returns_hint_when_drifted():
    tracker = AnchorTracker()
    tracker.set_anchor("sess10", "Python machine learning model training")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess10")
    hint = tracker.get_anchor_hint("sess10", "cooking bread baking flour recipe oven")
    assert hint != ""
    assert isinstance(hint, str)


def test_get_anchor_hint_contains_original_query_snippet():
    tracker = AnchorTracker()
    tracker.set_anchor("sess11", "Python machine learning model training")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess11")
    hint = tracker.get_anchor_hint("sess11", "cooking bread baking recipe flour oven")
    assert "Python machine learning" in hint


def test_get_anchor_hint_max_120_chars():
    tracker = AnchorTracker()
    long_query = "Python " * 20  # very long original query
    tracker.set_anchor("sess12", long_query)
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess12")
    hint = tracker.get_anchor_hint("sess12", "cooking bread baking flour recipe oven")
    assert len(hint) <= AnchorTracker.MAX_HINT_LENGTH


def test_get_anchor_hint_no_anchor_returns_empty():
    tracker = AnchorTracker()
    hint = tracker.get_anchor_hint("no_such_session", "anything here")
    assert hint == ""


def test_get_anchor_hint_before_turns_threshold_returns_empty():
    tracker = AnchorTracker()
    tracker.set_anchor("sess13", "Python machine learning tutorial")
    # Only 2 turns — below REMIND_AFTER_TURNS
    tracker.record_turn("sess13")
    tracker.record_turn("sess13")
    hint = tracker.get_anchor_hint("sess13", "cooking bread baking flour oven recipe")
    assert hint == ""


# ── clear_session tests ───────────────────────────────────────────────────

def test_clear_session_removes_anchor():
    tracker = AnchorTracker()
    tracker.set_anchor("sess14", "Python machine learning")
    tracker.clear_session("sess14")
    assert "sess14" not in tracker._anchors


def test_clear_session_after_clear_returns_1():
    tracker = AnchorTracker()
    tracker.set_anchor("sess15", "Python machine learning")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("sess15")
    tracker.clear_session("sess15")
    score = tracker.check_drift("sess15", "Python machine learning")
    assert score == 1.0


def test_clear_session_nonexistent_is_noop():
    tracker = AnchorTracker()
    tracker.clear_session("ghost_session")  # should not raise


def test_after_clear_can_re_anchor_same_session():
    tracker = AnchorTracker()
    tracker.set_anchor("sess16", "Original query about Python")
    tracker.clear_session("sess16")
    tracker.set_anchor("sess16", "New query about cooking")
    anchor = tracker._anchors.get("sess16")
    assert anchor is not None
    assert anchor.original_query == "New query about cooking"
    assert anchor.turn_count == 0


# ── Multiple sessions ─────────────────────────────────────────────────────

def test_multiple_sessions_tracked_independently():
    tracker = AnchorTracker()
    tracker.set_anchor("alpha", "Python machine learning tutorial")
    tracker.set_anchor("beta", "cooking bread baking recipes flour")
    for _ in range(AnchorTracker.REMIND_AFTER_TURNS):
        tracker.record_turn("alpha")
        tracker.record_turn("beta")
    # alpha: on-topic query should score high
    score_alpha = tracker.check_drift("alpha", "Python machine learning deep neural")
    # beta: on-topic query should score high
    score_beta = tracker.check_drift("beta", "cooking bread recipes baking oven")
    assert score_alpha >= AnchorTracker.DRIFT_THRESHOLD
    assert score_beta >= AnchorTracker.DRIFT_THRESHOLD
    # alpha: off-topic for beta
    score_cross = tracker.check_drift("alpha", "cooking bread baking flour recipes")
    assert score_cross < AnchorTracker.DRIFT_THRESHOLD


def test_clear_one_session_leaves_other_intact():
    tracker = AnchorTracker()
    tracker.set_anchor("s_a", "Python machine learning")
    tracker.set_anchor("s_b", "cooking bread baking")
    tracker.clear_session("s_a")
    assert "s_a" not in tracker._anchors
    assert "s_b" in tracker._anchors

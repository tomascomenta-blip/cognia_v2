"""tests/test_style_engine_phase54.py -- Phase 54: StyleEngine unit tests"""

import os
import sys
import tempfile
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from storage.db_pool import get_pool, close_pool
from cognia.adaptive.style_engine import StyleEngine


def _make_engine():
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = StyleEngine(tmp_path)
    return engine, tmp_path


def _cleanup(db_path):
    close_pool(db_path)
    try:
        os.unlink(db_path)
    except Exception:
        pass


# ── Schema / init ────────────────────────────────────────────────────────

def test_table_created_on_init():
    engine, db_path = _make_engine()
    try:
        with get_pool(db_path).get() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='style_profile'"
            ).fetchone()
        assert row is not None
    finally:
        _cleanup(db_path)


def test_initial_profile_defaults():
    engine, db_path = _make_engine()
    try:
        p = engine.get_profile()
        assert p["turn_count"] == 0
        assert p["formality_score"] == 0.5
        assert p["detail_score"] == 0.5
        assert p["avg_user_msg_len"] == 0.0
    finally:
        _cleanup(db_path)


# ── record_exchange basics ────────────────────────────────────────────────

def test_turn_count_increments():
    engine, db_path = _make_engine()
    try:
        engine.record_exchange("Hello", "Hi there")
        engine.record_exchange("How are you?", "I am fine")
        assert engine.get_profile()["turn_count"] == 2
    finally:
        _cleanup(db_path)


def test_record_exchange_stores_avg_len():
    engine, db_path = _make_engine()
    try:
        engine.record_exchange("Hi", "Hello back")
        p = engine.get_profile()
        assert p["avg_user_msg_len"] == 2.0
    finally:
        _cleanup(db_path)


def test_avg_user_msg_len_after_multiple_turns():
    engine, db_path = _make_engine()
    try:
        engine.record_exchange("a" * 10, "resp")
        engine.record_exchange("b" * 20, "resp")
        p = engine.get_profile()
        assert abs(p["avg_user_msg_len"] - 15.0) < 1.0
    finally:
        _cleanup(db_path)


def test_get_profile_returns_dict_with_all_fields():
    engine, db_path = _make_engine()
    try:
        p = engine.get_profile()
        for key in ["avg_user_msg_len", "avg_assistant_msg_len", "formality_score",
                    "detail_score", "turn_count", "last_updated"]:
            assert key in p
    finally:
        _cleanup(db_path)


# ── Formality score ───────────────────────────────────────────────────────

def test_formality_score_increases_with_formal_language():
    engine, db_path = _make_engine()
    try:
        initial = engine.get_profile()["formality_score"]
        engine.record_exchange("Could you please help me?", "Sure")
        p = engine.get_profile()
        assert p["formality_score"] > initial
    finally:
        _cleanup(db_path)


def test_formality_score_decreases_with_casual_lol():
    engine, db_path = _make_engine()
    try:
        initial = engine.get_profile()["formality_score"]
        engine.record_exchange("lol that was funny", "Glad you liked it")
        p = engine.get_profile()
        assert p["formality_score"] < initial
    finally:
        _cleanup(db_path)


def test_formality_score_decreases_with_jaja():
    engine, db_path = _make_engine()
    try:
        initial = engine.get_profile()["formality_score"]
        engine.record_exchange("jaja que gracioso", "Que bueno")
        p = engine.get_profile()
        assert p["formality_score"] < initial
    finally:
        _cleanup(db_path)


def test_formality_score_decreases_with_btw():
    engine, db_path = _make_engine()
    try:
        engine.record_exchange("btw what time is it", "It's noon")
        p = engine.get_profile()
        assert p["formality_score"] < 0.5
    finally:
        _cleanup(db_path)


def test_formality_score_increases_with_would_you():
    engine, db_path = _make_engine()
    try:
        engine.record_exchange("Would you explain this?", "Of course")
        p = engine.get_profile()
        assert p["formality_score"] > 0.5
    finally:
        _cleanup(db_path)


def test_formality_score_increases_with_por_favor():
    engine, db_path = _make_engine()
    try:
        engine.record_exchange("por favor explica esto", "Claro")
        p = engine.get_profile()
        assert p["formality_score"] > 0.5
    finally:
        _cleanup(db_path)


# ── Detail score ──────────────────────────────────────────────────────────

def test_detail_score_increases_with_question_mark():
    engine, db_path = _make_engine()
    try:
        initial = engine.get_profile()["detail_score"]
        engine.record_exchange("What is machine learning?", "ML is...")
        p = engine.get_profile()
        assert p["detail_score"] > initial
    finally:
        _cleanup(db_path)


def test_detail_score_decreases_after_terse_followup_to_long_response():
    engine, db_path = _make_engine()
    try:
        long_response = "x" * 300
        engine.record_exchange("Tell me everything about Python", long_response)
        p_after_long = engine.get_profile()
        engine.record_exchange("ok", long_response)
        p_after_terse = engine.get_profile()
        assert p_after_terse["detail_score"] <= p_after_long["detail_score"]
    finally:
        _cleanup(db_path)


# ── get_style_hint gating ─────────────────────────────────────────────────

def test_style_hint_empty_before_5_turns():
    engine, db_path = _make_engine()
    try:
        for i in range(4):
            engine.record_exchange("hi", "hello")
        assert engine.get_style_hint() == ""
    finally:
        _cleanup(db_path)


def test_style_hint_returns_string_after_5_turns():
    engine, db_path = _make_engine()
    try:
        for i in range(5):
            engine.record_exchange("hi", "hello")
        hint = engine.get_style_hint()
        assert isinstance(hint, str) and len(hint) > 0
    finally:
        _cleanup(db_path)


# ── get_style_hint content ────────────────────────────────────────────────

def test_style_hint_brief_for_terse_user():
    engine, db_path = _make_engine()
    try:
        for _ in range(5):
            engine.record_exchange("hi", "hello")
        hint = engine.get_style_hint()
        assert "brief" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_detailed_for_verbose_user():
    engine, db_path = _make_engine()
    try:
        for _ in range(5):
            engine.record_exchange("x" * 200, "response")
        hint = engine.get_style_hint()
        assert "detailed" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_moderate_for_normal_length():
    engine, db_path = _make_engine()
    try:
        for _ in range(5):
            engine.record_exchange("x" * 80, "response")
        hint = engine.get_style_hint()
        assert "moderate" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_casual_for_casual_user():
    engine, db_path = _make_engine()
    try:
        # Drive formality score well below 0.4 by repeated casual signals
        for _ in range(20):
            engine.record_exchange("lol jaja haha ok idk", "ok")
        hint = engine.get_style_hint()
        assert "casual" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_formal_for_formal_user():
    engine, db_path = _make_engine()
    try:
        for _ in range(20):
            engine.record_exchange("Could you please kindly help me?", "Of course")
        hint = engine.get_style_hint()
        assert "formal" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_brief_casual_concise_for_terse_casual():
    engine, db_path = _make_engine()
    try:
        for _ in range(20):
            engine.record_exchange("lol ok", "sure")
        hint = engine.get_style_hint()
        assert "brief" in hint
        assert "casual" in hint
        assert "concise" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_detailed_formal_high_detail_for_formal_verbose():
    engine, db_path = _make_engine()
    try:
        for _ in range(20):
            engine.record_exchange(
                "Could you please explain in detail: " + "x" * 160 + "?",
                "Of course"
            )
        hint = engine.get_style_hint()
        assert "detailed" in hint
        assert "formal" in hint
        assert "high-detail" in hint
    finally:
        _cleanup(db_path)


def test_style_hint_starts_with_style_prefix():
    engine, db_path = _make_engine()
    try:
        for _ in range(5):
            engine.record_exchange("hello", "hi")
        hint = engine.get_style_hint()
        assert hint.startswith("Style: ")
    finally:
        _cleanup(db_path)


def test_spanish_casual_jaja_detected():
    engine, db_path = _make_engine()
    try:
        before = engine.get_profile()["formality_score"]
        engine.record_exchange("jaja muy gracioso", "me alegro")
        after = engine.get_profile()["formality_score"]
        assert after < before
    finally:
        _cleanup(db_path)

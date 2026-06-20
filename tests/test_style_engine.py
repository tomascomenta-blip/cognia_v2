"""tests/test_style_engine.py -- unit tests for cognia/learning/style_engine.py"""
import json
import sys
import types
from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

# NOTE: StyleEngine lazy-imports db_connect_pooled INSIDE its save()/load()
# methods, so importing it here needs no DB stub. The "DB mocked" tests below
# patch "storage.db_pool.db_connect_pooled" per-test instead. A previous version
# injected an INCOMPLETE fake `storage.db_pool` module (only db_connect_pooled)
# into sys.modules via setdefault; when this file collected before the real
# module loaded, every later `from storage.db_pool import get_pool` failed with
# "cannot import name 'get_pool'". Do NOT reintroduce a module-level stub here.
from cognia.learning.style_engine import StyleHint, StyleEngine  # noqa: E402


# ---------------------------------------------------------------------------
# StyleHint -- round-trip
# ---------------------------------------------------------------------------

def test_to_dict_from_dict_roundtrip():
    hint = StyleHint(language="en", technical_level=0.8, preferred_length="long",
                     tone="formal", top_domains=["api", "backend"])
    restored = StyleHint.from_dict(hint.to_dict())
    assert restored.language == "en"
    assert restored.technical_level == 0.8
    assert restored.preferred_length == "long"
    assert restored.tone == "formal"
    assert restored.top_domains == ["api", "backend"]


def test_from_dict_defaults():
    hint = StyleHint.from_dict({})
    assert hint.language == "es"
    assert hint.technical_level == 0.5
    assert hint.preferred_length == "medium"
    assert hint.tone == "neutral"
    assert hint.top_domains == []


def test_to_dict_keys():
    d = StyleHint().to_dict()
    assert set(d.keys()) == {"language", "technical_level", "preferred_length", "tone", "top_domains"}


# ---------------------------------------------------------------------------
# StyleHint.to_prompt_instruction
# ---------------------------------------------------------------------------

def test_to_prompt_instruction_casual():
    hint = StyleHint(tone="casual")
    instr = hint.to_prompt_instruction()
    assert "conversacional" in instr


def test_to_prompt_instruction_formal():
    hint = StyleHint(tone="formal")
    instr = hint.to_prompt_instruction()
    assert "formal" in instr


def test_to_prompt_instruction_neutral_no_tone_phrase():
    hint = StyleHint(tone="neutral")
    instr = hint.to_prompt_instruction()
    assert "conversacional" not in instr
    assert "formal y precisa" not in instr


def test_to_prompt_instruction_high_technical():
    hint = StyleHint(technical_level=0.9)
    instr = hint.to_prompt_instruction()
    assert "tecnico" in instr


def test_to_prompt_instruction_low_technical():
    hint = StyleHint(technical_level=0.2)
    instr = hint.to_prompt_instruction()
    assert "simples" in instr


def test_to_prompt_instruction_short_length():
    hint = StyleHint(preferred_length="short")
    instr = hint.to_prompt_instruction()
    assert "concisamente" in instr


def test_to_prompt_instruction_long_length():
    hint = StyleHint(preferred_length="long")
    instr = hint.to_prompt_instruction()
    assert "detalladas" in instr


def test_to_prompt_instruction_top_domains():
    hint = StyleHint(top_domains=["api", "docker", "gpu"])
    instr = hint.to_prompt_instruction()
    assert "api" in instr
    assert "docker" in instr


def test_to_prompt_instruction_empty():
    hint = StyleHint()
    assert hint.to_prompt_instruction() == ""


# ---------------------------------------------------------------------------
# StyleEngine.observe
# ---------------------------------------------------------------------------

def test_observe_updates_messages():
    eng = StyleEngine("u1")
    eng.observe("hola como estas")
    assert len(eng._messages) == 1
    assert eng._messages[0]["text"] == "hola como estas"


def test_observe_updates_word_freq():
    eng = StyleEngine("u1")
    eng.observe("el api endpoint")
    assert eng._word_freq["api"] == 1
    assert eng._word_freq["endpoint"] == 1


def test_observe_empty_string_ignored():
    eng = StyleEngine("u1")
    eng.observe("")
    eng.observe("   ")
    assert len(eng._messages) == 0


def test_observe_window_truncation():
    eng = StyleEngine("u1")
    for i in range(55):
        eng.observe(f"mensaje numero {i}")
    assert len(eng._messages) == StyleEngine.WINDOW


# ---------------------------------------------------------------------------
# StyleEngine._recompute
# ---------------------------------------------------------------------------

def test_recompute_technical_level_high():
    eng = StyleEngine("u1")
    technical_msg = "el api endpoint backend async thread proceso funcion clase objeto variable"
    for _ in range(5):
        eng.observe(technical_msg)
    assert eng._hint.technical_level > 0.5


def test_recompute_tone_casual():
    eng = StyleEngine("u1")
    casual_msg = "bueno pues o sea digamos tipo igual ok oye"
    for _ in range(5):
        eng.observe(casual_msg)
    assert eng._hint.tone == "casual"


def test_recompute_tone_formal():
    eng = StyleEngine("u1")
    formal_msg = "por favor podria seria posible le agradezco no obstante sin embargo asimismo"
    for _ in range(5):
        eng.observe(formal_msg)
    assert eng._hint.tone == "formal"


def test_recompute_preferred_length_short():
    eng = StyleEngine("u1")
    for _ in range(5):
        eng.observe("ok dale bien")
    assert eng._hint.preferred_length == "short"


def test_recompute_preferred_length_long():
    eng = StyleEngine("u1")
    long_msg = ("este es un mensaje muy largo con muchas palabras que supera el umbral de veintinco "
                "tokens por mensaje para activar la deteccion de longitud preferida larga en el motor")
    for _ in range(5):
        eng.observe(long_msg)
    assert eng._hint.preferred_length == "long"


def test_recompute_language_english():
    eng = StyleEngine("u1")
    eng_msg = "the api is are was were have has do does it"
    for _ in range(5):
        eng.observe(eng_msg)
    assert eng._hint.language == "en"


def test_recompute_no_crash_when_empty():
    eng = StyleEngine("u1")
    eng._recompute()
    assert eng._hint.language == "es"


# ---------------------------------------------------------------------------
# StyleEngine.hint property and stats()
# ---------------------------------------------------------------------------

def test_hint_property_returns_style_hint():
    eng = StyleEngine("u1")
    assert isinstance(eng.hint, StyleHint)


def test_stats_keys():
    eng = StyleEngine("u1")
    eng.observe("hola")
    s = eng.stats()
    assert "messages_observed" in s
    assert "unique_words" in s
    assert "hint" in s
    assert "top_words" in s


def test_stats_counts_correct():
    eng = StyleEngine("u1")
    eng.observe("hola mundo")
    eng.observe("hola")
    assert eng.stats()["messages_observed"] == 2
    assert eng.stats()["unique_words"] >= 2


# ---------------------------------------------------------------------------
# StyleEngine.save / load -- DB mocked
# ---------------------------------------------------------------------------

def _make_mock_conn(row_value=None):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = row_value
    return conn


def test_save_returns_true_on_success():
    eng = StyleEngine("u1")
    eng.observe("api endpoint backend")
    mock_conn = _make_mock_conn()
    with patch("storage.db_pool.db_connect_pooled", return_value=mock_conn):
        result = eng.save("fake.db")
    assert result is True
    mock_conn.execute.assert_called_once()


def test_save_returns_false_on_exception():
    eng = StyleEngine("u1")
    with patch("storage.db_pool.db_connect_pooled", side_effect=Exception("DB down")):
        result = eng.save("fake.db")
    assert result is False


def test_load_restores_engine_state():
    original = StyleEngine("u2")
    for _ in range(5):
        original.observe("api backend endpoint docker cluster")
    serialized = json.dumps({
        "user_id": "u2",
        "messages": original._messages,
        "word_freq": dict(original._word_freq),
        "hint": original._hint.to_dict(),
    })
    mock_conn = _make_mock_conn(row_value=(serialized,))
    with patch("storage.db_pool.db_connect_pooled", return_value=mock_conn):
        restored = StyleEngine.load("u2", "fake.db")
    assert restored.user_id == "u2"
    assert len(restored._messages) == len(original._messages)
    assert restored._hint.technical_level == original._hint.technical_level


def test_load_returns_fresh_engine_on_missing_row():
    mock_conn = _make_mock_conn(row_value=None)
    with patch("storage.db_pool.db_connect_pooled", return_value=mock_conn):
        eng = StyleEngine.load("unknown", "fake.db")
    assert eng.user_id == "unknown"
    assert len(eng._messages) == 0


def test_load_returns_fresh_engine_on_exception():
    with patch("storage.db_pool.db_connect_pooled", side_effect=Exception("fail")):
        eng = StyleEngine.load("u3", "fake.db")
    assert eng.user_id == "u3"
    assert isinstance(eng._hint, StyleHint)

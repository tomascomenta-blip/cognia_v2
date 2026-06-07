"""
tests/test_session_summarizer.py
=================================
Unit tests for SessionSummarizer (extractive, deterministic, no LLM).
"""

import sys
import os
import pathlib

# Ensure repo root is on sys.path
_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cognia.summarizer.session_summarizer import SessionSummarizer


# ── Fixtures ─────────────────────────────────────────────────────────────

SUMMARIZER = SessionSummarizer()

MULTI_MESSAGES = [
    {"role": "user", "content": "Hola como estas. Bien gracias. Que tal tu dia"},
    {"role": "assistant", "content": "Estoy bien, gracias por preguntar."},
    {"role": "user", "content": "Quiero aprender Python para analisis de datos"},
]


# ── Tests: extract_summary ────────────────────────────────────────────────

def test_extract_summary_empty_list_returns_string():
    result = SUMMARIZER.extract_summary([])
    assert isinstance(result, str)


def test_extract_summary_single_user_message_returns_nonempty():
    msgs = [{"role": "user", "content": "Hola como estas. Bien gracias. Que tal tu dia"}]
    result = SUMMARIZER.extract_summary(msgs)
    assert isinstance(result, str)
    assert len(result) > 0


def test_extract_summary_respects_max_len():
    long_text = "Esta es una oracion muy larga con muchas palabras distintas. " * 20
    msgs = [{"role": "user", "content": long_text}]
    result = SUMMARIZER.extract_summary(msgs)
    assert len(result) <= SessionSummarizer.MAX_SUMMARY_LEN


def test_extract_summary_ignores_assistant_messages():
    msgs = [
        {"role": "assistant", "content": "Yo soy el asistente hablando."},
        {"role": "assistant", "content": "Otra respuesta del asistente aqui."},
    ]
    # All assistant messages: user_text is empty, result must be empty string
    result = SUMMARIZER.extract_summary(msgs)
    assert result == ""


def test_extract_summary_deterministic():
    msgs = [
        {"role": "user", "content": "Python es un lenguaje de programacion. Me gusta mucho programar. Quiero aprender mas sobre inteligencia artificial."},
    ]
    r1 = SUMMARIZER.extract_summary(msgs)
    r2 = SUMMARIZER.extract_summary(msgs)
    assert r1 == r2, "extract_summary must be deterministic for the same input"


# ── Tests: on_message counter ─────────────────────────────────────────────

def test_on_message_assistant_does_not_increment():
    s = SessionSummarizer()
    s.on_message("sess-1", "assistant", "Hello")
    with s._lock:
        count = s._session_counts.get("sess-1", 0)
    assert count == 0


def test_on_message_user_increments_counter():
    s = SessionSummarizer()
    s.on_message("sess-2", "user", "First user message")
    s.on_message("sess-2", "user", "Second user message")
    with s._lock:
        count = s._session_counts.get("sess-2", 0)
    assert count == 2

"""
tests/test_format_intelligence.py
===================================
Phase 59 - Tests for FormatIntelligence (RFI).
22 tests, pure unit — no LLM calls, no network, no DB.
"""

import pytest
from cognia.quality.format_intelligence import FormatIntelligence, QuestionType


@pytest.fixture
def fi():
    return FormatIntelligence()


# ── HOW_TO detection ──────────────────────────────────────────────────────────

def test_how_do_i_install(fi):
    assert fi.detect_type("how do I install Python") == QuestionType.HOW_TO


def test_how_to_sort(fi):
    assert fi.detect_type("how to sort a list") == QuestionType.HOW_TO


def test_spanish_como_hago(fi):
    assert fi.detect_type("como hago para conectarme a una base de datos") == QuestionType.HOW_TO


# ── COMPARE detection ─────────────────────────────────────────────────────────

def test_compare_python_vs_java(fi):
    assert fi.detect_type("compare Python vs Java") == QuestionType.COMPARE


def test_difference_between(fi):
    assert fi.detect_type("difference between list and tuple") == QuestionType.COMPARE


# ── EXPLAIN detection ─────────────────────────────────────────────────────────

def test_what_is_recursion(fi):
    assert fi.detect_type("what is recursion") == QuestionType.EXPLAIN


def test_explain_oop(fi):
    assert fi.detect_type("explain the concept of OOP") == QuestionType.EXPLAIN


def test_spanish_que_es(fi):
    assert fi.detect_type("que es la recursion") == QuestionType.EXPLAIN


# ── LIST detection ────────────────────────────────────────────────────────────

def test_list_data_types(fi):
    assert fi.detect_type("list all Python data types") == QuestionType.LIST


def test_give_me_examples(fi):
    assert fi.detect_type("give me examples of design patterns") == QuestionType.LIST


# ── DEBUG detection ───────────────────────────────────────────────────────────

def test_why_code_not_working(fi):
    assert fi.detect_type("why is my code not working") == QuestionType.DEBUG


def test_error_typeerror(fi):
    assert fi.detect_type("I have an error: TypeError") == QuestionType.DEBUG


# ── YES_NO detection ──────────────────────────────────────────────────────────

def test_is_python_faster(fi):
    assert fi.detect_type("Is Python faster than Java?") == QuestionType.YES_NO


def test_can_i_use_async(fi):
    assert fi.detect_type("Can I use async here?") == QuestionType.YES_NO


# ── GENERAL fallback ──────────────────────────────────────────────────────────

def test_general_fallback(fi):
    assert fi.detect_type("tell me something interesting") == QuestionType.GENERAL


# ── get_format_hint ───────────────────────────────────────────────────────────

def test_general_hint_empty(fi):
    assert fi.get_format_hint("tell me something interesting") == ""


def test_how_to_hint_nonempty(fi):
    assert fi.get_format_hint("how do I set up a virtual environment") != ""


def test_how_to_hint_contains_numbered(fi):
    hint = fi.get_format_hint("how to install numpy")
    assert "numbered" in hint.lower()


def test_compare_hint_contains_bullet(fi):
    hint = fi.get_format_hint("compare React vs Vue")
    assert "bullet" in hint.lower()


def test_debug_hint_contains_root_cause(fi):
    hint = fi.get_format_hint("my app crashes with a segfault")
    assert "root cause" in hint.lower()


def test_list_hint_contains_bullet(fi):
    hint = fi.get_format_hint("list the SOLID principles")
    assert "bullet" in hint.lower()


def test_explain_hint_contains_definition(fi):
    hint = fi.get_format_hint("what is polymorphism")
    assert "definition" in hint.lower()


def test_yes_no_hint_contains_yes_or_no(fi):
    hint = fi.get_format_hint("Does Python support multiple inheritance?")
    assert "yes or no" in hint.lower()

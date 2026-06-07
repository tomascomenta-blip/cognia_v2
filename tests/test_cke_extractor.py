"""
tests/test_cke_extractor.py
============================
Tests for CKEExtractor (Phase 53 - Conversational Knowledge Extraction).
"""

import os
import tempfile
import pytest

from cognia.knowledge.graph import KnowledgeGraph
from cognia.knowledge.cke_extractor import CKEExtractor


@pytest.fixture
def tmp_kg(tmp_path):
    db_file = str(tmp_path / "test_cke.db")
    kg = KnowledgeGraph(db_path=db_file)
    # Ensure the table exists
    from storage.db_pool import get_pool
    with get_pool(db_file).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_graph ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  subject TEXT NOT NULL,"
            "  predicate TEXT NOT NULL,"
            "  object TEXT NOT NULL,"
            "  weight REAL DEFAULT 1.0,"
            "  source TEXT DEFAULT 'learned',"
            "  timestamp TEXT,"
            "  last_accessed REAL DEFAULT 0.0"
            ")"
        )
    return kg


@pytest.fixture
def cke(tmp_kg):
    return CKEExtractor(tmp_kg)


# ── IS-A patterns ────────────────────────────────────────────────────────

def test_is_a_english_basic(cke, tmp_kg):
    results = cke.extract_and_store("Python is a programming language")
    assert len(results) == 1
    s, p, o, w = results[0]
    assert s == "python"
    assert p == "is_a"
    assert "programming" in o
    assert w == 0.8


def test_is_a_english_with_an(cke, tmp_kg):
    results = cke.extract_and_store("Django is an open source framework")
    assert any(r[1] == "is_a" for r in results)
    subj = [r[0] for r in results if r[1] == "is_a"][0]
    assert "django" in subj


def test_is_a_spanish(cke, tmp_kg):
    results = cke.extract_and_store("Python es un lenguaje de programacion")
    assert any(r[1] == "is_a" for r in results)
    subj = [r[0] for r in results if r[1] == "is_a"][0]
    assert "python" in subj


def test_is_a_stores_in_kg(cke, tmp_kg):
    cke.extract_and_store("Rust is a systems programming language")
    facts = tmp_kg.get_facts("rust")
    assert any(f["predicate"] == "is_a" for f in facts)


# ── PROPERTY patterns ─────────────────────────────────────────────────────

def test_has_property_english(cke):
    results = cke.extract_and_store("Python has libraries for data science")
    assert any(r[1] == "has_property" for r in results)


def test_has_property_spanish(cke):
    results = cke.extract_and_store("Python tiene librerias para machine learning")
    assert any(r[1] == "has_property" for r in results)


def test_has_property_weight(cke):
    results = cke.extract_and_store("Java has garbage collection")
    has_results = [r for r in results if r[1] == "has_property"]
    assert len(has_results) > 0
    assert has_results[0][3] == 0.7


# ── USER FACT patterns ────────────────────────────────────────────────────

def test_user_is_a(cke, tmp_kg):
    results = cke.extract_and_store("I am a data scientist")
    assert any(r[0] == "user" for r in results)
    user_facts = [r for r in results if r[0] == "user"]
    assert user_facts[0][1] == "is_a"
    assert user_facts[0][3] == 0.85


def test_user_works_at(cke, tmp_kg):
    results = cke.extract_and_store("I work at Google")
    assert any(r[0] == "user" for r in results)
    facts = tmp_kg.get_facts("user")
    assert len(facts) > 0


def test_user_prefers(cke):
    results = cke.extract_and_store("I prefer Python over Java")
    assert any(r[0] == "user" for r in results)


def test_user_likes(cke):
    results = cke.extract_and_store("I like functional programming")
    assert any(r[0] == "user" for r in results)


# ── CORRECTION patterns ───────────────────────────────────────────────────

def test_correction_no(cke):
    results = cke.extract_and_store("No, Python is interpreted")
    corr = [r for r in results if r[3] == 0.9]
    assert len(corr) > 0


def test_correction_actually(cke):
    results = cke.extract_and_store("Actually Python is dynamically typed")
    assert any(r[3] == 0.9 for r in results)


def test_correction_high_weight(cke):
    results = cke.extract_and_store("Wrong, Java is not compiled to machine code")
    # correction pattern should produce higher-weight entry
    weights = [r[3] for r in results]
    assert any(w >= 0.9 for w in weights)


# ── STOP ENTITY filtering ──────────────────────────────────────────────────

def test_stop_entity_it_filtered(cke):
    # "it" as subject should be filtered out
    results = cke.extract_and_store("It is a good tool")
    # "it" is in stop list — should produce nothing or no "it" subject
    subjs = [r[0] for r in results]
    assert "it" not in subjs


def test_stop_entity_this_filtered(cke):
    results = cke.extract_and_store("This is a language")
    subjs = [r[0] for r in results]
    assert "this" not in subjs


def test_stop_entity_they_filtered(cke):
    results = cke.extract_and_store("They have a feature")
    subjs = [r[0] for r in results]
    assert "they" not in subjs


# ── EDGE CASES ─────────────────────────────────────────────────────────────

def test_empty_message(cke):
    results = cke.extract_and_store("")
    assert results == []


def test_whitespace_only(cke):
    results = cke.extract_and_store("   ")
    assert results == []


def test_short_input(cke):
    results = cke.extract_and_store("Hi")
    assert results == []


def test_max_five_facts(cke):
    long_msg = (
        "Python is a language. "
        "Python has libraries. "
        "Django is a framework. "
        "Flask is a microframework. "
        "Rust is a systems language. "
        "Go is a compiled language. "
        "Java is an object oriented language."
    )
    results = cke.extract_and_store(long_msg)
    assert len(results) <= 5


def test_special_chars_punctuation(cke):
    results = cke.extract_and_store("Python is a language!!!")
    assert len(results) >= 1
    # trailing punctuation should be stripped from object
    for _, _, obj, _ in results:
        assert not obj.endswith("!")


def test_assistant_response_param_ignored(cke):
    # assistant_response is accepted but not processed; method should not raise
    results = cke.extract_and_store(
        "I am an engineer",
        assistant_response="Great to hear that!",
    )
    assert any(r[0] == "user" for r in results)


def test_related_to_uses(cke):
    results = cke.extract_and_store("Python uses indentation for blocks")
    rel = [r for r in results if r[1] == "related_to"]
    assert len(rel) >= 1


def test_no_duplicate_subject_object_below_min_length(cke):
    # Single-char objects should not be stored
    results = cke.extract_and_store("X is a y")
    for _, _, obj, _ in results:
        assert len(obj) >= 2

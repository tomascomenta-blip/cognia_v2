"""
tests/test_user_facts.py
========================
6 tests for UserFactsMemory.
"""

import os
import tempfile
import pytest

# Use a temp DB so tests are isolated from any production data
@pytest.fixture
def facts_db(tmp_path):
    db = str(tmp_path / "test_user_facts.db")
    from cognia.social.user_facts import UserFactsMemory
    return UserFactsMemory(db_path=db)


def test_add_fact_returns_id(facts_db):
    """add_fact() must return a positive integer id."""
    fact_id = facts_db.add_fact("El usuario es programador", source="declared")
    assert isinstance(fact_id, int)
    assert fact_id > 0


def test_add_fact_duplicate_ignored(facts_db):
    """Inserting the same fact twice must not create a duplicate row."""
    id1 = facts_db.add_fact("El usuario prefiere Python", source="declared")
    id2 = facts_db.add_fact("El usuario prefiere Python", source="declared")
    # Both calls return the same id
    assert id1 == id2
    all_facts = facts_db.get_facts(limit=100, min_confidence=0.0)
    matching = [f for f in all_facts if f["fact"] == "El usuario prefiere Python"]
    assert len(matching) == 1


def test_infer_from_text_finds_pattern(facts_db):
    """infer_from_text() must detect a known pattern and return a non-empty list."""
    results = facts_db.infer_from_text("Soy Juan y trabajo con Python")
    assert len(results) >= 1
    combined = " ".join(results)
    assert "Juan" in combined or "Python" in combined


def test_infer_from_text_empty_for_plain(facts_db):
    """infer_from_text() returns [] when no pattern matches."""
    results = facts_db.infer_from_text("el cielo es azul hoy en dia")
    assert results == []


def test_get_context_nonempty_when_facts_exist(facts_db):
    """get_context() returns a non-empty string after adding a fact."""
    facts_db.add_fact("El usuario vive en Madrid", source="declared")
    ctx = facts_db.get_context(limit=5)
    assert ctx != ""
    assert "Madrid" in ctx


def test_forget_fact_returns_true_on_existing(facts_db):
    """forget_fact() returns True when the id existed and was deleted."""
    fact_id = facts_db.add_fact("El usuario usa Linux", source="declared")
    result = facts_db.forget_fact(fact_id)
    assert result is True
    # Confirm it is gone
    remaining = facts_db.get_facts(limit=100, min_confidence=0.0)
    assert all(f["id"] != fact_id for f in remaining)

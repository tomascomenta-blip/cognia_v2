"""
tests/test_smart_notes.py
=========================
7 tests for SmartNotesEngine.
"""
import os
import tempfile
import pytest

from cognia.notes.smart_notes import SmartNotesEngine


@pytest.fixture
def engine(tmp_path):
    db_path = str(tmp_path / "test_notes.db")
    return SmartNotesEngine(db_path=db_path)


def test_add_note_returns_int_id(engine):
    note_id = engine.add_note("Python is a programming language", note_type="fact")
    assert isinstance(note_id, int)
    assert note_id >= 1


def test_extract_detects_decision_type(engine):
    text = "We decided to use FastAPI for the backend because it is async."
    notes = engine.extract_from_text(text, session_id="s1")
    assert len(notes) == 1
    assert notes[0]["note_type"] == "decision"
    assert notes[0]["session_id"] == "s1"


def test_extract_detects_action_type(engine):
    text = "You should install the dependencies before running the server."
    notes = engine.extract_from_text(text, session_id="s2")
    assert len(notes) == 1
    assert notes[0]["note_type"] == "action"


def test_extract_returns_max_2_notes(engine):
    # Even with a text that triggers the extractor, max 2 notes are returned.
    text = "You should use FastAPI. We decided on PostgreSQL. Is a good choice."
    notes = engine.extract_from_text(text, session_id="s3")
    assert len(notes) <= 2


def test_get_notes_with_type_filter(engine):
    engine.add_note("Decision A", note_type="decision", session_id="sess")
    engine.add_note("Fact B", note_type="fact", session_id="sess")
    engine.add_note("Decision C", note_type="decision", session_id="sess")

    decisions = engine.get_notes(session_id="sess", note_type="decision")
    assert all(n["note_type"] == "decision" for n in decisions)
    assert len(decisions) == 2

    facts = engine.get_notes(session_id="sess", note_type="fact")
    assert len(facts) == 1


def test_search_notes_finds_substring(engine):
    engine.add_note("FastAPI is an async web framework", note_type="fact")
    engine.add_note("Django is a sync web framework", note_type="fact")
    engine.add_note("Unrelated content here", note_type="insight")

    results = engine.search_notes("async")
    assert len(results) == 1
    assert "async" in results[0]["content"].lower()


def test_get_stats_returns_correct_structure(engine):
    engine.add_note("Fact one", note_type="fact")
    engine.add_note("Fact two", note_type="fact")
    engine.add_note("A decision was made", note_type="decision")
    note_id = engine.add_note("Action item here", note_type="action")
    engine.pin_note(note_id)

    stats = engine.get_stats()
    assert "total" in stats
    assert "by_type" in stats
    assert "pinned" in stats
    assert stats["total"] == 4
    assert stats["by_type"].get("fact") == 2
    assert stats["by_type"].get("decision") == 1
    assert stats["pinned"] == 1

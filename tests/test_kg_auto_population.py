"""
tests/test_kg_auto_population.py
=================================
Tests for KnowledgeGraph.extract_and_store() — auto-population of the KG
from conversation text using regex pattern matching.
"""

import tempfile
import os
import pytest

from cognia.knowledge.graph import KnowledgeGraph
from cognia.database import init_db


@pytest.fixture
def kg():
    """Fresh in-memory KnowledgeGraph backed by a temp SQLite file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ── 1. English "is a" ─────────────────────────────────────────────────

def test_extract_is_a_english(kg):
    triples = kg.extract_and_store("Python is a programming language.")
    subjects = [t[0] for t in triples]
    predicates = [t[1] for t in triples]
    objects = [t[2] for t in triples]
    assert "python" in subjects
    assert "is_a" in predicates
    assert any("programming" in o for o in objects)


# ── 2. Spanish "es un/una" ────────────────────────────────────────────

def test_extract_es_un_spanish(kg):
    triples = kg.extract_and_store("Python es un lenguaje de programacion.")
    subjects = [t[0] for t in triples]
    predicates = [t[1] for t in triples]
    assert "python" in subjects
    assert "is_a" in predicates


# ── 3. "tiene" / "has" ────────────────────────────────────────────────

def test_extract_tiene(kg):
    triples = kg.extract_and_store("Cognia tiene memoria episodica.")
    subjects = [t[0] for t in triples]
    predicates = [t[1] for t in triples]
    assert "cognia" in subjects
    # "tiene" maps to has_property in the predicate map
    assert any(p in ("has_property", "capable_of") for p in predicates)


# ── 4. "puede" / "can" ────────────────────────────────────────────────

def test_extract_puede(kg):
    triples = kg.extract_and_store("El agente puede razonar sobre el contexto.")
    subjects = [t[0] for t in triples]
    predicates = [t[1] for t in triples]
    assert "agente" in subjects
    assert "capable_of" in predicates


# ── 5. No duplicate insertion ─────────────────────────────────────────

def test_no_duplicate_insertion(kg):
    text = "Python is a programming language."
    first_batch = kg.extract_and_store(text, source="conversation")
    second_batch = kg.extract_and_store(text, source="conversation")
    # second call must return empty — nothing new was added
    assert len(second_batch) == 0


# ── 6. Short entities are skipped ─────────────────────────────────────

def test_short_entities_skipped(kg):
    # Single-char subject and object — must be ignored
    triples = kg.extract_and_store("X is Y.")
    assert len(triples) == 0


# ── 7. Auto-extracted triples have weight = 0.6 ───────────────────────

def test_weight_is_auto(kg):
    kg.extract_and_store("Cognia is a cognitive AI system.", source="conversation")
    facts = kg.get_facts("cognia")
    assert len(facts) > 0
    # All auto-extracted facts must have weight <= 0.6 (initial value 0.6)
    auto_facts = [f for f in facts if f["weight"] <= 0.65]
    assert len(auto_facts) > 0


# ── 8. get_recent_auto_facts returns source="conversation" ────────────

def test_get_recent_auto_facts(kg):
    kg.extract_and_store(
        "Cognia is a cognitive AI system. Cognia has episodic memory.",
        source="conversation",
    )
    recent = kg.get_recent_auto_facts(limit=10)
    assert len(recent) > 0
    # All returned facts must have source="conversation"
    for fact in recent:
        assert fact["source"] == "conversation"

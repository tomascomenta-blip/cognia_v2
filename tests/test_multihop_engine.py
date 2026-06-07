"""
tests/test_multihop_engine.py
Tests for cognia/knowledge/multihop_engine.py
KnowledgeGraph is mocked throughout — no DB access needed.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build a minimal mock KnowledgeGraph
# ---------------------------------------------------------------------------

def _make_kg(neighbors_map: dict | None = None, ancestors_map: dict | None = None):
    """
    Build a mock KnowledgeGraph.

    neighbors_map: {concept: [{"concept": ..., "relation": ...}, ...]}
    ancestors_map: {concept: [parent1, parent2, ...]}
    """
    kg = MagicMock()
    nm = neighbors_map or {}
    am = ancestors_map or {}

    def _neighbors(concept, predicate=None):
        return nm.get(concept, [])

    def _ancestors(concept, max_depth=4):
        return am.get(concept, [])

    kg.get_neighbors.side_effect = _neighbors
    kg.get_ancestors.side_effect = _ancestors
    return kg


def _make_engine(kg_mock):
    """Instantiate MultiHopEngine with the given KG mock bypassing __init__."""
    from cognia.knowledge.multihop_engine import MultiHopEngine
    engine = object.__new__(MultiHopEngine)
    engine._kg = kg_mock
    return engine


# ---------------------------------------------------------------------------
# find_path tests
# ---------------------------------------------------------------------------

class TestFindPath:

    def test_same_node_returns_empty(self):
        from cognia.knowledge.multihop_engine import MultiHopEngine
        engine = _make_engine(_make_kg())
        assert engine.find_path("A", "A") == []

    def test_no_path_returns_empty(self):
        # Mock KG with no neighbors at all
        engine = _make_engine(_make_kg(neighbors_map={}))
        result = engine.find_path("A", "Z")
        assert result == []

    def test_direct_one_hop(self):
        nm = {
            "python": [{"concept": "lenguaje", "relation": "is_a"}],
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        path = engine.find_path("python", "lenguaje")
        assert len(path) == 1
        assert path[0] == ("python", "is_a", "lenguaje")

    def test_two_hops(self):
        nm = {
            "python": [{"concept": "lenguaje", "relation": "is_a"}],
            "lenguaje": [{"concept": "herramienta", "relation": "is_a"}],
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        path = engine.find_path("python", "herramienta")
        assert len(path) == 2

    def test_max_hops_zero_returns_empty(self):
        nm = {
            "a": [{"concept": "b", "relation": "related_to"}],
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        result = engine.find_path("a", "b", max_hops=0)
        assert result == []

    def test_max_hops_capped_at_3(self):
        # A path 4 hops long should not be found with max_hops=3
        nm = {
            "a": [{"concept": "b", "relation": "r"}],
            "b": [{"concept": "c", "relation": "r"}],
            "c": [{"concept": "d", "relation": "r"}],
            "d": [{"concept": "e", "relation": "r"}],
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        # Requesting 4 hops but MAX_HOPS=3 caps it
        result = engine.find_path("a", "e", max_hops=4)
        assert result == []


# ---------------------------------------------------------------------------
# infer_properties tests
# ---------------------------------------------------------------------------

class TestInferProperties:

    def test_returns_expected_keys(self):
        engine = _make_engine(_make_kg())
        result = engine.infer_properties("concept")
        assert "concept" in result
        assert "direct_facts" in result
        assert "inherited_facts" in result
        assert "parent_chain" in result
        assert "total_facts" in result

    def test_direct_facts_populated(self):
        nm = {
            "python": [
                {"concept": "lenguaje", "relation": "is_a"},
                {"concept": "interpretado", "relation": "has_property"},
            ]
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        result = engine.infer_properties("python")
        # is_a should be excluded from direct_facts
        assert all(f["predicate"] != "is_a" for f in result["direct_facts"])
        assert len(result["direct_facts"]) == 1

    def test_inherited_facts_populated(self):
        nm = {
            "python": [{"concept": "lenguaje", "relation": "is_a"}],
            "lenguaje": [{"concept": "texto", "relation": "has_property"}],
        }
        am = {"python": ["lenguaje"]}
        engine = _make_engine(_make_kg(neighbors_map=nm, ancestors_map=am))
        result = engine.infer_properties("python", depth=2)
        assert len(result["inherited_facts"]) >= 1
        assert result["parent_chain"] == ["lenguaje"]

    def test_total_facts_matches(self):
        engine = _make_engine(_make_kg())
        result = engine.infer_properties("empty_concept")
        assert result["total_facts"] == len(result["direct_facts"]) + len(result["inherited_facts"])


# ---------------------------------------------------------------------------
# find_common_ancestors tests
# ---------------------------------------------------------------------------

class TestFindCommonAncestors:

    def test_returns_list(self):
        engine = _make_engine(_make_kg())
        result = engine.find_common_ancestors("A", "B")
        assert isinstance(result, list)

    def test_empty_when_no_ancestors(self):
        engine = _make_engine(_make_kg())
        result = engine.find_common_ancestors("python", "javascript")
        assert result == []

    def test_finds_shared_ancestor(self):
        am = {
            "python": ["lenguaje", "herramienta"],
            "javascript": ["lenguaje", "web"],
        }
        engine = _make_engine(_make_kg(ancestors_map=am))
        result = engine.find_common_ancestors("python", "javascript")
        assert "lenguaje" in result

    def test_no_common_when_disjoint(self):
        am = {
            "perro": ["animal"],
            "carro": ["vehiculo"],
        }
        engine = _make_engine(_make_kg(ancestors_map=am))
        result = engine.find_common_ancestors("perro", "carro")
        assert result == []


# ---------------------------------------------------------------------------
# explain_relationship tests
# ---------------------------------------------------------------------------

class TestExplainRelationship:

    def test_returns_expected_keys(self):
        engine = _make_engine(_make_kg())
        result = engine.explain_relationship("A", "B")
        assert "direct_path" in result
        assert "common_ancestors" in result
        assert "relationship_type" in result
        assert "explanation" in result

    def test_unrelated_type_when_no_connection(self):
        engine = _make_engine(_make_kg())
        result = engine.explain_relationship("X", "Y")
        assert result["relationship_type"] == "unrelated"

    def test_direct_type_when_path_exists(self):
        nm = {
            "python": [{"concept": "lenguaje", "relation": "is_a"}],
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        result = engine.explain_relationship("python", "lenguaje")
        assert result["relationship_type"] == "direct"
        assert len(result["direct_path"]) == 1

    def test_sibling_type_with_common_ancestor(self):
        am = {
            "python": ["lenguaje"],
            "java": ["lenguaje"],
        }
        engine = _make_engine(_make_kg(ancestors_map=am))
        result = engine.explain_relationship("python", "java")
        assert result["relationship_type"] == "sibling"
        assert "lenguaje" in result["common_ancestors"]


# ---------------------------------------------------------------------------
# answer_question tests
# ---------------------------------------------------------------------------

class TestAnswerQuestion:

    def test_returns_expected_keys(self):
        engine = _make_engine(_make_kg())
        result = engine.answer_question("que es python")
        assert "question" in result
        assert "entities_found" in result
        assert "facts" in result
        assert "confidence" in result
        assert "answer_text" in result

    def test_confidence_is_float_between_0_and_1(self):
        engine = _make_engine(_make_kg())
        result = engine.answer_question("que es python")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_no_facts_gives_low_confidence(self):
        engine = _make_engine(_make_kg())
        result = engine.answer_question("que es python")
        assert result["confidence"] == 0.0

    def test_facts_increase_confidence(self):
        nm = {
            "python": [
                {"concept": "lenguaje", "relation": "is_a"},
                {"concept": "interpretado", "relation": "has_property"},
                {"concept": "dinamico", "relation": "has_property"},
            ]
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        result = engine.answer_question("que es python")
        assert result["confidence"] > 0.0

    def test_confidence_capped_at_1(self):
        # 15 facts -> 15 * 0.1 = 1.5, should be capped at 1.0
        nm = {
            "python": [{"concept": f"prop{i}", "relation": "has_property"} for i in range(15)]
        }
        engine = _make_engine(_make_kg(neighbors_map=nm))
        result = engine.answer_question("que es python")
        assert result["confidence"] <= 1.0

    def test_answer_text_not_empty(self):
        engine = _make_engine(_make_kg())
        result = engine.answer_question("que es python")
        assert isinstance(result["answer_text"], str)
        assert len(result["answer_text"]) > 0

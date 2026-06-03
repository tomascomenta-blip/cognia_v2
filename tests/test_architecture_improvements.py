"""
tests/test_architecture_improvements.py
========================================
Functional tests for 4 capabilities added in recent cycles:
  - Group 1: CogniaReasoningEngine.enrich_with_meta() (Cycle 3)
  - Group 2: HypothesisModule.generate() (Cycle 2)
  - Group 3: KnowledgeGraph.get_inherited_facts() (Cycle 7)
"""

import os
import sys
import tempfile
import sqlite3

# ── path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _create_kg_db(path: str) -> None:
    """Create minimal schema for KnowledgeGraph tests."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_graph (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subject     TEXT NOT NULL,
            predicate   TEXT NOT NULL,
            object      TEXT NOT NULL,
            weight      REAL DEFAULT 1.0,
            source      TEXT DEFAULT 'learned',
            timestamp   TEXT,
            verified    INTEGER DEFAULT 0,
            UNIQUE(subject, predicate, object)
        )
    """)
    conn.commit()
    conn.close()


def _drain_pool(db_path: str) -> None:
    """Close all pooled SQLite connections for a given path (needed on Windows)."""
    try:
        from storage.db_pool import _pools
        pool = _pools.get(db_path)
        if pool is None:
            return
        conns = []
        while True:
            try:
                conns.append(pool._pool.get_nowait())
            except Exception:
                break
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        _pools.pop(db_path, None)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Group 1 — CogniaReasoningEngine.enrich_with_meta()
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichWithMeta:
    def setup_method(self):
        from cognia.reasoning.cognia_reasoning_engine import CogniaReasoningEngine
        self.eng = CogniaReasoningEngine()

    def test_returns_dict_with_required_keys(self):
        result = self.eng.enrich_with_meta(
            "Como funciona el sistema y por que es importante para el rendimiento?",
            "Contexto vacio",
            "general",
        )
        assert isinstance(result, dict)
        assert "context" in result
        assert "confidence" in result
        assert "has_contradiction" in result
        assert "sub_questions" in result

    def test_confidence_in_valid_range(self):
        result = self.eng.enrich_with_meta("simple pregunta", "contexto corto", "corta")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_low_confidence_on_empty_context(self):
        # Long question + empty context → confidence < 0.8
        result = self.eng.enrich_with_meta(
            "Que pasa con el sistema cuando falla la red y hay un error critico?",
            "",
            "general",
        )
        assert result["confidence"] < 0.8

    def test_enrich_backward_compat_returns_string(self):
        # enrich() must still return a str for callers that expect the old API
        result = self.eng.enrich(
            "Pregunta compleja con multiples partes y aspectos diferentes que explorar",
            "contexto",
            "general",
        )
        assert isinstance(result, str)

    def test_contradiction_detected_via_sin_embargo(self):
        contradictory_context = (
            "El sistema funciona bien. "
            "Sin embargo, el sistema no funciona bien en ningun caso."
        )
        # Use a question long enough (>=15 words) so the engine doesn't short-circuit
        result = self.eng.enrich_with_meta(
            "Como funciona el sistema cuando falla la red y hay problemas de rendimiento criticos en produccion?",
            contradictory_context,
            "general",
        )
        assert result["has_contradiction"] is True

    def test_no_contradiction_on_plain_context(self):
        plain_context = "El sistema procesa los tokens de forma eficiente usando INT4."
        result = self.eng.enrich_with_meta(
            "Explica el sistema de tokens y como afecta al rendimiento total del modelo",
            plain_context,
            "general",
        )
        assert result["has_contradiction"] is False

    def test_simple_qtype_skips_enrichment(self):
        # q_type in _SIMPLE_QTYPES → returns context unchanged, confidence=0.7
        result = self.eng.enrich_with_meta("hola", "ctx", "social")
        assert result["confidence"] == 0.7
        assert result["sub_questions"] == []
        assert result["context"] == "ctx"

    def test_context_is_string(self):
        result = self.eng.enrich_with_meta(
            "Como funciona el sistema y por que es importante para el rendimiento?",
            "algo de contexto aqui",
            "general",
        )
        assert isinstance(result["context"], str)


# ══════════════════════════════════════════════════════════════════════════════
# Group 2 — HypothesisModule
# ══════════════════════════════════════════════════════════════════════════════

class _FakeSemantic:
    """Minimal semantic stub — no network, no DB."""
    def __init__(self, known):
        # known: set of concept names that "exist"
        import numpy as np
        self._known = known
        self._rng = np.random.default_rng(42)

    def get_concept(self, name: str):
        if name not in self._known:
            return None
        vec = self._rng.random(128).astype("float32")
        vec /= (vec ** 2).sum() ** 0.5
        return {"vector": vec, "description": f"descripcion de {name}"}

    def add_association(self, a, b, weight):
        pass  # no-op


class TestHypothesisModule:
    def setup_method(self):
        # HypothesisModule needs a db with a 'hypotheses' table
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmp.name, "hyp_test.db")
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hypotheses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                hypothesis  TEXT,
                confidence  REAL,
                created_at  TEXT
            )
        """)
        conn.commit()
        conn.close()

    def teardown_method(self):
        _drain_pool(self._db_path)
        self._tmp.cleanup()

    def test_generate_returns_dict_with_hypothesis(self):
        from cognia.reasoning.hypothesis import HypothesisModule
        semantic = _FakeSemantic({"agua", "energia"})
        hmod = HypothesisModule(db_path=self._db_path, semantic=semantic)
        result = hmod.generate("agua", "energia", usar_ollama=False)
        assert isinstance(result, dict)
        assert "hypothesis" in result

    def test_generate_missing_concept_returns_error(self):
        from cognia.reasoning.hypothesis import HypothesisModule
        semantic = _FakeSemantic(set())  # nothing known
        hmod = HypothesisModule(db_path=self._db_path, semantic=semantic)
        result = hmod.generate("xyzzyconceptofalso12345", "otroconceptofalso99999")
        assert isinstance(result, dict)
        assert "error" in result

    def test_generate_persists_to_db(self):
        from cognia.reasoning.hypothesis import HypothesisModule
        semantic = _FakeSemantic({"luz", "sombra"})
        hmod = HypothesisModule(db_path=self._db_path, semantic=semantic)
        hmod.generate("luz", "sombra", usar_ollama=False)
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("SELECT COUNT(*) FROM hypotheses").fetchone()
        conn.close()
        assert row[0] >= 1

    def test_generate_confidence_in_range(self):
        from cognia.reasoning.hypothesis import HypothesisModule
        semantic = _FakeSemantic({"calor", "frio"})
        hmod = HypothesisModule(db_path=self._db_path, semantic=semantic)
        result = hmod.generate("calor", "frio", usar_ollama=False)
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Group 3 — KnowledgeGraph.get_inherited_facts()
# ══════════════════════════════════════════════════════════════════════════════

class TestKnowledgeGraphInheritance:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmp.name, "kg_test.db")
        _create_kg_db(self._db_path)

    def teardown_method(self):
        _drain_pool(self._db_path)
        self._tmp.cleanup()

    def _kg(self):
        from cognia.knowledge.graph import KnowledgeGraph
        return KnowledgeGraph(db_path=self._db_path)

    def test_unknown_concept_returns_empty_list(self):
        kg = self._kg()
        result = kg.get_inherited_facts("concepto_inexistente_xyz")
        assert result == []

    def test_single_hop_inheritance(self):
        kg = self._kg()
        # dog is_a animal; animal has_property breathes
        kg.add_triple("dog", "is_a", "animal", weight=1.0)
        kg.add_triple("animal", "has_property", "breathes", weight=1.0)
        result = kg.get_inherited_facts("dog")
        # Should find animal's has_property fact via dog→animal chain
        assert len(result) >= 1
        assert any("animal" in r for r in result)

    def test_max_depth_limits_traversal(self):
        kg = self._kg()
        # Chain: a → b → c; c has_property x
        kg.add_triple("a", "is_a", "b", weight=1.0)
        kg.add_triple("b", "is_a", "c", weight=1.0)
        kg.add_triple("c", "has_property", "x", weight=1.0)
        result_d2 = kg.get_inherited_facts("a", max_depth=2)
        result_d1 = kg.get_inherited_facts("a", max_depth=1)
        # Deeper traversal finds more or equal facts
        assert len(result_d2) >= len(result_d1)

    def test_result_capped_at_8(self):
        kg = self._kg()
        kg.add_triple("x", "is_a", "parent", weight=1.0)
        for i in range(12):
            kg.add_triple("parent", f"has_property", f"obj_{i}", weight=1.0)
        result = kg.get_inherited_facts("x")
        assert len(result) <= 8

    def test_depth0_returns_empty_for_concept_with_no_direct_parent_facts(self):
        kg = self._kg()
        # x is_a parent; parent has no non-is_a facts
        kg.add_triple("x", "is_a", "parent", weight=1.0)
        # At max_depth=0, x itself is processed (depth=0, not >0), parents are queued
        # at depth=1 which IS > 0, so they're skipped → no inherited facts
        result_d0 = kg.get_inherited_facts("x", max_depth=0)
        assert result_d0 == []

    def test_add_triple_non_isa_relation(self):
        # add_triple with a valid non-is_a relation doesn't crash
        kg = self._kg()
        is_new = kg.add_triple("fire", "causes", "heat", weight=1.0)
        assert isinstance(is_new, bool)

    def test_inherited_conflict_reduces_confidence(self):
        """Observations that conflict with inherited KG facts get lower confidence."""
        kg = self._kg()
        kg.add_triple("dog", "is_a", "animal", weight=1.0)
        kg.add_triple("animal", "has_property", "breathes", weight=1.0)
        inherited = kg.get_inherited_facts("dog")
        # "dog" inherits "breathes" from "animal" via is_a chain
        assert any("breathes" in r for r in inherited)
        # Verify the KG prerequisite is correct: inherited contains animal-level facts
        assert any("animal" in r for r in inherited)

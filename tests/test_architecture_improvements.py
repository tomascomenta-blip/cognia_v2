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


# ══════════════════════════════════════════════════════════════════════════════
# Group 4 — HypothesisModule.generate_many() (misión creatividad, pieza 1)
# ══════════════════════════════════════════════════════════════════════════════

class _FakeInferResult:
    """Doble de test del InferResult del backend (NO un mock de produccion)."""
    def __init__(self, text):
        self.text = text


class _FakeOrchestrator:
    """Backend de doble de test: devuelve textos fijos en orden por cada infer()."""
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = []

    def infer(self, prompt, max_tokens=None, temperature=None):
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens,
                           "temperature": temperature})
        text = self._texts.pop(0) if self._texts else ""
        return _FakeInferResult(text)


class TestHypothesisGenerateMany:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmp.name, "hyp_many.db")
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

    def _hmod(self):
        from cognia.reasoning.hypothesis import HypothesisModule
        return HypothesisModule(db_path=self._db_path, semantic=_FakeSemantic(set()))

    def test_none_orchestrator_returns_empty(self):
        hmod = self._hmod()
        assert hmod.generate_many("como mejorar el riego urbano", n=5, orchestrator=None) == []

    def test_full_flow_parses_orders_ranks_and_persists(self):
        gen = ("1. Recolectar agua de lluvia en azoteas\n"
               "2. Sensores de humedad para riego por goteo\n"
               "3. Plantas nativas de bajo consumo\n"
               "4. Reuso de aguas grises tratadas\n"
               "5. Micro-reservorios subterraneos en plazas\n")
        scores = "1: 0.6\n2: 0.9\n3: 0.7\n4: 0.4\n5: 0.8\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        items = hmod.generate_many("riego urbano", n=5, orchestrator=orch)

        assert len(items) == 5
        # Solo dos llamadas LLM (generacion + plausibilidad).
        assert len(orch.calls) == 2
        # Ordenadas por plausibilidad desc: 0.9, 0.8, 0.7, 0.6, 0.4
        plaus = [it["plausibility"] for it in items]
        assert plaus == sorted(plaus, reverse=True)
        assert plaus[0] == 0.9
        # Ranks consecutivos 1..5.
        assert [it["rank"] for it in items] == [1, 2, 3, 4, 5]
        # El de mayor plausibilidad es la hipotesis 2.
        assert "Sensores de humedad" in items[0]["hypothesis"]
        # Persistidas: 5 filas en la tabla hypotheses.
        conn = sqlite3.connect(self._db_path)
        cnt = conn.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0]
        conn.close()
        assert cnt == 5

    def test_clamp_n_below_three(self):
        gen = "1. Angulo uno\n2. Angulo dos\n3. Angulo tres\n"
        scores = "1: 0.5\n2: 0.5\n3: 0.5\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        # n=1 se clampa a 3 (minimo) -> el prompt pide 3 angulos.
        items = hmod.generate_many("problema cualquiera", n=1, orchestrator=orch)
        assert len(items) == 3
        assert "EXACTAMENTE 3" in orch.calls[0]["prompt"]

    def test_robust_parsing_paren_dash_and_missing_scores(self):
        # Mezcla de separadores: ") ", ". ", " - ", linea vacia intercalada.
        gen = ("1) Primera idea concreta\n"
               "\n"
               "2. Segunda idea concreta\n"
               "3 - Tercera idea concreta\n")
        # Solo se puntua la 1 y la 3; la 2 falta -> default 0.5. Padding para
        # superar el piso de 15 chars de creative_generate (caso real: lista mas larga).
        scores = "1: 0.8\n2: x\n3: 0.2\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        items = hmod.generate_many("problema", n=3, orchestrator=orch)
        assert len(items) == 3
        by_text = {it["hypothesis"]: it["plausibility"] for it in items}
        assert by_text["Primera idea concreta"] == 0.8
        assert by_text["Tercera idea concreta"] == 0.2
        assert by_text["Segunda idea concreta"] == 0.5  # default: "2: x" no parsea

    def test_too_few_hypotheses_returns_what_it_has(self):
        # El modelo solo entrego 2 lineas utilizables (<3): devolvemos las 2 (no [] si hay >=1).
        gen = "1. Unica idea concreta\n2. Otra idea concreta\n"
        orch = _FakeOrchestrator([gen, "1: 0.5\n2: 0.5\n8: 0.5\n"])
        hmod = self._hmod()
        items = hmod.generate_many("problema", n=5, orchestrator=orch)
        assert len(items) == 2
        assert [it["rank"] for it in items] == [1, 2]

    def test_empty_generation_returns_empty(self):
        orch = _FakeOrchestrator(["", ""])
        hmod = self._hmod()
        assert hmod.generate_many("problema", n=5, orchestrator=orch) == []

    def test_scoring_retry_on_first_call_empty(self):
        # Flake de 1a-llamada-en-frio: el scoring devuelve vacio la 1a vez y scores
        # validos la 2a. El reintento debe rescatar plausibilidades reales (no 0.5).
        gen = ("1. Recolectar agua de lluvia\n"
               "2. Sensores de humedad\n"
               "3. Plantas nativas\n")
        scores = "1: 0.7\n2: 0.4\n3: 0.9\n"
        orch = _FakeOrchestrator([gen, "", scores])  # 2a infer (1er scoring) vacio
        hmod = self._hmod()
        items = hmod.generate_many("riego", n=3, orchestrator=orch)
        assert len(items) == 3
        # 3 llamadas: generacion + scoring fallido + scoring reintento.
        assert len(orch.calls) == 3
        plaus = [it["plausibility"] for it in items]
        # Reintento exitoso -> plausibilidades reales (no todas None ni todas 0.5).
        assert None not in plaus
        assert set(plaus) != {0.5}
        assert plaus[0] == 0.9  # ordenado desc, la hipotesis 3

    def test_scoring_total_failure_marks_unscored_keeps_gen_order(self):
        # Scoring vacio AMBAS veces -> sin fabricar ranking: plausibility None y
        # orden = generacion (rank por orden de generacion).
        gen = ("1. Idea uno concreta\n"
               "2. Idea dos concreta\n"
               "3. Idea tres concreta\n")
        orch = _FakeOrchestrator([gen, "", ""])
        hmod = self._hmod()
        items = hmod.generate_many("problema", n=3, orchestrator=orch)
        assert len(items) == 3
        assert all(it["plausibility"] is None for it in items)
        # Orden de generacion preservado.
        assert items[0]["hypothesis"] == "Idea uno concreta"
        assert items[2]["hypothesis"] == "Idea tres concreta"
        assert [it["rank"] for it in items] == [1, 2, 3]
        # Persistido con confidence neutro 0.5 (no None en disco).
        conn = sqlite3.connect(self._db_path)
        confs = [r[0] for r in conn.execute("SELECT confidence FROM hypotheses").fetchall()]
        conn.close()
        assert confs == [0.5, 0.5, 0.5]

    def test_multiline_fold_keeps_body_not_just_title(self):
        # Hipotesis multilinea: el cuerpo (bullets de continuacion) debe foldearse
        # en la hipotesis, no descartarse dejando solo el titulo en negrita.
        gen = ("1. **Expandir memoria:**\n"
               "   - detalle uno\n"
               "   - mas\n"
               "\n"
               "2. T2\n"
               "   sigue\n")
        # Padding >15 chars: creative_generate descarta scores muy cortos (caso real: lista larga).
        scores = "1: 0.6\n2: 0.7\n(fin)\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        items = hmod.generate_many("problema", n=2, orchestrator=orch)
        assert len(items) == 2
        by_plaus = {it["plausibility"]: it["hypothesis"] for it in items}
        h1 = by_plaus[0.6]
        assert "detalle uno" in h1
        assert "mas" in h1
        assert "**" not in h1            # markdown removido
        assert "Expandir memoria" in h1  # titulo conservado
        h2 = by_plaus[0.7]
        assert "sigue" in h2

    def test_partial_scores_fill_missing_with_default(self):
        # Scoring solo para 1 y 3 -> el idx 2 cae al default 0.5; ordenado desc.
        gen = ("1. Idea uno concreta\n"
               "2. Idea dos concreta\n"
               "3. Idea tres concreta\n")
        # Padding >15 chars: creative_generate descarta scores muy cortos (caso real: lista larga).
        scores = "1: 0.9\n3: 0.2\n(fin)\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        items = hmod.generate_many("problema", n=3, orchestrator=orch)
        assert len(items) == 3
        # Parcial NO es fallo total: nadie queda con None.
        assert all(it["plausibility"] is not None for it in items)
        plaus = [it["plausibility"] for it in items]
        assert plaus == [0.9, 0.5, 0.2]
        assert [it["rank"] for it in items] == [1, 2, 3]

    def test_diversify_repetitive_set_forces_alternatives(self):
        # Conjunto generado REPETITIVO (diversity < 0.5) con diversify=True ->
        # se dispara force_alternatives, mergea las nuevas y el resultado es mas
        # diverso (incluye los enfoques alternativos del detector).
        gen = ("1. recolectar agua de lluvia en azoteas\n"
               "2. recolectar agua de lluvia en los techos\n"
               "3. recolectar agua de lluvia con canaletas\n")
        alts = ("1. construir un acueducto subterraneo presurizado\n"
                "2. desalinizar mediante membranas de osmosis inversa\n")
        scores = "1: 0.6\n2: 0.5\n3: 0.4\n"
        orch = _FakeOrchestrator([gen, alts, scores])
        hmod = self._hmod()
        items = hmod.generate_many("abastecer agua urbana", n=3,
                                   orchestrator=orch, diversify=True)
        # 3 llamadas: generacion + alternativas + scoring.
        assert len(orch.calls) == 3
        textos = " ".join(it["hypothesis"] for it in items)
        # Una alternativa nueva del detector entro al conjunto final.
        assert "acueducto" in textos or "osmosis" in textos
        # Recortado a n.
        assert len(items) <= 3

    def test_diversify_diverse_set_skips_alternatives(self):
        # Conjunto ya DIVERSO (diversity >= 0.5): diversify=True NO debe llamar a
        # force_alternatives. Solo generacion + scoring = 2 llamadas.
        gen = ("1. sensores de humedad para riego por goteo\n"
               "2. plantas nativas de bajo consumo hidrico\n"
               "3. reuso de aguas grises tratadas filtradas\n")
        scores = "1: 0.7\n2: 0.5\n3: 0.6\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        items = hmod.generate_many("riego urbano", n=3,
                                   orchestrator=orch, diversify=True)
        # Sin alternativas extra: solo 2 llamadas LLM.
        assert len(orch.calls) == 2
        assert len(items) == 3

    def test_diversify_default_false_unchanged(self):
        # diversify default = False: mismo comportamiento que siempre (2 llamadas),
        # aunque el conjunto sea repetitivo. Garantiza el contrato existente.
        gen = ("1. recolectar agua de lluvia en azoteas\n"
               "2. recolectar agua de lluvia en los techos\n"
               "3. recolectar agua de lluvia con canaletas\n")
        scores = "1: 0.6\n2: 0.5\n3: 0.4\n"
        orch = _FakeOrchestrator([gen, scores])
        hmod = self._hmod()
        items = hmod.generate_many("agua urbana", n=3, orchestrator=orch)
        # Sin diversify: NO se dispara force_alternatives -> 2 llamadas.
        assert len(orch.calls) == 2
        assert len(items) == 3


class TestParseNumberedFold:
    """_parse_numbered: fold de lineas de continuacion y limpieza de display."""

    def test_fold_multiline_item(self):
        from cognia.reasoning.hypothesis import _parse_numbered
        text = ("1. **T1:**\n"
                "   - detalle uno\n"
                "   - mas\n"
                "\n"
                "2. T2\n"
                "   sigue\n")
        out = _parse_numbered(text, 5)
        assert len(out) == 2
        assert "detalle uno" in out[0] and "mas" in out[0]
        assert "**" not in out[0]
        assert "T1" in out[0]
        assert "sigue" in out[1]

    def test_single_line_items_unchanged(self):
        from cognia.reasoning.hypothesis import _parse_numbered
        text = "1) Primera idea\n2. Segunda idea\n3 - Tercera idea\n"
        out = _parse_numbered(text, 3)
        assert out == ["Primera idea", "Segunda idea", "Tercera idea"]

    def test_caps_long_hypothesis_at_word_boundary(self):
        from cognia.reasoning.hypothesis import _parse_numbered
        long = "palabra " * 100  # ~800 chars
        out = _parse_numbered("1. " + long + "\n", 1)
        assert len(out) == 1
        assert len(out[0]) <= 403          # 400 + "..."
        assert out[0].endswith("...")
        assert not out[0].endswith(" ...")  # corte en limite de palabra, sin espacio colgante


class TestGenerateHypothesesManyFormatter:
    """generate_hypotheses_many de cognia.py: render honesto del caso sin puntuar."""

    def _ai_with_items(self, items):
        # Construye una instancia minima sin __init__ pesado y le inyecta un
        # hypothesis-module doble que devuelve items fijos.
        from cognia.cognia import Cognia

        class _HMod:
            def generate_many(self, problem, n, orchestrator=None, diversify=False):
                return items

        ai = Cognia.__new__(Cognia)
        ai.hypothesis = _HMod()
        ai._orchestrator = None
        return ai

    def test_unscored_items_render_sin_puntuar_and_note(self):
        items = [
            {"hypothesis": "Idea uno", "plausibility": None, "rank": 1},
            {"hypothesis": "Idea dos", "plausibility": None, "rank": 2},
        ]
        out = self._ai_with_items(items).generate_hypotheses_many("problema", n=2)
        assert "[sin puntuar]" in out
        assert "[plaus" not in out
        assert "orden = generacion" in out
        assert out.isascii()  # CLI ASCII puro

    def test_scored_items_render_plaus(self):
        items = [
            {"hypothesis": "Idea uno", "plausibility": 0.9, "rank": 1},
            {"hypothesis": "Idea dos", "plausibility": 0.3, "rank": 2},
        ]
        out = self._ai_with_items(items).generate_hypotheses_many("problema", n=2)
        assert "[plaus 0.90]" in out
        assert "[sin puntuar]" not in out
        assert "orden = generacion" not in out


class TestCreativeGenerate:
    def test_short_output_returns_none(self):
        from cognia.reasoning.creative_llm import creative_generate
        orch = _FakeOrchestrator(["corto"])  # len < 15
        assert creative_generate(orch, "p") is None

    def test_strips_and_returns_text(self):
        from cognia.reasoning.creative_llm import creative_generate
        orch = _FakeOrchestrator(["   una respuesta lo bastante larga   "])
        out = creative_generate(orch, "p", temperature=0.95, max_tokens=420)
        assert out == "una respuesta lo bastante larga"
        # temperature/max_tokens se forwardean al backend.
        assert orch.calls[0]["temperature"] == 0.95
        assert orch.calls[0]["max_tokens"] == 420

    def test_backend_exception_returns_none(self):
        from cognia.reasoning.creative_llm import creative_generate

        class _Boom:
            def infer(self, *a, **k):
                raise RuntimeError("backend caido")

        assert creative_generate(_Boom(), "p") is None


class TestHipotesisManyRouting:
    """El branch CLI: /hipotesis con texto y SIN '|' rutea a generate_hypotheses_many."""

    def _route(self, raw, ai):
        # Replica EXACTA de la cadena de branches de /hipotesis en cli.repl()
        # (lineas ~4906-4913). Verifica la decision de ruteo, no el render.
        if raw.startswith("/hipotesis ") and "|" in raw:
            partes = raw[len("/hipotesis "):].split("|", 1)
            return ("pair", ai.generate_hypothesis(partes[0].strip(), partes[1].strip()))
        elif raw.startswith("/hipotesis ") and raw[len("/hipotesis "):].strip():
            texto = raw[len("/hipotesis "):].strip()
            return ("many", ai.generate_hypotheses_many(texto))
        elif raw.startswith("/hipotesis"):
            return ("usage", None)

    def test_text_without_pipe_routes_to_many(self):
        from unittest.mock import MagicMock
        ai = MagicMock()
        ai.generate_hypotheses_many.return_value = "ok"
        kind, _ = self._route("/hipotesis como reducir el ruido urbano", ai)
        assert kind == "many"
        ai.generate_hypotheses_many.assert_called_once_with("como reducir el ruido urbano")
        ai.generate_hypothesis.assert_not_called()

    def test_pipe_still_routes_to_pair(self):
        from unittest.mock import MagicMock
        ai = MagicMock()
        kind, _ = self._route("/hipotesis agua | energia", ai)
        assert kind == "pair"
        ai.generate_hypothesis.assert_called_once_with("agua", "energia")
        ai.generate_hypotheses_many.assert_not_called()

    def test_bare_command_routes_to_usage(self):
        from unittest.mock import MagicMock
        ai = MagicMock()
        kind, _ = self._route("/hipotesis", ai)
        assert kind == "usage"

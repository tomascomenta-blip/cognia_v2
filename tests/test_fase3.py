"""
tests/test_fase3.py
===================
Tests de Fase 3: CRDTKnowledgeGraph, privatize_embedding,
filter_shareable_triples, classify_triple.

Usa únicamente stdlib + numpy (ya instalado). Sin dependencia de DB en disco.
Ejecutar con: python -m pytest tests/test_fase3.py -v
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: CRDTKnowledgeGraph
# ══════════════════════════════════════════════════════════════════════════════

class TestCRDTKnowledgeGraph:

    def _graph(self, node_id: str = "nodo-A"):
        from network.crdt_graph import CRDTKnowledgeGraph
        return CRDTKnowledgeGraph(node_id=node_id)

    # ── add ──────────────────────────────────────────────────────────

    def test_add_triple_basico(self):
        g = self._graph()
        t = g.add("Python", "es_un", "lenguaje")
        assert t.subject   == "Python"
        assert t.predicate == "es_un"
        assert t.object    == "lenguaje"
        assert t.valid     is True

    def test_add_idempotente(self):
        g = self._graph()
        t1 = g.add("A", "rel", "B")
        t2 = g.add("A", "rel", "B")
        assert t1.triple_id == t2.triple_id
        assert g.stats()["total"] == 1

    def test_triple_id_determinista(self):
        from network.crdt_graph import _triple_hash
        h1 = _triple_hash("X", "es", "Y")
        h2 = _triple_hash("X", "es", "Y")
        assert h1 == h2

    def test_triple_id_diferente_por_contenido(self):
        from network.crdt_graph import _triple_hash
        h1 = _triple_hash("A", "es", "B")
        h2 = _triple_hash("A", "es", "C")
        assert h1 != h2

    # ── invalidate ───────────────────────────────────────────────────

    def test_invalidate_soft_delete(self):
        g = self._graph()
        g.add("Python", "es_un", "lenguaje")
        resultado = g.invalidate("Python", "es_un", "lenguaje")
        assert resultado is True
        # El triple sigue en el set (G-Set: nunca se borra)
        assert g.stats()["total"] == 1
        assert g.stats()["invalid"] == 1

    def test_invalidate_no_existente_retorna_false(self):
        g = self._graph()
        resultado = g.invalidate("X", "rel", "Z")
        assert resultado is False

    def test_get_valid_excluye_invalidados(self):
        g = self._graph()
        g.add("A", "es", "B")
        g.add("C", "es", "D")
        g.invalidate("A", "es", "B")
        validos = g.get_valid()
        assert len(validos) == 1
        assert validos[0].subject == "C"

    # ── merge — idempotencia ─────────────────────────────────────────

    def test_merge_idempotente(self):
        """merge(A, B) luego merge(A, B) de nuevo == mismo resultado."""
        g = self._graph()
        g.add("Python", "es_un", "lenguaje")
        delta = g.get_delta()

        g2 = self._graph("nodo-B")
        g2.merge(delta)
        count1 = g2.stats()["total"]
        g2.merge(delta)   # segunda vez — no debe crecer
        count2 = g2.stats()["total"]
        assert count1 == count2

    def test_merge_commutativo(self):
        """merge(A, B) == merge(B, A) en términos de triples finales."""
        from network.crdt_graph import CRDTKnowledgeGraph
        gA = CRDTKnowledgeGraph("nodo-A")
        gA.add("Python", "es_un", "lenguaje")
        gA.add("Java",   "es_un", "lenguaje")

        gB = CRDTKnowledgeGraph("nodo-B")
        gB.add("Rust",  "es_un", "lenguaje")

        # A <- B
        g1 = CRDTKnowledgeGraph("resultado-1")
        g1.merge(gA.get_delta())
        g1.merge(gB.get_delta())

        # B <- A
        g2 = CRDTKnowledgeGraph("resultado-2")
        g2.merge(gB.get_delta())
        g2.merge(gA.get_delta())

        ids1 = set(t.triple_id for t in g1._triples.values())
        ids2 = set(t.triple_id for t in g2._triples.values())
        assert ids1 == ids2

    def test_merge_invalida_si_remoto_invalido(self):
        """Si el remoto marca un triple como inválido, local también queda inválido."""
        from network.crdt_graph import CRDTKnowledgeGraph
        local  = CRDTKnowledgeGraph("local")
        local.add("A", "rel", "B")

        remoto = CRDTKnowledgeGraph("remoto")
        remoto.add("A", "rel", "B")
        remoto.invalidate("A", "rel", "B")

        delta = remoto.get_delta()
        # get_delta filtra por privacidad; bypaseamos usando to_dict directo
        all_delta = [t.to_dict() for t in remoto._triples.values()]
        local.merge(all_delta)

        triple = list(local._triples.values())[0]
        assert triple.valid is False

    def test_merge_conserva_timestamp_mas_antiguo(self):
        from network.crdt_graph import CRDTKnowledgeGraph, CRDTTriple
        local  = CRDTKnowledgeGraph("local")
        t_local = local.add("A", "es", "B")
        t_local.timestamp = 1000.0

        t_remoto = CRDTTriple("A", "es", "B", node_id="remoto", timestamp=500.0)

        local.merge([t_remoto.to_dict()])
        triple = list(local._triples.values())[0]
        assert triple.timestamp == pytest.approx(500.0)

    def test_merge_nuevo_triple(self):
        from network.crdt_graph import CRDTKnowledgeGraph
        g1 = CRDTKnowledgeGraph("A")
        g1.add("X", "es", "Y")

        g2 = CRDTKnowledgeGraph("B")
        count = g2.merge([t.to_dict() for t in g1._triples.values()])
        assert count == 1
        assert g2.stats()["total"] == 1

    def test_merge_triple_invalido_ignorado(self):
        from network.crdt_graph import CRDTKnowledgeGraph
        g = CRDTKnowledgeGraph("A")
        count = g.merge([{"subject": "ROTO"}])   # dict malformado
        assert count == 0

    # ── serialización ────────────────────────────────────────────────

    def test_to_json_from_json_roundtrip(self):
        from network.crdt_graph import CRDTKnowledgeGraph
        g = CRDTKnowledgeGraph("nodo-X")
        g.add("A", "es", "B")
        g.add("C", "es", "D")
        g.invalidate("A", "es", "B")

        serializado = g.to_json()
        g2 = CRDTKnowledgeGraph.from_json("nodo-X", serializado)

        assert g2.stats()["total"]   == g.stats()["total"]
        assert g2.stats()["invalid"] == g.stats()["invalid"]

    def test_stats_correcto(self):
        g = self._graph("nodo-test")
        g.add("A", "rel", "B")
        g.add("C", "rel", "D")
        g.invalidate("A", "rel", "B")

        s = g.stats()
        assert s["total"]   == 2
        assert s["valid"]   == 1
        assert s["invalid"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: privatize_embedding
# ══════════════════════════════════════════════════════════════════════════════

class TestPrivatizeEmbedding:

    def test_retorna_vector_misma_dimension(self):
        from network.privacy import privatize_embedding
        v   = [0.1] * 64
        out = privatize_embedding(v)
        assert len(out) == 64

    def test_ruido_hace_diferente(self):
        from network.privacy import privatize_embedding
        v   = [1.0] * 16
        out = privatize_embedding(v, epsilon=1.0)
        assert out != v

    def test_epsilon_bajo_mas_ruido(self):
        """Epsilon pequeño → más ruido → mayor distancia al original."""
        import math
        from network.privacy import privatize_embedding
        v  = [0.5] * 32
        n_trials = 5

        def media_distancia(eps):
            dists = []
            for _ in range(n_trials):
                out = privatize_embedding(v, epsilon=eps)
                d = math.sqrt(sum((a - b) ** 2 for a, b in zip(v, out)))
                dists.append(d)
            return sum(dists) / len(dists)

        d_bajo  = media_distancia(0.1)
        d_alto  = media_distancia(10.0)
        assert d_bajo > d_alto

    def test_epsilon_cero_lanza_error(self):
        from network.privacy import privatize_embedding
        with pytest.raises(ValueError):
            privatize_embedding([0.5] * 4, epsilon=0.0)

    def test_epsilon_negativo_lanza_error(self):
        from network.privacy import privatize_embedding
        with pytest.raises(ValueError):
            privatize_embedding([0.5] * 4, epsilon=-1.0)

    def test_no_modifica_vector_original(self):
        from network.privacy import privatize_embedding
        v       = [0.3, 0.4, 0.5]
        v_copia = v[:]
        privatize_embedding(v)
        assert v == v_copia

    def test_retorna_lista_de_floats(self):
        from network.privacy import privatize_embedding
        out = privatize_embedding([0.1, 0.2, 0.3])
        assert isinstance(out, list)
        assert all(isinstance(x, float) for x in out)


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: classify_triple
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyTriple:

    def test_predicado_privado(self):
        from network.privacy import classify_triple, PrivacyLayer
        assert classify_triple("yo", "siente", "miedo") == PrivacyLayer.PRIVATE

    def test_predicado_semi_privado(self):
        from network.privacy import classify_triple, PrivacyLayer
        assert classify_triple("yo", "trabaja_en", "empresa") == PrivacyLayer.SEMI_PRIV

    def test_predicado_publico(self):
        from network.privacy import classify_triple, PrivacyLayer
        assert classify_triple("Python", "es_un", "lenguaje") == PrivacyLayer.PUBLIC

    def test_predicado_desconocido_es_publico(self):
        from network.privacy import classify_triple, PrivacyLayer
        assert classify_triple("A", "predicado_raro_xyz", "B") == PrivacyLayer.PUBLIC

    def test_case_insensitive(self):
        from network.privacy import classify_triple, PrivacyLayer
        assert classify_triple("yo", "SIENTE", "algo") == PrivacyLayer.PRIVATE

    def test_todos_privados_reconocidos(self):
        from network.privacy import classify_triple, PrivacyLayer
        privados = ["recuerda", "siente", "vivió", "experimentó", "teme", "desea"]
        for pred in privados:
            assert classify_triple("s", pred, "o") == PrivacyLayer.PRIVATE, pred

    def test_todos_semi_priv_reconocidos(self):
        from network.privacy import classify_triple, PrivacyLayer
        semi = ["conoce", "trabaja_en", "vive_en", "prefiere", "usa"]
        for pred in semi:
            assert classify_triple("s", pred, "o") == PrivacyLayer.SEMI_PRIV, pred


# ══════════════════════════════════════════════════════════════════════════════
# TESTS: filter_shareable_triples
# ══════════════════════════════════════════════════════════════════════════════

class TestFilterShareableTriples:

    def test_excluye_privados(self):
        from network.privacy import filter_shareable_triples
        triples = [{"subject": "yo", "predicate": "siente", "object": "miedo"}]
        result  = filter_shareable_triples(triples)
        assert result == []

    def test_incluye_publicos(self):
        from network.privacy import filter_shareable_triples
        triples = [{"subject": "Python", "predicate": "es_un", "object": "lenguaje"}]
        result  = filter_shareable_triples(triples)
        assert len(result) == 1

    def test_incluye_semi_privados(self):
        from network.privacy import filter_shareable_triples
        triples = [{"subject": "yo", "predicate": "trabaja_en", "object": "empresa"}]
        result  = filter_shareable_triples(triples)
        assert len(result) == 1

    def test_anonimiza_sujeto_largo(self):
        from network.privacy import filter_shareable_triples
        triples = [{"subject": "identidad_personal_muy_larga_y_sensible",
                    "predicate": "es_un", "object": "persona"}]
        result = filter_shareable_triples(triples)
        assert len(result) == 1
        assert "subject_hash" in result[0]
        assert result[0]["subject_hash"] != "identidad_personal_muy_larga_y_sensible"

    def test_filtra_mixto(self):
        from network.privacy import filter_shareable_triples
        triples = [
            {"subject": "yo",     "predicate": "siente",   "object": "miedo"},    # PRIVATE
            {"subject": "yo",     "predicate": "trabaja_en","object": "empresa"},  # SEMI_PRIV
            {"subject": "Python", "predicate": "es_un",    "object": "lenguaje"}, # PUBLIC
        ]
        result = filter_shareable_triples(triples)
        assert len(result) == 2

    def test_triple_malformado_no_rompe(self):
        from network.privacy import filter_shareable_triples
        triples = [{"roto": "sin claves válidas"}]
        result  = filter_shareable_triples(triples)
        # puede retornar vacío o el triple con predicado vacío (PUBLIC)
        assert isinstance(result, list)

    def test_retorna_campo_layer(self):
        from network.privacy import filter_shareable_triples, PrivacyLayer
        triples = [{"subject": "X", "predicate": "es_un", "object": "Y"}]
        result  = filter_shareable_triples(triples)
        assert "layer" in result[0]
        assert result[0]["layer"] == int(PrivacyLayer.PUBLIC)

    def test_lista_vacia(self):
        from network.privacy import filter_shareable_triples
        assert filter_shareable_triples([]) == []

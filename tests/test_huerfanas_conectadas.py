# -*- coding: utf-8 -*-
"""
tests/test_huerfanas_conectadas.py
===================================
Regresion de la conexion de funciones huerfanas (auditoria 2026-08-01) en
cognia/knowledge/ y cognia/search/:

1. InferenceEngine.apply_stored_rules ahora corre DENTRO de infer()
   (antes: add_rule escribia reglas que nadie leia jamas).
2. KnowledgeGraph.stats() expone get_auto_facts_count/get_recent_auto_facts.
3. KnowledgeGraph.graph_path es el fast-path networkx de
   MultiHopEngine.find_path (con fallback BFS intacto).
4. CrystallizationWorker._tick llama decrystallize_stale (antes la
   cristalizacion solo crecia).
5. WebSearch acota su cache en memoria via _prune_cache/clear_cache.
"""

import os
import tempfile
import time

import pytest

from cognia.database import init_db
from cognia.knowledge.graph import KnowledgeGraph
from cognia.knowledge.inference import InferenceEngine
from storage.db_pool import db_connect_pooled as db_connect


@pytest.fixture
def db_path():
    """DB temporal con el schema completo de Cognia."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    init_db(path)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def kg(db_path):
    return KnowledgeGraph(db_path=db_path)


# ── 1. Reglas almacenadas conectadas a infer() ────────────────────────


class TestStoredRulesEnInfer:

    def test_regla_con_premisa_cumplida_aparece_en_infer(self, db_path, kg):
        kg.add_triple("socrates", "is_a", "humano")
        eng = InferenceEngine(db_path=db_path, kg=kg)
        eng.add_rule("socrates", "is_a", "", "", "socrates es mortal", 0.9)

        inferencias = eng.infer("socrates")
        almacenadas = [i for i in inferencias if i.get("type") == "stored_rule"]
        assert len(almacenadas) == 1
        assert almacenadas[0]["conclusion_object"] == "socrates es mortal"
        assert almacenadas[0]["confidence"] == 0.9
        # contrato de los consumidores (cognia.py lee justification/confidence)
        assert "justification" in almacenadas[0]

    def test_regla_sin_hechos_no_dispara(self, db_path, kg):
        eng = InferenceEngine(db_path=db_path, kg=kg)
        eng.add_rule("platon", "is_a", "", "", "platon es mortal", 0.9)
        # 'platon' no tiene NINGUN hecho en el KG -> la regla no aplica
        assert eng.apply_stored_rules("platon") == []
        stored = [i for i in eng.infer("platon") if i.get("type") == "stored_rule"]
        assert stored == []

    def test_add_rule_normaliza_mayusculas(self, db_path, kg):
        # add_triple guarda en minusculas; la regla creada con 'Python'
        # debe casar igual (antes quedaba huerfana por el case).
        kg.add_triple("python", "is_a", "lenguaje")
        eng = InferenceEngine(db_path=db_path, kg=kg)
        eng.add_rule("Python", "is_a", "", "", "python es popular", 0.8)
        assert len(eng.apply_stored_rules("Python")) == 1

    def test_sin_tabla_inference_rules_no_revienta(self, tmp_path):
        # DB minima: solo knowledge_graph (sin init_db). apply_stored_rules
        # debe devolver [] en vez de tumbar infer().
        path = str(tmp_path / "minimo.db")
        conn = db_connect(path)
        conn.execute("""CREATE TABLE knowledge_graph (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, predicate TEXT, object TEXT,
            weight REAL DEFAULT 1.0, source TEXT, timestamp TEXT)""")
        conn.commit()
        conn.close()
        kg = KnowledgeGraph(db_path=path)
        eng = InferenceEngine(db_path=path, kg=kg)
        assert eng.apply_stored_rules("algo") == []


# ── 2. stats() expone los contadores de auto-extraccion ───────────────


class TestStatsAutoFacts:

    def test_stats_incluye_auto_facts(self, kg):
        kg.add_triple("gato", "is_a", "animal", source="learned")
        kg.extract_and_store("Cognia is a cognitive system.",
                             source="conversation")
        s = kg.stats()
        assert "auto_facts" in s and "recent_auto_facts" in s
        assert s["auto_facts"] >= 1
        assert isinstance(s["recent_auto_facts"], list)
        assert s["recent_auto_facts"][0]["source"] == "conversation"

    def test_stats_sin_auto_facts(self, kg):
        kg.add_triple("gato", "is_a", "animal", source="learned")
        s = kg.stats()
        assert s["auto_facts"] == 0
        assert s["recent_auto_facts"] == []


# ── 3. graph_path como fast-path de MultiHopEngine.find_path ──────────


class TestFindPathFastPath:

    def _engine(self, kg):
        from cognia.knowledge.multihop_engine import MultiHopEngine
        eng = object.__new__(MultiHopEngine)
        eng._kg = kg
        return eng

    def test_camino_real_dos_hops(self, kg):
        kg.add_triple("gato", "is_a", "animal")
        kg.add_triple("animal", "is_a", "ser vivo")
        eng = self._engine(kg)
        path = eng.find_path("gato", "ser vivo")
        assert path == [("gato", "is_a", "animal"),
                        ("animal", "is_a", "ser vivo")]

    def test_fast_path_se_usa_con_networkx(self, kg):
        from cognia.config import HAS_NETWORKX
        if not HAS_NETWORKX:
            pytest.skip("sin networkx: no hay fast-path que probar")
        kg.add_triple("a1", "causes", "b1")
        kg.add_triple("b1", "causes", "c1")
        # el fast-path resuelve el MISMO camino que el BFS
        assert kg.graph_path("a1", "c1") == ["a1", "b1", "c1"]
        eng = self._engine(kg)
        assert eng.find_path("a1", "c1") == [("a1", "causes", "b1"),
                                             ("b1", "causes", "c1")]

    def test_graph_path_basura_cae_a_bfs(self):
        # un KG cuyo graph_path devuelve algo no-lista (p.ej. un mock)
        # no debe romper find_path: BFS manda.
        class KGStub:
            def graph_path(self, s, t):
                return object()  # no-lista

            def get_neighbors(self, concept, predicate=None):
                return ({"x": [{"concept": "y", "relation": "is_a"}]}
                        .get(concept, []))

        eng = self._engine(KGStub())
        assert eng.find_path("x", "y") == [("x", "is_a", "y")]

    def test_camino_mas_largo_que_max_hops_vacio(self, kg):
        kg.add_triple("n1", "causes", "n2")
        kg.add_triple("n2", "causes", "n3")
        kg.add_triple("n3", "causes", "n4")
        kg.add_triple("n4", "causes", "n5")
        eng = self._engine(kg)
        assert eng.find_path("n1", "n5") == []  # 4 hops > MAX_HOPS=3


# ── 4. El tick del worker tambien descristaliza ───────────────────────


class TestCrystallizerTick:

    def test_tick_descristaliza_stale_y_conserva_frescos(self, db_path, kg):
        from cognia.knowledge.crystallizer import (CrystallizationWorker,
                                                   KnowledgeCrystallizer)
        kg.add_triple("viejo", "is_a", "hecho", weight=2.0)
        kg.add_triple("fresco", "is_a", "hecho", weight=2.0)
        cryst = KnowledgeCrystallizer(db_path=db_path)

        # 'viejo' sin acceso hace 60 dias; 'fresco' accedido ahora
        conn = db_connect(db_path)
        conn.execute("UPDATE knowledge_graph SET last_accessed=? WHERE subject='viejo'",
                     (time.time() - 60 * 86400,))
        conn.execute("UPDATE knowledge_graph SET last_accessed=? WHERE subject='fresco'",
                     (time.time(),))
        conn.commit()
        conn.close()

        worker = CrystallizationWorker(cryst)
        worker._tick()  # cristaliza frecuentes Y descristaliza stale

        conn = db_connect(db_path)
        viejo = conn.execute(
            "SELECT crystallized FROM knowledge_graph WHERE subject='viejo'"
        ).fetchone()[0]
        fresco = conn.execute(
            "SELECT crystallized FROM knowledge_graph WHERE subject='fresco'"
        ).fetchone()[0]
        conn.close()
        assert viejo == 0, "el hecho stale debe perder la cristalizacion"
        assert fresco == 1, "el hecho fresco debe seguir cristalizado"

    def test_tick_no_revienta_sin_tabla(self, tmp_path):
        # DB inexistente/vacia: _tick traga la excepcion (daemon no muere)
        from cognia.knowledge.crystallizer import (CrystallizationWorker,
                                                   KnowledgeCrystallizer)
        cryst = KnowledgeCrystallizer.__new__(KnowledgeCrystallizer)
        cryst.db = str(tmp_path / "no_existe" / "x.db")
        CrystallizationWorker(cryst)._tick()  # no debe lanzar


# ── 5. WebSearch: cache acotado (clear_cache conectada) ───────────────


class TestWebSearchCacheAcotado:

    def test_prune_expira_vencidas(self):
        from cognia.search.web_search import WebSearch
        ws = WebSearch()
        viejo = time.time() - ws._cache_ttl - 1
        for i in range(ws._CACHE_MAX):
            ws._cache[f"q{i}"] = ({"query": f"q{i}"}, viejo)
        ws._prune_cache()
        assert len(ws._cache) == 0

    def test_prune_llena_de_frescas_vacia_todo(self):
        from cognia.search.web_search import WebSearch
        ws = WebSearch()
        ahora = time.time()
        for i in range(ws._CACHE_MAX):
            ws._cache[f"q{i}"] = ({"query": f"q{i}"}, ahora)
        ws._prune_cache()
        # ninguna vencida -> clear_cache() total
        assert len(ws._cache) == 0

    def test_prune_no_toca_cache_chico(self):
        from cognia.search.web_search import WebSearch
        ws = WebSearch()
        ws._cache["q"] = ({"query": "q"}, time.time())
        ws._prune_cache()
        assert "q" in ws._cache

    def test_search_mantiene_cache_acotado(self):
        import json as _json
        from unittest.mock import MagicMock, patch
        from cognia.search.web_search import WebSearch

        payload = _json.dumps({"AbstractText": "algo util",
                               "AbstractSource": "Wikipedia",
                               "Heading": "x", "Answer": "",
                               "RelatedTopics": []}).encode("utf-8")
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        ws = WebSearch()
        with patch("urllib.request.urlopen", return_value=resp):
            for i in range(ws._CACHE_MAX + 10):
                ws.search(f"consulta {i}")
        assert len(ws._cache) <= ws._CACHE_MAX

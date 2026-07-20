# -*- coding: utf-8 -*-
"""Tests del grafo de código (cognia/knowledge/code_graph.py) — KG en tmp."""
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.knowledge.code_graph import (dependencias, indexar_codigo,
                                         quien_importa)
from cognia.knowledge.graph import KnowledgeGraph


@pytest.fixture()
def repo_fake(tmp_path):
    """Mini-repo: paquete cognia/ con 2 módulos que se importan y llaman."""
    paq = tmp_path / "cognia"
    paq.mkdir()
    (paq / "__init__.py").write_text("", encoding="utf-8")
    (paq / "alfa.py").write_text(textwrap.dedent("""
        import cognia.beta

        def saluda():
            return cognia.beta.nombre()

        class Cosa:
            def metodo(self):
                pass
    """), encoding="utf-8")
    (paq / "beta.py").write_text(textwrap.dedent("""
        def nombre():
            return "beta"
    """), encoding="utf-8")
    (paq / "rota.py").write_text("def sin_cerrar(:", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def kg_tmp(tmp_path):
    from cognia.database import init_db
    db = str(tmp_path / "kg.db")
    init_db(db)                     # crea el schema (knowledge_graph incl.)
    return KnowledgeGraph(db_path=db)


def test_indexa_imports_defines_metodos_y_llamadas(repo_fake, kg_tmp):
    m = indexar_codigo(raiz=repo_fake, kg=kg_tmp, paquetes=("cognia",))
    assert m["modulos"] == 3          # alfa, beta, cognia (__init__)
    assert m["triples"] >= 5
    assert dependencias("cognia.alfa", kg_tmp) == ["cognia.beta"]
    assert quien_importa("cognia.beta", kg_tmp) == ["cognia.alfa"]
    # define + tiene_metodo + llama_a en el MISMO kg (fusión, no sistema aparte)
    objetos = {f["object"] for f in kg_tmp.get_facts("cognia.alfa", "define")}
    assert {"cognia.alfa.saluda", "cognia.alfa.cosa"} <= objetos
    metodos = {f["object"]
               for f in kg_tmp.get_facts("cognia.alfa.cosa", "tiene_metodo")}
    assert metodos == {"metodo"}
    llamados = {f["object"]
                for f in kg_tmp.get_facts("cognia.alfa.saluda", "llama_a")}
    assert llamados == {"cognia.beta.nombre"}


def test_archivo_con_syntax_error_no_rompe(repo_fake, kg_tmp):
    m = indexar_codigo(raiz=repo_fake, kg=kg_tmp, paquetes=("cognia",))
    assert m["modulos"] == 3          # rota.py se salta, no lanza


def test_reindexar_es_idempotente(repo_fake, kg_tmp):
    m1 = indexar_codigo(raiz=repo_fake, kg=kg_tmp, paquetes=("cognia",))
    m2 = indexar_codigo(raiz=repo_fake, kg=kg_tmp, paquetes=("cognia",))
    assert m2["borrados_previos"] == m1["triples"]
    assert m2["triples"] == m1["triples"]
    # sin duplicados: dependencias sigue devolviendo 1 entrada
    assert dependencias("cognia.alfa", kg_tmp) == ["cognia.beta"]


def test_no_toca_triples_de_otras_fuentes(repo_fake, kg_tmp):
    kg_tmp.add_triple("gato", "is_a", "animal", source="learned")
    indexar_codigo(raiz=repo_fake, kg=kg_tmp, paquetes=("cognia",))
    indexar_codigo(raiz=repo_fake, kg=kg_tmp, paquetes=("cognia",))
    assert kg_tmp.get_facts("gato", "is_a")   # sobrevive los reindexados

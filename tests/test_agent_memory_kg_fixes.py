"""
Regresion de bugs de las herramientas de memoria/KG del agente (auditados y
verificados adversarialmente, 2026-07-01).

- get_facts case-insensitive (bug ALTO): add_triple guarda en minusculas; get_facts
  con concepto capitalizado devolvia [] -> kg_buscar 'sin hechos' para nombres propios.
- kg_agregar: relacion case-insensitive + reporta nuevo/reforzado (no 'no agregado').
- kg_buscar: formato legible (no repr de dict crudo).
- memorizar: reporta el rechazo real de observe() (no miente 'guardado').
- recordar: piso de similitud (no surfacea ruido ~0 como relevante).
"""

import types

import pytest

from cognia.agent import tools as T
from cognia.database import init_db
from cognia.knowledge.graph import KnowledgeGraph


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


# ── get_facts case-insensitive (bug ALTO) ───────────────────────────────

@pytest.fixture
def kg(tmp_path):
    db_path = str(tmp_path / "kg.db")
    init_db(db_path)
    return KnowledgeGraph(db_path=db_path)


def test_get_facts_case_insensitive(kg):
    # add_triple lo guarda en minusculas ('django', 'python').
    kg.add_triple("Django", "is_a", "Python", source="test")
    # Consultar con MAYUSCULAS (como escribe los nombres propios un modelo) debe
    # encontrar el hecho igual (antes devolvia [] por collation BINARY).
    assert kg.get_facts("Python"), "get_facts('Python') no encontro el hecho (bug de case)"
    assert kg.get_facts("DJANGO"), "get_facts('DJANGO') no encontro el hecho"
    assert kg.get_facts("python"), "get_facts('python') deberia seguir funcionando"
    # El hecho correcto sale por la posicion OBJETO tambien.
    objs = [f["object"] for f in kg.get_facts("Python")]
    assert "python" in objs


def test_kg_buscar_finds_capitalized_concept(kg):
    kg.add_triple("Flask", "is_a", "framework", source="test")
    ai = types.SimpleNamespace(kg=kg)
    out = T.run_tool("kg_buscar", "Flask", _ctx(ai=ai))
    assert "sin hechos" not in out
    assert "flask" in out.lower() and "framework" in out.lower()


# ── kg_agregar: relacion case-insensitive + nuevo/reforzado ──────────────

def test_kg_agregar_relation_case_insensitive():
    ai = types.SimpleNamespace(kg=types.SimpleNamespace(add_triple=lambda *a, **k: True))
    out = T.run_tool("kg_agregar", "cognia | IS_A | sistema", _ctx(ai=ai))
    assert "OK" in out and "invalida" not in out


def test_kg_agregar_reports_reinforced_not_failure():
    # add_triple devuelve False cuando el hecho YA existe (lo refuerza).
    ai = types.SimpleNamespace(kg=types.SimpleNamespace(add_triple=lambda *a, **k: False))
    out = T.run_tool("kg_agregar", "cognia | is_a | sistema", _ctx(ai=ai))
    assert "reforzado" in out and "no agregado" not in out


# ── kg_buscar: formato legible ───────────────────────────────────────────

def test_kg_buscar_readable_format():
    facts = [{"subject": "django", "predicate": "is_a", "object": "python", "weight": 1.0}]
    ai = types.SimpleNamespace(kg=types.SimpleNamespace(
        get_facts=lambda c: facts, get_neighbors=lambda c: []))
    out = T.run_tool("kg_buscar", "django", _ctx(ai=ai))
    assert "django is_a python" in out
    assert "{'subject'" not in out and "'predicate'" not in out


# ── memorizar: reporta rechazo real ──────────────────────────────────────

def test_memorizar_reports_rejection():
    ai = types.SimpleNamespace(
        observe=lambda text, provided_label=None: {"status": "rejected", "reason": "too_short"})
    out = T.run_tool("memorizar", "x", _ctx(ai=ai))
    assert "NO se guardo" in out and "too_short" in out


def test_memorizar_reports_success_when_learned():
    ai = types.SimpleNamespace(
        observe=lambda text, provided_label=None: {"action": "learned"})
    out = T.run_tool("memorizar", "un dato util y largo", _ctx(ai=ai))
    assert "guardado" in out and "NO se guardo" not in out


# ── recordar: piso de similitud ──────────────────────────────────────────

def test_recordar_similarity_floor_drops_noise():
    hits = [
        {"observation": "relevante", "similarity": 0.8},
        {"observation": "ruido casi ortogonal", "similarity": 0.02},
    ]
    ai = types.SimpleNamespace(
        episodic=types.SimpleNamespace(retrieve_similar=lambda vec, top_k=5: hits))
    out = T.run_tool("recordar", "consulta", _ctx(ai=ai))
    assert "relevante" in out
    assert "ruido casi ortogonal" not in out   # filtrado por el piso


def test_recordar_keeps_relevant_hits():
    hits = [{"observation": "el parser quedo listo", "similarity": 0.5}]
    ai = types.SimpleNamespace(
        episodic=types.SimpleNamespace(retrieve_similar=lambda vec, top_k=5: hits))
    out = T.run_tool("recordar", "parser", _ctx(ai=ai))
    assert "el parser quedo listo" in out

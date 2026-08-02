"""
Tests de regresion del AREA A4 (fase 2, auditoria 2026-08-01):

  1. seed_static es IDEMPOTENTE: dos corridas no duplican filas (antes:
     220.780 filas con 134 textos distintos, 1.9 GB de DB).
  2. _ngram_vector usa hash ESTABLE entre procesos (antes: hash() aleatorizado
     por PYTHONHASHSEED -> cos(guardado, mismo texto) = 0.559 en vez de 1.0).
  3. add_triple pela comillas de las entidades (antes: "recuerda que X se
     llama 'zafiro'" guardaba "'zafiro'" y get_facts('zafiro') devolvia []).
  4. update_concept rechaza un str como vector (antes lo persistia tal cual).
  5. VectorCache persiste la matriz en disco y un proceso nuevo la carga sin
     pagar el build completo (antes: 50s / +293MB dentro del primer turno).

Cada test falla sin su fix correspondiente.
"""

import json
import os
import subprocess
import sys

import pytest

from cognia.database import init_db
from storage.db_pool import db_connect_pooled, close_pool


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "mem.db")
    init_db(p)
    yield p
    close_pool(p)


def _count(db_path, where="1=1"):
    conn = db_connect_pooled(db_path)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM episodic_memory WHERE {where}"
        ).fetchone()[0]
    finally:
        conn.close()


# ── 1. seed idempotente ───────────────────────────────────────────────


def test_seed_static_no_duplica(db):
    from cognia.memory.episodic import EpisodicMemory
    from cognia.knowledge.knowledge_seeder import KnowledgeSeeder

    mem = EpisodicMemory(db)
    KnowledgeSeeder.SEED_BATCH_SLEEP = 0  # sin sleep entre stores en el test
    KnowledgeSeeder.seed_static(mem)
    n1 = _count(db, "label LIKE 'conocimiento_%'")
    assert n1 > 100  # se sembro de verdad

    KnowledgeSeeder.seed_static(mem)  # segundo arranque
    n2 = _count(db, "label LIKE 'conocimiento_%'")
    assert n2 == n1  # NO crece


# ── 2. hash estable en n-gramas ───────────────────────────────────────

_NGRAM_SNIPPET = (
    "from cognia.cognia_embedding import _ngram_vector; "
    "import json; print(json.dumps(_ngram_vector('el gil de python')))"
)


def _ngram_in_subprocess(hashseed):
    env = dict(os.environ, PYTHONHASHSEED=str(hashseed),
               PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = subprocess.run(
        [sys.executable, "-c", _NGRAM_SNIPPET],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_ngram_vector_estable_entre_procesos():
    v1 = _ngram_in_subprocess(1)
    v2 = _ngram_in_subprocess(2)
    assert v1 == v2  # con hash() builtin esto fallaba (seeds distintos)


def test_ngram_vector_identico_en_ambas_copias():
    # cognia/ y cognia_v3/memory/ comparten el fallback: deben producir
    # exactamente el mismo vector (mismo espacio vectorial).
    from cognia.cognia_embedding import _ngram_vector as v_a
    from cognia_v3.memory.cognia_embedding import _ngram_vector as v_b
    assert v_a("hola mundo") == v_b("hola mundo")


# ── 3. comillas en el KG ──────────────────────────────────────────────


def test_add_triple_pela_comillas(db):
    from cognia.knowledge.graph import KnowledgeGraph

    kg = KnowledgeGraph(db)
    kg.add_triple('"servidor de auditoria"', "is_a", "'zafiro'", source="user")
    facts = kg.get_facts("zafiro")
    assert facts, "entidad con comillas no recuperable sin comillas"
    assert facts[0]["subject"] == "servidor de auditoria"
    assert facts[0]["object"] == "zafiro"


def test_effective_predicate_expuesto(db):
    from cognia.knowledge.graph import KnowledgeGraph

    kg = KnowledgeGraph(db)
    assert kg.effective_predicate("se_llama") == "related_to"
    assert kg.effective_predicate("is_a") == "is_a"


# ── 4. vector invalido en semantic ────────────────────────────────────


def test_update_concept_rechaza_str(db):
    from cognia.memory.semantic import SemanticMemory

    sem = SemanticMemory(db)
    sem.update_concept("gato", "esto no es un vector")  # no debe crashear
    assert sem.get_concept("gato") is None  # y NO debe persistirse

    sem.update_concept("gato", [0.1] * 8)
    assert sem.get_concept("gato") is not None  # el camino valido sigue vivo


# ── 5. VectorCache persistido ─────────────────────────────────────────


def _insert_vectors(db_path, n):
    conn = db_connect_pooled(db_path)
    try:
        for i in range(n):
            vec = [0.0] * 384
            vec[i % 384] = 1.0
            conn.execute(
                "INSERT INTO episodic_memory (timestamp, observation, label, "
                "vector, confidence, importance, forgotten) "
                "VALUES (?,?,?,?,?,?,0)",
                ("2026-01-01", f"obs {i}", "test", json.dumps(vec), 0.8, 1.0),
            )
        conn.commit()
    finally:
        conn.close()


def test_vector_cache_persiste_y_recarga(db, tmp_path):
    from cognia.memory.episodic_fast import VectorCache

    _insert_vectors(db, 20)
    c1 = VectorCache(db)
    c1.build()
    npy, meta = c1._persist_paths()
    assert os.path.exists(npy) and os.path.exists(meta)

    # Proceso "nuevo": otra instancia. Si intenta el build completo, el test
    # falla — la unica via permitida es la matriz persistida + incremental.
    c2 = VectorCache(db)
    c2._build_locked = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("build completo en vez de cargar el cache persistido"))
    q = [0.0] * 384
    q[3] = 1.0
    res = c2.search(q, top_k=3)
    assert res and res[0]["observation"] == "obs 3"

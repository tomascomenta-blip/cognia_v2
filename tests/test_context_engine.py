"""Cycle 7 - context_engine facade: record_turn / retrieve / refresh_map / stats.

Deterministic: a FakeAI provides a fixed embedding, no real model involved.
The hybrid retriever decides the literal-phrase case by BM25 (vectors tie).
"""

import pytest

from cognia.context.context_map import ContextMap
from cognia.context import context_engine as ce
from storage.db_pool import close_pool


class _FakePerception:
    def extract_features(self, text):
        return {"vector": [0.0, 1.0]}


class FakeAI:
    def __init__(self, db):
        self.db = db
        self.perception = _FakePerception()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "ctxengine_test.db")
    yield path
    close_pool(path)


def test_record_turn(db_path):
    ai = FakeAI(db_path)

    pid = ce.record_turn(ai, "user", "hola mundo", 5)
    assert pid is not None

    cm = ContextMap(db_path=db_path)
    p = [r for r in cm.pointers() if r["id"] == pid][0]
    assert p["source_kind"] == "msg"
    assert p["source_ref"] == "5"

    assert ce.record_turn(ai, "user", "", 6) is None
    assert ce.record_turn(ai, "user", "   ", 7) is None


def test_retrieve_hybrid(db_path):
    ai = FakeAI(db_path)
    cm = ContextMap(db_path=db_path)
    cm.add_pointer("text", "", inline_text="texto sin relacion con la consulta",
                   vector=[0.0, 1.0])
    cm.add_pointer("text", "", inline_text="esta es la frase buscada por el usuario",
                   vector=[0.0, 1.0])

    res = ce.retrieve(ai, "frase buscada")

    assert res
    assert "frase buscada" in res[0]["text"]


def test_refresh_map(db_path, tmp_path):
    ai = FakeAI(db_path)
    cm = ContextMap(db_path=db_path)
    cm.add_pointer("text", "", inline_text="algo", summary="un span de prueba")

    out = str(tmp_path / "cognia_context.md")
    ret = ce.refresh_map(ai, out_path=out)

    assert ret == out
    from pathlib import Path
    contenido = Path(out).read_text(encoding="utf-8")
    assert "Mapa de contexto" in contenido
    assert all(ord(c) < 128 for c in contenido)


def test_stats(db_path):
    ai = FakeAI(db_path)
    cm = ContextMap(db_path=db_path)
    cm.add_pointer("text", "", inline_text="algo")

    s = ce.stats(ai)

    assert isinstance(s, dict)
    assert "pointers" in s
    assert s["pointers"] >= 1

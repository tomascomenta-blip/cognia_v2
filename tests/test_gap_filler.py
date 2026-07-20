"""Cycle 4 - gap-filling: index the uncovered tail of known sources and retry.

Deterministic, no real model. The embedder maps any text mentioning NEEDLE to
[1.0, 0.0] and everything else to [0.0, 1.0], so the needle chunk scores 1.0
against a needle query and non-needle chunks score 0.0.
"""

import numpy as np
import pytest

from cognia.context.context_map import ContextMap
from cognia.context.gap_filler import (
    fill_gaps,
    index_source_range,
    query_with_gap_fill,
)
from storage.db_pool import close_pool


def embed_fn(t):
    return [1.0, 0.0] if "NEEDLE" in t else [0.0, 1.0]


class FakePerc:
    def extract_features(self, t):
        return {"vector": embed_fn(t)}


class FakeEpis:
    def store(self, *a, **k):
        pass


class FakeAI:
    def __init__(self, db):
        self.db = db
        self.perception = FakePerc()
        self.episodic = FakeEpis()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "gap_filler_test.db")
    yield path
    close_pool(path)


_HEAD = (
    "Primer parrafo introductorio con bastante texto para superar el filtro de cuarenta.\n\n"
    "Segundo parrafo de relleno que tampoco menciona el dato buscado y supera el umbral.\n\n"
)
_NEEDLE_PARA = (
    "Tercer parrafo contiene el NEEDLE-7741 escondido en el medio del documento de prueba.\n\n"
)
_TAIL = "Cuarto parrafo final cierra el documento con material adicional suficiente para chunk."
_CONTENT = _HEAD + _NEEDLE_PARA + _TAIL


def test_uncovered_sources(db_path):
    cm = ContextMap(db_path=db_path)
    cm.mark_coverage("/a", indexed_through=50, total_chars=100)
    cm.mark_coverage("/b", indexed_through=100, total_chars=100)

    gaps = cm.uncovered_sources("default")

    assert ("/a", 50, 100) in gaps
    assert all(src != "/b" for (src, _it, _tc) in gaps)


def test_index_source_range_lossless(tmp_path, db_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text(_CONTENT, encoding="utf-8")
    cm = ContextMap(db_path=db_path)

    n = index_source_range(cm, FakeAI(db_path), str(ruta), "default", start=0)
    assert n > 0

    full = ruta.read_text(encoding="utf-8", errors="replace")
    ptrs = [p for p in cm.pointers() if p["source_kind"] == "file"]
    assert len(ptrs) == n
    for p in ptrs:
        assert cm.resolve(p["id"]) == full[p["char_start"]:p["char_end"]]
    assert any("NEEDLE-7741" in (cm.resolve(p["id"]) or "") for p in ptrs)

    assert cm.uncovered(str(ruta)) is None


def test_fill_gaps_indexes_tail(tmp_path, db_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text(_CONTENT, encoding="utf-8")
    cm = ContextMap(db_path=db_path)

    # Partial coverage WITHOUT tail pointers: index stops right before the
    # needle paragraph (K = len(head)).
    k = len(_HEAD)
    cm.mark_coverage(str(ruta), indexed_through=k, total_chars=len(_CONTENT))

    added = fill_gaps(cm, FakeAI(db_path), "default")
    assert added > 0

    res = cm.query_text("donde esta el NEEDLE", embed_fn, budget_tokens=4000)
    assert res
    assert any("NEEDLE" in r["text"] for r in res)


def test_query_with_gap_fill(tmp_path, db_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text(_CONTENT, encoding="utf-8")
    cm = ContextMap(db_path=db_path)
    ai = FakeAI(db_path)

    # Same gap setup as test 3: partial coverage, no tail pointers, so the
    # needle is absent from the index before the fill.
    k = len(_HEAD)
    cm.mark_coverage(str(ruta), indexed_through=k, total_chars=len(_CONTENT))

    before = cm.query_text("donde esta el NEEDLE", embed_fn, budget_tokens=4000)
    assert not before or before[0]["score"] < 0.5
    assert all("NEEDLE" not in r["text"] for r in before)

    res = query_with_gap_fill(cm, ai, "donde esta el NEEDLE", embed_fn, min_score=0.5)
    assert res
    assert "NEEDLE" in res[0]["text"]


def test_add_pointer_accepts_numpy(db_path):
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("text", "", inline_text="x", vector=np.array([1.0, 2.0, 3.0]))
    p = [r for r in cm.pointers() if r["id"] == pid][0]
    assert p["vector"] is not None

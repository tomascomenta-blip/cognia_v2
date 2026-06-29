"""Cycle 7 - organic on-disk gap-filling: detect gaps by the CURRENT file size
on disk (not by stored coverage), so a file that grew gets its new tail indexed.

Deterministic, no real model. The embedder maps any text mentioning NEEDLE to
[1.0, 0.0] and everything else to [0.0, 1.0].
"""

import pytest

from cognia.context.context_map import ContextMap
from cognia.context.gap_filler import fill_gaps_ondisk, index_source_range
from storage.db_pool import close_pool


def embed_fn(t):
    return [1.0, 0.0] if "NEEDLE" in t else [0.0, 1.0]


class FakePerc:
    def extract_features(self, t):
        return {"vector": embed_fn(t)}


class FakeAI:
    def __init__(self, db):
        self.db = db
        self.perception = FakePerc()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "gap_ondisk_test.db")
    yield path
    close_pool(path)


_INIT = (
    "Primer parrafo introductorio con bastante texto para superar el filtro de cuarenta."
)
_NEEDLE_APPEND = (
    "\n\nTercer parrafo contiene el NEEDLE-7741 escondido en el medio del documento de prueba."
)


def test_all_coverage(db_path):
    cm = ContextMap(db_path=db_path)
    cm.mark_coverage("/a", indexed_through=50, total_chars=100)   # con hueco
    cm.mark_coverage("/b", indexed_through=100, total_chars=100)  # sin hueco

    cov = cm.all_coverage("default")

    assert ("/a", 50, 100) in cov
    assert ("/b", 100, 100) in cov


def test_fill_gaps_ondisk_detects_growth(tmp_path, db_path):
    ruta = tmp_path / "doc.txt"
    ruta.write_text(_INIT, encoding="utf-8")
    cm = ContextMap(db_path=db_path)
    ai = FakeAI(db_path)

    # Index the initial (short) file in full; coverage now == len(_INIT).
    n0 = index_source_range(cm, ai, str(ruta), "default", start=0)
    assert n0 > 0

    before = cm.query_text("donde esta el NEEDLE", embed_fn, budget_tokens=4000)
    assert all("NEEDLE" not in r["text"] for r in before)

    # The file grows on disk (new tail with the needle), but coverage is stale.
    ruta.write_text(_INIT + _NEEDLE_APPEND, encoding="utf-8")

    added = fill_gaps_ondisk(cm, ai, "default")
    assert added > 0

    res = cm.query_text("donde esta el NEEDLE", embed_fn, budget_tokens=4000)
    assert res
    assert any("NEEDLE" in r["text"] for r in res)


def test_fill_gaps_ondisk_skips_missing_file(tmp_path, db_path):
    cm = ContextMap(db_path=db_path)
    missing = str(tmp_path / "no_such_file.txt")
    cm.mark_coverage(missing, indexed_through=0, total_chars=100)

    added = fill_gaps_ondisk(cm, FakeAI(db_path), "default")

    assert added == 0

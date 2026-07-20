"""Cycle 2 — auto-build of ContextMap pointers during ingestion.

Verifies that ingesting a text file writes one lossless pointer per chunk
(re-readable by offset) and marks coverage, without touching the existing
episodic ingestion path.
"""

from cognia.context.context_map import ContextMap
from cognia.ingest import ingest_file, _chunk_text_with_offsets
from storage.db_pool import close_pool


class FakePerc:
    def extract_features(self, t):
        return {"vector": [0.0] * 8}


class FakeEpis:
    def store(self, *a, **k):
        pass


class FakeAI:
    def __init__(self, db):
        self.db = db
        self.perception = FakePerc()
        self.episodic = FakeEpis()


_MULTI = (
    "Primer parrafo de prueba con suficiente texto para no ser descartado por el filtro.\n\n"
    "Segundo parrafo que tambien tiene contenido relevante y mas de cuarenta caracteres aqui.\n\n"
    "Tercer parrafo lleva el DATO-UNICO-7741 escondido en el medio del documento de prueba.\n\n"
    "Cuarto parrafo final que cierra el documento con material adicional para los chunks."
)


def test_chunk_offsets_lossless():
    spans = _chunk_text_with_offsets(_MULTI)
    assert len(spans) >= 1
    for chunk_text, s, e in spans:
        assert chunk_text == _MULTI[s:e]
        assert s < e


def test_ingest_writes_lossless_pointers(tmp_path):
    db = str(tmp_path / "ingest_ptr.db")
    ruta = tmp_path / "doc.txt"
    ruta.write_text(_MULTI, encoding="utf-8")
    try:
        res = ingest_file(FakeAI(db), str(ruta))
        assert "error" not in res
        assert res["pointers"] >= 1

        text_original = ruta.read_text(encoding="utf-8", errors="replace")
        cm = ContextMap(db_path=db, project="documento:doc")
        ptrs = cm.pointers()
        assert len(ptrs) >= 1

        assert any("DATO-UNICO-7741" in (cm.resolve(p["id"]) or "") for p in ptrs)

        for p in ptrs:
            if p["source_kind"] == "file":
                assert cm.resolve(p["id"]) == \
                    text_original[p["char_start"]:p["char_end"]]
    finally:
        close_pool(db)


def test_ingest_marks_coverage(tmp_path):
    db = str(tmp_path / "ingest_cov.db")
    ruta = tmp_path / "doc.txt"
    ruta.write_text(_MULTI, encoding="utf-8")
    try:
        ingest_file(FakeAI(db), str(ruta))
        # resolve the same absolute path the ingester stored
        from pathlib import Path
        stored_ref = str(Path(str(ruta)).expanduser().resolve())
        cm = ContextMap(db_path=db, project="documento:doc")
        assert cm.uncovered(stored_ref) is None
    finally:
        close_pool(db)

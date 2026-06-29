import pytest

from cognia.context.context_map import ContextMap
from storage.db_pool import close_pool


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "ctxmap_test.db")
    yield path
    close_pool(path)


def test_pointer_roundtrip_lossless(tmp_path, db_path):
    content = "linea uno\n\nDATO: zafiro-42\n\nlinea tres"
    ruta = tmp_path / "doc.txt"
    ruta.write_text(content, encoding="utf-8")

    start = content.index("DATO")
    end = start + len("DATO: zafiro-42")

    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("file", str(ruta), char_start=start, char_end=end)

    assert cm.resolve(pid) == content[start:end] == "DATO: zafiro-42"


def test_inline_text_pointer(db_path):
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("text", source_ref="", inline_text="contenido inline")
    assert cm.resolve(pid) == "contenido inline"


def test_msg_pointer_placeholder(db_path):
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("msg", source_ref="7", char_start=0, char_end=5)
    assert cm.resolve(pid) is None


def test_coverage_and_uncovered(db_path):
    cm = ContextMap(db_path=db_path)
    cm.mark_coverage("/x", indexed_through=100, total_chars=300)
    assert cm.uncovered("/x") == (100, 300)
    cm.mark_coverage("/x", 300, 300)
    assert cm.uncovered("/x") is None


def test_schema_idempotent(db_path):
    ContextMap(db_path=db_path)
    ContextMap(db_path=db_path)


def test_resolve_missing_file_returns_none(db_path):
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("file", "/no/existe", char_start=0, char_end=10)
    assert cm.resolve(pid) is None

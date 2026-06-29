"""Cycle 5 — resolve('msg') reads chat_history, record_message builds the
context memory as the conversation advances, and write_markdown emits the
ASCII pointer index (cognia_context.md).

Deterministic: a FakeAI provides a fixed embedding, no real model involved.
"""

import pytest

from cognia.context.context_map import ContextMap
from cognia.context.context_session import record_message
from storage.db_pool import get_pool, close_pool


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "ctxsession_test.db")
    yield path
    close_pool(path)


def _make_chat_history(db, rows):
    """Create the minimal chat_history table and insert (id, role, content) rows
    via the SAME pooled connection ContextMap uses."""
    with get_pool(db).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, "
            "timestamp REAL, cwd TEXT)"
        )
        for rid, role, content in rows:
            conn.execute(
                "INSERT INTO chat_history (id, role, content) VALUES (?,?,?)",
                (rid, role, content),
            )


class _FakePerception:
    def extract_features(self, text):
        return {"vector": [1.0, 0.0]}


class FakeAI:
    def __init__(self, db):
        self.db = db
        self.perception = _FakePerception()


def test_resolve_msg_reads_chat_history(db_path):
    _make_chat_history(db_path, [(5, "user", "hola mundo de prueba")])
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("msg", "5")
    assert cm.resolve(pid) == "hola mundo de prueba"


def test_resolve_msg_with_offsets(db_path):
    _make_chat_history(db_path, [(5, "user", "hola mundo de prueba")])
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("msg", "5", char_start=0, char_end=4)
    assert cm.resolve(pid) == "hola"


def test_resolve_msg_missing_returns_none(db_path):
    _make_chat_history(db_path, [(5, "user", "hola mundo de prueba")])
    cm = ContextMap(db_path=db_path)
    pid = cm.add_pointer("msg", "999")  # id ausente en chat_history
    assert cm.resolve(pid) is None


def test_resolve_msg_no_table_returns_none(tmp_path):
    db = str(tmp_path / "no_chat_history.db")
    cm = ContextMap(db_path=db)  # esta DB no tiene tabla chat_history
    pid = cm.add_pointer("msg", "5")
    assert cm.resolve(pid) is None
    close_pool(db)


def test_record_message(db_path):
    cm = ContextMap(db_path=db_path)
    pid = record_message(cm, FakeAI(db_path), 5, "contenido")
    assert pid is not None
    p = [r for r in cm.pointers() if r["id"] == pid][0]
    assert p["source_kind"] == "msg"
    assert p["source_ref"] == "5"
    assert p["vector"] is not None
    assert p["summary"].startswith("contenido")


def test_write_markdown_ascii(db_path, tmp_path):
    cm = ContextMap(db_path=db_path)
    cm.add_pointer("file", "/ruta/doc.txt", char_start=0, char_end=10,
                   summary="primer span de archivo")
    cm.add_pointer("text", "", inline_text="algo", summary="span inline")
    cm.add_pointer("msg", "5", summary="mensaje de chat")

    out = cm.write_markdown(str(tmp_path / "cognia_context.md"))

    from pathlib import Path
    contenido = Path(out).read_text(encoding="utf-8")
    assert Path(out).exists()
    assert "Mapa de contexto" in contenido
    assert "primer span de archivo" in contenido
    assert all(ord(c) < 128 for c in contenido)

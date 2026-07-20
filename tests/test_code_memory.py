"""
tests/test_code_memory.py
=========================
Direct tests for cognia_v3.memory.code_memory.CodeMemory (PRODUCTION module,
imported by cognia_v3/interfaces/respuestas_articuladas.py). It had no test
coverage; this file adds it so the db_pool migration (FASE 0b) is verified.

Uses a temp FILE db (NOT ':memory:' — pooled connections to ':memory:' would
each be a separate in-memory database). Teardown closes the pool before unlink
so Windows can delete the file once the migration keeps eager pool handles open.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia_v3.memory.code_memory import CodeMemory
from storage.db_pool import close_pool


def _unlink_db(path: str) -> None:
    try:
        _c = sqlite3.connect(path)
        _c.execute("PRAGMA wal_checkpoint(FULL)")
        _c.execute("PRAGMA journal_mode=DELETE")
        _c.close()
    except Exception:
        pass
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


@pytest.fixture()
def cm():
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    path = tf.name
    memory = CodeMemory(path)        # __init__ runs _init_tables (executescript DDL)
    yield memory, path
    close_pool(path)
    _unlink_db(path)


def test_save_and_count_snippet(cm):
    memory, _ = cm
    sid = memory.save_snippet("def suma(a,b): return a+b", "python",
                              "suma basica", ["aritmetica"], worked=True)
    assert sid > 0
    stats = memory.count()
    assert stats["snippets"] >= 1
    assert stats["by_language"].get("python", 0) >= 1


def test_save_project_upsert(cm):
    memory, _ = cm
    pid1 = memory.save_project("app", "/p", ["python", "flask"], "desc")
    pid2 = memory.save_project("app", "/p2", ["python"], "desc2")  # same name -> update
    assert pid1 > 0
    assert pid1 == pid2          # upsert keeps the same id
    assert memory.count()["projects"] == 1


def test_save_and_search_error(cm):
    memory, _ = cm
    eid = memory.save_error("NameError: name 'x' is not defined", "linea 5",
                            "declarar la variable antes de usarla")
    assert eid > 0
    hits = memory.search_errors("NameError variable not defined")
    assert len(hits) >= 1
    assert "declarar" in hits[0].solution


def test_search_snippets_by_language(cm):
    memory, _ = cm
    memory.save_snippet("for i in range(10): print(i)", "python",
                        "loop basico", ["loops"], worked=True)
    memory.save_snippet("<ul><li>x</li></ul>", "html", "lista html",
                        ["html"], worked=True)
    py = memory.search_snippets("loop", language="python", top_k=5)
    assert len(py) >= 1
    assert all(s.language == "python" for s in py)


def test_context_for_prompt_nonempty(cm):
    memory, _ = cm
    memory.save_snippet("def fact(n): return 1 if n<=1 else n*fact(n-1)",
                        "python", "factorial recursivo", ["recursion"])
    ctx = memory.get_context_for_prompt("como hacer una funcion recursiva en python")
    assert ctx
    assert "factorial" in ctx or "recursion" in ctx or "SNIPPET" in ctx.upper()


def test_update_snippet_feedback(cm):
    memory, path = cm
    sid = memory.save_snippet("x=1", "python", "asignacion", worked=True)
    memory.update_snippet_feedback(sid, 0.5)
    _c = sqlite3.connect(path)
    score = _c.execute("SELECT feedback_score FROM code_snippets WHERE id=?",
                       (sid,)).fetchone()[0]
    _c.close()
    assert score == pytest.approx(1.5)   # 1.0 default + 0.5 delta

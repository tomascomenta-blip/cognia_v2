"""
tests/test_fase6_deep.py
========================
FASE 6 deep:
  (a) recap injection — _build_stream_messages injects the auto-maintained
      _session_recap into the LAST user message (KV-cache-safe slot), "" => no-op.
  (b) ProjectMemory — db_pool-backed persistent flow state (O2 "proyectos" level).
  (c) run_flow records its flow state for cross-session resume.
"""

import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.db_pool import close_pool


def _unlink(path):
    try:
        _c = sqlite3.connect(path)
        _c.execute("PRAGMA wal_checkpoint(FULL)")
        _c.execute("PRAGMA journal_mode=DELETE")
        _c.close()
    except Exception:
        pass
    for s in ("", "-wal", "-shm"):
        try:
            os.unlink(path + s)
        except FileNotFoundError:
            pass


@pytest.fixture()
def dbpath(tmp_path):
    p = str(tmp_path / "proj.db")
    yield p
    close_pool(p)
    _unlink(p)


# ── (a) recap injection ──────────────────────────────────────────────

def test_recap_injected_into_last_user_message(monkeypatch):
    import cognia.cli as cli
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "")
    monkeypatch.setattr(cli, "_session_recap", "RESUMEN: hablamos de X e Y")
    msgs = cli._build_stream_messages(object(), "mi pregunta", "sys", [])
    last = msgs[-1]["content"]
    assert "RESUMEN: hablamos de X e Y" in last
    assert last.endswith("Pregunta: mi pregunta")
    assert msgs[0] == {"role": "system", "content": "sys"}


def test_no_recap_when_empty(monkeypatch):
    import cognia.cli as cli
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "")
    monkeypatch.setattr(cli, "_session_recap", "")
    msgs = cli._build_stream_messages(object(), "mi pregunta", "sys", [])
    assert msgs[-1]["content"] == "mi pregunta"     # zero overhead


def test_recap_and_memory_both_injected_history_preserved(monkeypatch):
    import cognia.cli as cli
    monkeypatch.setattr(cli, "_build_memory_block_for", lambda ai, q: "MEMBLOCK")
    monkeypatch.setattr(cli, "_session_recap", "RECAP")
    hist = [{"role": "user", "content": "h1"}, {"role": "assistant", "content": "a1"}]
    msgs = cli._build_stream_messages(object(), "q", "sys", hist)
    last = msgs[-1]["content"]
    assert "RECAP" in last and "MEMBLOCK" in last
    # history prefix byte-identical (KV-cache safety)
    assert msgs[1:3] == hist


# ── (b) ProjectMemory ────────────────────────────────────────────────

def test_project_memory_lifecycle(dbpath):
    from cognia.memory.project_memory import ProjectMemory
    pm = ProjectMemory(dbpath)
    fid = pm.start_flow("refactor memoria", ["analisis", "plan", "ejecucion", "informe"])
    assert fid > 0

    pm.mark_stage(fid, "analisis")
    pm.mark_stage(fid, "plan")
    pm.mark_stage(fid, "plan")        # idempotent

    pend = pm.latest_unfinished()
    assert pend is not None and pend["id"] == fid
    assert pend["status"] == "running"
    assert pend["stages_done"] == ["analisis", "plan"]   # no dupes

    pm.finish_flow(fid, report="informe final", score=0.83, status="done")
    done = pm.get_flow(fid)
    assert done["status"] == "done"
    assert done["report"] == "informe final"
    assert done["score"] == pytest.approx(0.83)
    assert pm.latest_unfinished() is None                # nothing running now
    assert any(f["id"] == fid for f in pm.recent(5))


# ── (c) run_flow persists flow state ─────────────────────────────────

class _FakeInfer:
    def __init__(self, text):
        self.text = text


class _FakeOrch:
    def infer(self, prompt, lpc_session_id=None, max_tokens=None, temperature=None):
        return _FakeInfer("Informe sintetizado del flujo.")


class _FakeAI:
    def __init__(self, db):
        self.db = db                  # real path -> run_flow persists
        self._orchestrator = _FakeOrch()


def test_run_flow_persists_to_project_memory(dbpath):
    from cognia.agents.flow import run_flow
    from cognia.memory.project_memory import ProjectMemory
    from cognia.effort_levels import get_effort

    report = run_flow(_FakeAI(dbpath), "que es una lista enlazada",
                      get_effort("bajo"), print_fn=lambda *_: None)
    assert report and "flujo" in report

    pm = ProjectMemory(dbpath)
    flows = pm.recent(5)
    assert len(flows) == 1
    f = flows[0]
    assert f["status"] == "done"
    assert f["goal"] == "que es una lista enlazada"
    # 'analisis' + the chosen route were all marked
    assert "analisis" in f["stages_done"]
    assert "informe" in f["stages_done"]
    assert set(f["route"]) <= set(f["stages_done"]) | {"analisis"}

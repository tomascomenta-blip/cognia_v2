"""
tests/test_self_architect_codegen.py
====================================
FASE 7c: SelfArchitect.generate_module_code rewired from Ollama (NO-OP with the
real backend) to ShatteringOrchestrator.infer (llama.cpp), keeping the skeleton
fallback when no backend is available, and dropping the hardcoded 'llama3.2'.

These tests inject a FAKE orchestrator (deterministic, no model load) to verify the
wiring: budget threading (max_tokens/temperature), markdown stripping, code persisted,
resolution from the injected ctor arg AND from the cognia instance's _orchestrator,
and the skeleton fallback path. A real-model E2E is run separately (see MANAGER_LOG).
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia_v3.core.self_architect import SelfArchitect, CODEGEN_MAX_TOKENS
from storage.db_pool import close_pool


class _FakeResult:
    def __init__(self, text, sub_model="techne", mode="local"):
        self.text = text
        self.sub_model = sub_model
        self.mode = mode
        self.confidence = 0.9
        self.latency_ms = 1.0
        self.route_reason = "test"
        self.tokens_generated = len(text.split())


class _FakeOrch:
    """Stand-in for ShatteringOrchestrator: records calls, returns canned text."""
    def __init__(self, text):
        self._text = text
        self.calls = []

    def infer(self, prompt, lpc_session_id=None, max_tokens=None, temperature=None):
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens,
                           "temperature": temperature})
        return _FakeResult(self._text)


class _FakeCognia:
    def __init__(self, orch):
        self._orchestrator = orch


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
def db(tmp_path):
    path = str(tmp_path / "arch.db")
    yield path
    close_pool(path)
    _unlink(path)


def _insert_new_module_proposal(db_path, title="New module: WidgetEngine"):
    """Insert a minimal new_module proposal directly; return its id."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        INSERT INTO architecture_proposals
        (timestamp, diagnosis_key, proposal_type, title, problem, modification,
         why_better, risks, impact)
        VALUES (?, ?, 'new_module', ?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), "diag1", title,
          "necesitamos X", "agregar modulo X", "mejora Y", "bajo", "alto"))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def _stored(db_path, pid):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT generated_code, status FROM architecture_proposals WHERE id=?",
        (pid,)).fetchone()
    conn.close()
    return row


# ─────────────────────────────────────────────────────────────────────

def test_uses_injected_orchestrator_and_threads_budget(db):
    code = "class WidgetEngine:\n    def status_report(self): return 'ok'\n"
    orch = _FakeOrch(code)
    arch = SelfArchitect(db_path=db, orchestrator=orch)
    pid = _insert_new_module_proposal(db)

    res = arch.generate_module_code(pid)

    assert res["status"] == "code_generated"
    assert res["backend_used"] is True
    assert res["sub_model"] == "techne"
    assert res["generation_error"] is None
    # budget threaded to infer (replaces the old Ollama num_predict=1200)
    assert orch.calls and orch.calls[0]["max_tokens"] == CODEGEN_MAX_TOKENS
    assert orch.calls[0]["temperature"] == 0.3
    # code persisted
    stored_code, status = _stored(db, pid)
    assert status == "code_generated"
    assert "class WidgetEngine" in stored_code


def test_strips_markdown_fences(db):
    fenced = "```python\nclass WidgetEngine:\n    pass\n```"
    arch = SelfArchitect(db_path=db, orchestrator=_FakeOrch(fenced))
    pid = _insert_new_module_proposal(db)

    arch.generate_module_code(pid)

    stored_code, _ = _stored(db, pid)
    assert "```" not in stored_code
    assert stored_code.strip().startswith("class WidgetEngine")


def test_resolves_orchestrator_from_cognia_instance(db):
    code = "class WidgetEngine:\n    pass\n"
    arch = SelfArchitect(db_path=db, cognia_instance=_FakeCognia(_FakeOrch(code)))
    pid = _insert_new_module_proposal(db)

    res = arch.generate_module_code(pid)

    assert res["status"] == "code_generated"
    assert res["backend_used"] is True


def test_skeleton_fallback_when_no_backend(db):
    arch = SelfArchitect(db_path=db)             # no orchestrator, no cognia
    pid = _insert_new_module_proposal(db)

    res = arch.generate_module_code(pid)

    assert res["status"] == "code_skeleton"
    assert res["backend_used"] is False
    assert res["generation_error"]
    stored_code, status = _stored(db, pid)
    assert status == "code_skeleton"
    assert "esqueleto" in stored_code
    assert "class WidgetEngine" in stored_code      # skeleton still valid scaffold


def test_skeleton_fallback_when_empty_inference(db):
    arch = SelfArchitect(db_path=db, orchestrator=_FakeOrch(""))   # empty text
    pid = _insert_new_module_proposal(db)

    res = arch.generate_module_code(pid)

    assert res["status"] == "code_skeleton"
    assert res["backend_used"] is False
    assert "vacia" in res["generation_error"]

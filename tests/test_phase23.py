"""
tests/test_phase23.py — Phase 23: Supervisor + TaskQueue + Verifier
"""

import os
import tempfile
import time

import pytest

from cognia.agents.task_queue import (
    TaskQueue, TaskRecord, CREATED, PLANNING, EXECUTING, DONE, FAILED, ABORTED,
    MAX_RECOVERY_ATTEMPTS,
)
from cognia.agents.verifier import verify, VerifyResult, SCORE_THRESHOLD
from cognia.agents.supervisor import CogniaAgentRuntime


# ── TaskQueue ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    path = str(tmp_path / "test_agents.db")
    yield path
    from storage.db_pool import close_pool
    close_pool(path)   # libera handles del pool para que Windows pueda borrar tmp


class TestTaskQueue:
    def test_submit_returns_task_id(self, tmp_db):
        tq = TaskQueue(tmp_db)
        tid = tq.submit("test task")
        assert isinstance(tid, str) and len(tid) > 0

    def test_pop_returns_task(self, tmp_db):
        tq = TaskQueue(tmp_db)
        tid = tq.submit("task A")
        record = tq.pop()
        assert record is not None
        assert record.task_id == tid

    def test_pop_empty_returns_none(self, tmp_db):
        tq = TaskQueue(tmp_db)
        assert tq.pop() is None

    def test_priority_order(self, tmp_db):
        tq = TaskQueue(tmp_db)
        tq.submit("low priority", priority=0.1)
        tq.submit("high priority", priority=1.0)
        tq.submit("medium priority", priority=0.5)
        first = tq.pop()
        assert first.priority == 1.0

    def test_status_transitions(self, tmp_db):
        tq = TaskQueue(tmp_db)
        tid = tq.submit("test")
        tq.update_status(tid, DONE, result="ok")
        record = tq.get(tid)
        assert record.status == DONE
        assert record.result == "ok"

    def test_increment_attempts(self, tmp_db):
        tq = TaskQueue(tmp_db)
        tid = tq.submit("test")
        assert tq.increment_attempts(tid) == 1
        assert tq.increment_attempts(tid) == 2

    def test_pending_count(self, tmp_db):
        tq = TaskQueue(tmp_db)
        assert tq.pending_count() == 0
        tq.submit("a")
        tq.submit("b")
        assert tq.pending_count() == 2

    def test_reload_pending_on_restart(self, tmp_db):
        tq1 = TaskQueue(tmp_db)
        tid = tq1.submit("surviving task", priority=1.0)
        # Simular restart sin pop (task queda en CREATED)
        tq2 = TaskQueue(tmp_db)
        assert tq2.pending_count() == 1
        record = tq2.pop()
        assert record.task_id == tid

    def test_recover_resets_interrupted_task(self, tmp_db):
        """Una tarea colgada en EXECUTING tras crash se resetea a CREATED + attempts+1
        y vuelve a estar disponible al recrear la queue (recovery real)."""
        tq1 = TaskQueue(tmp_db)
        tid = tq1.submit("interrupted task", priority=1.0)
        tq1.update_status(tid, EXECUTING)       # simula crash a mitad de ejecucion
        tq2 = TaskQueue(tmp_db)                  # restart -> recover() en __init__
        rec = tq2.get(tid)
        assert rec.status == CREATED            # estado colgado reseteado en disco
        assert rec.attempts == 1                # recover conto el reintento
        assert tq2.pending_count() == 1         # re-encolada en _mem
        assert tq2.pop().task_id == tid         # extraible de nuevo

    def test_recover_aborts_after_max_retries(self, tmp_db):
        """Tras superar MAX_RECOVERY_ATTEMPTS, una tarea interrumpida se marca ABORTED
        en vez de re-encolarse para siempre (corta el loop de crash)."""
        tq = TaskQueue(tmp_db)
        tid = tq.submit("crash loop", priority=1.0)
        for _ in range(MAX_RECOVERY_ATTEMPTS):
            tq.increment_attempts(tid)          # lleva attempts al tope
        tq.update_status(tid, EXECUTING)
        tq2 = TaskQueue(tmp_db)                  # recover() -> supera el tope
        rec = tq2.get(tid)
        assert rec.status == ABORTED
        assert tq2.pending_count() == 0         # no se re-encola

    def test_save_subtasks_persist(self, tmp_db):
        from cognia.agents.planner import SubTask
        tq = TaskQueue(tmp_db)
        tid = tq.submit("task with subtasks")
        subtasks = [
            SubTask(id=f"{tid}_explore", description="explore", tool_required="file_explorer"),
            SubTask(id=f"{tid}_synthesize", description="synthesize", tool_required="synthesize",
                    dependencies=[f"{tid}_explore"]),
        ]
        tq.save_subtasks(subtasks)
        # Verificar que quedaron en la DB
        with tq._conn() as conn:
            rows = conn.execute("SELECT subtask_id FROM agent_subtasks WHERE task_id=?",
                                (tid,)).fetchall()
        assert len(rows) == 2

    def test_does_not_share_data_with_cognia_memory_db(self, tmp_db):
        tq = TaskQueue(tmp_db)
        assert not os.path.exists("cognia_memory.db") or tmp_db != "cognia_memory.db"
        assert "cognia_memory" not in tmp_db


# ── Verifier ──────────────────────────────────────────────────────────────────

class TestVerifier:
    # ── código ──────────────────────────────────────────────────────────────
    def test_valid_code_passes(self):
        result = verify("x = 1 + 1\nprint(x)", output_type="code")
        assert result.passed is True
        assert result.score > SCORE_THRESHOLD

    def test_syntax_error_fails(self):
        result = verify("def foo(:\n    pass", output_type="code")
        assert result.passed is False
        assert "SYNTAX_ERROR" in result.fail_reason

    def test_blocked_import_fails(self):
        result = verify("import subprocess\nprint('hi')", output_type="code")
        assert result.passed is False

    def test_empty_code_fails(self):
        result = verify("", output_type="code")
        assert result.passed is False

    # ── texto ────────────────────────────────────────────────────────────────
    def test_text_too_short_fails(self):
        result = verify("ok", output_type="text")
        assert result.passed is False
        assert "TOO_SHORT" in result.fail_reason

    def test_text_sufficient_length_passes(self):
        result = verify("This is a sufficiently long response about a topic.", output_type="text")
        assert result.passed is True

    def test_text_none_fails(self):
        result = verify(None, output_type="text")
        assert result.passed is False

    # ── genérico ────────────────────────────────────────────────────────────
    def test_generic_none_fails(self):
        result = verify(None, output_type="generic")
        assert result.passed is False
        assert "NONE_OUTPUT" in result.fail_reason

    def test_generic_empty_fails(self):
        result = verify("   ", output_type="generic")
        assert result.passed is False

    def test_generic_any_content_passes(self):
        result = verify({"key": "value"}, output_type="generic")
        assert result.passed is True

    def test_verify_result_has_score(self):
        result = verify("print('hello')", output_type="code")
        assert 0.0 <= result.score <= 1.0

    def test_fail_reason_is_none_when_passed(self):
        result = verify("print(42)", output_type="code")
        assert result.passed is True
        assert result.fail_reason is None


# ── CogniaAgentRuntime ────────────────────────────────────────────────────────

class TestCogniaAgentRuntime:
    def test_submit_returns_task_id(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        tid = runtime.submit("investiga qué es Python")
        assert isinstance(tid, str)

    def test_pending_count(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        assert runtime.pending() == 0
        runtime.submit("task 1")
        runtime.submit("task 2")
        assert runtime.pending() == 2

    def test_tick_processes_one_task(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        tid = runtime.submit("ejecuta x = 1 + 1")
        result_id = runtime.tick()
        assert result_id == tid

    def test_tick_empty_queue_returns_none(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        assert runtime.tick() is None

    def test_task_reaches_terminal_state(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        tid = runtime.submit("ejecuta x = 2 + 2")
        runtime.tick()
        record = runtime.status(tid)
        assert record.status in {DONE, FAILED, ABORTED}

    def test_status_returns_none_for_unknown(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        assert runtime.status("nonexistent-id") is None

    def test_time_budget_respected(self, tmp_db):
        from cognia.agents import supervisor as sv_mod
        original = sv_mod.TIME_BUDGET_SECONDS
        sv_mod.TIME_BUDGET_SECONDS = 0   # forzar timeout inmediato
        try:
            runtime = CogniaAgentRuntime(db_path=tmp_db)
            tid = runtime.submit("investiga qué es Python")
            runtime.tick()
            record = runtime.status(tid)
            assert record.status == ABORTED
        finally:
            sv_mod.TIME_BUDGET_SECONDS = original

    def test_research_task_completes(self, tmp_db):
        runtime = CogniaAgentRuntime(db_path=tmp_db)
        tid = runtime.submit("investiga qué es el teorema de Pitágoras")
        runtime.tick()
        record = runtime.status(tid)
        # Puede ser DONE o FAILED (si Wikipedia no está disponible en tests)
        assert record.status in {DONE, FAILED, ABORTED}
        assert record.result is not None

    def test_executor_error_marks_failed_not_dangling(self, tmp_db, monkeypatch):
        """Regresión: una excepción no controlada en el cuerpo del executor debe
        dejar la tarea en FAILED (estado terminal) y NO propagarse hasta tick()/daemon."""
        from cognia.agents import supervisor as sv_mod

        def _boom(*a, **k):
            raise RuntimeError("planner exploded")

        monkeypatch.setattr(sv_mod, "plan_task", _boom)

        runtime = CogniaAgentRuntime(db_path=tmp_db)
        tid = runtime.submit("tarea que rompe el planner")
        # tick() no debe lanzar pese a la excepción interna
        result_id = runtime.tick()
        assert result_id == tid
        record = runtime.status(tid)
        assert record.status == FAILED
        assert "EXECUTOR_ERROR" in (record.result or "")
        assert "planner exploded" in (record.result or "")

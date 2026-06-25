"""
tests/test_phase25.py — Phase 25: AgentDaemon
"""

import os
import time
import tempfile
from pathlib import Path

import pytest

from cognia.agents.daemon import (
    AgentDaemon,
    get_fatigue_score,
    _changed_paths,
    PAUSE_THRESHOLD,
    SLOW_THRESHOLD,
    NORMAL_INTERVAL,
    SLOW_INTERVAL,
    FS_POLL_INTERVAL,
)
from cognia.agents.task_queue import DONE, FAILED, ABORTED


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "agents_test.db")


@pytest.fixture
def daemon(tmp_db):
    return AgentDaemon(db_path=tmp_db)


# ── tick() throttle por fatiga ────────────────────────────────────────────────

class TestTickFatigue:
    def test_tick_does_nothing_when_user_active(self, daemon):
        tid = daemon.submit("test task")
        result = daemon.tick(fatigue_score=0.0, user_active=True)
        assert result is None

    def test_tick_does_nothing_above_pause_threshold(self, daemon):
        daemon.submit("test task")
        result = daemon.tick(fatigue_score=PAUSE_THRESHOLD, user_active=False)
        assert result is None

    def test_tick_does_nothing_at_max_fatigue(self, daemon):
        daemon.submit("test task")
        result = daemon.tick(fatigue_score=100.0, user_active=False)
        assert result is None

    def test_tick_processes_task_below_pause_threshold(self, daemon):
        tid = daemon.submit("analiza el archivo cognia_idle.py")
        result = daemon.tick(fatigue_score=0.0, user_active=False)
        assert result == tid

    def test_tick_throttled_by_normal_interval(self, daemon):
        tid = daemon.submit("task A")
        # First tick fires
        r1 = daemon.tick(fatigue_score=0.0, user_active=False)
        assert r1 is not None
        # Second tick immediately after is throttled
        daemon.submit("task B")
        r2 = daemon.tick(fatigue_score=0.0, user_active=False)
        assert r2 is None

    def test_tick_returns_none_when_no_pending(self, daemon):
        result = daemon.tick(fatigue_score=0.0, user_active=False)
        assert result is None

    def test_slow_interval_used_when_high_fatigue(self, daemon):
        """tick just below pause but above slow uses SLOW_INTERVAL."""
        tid = daemon.submit("task")
        r1 = daemon.tick(fatigue_score=SLOW_THRESHOLD + 1, user_active=False)
        assert r1 == tid
        # A second task should be throttled by SLOW_INTERVAL
        daemon.submit("task 2")
        r2 = daemon.tick(fatigue_score=SLOW_THRESHOLD + 1, user_active=False)
        assert r2 is None


# ── submit() / pending() / status() ──────────────────────────────────────────

class TestSubmitStatus:
    def test_submit_returns_task_id(self, daemon):
        tid = daemon.submit("descripción de tarea")
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_pending_increments_on_submit(self, daemon):
        assert daemon.pending() == 0
        daemon.submit("t1")
        assert daemon.pending() == 1
        daemon.submit("t2")
        assert daemon.pending() == 2

    def test_status_returns_record(self, daemon):
        tid = daemon.submit("some task")
        record = daemon.status(tid)
        assert record is not None
        assert record.task_id == tid

    def test_status_nonexistent_returns_none(self, daemon):
        assert daemon.status("nonexistent-id-xyz") is None


# ── FS Watcher ────────────────────────────────────────────────────────────────

class TestFsWatcher:
    def test_watcher_starts_and_stops(self, daemon, tmp_path):
        daemon.start_fs_watcher(str(tmp_path))
        assert daemon._watcher_thread is not None
        assert daemon._watcher_thread.is_alive()
        daemon.stop_fs_watcher()
        assert daemon._watcher_thread is None

    def test_start_fs_watcher_idempotent(self, daemon, tmp_path):
        daemon.start_fs_watcher(str(tmp_path))
        t1 = daemon._watcher_thread
        daemon.start_fs_watcher(str(tmp_path))
        assert daemon._watcher_thread is t1  # same thread, not replaced
        daemon.stop_fs_watcher()

    def test_watcher_enqueues_task_on_file_change(self, daemon, tmp_path):
        py_file = tmp_path / "module.py"
        py_file.write_text("x = 1\n")

        daemon.start_fs_watcher(str(tmp_path))
        # Wait for initial snapshot
        time.sleep(FS_POLL_INTERVAL + 0.5)

        py_file.write_text("x = 2\n")
        # Wait for change detection
        time.sleep(FS_POLL_INTERVAL + 0.5)

        daemon.stop_fs_watcher()
        assert daemon.pending() >= 1

    def test_watcher_deduplicates_per_path(self, daemon, tmp_path):
        py_file = tmp_path / "dup.py"
        py_file.write_text("a = 1\n")

        daemon.start_fs_watcher(str(tmp_path))
        time.sleep(FS_POLL_INTERVAL + 0.5)

        # Modify file twice rapidly
        py_file.write_text("a = 2\n")
        time.sleep(0.1)
        py_file.write_text("a = 3\n")
        time.sleep(FS_POLL_INTERVAL + 0.5)

        daemon.stop_fs_watcher()
        # Should only enqueue once (deduplicated)
        assert daemon.pending() == 1

    def test_watcher_ignores_nonexistent_path(self, daemon):
        daemon.start_fs_watcher("/nonexistent/path/xyz")
        time.sleep(FS_POLL_INTERVAL + 0.2)
        daemon.stop_fs_watcher()
        assert daemon.pending() == 0


class TestChangedPaths:
    """Detección de cambios determinista (función pura, sin hilos/timing)."""

    def test_unseen_file_not_reported_on_startup(self):
        # Archivo nunca visto → no se analiza (evita analizar todo el dir al arrancar)
        assert _changed_paths({"a.py": 1.0}, {}, {}) == []

    def test_modified_file_reported_once(self):
        prev = {"a.py": 1.0}
        cur  = {"a.py": 2.0}
        assert _changed_paths(cur, prev, {}) == ["a.py"]

    def test_same_version_not_requeued(self):
        # Ya encolado en mtime 2.0 → no re-encolar la misma versión
        prev = {"a.py": 1.0}
        cur  = {"a.py": 2.0}
        assert _changed_paths(cur, prev, {"a.py": 2.0}) == []

    def test_second_modification_retriggers(self):
        # REGRESIÓN del bug: un archivo ya analizado que cambia de nuevo (mtime nuevo)
        # DEBE re-dispararse. El set permanente anterior lo suprimía para siempre.
        prev = {"a.py": 2.0}          # snapshot tras el primer análisis
        cur  = {"a.py": 3.0}          # segunda modificación
        submitted = {"a.py": 2.0}     # ya se encoló la versión 2.0
        assert _changed_paths(cur, prev, submitted) == ["a.py"]

    def test_unchanged_file_not_reported(self):
        prev = {"a.py": 2.0}
        cur  = {"a.py": 2.0}
        assert _changed_paths(cur, prev, {"a.py": 2.0}) == []


# ── get_fatigue_score ─────────────────────────────────────────────────────────

class TestGetFatigueScore:
    def test_returns_zero_for_none(self):
        assert get_fatigue_score(None) == 0.0

    def test_returns_zero_for_object_without_monitor(self):
        class FakeCognia:
            pass
        assert get_fatigue_score(FakeCognia()) == 0.0

    def test_returns_score_from_monitor(self):
        class FakeMonitor:
            score = 55.0
        class FakeCognia:
            fatigue_monitor = FakeMonitor()
        assert get_fatigue_score(FakeCognia()) == 55.0

    def test_handles_bad_score_gracefully(self):
        class FakeMonitor:
            score = "not_a_number"
        class FakeCognia:
            fatigue_monitor = FakeMonitor()
        assert get_fatigue_score(FakeCognia()) == 0.0


# ── Integration: tick processes a real task ───────────────────────────────────

class TestDaemonIntegration:
    def test_full_cycle_analyze_file(self, tmp_path, tmp_db):
        py_file = tmp_path / "sample.py"
        py_file.write_text("def add(a, b):\n    return a + b\n")

        d = AgentDaemon(db_path=tmp_db)
        tid = d.submit(f"analiza el archivo {py_file}")
        result = d.tick(fatigue_score=0.0, user_active=False)
        assert result == tid

        record = d.status(tid)
        assert record is not None
        assert record.status in {DONE, FAILED, ABORTED}

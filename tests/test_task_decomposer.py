"""
tests/test_task_decomposer.py
==============================
Tests for TaskDecomposer — deterministic goal decomposition.
No LLM calls, no external services required.
"""

from __future__ import annotations

import os
import tempfile
import time
import pytest

# ── Helpers ───────────────────────────────────────────────────────────


def _make_decomposer(db_path: str):
    """Create a TaskDecomposer wired to a temp DB that already has user_goals."""
    from storage.db_pool import get_pool
    with get_pool(db_path).get() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_goals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                title        TEXT    NOT NULL,
                description  TEXT    NOT NULL DEFAULT '',
                status       TEXT    NOT NULL DEFAULT 'active',
                progress_pct INTEGER NOT NULL DEFAULT 0,
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL,
                completed_at INTEGER
            )
            """
        )
    from cognia.goals.task_decomposer import TaskDecomposer
    return TaskDecomposer(db_path=db_path)


def _insert_goal(db_path: str, user_id: str, title: str) -> int:
    """Insert a goal directly and return its id."""
    from storage.db_pool import get_pool
    now = int(time.time())
    with get_pool(db_path).get() as conn:
        cur = conn.execute(
            "INSERT INTO user_goals (user_id, title, description, status, "
            "progress_pct, created_at, updated_at) VALUES (?, ?, '', 'active', 0, ?, ?)",
            (user_id, title, now, now),
        )
        return cur.lastrowid


# ── _detect_template ──────────────────────────────────────────────────

class TestDetectTemplate:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = self._tmp.name
        self._td = _make_decomposer(self._db)

    def teardown_method(self):
        from storage.db_pool import close_pool
        close_pool(self._db)
        try:
            os.unlink(self._db)
        except OSError:
            pass

    def test_aprender_spanish(self):
        key, topic = self._td._detect_template("Aprender Python")
        assert key == "aprender"
        assert "python" in topic

    def test_learn_english(self):
        key, topic = self._td._detect_template("Learn JavaScript")
        assert key == "learn"
        assert "javascript" in topic

    def test_crear_spanish(self):
        key, topic = self._td._detect_template("Crear una app de notas")
        assert key == "crear"
        assert topic  # not empty

    def test_build_english(self):
        key, topic = self._td._detect_template("Build a REST API")
        assert key == "build"
        assert "rest api" in topic or "a rest api" in topic

    def test_leer_spanish(self):
        key, topic = self._td._detect_template("Leer el libro de ML")
        assert key == "leer"

    def test_read_english(self):
        key, topic = self._td._detect_template("Read Clean Code")
        assert key == "read"

    def test_mejorar_spanish(self):
        key, topic = self._td._detect_template("Mejorar la velocidad del sitio")
        assert key == "mejorar"

    def test_improve_english(self):
        key, topic = self._td._detect_template("Improve test coverage")
        assert key == "improve"

    def test_default_fallback(self):
        key, topic = self._td._detect_template("tarea sin template")
        assert key == "_default"
        assert topic == "tarea sin template"

    def test_empty_topic_falls_back_to_esto(self):
        # "aprender" alone → topic is empty → should default to "esto"
        key, topic = self._td._detect_template("aprender")
        assert key == "aprender"
        assert topic == "esto"


# ── decompose ─────────────────────────────────────────────────────────

class TestDecompose:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = self._tmp.name
        self._td = _make_decomposer(self._db)

    def teardown_method(self):
        from storage.db_pool import close_pool
        close_pool(self._db)
        try:
            os.unlink(self._db)
        except OSError:
            pass

    def test_decompose_returns_non_empty_list(self):
        gid = _insert_goal(self._db, "alice", "Aprender Rust")
        result = self._td.decompose(gid, "alice")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_subtasks_have_parent_id(self):
        gid = _insert_goal(self._db, "alice", "Build a CLI tool")
        subtasks = self._td.decompose(gid, "alice")
        for s in subtasks:
            assert s["parent_id"] == gid

    def test_max_subtasks_limits_output(self):
        gid = _insert_goal(self._db, "alice", "Learn Go")
        subtasks = self._td.decompose(gid, "alice", max_subtasks=2)
        assert len(subtasks) <= 2

    def test_default_template_used_for_unknown_keyword(self):
        gid = _insert_goal(self._db, "alice", "Organizar el escritorio")
        subtasks = self._td.decompose(gid, "alice")
        assert len(subtasks) > 0
        # default template has 4 steps
        assert len(subtasks) <= 4

    def test_decompose_raises_for_missing_goal(self):
        with pytest.raises(ValueError, match="not found"):
            self._td.decompose(99999, "nobody")

    def test_subtasks_are_persisted_in_db(self):
        gid = _insert_goal(self._db, "bob", "Crear un blog")
        self._td.decompose(gid, "bob")
        from storage.db_pool import get_pool
        with get_pool(self._db).get() as conn:
            rows = conn.execute(
                "SELECT id FROM user_goals WHERE parent_id = ?", (gid,)
            ).fetchall()
        assert len(rows) > 0

    def test_topic_is_interpolated_in_titles(self):
        gid = _insert_goal(self._db, "alice", "Aprender Docker")
        subtasks = self._td.decompose(gid, "alice")
        titles = [s["title"].lower() for s in subtasks]
        # At least one step should mention "docker"
        assert any("docker" in t for t in titles)


# ── get_subtasks ──────────────────────────────────────────────────────

class TestGetSubtasks:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db = self._tmp.name
        self._td = _make_decomposer(self._db)

    def teardown_method(self):
        from storage.db_pool import close_pool
        close_pool(self._db)
        try:
            os.unlink(self._db)
        except OSError:
            pass

    def test_returns_list(self):
        gid = _insert_goal(self._db, "alice", "Learn Rust")
        result = self._td.get_subtasks(gid)
        assert isinstance(result, list)

    def test_empty_before_decompose(self):
        gid = _insert_goal(self._db, "alice", "something new")
        assert self._td.get_subtasks(gid) == []

    def test_returns_subtasks_after_decompose(self):
        gid = _insert_goal(self._db, "alice", "Build a web app")
        self._td.decompose(gid, "alice")
        subtasks = self._td.get_subtasks(gid)
        assert len(subtasks) > 0

    def test_each_subtask_has_required_keys(self):
        gid = _insert_goal(self._db, "alice", "Learn Python")
        self._td.decompose(gid, "alice")
        for s in self._td.get_subtasks(gid):
            for key in ("id", "user_id", "title", "status", "parent_id"):
                assert key in s, f"missing key: {key}"

    def test_non_existent_parent_returns_empty(self):
        result = self._td.get_subtasks(99999)
        assert result == []

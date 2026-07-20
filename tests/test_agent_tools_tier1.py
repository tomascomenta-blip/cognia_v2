"""
tests/test_agent_tools_tier1.py - Tier 1 dev tools (search/write/edit/run_tests)

Workspace de cada test = tmp_path, redirigiendo AGENT_WORKSPACE_ROOT con monkeypatch.
"""

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agents.workers.dev_tools import search_code, write_file, edit_file, run_tests
from cognia.agents.tool_registry import get_tool_registry


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


# -- search_code ---------------------------------------------------------------

class TestSearchCode:
    def test_finds_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("def needle_fn():\n    pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
        r = search_code(r"needle_fn", root=str(tmp_path))
        assert r["count"] == 1
        assert r["matches"][0]["line_no"] == 1
        assert "needle_fn" in r["matches"][0]["line"]
        assert r["matches"][0]["file"].endswith("a.py")

    def test_respects_ignore_dirs(self, tmp_path):
        for d in ("venv312", "__pycache__", ".git", "node_modules", "model_shards", "checkpoints"):
            sub = tmp_path / d
            sub.mkdir()
            (sub / "hidden.py").write_text("needle_fn = 1\n", encoding="utf-8")
        (tmp_path / "visible.py").write_text("needle_fn = 2\n", encoding="utf-8")
        r = search_code(r"needle_fn", root=str(tmp_path))
        assert r["count"] == 1
        assert r["matches"][0]["file"].endswith("visible.py")

    def test_respects_max_results(self, tmp_path):
        (tmp_path / "many.py").write_text("hit = 1\n" * 10, encoding="utf-8")
        r = search_code(r"hit", root=str(tmp_path), max_results=3)
        assert r["count"] == 3
        assert r["truncated"] is True

    def test_glob_filters_extension(self, tmp_path):
        (tmp_path / "notes.txt").write_text("needle in txt\n", encoding="utf-8")
        (tmp_path / "code.py").write_text("needle = 'py'\n", encoding="utf-8")
        r = search_code(r"needle", root=str(tmp_path))  # glob default *.py
        assert r["count"] == 1
        assert r["matches"][0]["file"].endswith("code.py")


# -- write_file ----------------------------------------------------------------

class TestWriteFile:
    def test_write_inside_workspace(self, workspace):
        r = write_file("ok.py", "x = 1\n")
        assert r["created"] is True
        assert r["backup"] is None
        assert (workspace / "ok.py").read_text(encoding="utf-8") == "x = 1\n"

    def test_invalid_python_rejected_not_written(self, workspace):
        with pytest.raises(ValueError, match="invalid Python"):
            write_file("bad.py", "def f(:\n    pass\n")
        assert not (workspace / "bad.py").exists()

    def test_path_traversal_blocked(self, workspace):
        with pytest.raises(ValueError, match="outside agent workspace"):
            write_file("../evil.txt", "pwned")
        assert not (workspace.parent / "evil.txt").exists()

    def test_absolute_path_outside_blocked(self, workspace, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside") / "evil.txt"
        with pytest.raises(ValueError, match="outside agent workspace"):
            write_file(str(outside), "pwned")
        assert not outside.exists()

    def test_env_blocked(self, workspace):
        with pytest.raises(ValueError, match="blocked file name"):
            write_file(".env", "TOKEN=abc")

    def test_secret_and_binaries_blocked(self, workspace):
        for name in ("my_secrets.txt", "tool.exe", "lib.dll"):
            with pytest.raises(ValueError, match="blocked file name"):
                write_file(name, "data")

    def test_git_dir_blocked(self, workspace):
        with pytest.raises(ValueError, match=r"\.git is blocked"):
            write_file(".git/config", "[core]")

    def test_backup_on_overwrite(self, workspace):
        write_file("v.py", "version = 1\n")
        r = write_file("v.py", "version = 2\n")
        assert r["created"] is False
        assert r["backup"].endswith("v.py.bak")
        assert (workspace / "v.py.bak").read_text(encoding="utf-8") == "version = 1\n"
        assert (workspace / "v.py").read_text(encoding="utf-8") == "version = 2\n"


# -- edit_file -----------------------------------------------------------------

class TestEditFile:
    def test_exact_replace(self, workspace):
        write_file("m.py", "a = 1\nb = 2\n")
        r = edit_file("m.py", "b = 2", "b = 99")
        assert r["replacements"] == 1
        assert (workspace / "m.py").read_text(encoding="utf-8") == "a = 1\nb = 99\n"

    def test_missing_old_string_reports_zero(self, workspace):
        write_file("m.py", "a = 1\n")
        with pytest.raises(ValueError, match="appears 0 times"):
            edit_file("m.py", "no_such_string", "x")

    def test_duplicate_old_string_reports_count(self, workspace):
        write_file("m.py", "x = 1\nx = 1\n")
        with pytest.raises(ValueError, match="appears 2 times"):
            edit_file("m.py", "x = 1", "x = 2", count=1)

    def test_backup_created(self, workspace):
        write_file("m.py", "a = 1\n")
        r = edit_file("m.py", "a = 1", "a = 2")
        assert r["backup"].endswith("m.py.bak")
        assert (workspace / "m.py.bak").read_text(encoding="utf-8") == "a = 1\n"

    def test_ast_invalid_result_rejected(self, workspace):
        write_file("m.py", "def f():\n    return 1\n")
        with pytest.raises(ValueError, match="invalid Python"):
            edit_file("m.py", "return 1", "return ((")
        # el original queda intacto
        assert (workspace / "m.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"

    def test_outside_workspace_blocked(self, workspace):
        with pytest.raises(ValueError, match="outside agent workspace"):
            edit_file("../other.py", "a", "b")


# -- run_tests -----------------------------------------------------------------

class TestRunTests:
    def test_passing_test_in_workspace(self, workspace):
        write_file("test_mini.py", "def test_ok():\n    assert 1 + 1 == 2\n")
        r = run_tests("test_mini.py")
        assert r["timed_out"] is False
        assert r["passed"] == 1
        assert r["failed"] == 0
        assert "passed" in r["summary_line"]

    def test_failing_test_in_workspace(self, workspace):
        write_file("test_fail.py", "def test_bad():\n    assert 1 == 2\n")
        r = run_tests("test_fail.py")
        assert r["failed"] == 1
        assert r["passed"] == 0

    def test_outside_workspace_blocked(self, workspace):
        with pytest.raises(ValueError, match="outside agent workspace"):
            run_tests("../../tests")


# -- registro en ToolRegistry ----------------------------------------------------

class TestRegistryIntegration:
    def test_tier1_tools_registered(self):
        reg = get_tool_registry()
        for name in ("search_code", "write_file", "edit_file", "run_tests"):
            assert name in reg.names()

    def test_registry_blocks_traversal_as_tool_result(self, workspace):
        reg = get_tool_registry()
        result = reg.execute("write_file", path="../evil.txt", content="x")
        assert result.success is False
        assert "outside agent workspace" in result.error

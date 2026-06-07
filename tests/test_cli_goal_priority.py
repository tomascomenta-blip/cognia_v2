"""
tests/test_cli_goal_priority.py
================================
Unit tests for /meta-prioridad, /metas-alta, /meta-prioridad-ver, /metas-ordenar
added to cognia/cli.py.
GoalTracker and filesystem I/O are mocked — no DB or file access required.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


# ---------------------------------------------------------------------------
# Cross-test isolation: this module stubs sys.modules entries (cognia.cognia,
# cognia.config, cognia.goals.goal_tracker, cognia.cli, rich.*) to import
# cognia.cli without heavy deps. Without restoring them, later test files
# inherit a MagicMock `Cognia`, a stub `cognia.config`, and a MagicMock
# GoalTracker — polluting test_phase9_security, test_context_injector and
# test_cli_synthesis. This autouse fixture snapshots and restores every key
# this file touches, so the leak cannot escape the module.
# ---------------------------------------------------------------------------

# Modules stubbed-and-restored. The "cognia.*" entries are pre-imported in the
# fixture so the REAL module is what gets restored on teardown (popping them
# would leave a stale `web_app` whose `from cognia import Cognia` resolves to a
# MagicMock and crashes JSON serialization in test_phase9_security).
_REAL_MODULE_KEYS = (
    "cognia.cognia",
    "cognia.config",
    "cognia.goals.goal_tracker",
    # Pre-import REAL rich so teardown restores it, not the _FakeConsole stub.
    # If rich is left stubbed, a later test (e.g. test_cli_learning) imports
    # cognia.cli with _console = _FakeConsole (whose .print is a no-op), and
    # downstream tests like test_cli_template_commands then see empty output.
    "rich", "rich.console", "rich.markup", "rich.panel",
    "rich.text", "rich.table", "rich.theme", "rich.progress",
    # Restore the REAL cognia.cli too: popping it leaves the `cognia` package's
    # `.cli` attribute pointing at the stub module, so a later `import cognia.cli`
    # returns a stale stub object distinct from sys.modules["cognia.cli"]. That
    # split-identity made test_cli_template_commands read an empty buffer.
    "cognia.cli",
)
# Modules to evict entirely on teardown (re-imported fresh by their own tests).
_EVICT_MODULE_KEYS = (
    "web_app",
)


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    import importlib
    # Force the real modules into sys.modules so teardown restores them
    # (not the stubs and not a popped/absent entry).
    _saved = {}
    for key in _REAL_MODULE_KEYS:
        try:
            importlib.import_module(key)
        except Exception:
            pass
        _saved[key] = sys.modules.get(key, KeyError)
    _evict_saved = {k: sys.modules.get(k, KeyError) for k in _EVICT_MODULE_KEYS}
    try:
        yield
    finally:
        def _restore(key, original):
            if original is KeyError:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = original
            # Re-sync the parent package attribute. The helpers do
            # `del sys.modules["cognia.cli"]` which leaves the `cognia`
            # package's `.cli` attribute pointing at a stub module, so a
            # later `import cognia.cli` returns the stale stub instead of the
            # restored sys.modules entry. Rebind the attribute to keep both
            # views consistent.
            if "." in key:
                parent_name, _, child = key.rpartition(".")
                parent = sys.modules.get(parent_name)
                if parent is not None:
                    if original is KeyError:
                        if hasattr(parent, child):
                            try:
                                delattr(parent, child)
                            except Exception:
                                pass
                    else:
                        setattr(parent, child, original)

        for key, original in _saved.items():
            _restore(key, original)
        for key, original in _evict_saved.items():
            _restore(key, original)


# ---------------------------------------------------------------------------
# Rich + prompt_toolkit stubs (same pattern as test_cli_goal_commands.py)
# ---------------------------------------------------------------------------

def _stub_rich():
    if "rich" in sys.modules and hasattr(sys.modules["rich"], "_cognia_stubbed"):
        return

    class _FakeTheme:
        def __init__(self, *a, **kw): pass

    class _FakeConsole:
        def __init__(self, *a, **kw): pass
        def print(self, *a, **kw): pass
        def status(self, *a, **kw):
            import contextlib
            return contextlib.nullcontext()

    class _FakePanel:
        def __init__(self, *a, **kw): pass

    class _FakeText:
        def __init__(self, *a, **kw): pass
        def append(self, *a, **kw): pass

    class _FakeTable:
        @staticmethod
        def grid(*a, **kw): return _FakeTable()
        def add_column(self, *a, **kw): pass
        def add_row(self, *a, **kw): pass

    def _fake_escape(s): return s

    rich_mod = types.ModuleType("rich")
    rich_mod._cognia_stubbed = True

    console_mod = types.ModuleType("rich.console")
    console_mod.Console = _FakeConsole

    markup_mod = types.ModuleType("rich.markup")
    markup_mod.escape = _fake_escape

    panel_mod = types.ModuleType("rich.panel")
    panel_mod.Panel = _FakePanel

    text_mod = types.ModuleType("rich.text")
    text_mod.Text = _FakeText

    table_mod = types.ModuleType("rich.table")
    table_mod.Table = _FakeTable

    theme_mod = types.ModuleType("rich.theme")
    theme_mod.Theme = _FakeTheme

    progress_mod = types.ModuleType("rich.progress")
    for cls_name in ("Progress", "SpinnerColumn", "TextColumn", "BarColumn"):
        setattr(progress_mod, cls_name, type(cls_name, (), {"__init__": lambda self, *a, **kw: None}))

    for name, mod in [
        ("rich", rich_mod),
        ("rich.console", console_mod),
        ("rich.markup", markup_mod),
        ("rich.panel", panel_mod),
        ("rich.text", text_mod),
        ("rich.table", table_mod),
        ("rich.theme", theme_mod),
        ("rich.progress", progress_mod),
    ]:
        sys.modules[name] = mod

    for mod_name in [
        "prompt_toolkit",
        "prompt_toolkit.completion",
        "prompt_toolkit.history",
        "prompt_toolkit.key_binding",
        "prompt_toolkit.shortcuts",
        "prompt_toolkit.styles",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)


def _import_cli():
    _rich_keys = [k for k in ("rich", "rich.console", "rich.markup", "rich.panel",
                               "rich.text", "rich.table", "rich.theme", "rich.progress")
                  if k in sys.modules]
    _saved_rich = {k: sys.modules[k] for k in _rich_keys}
    _stub_rich()
    for key in list(sys.modules):
        if key == "cognia.cli":
            del sys.modules[key]

    mock_cognia_mod = types.ModuleType("cognia.cognia")
    mock_cognia_mod.Cognia = MagicMock
    sys.modules["cognia.cognia"] = mock_cognia_mod

    mock_config_mod = types.ModuleType("cognia.config")
    mock_config_mod.HAS_RESEARCH_ENGINE = False
    mock_config_mod.HAS_PROGRAM_CREATOR = False
    # DB_PATH must be present so downstream tests that import cognia.config
    # from the module cache (after this stub replaces the real module) don't fail.
    import os, pathlib
    mock_config_mod.DB_PATH = str(pathlib.Path.home() / ".cognia" / "cognia_memory.db")
    sys.modules["cognia.config"] = mock_config_mod

    import cognia.cli as cli_mod
    sys.modules.update(_saved_rich)  # restore real rich so other test modules work
    del sys.modules["cognia.cli"]    # don't leave fake-rich cli cached for other tests
    return cli_mod


def _show_response_to_stdout(text, color=None):
    """Replacement for _show_response that writes to stdout so capsys catches it."""
    print(text)


def _make_goal(goal_id, title, progress=0, status="active"):
    return {
        "id": goal_id,
        "user_id": "cli_user",
        "title": title,
        "description": "",
        "status": status,
        "progress_pct": progress,
        "created_at": 0,
        "updated_at": 0,
        "completed_at": None,
    }


def _fake_goal_tracker(goals):
    """Return a mock GoalTracker class whose instance returns `goals` from get_goals."""
    instance = MagicMock()
    instance.get_goals.return_value = goals
    mod = types.ModuleType("cognia.goals.goal_tracker")
    mod.GoalTracker = MagicMock(return_value=instance)
    sys.modules["cognia.goals.goal_tracker"] = mod
    return instance


# ---------------------------------------------------------------------------
# _load_priorities
# ---------------------------------------------------------------------------

class TestLoadPriorities:

    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        cli = _import_cli()
        missing_path = tmp_path / "does_not_exist.json"
        with patch.object(cli, "_PRIORITIES_PATH", missing_path):
            result = cli._load_priorities()
        assert result == {}

    def test_returns_dict_when_file_exists(self, tmp_path):
        cli = _import_cli()
        data = {"1": "alta", "2": "media"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p):
            result = cli._load_priorities()
        assert result == data

    def test_returns_empty_on_corrupt_json(self, tmp_path):
        cli = _import_cli()
        p = tmp_path / ".cognia_priorities.json"
        p.write_text("not-json", encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p):
            result = cli._load_priorities()
        assert result == {}


# ---------------------------------------------------------------------------
# _slash_meta_prioridad
# ---------------------------------------------------------------------------

class TestSlashMetaPrioridad:

    def test_saves_priority_correctly(self, tmp_path, capsys):
        cli = _import_cli()
        p = tmp_path / ".cognia_priorities.json"
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_meta_prioridad("1 alta")
        saved = json.loads(p.read_text(encoding="utf-8"))
        assert saved.get("1") == "alta"

    def test_prints_confirmation(self, tmp_path, capsys):
        cli = _import_cli()
        p = tmp_path / ".cognia_priorities.json"
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_meta_prioridad("5 media")
        out = capsys.readouterr().out
        assert "Meta 5" in out
        assert "media" in out

    def test_invalid_priority_prints_error_no_crash(self, tmp_path, capsys):
        cli = _import_cli()
        p = tmp_path / ".cognia_priorities.json"
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_meta_prioridad("1 invalida")
        out = capsys.readouterr().out
        assert "invalida" in out.lower() or "Opciones" in out
        assert not p.exists()

    def test_empty_args_prints_usage(self, capsys):
        cli = _import_cli()
        cli._slash_meta_prioridad("")
        out = capsys.readouterr().out
        assert "Uso:" in out or "uso" in out.lower()

    def test_missing_priority_arg_prints_usage(self, capsys):
        cli = _import_cli()
        cli._slash_meta_prioridad("3")
        out = capsys.readouterr().out
        assert "Uso:" in out or "uso" in out.lower()

    def test_all_valid_priority_values(self, tmp_path):
        cli = _import_cli()
        for nivel in ("alta", "media", "baja"):
            p = tmp_path / f".cognia_priorities_{nivel}.json"
            with patch.object(cli, "_PRIORITIES_PATH", p):
                cli._slash_meta_prioridad(f"1 {nivel}")
            saved = json.loads(p.read_text(encoding="utf-8"))
            assert saved["1"] == nivel


# ---------------------------------------------------------------------------
# _slash_metas_alta
# ---------------------------------------------------------------------------

class TestSlashMetasAlta:

    def test_does_not_raise_with_mock(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta A"), _make_goal(2, "Meta B")]
        _fake_goal_tracker(goals)
        priorities = {"1": "alta", "2": "media"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_metas_alta("")  # must not raise

    def test_shows_only_alta_goals(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Alta meta"), _make_goal(2, "Media meta"), _make_goal(3, "Baja meta")]
        _fake_goal_tracker(goals)
        priorities = {"1": "alta", "2": "media", "3": "baja"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p), \
             patch.object(cli, "_show_response", _show_response_to_stdout):
            cli._slash_metas_alta("")
        out = capsys.readouterr().out
        assert "Alta meta" in out
        assert "Media meta" not in out
        assert "Baja meta" not in out

    def test_no_alta_goals_prints_message(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta sin prioridad")]
        _fake_goal_tracker(goals)
        p = tmp_path / ".cognia_priorities.json"
        p.write_text("{}", encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_metas_alta("")
        out = capsys.readouterr().out
        assert "alta" in out.lower()


# ---------------------------------------------------------------------------
# _slash_meta_prioridad_ver
# ---------------------------------------------------------------------------

class TestSlashMetaPrioridadVer:

    def test_does_not_raise(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta A"), _make_goal(2, "Meta B")]
        _fake_goal_tracker(goals)
        priorities = {"1": "alta"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_meta_prioridad_ver("")  # must not raise

    def test_shows_all_goals_with_priority(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta A"), _make_goal(2, "Meta B")]
        _fake_goal_tracker(goals)
        priorities = {"1": "alta", "2": "baja"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p), \
             patch.object(cli, "_show_response", _show_response_to_stdout):
            cli._slash_meta_prioridad_ver("")
        out = capsys.readouterr().out
        assert "Meta A" in out
        assert "Meta B" in out
        assert "alta" in out
        assert "baja" in out

    def test_shows_sin_prioridad_for_unset(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta sin asignar")]
        _fake_goal_tracker(goals)
        p = tmp_path / ".cognia_priorities.json"
        p.write_text("{}", encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p), \
             patch.object(cli, "_show_response", _show_response_to_stdout):
            cli._slash_meta_prioridad_ver("")
        out = capsys.readouterr().out
        assert "sin prioridad" in out


# ---------------------------------------------------------------------------
# _slash_metas_ordenar
# ---------------------------------------------------------------------------

class TestSlashMetasOrdenar:

    def test_does_not_raise(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta A"), _make_goal(2, "Meta B")]
        _fake_goal_tracker(goals)
        priorities = {"1": "baja", "2": "alta"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p):
            cli._slash_metas_ordenar("")  # must not raise

    def test_alta_appears_before_baja(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "Meta baja"), _make_goal(2, "Meta alta")]
        _fake_goal_tracker(goals)
        priorities = {"1": "baja", "2": "alta"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p), \
             patch.object(cli, "_show_response", _show_response_to_stdout):
            cli._slash_metas_ordenar("")
        out = capsys.readouterr().out
        assert out.index("Meta alta") < out.index("Meta baja")

    def test_labels_appear_in_output(self, tmp_path, capsys):
        cli = _import_cli()
        goals = [_make_goal(1, "A"), _make_goal(2, "B"), _make_goal(3, "C")]
        _fake_goal_tracker(goals)
        priorities = {"1": "alta", "2": "media", "3": "baja"}
        p = tmp_path / ".cognia_priorities.json"
        p.write_text(json.dumps(priorities), encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p), \
             patch.object(cli, "_show_response", _show_response_to_stdout):
            cli._slash_metas_ordenar("")
        out = capsys.readouterr().out
        assert "[ALTA]" in out
        assert "[MEDIA]" in out
        assert "[BAJA]" in out

    def test_no_goals_prints_message(self, tmp_path, capsys):
        cli = _import_cli()
        _fake_goal_tracker([])
        p = tmp_path / ".cognia_priorities.json"
        p.write_text("{}", encoding="utf-8")
        with patch.object(cli, "_PRIORITIES_PATH", p), \
             patch.object(cli, "_show_response", _show_response_to_stdout):
            cli._slash_metas_ordenar("")
        out = capsys.readouterr().out
        assert "Sin metas" in out


# ---------------------------------------------------------------------------
# COMMANDS dict entries
# ---------------------------------------------------------------------------

class TestCommandsDict:

    def test_meta_prioridad_in_commands(self):
        cli = _import_cli()
        assert "/meta-prioridad" in cli.COMMANDS

    def test_metas_alta_in_commands(self):
        cli = _import_cli()
        assert "/metas-alta" in cli.COMMANDS

    def test_meta_prioridad_ver_in_commands(self):
        cli = _import_cli()
        assert "/meta-prioridad-ver" in cli.COMMANDS

    def test_metas_ordenar_in_commands(self):
        cli = _import_cli()
        assert "/metas-ordenar" in cli.COMMANDS

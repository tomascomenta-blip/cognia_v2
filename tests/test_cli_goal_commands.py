"""
tests/test_cli_goal_commands.py
================================
Unit tests for the /meta* CLI commands added to cognia/cli.py.
GoalTracker is mocked so the tests do not require a database.
"""

import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub rich + prompt_toolkit before importing cli so module-level code runs
# ---------------------------------------------------------------------------

def _stub_rich():
    """Install minimal rich stubs so cli.py module-level code succeeds."""
    if "rich" in sys.modules and hasattr(sys.modules["rich"], "_cognia_stubbed"):
        return  # already installed

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

    # Build stubs
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

    # prompt_toolkit stubs
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


def _import_cli_funcs():
    """Return a fresh import of cognia.cli with rich properly stubbed."""
    _rich_keys = [k for k in ("rich", "rich.console", "rich.markup", "rich.panel",
                               "rich.text", "rich.table", "rich.theme", "rich.progress")
                  if k in sys.modules]
    _saved_rich = {k: sys.modules[k] for k in _rich_keys}
    _stub_rich()
    # Remove cached module to force re-import each test class
    for key in list(sys.modules):
        if key == "cognia.cli":
            del sys.modules[key]

    # Stub cognia.cognia and cognia.config to avoid heavy init
    mock_cognia_mod = types.ModuleType("cognia.cognia")
    mock_cognia_mod.Cognia = MagicMock
    sys.modules["cognia.cognia"] = mock_cognia_mod

    mock_config_mod = types.ModuleType("cognia.config")
    mock_config_mod.HAS_RESEARCH_ENGINE = False
    mock_config_mod.HAS_PROGRAM_CREATOR = False
    import pathlib as _pl
    mock_config_mod.DB_PATH = str(_pl.Path.home() / ".cognia" / "cognia_memory.db")
    sys.modules["cognia.config"] = mock_config_mod

    import cognia.cli as cli_mod
    sys.modules.update(_saved_rich)  # restore real rich so other test modules work
    del sys.modules["cognia.cli"]    # don't leave fake-rich cli cached for other tests
    return cli_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_goal(goal_id: int, title: str, progress: int = 0, status: str = "active") -> dict:
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlashMeta:
    """_slash_meta creates a new goal."""

    def test_creates_goal_without_exception(self, capsys):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.create_goal.return_value = _make_goal(1, "Aprender Python")
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta("Aprender Python")

        captured = capsys.readouterr()
        assert "Meta creada" in captured.out
        assert "Aprender Python" in captured.out

    def test_calls_create_goal_with_cli_user(self, capsys):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.create_goal.return_value = _make_goal(2, "Leer 12 libros")
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta("Leer 12 libros")

        mock_gt_instance.create_goal.assert_called_once_with("cli_user", "Leer 12 libros")


class TestSlashMetas:
    """_slash_metas lists active goals."""

    def test_calls_get_goals_with_active_status(self, capsys):
        cli = _import_cli_funcs()
        goals = [
            _make_goal(1, "Aprender Python", 0),
            _make_goal(2, "Leer 12 libros", 45),
        ]
        mock_gt_instance = MagicMock()
        mock_gt_instance.get_goals.return_value = goals
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_metas()

        mock_gt_instance.get_goals.assert_called_once_with("cli_user", status="active")

    def test_no_goals_prints_message(self, capsys):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.get_goals.return_value = []
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_metas()

        captured = capsys.readouterr()
        assert "Sin metas activas" in captured.out


class TestSlashMetaOk:
    """_slash_meta_ok marks a goal complete (progress=100)."""

    def test_calls_update_progress_100(self):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.update_progress.return_value = True
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta_ok("1")

        mock_gt_instance.update_progress.assert_called_once_with(1, 100, user_id="cli_user")

    def test_prints_completada(self, capsys):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.update_progress.return_value = True
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta_ok("1")

        captured = capsys.readouterr()
        assert "completada" in captured.out


class TestSlashMetaProg:
    """_slash_meta_prog updates goal progress to given percentage."""

    def test_calls_update_progress_with_pct(self):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.update_progress.return_value = True
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta_prog("1 50")

        mock_gt_instance.update_progress.assert_called_once_with(1, 50, user_id="cli_user")

    def test_prints_progress_updated(self, capsys):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.update_progress.return_value = True
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta_prog("1 50")

        captured = capsys.readouterr()
        assert "50%" in captured.out


class TestSlashMetaBorrar:
    """_slash_meta_borrar deletes a goal."""

    def test_calls_delete_goal(self):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.delete_goal.return_value = True
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta_borrar("1")

        mock_gt_instance.delete_goal.assert_called_once_with(1, "cli_user")

    def test_prints_eliminada(self, capsys):
        cli = _import_cli_funcs()
        mock_gt_instance = MagicMock()
        mock_gt_instance.delete_goal.return_value = True
        mock_gt_cls = MagicMock(return_value=mock_gt_instance)
        fake_goals_mod = types.ModuleType("cognia.goals.goal_tracker")
        fake_goals_mod.GoalTracker = mock_gt_cls
        sys.modules["cognia.goals.goal_tracker"] = fake_goals_mod

        cli._slash_meta_borrar("1")

        captured = capsys.readouterr()
        assert "eliminada" in captured.out


class TestGoalTrackerUnavailable:
    """When GoalTracker cannot be imported, commands print fallback message."""

    def test_meta_unavailable_prints_fallback(self, capsys):
        cli = _import_cli_funcs()
        # Remove the module so import inside the function will raise ImportError
        sys.modules.pop("cognia.goals.goal_tracker", None)
        sys.modules.pop("cognia.goals", None)

        # Patch the import inside _slash_meta to raise ImportError
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _raise_on_goal_tracker(name, *args, **kwargs):
            if "goal_tracker" in name:
                raise ImportError("mocked unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_raise_on_goal_tracker):
            cli._slash_meta("test")

        captured = capsys.readouterr()
        assert "no disponible" in captured.out

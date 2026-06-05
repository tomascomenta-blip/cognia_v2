"""
tests/test_cli_profile_commands.py
===================================
Tests for /reporte, /reporte-json, /yo, and /yo-actualizar CLI commands.
All external modules are mocked so tests run without a real DB or model.
"""

import sys
import types
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# Import the four functions under test directly from cognia.cli
from cognia.cli import (  # noqa: E402
    _slash_reporte,
    _slash_reporte_json,
    _slash_yo_perfil,
    _slash_yo_actualizar,
    _CLI_USER_ID,
)


# ---------------------------------------------------------------------------
# Test: _slash_reporte — no exception with mock ProgressReporter
# ---------------------------------------------------------------------------

def test_slash_reporte_no_exception():
    mock_reporter_cls = MagicMock()
    mock_reporter_cls.return_value.generate_report.return_value = (
        "# Cognia Progress Report\n\n**User:** cli_user"
    )
    with patch.dict(
        sys.modules,
        {"cognia.reports.progress_reporter": types.SimpleNamespace(
            ProgressReporter=mock_reporter_cls
        )},
    ):
        _slash_reporte()

    mock_reporter_cls.return_value.generate_report.assert_called_once_with(
        user_id=_CLI_USER_ID, period_days=7
    )


# ---------------------------------------------------------------------------
# Test: _slash_reporte_json — prints expected stats lines
# ---------------------------------------------------------------------------

def test_slash_reporte_json_prints_stats():
    mock_reporter_cls = MagicMock()
    mock_reporter_cls.return_value.generate_json_stats.return_value = {
        "period_days": 7,
        "goals_active": 3,
        "goals_completed": 1,
        "messages_total": 42,
        "sessions_total": 5,
        "insights_count": 2,
    }

    captured_output = []

    # Patch _show_response in the function's own globals (not via sys.modules
    # lookup, which may return a stub module after other tests run _import_cli()).
    _fn_globals = _slash_reporte_json.__globals__
    original_show = _fn_globals["_show_response"]

    def fake_show(text, color="cyan"):
        captured_output.append(text)

    with patch.dict(
        sys.modules,
        {"cognia.reports.progress_reporter": types.SimpleNamespace(
            ProgressReporter=mock_reporter_cls
        )},
    ):
        _fn_globals["_show_response"] = fake_show
        try:
            _slash_reporte_json()
        finally:
            _fn_globals["_show_response"] = original_show

    assert captured_output, "Expected _show_response to be called"
    output = captured_output[0]
    assert "Estadisticas (7 dias):" in output
    assert "Metas activas: 3" in output
    assert "Metas completadas: 1" in output
    assert "Mensajes totales: 42" in output
    assert "Sesiones: 5" in output
    assert "Insights de curiosidad: 2" in output


# ---------------------------------------------------------------------------
# Test: _slash_yo_perfil — with mock profile returns formatted output
# ---------------------------------------------------------------------------

def test_slash_yo_with_profile():
    mock_builder_cls = MagicMock()
    mock_builder_cls.return_value.get_profile.return_value = {
        "top_topics": [
            {"term": "python", "count": 10},
            {"term": "fastapi", "count": 5},
        ],
        "query_patterns": ["asks_code", "asks_how"],
        "dominant_language": "es",
    }

    captured_output = []

    _fn_globals = _slash_yo_perfil.__globals__
    original_show = _fn_globals["_show_response"]

    def fake_show(text, color="cyan"):
        captured_output.append(text)

    with patch.dict(
        sys.modules,
        {"cognia.profile.user_profile_builder": types.SimpleNamespace(
            UserProfileBuilder=mock_builder_cls
        )},
    ):
        _fn_globals["_show_response"] = fake_show
        try:
            _slash_yo_perfil()
        finally:
            _fn_globals["_show_response"] = original_show

    assert captured_output, "Expected _show_response to be called"
    output = captured_output[0]
    assert "python" in output
    assert "fastapi" in output
    assert "asks_code" in output
    assert "es" in output


# ---------------------------------------------------------------------------
# Test: _slash_yo_perfil — without profile prints fallback message
# ---------------------------------------------------------------------------

def test_slash_yo_no_profile():
    mock_builder_cls = MagicMock()
    mock_builder_cls.return_value.get_profile.return_value = None

    with patch.dict(
        sys.modules,
        {"cognia.profile.user_profile_builder": types.SimpleNamespace(
            UserProfileBuilder=mock_builder_cls
        )},
    ):
        captured = StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured
        try:
            _slash_yo_perfil()
        finally:
            sys.stdout = original_stdout

    assert "No hay perfil disponible" in captured.getvalue()


# ---------------------------------------------------------------------------
# Test: _slash_yo_actualizar — calls build_profile() and save_profile()
# ---------------------------------------------------------------------------

def test_slash_yo_actualizar_calls_build_and_save():
    mock_builder_cls = MagicMock()
    fake_profile = {
        "top_topics": [],
        "query_patterns": [],
        "message_count": 0,
        "avg_message_len": 0.0,
        "dominant_language": "unknown",
    }
    mock_builder_cls.return_value.build_profile.return_value = fake_profile

    with patch.dict(
        sys.modules,
        {"cognia.profile.user_profile_builder": types.SimpleNamespace(
            UserProfileBuilder=mock_builder_cls
        )},
    ):
        captured = StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured
        try:
            _slash_yo_actualizar()
        finally:
            sys.stdout = original_stdout

    mock_builder_cls.return_value.build_profile.assert_called_once()
    mock_builder_cls.return_value.save_profile.assert_called_once_with(_CLI_USER_ID, fake_profile)
    assert "Perfil actualizado" in captured.getvalue()

"""
tests/test_cli_profile_status.py
Tests for /mi-cognia, /perfil-completo, and /estado CLI commands.
"""
import sys
import types
from io import StringIO
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to import only cli.py without side-effects
# ---------------------------------------------------------------------------

def _get_functions():
    from cognia.cli import _slash_mi_cognia, _slash_perfil_completo, _slash_estado
    return _slash_mi_cognia, _slash_perfil_completo, _slash_estado


# ---------------------------------------------------------------------------
# Test 1: /mi-cognia handles connection error gracefully
# ---------------------------------------------------------------------------

def test_mi_cognia_connection_error(capsys):
    _slash_mi_cognia, _, _ = _get_functions()
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_mi_cognia("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


# ---------------------------------------------------------------------------
# Test 2: /perfil-completo handles connection error gracefully
# ---------------------------------------------------------------------------

def test_perfil_completo_connection_error(capsys):
    _, _slash_perfil_completo, _ = _get_functions()
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_perfil_completo("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


# ---------------------------------------------------------------------------
# Test 3: /estado handles all services down
# ---------------------------------------------------------------------------

def test_estado_all_services_down(capsys):
    _, _, _slash_estado = _get_functions()
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_estado("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower() or "Servicio" in out


# ---------------------------------------------------------------------------
# Test 4: /estado output contains "Estado de Cognia" when at least one service responds
# ---------------------------------------------------------------------------

def test_estado_output_header(capsys):
    _, _, _slash_estado = _get_functions()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "total": 5,
        "pinned": 1,
        "unlocked": 3,
        "points": 120,
        "streak": 4,
        "today_count": 7,
        "due_today": 2,
    }

    with patch("requests.get", return_value=mock_resp):
        _slash_estado("")

    out = capsys.readouterr().out
    assert "Estado de Cognia" in out


# ---------------------------------------------------------------------------
# Test 5: /mi-cognia prints fallback message on any exception
# ---------------------------------------------------------------------------

def test_mi_cognia_fallback_message(capsys):
    _slash_mi_cognia, _, _ = _get_functions()

    # Simulate an OSError (e.g., port not open)
    with patch("requests.get", side_effect=OSError("port closed")):
        _slash_mi_cognia("")

    out = capsys.readouterr().out
    assert len(out.strip()) > 0, "Should print something even on error"
    assert "no disponible" in out.lower()

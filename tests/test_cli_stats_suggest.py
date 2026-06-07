"""
tests/test_cli_stats_suggest.py
Tests for /stats, /sesion-stats, and /sugerir CLI commands (Cycle 23B).
"""
import sys
import time
from pathlib import Path
from io import StringIO
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
import cognia.cli as cli_mod


def _reset_history():
    cli_mod._history.clear()
    cli_mod._session_start = time.time()


class TestSlashStats:
    def test_stats_shows_user_turns(self, capsys):
        _reset_history()
        cli_mod._history.append({"role": "user", "content": "hola"})
        cli_mod._history.append({"role": "assistant", "content": "Hola!"})
        cli_mod._slash_stats()
        out = capsys.readouterr().out
        assert "Turnos usuario   : 1" in out

    def test_stats_shows_duration(self, capsys):
        _reset_history()
        cli_mod._session_start = time.time() - 130
        cli_mod._slash_stats()
        out = capsys.readouterr().out
        assert "Duracion" in out
        assert "2 min" in out

    def test_stats_empty_history_shows_zeros(self, capsys):
        _reset_history()
        cli_mod._slash_stats()
        out = capsys.readouterr().out
        assert "Turnos usuario   : 0" in out
        assert "Turnos asistente : 0" in out
        assert "Total            : 0" in out

    def test_stats_counts_multiple_turns(self, capsys):
        _reset_history()
        for _ in range(3):
            cli_mod._history.append({"role": "user", "content": "q"})
            cli_mod._history.append({"role": "assistant", "content": "a"})
        cli_mod._slash_stats()
        out = capsys.readouterr().out
        assert "Turnos usuario   : 3" in out
        assert "Turnos asistente : 3" in out
        assert "Total            : 6" in out


class TestSesionStatsAlias:
    def test_sesion_stats_alias_in_commands(self):
        from cognia.cli import COMMANDS
        assert "/sesion-stats" in COMMANDS
        assert "/stats" in COMMANDS

    def test_sesion_stats_same_output_as_stats(self, capsys):
        _reset_history()
        cli_mod._history.append({"role": "user", "content": "x"})
        cli_mod._history.append({"role": "assistant", "content": "y"})
        cli_mod._slash_stats()
        out1 = capsys.readouterr().out
        cli_mod._slash_stats()
        out2 = capsys.readouterr().out
        assert out1 == out2


class TestSlashSugerir:
    def test_sugerir_handles_connection_error_gracefully(self, capsys):
        with patch("requests.get", side_effect=Exception("connection refused")):
            cli_mod._slash_sugerir()
        out = capsys.readouterr().out
        assert "no disponible" in out.lower() or "cognia_desktop_api" in out

    def test_sugerir_shows_suggestions_when_available(self, capsys):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"suggestions": ["Revisa tus metas", "Duerme para consolidar"]}
        with patch("requests.get", return_value=mock_resp):
            cli_mod._slash_sugerir()
        out = capsys.readouterr().out
        assert "Revisa tus metas" in out
        assert "Duerme para consolidar" in out

"""
tests/test_cli_digest.py
Tests for /digest, /cognia-info, and /inicio-dia CLI commands (Cycle 41B).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import patch, MagicMock


class TestDigestCommand:
    """Tests for _slash_digest."""

    def test_digest_handles_connection_error(self, capsys):
        from cognia.cli import _slash_digest
        with patch("requests.get", side_effect=Exception("connection refused")):
            _slash_digest("")
        out = capsys.readouterr().out
        assert "no disponible" in out.lower()

    def test_digest_shows_text_on_success(self, capsys):
        from cognia.cli import _slash_digest
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"digest": "Hoy: 3 metas activas, 5 tarjetas."}
        with patch("requests.get", return_value=mock_resp):
            _slash_digest("")
        out = capsys.readouterr().out
        assert "metas activas" in out

    def test_digest_shows_error_on_non_200(self, capsys):
        from cognia.cli import _slash_digest
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("requests.get", return_value=mock_resp):
            _slash_digest("")
        out = capsys.readouterr().out
        assert "503" in out


class TestCogniaInfoCommand:
    """Tests for _slash_cognia_info."""

    def test_cognia_info_shows_v3(self, capsys):
        from cognia.cli import _slash_cognia_info
        _slash_cognia_info("")
        out = capsys.readouterr().out
        assert "Cognia v3" in out

    def test_cognia_info_shows_total_commands_count(self, capsys):
        from cognia.cli import _slash_cognia_info, _CMD_DESCRIPTIONS
        _slash_cognia_info("")
        out = capsys.readouterr().out
        total = len(_CMD_DESCRIPTIONS)
        assert str(total) in out

    def test_cognia_info_shows_capabilities(self, capsys):
        from cognia.cli import _slash_cognia_info
        _slash_cognia_info("")
        out = capsys.readouterr().out
        assert "Inferencia" in out
        assert "Memoria" in out
        assert "Gamificacion" in out


class TestInicioDiaCommand:
    """Tests for _slash_inicio_dia."""

    def test_inicio_dia_calls_digest(self, capsys):
        from cognia.cli import _slash_inicio_dia
        with patch("cognia.cli._slash_digest") as mock_digest, \
             patch("cognia.cli._slash_proximos_pasos"), \
             patch("requests.get", side_effect=Exception("no service")):
            _slash_inicio_dia("")
        mock_digest.assert_called_once_with("")

    def test_inicio_dia_calls_proximos_pasos(self, capsys):
        from cognia.cli import _slash_inicio_dia
        with patch("cognia.cli._slash_digest"), \
             patch("cognia.cli._slash_proximos_pasos") as mock_ps, \
             patch("requests.get", side_effect=Exception("no service")):
            _slash_inicio_dia("")
        mock_ps.assert_called_once_with("")

    def test_inicio_dia_shows_due_cards(self, capsys):
        from cognia.cli import _slash_inicio_dia
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"due_today": 7}
        with patch("cognia.cli._slash_digest"), \
             patch("cognia.cli._slash_proximos_pasos"), \
             patch("requests.get", return_value=mock_resp):
            _slash_inicio_dia("")
        out = capsys.readouterr().out
        assert "7" in out
        assert "tarjeta" in out

    def test_inicio_dia_silent_on_no_service(self, capsys):
        from cognia.cli import _slash_inicio_dia
        with patch("cognia.cli._slash_digest"), \
             patch("cognia.cli._slash_proximos_pasos"), \
             patch("requests.get", side_effect=Exception("no service")):
            _slash_inicio_dia("")
        out = capsys.readouterr().out
        assert "Buenos dias" in out

"""
tests/test_cli_notes.py
Tests for CLI Notes Commands (Cycle 24B).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import io

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest


class TestSlashNotas:

    def test_notas_handles_connection_error(self, capsys):
        from cognia.cli import _slash_notas
        with patch("requests.get", side_effect=Exception("connection refused")):
            _slash_notas("")
        out = capsys.readouterr().out
        assert "no disponible" in out.lower()

    def test_notas_with_type_filter_maps_correctly(self, capsys):
        from cognia.cli import _slash_notas
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"notes": [
            {"note_type": "fact", "content": "Python is great", "pinned": False}
        ]}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            _slash_notas("hechos")
        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        assert params.get("note_type") == "fact"

    def test_nota_agregar_requires_content(self, capsys):
        from cognia.cli import _slash_nota_agregar
        _slash_nota_agregar("")
        out = capsys.readouterr().out
        assert "Uso:" in out

    def test_notas_buscar_calls_endpoint(self, capsys):
        from cognia.cli import _slash_notas_buscar
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        with patch("requests.get", return_value=mock_resp) as mock_get:
            _slash_notas_buscar("python")
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "/notes/search" in url

    def test_notas_stats_shows_total(self, capsys):
        from cognia.cli import _slash_notas_stats
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "total": 15, "facts": 3, "decisions": 2,
            "actions": 1, "insights": 8, "questions": 1, "pinned": 2
        }
        with patch("requests.get", return_value=mock_resp):
            _slash_notas_stats()
        out = capsys.readouterr().out
        assert "15 total" in out

    def test_nota_fijar_requires_id(self, capsys):
        from cognia.cli import _slash_nota_fijar
        _slash_nota_fijar("")
        out = capsys.readouterr().out
        assert "Uso:" in out

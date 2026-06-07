"""
tests/test_cli_critique.py
Tests for CLI critique and reflection commands added in Cycle 31B.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import patch, MagicMock
import io


class TestVerCriticas:
    def test_connection_error_prints_fallback(self, capsys):
        from cognia.cli import _slash_ver_criticas
        with patch("requests.get", side_effect=Exception("connection refused")):
            _slash_ver_criticas("")
        out = capsys.readouterr().out
        assert "no disponible" in out.lower()

    def test_empty_list_prints_no_criticas(self, capsys):
        from cognia.cli import _slash_ver_criticas
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        with patch("requests.get", return_value=mock_resp):
            _slash_ver_criticas("")
        out = capsys.readouterr().out
        assert "Sin criticas" in out


class TestReflexionProfunda:
    def test_requires_args(self, capsys):
        from cognia.cli import _slash_reflexion_profunda
        _slash_reflexion_profunda("")
        out = capsys.readouterr().out
        assert "Uso:" in out

    def test_prints_five_lenses(self, capsys):
        from cognia.cli import _slash_reflexion_profunda
        _slash_reflexion_profunda("inteligencia artificial")
        out = capsys.readouterr().out
        for lens in ("Analitico", "Critico", "Creativo", "Sistemico", "Pragmatico"):
            assert lens in out

    def test_includes_all_five_lens_names_in_output(self, capsys):
        from cognia.cli import _slash_reflexion_profunda
        _slash_reflexion_profunda("aprendizaje automatico")
        out = capsys.readouterr().out
        lens_names = ["Analitico", "Critico", "Creativo", "Sistemico", "Pragmatico"]
        found = [name for name in lens_names if name in out]
        assert len(found) == 5


class TestCalidadRespuestas:
    def test_connection_error_prints_fallback(self, capsys):
        from cognia.cli import _slash_calidad_respuestas
        with patch("requests.get", side_effect=Exception("connection refused")):
            _slash_calidad_respuestas("")
        out = capsys.readouterr().out
        assert "no disponible" in out.lower()

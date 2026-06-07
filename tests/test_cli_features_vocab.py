"""
tests/test_cli_features_vocab.py
Tests for /features, /vocabulario, and /vocabulario-guardar CLI commands (Cycle 34B).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from unittest.mock import patch, MagicMock


class TestSlashFeatures:
    def test_handles_connection_error(self, capsys):
        import cognia.cli as cli
        with patch("requests.get", side_effect=Exception("connection refused")):
            cli._slash_features("")
        out = capsys.readouterr().out
        assert "no disponible" in out.lower()

    def test_empty_flags_list(self, capsys):
        import cognia.cli as cli
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"flags": []}
        with patch("requests.get", return_value=mock_resp):
            cli._slash_features("")
        out = capsys.readouterr().out
        assert "No hay feature flags" in out


class TestSlashVocabulario:
    def test_empty_history_prints_message(self, capsys):
        import cognia.cli as cli
        original = cli._history[:]
        cli._history.clear()
        try:
            cli._slash_vocabulario("")
        finally:
            cli._history.extend(original)
        out = capsys.readouterr().out
        assert "No hay historial" in out

    def test_extracts_long_words_from_assistant_messages(self, capsys):
        import cognia.cli as cli
        original = cli._history[:]
        cli._history.clear()
        cli._history.append({"role": "assistant", "content": "El algoritmo de inferencia distribuida es eficiente"})
        try:
            cli._slash_vocabulario("")
        finally:
            cli._history.clear()
            cli._history.extend(original)
        out = capsys.readouterr().out
        assert "algoritmo" in out or "inferencia" in out or "distribuida" in out or "eficiente" in out

    def test_excludes_stop_words(self, capsys):
        import cognia.cli as cli
        original = cli._history[:]
        cli._history.clear()
        cli._history.append({"role": "assistant", "content": "tambien pueden hacer import return class"})
        try:
            cli._slash_vocabulario("")
        finally:
            cli._history.clear()
            cli._history.extend(original)
        out = capsys.readouterr().out
        # stop words should not appear as vocabulary items
        for stop in ("tambien", "pueden", "hacer", "import", "return", "class"):
            assert stop not in out


class TestSlashVocabularioGuardar:
    def test_empty_history_prints_message(self, capsys):
        import cognia.cli as cli
        original = cli._history[:]
        cli._history.clear()
        try:
            cli._slash_vocabulario_guardar("")
        finally:
            cli._history.extend(original)
        out = capsys.readouterr().out
        assert "No hay historial" in out

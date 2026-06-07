"""
tests/test_cli_quiz.py
Tests for /quiz, /quiz-stats, and /exportar-todo CLI commands.
"""
import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.cli import _slash_quiz, _slash_quiz_stats, _slash_exportar_todo, COMMANDS


def test_quiz_handles_connection_error(capsys):
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_quiz("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower() or "refused" in out.lower()


def test_quiz_stats_handles_connection_error(capsys):
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_quiz_stats("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_exportar_todo_handles_connection_error(capsys, tmp_path):
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_exportar_todo(str(tmp_path))
    out = capsys.readouterr().out
    assert "advertencia" in out.lower() or "no se pudo" in out.lower()


def test_exportar_todo_creates_directory(capsys, tmp_path):
    dest = tmp_path / "new_export_dir"
    assert not dest.exists()
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_exportar_todo(str(dest))
    assert dest.exists()


def test_quiz_stats_shows_precision(capsys):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "total_attempts": 10,
        "correct": 7,
        "accuracy": 0.7,
        "by_source": {
            "kg": {"total": 5, "correct": 4},
            "cards": {"total": 5, "correct": 3},
        },
    }
    with patch("requests.get", return_value=mock_resp):
        _slash_quiz_stats("")
    out = capsys.readouterr().out
    assert "70.0%" in out
    assert "Precision" in out
    assert "10" in out
    assert "7" in out

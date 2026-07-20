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

import cognia.cli as cli
from cognia.cli import _slash_quiz, _slash_quiz_stats, _slash_exportar_todo, COMMANDS


def _patch_quiz(tmp_path, monkeypatch):
    from cognia.learning.quiz_generator import QuizGenerator
    db = str(tmp_path / "learn.db")
    monkeypatch.setattr(cli, "_quiz_gen", lambda: QuizGenerator(db_path=db, kg_db_path=db))
    return db


def test_quiz_empty_no_http(tmp_path, monkeypatch, capsys):
    # No SR cards and no KG -> nothing to ask, but never an HTTP failure.
    _patch_quiz(tmp_path, monkeypatch)
    _slash_quiz("")
    out = capsys.readouterr().out
    assert "no disponible" not in out.lower()


def test_quiz_stats_empty_no_http(tmp_path, monkeypatch, capsys):
    _patch_quiz(tmp_path, monkeypatch)
    _slash_quiz_stats("")
    out = capsys.readouterr().out
    assert "Intentos totales : 0" in out
    assert "no disponible" not in out.lower()


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


def test_quiz_stats_shows_precision(tmp_path, monkeypatch, capsys):
    db = _patch_quiz(tmp_path, monkeypatch)
    gen = cli._quiz_gen()
    # 7 correct out of 10 -> 70.0% precision, computed locally.
    for _ in range(7):
        gen.record_answer("q", "a", "a", source="kg")
    for _ in range(3):
        gen.record_answer("q", "a", "wrong", source="kg")

    _slash_quiz_stats("")
    out = capsys.readouterr().out
    assert "70.0%" in out
    assert "Precision" in out
    assert "10" in out
    assert "7" in out

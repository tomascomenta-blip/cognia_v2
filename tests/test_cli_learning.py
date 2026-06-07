"""
tests/test_cli_learning.py
Tests for spaced repetition CLI commands added in Cycle 25B.
"""

from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.cli import (
    _slash_aprender_card,
    _slash_aprendiendo,
    _slash_revisar_sm2,
    COMMANDS,
)


def test_aprender_requires_pipe_separator(capsys):
    _slash_aprender_card("sin separador")
    out = capsys.readouterr().out
    assert "Uso:" in out


def test_aprender_parses_front_back_topic():
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": 42}
        return resp

    with patch("requests.post", side_effect=fake_post):
        _slash_aprender_card("frente test | respuesta test | Python")

    assert captured.get("front") == "frente test"
    assert captured.get("back") == "respuesta test"
    assert captured.get("topic") == "Python"


def test_aprendiendo_handles_connection_error(capsys):
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_aprendiendo()
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_revisar_handles_empty_due_list(capsys):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"cards": []}

    with patch("requests.get", return_value=resp):
        _slash_revisar_sm2()

    out = capsys.readouterr().out
    assert "No hay tarjetas" in out


def test_aprendiendo_shows_stats_format(capsys):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "total": 15,
        "due": 3,
        "mastered": 2,
        "topics": ["Python", "FastAPI", "tests"],
    }

    with patch("requests.get", return_value=resp):
        _slash_aprendiendo()

    out = capsys.readouterr().out
    assert "Total tarjetas" in out
    assert "15" in out
    assert "Python" in out

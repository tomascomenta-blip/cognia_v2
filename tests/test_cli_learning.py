"""
tests/test_cli_learning.py
Tests for spaced repetition CLI commands added in Cycle 25B.

As of the standalone rewrite these commands use the local
SpacedRepetitionEngine directly (no :8765 desktop API), so the tests inject
an engine backed by a temp DB instead of mocking HTTP.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cognia.cli as cli
from cognia.cli import (
    _slash_aprender_card,
    _slash_aprendiendo,
    _slash_revisar_sm2,
    COMMANDS,
)


def _patch_engine(tmp_path, monkeypatch):
    from cognia.learning.spaced_repetition import SpacedRepetitionEngine
    db = str(tmp_path / "sr.db")
    monkeypatch.setattr(cli, "_sr_engine", lambda: SpacedRepetitionEngine(db_path=db))


def test_aprender_requires_pipe_separator(capsys):
    _slash_aprender_card("sin separador")
    out = capsys.readouterr().out
    assert "Uso:" in out


def test_aprender_parses_front_back_topic(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)
    _slash_aprender_card("frente test | respuesta test | Python")
    capsys.readouterr()

    # The card must be retrievable from the local engine with the parsed fields.
    cards = cli._sr_engine().get_due_cards(limit=10)
    assert any(
        c["front"] == "frente test"
        and c["back"] == "respuesta test"
        and c.get("topic") == "Python"
        for c in cards
    )


def test_aprendiendo_empty_no_http(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)
    _slash_aprendiendo()
    out = capsys.readouterr().out
    assert "Total tarjetas : 0" in out
    assert "no disponible" not in out.lower()


def test_revisar_handles_empty_due_list(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)
    _slash_revisar_sm2()
    out = capsys.readouterr().out
    assert "No hay tarjetas" in out


def test_aprendiendo_shows_stats_format(tmp_path, monkeypatch, capsys):
    _patch_engine(tmp_path, monkeypatch)
    eng = cli._sr_engine()
    eng.add_card("q1", "a1", "Python")
    eng.add_card("q2", "a2", "FastAPI")

    _slash_aprendiendo()
    out = capsys.readouterr().out
    assert "Total tarjetas" in out
    assert "2" in out
    assert "Python" in out

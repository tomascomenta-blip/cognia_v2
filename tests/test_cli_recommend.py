"""
tests/test_cli_recommend.py
Tests for /recomendar, /proximos-pasos, /mapa CLI commands.
"""
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

# Import the functions directly
from cognia.cli import _slash_recomendar, _slash_proximos_pasos, _slash_mapa


# ---------------------------------------------------------------------------
# /recomendar
# ---------------------------------------------------------------------------

def test_recomendar_connection_error(capsys):
    """Should print fallback message when service is unavailable."""
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_recomendar("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_recomendar_empty_list(capsys):
    """Should say no hay recomendaciones when list is empty."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"recommendations": []}
    with patch("requests.get", return_value=mock_resp):
        _slash_recomendar("")
    out = capsys.readouterr().out
    assert "No hay recomendaciones" in out


# ---------------------------------------------------------------------------
# /proximos-pasos
# ---------------------------------------------------------------------------

def test_proximos_pasos_connection_error(capsys):
    """Should print fallback message when service is unavailable."""
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_proximos_pasos("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


# ---------------------------------------------------------------------------
# /mapa
# ---------------------------------------------------------------------------

def test_mapa_requires_args(capsys):
    """Should print usage hint when no concept is provided."""
    _slash_mapa("")
    out = capsys.readouterr().out
    assert "Uso:" in out
    assert "/mapa" in out


def test_mapa_fallback_when_kg_unavailable(capsys):
    """Should show template fallback nodes when KG returns nothing."""
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_mapa("inteligencia")
    out = capsys.readouterr().out
    assert "definicion" in out
    assert "causas" in out
    assert "efectos" in out


def test_mapa_includes_center_concept(capsys):
    """Center concept should appear in the ASCII map output."""
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_mapa("machine learning")
    out = capsys.readouterr().out
    assert "machine learning" in out

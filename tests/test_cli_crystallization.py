"""
tests/test_cli_crystallization.py
Tests for CLI crystallization commands added in Cycle 35B.
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognia.cli import (
    _slash_hechos_solidos,
    _slash_cristalizar,
    _slash_conocimiento_ver,
)


def test_hechos_solidos_connection_error(capsys):
    """_slash_hechos_solidos prints fallback message when service is unreachable."""
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_hechos_solidos("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_cristalizar_connection_error(capsys):
    """_slash_cristalizar prints fallback message when service is unreachable."""
    with patch("requests.post", side_effect=ConnectionError("refused")):
        _slash_cristalizar("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_conocimiento_ver_requires_args(capsys):
    """_slash_conocimiento_ver prints usage hint when called with empty args."""
    _slash_conocimiento_ver("")
    out = capsys.readouterr().out
    assert "/conocimiento-ver" in out
    assert "Uso:" in out


def test_conocimiento_ver_connection_error(capsys):
    """_slash_conocimiento_ver prints fallback message when service is unreachable."""
    with patch("requests.get", side_effect=ConnectionError("refused")):
        _slash_conocimiento_ver("python")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_hechos_solidos_empty_facts(capsys):
    """_slash_hechos_solidos shows empty message when API returns no facts."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    with patch("requests.get", return_value=mock_resp):
        _slash_hechos_solidos("")
    out = capsys.readouterr().out
    assert "cristalizar" in out.lower() or "No hay" in out

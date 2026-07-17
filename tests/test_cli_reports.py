"""
tests/test_cli_reports.py
Tests for CLI report and causal-chain commands added in Cycle 32B.
"""

import sys
import io
from unittest.mock import patch, MagicMock


def _import_cli():
    """Import cli module functions without triggering the REPL."""
    import importlib
    import cognia.cli as cli
    return cli


def test_reporte_completo_connection_error(capsys):
    """reporte-completo should print fallback message on connection error."""
    from cognia.cli import _slash_reporte_completo
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_reporte_completo("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def test_reporte_semanal_connection_error(capsys):
    """reporte-semanal should print fallback message on connection error."""
    from cognia.cli import _slash_reporte_semanal
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_reporte_semanal("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()


def _fake_ai_cadena(texto):
    """/cadena-causal genera por el backend REAL desde 2026-07-16."""
    import types

    class _Orch:
        def infer(self, prompt, max_tokens=None, temperature=None):
            return types.SimpleNamespace(text=texto, mode="local")

    return types.SimpleNamespace(_orchestrator=_Orch())


def test_cadena_causal_requires_args(capsys):
    """cadena-causal should print usage hint when called with no args."""
    from cognia.cli import _slash_cadena_causal
    _slash_cadena_causal(None, "")
    out = capsys.readouterr().out
    assert "Uso:" in out


def test_cadena_causal_prints_causas(capsys):
    """cadena-causal imprime la cadena generada por el modelo."""
    from cognia.cli import _slash_cadena_causal
    ai = _fake_ai_cadena("Causas raiz:\n- emision\nCausas directas:\n- demanda\n"
                         "Efectos de 'inflacion':\n- precios\n"
                         "Efectos de segundo orden:\n- tasas")
    _slash_cadena_causal(ai, "inflacion")
    out = capsys.readouterr().out
    assert "Causas raiz" in out
    assert "inflacion" in out


def test_metas_pendientes_connection_error(capsys):
    """metas-pendientes should print fallback message on connection error."""
    from cognia.cli import _slash_metas_pendientes
    with patch("requests.get", side_effect=Exception("connection refused")):
        _slash_metas_pendientes("")
    out = capsys.readouterr().out
    assert "no disponible" in out.lower()

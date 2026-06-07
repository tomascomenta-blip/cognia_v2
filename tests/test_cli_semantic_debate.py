"""
tests/test_cli_semantic_debate.py
Tests for /buscar-memoria, /debate, /contexto-semantico CLI commands.
"""
import sys
import os
import io
from unittest import mock

# Ensure package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.cli import (
    _slash_buscar_memoria,
    _slash_debate,
    _slash_contexto_semantico,
    COMMANDS,
)


def _capture(fn, *args):
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        fn(*args)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. /buscar-memoria requires args
# ---------------------------------------------------------------------------
def test_buscar_memoria_requires_args():
    out = _capture(_slash_buscar_memoria, "")
    assert "Uso:" in out
    assert "/buscar-memoria" in out


# ---------------------------------------------------------------------------
# 2. /debate requires args
# ---------------------------------------------------------------------------
def test_debate_requires_args():
    out = _capture(_slash_debate, "")
    assert "Uso:" in out
    assert "/debate" in out


# ---------------------------------------------------------------------------
# 3. /debate prints pro/con sections
# ---------------------------------------------------------------------------
def test_debate_prints_pro_con_sections():
    out = _capture(_slash_debate, "inteligencia artificial")
    assert "A FAVOR:" in out
    assert "EN CONTRA:" in out
    assert "CONCLUSION:" in out
    # At least one pro and one con line
    assert "+" in out
    assert "-" in out


# ---------------------------------------------------------------------------
# 4. /contexto-semantico requires args
# ---------------------------------------------------------------------------
def test_contexto_semantico_requires_args():
    out = _capture(_slash_contexto_semantico, "")
    assert "Uso:" in out
    assert "/contexto-semantico" in out


# ---------------------------------------------------------------------------
# 5. /buscar-memoria handles connection error gracefully
# ---------------------------------------------------------------------------
def test_buscar_memoria_handles_connection_error():
    import requests
    with mock.patch("requests.get", side_effect=Exception("connection refused")):
        out = _capture(_slash_buscar_memoria, "python")
    assert "no disponible" in out.lower() or "servicio" in out.lower()


# ---------------------------------------------------------------------------
# Bonus: commands registered in COMMANDS dict
# ---------------------------------------------------------------------------
def test_commands_registered():
    assert "/buscar-memoria" in COMMANDS
    assert "/debate" in COMMANDS
    assert "/contexto-semantico" in COMMANDS

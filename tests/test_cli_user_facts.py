"""
tests/test_cli_user_facts.py
Tests for CLI user facts and argument commands (Cycle 38B).
"""
import io
import sys
from unittest.mock import MagicMock, patch

import pytest

from cognia.cli import (
    _slash_cognia_aprende,
    _slash_cognia_olvida,
    _slash_cognia_sabe,
    _slash_argumento,
)


def _capture(fn, *args):
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn(*args)
    finally:
        sys.stdout = old
    return buf.getvalue()


# ---------------------------------------------------------------------------
# /cognia-sabe
# ---------------------------------------------------------------------------

def test_cognia_sabe_handles_error():
    """When the service is unavailable, prints a friendly error message."""
    with patch("requests.get", side_effect=Exception("connection refused")):
        out = _capture(_slash_cognia_sabe, "")
    assert "no disponible" in out.lower()


# ---------------------------------------------------------------------------
# /cognia-aprende
# ---------------------------------------------------------------------------

def test_cognia_aprende_requires_args():
    """Without args, prints usage hint."""
    out = _capture(_slash_cognia_aprende, "")
    assert "Uso:" in out
    assert "/cognia-aprende" in out


def test_cognia_aprende_shows_usage_example():
    """Usage line includes an example with 'Ejemplo:'."""
    out = _capture(_slash_cognia_aprende, "")
    assert "Ejemplo:" in out


# ---------------------------------------------------------------------------
# /cognia-olvida
# ---------------------------------------------------------------------------

def test_cognia_olvida_requires_numeric_id():
    """Non-numeric argument prints usage hint."""
    out = _capture(_slash_cognia_olvida, "abc")
    assert "Uso:" in out
    assert "/cognia-olvida" in out


# ---------------------------------------------------------------------------
# /argumento
# ---------------------------------------------------------------------------

def _fake_ai_arg(texto):
    """/argumento genera por el backend REAL desde 2026-07-16."""
    import types

    class _Orch:
        def infer(self, prompt, max_tokens=None, temperature=None):
            return types.SimpleNamespace(text=texto, mode="local")

    return types.SimpleNamespace(_orchestrator=_Orch())


def test_argumento_requires_args():
    """Without args, prints usage hint."""
    out = _capture(_slash_argumento, None, "")
    assert "Uso:" in out
    assert "/argumento" in out


def test_argumento_prints_tesis_antitesis_sintesis():
    """With a tesis, prints all three analysis sections (del modelo)."""
    ai = _fake_ai_arg("TESIS:\n  acceso universal\nANTITESIS:\n  calidad "
                      "desigual\nSINTESIS:\n  depende del financiamiento")
    out = _capture(_slash_argumento, ai, "la educacion publica es superior")
    assert "TESIS:" in out
    assert "ANTITESIS:" in out
    assert "SINTESIS:" in out

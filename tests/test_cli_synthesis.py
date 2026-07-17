"""
tests/test_cli_synthesis.py
Tests for /sintetizar, /y-si, /temas CLI commands (Cycle 29B).
"""
import sys
import os
import io
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cognia.cli import (
    _slash_sintetizar,
    _slash_y_si,
    _slash_temas,
)


def _capture(fn, *args):
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        fn(*args)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. /sintetizar requires args
# ---------------------------------------------------------------------------
def test_sintetizar_requires_args():
    out = _capture(_slash_sintetizar, None, "")
    assert "Uso:" in out


# ---------------------------------------------------------------------------
# 2. /y-si requires args
# ---------------------------------------------------------------------------
def _fake_ai(texto):
    """/y-si genera por el backend REAL desde 2026-07-16 (antes plantilla)."""
    import types

    class _Orch:
        def infer(self, prompt, max_tokens=None, temperature=None):
            return types.SimpleNamespace(text=texto, mode="local")

    return types.SimpleNamespace(_orchestrator=_Orch())


def test_y_si_requires_args():
    out = _capture(_slash_y_si, None, "")
    assert "Uso:" in out


# ---------------------------------------------------------------------------
# 3. /y-si prints escenario section (generada por el modelo)
# ---------------------------------------------------------------------------
def test_y_si_prints_escenario():
    ai = _fake_ai("Escenario probable:\n  adopcion masiva\nRiesgos:\n- x\n"
                  "Oportunidades:\n- y\nRecomendacion: pilotos chicos")
    out = _capture(_slash_y_si, ai, "todos usaran IA")
    assert "Escenario probable" in out
    assert "Riesgos" in out
    assert "Oportunidades" in out


# ---------------------------------------------------------------------------
# 4. /temas with empty history
# ---------------------------------------------------------------------------
def test_temas_empty_history():
    # Use the *exact* module the imported _slash_temas closure reads from.
    # An earlier test (test_cli_goal_*) may evict and re-import cognia.cli,
    # so `import cognia.cli` here could bind a different module instance whose
    # _history is not the one _slash_temas actually consults.
    cli_mod = sys.modules[_slash_temas.__module__]
    original = cli_mod._history[:]
    cli_mod._history.clear()
    try:
        out = _capture(_slash_temas, "")
        assert "No hay historial" in out
    finally:
        cli_mod._history[:] = original


# ---------------------------------------------------------------------------
# 5. /temas extracts frequent words
# ---------------------------------------------------------------------------
def test_temas_extracts_frequent_words():
    # See note in test_temas_empty_history: bind to the same module instance
    # that _slash_temas reads, not whatever `import cognia.cli` resolves to now.
    cli_mod = sys.modules[_slash_temas.__module__]
    original = cli_mod._history[:]
    cli_mod._history.clear()
    cli_mod._history.extend([
        {"role": "user", "content": "python python python inferencia modelos"},
        {"role": "assistant", "content": "respuesta del sistema"},
        {"role": "user", "content": "python machine learning inferencia"},
    ])
    try:
        out = _capture(_slash_temas, "")
        assert "python" in out
        assert "inferencia" in out
    finally:
        cli_mod._history[:] = original

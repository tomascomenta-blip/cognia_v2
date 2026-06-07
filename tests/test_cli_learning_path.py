"""
tests/test_cli_learning_path.py
Tests for CLI learning path and tagging commands (Cycle 37B).
"""
import io
import sys
from unittest.mock import MagicMock, patch

import pytest

from cognia.cli import (
    _slash_camino_avanzar,
    _slash_camino_nuevo,
    _slash_caminos,
    _slash_etiquetar,
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
# 1. /camino-nuevo requires args
# ---------------------------------------------------------------------------
def test_camino_nuevo_requires_args():
    out = _capture(_slash_camino_nuevo, "")
    assert "Uso:" in out


def test_camino_nuevo_whitespace_only_requires_args():
    out = _capture(_slash_camino_nuevo, "   ")
    assert "Uso:" in out


# ---------------------------------------------------------------------------
# 2. /caminos handles connection error gracefully
# ---------------------------------------------------------------------------
def test_caminos_handles_connection_error():
    with patch("requests.get", side_effect=Exception("refused")):
        out = _capture(_slash_caminos, "")
    assert "no disponible" in out.lower()


# ---------------------------------------------------------------------------
# 3. /camino-avanzar requires numeric id
# ---------------------------------------------------------------------------
def test_camino_avanzar_requires_numeric_id():
    out = _capture(_slash_camino_avanzar, "abc")
    assert "Uso:" in out


def test_camino_avanzar_empty_requires_numeric_id():
    out = _capture(_slash_camino_avanzar, "")
    assert "Uso:" in out


# ---------------------------------------------------------------------------
# 4. /etiquetar detects programacion tag
# ---------------------------------------------------------------------------
def test_etiquetar_detects_programacion():
    out = _capture(_slash_etiquetar, "necesito depurar esta funcion python")
    assert "programacion" in out


def test_etiquetar_detects_ia():
    out = _capture(_slash_etiquetar, "el modelo de inferencia usa un tensor de embedding")
    assert "ia" in out


# ---------------------------------------------------------------------------
# 5. /etiquetar returns general for unknown text
# ---------------------------------------------------------------------------
def test_etiquetar_returns_general_for_unknown():
    out = _capture(_slash_etiquetar, "hola como estas hoy en el parque")
    assert "general" in out


def test_etiquetar_requires_args():
    out = _capture(_slash_etiquetar, "")
    assert "Uso:" in out

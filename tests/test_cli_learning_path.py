"""
tests/test_cli_learning_path.py
Tests for CLI learning path and tagging commands (Cycle 37B).
"""
import io
import sys
from unittest.mock import MagicMock, patch

import pytest

import cognia.cli as cli
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
# 2. /caminos works locally with no active paths (no :8765 dependency)
# ---------------------------------------------------------------------------
def test_caminos_empty_no_http(tmp_path, monkeypatch):
    from cognia.learning.learning_path import LearningPathGenerator
    db = str(tmp_path / "lp.db")
    monkeypatch.setattr(cli, "_lpath_gen", lambda: LearningPathGenerator(db_path=db))
    out = _capture(_slash_caminos, "")
    assert "no disponible" not in out.lower()


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

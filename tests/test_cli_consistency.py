"""
tests/test_cli_consistency.py
Tests for CLI consistency commands: /conflictos-kg, /verificar-kg,
/resolver-conflicto, /comandos.
Cycle 40B
"""
import sys
import io
import pytest
from unittest.mock import patch, MagicMock

from cognia.cli import (
    _slash_conflictos_kg,
    _slash_verificar_kg,
    _slash_resolver_conflicto,
    _slash_comandos,
    _CMD_DESCRIPTIONS,
)


def _capture(fn, *args):
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        fn(*args)
    return buf.getvalue()


# 1. /conflictos-kg handles connection error gracefully
def test_conflictos_kg_handles_error():
    with patch("requests.get", side_effect=Exception("connection refused")):
        out = _capture(_slash_conflictos_kg, "")
    assert "no disponible" in out.lower() or "servicio" in out.lower()


# 2. /verificar-kg handles connection error gracefully
def test_verificar_kg_handles_error():
    with patch("requests.post", side_effect=Exception("connection refused")):
        out = _capture(_slash_verificar_kg, "")
    assert "no disponible" in out.lower() or "servicio" in out.lower()


# 3. /resolver-conflicto requires a numeric id
def test_resolver_conflicto_requires_numeric_id():
    out = _capture(_slash_resolver_conflicto, "abc")
    assert "Uso:" in out
    out2 = _capture(_slash_resolver_conflicto, "")
    assert "Uso:" in out2


# 4. /comandos shows total count matching _CMD_DESCRIPTIONS
def test_comandos_shows_total_count():
    out = _capture(_slash_comandos, "")
    total = len(_CMD_DESCRIPTIONS)
    assert str(total) in out
    assert "total" in out.lower()


# 5. /comandos shows "Categorias principales" line
def test_comandos_shows_categorias_line():
    out = _capture(_slash_comandos, "")
    assert "Categorias" in out or "categorias" in out.lower()

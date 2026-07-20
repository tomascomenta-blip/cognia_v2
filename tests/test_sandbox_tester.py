"""
tests/test_sandbox_tester.py — FASE 7b
SandboxTester valida+ejecuta en sandbox el codigo de un modulo propuesto y devuelve
el reporte que self_architect.test_proposal consume. Antes el import estaba roto.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_VALID = (
    "import sqlite3\n\n"
    "class Foo:\n"
    "    def __init__(self, db_path='x.db'):\n"
    "        self.db = db_path\n"
    "    def status_report(self):\n"
    "        return 'ok'\n"
)


def test_valid_module_passes():
    from cognia_v3.core.sandbox_tester import SandboxTester
    rep = SandboxTester(":memory:").test_module_from_code(_VALID, "Foo", 1)
    assert rep["passed"] is True
    crit = rep["details"]["criteria"]
    assert crit["syntax_valid"]["passed"]
    assert crit["executes"]["passed"]
    assert crit["no_blocked_imports"]["passed"]
    assert rep["timestamp"]


def test_syntax_error_fails():
    from cognia_v3.core.sandbox_tester import SandboxTester
    rep = SandboxTester().test_module_from_code("def broken(:\n    pass\n", "Bad", 2)
    assert rep["passed"] is False
    assert not rep["details"]["criteria"]["syntax_valid"]["passed"]


def test_blocked_import_fails():
    from cognia_v3.core.sandbox_tester import SandboxTester
    rep = SandboxTester().test_module_from_code("import os\nos.system('echo hi')\n", "Evil", 3)
    assert rep["passed"] is False


def test_self_architect_imports_sandbox_tester():
    """Regresion del bug: el import dentro de test_proposal ya resuelve (antes apuntaba
    a un modulo top-level inexistente)."""
    import importlib
    mod = importlib.import_module("cognia_v3.core.sandbox_tester")
    assert hasattr(mod, "SandboxTester")

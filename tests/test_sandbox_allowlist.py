"""
tests/test_sandbox_allowlist.py
===============================
S5 (prompt de auto-mejora, Fase 1): allowlist de imports para CODIGO AUTO-GENERADO
(regla 9 de CLAUDE.md). Mas estricto que la blocklist: rechaza imports validos-pero-no-
previstos (p.ej. pathlib) que la blocklist conocida no captura. Compuerta ANTES de ejecutar.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia_v3.interfaces.code_executor import (
    validate_generated_module_imports, ALLOWED_IMPORTS_GENERATED, BLOCKED_IMPORTS_PYTHON,
)
from cognia_v3.core.sandbox_tester import SandboxTester


# ── validate_generated_module_imports (allowlist AST) ────────────────

def test_allowlisted_only_passes():
    code = ("import sqlite3\nimport json\nfrom datetime import datetime\n"
            "from typing import Optional\nclass M:\n    pass\n")
    ok, offending = validate_generated_module_imports(code)
    assert ok is True
    assert offending == []


def test_socket_rejected():
    ok, offending = validate_generated_module_imports("import socket\n")
    assert ok is False
    assert "socket" in offending


def test_from_os_rejected():
    ok, offending = validate_generated_module_imports("from os import path\n")
    assert ok is False
    assert "os" in offending


def test_pathlib_rejected_even_though_not_blocklisted():
    """The allowlist's reason to exist: pathlib is NOT dangerous-by-blocklist but is
    also NOT explicitly allowed -> rejected. A blocklist alone would let it through."""
    code = "import pathlib\n"
    ok, offending = validate_generated_module_imports(code)
    assert ok is False
    assert "pathlib" in offending
    # confirm the blocklist would NOT have caught it
    assert "pathlib" not in BLOCKED_IMPORTS_PYTHON
    assert "pathlib" not in ALLOWED_IMPORTS_GENERATED


def test_relative_import_rejected():
    ok, offending = validate_generated_module_imports("from . import helpers\n")
    assert ok is False
    assert "<relative import>" in offending


def test_syntax_error_rejected():
    ok, offending = validate_generated_module_imports("import (((\n")
    assert ok is False
    assert "<syntax error>" in offending


# ── sandbox_tester gates on the allowlist ────────────────────────────

def test_sandbox_rejects_non_allowlisted_import():
    code = ("import pathlib\nclass Widget:\n"
            "    def status_report(self):\n        return 'x'\n")
    report = SandboxTester().test_module_from_code(code, "Widget", 1)
    crit = report["details"]["criteria"]
    assert report["passed"] is False
    assert crit["imports_allowlisted"]["passed"] is False
    assert "pathlib" in crit["imports_allowlisted"]["value"]
    # not executed because it failed the allowlist gate
    assert crit["executes"]["passed"] is False
    # and the blocklist alone would NOT have flagged pathlib
    assert crit["no_blocked_imports"]["passed"] is True


def test_sandbox_accepts_allowlisted_module():
    code = ("import sqlite3\nimport json\nclass Widget:\n"
            "    def __init__(self, db_path='x.db'):\n        self.db = db_path\n"
            "    def status_report(self):\n        return 'ok'\n")
    report = SandboxTester().test_module_from_code(code, "Widget", 2)
    crit = report["details"]["criteria"]
    assert crit["imports_allowlisted"]["passed"] is True

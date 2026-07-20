"""
Regresion del fix F1 (E2E comercial 2026-07-05): el env del subprocess sandbox
omitia SystemRoot -> Node/OpenSSL crasheaba en Windows con
'Assertion failed: ncrypto::CSPRNG'. _sandbox_env ahora pasa los vars de sistema
imprescindibles de Windows SIN filtrar el entorno completo (no fuga secretos).
"""
from __future__ import annotations

import shutil

import pytest

from cognia_v3.interfaces.code_executor import _sandbox_env, run_javascript


def test_sandbox_env_includes_systemroot_when_present(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("SECRET_TOKEN", "pypi-should-not-leak")
    env = _sandbox_env()
    assert env.get("SystemRoot") == r"C:\Windows"     # el var critico de Windows
    assert "SECRET_TOKEN" not in env                  # NO filtra el entorno del padre
    assert env["TERM"] == "dumb" and "PATH" in env    # base sandbox intacta


def test_sandbox_env_extra_merges():
    env = _sandbox_env({"PYTHONPATH": ""})
    assert env["PYTHONPATH"] == ""


@pytest.mark.skipif(shutil.which("node") is None, reason="node no instalado")
def test_run_javascript_works_end_to_end():
    # el bug F1: esto crasheaba en Windows por falta de SystemRoot
    r = run_javascript("console.log(1+1)")
    assert r.success and r.output.strip() == "2", (r.output, r.errors)


@pytest.mark.skipif(shutil.which("node") is None, reason="node no instalado")
def test_run_javascript_crypto_csprng():
    # el CSPRNG de Node (el que fallaba sin SystemRoot)
    r = run_javascript('const c=require("crypto"); console.log(c.randomBytes(4).toString("hex"))')
    assert r.success and len(r.output.strip()) >= 8, (r.output, r.errors)

"""
Tests for self-extending tools (cognia/agent/tool_synthesis.py).

Pins the safety contract: a tool is registered ONLY if it parses, defines run(),
passes the static safety scan, executes cleanly in the sandbox, and produces the
expected output. Anything else is rejected and never written.
"""

import pytest

from cognia.agent import tool_synthesis as TS


@pytest.fixture(autouse=True)
def _isolate_generated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(TS, "GENERATED_DIR", tmp_path / "gen")
    monkeypatch.setattr(TS, "MANIFEST_PATH", tmp_path / "gen" / "_manifest.json")


def _spec(name="invertir_texto", ti="hola", exp="aloh"):
    return TS.ToolSpec(name=name, doc="invierte texto", purpose="invierte la cadena",
                       test_input=ti, expect_contains=exp)


# ── verification ───────────────────────────────────────────────────────

def test_good_pure_tool_verifies():
    ok, reason = TS.verify_tool("def run(args):\n    return args[::-1]\n", "hola", "aloh")
    assert ok, reason


def test_missing_run_rejected():
    ok, reason = TS.verify_tool("def otra(a):\n    return a\n", "x", "x")
    assert not ok and "run()" in reason


def test_wrong_output_rejected():
    ok, reason = TS.verify_tool("def run(args):\n    return 'nope'\n", "hola", "aloh")
    assert not ok and "no contiene" in reason


def test_dangerous_import_rejected_statically():
    ok, reason = TS.verify_tool(
        "import os\ndef run(args):\n    return os.getcwd()\n", "x", "x"
    )
    assert not ok and "import no permitido" in reason


def test_forbidden_builtin_rejected():
    ok, reason = TS.verify_tool(
        "def run(args):\n    return open('/etc/passwd').read()\n", "x", "x"
    )
    assert not ok and ("prohibida" in reason or "import" in reason)


def test_allowed_stdlib_import_ok():
    code = "import math\ndef run(args):\n    return str(math.sqrt(float(args)))\n"
    ok, reason = TS.verify_tool(code, "16", "4.0")
    assert ok, reason


# ── synthesize -> register -> load ─────────────────────────────────────

def test_synthesize_registers_only_verified(tmp_path):
    res = TS.synthesize_and_register(_spec(), code="def run(args):\n    return args[::-1]\n")
    assert res["ok"]
    assert (TS.GENERATED_DIR / "invertir_texto.py").exists()
    manifest = TS._load_manifest()
    assert any(e["name"] == "invertir_texto" and e["verified"] for e in manifest)


def test_failed_tool_is_not_written():
    res = TS.synthesize_and_register(_spec(name="rota"), code="import os\ndef run(a):\n return os.getcwd()\n")
    assert not res["ok"]
    assert not (TS.GENERATED_DIR / "rota.py").exists()
    assert TS._load_manifest() == []


def test_invalid_name_rejected():
    res = TS.synthesize_and_register(_spec(name="Mal-Nombre"), code="def run(a):\n return a\n")
    assert not res["ok"] and "nombre" in res["reason"]


def test_load_generated_tools_into_registry_and_run():
    TS.synthesize_and_register(_spec(), code="def run(args):\n    return args[::-1]\n")
    reg = {}
    n = TS.load_generated_tools(registry=reg)
    assert n == 1
    assert "invertir_texto" in reg
    out = reg["invertir_texto"]["fn"]("mundo", {})
    assert out == "RESULTADO invertir_texto: odnum"


def test_loaded_tool_wraps_exceptions():
    # A tool that blows up at call time must return an ERROR string, not raise.
    TS.synthesize_and_register(
        _spec(name="parte", ti="5", exp="2"),
        code="def run(args):\n    return str(int(args) // 2)\n",
    )
    reg = {}
    TS.load_generated_tools(registry=reg)
    assert "ERROR" in reg["parte"]["fn"]("no-es-numero", {})


def test_clean_code_fences_anidados():
    """El 3B cierra con varios ``` seguidos (`` ``` ```python ... ``` ``` `` );
    _clean_code debe devolver codigo que parsea, sin backticks sueltos ni
    prosa posterior. Regresion de la demo CP2 (2026-07-03)."""
    import ast
    from cognia.agent.tool_synthesis import _clean_code
    cases = [
        ' ``` ```python\ndef run(a):\n    return str(len(a.split()))\n``` ``` ```',
        "def run(a):\n    return a[::-1]\n",
        "```python\ndef run(a):\n    return a.upper()\n```",
        "Aca esta:\n```python\ndef run(a):\n    return a\n```\nEso es todo.",
    ]
    for raw in cases:
        c = _clean_code(raw)
        assert "def run" in c
        assert not c.rstrip().endswith("`")
        ast.parse(c)  # no debe levantar SyntaxError

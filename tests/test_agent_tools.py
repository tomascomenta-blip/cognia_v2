"""
Tests for the concrete agent tool registry (cognia/agent/tools.py).

Pins that every tool is callable, returns a RESULTADO string, that the registry
doc and dispatch stay in sync, and that the safety blocks hold.
"""

import types

import pytest

from cognia.agent import tools as T


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


def test_registry_has_core_and_new_tools():
    names = set(T.TOOLS)
    # Ported originals...
    assert {"leer_archivo", "escribir_archivo", "buscar", "ejecutar",
            "memorizar", "anotar", "notas"} <= names
    # ...and the new ones the user asked for.
    assert {"recordar", "kg_buscar", "kg_agregar", "calcular", "http_get",
            "arbol", "git_estado", "tests", "py_validar"} <= names


def test_build_tools_doc_lists_registered_tools():
    doc = T.build_tools_doc()
    for name in ("recordar", "calcular", "escribir_archivo"):
        assert name in doc


def test_file_roundtrip(tmp_path):
    f = str(tmp_path / "x.txt")
    ctx = _ctx()
    assert "OK" in T.run_tool("escribir_archivo", f + " | hola\nmundo", ctx)
    assert "hola" in T.run_tool("leer_archivo", f, ctx)
    assert "OK" in T.run_tool("apendar_archivo", f + " | tercera", ctx)
    assert "3 lineas" in T.run_tool("contar_lineas", f, ctx)


def test_escribir_archivo_records_in_agent_state(tmp_path):
    f = str(tmp_path / "sub" / "y.txt")
    ctx = _ctx()
    T.run_tool("escribir_archivo", f + " | data", ctx)
    assert f in ctx["agent_state"]["files_touched"]


def test_escribir_archivo_strips_code_fences(tmp_path):
    f = tmp_path / "z.py"
    ctx = _ctx()
    T.run_tool("escribir_archivo", str(f) + " | ```python\nx = 1\n```", ctx)
    assert f.read_text(encoding="utf-8") == "x = 1"


def test_calcular_exact():
    assert "1039" in T.run_tool("calcular", "2**10 + 5*3", _ctx())


def test_calcular_rejects_non_arithmetic():
    out = T.run_tool("calcular", "__import__('os').system('x')", _ctx())
    assert "ERROR" in out and "1039" not in out


def test_ejecutar_blocks_dangerous_commands():
    for bad in ("rm -rf /", "shutdown now", "mkfs.ext4 /dev/sda"):
        assert "BLOQUEADO" in T.run_tool("ejecutar", bad, _ctx())


def test_unknown_tool_is_handled():
    out = T.run_tool("inventada", "x", _ctx())
    assert "no existe" in out


def test_run_tool_never_raises_on_bad_args():
    # leer_archivo on a missing file must return an ERROR string, not raise.
    out = T.run_tool("leer_archivo", "/nope/does/not/exist.xyz", _ctx())
    assert "ERROR" in out


def test_anotar_and_notas_share_working_memory():
    ctx = _ctx()
    T.run_tool("anotar", "plan | hacer X", ctx)
    assert ctx["working_memory"]["plan"] == "hacer X"
    assert "hacer X" in T.run_tool("notas", "", ctx)


def test_recordar_uses_episodic_memory():
    fake_ai = types.SimpleNamespace(
        episodic=types.SimpleNamespace(
            retrieve_similar=lambda vec, top_k=5: [
                {"observation": "el parser de facturas quedo listo", "similarity": 0.91},
            ]
        )
    )
    out = T.run_tool("recordar", "facturas", _ctx(ai=fake_ai))
    assert "parser de facturas" in out


def test_kg_agregar_validates_relation():
    fake_ai = types.SimpleNamespace(
        kg=types.SimpleNamespace(add_triple=lambda *a, **k: True)
    )
    ok = T.run_tool("kg_agregar", "cognia | is_a | sistema", _ctx(ai=fake_ai))
    assert "OK" in ok
    bad = T.run_tool("kg_agregar", "cognia | relacion_falsa | x", _ctx(ai=fake_ai))
    assert "invalida" in bad

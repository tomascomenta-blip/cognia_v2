"""
Tests for the concrete agent tool registry (cognia/agent/tools.py).

Pins that every tool is callable, returns a RESULTADO string, that the registry
doc and dispatch stay in sync, and that the safety blocks hold.
"""

import sys
import types

import pytest

import cognia.agents.workers.dev_tools as dev_tools
from cognia.agent import tools as T


def _ctx(**over):
    c = {"working_memory": {}, "agent_state": {}, "print_fn": lambda *a, **k: None}
    c.update(over)
    return c


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Workspace del agente = tmp_path (mismo patron que test_agent_tools_tier1)."""
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


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


def test_file_roundtrip(workspace):
    f = str(workspace / "x.txt")
    ctx = _ctx()
    assert "OK" in T.run_tool("escribir_archivo", f + " | hola\nmundo", ctx)
    assert "hola" in T.run_tool("leer_archivo", f, ctx)
    assert "OK" in T.run_tool("apendar_archivo", f + " | tercera", ctx)
    assert "3 lineas" in T.run_tool("contar_lineas", f, ctx)


def test_escribir_archivo_records_in_agent_state(workspace):
    f = str(workspace / "sub" / "y.txt")
    ctx = _ctx()
    T.run_tool("escribir_archivo", f + " | data", ctx)
    # files_touched guarda el path RESUELTO (post-confinamiento)
    assert str((workspace / "sub" / "y.txt").resolve()) in ctx["agent_state"]["files_touched"]


def test_escribir_archivo_strips_code_fences(workspace):
    f = workspace / "z.py"
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


def test_ejecutar_blocks_windows_disk_format_only():
    # El borrado de disco real SI se bloquea...
    for bad in ("format c:", "format d: /q"):
        assert "BLOQUEADO" in T.run_tool("ejecutar", bad, _ctx())


def test_ejecutar_allows_benign_format_substrings():
    # ...pero 'format' como substring de comandos benignos NO (antes se bloqueaba
    # 'ruff format .', 'git log --pretty=format:%H'). Se usa echo para no tener
    # efectos: prueba que el gate NO bloquea, no que ruff/git corran.
    out = T.run_tool("ejecutar", "echo ruff format aca", _ctx())
    assert "BLOQUEADO" not in out and "ruff format aca" in out
    out2 = T.run_tool("ejecutar", "echo pretty=format:%H", _ctx())
    assert "BLOQUEADO" not in out2


def test_tests_requires_explicit_path_and_uses_sys_executable(monkeypatch):
    captured = {}

    def fake_shell(cmd, ctx, timeout=30):
        captured["cmd"] = cmd
        return "RESULTADO ejecutar: ok"

    monkeypatch.setattr(T, "_shell", fake_shell)
    # sin ruta -> error accionable, NO ejecuta la suite entera
    out = T.run_tool("tests", "", _ctx())
    assert "ruta ESPECIFICA" in out and "cmd" not in captured
    # con ruta -> usa el interprete que corre el agente (no 'python' pelado)
    T.run_tool("tests", "tests/test_foo.py", _ctx())
    assert f'"{sys.executable}"' in captured["cmd"]


def test_escribir_tolerant_pipe_separator(workspace):
    # El 3B suele emitir 'path|contenido' sin espacios alrededor del pipe.
    assert "OK" in T.run_tool("escribir_archivo", "a.txt|hola", _ctx())
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "hola"
    assert "OK" in T.run_tool("escribir_archivo", "b.txt |mundo", _ctx())
    assert (workspace / "b.txt").read_text(encoding="utf-8") == "mundo"


def test_leer_archivo_marks_truncation(workspace):
    big = workspace / "big.txt"
    big.write_text("x" * 5000, encoding="utf-8")
    out = T.run_tool("leer_archivo", str(big), _ctx())
    assert "TRUNCADO" in out and "5000" in out
    small = workspace / "small.txt"
    small.write_text("hola corto", encoding="utf-8")
    assert "TRUNCADO" not in T.run_tool("leer_archivo", str(small), _ctx())


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


# ── confinamiento de escrituras al workspace (CYCLE 6) ─────────────────
# Las tools de escritura del loop ReAct reusan resolve_write_path() de
# dev_tools: relativo -> dentro del workspace; fuera / traversal / nombre
# sensible -> string de ERROR (nunca escribe). Las de lectura no se tocan.

def test_escribir_relativo_cae_en_workspace(workspace):
    out = T.run_tool("escribir_archivo", "rel/nuevo.txt | data", _ctx())
    assert "OK" in out
    assert (workspace / "rel" / "nuevo.txt").read_text(encoding="utf-8") == "data"


def test_escribir_absoluto_fuera_rechazado(workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("fuera") / "evil.txt"
    out = T.run_tool("escribir_archivo", f"{outside} | pwned", _ctx())
    assert "ERROR" in out and "outside agent workspace" in out
    assert not outside.exists()


def test_escribir_traversal_rechazado(workspace):
    out = T.run_tool("escribir_archivo", "../evil.txt | pwned", _ctx())
    assert "ERROR" in out and "outside agent workspace" in out
    assert not (workspace.parent / "evil.txt").exists()


def test_escribir_nombres_bloqueados(workspace):
    for name in (".env", "x.env", "my_secrets.txt", "foo.exe", "lib.dll"):
        out = T.run_tool("escribir_archivo", f"{name} | data", _ctx())
        assert "ERROR" in out and "blocked file name" in out, name
        assert not (workspace / name).exists()


def test_apendar_fuera_rechazado(workspace):
    out = T.run_tool("apendar_archivo", "../evil.txt | linea", _ctx())
    assert "ERROR" in out and "outside agent workspace" in out
    assert not (workspace.parent / "evil.txt").exists()


def test_apendar_dentro_ok(workspace):
    assert "OK" in T.run_tool("apendar_archivo", "log.txt | linea", _ctx())
    assert "linea" in (workspace / "log.txt").read_text(encoding="utf-8")


def test_copiar_dst_fuera_rechazado(workspace):
    (workspace / "src.txt").write_text("data", encoding="utf-8")
    out = T.run_tool("copiar_archivo", f"{workspace / 'src.txt'} | ../robado.txt", _ctx())
    assert "ERROR" in out and "outside agent workspace" in out
    assert not (workspace.parent / "robado.txt").exists()


def test_copiar_dentro_ok(workspace):
    (workspace / "src.txt").write_text("data", encoding="utf-8")
    out = T.run_tool("copiar_archivo", f"{workspace / 'src.txt'} | copia.txt", _ctx())
    assert "OK" in out
    assert (workspace / "copia.txt").read_text(encoding="utf-8") == "data"


def test_copiar_src_fuera_dst_dentro_permitido(workspace, tmp_path_factory):
    # Leer desde fuera es legitimo (igual que leer_archivo); solo dst se confina.
    src = tmp_path_factory.mktemp("lectura") / "origen.txt"
    src.write_text("contenido externo", encoding="utf-8")
    out = T.run_tool("copiar_archivo", f"{src} | traido.txt", _ctx())
    assert "OK" in out
    assert (workspace / "traido.txt").read_text(encoding="utf-8") == "contenido externo"

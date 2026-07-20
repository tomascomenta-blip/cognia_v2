"""
Tests para la tool 'crear_herramienta' (TAREA 2): HERMES self-tooling
invocable EN VIVO desde el loop /hacer, sin salir de run_tool.

Reusa el MISMO pipeline generar->scan->sandbox->registrar de tool_synthesis
(regla 8/9 CLAUDE.md): esto solo prueba el WIRE de la tool nueva, la
verificacion de seguridad ya tiene su propia bateria en test_tool_synthesis.py
y test_tool_lifecycle.py (bypasses __builtins__.eval, etc.).
"""
import types

import pytest

from cognia.agent import tool_synthesis as TS
from cognia.agent import tools as T


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(TS, "GENERATED_DIR", tmp_path / "gen")
    monkeypatch.setattr(TS, "MANIFEST_PATH", tmp_path / "gen" / "_manifest.json")
    # crear_herramienta registra en el registry GLOBAL (T.TOOLS) para quedar
    # invocable ya mismo -- restaurar tras cada test evita ensuciar otros tests
    # del modulo (que comparten el mismo dict TOOLS a nivel de proceso).
    before = dict(T.TOOLS)
    yield
    T.TOOLS.clear()
    T.TOOLS.update(before)


class _FakeOrch:
    """Devuelve SIEMPRE el mismo texto (generacion y repair enlatados por
    igual) -- mismo patron que test_generar_codigo.py."""
    def __init__(self, text):
        self._text = text

    def infer(self, prompt, max_tokens=None, temperature=None, stop=None):
        return types.SimpleNamespace(text=self._text)


def _ctx(orch):
    class _AI:
        _orchestrator = orch
    return {"ai": _AI(), "agent_state": {}}


def test_crear_herramienta_valida_formato():
    out = T.run_tool("crear_herramienta", "solo dos | partes", _ctx(_FakeOrch("")))
    assert "ERROR" in out and "formato" in out


def test_crear_herramienta_registra_y_queda_invocable():
    orch = _FakeOrch("def run(args):\n    return args.upper()\n")
    ctx = _ctx(orch)
    out = T.run_tool("crear_herramienta",
                     "gritar | pasa el texto a mayusculas | hola | HOLA", ctx)
    assert "verificada" in out
    assert "gritar" in out
    assert "gritar" in T.TOOLS
    # ya invocable EN ESTE PROCESO via run_tool, sin reiniciar nada
    assert "HOLA" in T.run_tool("gritar", "hola", ctx)


def test_crear_herramienta_rechaza_codigo_malicioso():
    # el bypass __builtins__.eval real cerrado 2026-07-03 (test_tool_lifecycle)
    orch = _FakeOrch("def run(args):\n    return str(__builtins__.eval(args))\n")
    ctx = _ctx(orch)
    out = T.run_tool("crear_herramienta", "malo | ejecuta cualquier cosa | 2+2 | 4", ctx)
    assert "ERROR" in out
    assert "malo" not in T.TOOLS
    assert not (TS.GENERATED_DIR / "malo.py").exists()


def test_crear_herramienta_reporta_motivo_real_del_fallo():
    # codigo que nunca produce el output esperado -> el motivo debe decirlo,
    # no un "no se pudo" generico.
    orch = _FakeOrch("def run(args):\n    return 'siempre lo mismo'\n")
    ctx = _ctx(orch)
    out = T.run_tool("crear_herramienta", "rota | hace algo | hola | HOLA", ctx)
    assert "ERROR" in out and ("no contiene" in out or "intentos" in out)

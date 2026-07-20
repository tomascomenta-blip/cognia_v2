# -*- coding: utf-8 -*-
"""Flujos estilo n8n (flows.py): validación DAG, ejecución con interpolación,
retries, condicionales, from_plan. run_tool fake (sin modelo)."""
import pytest

from cognia.agent.flows import (FlowError, ejecutar, from_json, from_plan,
                                to_json, validar)


def _fake_run(registro):
    """Devuelve un run_tool(name,args,ctx) que consulta un dict tool->fn."""
    def run(name, args, ctx):
        return registro[name](args)
    return run


def test_validar_orden_topologico():
    flujo = {"nodos": [
        {"id": "a", "tool": "t", "wires": ["b", "c"]},
        {"id": "b", "tool": "t", "wires": ["d"]},
        {"id": "c", "tool": "t", "wires": ["d"]},
        {"id": "d", "tool": "t", "wires": []}]}
    orden = validar(flujo)
    assert orden.index("a") < orden.index("b") < orden.index("d")
    assert orden.index("c") < orden.index("d")


def test_validar_detecta_ciclo():
    flujo = {"nodos": [
        {"id": "a", "tool": "t", "wires": ["b"]},
        {"id": "b", "tool": "t", "wires": ["a"]}]}
    with pytest.raises(FlowError, match="CICLO"):
        validar(flujo)


def test_validar_wire_colgado_y_dup():
    with pytest.raises(FlowError, match="inexistente"):
        validar({"nodos": [{"id": "a", "tool": "t", "wires": ["zzz"]}]})
    with pytest.raises(FlowError, match="duplicados"):
        validar({"nodos": [{"id": "a", "tool": "t"}, {"id": "a", "tool": "t"}]})


def test_validar_tool_inexistente():
    with pytest.raises(FlowError, match="no existe"):
        validar({"nodos": [{"id": "a", "tool": "fantasma"}]},
                tool_existe=lambda n: n in {"real"})


def test_ejecutar_encadena_e_interpola():
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "hola", "wires": ["b"]},
        {"id": "b", "tool": "eco", "args": "vi: {{a}}", "wires": []}]}
    reg = {"eco": lambda a: f"RESULTADO eco: {a}"}
    r = ejecutar(flujo, {}, _fake_run(reg))
    assert r["salidas"]["a"] == "RESULTADO eco: hola"
    assert "vi: RESULTADO eco: hola" in r["salidas"]["b"]
    assert r["errores"] == {}


def test_ejecutar_reintenta_hasta_ok():
    intentos = {"n": 0}

    def flaky(args):
        intentos["n"] += 1
        return "RESULTADO x: ok" if intentos["n"] >= 2 else "RESULTADO x ERROR: fallo"

    flujo = {"nodos": [{"id": "a", "tool": "f", "args": "", "reintentos": 2,
                        "wires": []}]}
    r = ejecutar(flujo, {}, _fake_run({"f": flaky}))
    assert intentos["n"] == 2
    assert r["errores"] == {}


def test_ejecutar_error_no_frena_flujo():
    flujo = {"nodos": [
        {"id": "a", "tool": "malo", "args": "", "wires": ["b"]},
        {"id": "b", "tool": "bueno", "args": "sigo", "wires": []}]}
    reg = {"malo": lambda a: "RESULTADO malo ERROR: boom",
           "bueno": lambda a: "RESULTADO bueno: ok"}
    r = ejecutar(flujo, {}, _fake_run(reg))
    assert "a" in r["errores"]
    assert r["salidas"]["b"] == "RESULTADO bueno: ok"   # b igual corrió


def test_ejecutar_saltar_si():
    flujo = {"nodos": [
        {"id": "a", "tool": "eco", "args": "todo bien", "wires": ["b"]},
        {"id": "b", "tool": "eco", "args": "x", "saltar_si": "bien", "wires": []}]}
    reg = {"eco": lambda a: f"RESULTADO eco: {a}"}
    r = ejecutar(flujo, {}, _fake_run(reg))
    assert "b" in r["saltados"]


def test_from_plan_lineal():
    pasos = [{"description": "leer x", "tool_required": "leer_archivo"},
             {"description": "resumir", "tool_required": "resumir"}]
    flujo = from_plan("mi flujo", pasos)
    assert flujo["nombre"] == "mi flujo"
    orden = validar(flujo)
    assert orden == ["n0", "n1"]
    assert flujo["nodos"][0]["tool"] == "leer_archivo"
    assert flujo["nodos"][0]["wires"] == ["n1"]


def test_roundtrip_json():
    flujo = {"nombre": "f", "nodos": [{"id": "a", "tool": "t", "args": "x",
                                       "wires": []}]}
    assert from_json(to_json(flujo)) == flujo
    with pytest.raises(FlowError):
        from_json('{"foo": 1}')

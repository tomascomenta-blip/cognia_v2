# -*- coding: utf-8 -*-
"""generar_codigo tiene que decir QUE HACER cuando no puede, no solo que fallo.

Medido el 2026-08-13 con scripts/diag_tarea_python.py contra el modelo real:
ante "escribi y ejecuta un script python que imprima la suma de 100 mas 250"
(un SCRIPT, no una funcion) el modelo elegia `generar_codigo`, recibia
"no identifique el nombre de la funcion" y reintentaba IDENTICO hasta que el
detector de estancamiento mataba la tarea. Con la salida alternativa nombrada
en el propio mensaje de error, la tarea pasa de 4/6 a 8/8, y el gate del camino
feliz de 1/4 corridas en 5/5 a 3/3.

El test NO llama al modelo: fija el contrato del mensaje, que es lo que cambia
el comportamiento.
"""

from __future__ import annotations

import pytest

from cognia.agent.tools import run_tool


def _ctx(tmp_path):
    return {"working_memory": {}, "agent_state": {}, "workspace": str(tmp_path)}


@pytest.fixture(autouse=True)
def _en_tmp(tmp_path, monkeypatch):
    from cognia.agents.workers import dev_tools
    monkeypatch.setattr(dev_tools, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)


def test_sin_nombre_de_funcion_nombra_la_herramienta_alternativa(tmp_path):
    salida = run_tool("generar_codigo",
                      "suma.py | un script que imprima la suma de 100 mas 250",
                      _ctx(tmp_path))
    assert "ERROR" in salida
    assert "escribir_archivo" in salida, (
        "el modelo se queda sin salida: el error tiene que nombrar la "
        "herramienta que SI sirve, o reintenta lo mismo hasta agotar la tarea")
    assert "ejecutar" in salida


def test_sigue_diciendo_como_pedir_una_funcion(tmp_path):
    """La via original no se pierde: si queria una funcion, que sepa completarla."""
    salida = run_tool("generar_codigo", "suma.py | calcula cosas", _ctx(tmp_path))
    assert "suma(a, b)" in salida or "nombre(args)" in salida


def test_con_nombre_de_funcion_no_devuelve_ese_error(tmp_path):
    """Con el nombre presente, el rechazo por 'no identifique el nombre' no aplica.

    No se comprueba que genere codigo (eso llama al modelo): solo que el fallo
    de arriba ya no es el que corta.
    """
    salida = run_tool("generar_codigo", "suma.py | implementa suma(a, b)",
                      _ctx(tmp_path))
    assert "no encuentro su nombre" not in salida


# ── la firma suelta ────────────────────────────────────────────────────
@pytest.mark.parametrize("texto,esperado", [
    ("implementa suma(a, b)", "suma"),
    ("suma(a, b)", "suma"),               # exactamente lo que pide la ayuda
    ("suma(a,b)", "suma"),
    ("calcula el total(items) del carrito", "total"),
])
def test_firma_suelta_reconoce_lo_que_la_ayuda_pide(texto, esperado):
    """extract_entry_point exige la palabra 'funcion' antes de la firma; la
    ayuda de la tool pide solo `nombre(args)`. Ese hueco es el que se cubre."""
    from cognia.agent.stepwise import extract_entry_point
    from cognia.agent.tools import _firma_suelta
    assert extract_entry_point(texto) is None, (
        "si extract_entry_point ya lo reconoce, este fallback sobra")
    assert _firma_suelta(texto) == esperado


@pytest.mark.parametrize("texto", [
    "un script que imprima la suma de 100 mas 250",   # la tarea del gate: NO es funcion
    "que imprima(350)",                               # verbo de la consigna
    "usa print(x) para mostrarlo",                    # builtin
    "sin firma ninguna",
])
def test_firma_suelta_no_inventa_funciones(texto):
    from cognia.agent.tools import _firma_suelta
    assert _firma_suelta(texto) is None

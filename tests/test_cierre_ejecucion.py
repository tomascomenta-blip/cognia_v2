# -*- coding: utf-8 -*-
"""Cierre informativo E8: task_pide_ejecucion + wiring del nudge en el loop."""
import pytest

from cognia.agent.loop import task_pide_ejecucion


@pytest.mark.parametrize("task", [
    "escribí y ejecutá un script python que imprima la suma de 100 más 250",
    "corré el script prueba.py",
    "ejecutalo y decime qué sale",
    "run the tests and report the output",
    "execute main.py",
])
def test_pide_ejecucion(task):
    assert task_pide_ejecucion(task)


@pytest.mark.parametrize("task", [
    "escribí un archivo llamado nota.txt con hola",
    "corregí el bug del parser",          # 'corregí' NO es 'corré'
    "creá un json con la clave modo",
    "resumí este texto",
    "",
])
def test_no_pide_ejecucion(task):
    assert not task_pide_ejecucion(task)


def test_wiring_en_el_loop():
    # el loop real importa y usa el detector + flag de un solo aviso
    import inspect
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    assert "task_pide_ejecucion" in src
    assert "_exec_nudged" in src
    assert "RESULTADO ejecutar" in src

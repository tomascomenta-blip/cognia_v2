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


def test_nudge_tambien_en_cierre_por_prosa():
    # la bateria v4 cazo la fuga: el cierre por prosa (sin ACCION x2) tambien
    # debe pasar por el gate de ejecucion
    import inspect, re
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    # dos sitios con el nudge: responder y prosa
    assert src.count("cierre rechazado: la tarea pide ejecutar") == 2
    # el de prosa esta ANTES del break de _no_action_streak
    prosa = src.split("respuesta no estructurada")[1][:1600]
    assert "task_pide_ejecucion" in prosa and "_exec_nudged" in prosa


def test_salida_de_ejecucion():
    from cognia.agent.loop import salida_de_ejecucion
    h = ["RESULTADO escribir_archivo OK: script.py",
         "RESULTADO ejecutar: 350"]
    assert salida_de_ejecucion(h) == "350"
    # la ULTIMA exitosa gana
    h.append("RESULTADO ejecutar: 999")
    assert salida_de_ejecucion(h) == "999"
    # errores y (sin output) no cuentan
    assert salida_de_ejecucion(["RESULTADO ejecutar (exit 1): boom"]) == ""
    assert salida_de_ejecucion(["RESULTADO ejecutar: (sin output)"]) == ""
    assert salida_de_ejecucion([]) == ""
    assert salida_de_ejecucion(None) == ""


def test_cierre_con_salida_wiring():
    # el post-loop anexa la salida real si la tarea pedia ejecutar
    import inspect
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    assert "salida_de_ejecucion" in src
    assert "Salida de la ejecuci" in src


def test_error_accionable_de_ejecucion():
    # E8 parte 3: cuando la ULTIMA tool fallo, devuelve la causa; si fue
    # exitosa o no hubo, ''. (diag CIERRES: error_accionable 2/14)
    from cognia.agent.loop import error_accionable_de_ejecucion
    # ultima fallo -> reporta la causa
    assert "no existe" in error_accionable_de_ejecucion(
        ["RESULTADO leer_archivo ERROR: el archivo logs.txt no existe"])
    assert "boom" in error_accionable_de_ejecucion(
        ["RESULTADO ejecutar (exit 1): boom Traceback"])
    # ultima EXITOSA -> '' (lo cubre salida_de_ejecucion; no doble-reporte)
    assert error_accionable_de_ejecucion(
        ["RESULTADO leer_archivo ERROR: x", "RESULTADO ejecutar: 350"]) == ""
    # error ANTES de un exito posterior no gana (se mira la ultima ejecucion)
    assert error_accionable_de_ejecucion(
        ["RESULTADO ejecutar ERROR: boom", "RESULTADO escribir_archivo OK: a.txt"]) == ""
    # exito ANTES de un fallo final -> reporta el fallo final
    assert "roto" in error_accionable_de_ejecucion(
        ["RESULTADO ejecutar: 350", "RESULTADO ejecutar (exit 2): roto"])
    # sin tools / vacio / None -> ''
    assert error_accionable_de_ejecucion(["pensar: hmm", "ACCION responder"]) == ""
    assert error_accionable_de_ejecucion([]) == ""
    assert error_accionable_de_ejecucion(None) == ""


def test_cierre_error_accionable_wiring():
    # el post-loop tambien reporta la causa del fallo (no solo el exito)
    import inspect
    from cognia import cli
    src = inspect.getsource(cli._run_agent_task)
    assert "error_accionable_de_ejecucion" in src
    assert "No se pudo completar" in src

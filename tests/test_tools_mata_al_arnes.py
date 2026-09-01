# -*- coding: utf-8 -*-
"""Rail duro (2026-09-01): el agente no mata en masa a su propio interprete.

A/B con 20 min de reloj: el agente ejecuto `taskkill /f /im python.exe` para
cerrar un servidor que habia lanzado, y mato TODOS los Python de la maquina:
el servidor, el propio agente y el runner del banco. Un 'preguntar' de permisos
no sirve sin terminal; esto es un rail que no depende del interceptor.
"""
from __future__ import annotations

import pytest

from cognia.agent import tools


@pytest.mark.parametrize("cmd", [
    "taskkill /f /im python.exe",
    "taskkill /F /IM pythonw.exe /T",
    'taskkill /im "python.exe"',
    "taskkill /f /im * ",
    "TASKKILL.EXE /IM cognia.exe",
    "pkill -f python",
    "pkill -9 python3",
    "killall python",
    "kill -9 -1",
    "Stop-Process -Name python -Force",
    "powershell -c Stop-Process -Name pythonw",
])
def test_bloquea_matanzas_del_interprete(cmd):
    msg = tools._mata_al_propio_arnes(cmd)
    assert msg.startswith("RESULTADO ejecutar ERROR")
    assert "matar_proceso" in msg


@pytest.mark.parametrize("cmd", [
    "taskkill /PID 12345 /F",
    "taskkill /f /pid 777 /t",
    "kill 4242",
    "kill -9 4242",
    "pkill -f mi_servidor_node",
    "taskkill /f /im notepad.exe",
    "python servidor.py --puerto 8903",
    "echo taskkill",
    "git commit -m 'quita el pkill del script'",
])
def test_deja_pasar_lo_que_mata_un_pid_o_no_es_python(cmd):
    assert tools._mata_al_propio_arnes(cmd) == ""


def test_shell_devuelve_el_veto_sin_ejecutar():
    ctx = {}
    out = tools._shell("taskkill /f /im python.exe", ctx)
    assert out.startswith("RESULTADO ejecutar ERROR")
    assert ctx.get("_exit") == 1      # el exit REAL que luego lee run_tool


def test_fondo_tambien_veta():
    out = tools._ejecutar_fondo("pkill -f python | cwd=.", {})
    assert out.startswith("RESULTADO ejecutar_fondo ERROR")

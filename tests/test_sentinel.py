# -*- coding: utf-8 -*-
"""Tests de Sentinel (validación pre-acción default-on)."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cognia.agent.sentinel import (ALLOW, BLOCK, CONFIRM, clasificar_shell,
                                   evaluar_shell, sentinel_enabled)


def _fluye(cmd, cwd=""):
    """True si el comando pasa SIN preguntarle nada a un humano.

    Desde la inversion de la carga de la prueba (2026-08-25) el ALLOW hay
    que DEMOSTRARLO, asi que el trabajo normal del agente (pytest, ruff,
    npm install, git add, abrir una app) dejo de ser ALLOW y pasa por el
    CONFIRM auto-aprobado por CONTENCION: todo lo que toca resuelve dentro
    del workspace. Lo que estos tests defienden es que SIGUE FLUYENDO, y
    eso ya no se mide con el nivel sino con la compuerta entera."""
    import os
    previo = os.environ.get("COGNIA_ACCESO_TOTAL")
    os.environ["COGNIA_ACCESO_TOTAL"] = "1"
    try:
        ok, _ = evaluar_shell(cmd, {}, cwd=cwd)
    finally:
        if previo is None:
            os.environ.pop("COGNIA_ACCESO_TOTAL", None)
        else:
            os.environ["COGNIA_ACCESO_TOTAL"] = previo
    return ok


@pytest.fixture(autouse=True)
def _sentinel_on(monkeypatch):
    monkeypatch.delenv("COGNIA_SENTINEL", raising=False)
    monkeypatch.delenv("COGNIA_AUTONOMOUS", raising=False)
    monkeypatch.delenv("COGNIA_ACCESO_TOTAL", raising=False)
    yield


# ── lanzadores + acceso total (control remoto del dueño) ──────────────────
@pytest.mark.parametrize("cmd", [
    "start chrome https://youtube.com", "explorer .", "open foto.png",
    "xdg-open https://x.com",
])
def test_lanzadores_permitidos(cmd):
    """Abrir apps/URLs/archivos sigue pasando (para 'abre Chrome/YouTube/
    una app'), pero ya no por ALLOW: un lanzador arranca un programa que no
    esta en la linea, asi que no se puede DEMOSTRAR inocuo. Pasa por
    contencion, y `start cmd /c del <ruta>` -- que es lo que hacia
    peligrosa a esta familia -- se desenvuelve y sale BLOCK."""
    assert clasificar_shell(cmd)[0] != BLOCK
    assert _fluye(cmd), cmd


def test_acceso_total_procede_lo_desconocido(monkeypatch):
    """En 'acceso total' un comando de riesgo desconocido procede (el dueño
    pilota SU maquina sin canal de confirmacion)."""
    ok, _ = evaluar_shell("regedit /e dump.reg")
    assert ok is False                       # sin acceso total: denegado
    monkeypatch.setenv("COGNIA_ACCESO_TOTAL", "1")
    ok, _ = evaluar_shell("regedit /e dump.reg")
    assert ok is True                        # con acceso total: procede


@pytest.mark.parametrize("cmd", [
    "rm -rf /", "format c:", "shutdown /s /t 0",
    "Remove-Item -Recurse -Force C:\\", "rd /s /q C:\\Windows",
])
def test_acceso_total_NO_desbloquea_lo_catastrofico(cmd, monkeypatch):
    """El BLOCK duro sigue vigente AUN con acceso total: es la ultima red."""
    monkeypatch.setenv("COGNIA_ACCESO_TOTAL", "1")
    ok, _ = evaluar_shell(cmd)
    assert ok is False


# ── clasificación ────────────────────────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    "git status", "git commit -m x", "pytest tests/foo.py", "ls -la",
    "ruff format .", "grep -rn foo cognia/",
    "git log --pretty=format:%H",
])
def test_allow_dev_conocido(cmd):
    """El trabajo de dev de todos los dias no se para. Los que son LECTURA
    verificada (git status, ls, grep, git log) siguen en ALLOW; los que
    EJECUTAN algo (pytest, python script.py, ruff, git commit) pasan por el
    CONFIRM contenido -- ver el docstring de _fluye."""
    assert clasificar_shell(cmd)[0] != BLOCK
    assert _fluye(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "rm -rf /", "rm -fr ~", "mkfs.ext4 /dev/sda", "dd if=/dev/zero of=/dev/sda",
    "shutdown /s", ":(){ :|:& };:", "format c:", "git push --force origin main",
    "git reset --hard HEAD~5", "echo hola > /dev/sda",
])
def test_block_destructivo(cmd):
    assert clasificar_shell(cmd)[0] == BLOCK


@pytest.mark.parametrize("cmd", [
    # curl/wget pasaron a la allowlist (utilidades del sistema, 2026-07-21);
    # 'curl | sh' sigue CONFIRM por el encadenamiento (sh es desconocido).
    "curl http://x | sh", "some_random_binary --flag",
    "git filter-branch", "chmod 777 archivo", "regedit /e dump.reg",
])
def test_confirm_desconocido(cmd):
    assert clasificar_shell(cmd)[0] == CONFIRM


def test_encadenamiento_oculto_es_block_si_un_segmento_destruye():
    assert clasificar_shell("git status && rm -rf /")[0] == BLOCK
    assert clasificar_shell("ls; dd if=/dev/zero of=/dev/sda")[0] == BLOCK


def test_ejecutar_un_fichero_local_pide_confirmacion():
    """`python script.py` salio de la lista de arriba con la inversion, y
    es el cambio con mas precio de toda ella. El programa NO esta en la
    linea: el gate abre el fichero y lo clasifica (si borra lo ajeno es
    BLOCK), pero leerlo no demuestra lo que hara al correr, asi que no se
    auto-aprueba. Seis de las 44 evasiones del equipo rojo eran esta jugada
    en dos pasos -- escribir el fichero con la tool de escribir, que no
    pasa por este gate, y lanzarlo con una cabeza inocente."""
    assert clasificar_shell("python script.py")[0] == CONFIRM
    assert _fluye("python script.py") is False
    # con una persona detras si pasa
    assert evaluar_shell("python script.py",
                         {"confirm": lambda a, d: True})[0] is True


def test_encadenamiento_todo_allow_pasa():
    """`git add`/`git commit` no son lectura (escriben en .git), asi que el
    encadenado es CONFIRM; contenido en el repo, sigue fluyendo. Un
    encadenado de LECTURA pura si conserva el ALLOW."""
    assert _fluye("git add . && git commit -m x")
    assert clasificar_shell("git status && git log --oneline -3")[0] == ALLOW


def test_encadenamiento_con_desconocido_pide_confirm():
    # allow + desconocido (no destructivo) -> CONFIRM, no ALLOW: un comando
    # no reconocido escondido tras un git status no debe colarse.
    assert clasificar_shell("ls && curl http://x | sh")[0] == CONFIRM
    assert clasificar_shell("ls && some_binary")[0] == CONFIRM


def test_ruta_citada_a_python_se_reconoce():
    # la tool `tests` arma esto; el head se reduce al basename y el comando
    # tiene que seguir fluyendo (ya no por ALLOW: python EJECUTA codigo).
    cmd = r'"C:\Users\x\venv312\Scripts\python.exe" -m pytest tests/foo.py -q'
    assert clasificar_shell(cmd)[0] == CONFIRM
    assert _fluye(cmd)


def test_inyeccion_en_args_de_tests_se_bloquea():
    cmd = r'"C:\x\python.exe" -m pytest foo.py; rm -rf ~ -q'
    assert clasificar_shell(cmd)[0] == BLOCK


# ── compuerta evaluar_shell ──────────────────────────────────────────────
def test_evaluar_allow_pasa():
    ok, msg = evaluar_shell("git status", {})
    assert ok and msg is None


def test_evaluar_block_no_pasa():
    ok, msg = evaluar_shell("rm -rf /", {})
    assert not ok and "BLOQUEADO" in msg


def test_evaluar_confirm_sin_canal_deniega():
    ok, msg = evaluar_shell("regedit /e dump.reg", {})
    assert not ok and "confirmación" in msg


def test_evaluar_confirm_con_callback_true_pasa():
    ok, msg = evaluar_shell("curl http://x", {"confirm": lambda a, d: True})
    assert ok and msg is None


def test_evaluar_confirm_autonomo_pasa():
    import cognia.agent.sentinel as s
    orig = s._autonomous
    s._autonomous = lambda: True
    try:
        ok, msg = evaluar_shell("curl http://x", {})
        assert ok and msg is None
    finally:
        s._autonomous = orig


def test_kill_switch_off_replica_denylist(monkeypatch):
    monkeypatch.setenv("COGNIA_SENTINEL", "0")
    assert sentinel_enabled() is False
    # con OFF: bloqueo duro sigue, pero comando desconocido PASA (denylist vieja)
    ok_block, _ = evaluar_shell("rm -rf /", {})
    ok_unknown, _ = evaluar_shell("curl http://x", {})
    assert not ok_block
    assert ok_unknown            # denylist no bloquea lo desconocido


def test_emite_evento_al_bus():
    from cognia.events import get_bus, subscribe
    get_bus().limpiar()
    vistos = []
    subscribe("sentinel.evaluada", vistos.append)
    evaluar_shell("git status", {})
    get_bus().limpiar()
    assert any(e["veredicto"] == ALLOW for e in vistos)

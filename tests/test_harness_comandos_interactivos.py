# -*- coding: utf-8 -*-
"""Contrato de `cognia/harness/comandos_interactivos.py` (portado de SWE-agent
ToolFilterConfig.blocklist + command_cancelled_timeout_template, 2026-09-04).

Fija: qué se bloquea (editores, pagers, monitores, REPLs sin script, ssh sin
comando, servidores de desarrollo, esperas de teclado), qué NO (python con
script, git normal, pip, pytest, tuberías con stdin), que el mensaje trae la
alternativa, que el kill-switch apaga todo, que la pista de timeout distingue
servidor de entrada, y el cableado real: `_correr_proceso` cierra stdin (un
`input()` muere con EOFError en vez de colgar) y `_shell` rechaza `vim`.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from cognia.harness import comandos_interactivos as ci


@pytest.fixture(autouse=True)
def encendido(monkeypatch):
    monkeypatch.delenv(ci.ENV_ACTIVO, raising=False)


@pytest.mark.parametrize("cmd", [
    "vim a.py", "nano x", "less log.txt", "more x.txt", "man ls", "top", "htop",
    "tail -f server.log", "python", "python3", "node", "bash", "cmd", "powershell",
    "python -i", "ssh servidor", "npm run dev", "flask run", "pause", "read x",
    "cd proyecto && vim a.py", "sudo vim /etc/hosts", "cat x.py | less",
])
def test_bloquea_lo_que_espera_a_un_humano(cmd):
    assert ci.motivo_bloqueo(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "python main.py", "python -m pytest -q", "python -c \"print(1)\"", "py -3 x.py",
    "node build.js", "git status", "git log --oneline -3", "git diff", "pip install -e .",
    "python -m venv venv", "cat a.py", "tail -n 20 x.log", "echo hola | python -",
    "ssh host 'ls -la'", "dir", "ls -la", "npm test", "npm run build", "pytest",
    "sqlite3 db.sqlite 'select 1'",
])
def test_no_bloquea_lo_normal(cmd):
    assert ci.motivo_bloqueo(cmd) is None, cmd


def test_el_mensaje_trae_alternativa():
    m = ci.motivo_bloqueo("vim a.py")
    assert "editar_archivo" in m
    assert "bloqueado" in m
    m = ci.motivo_bloqueo("npm run dev")
    assert "ejecutar_fondo" in m
    m = ci.motivo_bloqueo("python")
    assert "script" in m


def test_kill_switch(monkeypatch):
    monkeypatch.setenv(ci.ENV_ACTIVO, "0")
    assert ci.motivo_bloqueo("vim a.py") is None


def test_pista_timeout_distingue_servidor_de_entrada():
    assert "ejecutar_fondo" in ci.pista_timeout("python -m http.server 8000", 30)
    assert "SERVIDOR" in ci.pista_timeout("uvicorn app:app", 30)
    p = ci.pista_timeout("python procesar.py", 30)
    assert "ENTRADA" in p and "timeout tras 30s" in p


def test_nunca_lanza_con_basura():
    assert ci.motivo_bloqueo(None) is None
    assert ci.motivo_bloqueo("") is None
    assert ci.motivo_bloqueo("   ") is None
    assert isinstance(ci.pista_timeout(None, 5), str)


# ── Cableado real ────────────────────────────────────────────────────────────

def test_correr_proceso_cierra_stdin_un_input_no_cuelga():
    from cognia.agent.tools import _correr_proceso
    ctx = {"_procesos_tool": []}
    r = _correr_proceso([sys.executable, "-c", "input('x')"], ctx, timeout=20)
    assert r.returncode != 0
    assert b"EOFError" in (r.stderr or b"")


def test_shell_rechaza_un_editor_antes_de_lanzarlo(monkeypatch):
    from cognia.agent import tools as t
    llamado = []

    def _no_deberia_correr(*a, **k):
        llamado.append(a)
        raise AssertionError("se lanzó el proceso")

    monkeypatch.setattr(t, "_correr_proceso", _no_deberia_correr)
    monkeypatch.setattr("cognia.agent.sentinel.evaluar_shell", lambda cmd, ctx=None, cwd="": (True, ""))
    out = t._shell("vim a.py", {})
    assert out.startswith("RESULTADO ejecutar ERROR")
    assert "editar_archivo" in out
    assert not llamado


def test_shell_timeout_da_la_pista(monkeypatch):
    from cognia.agent import tools as t

    def _vence(*a, **k):
        raise subprocess.TimeoutExpired("cmd", 1)

    monkeypatch.setattr(t, "_correr_proceso", _vence)
    monkeypatch.setattr("cognia.agent.sentinel.evaluar_shell", lambda cmd, ctx=None, cwd="": (True, ""))
    out = t._shell("python procesar.py", {}, timeout=1)
    assert "timeout tras 1s" in out and "ENTRADA" in out

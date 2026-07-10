# -*- coding: utf-8 -*-
"""Regresión: el REPL con stdin PIPED y SIN consola Win32 no debe morir.

Bug real (cazado por el e2e del portero, 2026-07-10): `python -m cognia` con
stdin redirigido en un proceso sin consola (CREATE_NO_WINDOW) crasheaba al
arrancar — prompt_toolkit levanta NoConsoleScreenBufferError al construir la
PromptSession (cli.py repl()). Con el fix cae al input() plano y el REPL es
scripteable (p.ej. `echo hola | cognia`).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "win32", reason="repro exclusiva de consola Win32")
def test_repl_piped_sin_consola_no_crashea():
    # /salir inmediato: solo arranque + dispatch + salida limpia (sin turnos LLM).
    # PYTHONUTF8=1 + decode utf-8: el panel de arranque trae box-drawing chars
    # que revientan el reader de cp1252 (lección del programa: PYTHONUTF8).
    env = dict(os.environ, PYTHONUTF8="1")
    r = subprocess.run(
        [sys.executable, "-m", "cognia"],
        input="/salir\n", capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
        cwd=str(REPO), timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert "NoConsoleScreenBufferError" not in (r.stderr or ""), (r.stderr or "")[-500:]
    assert "Traceback" not in (r.stderr or ""), (r.stderr or "")[-500:]
    # el REPL llegó al loop y despachó /salir (mensaje de despedida en stdout)
    assert "Hasta luego" in (r.stdout or ""), (r.stdout or "")[-300:]

# -*- coding: utf-8 -*-
"""E2E del CAMINO FELIZ del agente /hacer — GATE de pre-release (2026-07-11).

Correr ANTES de cada release del CLI/agente, además de pytest. El pytest (~3700
tests) NO ejecuta el agente con un modelo real; la regresión de 3.8.4 (un
repeat_penalty que empujaba al 3B a basura -> /hacer 0/5) pasó la suite y llegó a
PyPI justamente por eso. Este script corre 5 tareas normales de /hacer con
postcondición verificada en un workspace temporal, contra el backend real del
repo (ShatteringOrchestrator local + _try_load_llama). Si algún cambio del agente
rompe el camino feliz, esto lo caza antes de publicar.

Uso:  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\e2e_happy_path.py
Salida: 'E2E CAMINO FELIZ: N/5 OK'; exit 0 si 5/5, 1 si alguna falla.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECKS = []


def check(nombre, ok, detalle=""):
    CHECKS.append((nombre, bool(ok)))
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre}"
          + (f" — {str(detalle)[:100]}" if detalle else ""), flush=True)


def main():
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from shattering.orchestrator import ShatteringOrchestrator

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    def _lee(ws, n):
        hits = list(ws.rglob(n))
        return hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""

    def hacer(tarea, verificar, setup=None, pasos=6):
        ws = Path(tempfile.mkdtemp(prefix="hp_")).resolve()
        if setup:
            setup(ws)
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: None, max_steps=pasos)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        try:
            return verificar(ws), (str(resp) or "")[:90]
        except Exception as exc:
            return False, f"verify exc: {exc}"

    tareas = [
        ("escribir", "escribí un archivo llamado nota.txt con el texto exacto: bateria ok",
         lambda ws: "bateria ok" in _lee(ws, "nota.txt"), None),
        ("calcular+guardar", "calculá 17 por 23 y guardá el resultado en resultado.txt",
         lambda ws: "391" in _lee(ws, "resultado.txt"), None),
        ("json", "creá un archivo config.json con la clave modo puesta en rapido",
         lambda ws: json.loads(_lee(ws, "config.json") or "{}").get("modo") == "rapido", None),
        ("apendar", "agregá la línea 'tercera' al final del archivo bitacora.txt",
         lambda ws: _lee(ws, "bitacora.txt").strip().splitlines()[-1].strip().strip("'\"") == "tercera",
         lambda ws: (ws / "bitacora.txt").write_text("primera\nsegunda\n", encoding="utf-8")),
        ("python", "escribí y ejecutá un script python que imprima la suma de 100 más 250",
         None, None),   # check por respuesta
    ]
    t0 = time.time()
    for nombre, tarea, verificar, setup in tareas:
        t1 = time.time()
        ok, resp = hacer(tarea, verificar or (lambda ws: True), setup)
        if nombre == "python":
            ok = "350" in resp
        check(f"{nombre} ({time.time()-t1:.0f}s)", ok, resp)

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E CAMINO FELIZ: {len(CHECKS)-len(fallos)}/{len(CHECKS)} OK en "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    if fallos:
        print("FALLARON:", fallos, flush=True)
    subprocess.run(["taskkill", "/IM", "llama-server.exe", "/F"], capture_output=True)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

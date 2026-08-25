# -*- coding: utf-8 -*-
"""E2E del CAMINO FELIZ del agente /hacer — GATE de pre-release (2026-07-11).

Correr ANTES de cada release del CLI/agente, además de pytest. El pytest (~3700
tests) NO ejecuta el agente con un modelo real; la regresión de 3.8.4 (un
repeat_penalty que empujaba al 3B a basura -> /hacer 0/5) pasó la suite y llegó a
PyPI justamente por eso. Este script corre 5 tareas normales de /hacer con
postcondición verificada en un workspace temporal, contra el backend real del
repo (ShatteringOrchestrator local + _try_load_llama). Si algún cambio del agente
rompe el camino feliz, esto lo caza antes de publicar.

Las 5 postcondiciones se comprueban en DISCO, nunca contra la respuesta del
modelo (2026-08-14: la tarea 'python' era la última que se validaba con
`'350' in resp` — ver ejecuta_algun_py). Un modelo que dice "listo" sin tocar
el workspace tiene que FALLAR, o el gate obligatorio no gatea nada.

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
# MODO EFIMERO (2026-08-25): el gate corre el agente REAL en proceso; sin esto,
# cualquier via que toque chat_history/user_profile/episodica (p.ej. el
# ai.observe de _run_agent_task con un Cognia real) escribia en la memoria del
# dueno. setdefault, no asignacion: quien quiera medir persistencia puede
# exportar COGNIA_EFIMERO=0 antes de correrlo. Va ANTES de importar cognia.
os.environ.setdefault("COGNIA_EFIMERO", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECKS = []


def ejecuta_algun_py(ws, esperado, timeout=30):
    """Postcondicion de DISCO de la tarea 'python': ¿quedó escrito en `ws` un
    .py que, AL EJECUTARLO, imprime `esperado`?

    POR QUE existe (2026-08-14): esta tarea se verificaba con `'350' in resp`,
    o sea contra la RESPUESTA del modelo. Un modelo que contesta "la suma es
    350" sin escribir ni ejecutar nada APROBABA el gate que CLAUDE.md declara
    obligatorio antes de publicar a PyPI — justo el agujero por el que la
    regresión de 3.8.4 llegó al release. Es además la regla que el propio repo
    ya se había escrito en scripts/banco_cerebro.py:19-22: la postcondición se
    comprueba leyendo el disco y, cuando hace falta, EJECUTANDO lo que quedó
    escrito; la respuesta se guarda solo como diagnóstico.

    Exige las dos mitades del enunciado ("escribí Y ejecutá"): sin .py no hay
    nada que ejecutar (False), y un .py que existe pero peta o imprime otra
    cosa tampoco cuenta. Se exige exit 0: un script que imprime 350 y después
    revienta no "funciona".

    stdin=DEVNULL a propósito, misma razón que en banco_cerebro._ejecutar_py:
    el código lo escribió un modelo y un `input()` colado heredaría la consola
    del gate — se comería las teclas y colgaría la corrida hasta el timeout.
    Con DEVNULL da EOFError, el script falla y el veredicto es el correcto.
    """
    for p in sorted(Path(ws).rglob("*.py")):
        try:
            r = subprocess.run([sys.executable, str(p)], cwd=str(p.parent),
                               capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL,
                               encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            continue
        if r.returncode == 0 and esperado in ((r.stdout or "") + (r.stderr or "")):
            return True
    return False


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
         lambda ws: ejecuta_algun_py(ws, "350"), None),   # postcondicion de DISCO
    ]
    t0 = time.time()
    for nombre, tarea, verificar, setup in tareas:
        t1 = time.time()
        ok, resp = hacer(tarea, verificar, setup)
        check(f"{nombre} ({time.time()-t1:.0f}s)", ok, resp)

    fallos = [n for n, ok in CHECKS if not ok]
    print(f"\nE2E CAMINO FELIZ: {len(CHECKS)-len(fallos)}/{len(CHECKS)} OK en "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    if fallos:
        print("FALLARON:", fallos, flush=True)
    # Parar SOLO el llama-server que arranco ESTE script. El taskkill /IM
    # anterior mataba TODOS los llama-server.exe de la maquina, incluida la
    # flota compartida (:8080/:8081) que sirven otros procesos. stop() de
    # LlamaBackend termina unicamente self._proc y deja en paz los servers
    # adoptados (arrancados fuera; en ese caso no hay nada que parar aqui).
    try:
        if getattr(orch, "_llama", None) is not None:
            orch._llama.stop()
    except Exception:
        pass
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Bench de ESTANCAMIENTO del agent loop REAL (diagnóstico del fallo
"Agente estancado (accion repetida)" visto en cognia/oficina y /hacer).

Corre cli._run_agent_task (el loop de PRODUCCIÓN, sin réplicas) con el
orquestador real (llama-server + GGUF 3B) sobre tareas VERIFICABLES por
postcondición del banco de tool-use, cada una en un workspace aislado.

Mide por tarea:
  fin        -> responder | stuck | sin_resultado (budget/prosa/error)
  exito      -> postcondición verify (el estado REAL del workspace)
  pasos      -> pasos consumidos
  acciones   -> traza (de los prints 'paso N:'), para ver QUÉ repite
  stuck_sig  -> la primera acción que llegó a 2+ repeticiones (si hubo)

Es un INSTRUMENTO DE DIAGNÓSTICO (no gate congelado): sus tareas vienen del
banco de train/eval de tooluse; el gate real del agente es la suite G2A
congelada + este bench como comparación pareada pre/post fix (misma lista de
tareas, mismo modelo, greedy).

Uso:
  .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.bench_estancamiento ^
      --out cognia_v3/eval/results_estancamiento_baseline.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Tareas del banco tooluse: mezcla de multi-paso (donde el 3B base cicla,
# report Fase A: multi-paso 0% accept) + held-out + single fáciles (control).
TASK_IDS = [
    # multi-paso históricamente difíciles (train bank, uso diagnóstico)
    "json_make_key", "append_then_count", "py_write_run",
    "math_to_file", "copiar_dos_veces", "json_anidado",
    # held-out del pipeline tooluse (EVAL_IDS)
    "math_pow", "copy_file", "search_word", "shell_echo",
    # single-step fáciles (control: no deberían estancarse)
    "math_mul", "fecha_hoy",
]


class _AIStub:
    """ai mínimo para _run_agent_task: solo _orchestrator; el resto de accesos
    (observe, skills, episodic) están en try/except en el loop."""
    def __init__(self, orch):
        self._orchestrator = orch


def corre_tarea(task: dict, ai, verbose: bool) -> dict:
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia.cli import _run_agent_task
    from cognia_v3.training.tooluse.gen_trajectories import _results_only

    prints: list = []

    def _print_fn(msg, *a, **k):
        prints.append(str(msg))
        if verbose:
            print("   ", str(msg)[:110], flush=True)

    ws = Path(tempfile.mkdtemp(prefix=f"be_{task['id']}_")).resolve()
    prev_cwd = os.getcwd()
    prev_root = dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)
    t0 = time.time()
    try:
        result_text = _run_agent_task(ai, task["prompt"], _print_fn)
        # postcondición sobre el estado REAL del workspace + transcript de prints
        transcript = "\n".join(prints)
        try:
            exito = bool(task["verify"](ws, transcript, result_text or ""))
        except Exception:
            exito = False
    finally:
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        shutil.rmtree(ws, ignore_errors=True)
    wall = time.time() - t0

    # traza de acciones desde los prints 'paso N: ...'
    acciones = []
    for p in prints:
        m = re.search(r"paso (\d+): (.*)", p)
        if m:
            am = re.search(r"ACCI[OÓ]N:\s*(\w+)\s*([^\n]*)", m.group(2), re.IGNORECASE)
            acciones.append({"paso": int(m.group(1)),
                             "accion": (am.group(1).lower() if am else None),
                             "args_head": (am.group(2)[:80] if am else m.group(2)[:80])})
    stuck = any("Agente estancado" in p for p in prints)
    # primera firma que se repitió (action + args_head como aproximación)
    vistos, stuck_sig = {}, None
    for a in acciones:
        if not a["accion"]:
            continue
        k = (a["accion"], a["args_head"])
        vistos[k] = vistos.get(k, 0) + 1
        if vistos[k] >= 2 and stuck_sig is None:
            stuck_sig = f"{k[0]} {k[1][:60]}"

    if stuck:
        fin = "stuck"
    elif acciones and acciones[-1]["accion"] == "responder":
        fin = "responder"
    elif result_text:
        fin = "prosa_o_bon"
    else:
        fin = "sin_resultado"

    return {"fin": fin, "exito": exito, "pasos": len(acciones),
            "wall_s": round(wall, 1), "stuck_sig": stuck_sig,
            "acciones": acciones, "result_head": (result_text or "")[:160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="cognia_v3/eval/results_estancamiento_baseline.json")
    ap.add_argument("--tasks", default="", help="ids separados por coma (filtra)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from cognia_v3.training.tooluse.tasks import by_id
    from shattering.orchestrator import ShatteringOrchestrator

    ids = [x.strip() for x in args.tasks.split(",") if x.strip()] or TASK_IDS
    tasks = [by_id(i) for i in ids]
    faltan = [i for i, t in zip(ids, tasks) if t is None]
    if faltan:
        print(f"[bench] ids inexistentes: {faltan}")
        sys.exit(1)

    print("[bench] cargando orquestador local (llama-server + GGUF)...", flush=True)
    orch = ShatteringOrchestrator(
        manifest_path="shattering/manifests/cognia_desktop.json")
    orch._try_load_llama()
    ai = _AIStub(orch)

    res = {"bench": "estancamiento-agent-loop", "modelo": "local-gguf",
           "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "tareas": {}}
    out = Path(args.out)
    t0 = time.time()
    for task in tasks:
        print(f"[bench] == {task['id']} ==", flush=True)
        r = corre_tarea(task, ai, args.verbose)
        res["tareas"][task["id"]] = r
        print(f"[bench] {task['id']}: fin={r['fin']} exito={r['exito']} "
              f"pasos={r['pasos']} ({r['wall_s']}s)", flush=True)
        out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

    n = len(res["tareas"])
    stuck = sum(1 for r in res["tareas"].values() if r["fin"] == "stuck")
    exito = sum(1 for r in res["tareas"].values() if r["exito"])
    res["resumen"] = {"n": n, "stuck": stuck, "stuck_rate": round(stuck / n, 3),
                      "exito": exito, "exito_rate": round(exito / n, 3),
                      "wall_total_min": round((time.time() - t0) / 60, 1)}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n[bench] RESUMEN: {n} tareas | stuck {stuck}/{n} | exito {exito}/{n} "
          f"| {res['resumen']['wall_total_min']} min -> {out}", flush=True)


if __name__ == "__main__":
    main()

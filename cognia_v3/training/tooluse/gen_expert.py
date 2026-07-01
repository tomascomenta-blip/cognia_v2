"""
cognia_v3/training/tooluse/gen_expert.py
=========================================
Genera trayectorias EXPERTAS (scripted) verificadas por ejecucion.

A diferencia de gen_trajectories.py (corre el 3B local y conserva lo que acierta),
aca la secuencia CORRECTA de acciones esta escrita a mano en tasks.py:EXPERT_STEPS.
Se EJECUTA contra las tools reales (run_tool, el mismo del deploy) en un workspace
aislado, y la trayectoria se conserva SOLO si la postcondicion (task['verify']) pasa.

Por que: en el report Fase A el 3B base da 0% accept en multi-paso (append/count/
json/py) -> no genera datos para esas tareas por mas samples que se tiren. Y las
tools de memoria/KG estaban deshabilitadas. Las trayectorias expertas llenan ambos
huecos y, al no usar el 3B, NO cuestan la hora de CPU.

El formato de cada par SFT es IDENTICO al de gen_trajectories (prompt = tools_doc +
contexto + 'Siguiente ACCION:'; completion = 'ACCION: <tool> <args>'; cierre con
'responder'), para mezclarlas con las del 3B sin mismatch train/inference.

Aislamiento: workspace temporal por trayectoria; para tareas de KG (NEEDS_AI_KG) se
inyecta un KnowledgeGraph sobre una DB temporal -> NUNCA toca la memoria del usuario.

Uso:
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_expert --smoke
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_expert --verbose
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_expert \\
        --merge cognia_v3/training/tooluse/data/tooluse_train.jsonl \\
        --out   cognia_v3/training/tooluse/data/tooluse_train_v2.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from cognia_v3.training.tooluse.gen_trajectories import (
    build_tools_doc_full, _sanitize, _results_only, _normalize_completion,
    _verify_safe,
)
from cognia_v3.training.tooluse.tasks import (
    EXPERT_STEPS, NEEDS_AI_KG, expert_tasks, by_id,
)


class _AIStub:
    """ai minimo para las tools de memoria/KG en generacion aislada: expone solo
    lo que esas tools tocan (.kg). NO carga el cerebro Cognia real ni su DB."""
    def __init__(self, kg=None):
        self.kg = kg
        self.episodic = None
        self._orchestrator = None


def _make_ctx(task_id: str, ws: Path) -> dict:
    ctx = {
        "ai": None,
        "working_memory": {},
        "agent_state": {"files_touched": [], "tasks": []},
        "print_fn": (lambda *a, **k: None),
        "show_diff": None,
    }
    if task_id in NEEDS_AI_KG:
        from cognia.database import init_db
        from cognia.knowledge.graph import KnowledgeGraph
        kg_db = str(ws / "_kg_isolated.db")          # DB temporal, se borra con ws
        init_db(kg_db)                                # crea el schema (tabla knowledge_graph)
        ctx["ai"] = _AIStub(kg=KnowledgeGraph(db_path=kg_db))
    return ctx


def run_expert(task: dict, tools_doc: str, verbose: bool = False) -> dict:
    """Ejecuta la secuencia experta de la tarea contra las tools reales y devuelve
    los pares SFT si la postcondicion pasa. Devuelve {ok, pairs}."""
    from cognia.agent.tools import run_tool
    import cognia.agents.workers.dev_tools as dev_tools

    steps = EXPERT_STEPS[task["id"]]
    ws = Path(tempfile.mkdtemp(prefix=f"te_{task['id']}_")).resolve()
    ws_str = str(ws)
    prev_cwd = os.getcwd()
    prev_root = dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)

    ctx = _make_ctx(task["id"], ws)
    history = [f"TAREA: {task['prompt']}"]
    raw_pairs = []
    final_ctx = "\n".join(history[-6:])
    try:
        for (action, args) in steps:
            ctx_text = "\n".join(history[-6:])
            agent_prompt = (f"{tools_doc}\n\nContexto de la tarea:\n{ctx_text}\n\n"
                            f"Siguiente ACCION:")
            completion = _normalize_completion(action, args)
            # El args de ejecutar usa sys.executable (ruta ABSOLUTA de esta maquina)
            # para que la generacion corra con el interprete correcto; pero el dato
            # de entrenamiento debe ser GENERICO ('python calc.py'), no memorizar la
            # ruta del venv de esta PC. Se ejecuta con la ruta real, se guarda scrub.
            completion = completion.replace(f'"{sys.executable}"', "python").replace(sys.executable, "python")
            result = run_tool(action, args, ctx)
            if verbose:
                print(f"    {completion[:80]}")
                print(f"      -> {result[:100]}")
            raw_pairs.append({"prompt": agent_prompt, "completion": completion,
                              "tool": action})
            history.append(result)
            final_ctx = "\n".join(history[-6:])
        ok = _verify_safe(task, ws, _results_only(history))
    finally:
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        shutil.rmtree(ws, ignore_errors=True)

    if not ok:
        return {"ok": False, "pairs": []}

    clean = []
    for i, p in enumerate(raw_pairs):
        clean.append({"prompt": _sanitize(p["prompt"], ws_str),
                      "completion": _sanitize(p["completion"], ws_str),
                      "tool": p["tool"], "task_id": task["id"], "step": i + 1})
    # Cierre limpio: enseña a PARAR con una respuesta final plausible.
    ans = task.get("answer") or "Listo, tarea completada."
    final_prompt = (f"{tools_doc}\n\nContexto de la tarea:\n{final_ctx}\n\n"
                    f"Siguiente ACCION:")
    clean.append({"prompt": _sanitize(final_prompt, ws_str),
                  "completion": f"ACCION: responder {ans}",
                  "tool": "responder", "task_id": task["id"], "step": len(raw_pairs) + 1})
    return {"ok": True, "pairs": clean}


def _load_jsonl(path: Path) -> list:
    if not path or not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def main():
    ap = argparse.ArgumentParser(description="Genera trayectorias expertas de tool-use")
    default_out = "cognia_v3/training/tooluse/data/tooluse_expert.jsonl"
    ap.add_argument("--out", default=default_out)
    ap.add_argument("--merge", default="", help="jsonl base a concatenar (dedup por prompt+completion)")
    ap.add_argument("--tasks", default="", help="ids separados por coma (filtra)")
    ap.add_argument("--smoke", action="store_true", help="1-2 tareas verbose, no escribe")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    tools_doc = build_tools_doc_full()

    if args.smoke:
        ids = ["append_then_count", "kg_agregar_buscar"]
        tasks = [by_id(i) for i in ids if by_id(i)]
    elif args.tasks.strip():
        tasks = [by_id(x.strip()) for x in args.tasks.split(",") if by_id(x.strip())]
    else:
        tasks = expert_tasks()

    t0 = time.time()
    all_pairs = []
    per_task = {}
    for task in tasks:
        r = run_expert(task, tools_doc, verbose=(args.verbose or args.smoke))
        per_task[task["id"]] = "OK" if r["ok"] else "FAIL"
        status = "OK " if r["ok"] else "xx "
        print(f"[expert] {status}{task['id']:<22} pares={len(r['pairs'])}")
        if r["ok"]:
            all_pairs.extend(r["pairs"])

    n_ok = sum(1 for v in per_task.values() if v == "OK")
    print(f"\n[expert] {n_ok}/{len(tasks)} tareas expertas OK | {len(all_pairs)} pares | {time.time()-t0:.1f}s")
    fails = [k for k, v in per_task.items() if v == "FAIL"]
    if fails:
        print(f"[expert] FALLARON (revisar EXPERT_STEPS): {fails}")

    if args.smoke:
        print("[expert] smoke: no se escribe archivo.")
        return

    # Merge opcional con el dataset del 3B + dedup por (prompt, completion).
    base = _load_jsonl(Path(args.merge)) if args.merge else []
    merged = []
    seen = set()
    for rec in base + all_pairs:
        k = (rec["prompt"], rec["completion"])
        if k in seen:
            continue
        seen.add(k)
        merged.append(rec)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in merged:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[expert] escrito {len(merged)} pares (base={len(base)} + expert={len(all_pairs)}, "
          f"dedup) -> {out}")


if __name__ == "__main__":
    main()

"""
cognia_v3/training/tooluse/gen_expert_v2.py
============================================
Genera pares SFT del banco v2 (tasks_v2.py), verificados por ejecución,
con TRES clases de datos (TEORIA Parte 4 §4.2 D2 + E-D2b):

1. EXPERTOS: la trayectoria correcta ejecutada contra las tools reales
   (formato idéntico a gen_expert.py). La trayectoria se ejecuta UNA vez con
   el prompt principal; se emiten pares para CADA paráfrasis (el RESULTADO de
   las tools no depende del fraseo de la TAREA) -> diversidad léxica gratis.

2. RECUPERACIÓN DE ERROR (E-D2b): antes del primer paso se ejecuta DE VERDAD
   una acción errónea plausible (leer_archivo del objetivo cuando aún no
   existe -> ERROR real con el formato exacto del deploy); el par enseña:
   contexto con ERROR -> la completion correcta es el primer paso BUENO
   (no repetir la lectura).

3. ANTI-CICLO: contexto calcado del loop real cuando el agente repitió una
   acción (2× el mismo RESULTADO ERROR + el AVISO literal de cli.py) ->
   completion = el paso correcto. Ataca la causa raíz medida en
   bench_estancamiento (greedy repite; el AVISO solo no desvía al 3B: ahora
   hay datos de qué hacer tras el AVISO).

Higiene: check_superficies() debe dar vacío (train no toca la suite G2A);
la descontaminación K=8 contra suites corre aparte (decontaminar.py).

Uso:
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_expert_v2 --smoke
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_expert_v2 \\
        --merge cognia_v3/training/tooluse/data/tooluse_train_v2.jsonl \\
        --out   cognia_v3/training/tooluse/data/tooluse_train_v3.jsonl
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
)
from cognia_v3.training.tooluse.tasks_v2 import TASKS_V2, check_superficies, by_id

# El AVISO LITERAL del loop de producción (cli.py) — el dato de entrenamiento
# debe calcar lo que el modelo ve en deploy.
AVISO_LOOP = ("AVISO: estas repitiendo la misma accion sin progreso. "
              "Cambia de enfoque o usa responder.")


class _AIStub:
    def __init__(self, kg=None):
        self.kg = kg
        self.episodic = None
        self._orchestrator = None


def _make_ctx(task: dict, ws: Path) -> dict:
    ctx = {
        "ai": None,
        "working_memory": {},
        "agent_state": {"files_touched": [], "tasks": []},
        "print_fn": (lambda *a, **k: None),
        "show_diff": None,
    }
    if task.get("needs_kg"):
        from cognia.database import init_db
        from cognia.knowledge.graph import KnowledgeGraph
        kg_db = str(ws / "_kg_isolated.db")
        init_db(kg_db)
        ctx["ai"] = _AIStub(kg=KnowledgeGraph(db_path=kg_db))
    return ctx


def _verify_safe(task, ws, transcript) -> bool:
    try:
        return bool(task["verify"](ws, transcript, ""))
    except Exception:
        return False


def _primer_filename(task: dict):
    """Primer archivo que la tarea va a crear (para el paso erróneo de
    recuperación: leerlo ANTES de crearlo da un ERROR real)."""
    for tool, args in task["expert_steps"]:
        if tool == "escribir_archivo":
            return args.split("|")[0].strip()
    return None


def _prompt_de(tools_doc: str, ctx_text: str) -> str:
    return f"{tools_doc}\n\nContexto de la tarea:\n{ctx_text}\n\nSiguiente ACCION:"


def run_task_v2(task: dict, tools_doc: str, verbose: bool = False) -> dict:
    """Ejecuta la trayectoria experta y devuelve pares de las 3 clases si la
    postcondición pasa. {ok, pares_expertos, pares_recuperacion, pares_anticiclo}"""
    from cognia.agent.tools import run_tool
    import cognia.agents.workers.dev_tools as dev_tools

    ws = Path(tempfile.mkdtemp(prefix=f"tv2_{task['id']}_")).resolve()
    ws_str = str(ws)
    prev_cwd = os.getcwd()
    prev_root = dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)

    ctx = _make_ctx(task, ws)
    prompt_ppal = task["prompts"][0]
    steps = task["expert_steps"]

    # bloques por paso: (ctx_relativo_sin_TAREA, completion, tool)
    bloques = []
    err_recuperacion = None   # RESULTADO ERROR real del paso erróneo inyectado
    try:
        # paso erróneo REAL para la clase recuperación (solo tareas de archivos)
        objetivo = _primer_filename(task)
        if objetivo:
            err_recuperacion = run_tool("leer_archivo", objetivo, ctx)
            if "ERROR" not in err_recuperacion:
                err_recuperacion = None   # (existía: no sirve como error)

        history = [f"TAREA: {prompt_ppal}"]
        for (tool, args) in steps:
            cola = history[1:][-5:]
            completion = _normalize_completion(tool, args)
            completion = completion.replace("__PYTHON__", "python")
            bloques.append({"cola": list(cola), "completion": completion, "tool": tool})
            args_exec = args.replace("__PYTHON__", f'"{sys.executable}"')
            result = run_tool(tool, args_exec, ctx)
            history.append(result)
            if verbose:
                print(f"    {completion[:70]} -> {result[:70]}")
        cola_final = history[1:][-5:]
        ok = _verify_safe(task, ws, _results_only(history))
    finally:
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        shutil.rmtree(ws, ignore_errors=True)

    if not ok:
        return {"ok": False}

    def _sane(texto: str) -> str:
        t = _sanitize(texto, ws_str)
        return t.replace(f'"{sys.executable}"', "python").replace(sys.executable, "python")

    expertos, recuperacion, anticiclo = [], [], []
    answer = task.get("answer") or "Listo, tarea completada."
    for vi, variante in enumerate(task["prompts"]):
        tarea_line = f"TAREA: {variante}"
        # 1) pares expertos (todos los pasos) + cierre responder
        for si, b in enumerate(bloques, 1):
            ctx_text = "\n".join([tarea_line] + b["cola"])
            expertos.append({
                "prompt": _sane(_prompt_de(tools_doc, ctx_text)),
                "completion": _sane(b["completion"]),
                "tool": b["tool"], "task_id": task["id"],
                "step": si, "variante": vi, "clase": "experto"})
        ctx_text = "\n".join([tarea_line] + cola_final)
        expertos.append({
            "prompt": _sane(_prompt_de(tools_doc, ctx_text)),
            "completion": f"ACCION: responder {answer}",
            "tool": "responder", "task_id": task["id"],
            "step": len(bloques) + 1, "variante": vi, "clase": "experto"})

        primero = bloques[0]
        # 2) recuperación de error: TAREA + ERROR real -> primer paso bueno
        if err_recuperacion:
            ctx_text = "\n".join([tarea_line, _sane(err_recuperacion)])
            recuperacion.append({
                "prompt": _sane(_prompt_de(tools_doc, ctx_text)),
                "completion": _sane(primero["completion"]),
                "tool": primero["tool"], "task_id": task["id"],
                "step": 1, "variante": vi, "clase": "recuperacion"})
            # 3) anti-ciclo: 2× el mismo ERROR + AVISO literal del loop
            ctx_text = "\n".join([tarea_line, _sane(err_recuperacion),
                                  _sane(err_recuperacion), AVISO_LOOP])
            anticiclo.append({
                "prompt": _sane(_prompt_de(tools_doc, ctx_text)),
                "completion": _sane(primero["completion"]),
                "tool": primero["tool"], "task_id": task["id"],
                "step": 1, "variante": vi, "clase": "anticiclo"})

    return {"ok": True, "expertos": expertos, "recuperacion": recuperacion,
            "anticiclo": anticiclo}


def _load_jsonl(path: Path) -> list:
    if not path or not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def main():
    ap = argparse.ArgumentParser(description="Genera pares SFT v2 (expertos+recuperacion+anticiclo)")
    ap.add_argument("--out", default="cognia_v3/training/tooluse/data/tooluse_train_v3.jsonl")
    ap.add_argument("--merge", default="", help="jsonl base a concatenar (dedup)")
    ap.add_argument("--tasks", default="", help="ids separados por coma")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    malas = check_superficies()
    if malas:
        print(f"[v2] ABORT: superficies de train colisionan con la suite G2A: {malas}")
        sys.exit(1)

    tools_doc = build_tools_doc_full()
    if args.smoke:
        tasks = [by_id("v2_ac_visitas"), by_id("v2_kg_tango")]
    elif args.tasks.strip():
        tasks = [by_id(x.strip()) for x in args.tasks.split(",") if by_id(x.strip())]
    else:
        tasks = TASKS_V2

    t0 = time.time()
    todo, fallos = [], []
    stats = {"experto": 0, "recuperacion": 0, "anticiclo": 0}
    for task in tasks:
        r = run_task_v2(task, tools_doc, verbose=(args.verbose or args.smoke))
        if not r["ok"]:
            fallos.append(task["id"])
            print(f"[v2] xx {task['id']}")
            continue
        for clase in ("expertos", "recuperacion", "anticiclo"):
            todo.extend(r[clase])
        stats["experto"] += len(r["expertos"])
        stats["recuperacion"] += len(r["recuperacion"])
        stats["anticiclo"] += len(r["anticiclo"])
        print(f"[v2] OK {task['id']:<18} exp={len(r['expertos'])} rec={len(r['recuperacion'])} anti={len(r['anticiclo'])}")

    print(f"\n[v2] {len(tasks) - len(fallos)}/{len(tasks)} tareas OK | {stats} | {time.time()-t0:.1f}s")
    if fallos:
        print(f"[v2] FALLARON: {fallos}")
        sys.exit(1)
    if args.smoke:
        print("[v2] smoke: no se escribe archivo.")
        return

    base = _load_jsonl(Path(args.merge)) if args.merge else []
    merged, seen = [], set()
    for rec in base + todo:
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
    print(f"[v2] escrito {len(merged)} pares (base={len(base)} + v2={len(todo)}, dedup) -> {out}")


if __name__ == "__main__":
    main()

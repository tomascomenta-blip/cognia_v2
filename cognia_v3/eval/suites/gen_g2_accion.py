"""Genera la suite G2-ACCION (g2_accion.jsonl) desde el banco held-out
g2_accion_tasks.py, VERIFICADA POR EJECUCION.

Por cada tarea: ejecuta su trayectoria experta scripted contra las tools
REALES (run_tool, el mismo del deploy) en un workspace aislado; si la
postcondicion (verify) pasa, corta la trayectoria en ITEMS de eval:

  paso k (1..n): prompt = tools_doc + contexto real (RESULTADOs de los pasos
                 previos ya ejecutados) + 'Siguiente ACCION:'
                 oracle = {accion_tools: [tool_k, *first_alt si k=1],
                           args_regex: nombre de archivo si la tool opera
                           archivos (valida que use el archivo CORRECTO)}
  cierre:        contexto final completo -> accion_tools=['responder']
                 (mide TERMINACION: parar cuando la tarea esta completa)

El item se evalua en el kernel con suite_oracle.accion_pass (primera linea
ACCION del output), sin ejecutar tools -> corre en Kaggle. La ejecucion real
E2E queda para el gate G4/CLI.

Determinismo: los RESULTADOs quedan CONGELADOS en el JSONL (se genera una vez
y se congela por hash; re-generar = suite nueva). `fecha` congela la fecha de
generacion — irrelevante para el oraculo (mide seleccion de tool).

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.suites.gen_g2_accion
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from cognia_v3.training.tooluse.gen_trajectories import (
    build_tools_doc_full, _sanitize, _results_only, _normalize_completion,
)
from cognia_v3.eval.suites.g2_accion_tasks import TASKS

HERE = Path(__file__).resolve().parent
OUT = HERE / "g2_accion.jsonl"

# tools cuyo primer token de args es un path -> args_regex valida el archivo
_FILE_TOOLS = {"escribir_archivo", "apendar_archivo", "leer_archivo",
               "copiar_archivo", "contar_lineas", "py_validar", "json_validar"}


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


def _args_regex(tool: str, args: str):
    """Regex del archivo objetivo para tools de archivo (primer token del args).
    Valida que el modelo opere el archivo CORRECTO, no solo la tool correcta."""
    if tool not in _FILE_TOOLS:
        return None
    primer = args.split("|")[0].strip()
    if not primer or primer == ".":
        return None
    return re.escape(primer).replace("\\/", "[/\\\\]")


def _verify_safe(task, ws, transcript) -> bool:
    try:
        return bool(task["verify"](ws, transcript, ""))
    except Exception:
        return False


def genera_items(task: dict, tools_doc: str) -> list:
    """Ejecuta la trayectoria experta y devuelve los items de eval, o [] si la
    postcondicion falla (la tarea NO entra a la suite)."""
    from cognia.agent.tools import run_tool
    import cognia.agents.workers.dev_tools as dev_tools

    ws = Path(tempfile.mkdtemp(prefix=f"g2a_{task['id']}_")).resolve()
    ws_str = str(ws)
    prev_cwd = os.getcwd()
    prev_root = dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)

    ctx = _make_ctx(task, ws)
    history = [f"TAREA: {task['prompt']}"]
    steps = task["expert_steps"]
    raw_items = []
    try:
        for k, (tool, args) in enumerate(steps, 1):
            ctx_text = "\n".join(history[-6:])
            prompt = (f"{tools_doc}\n\nContexto de la tarea:\n{ctx_text}\n\n"
                      f"Siguiente ACCION:")
            expected = [tool]
            if k == 1:
                for alt in task.get("first_alt", []):
                    if alt not in expected:
                        expected.append(alt)
            raw_items.append({"prompt": prompt, "tools": expected,
                              "args_regex": _args_regex(tool, args), "step": k})
            args_exec = args.replace("__PYTHON__", f'"{sys.executable}"')
            result = run_tool(tool, args_exec, ctx)
            history.append(result)
        # item de cierre: la accion correcta es PARAR
        ctx_final = "\n".join(history[-6:])
        raw_items.append({"prompt": (f"{tools_doc}\n\nContexto de la tarea:\n"
                                     f"{ctx_final}\n\nSiguiente ACCION:"),
                          "tools": ["responder"], "args_regex": None,
                          "step": len(steps) + 1})
        ok = _verify_safe(task, ws, _results_only(history))
    finally:
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        shutil.rmtree(ws, ignore_errors=True)

    if not ok:
        return []

    items = []
    n = len(steps) + 1
    for it in raw_items:
        prompt = _sanitize(it["prompt"], ws_str)
        prompt = prompt.replace(f'"{sys.executable}"', "python").replace(sys.executable, "python")
        items.append({
            "id": f"{task['id']}-s{it['step']}",
            "gate": "G2A",
            "dominio": task["dominio"],
            "idioma": "es",
            "shots": 0,
            "prompt": prompt,
            "max_new_tokens": 200,
            "oracle": {"accion_tools": it["tools"], "args_regex": it["args_regex"]},
            "task_id": task["id"], "step": it["step"], "n_steps": n,
        })
    return items


def main():
    tools_doc = build_tools_doc_full()
    all_items, fallos = [], []
    for task in TASKS:
        items = genera_items(task, tools_doc)
        status = "OK " if items else "xx "
        print(f"[g2a] {status}{task['id']:<24} items={len(items)}")
        if items:
            all_items.extend(items)
        else:
            fallos.append(task["id"])

    print(f"\n[g2a] {len(TASKS) - len(fallos)}/{len(TASKS)} tareas OK -> {len(all_items)} items")
    if fallos:
        print(f"[g2a] FALLARON (postcondicion; revisar expert_steps): {fallos}")
        sys.exit(1)
    if len(all_items) < 100:
        print(f"[g2a] ERROR: {len(all_items)} items < 100 (P0-ii exige N>=100)")
        sys.exit(1)

    with OUT.open("w", encoding="utf-8") as f:
        for it in all_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"[g2a] escrito {len(all_items)} items -> {OUT}")


if __name__ == "__main__":
    main()

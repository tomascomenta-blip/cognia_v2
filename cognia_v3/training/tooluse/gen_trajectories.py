"""
cognia_v3/training/tooluse/gen_trajectories.py
==============================================
Genera trayectorias ReAct VERIFICADAS y las vuelca como pares SFT.

Corre el MISMO loop del deploy (cli.py:_run_agent_task) contra las herramientas
REALES (cognia/agent/tools.py), en un workspace aislado por tarea, con el modelo
local (LlamaBackend). Alimenta al modelo con el input EXACTO del deploy
(_apply_qwen_template + COGNIA_SYSTEM_PROMPT) para que no haya mismatch
train/inference. Guarda SOLO los pasos de trayectorias cuya postcondición pasa.

Uso:
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_trajectories --smoke
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_trajectories \\
        --split train --samples 4 --temperature 0.7 --out data/tooluse_train.jsonl
  venv312\\Scripts\\python.exe -m cognia_v3.training.tooluse.gen_trajectories \\
        --split eval --samples 1 --temperature 0.0 --eval-only   # mide accept-rate base

Salida: JSONL {system, prompt, completion, task_id, step, tool} + report al final.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

# El header del loop es la ÚNICA fuente de verdad del prompt de tool-use; se
# replica idéntico al de cli.py:_run_agent_task para que el dato entrene lo que
# el deploy realmente ve.
_TOOLS_HEADER = (
    "You are an autonomous agent. Start your reply with ACCION: on the first line.\n\n"
    "ACCION: <tool> <args>\n\n"
    "Tools (ONLY these -- do NOT invent others):\n"
)
_TOOLS_FOOTER = (
    "\n  responder <respuesta final>          -- usar SOLO cuando la tarea esta completa\n\n"
    "Rules:\n"
    "- escribir_archivo crea directorios solo. NO uses mkdir.\n"
    "- Para escribir_archivo, pone codigo COMPLETO y REAL despues de | (varias lineas ok).\n"
    "- Usa anotar para guardar resultados intermedios; notas para recordarlos.\n"
    "- Usa recordar/kg_buscar para consultar la memoria de Cognia.\n"
    "- responder solo cuando termines. Nada de texto fuera de la linea ACCION."
)

_ACCION_RE = re.compile(r"ACCI[OÓ]N:\s*(\w+)\s*(.*)", re.IGNORECASE | re.DOTALL)

# Helper canonico compartido con el loop de produccion (cognia/agent/loop.py),
# asi el dato de entrenamiento y el deploy recortan el rambling IGUAL.
from cognia.agent.loop import first_action_block as _first_action_block


def _results_only(history: list) -> str:
    """Transcript SOLO de observaciones de tools (excluye la linea 'TAREA:' y los
    ecos de texto no estructurado del modelo). Evita que el verificador tome como
    'cumplido' un keyword que ya venia en el prompt de la tarea."""
    obs = []
    for h in history[1:]:
        if h.startswith("RESULTADO:"):   # eco de texto del modelo, no una tool real
            continue
        obs.append(h)
    return "\n".join(obs)

# Herramientas que NO se ejecutan en la generación Fase A: 'resumir' dispararía
# un segundo orquestador (otra carga de llama) y las de memoria/KG necesitan el
# cerebro Cognia. Se responden con un error benigno para no colgar el loop; las
# tareas de Fase A no las requieren.
_UNAVAILABLE = {"resumir", "recordar", "memorizar", "kg_buscar", "kg_agregar"}


def build_tools_doc_full() -> str:
    from cognia.agent.tools import build_tools_doc
    return _TOOLS_HEADER + build_tools_doc() + _TOOLS_FOOTER


def _model_input(agent_prompt: str, system: str) -> str:
    from node.inference_pipeline import _apply_qwen_template
    return _apply_qwen_template(agent_prompt, system)


def _normalize_completion(action: str, args: str) -> str:
    args = args.strip()
    return f"ACCION: {action} {args}".rstrip() if args else f"ACCION: {action}"


def _sanitize(text: str, ws_str: str) -> str:
    """Reemplaza el path ABSOLUTO del workspace temporal por rutas relativas, para
    que el dataset no memorice la estructura de directorios de esta máquina. El
    workspace-root en sí -> '.'; los archivos dentro -> ruta relativa."""
    if not ws_str:
        return text
    for sep in ("\\", "/"):
        text = text.replace(ws_str + sep, "")
    text = text.replace(ws_str, ".")
    return text


def _verify_safe(task, ws, transcript) -> bool:
    try:
        return bool(task["verify"](ws, transcript, ""))
    except Exception:
        return False


def run_one_trajectory(task: dict, backend, tools_doc: str, system: str,
                       max_steps: int, temperature: float, seed: int,
                       verbose: bool = False) -> dict:
    """Corre UNA trayectoria en un workspace aislado, con RELABELING HINDSIGHT:
    verifica la postcondición tras cada paso y corta en el PRIMER éxito
    (descarta el loop redundante que el 3B base suele generar). Descarta pasos
    que produjeron ERROR y agrega un cierre limpio `ACCION: responder <answer>`.

    Devuelve: ok(bool), pairs(list[{prompt,completion,tool,task_id,step}]),
    steps, tools_used."""
    from cognia.agent.tools import run_tool
    import cognia.agents.workers.dev_tools as dev_tools

    ws = Path(tempfile.mkdtemp(prefix=f"tu_{task['id']}_")).resolve()
    ws_str = str(ws)
    prev_cwd = os.getcwd()
    prev_root = dev_tools.AGENT_WORKSPACE_ROOT
    dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
    os.chdir(ws)

    ctx = {
        "ai": None,
        "working_memory": {},
        "agent_state": {"files_touched": [], "tasks": []},
        "print_fn": (lambda *a, **k: None),
        "show_diff": None,
    }
    history = [f"TAREA: {task['prompt']}"]
    raw_pairs = []          # candidatos {prompt, completion, tool, errored}
    tools_used = []
    last_sig = None
    repeat = 0
    steps = 0
    success_at = None       # nº de pasos-con-ACCION al primer éxito
    final_ctx = None        # contexto tras el éxito (para el responder sintético)

    try:
        for steps in range(1, max_steps + 1):
            ctx_text = "\n".join(history[-6:])
            agent_prompt = f"{tools_doc}\n\nContexto de la tarea:\n{ctx_text}\n\nSiguiente ACCION:"
            model_in = _model_input(agent_prompt, system)
            raw = backend.generate(model_in, max_tokens=384, temperature=temperature,
                                   seed=seed + steps)
            if not raw or not raw.strip():
                break
            # Quedarse SOLO con el primer bloque de accion (el 3B rambléa varias).
            raw = _first_action_block(raw.strip())
            m = _ACCION_RE.search(raw)
            if not m:
                history.append(f"RESULTADO: (respuesta no estructurada) {raw[:150]}")
                continue

            action = m.group(1).lower().strip()
            args = m.group(2).strip()
            completion = _normalize_completion(action, args)
            if verbose:
                print(f"    paso {steps}: {completion[:90]}")

            if action == "responder":
                # El modelo decidió parar. La terminación limpia la sintetizamos
                # nosotros abajo; si ya había éxito, ctx quedó fijado.
                break

            # Stuck-detector (igual que cli.py): misma accion+args repetida -> corta.
            sig = (action, args[:60])
            if sig == last_sig:
                repeat += 1
                if repeat >= 3:
                    break
            else:
                repeat = 0
            last_sig = sig

            if action in _UNAVAILABLE:
                result = f"RESULTADO {action}: (no disponible en generacion Fase A)"
            else:
                result = run_tool(action, args, ctx)
            errored = bool(re.search(r"\bERROR\b", result))
            raw_pairs.append({"prompt": agent_prompt, "completion": completion,
                              "tool": action, "errored": errored})
            tools_used.append(action)
            history.append(result)
            if verbose:
                print(f"      -> {result[:90]}  [{'ERR' if errored else 'ok'}]")

            # Verificación hindsight: ¿la postcondición ya se cumple? Solo contra
            # las observaciones de tools (no el prompt) para evitar fugas.
            if _verify_safe(task, ws, _results_only(history)):
                success_at = len(raw_pairs)
                final_ctx = "\n".join(history[-6:])
                if verbose:
                    print(f"    -> POSTCONDICION OK en paso {steps}")
                break
    finally:
        os.chdir(prev_cwd)
        dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        shutil.rmtree(ws, ignore_errors=True)

    ok = success_at is not None
    clean = []
    if ok:
        kept = [p for p in raw_pairs[:success_at] if not p["errored"]]
        for i, p in enumerate(kept):
            clean.append({"prompt": _sanitize(p["prompt"], ws_str),
                          "completion": _sanitize(p["completion"], ws_str),
                          "tool": p["tool"], "task_id": task["id"], "step": i + 1})
        # Cierre limpio: enseña a PARAR con una respuesta final plausible.
        final_prompt = (f"{tools_doc}\n\nContexto de la tarea:\n{final_ctx}\n\n"
                        f"Siguiente ACCION:")
        ans = task.get("answer") or "Listo, tarea completada."
        clean.append({"prompt": _sanitize(final_prompt, ws_str),
                      "completion": f"ACCION: responder {ans}",
                      "tool": "responder", "task_id": task["id"], "step": len(kept) + 1})

    return {"ok": ok, "pairs": clean, "steps": steps, "tools_used": tools_used}


def generate(tasks, samples: int, temperature: float, max_steps: int,
             out_path: Path, eval_only: bool, verbose: bool) -> dict:
    from node.llama_backend import LlamaBackend
    from shattering.model_constants import COGNIA_SYSTEM_PROMPT

    print(f"[gen] cargando backend local (llama-server + GGUF)...")
    backend = LlamaBackend.try_load()
    if backend is None:
        raise RuntimeError("No hay backend llama disponible (revisa LLAMA_GGUF_PATH/LLAMA_SERVER_PATH)")
    gg = backend.gguf_path
    print(f"[gen] backend OK, modelo: {gg.name if gg else '?'}")

    tools_doc = build_tools_doc_full()
    system = COGNIA_SYSTEM_PROMPT

    per_task = {}
    seen = set()          # (prompt, completion) ya escritos -> dedup incremental
    n_written = 0
    t0 = time.time()

    # ESCRITURA INCREMENTAL (deadline-safe): se abre el archivo y se vuelca por
    # tarea con flush, de modo que un corte (p.ej. apagado programado) conserva
    # todo lo generado hasta ese punto, no se pierde la corrida entera.
    fh = None
    if not eval_only:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fh = out_path.open("w", encoding="utf-8")

    try:
        for ti, task in enumerate(tasks, 1):
            succ = 0
            task_pairs = []
            for s in range(samples):
                seed = 1000 * ti + s
                r = run_one_trajectory(task, backend, tools_doc, system, max_steps,
                                       temperature, seed, verbose=verbose)
                status = "OK " if r["ok"] else "xx "
                if r["ok"]:
                    succ += 1
                    task_pairs.extend(r["pairs"])
                print(f"[{ti}/{len(tasks)}] {status}{task['id']:<20} "
                      f"sample {s+1}/{samples}  pasos={r['steps']} "
                      f"tools={r['tools_used']}")
            per_task[task["id"]] = {"success": succ, "samples": samples,
                                    "accept_rate": round(succ / samples, 3)}
            # Volcar los pares UNICOS de esta tarea de una, con flush.
            if fh is not None:
                for p in task_pairs:
                    k = (p["prompt"], p["completion"])
                    if k in seen:
                        continue
                    seen.add(k)
                    fh.write(json.dumps(p, ensure_ascii=False) + "\n")
                    n_written += 1
                fh.flush()
    finally:
        if fh is not None:
            fh.close()

    dt = time.time() - t0
    accepted_tasks = sum(1 for v in per_task.values() if v["success"] > 0)
    total_success = sum(v["success"] for v in per_task.values())
    total_tries = sum(v["samples"] for v in per_task.values())
    report = {
        "tasks": len(tasks),
        "samples_per_task": samples,
        "temperature": temperature,
        "trajectory_accept_rate": round(total_success / max(1, total_tries), 3),
        "tasks_with_any_success": f"{accepted_tasks}/{len(tasks)}",
        "sft_pairs": n_written,
        "elapsed_sec": round(dt, 1),
        "per_task": per_task,
        "model": gg.name if gg else None,
    }

    if not eval_only:
        print(f"\n[gen] {n_written} pares SFT (unicos) -> {out_path}")
        report_path = out_path.with_suffix(".report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[gen] reporte -> {report_path}")

    print("\n" + "=" * 60)
    print(f"RESUMEN: accept-rate trayectoria={report['trajectory_accept_rate']} "
          f"| tareas con exito={report['tasks_with_any_success']} "
          f"| pares SFT={report['sft_pairs']} | {dt:.0f}s")
    print("=" * 60)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["train", "eval", "all"], default="train")
    ap.add_argument("--samples", type=int, default=4, help="trayectorias por tarea")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--out", default="cognia_v3/training/tooluse/data/tooluse_train.jsonl")
    ap.add_argument("--eval-only", action="store_true",
                    help="no escribe dataset; solo mide accept-rate (baseline)")
    ap.add_argument("--smoke", action="store_true",
                    help="1 tarea, 1 sample, verbose: verifica que el sustrato corre")
    ap.add_argument("--limit", type=int, default=0, help="usar solo las primeras N tareas del split")
    ap.add_argument("--tasks", default="", help="ids separados por coma (filtra el split)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from cognia_v3.training.tooluse.tasks import TASKS, train_tasks, eval_tasks, by_id

    if args.smoke:
        tasks = [TASKS[0]]
        return generate(tasks, samples=1, temperature=0.0, max_steps=args.max_steps,
                        out_path=Path(args.out), eval_only=True, verbose=True)

    if args.tasks.strip():
        tasks = [by_id(x.strip()) for x in args.tasks.split(",") if by_id(x.strip())]
    else:
        tasks = {"train": train_tasks(), "eval": eval_tasks(), "all": TASKS}[args.split]
    if args.limit > 0:
        tasks = tasks[:args.limit]
    generate(tasks, samples=args.samples, temperature=args.temperature,
             max_steps=args.max_steps, out_path=Path(args.out),
             eval_only=args.eval_only, verbose=args.verbose)


if __name__ == "__main__":
    main()

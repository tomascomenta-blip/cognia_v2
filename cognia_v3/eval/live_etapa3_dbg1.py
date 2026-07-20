# -*- coding: utf-8 -*-
"""Live check e2e de la etapa 3 (COLONIA): DBG1 (tarea SOLO-q35 medida) por
el path REAL de generar_codigo con orquestador y servers de verdad.
COGNIA_HEAVY_CODE=0 aisla la etapa 3 (sin 7B). Veredicto: tests OCULTOS.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.live_etapa3_dbg1
"""
import json
import os
import sys
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ["COGNIA_HEAVY_CODE"] = "0"          # aislar la etapa 3
    os.environ.setdefault("COGNIA_FLEET_RAM_GB", "6")

    tasks = {json.loads(l)["id"]: json.loads(l) for l in
             open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                  encoding="utf-8") if l.strip()}
    t = tasks["DBG1"]
    from cognia.agent.model_router import estimate_difficulty
    dif = estimate_difficulty(t["prompt"])
    print(f"[live] DBG1 entry={t['entry_point']} dif={dif} "
          f"(etapa 3 exige >=0.30)", flush=True)

    from shattering.orchestrator import ShatteringOrchestrator
    orch = ShatteringOrchestrator(
        manifest_path=str(REPO / "shattering" / "manifests" / "cognia_desktop.json"))
    orch._try_load_llama()
    print("[live] orquestador 3B listo", flush=True)

    import cognia.agents.workers.dev_tools as dev
    ws = REPO / "cognia_v3" / "eval" / "_live_ws"
    ws.mkdir(exist_ok=True)
    dev.AGENT_WORKSPACE_ROOT = str(ws)
    ctx = {"ai": types.SimpleNamespace(_orchestrator=orch),
           "agent_state": {}, "print_fn": lambda m: print(f"  {m}", flush=True)}

    import cognia.agent.tools as tools
    t0 = time.time()
    r = tools._generar_codigo(f"dbg1.py | {t['prompt']}", ctx)
    print(f"[live] RESULTADO ({time.time() - t0:.0f}s): {r[:300]}", flush=True)

    hits = list(ws.rglob("dbg1.py"))
    if not hits:
        print("CHECK FALLO: no se escribio dbg1.py")
        return 1
    code = hits[0].read_text(encoding="utf-8")
    from cognia_v3.eval.benchmark_code import run_task_tests
    ok, et, det = run_task_tests(code, t["tests"], t["entry_point"])
    print(f"CHECK [{'OK' if ok else 'FALLO'}] tests OCULTOS de DBG1: "
          f"{'PASA' if ok else et + ' ' + det[:120]}")
    print(f"(etapa 3 declarada en el RESULTADO: "
          f"{'SI' if 'Qwen3.5' in r else 'no'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

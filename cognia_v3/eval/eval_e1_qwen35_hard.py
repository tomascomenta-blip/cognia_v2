# -*- coding: utf-8 -*-
"""E1 (PREREG_E1_QWEN35.md): Qwen3.5-4B no-think greedy sobre tasks_hard_v2
N=40, tests ocultos, protocolo RAW del gate 7B. Persistencia incremental.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_e1_qwen35_hard
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT = REPO / "cognia_v3" / "eval" / "results_e1_qwen35_hard.json"
NOTHINK = "<think>\n\n</think>\n\n"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import os
    os.environ.setdefault("COGNIA_FLEET_RAM_GB", "6")
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code, run_task_tests)
    from node.fleet_registry import fleet_backend, close_fleet30

    tasks = [json.loads(l) for l in
             open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                  encoding="utf-8") if l.strip()]
    res = {"prereg": "PREREG_E1_QWEN35.md", "modelo": "qwen35_4b no-think",
           "protocolo": "RAW greedy 640tok + prefill nothink", "results": {}}
    if OUT.is_file():
        res = json.loads(OUT.read_text(encoding="utf-8"))

    b = fleet_backend("qwen35_4b")
    if b is None:
        print("FALLO: qwen35_4b no arranco")
        return 1
    try:
        for t in tasks:
            if t["id"] in res["results"]:
                continue
            p = build_prompt(t["prompt"], system=SYSTEM_PROMPT) + NOTHINK
            t0 = time.time()
            raw = b.generate(p, max_tokens=640, temperature=0.0,
                             cache_prompt=False) or ""
            code = extract_code(raw)
            ok, et, det = run_task_tests(code, t["tests"], t["entry_point"])
            res["results"][t["id"]] = {"passed": bool(ok), "error_type": et,
                                       "secs": round(time.time() - t0, 1),
                                       "difficulty": t.get("difficulty")}
            n_ok = sum(1 for r in res["results"].values() if r["passed"])
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(f"  [{t['id']}] {'PASS' if ok else 'fail:' + et} "
                  f"({res['results'][t['id']]['secs']}s) — {n_ok}/"
                  f"{len(res['results'])}", flush=True)
    finally:
        close_fleet30()

    n_ok = sum(1 for r in res["results"].values() if r["passed"])
    n = len(res["results"])
    res["veredictos"] = {
        "pass_at_1": [n_ok, n, round(n_ok / max(1, n), 3)],
        "E1-KILL_supera_3B_raw(>=16/40)": n_ok >= 16,
        "E1-MAYOR_supera_ref_GLM(>=21/40)": n_ok >= 21,
        "E1-LAT_secs_media": round(sum(r["secs"] for r in
                                       res["results"].values()) / max(1, n), 1)}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nVEREDICTOS:", json.dumps(res["veredictos"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

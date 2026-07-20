# -*- coding: utf-8 -*-
"""E-PASSK (ROMPER EL TECHO): ¿capacidad o búsqueda? pass@16 temp 0.8 del
mejor coder (qwen35_4b) sobre las 13 no-resueltas, puntuado contra los tests
OCULTOS. Sonda-oráculo (NO desplegable): mide el TECHO de generación.
Persistencia incremental por (tarea, muestra).

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_passk_techo
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT = REPO / "cognia_v3" / "eval" / "results_passk_techo.json"
NOTHINK = "<think>\n\n</think>\n\n"
K = 16
# Las 13 no-resueltas (derivadas por dato en AUTOPSIA_13).
VIRGENES = ["ALG3", "LONG2", "LONG3", "LONG5", "SPEC1", "SPEC2", "SPEC3",
            "SPEC4", "NEWX2", "NEWX3", "NEWX4", "NEWX5", "NEWD2"]


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

    tasks = {json.loads(l)["id"]: json.loads(l) for l in
             open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                  encoding="utf-8") if l.strip()}

    res = {"prereg": "AUTOPSIA_13 / E-PASSK", "modelo": "qwen35_4b",
           "K": K, "temp": 0.8, "muestras": {}}
    if OUT.is_file():
        res = json.loads(OUT.read_text(encoding="utf-8"))

    b = fleet_backend("qwen35_4b")
    if b is None:
        print("FALLO: qwen35_4b no arranco")
        return 1
    try:
        for tid in VIRGENES:
            t = tasks[tid]
            hechos = res["muestras"].setdefault(tid, {})
            base = build_prompt(t["prompt"], system=SYSTEM_PROMPT) + NOTHINK
            for k in range(K):
                if str(k) in hechos:
                    continue
                # muestra 0 greedy (reproducible), resto temp 0.8 seeds
                temp = 0.0 if k == 0 else 0.8
                t0 = time.time()
                raw = b.generate(base, max_tokens=768, temperature=temp,
                                 seed=1000 + k, cache_prompt=False) or ""
                code = extract_code(raw)
                ok, et, _ = run_task_tests(code, t["tests"], t["entry_point"])
                hechos[str(k)] = {"passed": bool(ok), "err": et,
                                  "secs": round(time.time() - t0, 1)}
                OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
                if ok:
                    print(f"  [{tid}] muestra {k}: **PASS** "
                          f"(pass@{k + 1} lo tocó)", flush=True)
            n_ok = sum(1 for v in hechos.values() if v["passed"])
            print(f"[{tid}] pass@{K}: {n_ok}/{K} muestras correctas "
                  f"{'-> RECUPERABLE' if n_ok else '-> ni una'}", flush=True)
    finally:
        close_fleet30()

    # Veredicto: cuántas de las 13 son recuperables por búsqueda
    recuperables = [tid for tid in VIRGENES
                    if any(v["passed"] for v in res["muestras"][tid].values())]
    res["veredicto"] = {
        "recuperables_por_passk": [len(recuperables), recuperables],
        "es_busqueda_no_capacidad(>=4)": len(recuperables) >= 4,
        "pass_at_1_equiv": sum(1 for tid in VIRGENES
                               if res["muestras"][tid].get("0", {}).get("passed"))}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nVEREDICTO:", json.dumps(res["veredicto"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

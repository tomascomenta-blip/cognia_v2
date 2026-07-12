# -*- coding: utf-8 -*-
"""Gate de la MESA REDONDA (PREREG_DELIBERACION.md, congelado 2026-07-12).

Fase 1 (3B): candidato greedy + tests visibles test-first para las 6 tareas
congeladas; cierra el server. Fase 2 (NextCoder-7B): deliberate() 1 ronda con
feedback de ejecucion de los visibles. Fase 3: tests OCULTOS antes/despues.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.gate_mesa_redonda
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

TASK_IDS = ["ALG3", "LONG1", "LONG2", "LONG3", "LONG4", "LONG5"]  # CONGELADAS
OUT = REPO / "cognia_v3" / "eval" / "results_mesa_redonda.json"
PORT_3B = 8188      # puerto propio: no adoptar/tocar el server del CLI


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code, run_task_tests)
    from cognia.agent.candidates import (build_test_gen_prompt,
                                         extract_asserts, TEST_GEN_SYSTEM)
    from cognia.agent.deliberation import deliberate, execution_feedback, feedback_score
    from shattering.model_constants import resolve_gguf_path
    from node.llama_backend import _LlamaServerBackend

    tasks = {json.loads(l)["id"]: json.loads(l)
             for l in open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                           encoding="utf-8") if l.strip()}
    sel = [tasks[i] for i in TASK_IDS]
    res = {"prereg": "PREREG_DELIBERACION.md", "task_ids": TASK_IDS,
           "fase1": {}, "fase2": {}, "veredictos": {}}

    # ── Fase 1: 3B greedy + test-first (server propio, luego se cierra) ──
    print("== FASE 1: candidatos 3B greedy + tests visibles ==", flush=True)
    b3 = _LlamaServerBackend(resolve_gguf_path("3b"), port=PORT_3B, ctx_size=4096)
    cand = {}
    try:
        for t in sel:
            p = build_prompt(t["prompt"], system=SYSTEM_PROMPT)
            raw = b3.generate(p, max_tokens=640, temperature=0.0,
                              cache_prompt=False) or ""
            code = extract_code(raw)
            tg = build_test_gen_prompt(t["prompt"], t["entry_point"], k=4)
            rawt = b3.generate(build_prompt(tg, system=TEST_GEN_SYSTEM),
                               max_tokens=256, temperature=0.0,
                               cache_prompt=False) or ""
            visibles = extract_asserts(rawt, t["entry_point"])
            oculto_antes, et, det = run_task_tests(code, t["tests"], t["entry_point"])
            cand[t["id"]] = {"code": code, "visibles": visibles,
                             "oculto_antes": bool(oculto_antes)}
            print(f"  [{t['id']}] visibles={len(visibles)} oculto_antes="
                  f"{oculto_antes} ({et})", flush=True)
    finally:
        b3.stop()
    res["fase1"] = {k: {"visibles": v["visibles"],
                        "oculto_antes": v["oculto_antes"]}
                    for k, v in cand.items()}

    # ── Fase 2: mesa redonda con NextCoder-7B (1 ronda, PREREG) ──
    print("== FASE 2: mesa redonda con nextcoder7b ==", flush=True)
    import os
    os.environ.setdefault("COGNIA_FLEET_RAM_GB", "6")
    from node.fleet_registry import fleet_backend, close_fleet30
    nc = fleet_backend("nextcoder7b")
    if nc is None:
        print("FALLO: nextcoder7b no arranco")
        return 1
    try:
        def gen_nc(prompt, temperature=0.0, seed=None):
            return nc.generate(build_prompt(prompt, system=SYSTEM_PROMPT),
                               max_tokens=512, temperature=0.0,
                               cache_prompt=False) or ""

        for t in sel:
            c = cand[t["id"]]
            t0 = time.time()
            out = deliberate(t["prompt"], t["entry_point"],
                             [("nextcoder7b", gen_nc)], extract_code,
                             c["visibles"], initial_code=c["code"], rounds=1)
            dt = round(time.time() - t0, 1)
            oculto_despues, et, det = run_task_tests(out["code"], t["tests"],
                                                     t["entry_point"])
            res["fase2"][t["id"]] = {
                "motivo": out["motivo"], "score_visible": out["score"],
                "total_visible": out["total"],
                "mejoro_visible": out["mejorado"],
                "oculto_despues": bool(oculto_despues),
                "error_despues": et, "secs_mesa": dt}
            print(f"  [{t['id']}] mesa={out['motivo']} vis={out['score']}/"
                  f"{out['total']} oculto: {c['oculto_antes']} -> "
                  f"{oculto_despues} ({dt}s)", flush=True)
    finally:
        close_fleet30()

    # ── Veredictos (gates congelados) ──
    antes = {k: cand[k]["oculto_antes"] for k in cand}
    despues = {k: res["fase2"][k]["oculto_despues"] for k in res["fase2"]}
    recuperadas = [k for k in antes if not antes[k] and despues.get(k)]
    rotas = [k for k in antes if antes[k] and not despues.get(k)]
    sobreajuste = [k for k in res["fase2"]
                   if res["fase2"][k]["mejoro_visible"]
                   and not res["fase2"][k]["oculto_despues"]]
    res["veredictos"] = {
        "MR-1_recuperadas_ocultos": [len(recuperadas), recuperadas,
                                     len(recuperadas) >= 2],
        "MR-2_sobreajuste_visible": sobreajuste,
        "rotas": rotas,
        "MR-3_lat_media_s": round(sum(r["secs_mesa"] for r in
                                      res["fase2"].values()) /
                                  max(1, len(res["fase2"])), 1)}
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=True),
                   encoding="utf-8")
    print("\nVEREDICTOS:", json.dumps(res["veredictos"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

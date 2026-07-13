# -*- coding: utf-8 -*-
"""E-ATAQUE-A (ROMPER EL TECHO): mide DOS cosas de una, rápido y decisivo,
sobre las 13 no-resueltas con el 3B (generador de producción, ~2× q35):

  (1) COBERTURA@6 contra tests ocultos: ¿alguna de las 6 muestras pasa?
      -> separa BÚSQUEDA (sí) de CAPACIDAD (no) por ítem.
  (2) CONSENSO vs GREEDY: pick por exec_consensus (S*/CodeT, oráculo
      endurecido) vs pick greedy (candidato 0), ambos contra ocultos.
      -> mide si el techo de ORÁCULO es rompible sin entrenar.

Sonda-oráculo (los ocultos JAMÁS se muestran al modelo; se usan solo para
puntuar). Persistencia incremental por tarea.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_ataque_a
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT = REPO / "cognia_v3" / "eval" / "results_ataque_a.json"
N = 6
VIRGENES = ["ALG3", "LONG2", "LONG3", "LONG5", "SPEC1", "SPEC2", "SPEC3",
            "SPEC4", "NEWX2", "NEWX3", "NEWX4", "NEWX5", "NEWD2"]
PORT_3B = 8188


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code, run_task_tests)
    from cognia.agent.exec_consensus import (build_input_gen_prompt,
                                             consensus_pick,
                                             extract_input_calls,
                                             _INPUT_GEN_SYSTEM)
    from node.llama_backend import _LlamaServerBackend
    from shattering.model_constants import resolve_gguf_path

    tasks = {json.loads(l)["id"]: json.loads(l) for l in
             open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                  encoding="utf-8") if l.strip()}

    res = {"prereg": "RAIZ_GROKKING §4 ataque A", "modelo": "3b", "N": N,
           "tareas": {}}
    if OUT.is_file():
        res = json.loads(OUT.read_text(encoding="utf-8"))

    b = _LlamaServerBackend(resolve_gguf_path("3b"), port=PORT_3B, ctx_size=8192)
    try:
        for tid in VIRGENES:
            if tid in res["tareas"]:
                continue
            t = tasks[tid]
            prompt = build_prompt(t["prompt"], system=SYSTEM_PROMPT)
            t0 = time.time()
            # N candidatos: 0 greedy, resto temp 0.7 (mismo protocolo BoN)
            codes = []
            for k in range(N):
                temp = 0.0 if k == 0 else 0.7
                raw = b.generate(prompt, max_tokens=768, temperature=temp,
                                 seed=42 + k, cache_prompt=False) or ""
                codes.append(extract_code(raw))
            # inputs distinguidores (greedy, prompt propio)
            ig = build_input_gen_prompt(t["prompt"], t["entry_point"], k=6)
            raw_in = b.generate(build_prompt(ig, system=_INPUT_GEN_SYSTEM),
                                max_tokens=256, temperature=0.0,
                                cache_prompt=False) or ""
            inputs = extract_input_calls(raw_in, t["entry_point"])
            # puntajes contra OCULTOS (solo medición)
            oc = [bool(run_task_tests(c, t["tests"], t["entry_point"])[0])
                  for c in codes]
            cobertura = any(oc)
            greedy_ok = oc[0]
            idx_cons, info = consensus_pick(codes, inputs, t["entry_point"])
            cons_ok = (idx_cons is not None and oc[idx_cons])
            res["tareas"][tid] = {
                "cobertura@N": cobertura,
                "cuales_pasan": [i for i, o in enumerate(oc) if o],
                "greedy_ok": greedy_ok,
                "consenso_idx": idx_cons, "consenso_ok": cons_ok,
                "consenso_info": info, "n_inputs": len(inputs),
                "secs": round(time.time() - t0, 1)}
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(f"[{tid}] cob@{N}={cobertura} pasan={res['tareas'][tid]['cuales_pasan']} "
                  f"greedy={greedy_ok} consenso={cons_ok} "
                  f"(idx={idx_cons}, cluster={info['winner_size']}/{info['n_valid']}, "
                  f"{res['tareas'][tid]['secs']}s)", flush=True)
    finally:
        b.stop()

    T = res["tareas"]
    cob = [k for k in T if T[k]["cobertura@N"]]
    g = sum(1 for k in T if T[k]["greedy_ok"])
    c = sum(1 for k in T if T[k]["consenso_ok"])
    res["veredicto"] = {
        "cobertura_busqueda": [len(cob), cob,
                               f"{len(cob)}/13 tienen solucion en el pool@{N}"],
        "greedy_recupera": g,
        "consenso_recupera": c,
        "delta_oraculo(consenso-greedy)": c - g,
        "lectura": ("BUSQUEDA+ORACULO rompibles" if len(cob) >= 4
                    else "mayormente CAPACIDAD")}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nVEREDICTO:", json.dumps(res["veredicto"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

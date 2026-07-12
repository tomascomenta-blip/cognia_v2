# -*- coding: utf-8 -*-
"""E-FEWSHOT (PREREG_EFEWSHOT.md): few-shot recuperado de la biblioteca de
soluciones verificadas, sobre las 13 tareas que nadie resuelve + 5 de
no-regresión. Persistencia incremental.

Uso: venv312\\Scripts\\python.exe -m cognia_v3.eval.eval_efewshot
"""
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OUT = REPO / "cognia_v3" / "eval" / "results_efewshot.json"
NOTHINK = "<think>\n\n</think>\n\n"
PORT_3B = 8188


def trigrams(t):
    t = re.sub(r"\s+", " ", t.lower())
    return Counter(t[i:i + 3] for i in range(len(t) - 2))


def cosine(a, b):
    inter = set(a) & set(b)
    num = sum(a[k] * b[k] for k in inter)
    da = math.sqrt(sum(v * v for v in a.values()))
    db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


def retrieve(task, library, k=2):
    """k soluciones más similares por 3-gramas (leave-one-out por id)."""
    q = trigrams(task["prompt"])
    scored = [(cosine(q, e["tri"]), e) for e in library
              if e["id"] != task["id"]]
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:k]]


def fewshot_block(exemplars):
    parts = []
    for e in exemplars:
        parts.append(f"# Ejemplo resuelto (verificado):\n# Tarea: "
                     f"{e['prompt'][:400]}\n```python\n{e['code'].strip()}\n```")
    return "\n\n".join(parts) + "\n\n# Ahora resuelve la tarea nueva:\n"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import os
    os.environ.setdefault("COGNIA_FLEET_RAM_GB", "6")
    from cognia_v3.eval.benchmark_code import (SYSTEM_PROMPT, build_prompt,
                                               extract_code, run_task_tests)

    tasks = {json.loads(l)["id"]: json.loads(l) for l in
             open(REPO / "cognia_v3" / "eval" / "tasks_hard_v2.jsonl",
                  encoding="utf-8") if l.strip()}
    g7 = json.loads((REPO / "cognia_v3" / "eval" /
                     "results_code_gate7b_n40_20260710_1614.json")
                    .read_text(encoding="utf-8"))
    e1 = json.loads((REPO / "cognia_v3" / "eval" /
                     "results_e1_qwen35_hard.json")
                    .read_text(encoding="utf-8"))["results"]

    # Biblioteca: código verificado (stage first/cascade) con su prompt.
    library = []
    for r in g7["results"]:
        if r.get("stage") in ("first", "cascade") and r.get("extracted_code"):
            library.append({"id": r["id"], "prompt": tasks[r["id"]]["prompt"],
                            "code": r["extracted_code"],
                            "tri": trigrams(tasks[r["id"]]["prompt"])})
    # Gate set: nadie las resuelve (ni cascada ni q35) — derivado por dato.
    resueltas_casc = {r["id"] for r in g7["results"]
                      if r.get("stage") in ("first", "cascade")}
    resueltas_q35 = {i for i in e1 if e1[i]["passed"]}
    virgenes = [i for i in tasks if i not in resueltas_casc
                and i not in resueltas_q35]
    noreg = [r["id"] for r in g7["results"]
             if r.get("stage") == "first"][:5]
    print(f"[fs] biblioteca={len(library)} virgenes={len(virgenes)} "
          f"noreg={noreg}", flush=True)

    res = {"prereg": "PREREG_EFEWSHOT.md", "virgenes": virgenes,
           "noreg_ids": noreg, "brazos": {}}
    if OUT.is_file():
        res = json.loads(OUT.read_text(encoding="utf-8"))

    def corre_brazo(nombre, backend, prefill):
        hecho = res["brazos"].setdefault(nombre, {})
        for tid in virgenes + noreg:
            if tid in hecho:
                continue
            t = tasks[tid]
            ex = retrieve(t, library, k=2)
            user = fewshot_block(ex) + t["prompt"]
            p = build_prompt(user, system=SYSTEM_PROMPT) + prefill
            t0 = time.time()
            raw = backend.generate(p, max_tokens=640, temperature=0.0,
                                   cache_prompt=False) or ""
            code = extract_code(raw)
            ok, et, _ = run_task_tests(code, t["tests"], t["entry_point"])
            hecho[tid] = {"passed": bool(ok), "error_type": et,
                          "virgen": tid in virgenes,
                          "exemplars": [e["id"] for e in ex],
                          "secs": round(time.time() - t0, 1)}
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(f"  [{nombre}][{tid}] {'PASS' if ok else 'fail:' + et} "
                  f"(ex={[e['id'] for e in ex]})", flush=True)

    # Brazo A: 3B
    if not all(t in res["brazos"].get("3b_fs", {}) for t in virgenes + noreg):
        from node.llama_backend import _LlamaServerBackend
        from shattering.model_constants import resolve_gguf_path
        b3 = _LlamaServerBackend(resolve_gguf_path("3b"), port=PORT_3B,
                                 ctx_size=8192)
        try:
            corre_brazo("3b_fs", b3, "")
        finally:
            b3.stop()

    # Brazo B: qwen35 no-think
    if not all(t in res["brazos"].get("q35_fs", {}) for t in virgenes + noreg):
        from node.fleet_registry import fleet_backend, close_fleet30
        q = fleet_backend("qwen35_4b")
        if q is not None:
            try:
                corre_brazo("q35_fs", q, NOTHINK)
            finally:
                close_fleet30()

    # Veredictos
    a = res["brazos"].get("3b_fs", {})
    b = res["brazos"].get("q35_fs", {})
    rec = sorted({i for i in virgenes
                  if a.get(i, {}).get("passed") or b.get(i, {}).get("passed")})
    reg = [i for i in noreg
           if a.get(i) and not a[i]["passed"]]   # regresión del brazo 3B
    res["veredictos"] = {
        "FS-1_virgenes_recuperadas(>=2)": [len(rec), rec, len(rec) >= 2],
        "FS-2_regresiones_3b(0)": [len(reg), reg, len(reg) == 0],
        "detalle": {"3b_fs_virgenes": sum(1 for i in virgenes
                                          if a.get(i, {}).get("passed")),
                    "q35_fs_virgenes": sum(1 for i in virgenes
                                           if b.get(i, {}).get("passed"))}}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nVEREDICTOS:", json.dumps(res["veredictos"], indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

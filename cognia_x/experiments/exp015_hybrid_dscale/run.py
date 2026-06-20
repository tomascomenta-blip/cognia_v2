"""
exp015 — CYCLE 28: H-HYB-2. ¿La recuperación de recall del HÍBRIDO es d-dependiente? (barrido de d)

CONTEXTO (exp014, CYCLE 27): a d=24 el híbrido interleaved (2 lineal + 2 atención) NO recupera recall —
platea en 0.186 (= lineal puro) aun con 10000 steps, mientras la atención pura cruza (0.95). PERO CYCLE 6
(H-MEZ-4) mostró el híbrido a 0.99 a d=64. H-HYB-2: la recuperación del híbrido es d-dependiente — las
capas LINEALES de baja capacidad (a d chico) bottleneckean el recall; con d suficiente dejan de hacerlo.

HIPOTESIS H-HYB-2 (este experimento): subir d hace que el MISMO híbrido (attn_every=2, 2 lineal + 2
atención) cruce el plateau ~0.18 que tiene a d=24.
  APOYADA SI: el híbrido recupera recall (>> 0.18, umbral >= 0.40) a d=48 y/o d=64 (reconcilia con CYCLE 6).
  REFUTADA SI: el híbrido sigue ~0.18 aun a d=64 -> el cuello NO es d (sería el arreglo lineal-primero o
    la carga np); contradiría a CYCLE 6 y exigiría revisar la reconciliación.

DISENO — 3 brazos, n_heads=4, n_pairs=16, seed0, steps=6000, attn_every=2 (2 lineal + 2 atención) FIJO,
variando SOLO d_model:
  1) hibrido_d24 : d=24  -> baseline bottleneckeado (exp014: 0.186).
  2) hibrido_d48 : d=48  -> punto intermedio (exp009 vio al híbrido separar a d=48).
  3) hibrido_d64 : d=64  -> el d de CYCLE 6 (deberia recuperar ~0.99 si el cuello es d).
Misma receta de optim. early_stop=0.95 corta si el híbrido cruza recall. d/n_heads=4 -> d_head 6/12/16 (par).

----------------------------------------------------------------------------------------------------
Escalabilidad: 3 híbridos tiny; sin coste Taylor. d=64 es el más pesado (~2.7x el matmul de d=24) pero
L=48 lo mantiene barato. Deadline POR brazo (~15 min) -> total acotado. torch.set_num_threads(3).
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp015_hybrid_dscale.run --smoke
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp015_hybrid_dscale.run
"""
import argparse
import json
import os
import sys
import time

import torch

from cognia_x.train.recall_task import train_and_eval

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

RECIPE = dict(n_heads=4, n_vals=16, n_queries=16, n_keys=160, batch=64, lr=1e-3)
N_LAYERS = 4
N_PAIRS = 16
ATTN_EVERY = 2          # 2 lineal + 2 atencion, FIJO -> la unica variable es d
EARLY_STOP = 0.95
BASELINE = "hibrido_d24"
RECOVER_THRESH = 0.40   # "recupera" = recall claramente fuera del plateau ~0.18


def arms():
    return [
        dict(name="hibrido_d24", d_model=24, note="baseline bottleneckeado (exp014=0.186)"),
        dict(name="hibrido_d48", d_model=48, note="intermedio (exp009 separo a d=48)"),
        dict(name="hibrido_d64", d_model=64, note="d de CYCLE 6 (deberia recuperar ~0.99)"),
    ]


def main():
    ap = argparse.ArgumentParser(description="exp015 — la recuperacion del hibrido es d-dependiente? (H-HYB-2)")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--warmup", type=int, default=None)
    ap.add_argument("--per_config_sec", type=float, default=None)
    ap.add_argument("--only", type=str, default=None)
    args = ap.parse_args()

    if args.smoke:
        steps = args.steps if args.steps is not None else 400
        warmup = args.warmup if args.warmup is not None else 60
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 90.0
    else:
        steps = args.steps if args.steps is not None else 6000
        warmup = args.warmup if args.warmup is not None else 250
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 900.0

    torch.set_num_threads(3)
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n")
        logf.flush()

    selected = arms()
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        selected = [a for a in selected if a["name"] in keep]

    chance = 1.0 / RECIPE["n_vals"]
    log(f"[exp015] inicio smoke={args.smoke} attn_every={ATTN_EVERY} n_pairs={N_PAIRS} steps={steps} "
        f"warmup={warmup} per_config={per_config_sec:.0f}s seed={args.seed} azar={chance:.4f} "
        f"brazos={[(a['name'], a['d_model']) for a in selected]}")

    grid = []
    acc_by_name = {}
    t_start = time.time()

    for a in selected:
        t0 = time.time()
        deadline = time.time() + per_config_sec
        try:
            r = train_and_eval(
                a["name"], attn_every=ATTN_EVERY, steps=steps, log=log, seed=args.seed,
                d_model=a["d_model"], n_layers=N_LAYERS, n_pairs=N_PAIRS,
                warmup=warmup, early_stop=EARLY_STOP, deadline=deadline, **RECIPE)
            acc, params = r["final_acc"], r["params"]
            log(f"[exp015] {a['name']:<12} ({a['note']}) d={a['d_model']} "
                f"acc={acc:.3f} azar={r['chance']:.4f} params={params:,} ({(time.time()-t0)/60:.1f} min)")
        except Exception as e:  # noqa: BLE001
            acc, params = None, None
            log(f"[exp015] {a['name']} ERROR {e!r}")
        grid.append({"name": a["name"], "d_model": a["d_model"], "attn_every": ATTN_EVERY,
                     "note": a["note"], "final_acc": acc, "chance": chance, "params": params})
        acc_by_name[a["name"]] = acc
        _dump(grid, chance, args, steps, warmup, summary=None)

    summary = _build_summary(acc_by_name, chance)
    _dump(grid, chance, args, steps, warmup, summary=summary)

    log("[exp015] ==== RESUMEN — el hibrido (2 lin + 2 attn) recupera recall al subir d? ====")
    base = acc_by_name.get(BASELINE)
    log(f"azar={chance:.4f}  baseline(d24)={base if base is None else round(base,3)}  umbral_recupera={RECOVER_THRESH}")
    log(f"{'brazo':>12} | {'d':>4} | {'recall acc':>10} | nota")
    log("-" * 72)
    for a in selected:
        v = acc_by_name.get(a["name"])
        vs = f"{v:.3f}" if isinstance(v, float) else "   -   "
        log(f"{a['name']:>12} | {a['d_model']:>4} | {vs:>10} | {a['note']}")
    log("-" * 72)
    log(f"[exp015] HEADLINE: {summary['headline']}")
    log(f"[exp015] tiempo total {(time.time()-t_start)/60:.1f} min")
    logf.close()


def _build_summary(acc_by_name, chance):
    base = acc_by_name.get(BASELINE)
    recovered = [k for k, v in acc_by_name.items() if k != BASELINE and isinstance(v, float) and v >= RECOVER_THRESH]
    by_d = {k: acc_by_name.get(k) for k in ("hibrido_d24", "hibrido_d48", "hibrido_d64")}

    if recovered:
        headline = ("H-HYB-2 APOYADA: el hibrido RECUPERA recall al subir d ({} cruza(n) >= {}) -> el cuello "
                    "del hibrido a d chico ES la capacidad lineal (d-dependiente); reconcilia con CYCLE 6 "
                    "(hibrido a d=64). El hibrido necesita d suficiente.").format(" y ".join(recovered), RECOVER_THRESH)
    elif any(isinstance(v, float) for v in by_d.values()):
        headline = ("H-HYB-2 REFUTADA a d<=64: el hibrido sigue ~0.18 aun a d=64 -> el cuello NO es solo d "
                    "(seria el arreglo lineal-primero o la carga np); tension con CYCLE 6 a revisar.")
    else:
        headline = "INCONCLUSO: faltan datos."

    bits = [f"{k}={v:.3f}" for k, v in acc_by_name.items() if isinstance(v, float)]
    return {
        "chance": chance, "baseline": BASELINE, "baseline_acc": base, "acc_by_name": acc_by_name,
        "recover_thresh": RECOVER_THRESH, "recovered": recovered, "by_d": by_d,
        "headline": headline, "headline_full": headline + " " + "; ".join(bits) + ".",
    }


def _dump(grid, chance, args, steps, warmup, summary=None):
    out = {
        "experiment": "exp015_hybrid_dscale",
        "hypothesis": ("H-HYB-2: la recuperacion de recall del hibrido (2 lineal + 2 atencion) es "
                       "d-dependiente -> sube d y el hibrido cruza el plateau ~0.18 que tiene a d=24."),
        "smoke": args.smoke, "seed": args.seed, "n_layers": N_LAYERS, "attn_every": ATTN_EVERY,
        "n_pairs": N_PAIRS, "recipe": RECIPE, "steps": steps, "warmup": warmup,
        "early_stop": EARLY_STOP, "chance": chance, "recover_thresh": RECOVER_THRESH, "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

"""
exp014 — CYCLE 27: H-HYB-1. ¿El HÍBRIDO cierra la brecha con la atención pura si le doy más BUDGET?

CONTEXTO (exp013, CYCLE 26): a d=24, steps=3000 step-parity, la atención pura cruzó el plateau (0.882)
pero el híbrido 50/50 quedó en ~0.18 — PERO todavía ASCENDIENTE (hibrido_h4: 0.06->0.105->0.152->0.190),
no plateau. Diagnóstico: under-trained, no falla estructural. H-HYB-1 (abierta): el híbrido es más DURO de
optimizar que la atención pura a d chico (las capas lineales endurecen el landscape), pero CAN (CYCLE 6:
0.99 con la receta/budget adecuados).

HIPOTESIS H-HYB-1 (este experimento): con MÁS steps, el híbrido a d=24 sube el recall MUY por encima del
plateau ~0.18, cerrando la brecha hacia la atención pura (0.882).
  APOYADA SI: hibrido_h4 a 10000 steps alcanza recall >> 0.18 (umbral >= 0.40, claramente fuera del plateau).
  REFUTADA SI: hibrido_h4 sigue ~0.18 con 10000 steps -> sería falla ESTRUCTURAL del interleaving a d chico
    (las capas lineales bloquean el recall de las de atención), no under-training.

DISENO — 2 brazos, d=24 FIJO, n_heads=4, n_pairs=16, seed0, steps=10000 (3.3x el step-parity de exp013):
  1) hibrido_h4   : attn_every=2 (2 lineales + 2 atención) -> el brazo de la hipótesis.
  2) atencion_h4  : attn_every=1 (atención pura)           -> referencia (ya cruzó 0.882 en exp013).
Misma receta de optim que exp013. early_stop=0.95 corta si el híbrido cruza recall.

----------------------------------------------------------------------------------------------------
Escalabilidad: 2 modelos tiny d=24; sin coste Taylor. steps=10000 ~13 min/brazo (~13 steps/s medido en
exp013). torch.set_num_threads(3). Deadline POR brazo. early_stop corta el híbrido si cruza 0.95.
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp014_hybrid_budget.run --smoke
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp014_hybrid_budget.run
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
D_MODEL = 24
N_LAYERS = 4
N_PAIRS = 16
EARLY_STOP = 0.95
CLOSE_THRESH = 0.40   # "cierra la brecha" = recall claramente fuera del plateau ~0.18, hacia la atención


def arms():
    return [
        dict(name="hibrido_h4", attn_every=2, note="2 lineales + 2 atencion (hipotesis H-HYB-1)"),
        dict(name="atencion_h4", attn_every=1, note="atencion pura (referencia; exp013=0.882)"),
    ]


def main():
    ap = argparse.ArgumentParser(description="exp014 — el hibrido cierra la brecha con mas budget? (H-HYB-1)")
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
        steps = args.steps if args.steps is not None else 10000
        warmup = args.warmup if args.warmup is not None else 250
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 1200.0

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
    log(f"[exp014] inicio smoke={args.smoke} d={D_MODEL} n_pairs={N_PAIRS} steps={steps} warmup={warmup} "
        f"per_config={per_config_sec:.0f}s seed={args.seed} azar={chance:.4f} brazos={[a['name'] for a in selected]}")

    grid = []
    acc_by_name = {}
    t_start = time.time()

    for a in selected:
        t0 = time.time()
        deadline = time.time() + per_config_sec
        try:
            r = train_and_eval(
                a["name"], attn_every=a["attn_every"], steps=steps, log=log, seed=args.seed,
                d_model=D_MODEL, n_layers=N_LAYERS, n_pairs=N_PAIRS,
                warmup=warmup, early_stop=EARLY_STOP, deadline=deadline, **RECIPE)
            acc, params = r["final_acc"], r["params"]
            log(f"[exp014] {a['name']:<12} ({a['note']}) attn_every={a['attn_every']} "
                f"acc={acc:.3f} azar={r['chance']:.4f} params={params:,} ({(time.time()-t0)/60:.1f} min)")
        except Exception as e:  # noqa: BLE001
            acc, params = None, None
            log(f"[exp014] {a['name']} ERROR {e!r}")
        grid.append({"name": a["name"], "attn_every": a["attn_every"], "note": a["note"],
                     "final_acc": acc, "chance": chance, "params": params})
        acc_by_name[a["name"]] = acc
        _dump(grid, chance, args, steps, warmup, summary=None)

    summary = _build_summary(acc_by_name, chance, steps)
    _dump(grid, chance, args, steps, warmup, summary=summary)

    log("[exp014] ==== RESUMEN — el hibrido cierra la brecha con mas budget? (d=24, steps={}) ====".format(steps))
    log(f"azar={chance:.4f}  plateau_lineal=0.18  atencion_pura(exp013)=0.882  umbral_cierre={CLOSE_THRESH}")
    log(f"{'brazo':>12} | {'recall acc':>10} | nota")
    log("-" * 70)
    for a in selected:
        v = acc_by_name.get(a["name"])
        vs = f"{v:.3f}" if isinstance(v, float) else "   -   "
        log(f"{a['name']:>12} | {vs:>10} | {a['note']}")
    log("-" * 70)
    log(f"[exp014] HEADLINE: {summary['headline']}")
    log(f"[exp014] tiempo total {(time.time()-t_start)/60:.1f} min")
    logf.close()


def _build_summary(acc_by_name, chance, steps):
    hyb = acc_by_name.get("hibrido_h4")
    ref = acc_by_name.get("atencion_h4")
    closes = isinstance(hyb, float) and hyb >= CLOSE_THRESH

    if closes:
        headline = ("H-HYB-1 APOYADA: con {} steps el hibrido sube a {} (>> plateau 0.18) -> era "
                    "UNDER-TRAINING, no falla estructural; el hibrido cierra la brecha con mas budget "
                    "(atencion pura ref={}).").format(steps, round(hyb, 3) if isinstance(hyb, float) else hyb,
                                                      round(ref, 3) if isinstance(ref, float) else ref)
    elif isinstance(hyb, float):
        headline = ("H-HYB-1 REFUTADA a {} steps: el hibrido sigue en {} (~plateau) pese a 3.3x el budget "
                    "-> apunta a falla ESTRUCTURAL del interleaving a d chico (las capas lineales bloquean "
                    "el recall), no solo under-training. (atencion pura ref={}).").format(
                        steps, round(hyb, 3), round(ref, 3) if isinstance(ref, float) else ref)
    else:
        headline = "INCONCLUSO: falta el dato del hibrido."

    bits = [f"{k}={v:.3f}" for k, v in acc_by_name.items() if isinstance(v, float)]
    return {
        "chance": chance, "steps": steps, "close_thresh": CLOSE_THRESH,
        "hibrido_acc": hyb, "atencion_acc": ref, "closes": closes,
        "acc_by_name": acc_by_name, "headline": headline, "headline_full": headline + " " + "; ".join(bits) + ".",
    }


def _dump(grid, chance, args, steps, warmup, summary=None):
    out = {
        "experiment": "exp014_hybrid_budget",
        "hypothesis": ("H-HYB-1: el hibrido (mayoria lineal + pocas atencion) a d=24 cierra la brecha con "
                       "la atencion pura (0.882) si se le da mas budget -> el 0.18 de exp013 era "
                       "under-training, no falla estructural."),
        "smoke": args.smoke, "seed": args.seed, "d_model": D_MODEL, "n_layers": N_LAYERS,
        "n_pairs": N_PAIRS, "recipe": RECIPE, "steps": steps, "warmup": warmup,
        "early_stop": EARLY_STOP, "chance": chance, "close_thresh": CLOSE_THRESH, "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

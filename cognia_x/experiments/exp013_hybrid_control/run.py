"""
exp013 — CYCLE 26: control POSITIVO de la linea H-CEIL. ¿La ATENCION cruza el plateau ~0.18 donde el
lineal puro (6 levers refutados: exp010 ancho, exp011 forma+init, exp012 profundidad/escala/optim) no?

CONTEXTO: CYCLE 25 concluyo que el techo de recall del mezclador de estado fijo es ESTRUCTURAL y que el
remedio es ARQUITECTONICO (la atencion del hibrido, D-CEIL-1/D-CEIL-4). CYCLE 6 (H-MEZ-4) ya lo mostro a
OTRA escala (np=8: lineal 0.255 -> hibrido 0.998). Este experimento lo confirma a la MISMA escala de la
linea H-CEIL (d=24, n_pairs=16, steps=3000 step-parity) -> conclusion autocontenida, no por eliminacion.

HIPOTESIS (control positivo): a d=24, n_pairs=16, steps iguales, anadir ATENCION (capas softmax, estado
proporcional a L) cruza el plateau ~0.18 que el lineal puro no cruza con NINGUN tuning.
  CONFIRMADO SI: algun brazo con atencion alcanza recall >> 0.18 (umbral >=0.30, MUY por encima del ruido).
  (Si NO cruzara a esta escala/receta, seria un null informativo: la atencion necesitaria otra receta —
   se reportaria honestamente; la conclusion estructural de CYCLE 25 se apoya ademas en CYCLE 6.)

DISENO — 4 brazos, d=24 FIJO, n_pairs=16, seed0, steps=3000 step-parity, misma receta de optim:
  1) lineal_h1     : attn_every=0, n_heads=1  -> BASELINE (reproduce exp012 lin_d24_L4 ~0.173).
  2) hibrido_h1    : attn_every=2, n_heads=1  -> 2 capas de atencion (L=4) a 1 cabeza.
  3) hibrido_h4    : attn_every=2, n_heads=4  -> 2 capas de atencion a 4 cabezas (receta ganadora CYCLE 6).
  4) atencion_h4   : attn_every=1, n_heads=4  -> atencion pura (cota superior del recall).
n_heads varia SOLO en los brazos de atencion (la atencion se beneficia de multi-cabeza; CYCLE 6 uso h=4);
el lineal_h1 ancla al baseline establecido. d=24,h=4 -> d_head=6 (par, RoPE OK).

----------------------------------------------------------------------------------------------------
Escalabilidad: O(n_brazos*steps). 4 modelos tiny; la atencion es O(L^2) pero L=48 -> trivial (sin el
coste dim-325 del Taylor de exp011). Deadline POR brazo. torch.set_num_threads(3). early_stop=0.95:
los brazos de atencion CRUZAN recall y cortan temprano (CYCLE 6: ~1200 pasos) -> mas rapido aun.
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp013_hybrid_control.run --smoke
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp013_hybrid_control.run
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

RECIPE = dict(n_vals=16, n_queries=16, n_keys=160, batch=64, lr=1e-3)
D_MODEL = 24
N_LAYERS = 4
N_PAIRS = 16
EARLY_STOP = 0.95
BASELINE = "lineal_h1"
CROSS_THRESH = 0.30   # "cruza" = recall MUY por encima del plateau ~0.18 (no ruido)


def arms():
    return [
        dict(name="lineal_h1", attn_every=0, n_heads=1, note="BASELINE lineal puro (~0.173)"),
        dict(name="hibrido_h1", attn_every=2, n_heads=1, note="2 capas atencion, h=1"),
        dict(name="hibrido_h4", attn_every=2, n_heads=4, note="2 capas atencion, h=4 (receta CYCLE 6)"),
        dict(name="atencion_h4", attn_every=1, n_heads=4, note="atencion pura, h=4 (cota superior)"),
    ]


def main():
    ap = argparse.ArgumentParser(description="exp013 — control positivo: la atencion cruza el plateau? (H-CEIL)")
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
        steps = args.steps if args.steps is not None else 3000
        warmup = args.warmup if args.warmup is not None else 250
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 600.0

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
    log(f"[exp013] inicio smoke={args.smoke} d={D_MODEL} n_pairs={N_PAIRS} steps={steps} warmup={warmup} "
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
                d_model=D_MODEL, n_layers=N_LAYERS, n_heads=a["n_heads"], n_pairs=N_PAIRS,
                warmup=warmup, early_stop=EARLY_STOP, deadline=deadline, **RECIPE)
            acc, params = r["final_acc"], r["params"]
            log(f"[exp013] {a['name']:<12} ({a['note']}) attn_every={a['attn_every']} h={a['n_heads']} "
                f"acc={acc:.3f} azar={r['chance']:.4f} params={params:,} ({(time.time()-t0)/60:.1f} min)")
        except Exception as e:  # noqa: BLE001
            acc, params = None, None
            log(f"[exp013] {a['name']} ERROR {e!r}")
        grid.append({"name": a["name"], "attn_every": a["attn_every"], "n_heads": a["n_heads"],
                     "note": a["note"], "final_acc": acc, "chance": chance, "params": params})
        acc_by_name[a["name"]] = acc
        _dump(grid, chance, args, steps, warmup, summary=None)

    summary = _build_summary(acc_by_name, chance)
    _dump(grid, chance, args, steps, warmup, summary=summary)

    log("[exp013] ==== RESUMEN — control positivo: la ATENCION cruza el plateau del lineal? (d=24) ====")
    base = acc_by_name.get(BASELINE)
    log(f"azar={chance:.4f}  baseline(lineal)={base if base is None else round(base,3)}  umbral_cruce={CROSS_THRESH}")
    log(f"{'brazo':>12} | {'recall acc':>10} | {'delta vs base':>13} | nota")
    log("-" * 80)
    for a in selected:
        v = acc_by_name.get(a["name"])
        def fmt(x):
            return f"{x:.3f}" if isinstance(x, float) else "   -   "
        delta = (v - base) if isinstance(v, float) and isinstance(base, float) else None
        dstr = (f"{delta:+.3f}" if isinstance(delta, float) else "   -   ")
        log(f"{a['name']:>12} | {fmt(v):>10} | {dstr:>13} | {a['note']}")
    log("-" * 80)
    log(f"[exp013] HEADLINE: {summary['headline']}")
    log(f"[exp013] tiempo total {(time.time()-t_start)/60:.1f} min")
    logf.close()


def _build_summary(acc_by_name, chance):
    base = acc_by_name.get(BASELINE)
    attn_arms = {k: v for k, v in acc_by_name.items() if k != BASELINE and isinstance(v, float)}
    crossers = [k for k, v in attn_arms.items() if v >= CROSS_THRESH]
    best = max(attn_arms.items(), key=lambda p: p[1]) if attn_arms else (None, None)

    if crossers:
        headline = ("CONTROL POSITIVO CONFIRMADO: la ATENCION cruza el plateau ~0.18 del lineal puro "
                    "({} alcanza(n) recall >= {}) -> el remedio del recall es arquitectonico (atencion), "
                    "como concluyo CYCLE 25. Mejor: {}={}.").format(
                        " y ".join(crossers), CROSS_THRESH, best[0], round(best[1], 3) if best[1] else best[1])
    elif attn_arms:
        headline = ("NULL a esta receta: ningun brazo de atencion cruza {} (mejor {}={}); la atencion "
                    "necesitaria otra receta a esta escala. La conclusion estructural de CYCLE 25 se apoya "
                    "ademas en CYCLE 6 (donde la atencion SI cruzo).").format(
                        CROSS_THRESH, best[0], round(best[1], 3) if best[1] else best[1])
    else:
        headline = "INCONCLUSO: faltan datos de los brazos de atencion."

    bits = [f"{k}={v:.3f}" for k, v in acc_by_name.items() if isinstance(v, float)]
    return {
        "chance": chance, "baseline": BASELINE, "baseline_acc": base, "acc_by_name": acc_by_name,
        "cross_thresh": CROSS_THRESH, "crossers": crossers, "best_attn": list(best),
        "headline": headline, "headline_full": headline + " " + "; ".join(bits) + ".",
    }


def _dump(grid, chance, args, steps, warmup, summary=None):
    out = {
        "experiment": "exp013_hybrid_control",
        "hypothesis": ("Control positivo de la linea H-CEIL: anadir ATENCION cruza el plateau ~0.18 del "
                       "lineal puro (6 levers refutados) a d=24 -> el remedio del recall es arquitectonico."),
        "smoke": args.smoke, "seed": args.seed, "d_model": D_MODEL, "n_layers": N_LAYERS,
        "n_pairs": N_PAIRS, "recipe": RECIPE, "steps": steps, "warmup": warmup,
        "early_stop": EARLY_STOP, "chance": chance, "cross_thresh": CROSS_THRESH, "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

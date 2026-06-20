"""
exp012 — CYCLE 25: el plateau de recall del lineal PURO, ¿se levanta con PROFUNDIDAD / ESCALA-d /
OPTIMIZADOR (sin atencion)?

CONTEXTO (la triple refutacion previa):
  - exp009: el lineal puro entrenado satura su recall en ~0.18 (azar 0.0625) desde d~24.
  - exp010 (H-CEIL-2 REFUTADA): el ANCHO del feature-map no lo levanta (16x estado -> +0.000).
  - exp011 (H-CEIL-3 REFUTADA): ni la FORMA del kernel (Taylor) ni la INIT (mimetic) lo levantan
    (taylor=0.160 < baseline 0.173; mimetic +0.0098, ruido).
El cuello NO es del feature-map. H-CEIL-4: es de PROFUNDIDAD/ESCALA/OPTIMIZADOR o requiere ATENCION.

Este experimento aisla lo NOVEDOSO: ¿el lineal PURO (sin atencion) cruza el plateau con mas
profundidad, mas d, o mejor optimizacion? La atencion ya se sabe que recupera el recall (CYCLE 6,
H-MEZ-4: a np alto el lineal satura y el hibrido con >=2 capas de atencion lo recupera) — por eso aqui
NO se re-testea la atencion; se ataca la parte abierta. Apoyo tier-1: Okpekpe & Orvieto 2025
(arXiv:2508.19029): gran parte de la brecha de recall de los SSM es de OPTIMIZACION, no expresividad.

HIPOTESIS (clausula de H-CEIL-4 que toca este experimento): a n_pairs=16 fijo y steps IGUALES, ALGUN
lever de {profundidad, d, optimizador} sube el recall del lineal PURO por encima de ~0.18.
  REFUTADA SI: ninguno cruza el baseline -> el plateau del estado fijo a esta escala es robusto tambien
    a profundidad/escala/optimizador -> solo la ATENCION lo levanta (refuerza D-CEIL-1, estructural).

DISENO — 4 brazos lineales PUROS (attn_every=0), n_heads=1, n_pairs=16, seed0, steps=3000 step-parity,
misma receta que exp011 salvo el lever que cada brazo cambia:
  1) lin_d24_L4   : d=24, n_layers=4, lr=1e-3                 -> BASELINE (reproduce exp011 elu_base ~0.173).
  2) lin_d24_L8   : d=24, n_layers=8, lr=1e-3                 -> lever PROFUNDIDAD (2x capas).
  3) lin_d48_L4   : d=48, n_layers=4, lr=1e-3                 -> lever ESCALA-d (estado 24^2->48^2; exp009 vio separar a d=48).
  4) lin_d24_L4_hi: d=24, n_layers=4, lr=3e-3                 -> lever OPTIMIZADOR (LR 3x; Okpekpe&Orvieto).

----------------------------------------------------------------------------------------------------
Escalabilidad Obligatoria:
  - Tiempo:  O(n_brazos * steps). 4 modelos tiny lineales (sin el coste dim-325 del Taylor de exp011):
    feature dim = d_head (24 o 48), q@k.T barato a L=48. Deadline POR brazo (~7 min) -> total acotado.
    torch.set_num_threads(3) (i3). early_stop=0.95 corta si algun brazo cruza recall (informativo).
  - Espacio:  modelos diminutos; d48/L8 agregan pocos params. Un results.json chico. Sin checkpoints.
  - CPU / multi-dispositivo:  todo CPU, sin CUDA. Reproducible (seed=0). Portable.
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp012_depth_scale.run --smoke   # rapido
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp012_depth_scale.run           # FULL acotado
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

# Misma receta que exp011; cada brazo cambia UN lever (n_layers / d_model / lr).
RECIPE = dict(n_heads=1, n_vals=16, n_queries=16, n_keys=160, batch=64)
N_PAIRS = 16
EARLY_STOP = 0.95
BASELINE = "lin_d24_L4"


def arms():
    return [
        dict(name="lin_d24_L4", d_model=24, n_layers=4, lr=1e-3, note="BASELINE (exp011 elu_base ~0.173)"),
        dict(name="lin_d24_L8", d_model=24, n_layers=8, lr=1e-3, note="PROFUNDIDAD (2x capas)"),
        dict(name="lin_d48_L4", d_model=48, n_layers=4, lr=1e-3, note="ESCALA-d (estado 24^2->48^2)"),
        dict(name="lin_d24_L4_hi", d_model=24, n_layers=4, lr=3e-3, note="OPTIMIZADOR (LR 3x)"),
    ]


def main():
    ap = argparse.ArgumentParser(description="exp012 — el plateau lineal: profundidad/escala/optimizador? (H-CEIL-4)")
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
    log(f"[exp012] inicio smoke={args.smoke} n_pairs={N_PAIRS} steps={steps} warmup={warmup} "
        f"per_config={per_config_sec:.0f}s seed={args.seed} azar={chance:.4f} "
        f"brazos={[a['name'] for a in selected]}")

    grid = []
    acc_by_name = {}
    t_start = time.time()

    for a in selected:
        t0 = time.time()
        deadline = time.time() + per_config_sec
        try:
            r = train_and_eval(
                a["name"], attn_every=0, steps=steps, log=log, seed=args.seed,
                d_model=a["d_model"], n_layers=a["n_layers"], n_pairs=N_PAIRS,
                warmup=warmup, early_stop=EARLY_STOP, deadline=deadline, lr=a["lr"], **RECIPE)
            acc, params = r["final_acc"], r["params"]
            log(f"[exp012] {a['name']:<14} ({a['note']}) d={a['d_model']} L={a['n_layers']} lr={a['lr']} "
                f"acc={acc:.3f} azar={r['chance']:.4f} params={params:,} ({(time.time()-t0)/60:.1f} min)")
        except Exception as e:  # noqa: BLE001
            acc, params = None, None
            log(f"[exp012] {a['name']} ERROR {e!r}")
        grid.append({"name": a["name"], "d_model": a["d_model"], "n_layers": a["n_layers"], "lr": a["lr"],
                     "note": a["note"], "final_acc": acc, "chance": chance, "params": params})
        acc_by_name[a["name"]] = acc
        _dump(grid, chance, args, steps, warmup, summary=None)

    summary = _build_summary(acc_by_name, chance)
    _dump(grid, chance, args, steps, warmup, summary=summary)

    log("[exp012] ==== RESUMEN — recall del lineal PURO: profundidad / escala-d / optimizador ====")
    base = acc_by_name.get(BASELINE)
    log(f"azar={chance:.4f}  baseline={BASELINE}  steps={steps} (step-parity exp009/010/011)")
    log(f"{'brazo':>14} | {'recall acc':>10} | {'delta vs base':>13} | nota")
    log("-" * 78)
    for a in selected:
        v = acc_by_name.get(a["name"])
        def fmt(x):
            return f"{x:.3f}" if isinstance(x, float) else "   -   "
        delta = (v - base) if isinstance(v, float) and isinstance(base, float) else None
        dstr = (f"{delta:+.3f}" if isinstance(delta, float) else "   -   ")
        log(f"{a['name']:>14} | {fmt(v):>10} | {dstr:>13} | {a['note']}")
    log("-" * 78)
    log(f"[exp012] HEADLINE: {summary['headline']}")
    log(f"[exp012] tiempo total {(time.time()-t_start)/60:.1f} min")
    logf.close()


def _build_summary(acc_by_name, chance):
    base = acc_by_name.get(BASELINE)
    rise = 0.02
    floor_thresh = chance + 0.05

    def d(x):
        return (x - base) if isinstance(x, float) and isinstance(base, float) else None

    deltas = {k: d(v) for k, v in acc_by_name.items() if k != BASELINE}
    lifts = [k for k, dd in deltas.items() if isinstance(dd, float) and dd >= rise]
    valid = [v for v in acc_by_name.values() if isinstance(v, float)]
    all_near_floor = bool(valid) and all(v < floor_thresh for v in valid)

    if all_near_floor:
        headline = ("INCONCLUSO (PISO de optim/budget): todo cerca del azar; no separa el efecto de los "
                    "levers del piso de aprendibilidad")
    elif lifts:
        headline = ("H-CEIL-4 (parcial) APOYADA: el lineal PURO cruza el plateau con {} -> el cuello era "
                    "profundidad/escala/optimizador, no estructural del feature-map").format(" y ".join(lifts))
    else:
        headline = ("H-CEIL-4 (clausula lineal) REFUTADA: ni profundidad ni escala-d ni optimizador suben "
                    "el recall del lineal PURO sobre ~0.18 -> el plateau del estado fijo a esta escala es "
                    "robusto; solo la ATENCION lo levanta (refuerza D-CEIL-1, estructural)")

    bits = []
    for nm, v in acc_by_name.items():
        if isinstance(v, float):
            bits.append(f"{nm}={v:.3f}")
    return {
        "chance": chance, "baseline": BASELINE, "baseline_acc": base,
        "acc_by_name": acc_by_name, "deltas": deltas, "lifts": lifts,
        "rise_thresh": rise, "floor_thresh": floor_thresh, "all_near_floor": all_near_floor,
        "headline": headline, "headline_full": headline + ". " + "; ".join(bits) + ".",
    }


def _dump(grid, chance, args, steps, warmup, summary=None):
    out = {
        "experiment": "exp012_depth_scale",
        "hypothesis": ("H-CEIL-4 (clausula lineal): el plateau de recall del lineal PURO (~0.18) se "
                       "levanta con profundidad / escala-d / optimizador a steps iguales — o es "
                       "estructural (solo la atencion, ya mostrada en CYCLE 6)."),
        "smoke": args.smoke, "seed": args.seed, "n_pairs": N_PAIRS, "recipe": RECIPE,
        "steps": steps, "warmup": warmup, "early_stop": EARLY_STOP, "chance": chance, "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

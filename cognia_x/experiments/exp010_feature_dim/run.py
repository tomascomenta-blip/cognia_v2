"""
exp010 — CYCLE: el PLATEAU de recall del lineal puro, es del FEATURE MAP o un techo duro?

CONTEXTO (exp009): el mezclador puramente LINEAL ENTRENADO satura su recall asociativo en ~0.18
(azar 0.0625) a partir de d_model~24, MUY por debajo de su capacidad informacional d^2. exp009 lo
reporto como "techo de estado ENTRENADO < d^2 ideal" y lo dejo asumido como permanente.

Literatura tier-1 (Arora et al. 2024, "Based", arXiv:2402.18668; Trockman et al. 2024, "Mimetic
Initialization", arXiv:2410.11135): ese gap entre el recall ENTRENADO y la capacidad d^2 es en gran
parte un limite de OPTIMIZACION / FEATURE-MAP, no un techo duro de capacidad. El lever explicito de
Based para recorrer la frontera de recall es la DIMENSION DEL FEATURE MAP de la atencion lineal.

HIPOTESIS H-CEIL-2 (este experimento): subir la dimension del feature map de la atencion lineal SUBE
el recall ENTRENADO del lineal a d FIJO (el plateau de exp009 es feature-map-limited, NO permanente).
  PREDICCION: a d_model FIJO, un feature map mas ancho (mult>1) da MAS recall entrenado que el
    baseline ELU+1 (mult=1).
  REFUTADA SI: ensanchar el feature map NO sube el recall (queda en el plateau ~0.18, o en azar).

LEVER (implementado, no-rompiente): HybridConfig.linear_feature_mult (default 1 = comportamiento
previo EXACTO; sin proyeccion extra). Con mult>1, cada capa LINEAL proyecta q,k de d_head a
d_head*mult ANTES del feature map elu+1 (un Linear sin bias por q y por k). v y el residual quedan en
d_head: solo se ensancha el q,k que arma el estado clave-valor. Ver cognia_x/model/hybrid.py.

DISENO: d FIJO=24 (donde exp009 ya satura: lineal_puro=0.183), n_layers=4, n_heads=1, n_pairs=16,
n_keys=160, n_vals=16, n_queries=16, seed=0. Se compara SOLO lineal_puro (attn_every=0) variando
linear_feature_mult en [1 (baseline), 4] (+8 si --mult8 y hay tiempo). Misma receta de optimizacion
que exp009 (lr=1e-3, batch=64, warmup~250, early_stop=0.95) para que la UNICA variable sea el ancho
del feature map. Si mult=4 sube el recall sobre mult=1 -> el plateau era feature-map-limited.

----------------------------------------------------------------------------------------------------
Escalabilidad Obligatoria (presupuesto de este experimento):
  - Complejidad temporal:  O(n_mults * steps). Cada step es forward+backward de un modelo TINY
    (d=24, 4 capas). El feature map ensanchado lleva el coste de la feature por token de O(d) a
    O(mult*d), y el ESTADO recurrente de d^2 a (mult*d)^2 (con n_heads=1: de 24^2=576 a (4*24)^2=
    9216 con mult=4). El forward de entrenamiento es la forma PARALELA O(L^2) con L=2*n_pairs+
    n_queries=48: el feature ancho agranda solo el q@k.T en su ultima dim (mult*d_head), coste
    ~lineal en mult. 2-3 modelos tiny * <=6000 steps con early-stop.
  - Espacio:  modelos diminutos (d=24, 4 capas; mult=4 agrega ~18k params de proyeccion -> <60k
    total). Un unico results.json chico. Sin checkpoints en disco.
  - Comportamiento CPU:  torch.set_num_threads(3) (acorde a llama-server-speed-findings del lab: el
    i3 rinde mejor acotando hilos). Todo en CPU, sin CUDA. DEADLINE por config (~5-6 min c/u) para
    que el total quede ~15-20 min: experimento ACOTADO, no maraton.
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp010_feature_dim.run --smoke   # rapido
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp010_feature_dim.run           # FULL acotado
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp010_feature_dim.run --mult8    # +mult=8 si hay tiempo
"""
import argparse
import json
import os
import sys
import time

import torch

from cognia_x.train.recall_task import train_and_eval

# ASCII-safe printing: reconfigurar stdout a utf-8 si la consola lo permite (Windows cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# Misma receta de optimizacion que exp009 -> la UNICA variable es linear_feature_mult.
# n_heads=1 -> el estado lineal es la matriz (mult*d_head) x (mult*d_head) COMPLETA.
RECIPE = dict(n_heads=1, n_vals=16, n_queries=16, n_keys=160, batch=64, lr=1e-3)

D_MODEL = 24          # FIJO: el punto donde exp009 satura (lineal_puro=0.183)
N_LAYERS = 4
N_PAIRS = 16
EARLY_STOP = 0.95
BASELINE_MULT = 1


def main():
    ap = argparse.ArgumentParser(description="exp010 — el plateau de recall del lineal es feature-map-limited? (H-CEIL-2)")
    ap.add_argument("--smoke", action="store_true",
                    help="modo rapido: pocos pasos (smoke test del pipeline, no cruza recall del todo)")
    ap.add_argument("--mult8", action="store_true", help="ademas de [1,4] corre mult=8 si hay tiempo")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=None, help="override de pasos por config")
    ap.add_argument("--warmup", type=int, default=None, help="override de warmup lineal de LR")
    ap.add_argument("--per_config_sec", type=float, default=None,
                    help="override del deadline por config en segundos (default 330 ~5.5 min)")
    args = ap.parse_args()

    mults = [1, 4] + ([8] if args.mult8 else [])

    if args.smoke:
        steps = args.steps if args.steps is not None else 400
        warmup = args.warmup if args.warmup is not None else 60
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 90.0
    else:
        steps = args.steps if args.steps is not None else 6000
        warmup = args.warmup if args.warmup is not None else 250
        # ~5.5 min por config -> 2 configs ~11 min, 3 configs ~16.5 min: dentro del cap ~15-20 min.
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 330.0

    torch.set_num_threads(3)
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n")
        logf.flush()

    chance = 1.0 / RECIPE["n_vals"]
    log(f"[exp010] inicio smoke={args.smoke} d_model={D_MODEL} mults={mults} n_pairs={N_PAIRS} "
        f"steps={steps} warmup={warmup} per_config={per_config_sec:.0f}s recipe={RECIPE} azar={chance:.4f}")

    # grid: una celda por mult {d_model, linear_feature_mult, config, final_acc, chance, params, state_size}
    grid = []
    acc_by_mult = {m: None for m in mults}
    params_by_mult = {m: None for m in mults}
    dh = D_MODEL  # n_heads=1 -> d_head = d_model
    t_start = time.time()

    for m in mults:
        t0 = time.time()
        deadline = time.time() + per_config_sec   # deadline POR config -> total acotado
        state_size = (m * dh) ** 2                 # estado recurrente = (mult*d_head)^2 (n_heads=1)
        try:
            r = train_and_eval(
                f"lineal_puro_d{D_MODEL}_fm{m}", attn_every=0, steps=steps, log=log,
                seed=args.seed, d_model=D_MODEL, n_layers=N_LAYERS, n_pairs=N_PAIRS,
                warmup=warmup, early_stop=EARLY_STOP, deadline=deadline,
                linear_feature_mult=m, **RECIPE)
            acc, params = r["final_acc"], r["params"]
            log(f"[exp010] d={D_MODEL} feature_mult={m} (estado~{state_size}) lineal_puro "
                f"acc={acc:.3f} azar={r['chance']:.4f} params={params:,} ({(time.time()-t0)/60:.1f} min)")
        except Exception as e:  # noqa: BLE001
            acc, params = None, None
            log(f"[exp010] d={D_MODEL} feature_mult={m} lineal_puro ERROR {e!r}")
        grid.append({"d_model": D_MODEL, "linear_feature_mult": m, "state_size": state_size,
                     "config": "lineal_puro", "final_acc": acc, "chance": chance, "params": params})
        acc_by_mult[m] = acc
        params_by_mult[m] = params
        _dump(grid, mults, chance, args, steps, warmup, summary=None)

    summary = _build_summary(mults, acc_by_mult, chance)
    _dump(grid, mults, chance, args, steps, warmup, summary=summary)

    # ---------------- RESUMEN (ASCII-safe) ----------------
    log("[exp010] ==== RESUMEN — recall del lineal_puro vs ANCHO del feature map (d_model=24 FIJO) ====")
    log(f"azar (1/n_vals) = {chance:.4f}  |  n_heads=1 -> estado = (mult*d_head)^2  |  baseline = mult={BASELINE_MULT}")
    base = acc_by_mult.get(BASELINE_MULT)
    log(f"{'feature_mult':>12} | {'estado~(m*dh)^2':>15} | {'lineal_puro acc':>15} | {'delta vs base':>13}")
    log("-" * 66)
    for m in mults:
        v = acc_by_mult[m]
        st = (m * dh) ** 2
        def fmt(x):
            return f"{x:.3f}" if isinstance(x, float) else "   -   "
        delta = (v - base) if isinstance(v, float) and isinstance(base, float) else None
        dstr = (f"{delta:+.3f}" if isinstance(delta, float) else "   -   ")
        log(f"{m:>12} | {st:>15} | {fmt(v):>15} | {dstr:>13}")
    log("-" * 66)
    log(f"[exp010] azar={chance:.4f}  baseline(mult=1)={fmt(base) if isinstance(base,float) else base}")
    log(f"[exp010] HEADLINE: {summary['headline']}")
    log(f"[exp010] tiempo total {(time.time()-t_start)/60:.1f} min  | results.json -> "
        f"{os.path.join(RESULTS, 'results.json')}")
    logf.close()


def _build_summary(mults, acc_by_mult, chance):
    """HEADLINE honesto ASCII-safe. Distingue: (a) prediccion HELD (ensanchar SUBE el recall ->
    el plateau era feature-map-limited), (b) prediccion REFUTADA a esta escala (no sube), y el caso
    de PISO de aprendibilidad (todo cerca del azar -> es el budget/optim, no el feature map)."""
    base = acc_by_mult.get(BASELINE_MULT)
    widened = acc_by_mult.get(4)        # mult=4 es el contraste principal de la prediccion
    floor_thresh = chance + 0.05        # "cerca del azar" = a menos de 0.05 sobre el azar
    rise_thresh = 0.02                  # subida considerada real (sobre ruido de eval)

    delta = (widened - base) if isinstance(widened, float) and isinstance(base, float) else None
    raised = bool(isinstance(delta, float) and delta >= rise_thresh)

    # Lectura del mejor mult (por si mult=8 supera a mult=4).
    valid = [(m, acc_by_mult[m]) for m in mults if isinstance(acc_by_mult[m], float)]
    best_mult, best_acc = (max(valid, key=lambda p: p[1]) if valid else (None, None))

    near_floor_base = isinstance(base, float) and base < floor_thresh
    all_near_floor = bool(valid) and all(a < floor_thresh for _, a in valid)

    bits = []
    if isinstance(base, float):
        bits.append(f"baseline mult=1 recall={base:.3f}")
    if isinstance(widened, float):
        bits.append(f"mult=4 recall={widened:.3f}")
    if isinstance(delta, float):
        bits.append(f"delta(mult4-base)={delta:+.3f}")

    if all_near_floor:
        verdict = ("INCONCLUSO (PISO de optim/budget): todas las configs quedan cerca del azar "
                   f"(<{floor_thresh:.3f}); a esta escala no se separa el efecto del feature map del "
                   "piso de aprendibilidad CPU, NO es evidencia ni a favor ni en contra de H-CEIL-2")
    elif raised:
        verdict = ("PREDICCION HELD: ensanchar el feature map SUBE el recall ENTRENADO del lineal a "
                   "d fijo -> el plateau de exp009 era FEATURE-MAP-LIMITED, no un techo duro")
    elif near_floor_base:
        verdict = ("PREDICCION REFUTADA con matiz: el baseline ya estaba cerca del azar; ensanchar no "
                   "lo levanta a esta escala (mas budget/optim haria falta para distinguir)")
    else:
        verdict = ("PREDICCION REFUTADA a esta escala: ensanchar el feature map NO sube el recall "
                   "entrenado sobre el baseline (el plateau ~0.18 no se mueve solo con el ancho)")

    headline = verdict + ". " + "; ".join(bits) + "."

    return {
        "d_model": D_MODEL,
        "chance": chance,
        "baseline_mult": BASELINE_MULT,
        "acc_by_mult": {str(m): acc_by_mult[m] for m in mults},
        "baseline_acc": base,
        "widened_acc": widened,
        "delta": delta,
        "raised": raised,
        "best_mult": best_mult,
        "best_acc": best_acc,
        "all_near_floor": all_near_floor,
        "floor_thresh": floor_thresh,
        "headline": headline,
    }


def _dump(grid, mults, chance, args, steps, warmup, summary=None):
    out = {
        "experiment": "exp010_feature_dim",
        "hypothesis": ("H-CEIL-2: subir la dimension del feature map de la atencion lineal sube el "
                       "recall ENTRENADO del lineal a d fijo (el plateau de exp009 es feature-map-"
                       "limited, no un techo duro). Lever: HybridConfig.linear_feature_mult."),
        "smoke": args.smoke,
        "seed": args.seed,
        "d_model": D_MODEL,
        "n_layers": N_LAYERS,
        "n_pairs": N_PAIRS,
        "recipe": RECIPE,
        "steps": steps,
        "warmup": warmup,
        "early_stop": EARLY_STOP,
        "chance": chance,
        "mults": mults,
        "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

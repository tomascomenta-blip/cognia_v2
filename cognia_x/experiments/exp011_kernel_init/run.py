"""
exp011 — CYCLE 24: el plateau de recall del lineal, se levanta con la FORMA del kernel o con la INIT?

CONTEXTO (cadena de evidencia propia):
  - exp009: el lineal puro ENTRENADO satura su recall asociativo en ~0.18 (azar 0.0625) desde d~24,
    MUY por debajo de su capacidad informacional d^2.
  - exp010 (H-CEIL-2, REFUTADA): ENSANCHAR el feature map ELU+1 x4 -> estado 576->9216 (16x mas
    estado) NO mueve el recall (+0.000). => el plateau NO es de tamano de estado / ancho.

El fracaso de exp010 afilo la pregunta -> H-CEIL-3 (este experimento). Literatura tier-1:
  - Arora et al. 2024 ("Based", arXiv:2402.18668): lo que importa NO es el ANCHO del feature map sino
    su FORMA — el feature map de 2do orden de TAYLOR exp̂(x)=1+x+x^2/2 (phi(q).phi(k) ~ exp(q.k)) es el
    "most effective" en recall MQAR; los mapas simples tipo ELU+1 "caen por debajo".
  - Trockman et al. 2024 ("Mimetic Initialization", arXiv:2410.11135): el recall pobre puede ser de
    OPTIMIZACION/INIT, no de capacidad — una init estructurada cerca de una copia desbloquea recall.

HIPOTESIS H-CEIL-3: el plateau (~0.18) se levanta con un KERNEL mas rico (Taylor 2do orden) Y/O con
  mimetic init, a presupuesto de pasos IGUAL — NO con el mero ancho del ELU+1.
  PREDICCION: a d FIJO=24 y steps IGUALES (6000, step-parity con exp009/exp010), alguno de
    {taylor, mimetic} sube el recall por encima de ~0.18.
  REFUTADA SI: ni el kernel Taylor ni la mimetic init mueven el recall sobre el baseline.

DISENO — 4 brazos, MISMA receta de optim que exp009/exp010 (la unica variable es kernel/init):
  d_model=24 FIJO, n_layers=4, n_heads=1, n_pairs=16, n_keys=160, n_vals=16, n_queries=16, seed=0,
  steps=6000, warmup=250, early_stop=0.95, lr=1e-3, batch=64. attn_every=0 (LINEAL PURO en todos).
    1) elu_base    : ELU+1, mult=1               -> BASELINE (reproduce el plateau de exp010, ~0.181).
    2) taylor      : feature map Taylor 2do orden -> FORMA del kernel (feature dim = 1+dh+dh(dh+1)/2=325).
    3) elu_matched : ELU+1, mult=14 (dim 336~325) -> CONTROL DE TAMANO: misma dim de feature que taylor
                     pero forma ELU. Aisla FORMA de TAMANO (el confound de exp010 llevado a la dim de Taylor).
    4) elu_mimetic : ELU+1, mult=1, mimetic_init  -> LEVER de INIT (W_k:=W_q, W_o:=I; cero coste inferencia).

VEREDICTO (honesto, por clausula):
  - KERNEL: taylor sube sobre baseline Y sobre elu_matched -> la FORMA es el lever (no el tamano).
            taylor sube pero elu_matched tambien -> a esta dim es TAMANO, no forma (tension con exp010).
            taylor ~ baseline -> el kernel Taylor NO levanta el plateau a esta escala.
  - INIT:   elu_mimetic sube sobre baseline -> la init desbloquea recall. Si no, no a esta escala.
  - H-CEIL-3 se APOYA si ALGUNO de {taylor, mimetic} levanta el plateau; se REFUTA si NINGUNO.

----------------------------------------------------------------------------------------------------
Escalabilidad Obligatoria (presupuesto de este experimento):
  - Tiempo:  O(n_brazos * steps). 4 modelos TINY (d=24, 4 capas) * <=6000 steps con early-stop y
    deadline POR brazo (~7 min c/u -> total acotado <=~28 min). El feature de Taylor/elu_matched (dim
    ~325-336) encarece el q@k.T y la feature por token vs el baseline (dim 24), pero L=48 lo mantiene
    trivial. torch.set_num_threads(3) (i3, mejor acotando hilos — llama-server-speed-findings).
  - Espacio:  modelos diminutos; elu_matched anade ~16k params de proyeccion (Linear 24->336 x2).
    Un unico results.json. Sin checkpoints en disco.
  - CPU / multi-dispositivo:  todo CPU, sin CUDA. Reproducible (seed=0). Portable.
----------------------------------------------------------------------------------------------------

Uso:
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp011_kernel_init.run --smoke   # rapido (pipeline)
  venv312\\Scripts\\python.exe -m cognia_x.experiments.exp011_kernel_init.run           # FULL acotado
"""
import argparse
import json
import os
import sys
import time

import torch

from cognia_x.model.hybrid import taylor_feature_dim
from cognia_x.train.recall_task import train_and_eval

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# Misma receta de optim que exp009/exp010 -> la UNICA variable es el kernel/init de cada brazo.
RECIPE = dict(n_heads=1, n_vals=16, n_queries=16, n_keys=160, batch=64, lr=1e-3)
D_MODEL = 24          # FIJO: el punto donde exp009 satura y exp010 mostro plateau ~0.181
N_LAYERS = 4
N_PAIRS = 16
EARLY_STOP = 0.95
BASELINE = "elu_base"

# mult para igualar la dim de feature de Taylor (1+dh+dh(dh+1)/2) con ELU+1 (dh*mult): aisla forma/tamano.
_DH = D_MODEL  # n_heads=1 -> d_head = d_model
_TAYLOR_DIM = taylor_feature_dim(_DH)                 # 325 a dh=24
_MATCHED_MULT = max(2, round(_TAYLOR_DIM / _DH))      # 14 a dh=24 (24*14=336 ~ 325)


def arms():
    """4 brazos: cada uno fija (kernel, init) dejando TODO lo demas igual. feature_dim es informativo."""
    return [
        dict(name="elu_base", feature_map="elu", mult=1, mimetic=False,
             feature_dim=_DH, note="BASELINE ELU+1 (plateau de exp010)"),
        dict(name="taylor", feature_map="taylor", mult=1, mimetic=False,
             feature_dim=_TAYLOR_DIM, note="FORMA: kernel Taylor 2do orden (Based)"),
        dict(name="elu_matched", feature_map="elu", mult=_MATCHED_MULT, mimetic=False,
             feature_dim=_DH * _MATCHED_MULT, note="CONTROL DE TAMANO: ELU+1 a la dim de Taylor"),
        dict(name="elu_mimetic", feature_map="elu", mult=1, mimetic=True,
             feature_dim=_DH, note="INIT: mimetic init (Trockman)"),
    ]


def main():
    ap = argparse.ArgumentParser(description="exp011 — el plateau de recall: forma del kernel o init? (H-CEIL-3)")
    ap.add_argument("--smoke", action="store_true", help="modo rapido: pocos pasos (smoke del pipeline)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=None, help="override de pasos por brazo")
    ap.add_argument("--warmup", type=int, default=None)
    ap.add_argument("--per_config_sec", type=float, default=None,
                    help="deadline por brazo en seg (default 420 ~7 min)")
    ap.add_argument("--only", type=str, default=None,
                    help="correr solo brazos cuyo nombre este en esta lista separada por comas")
    args = ap.parse_args()

    if args.smoke:
        steps = args.steps if args.steps is not None else 400
        warmup = args.warmup if args.warmup is not None else 60
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 90.0
    else:
        steps = args.steps if args.steps is not None else 6000
        warmup = args.warmup if args.warmup is not None else 250
        per_config_sec = args.per_config_sec if args.per_config_sec is not None else 420.0

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
    log(f"[exp011] inicio smoke={args.smoke} d_model={D_MODEL} n_pairs={N_PAIRS} steps={steps} "
        f"warmup={warmup} per_config={per_config_sec:.0f}s seed={args.seed} azar={chance:.4f} "
        f"taylor_dim={_TAYLOR_DIM} matched_mult={_MATCHED_MULT} brazos={[a['name'] for a in selected]}")

    grid = []
    acc_by_name = {}
    t_start = time.time()

    for a in selected:
        t0 = time.time()
        deadline = time.time() + per_config_sec
        try:
            r = train_and_eval(
                a["name"], attn_every=0, steps=steps, log=log, seed=args.seed,
                d_model=D_MODEL, n_layers=N_LAYERS, n_pairs=N_PAIRS,
                warmup=warmup, early_stop=EARLY_STOP, deadline=deadline,
                linear_feature_mult=a["mult"], linear_feature_map=a["feature_map"],
                mimetic_init=a["mimetic"], **RECIPE)
            acc, params = r["final_acc"], r["params"]
            log(f"[exp011] {a['name']:<12} ({a['note']}) feature_dim~{a['feature_dim']} "
                f"acc={acc:.3f} azar={r['chance']:.4f} params={params:,} ({(time.time()-t0)/60:.1f} min)")
        except Exception as e:  # noqa: BLE001
            acc, params = None, None
            log(f"[exp011] {a['name']} ERROR {e!r}")
        grid.append({"name": a["name"], "feature_map": a["feature_map"], "mult": a["mult"],
                     "mimetic": a["mimetic"], "feature_dim": a["feature_dim"], "note": a["note"],
                     "final_acc": acc, "chance": chance, "params": params})
        acc_by_name[a["name"]] = acc
        _dump(grid, chance, args, steps, warmup, summary=None)

    summary = _build_summary(acc_by_name, chance)
    _dump(grid, chance, args, steps, warmup, summary=summary)

    # ---------------- RESUMEN (ASCII-safe) ----------------
    log("[exp011] ==== RESUMEN — recall del lineal_puro: FORMA del kernel vs TAMANO vs INIT (d=24 FIJO) ====")
    log(f"azar={chance:.4f}  baseline={BASELINE}  steps={steps} (step-parity exp009/exp010)")
    base = acc_by_name.get(BASELINE)
    log(f"{'brazo':>12} | {'feature_dim':>11} | {'recall acc':>10} | {'delta vs base':>13} | nota")
    log("-" * 92)
    for a in selected:
        v = acc_by_name.get(a["name"])
        def fmt(x):
            return f"{x:.3f}" if isinstance(x, float) else "   -   "
        delta = (v - base) if isinstance(v, float) and isinstance(base, float) else None
        dstr = (f"{delta:+.3f}" if isinstance(delta, float) else "   -   ")
        log(f"{a['name']:>12} | {a['feature_dim']:>11} | {fmt(v):>10} | {dstr:>13} | {a['note']}")
    log("-" * 92)
    log(f"[exp011] HEADLINE: {summary['headline']}")
    log(f"[exp011] tiempo total {(time.time()-t_start)/60:.1f} min  | results.json -> "
        f"{os.path.join(RESULTS, 'results.json')}")
    logf.close()


def _build_summary(acc_by_name, chance):
    """Veredicto honesto por clausula (kernel / init) + overall H-CEIL-3. ASCII-safe."""
    base = acc_by_name.get(BASELINE)
    taylor = acc_by_name.get("taylor")
    matched = acc_by_name.get("elu_matched")
    mimetic = acc_by_name.get("elu_mimetic")
    floor_thresh = chance + 0.05      # "cerca del azar"
    rise = 0.02                       # subida real sobre ruido de eval (~0.01)

    def d(x):
        return (x - base) if isinstance(x, float) and isinstance(base, float) else None

    dt, dmatch, dmim = d(taylor), d(matched), d(mimetic)
    valid = [v for v in (base, taylor, matched, mimetic) if isinstance(v, float)]
    all_near_floor = bool(valid) and all(v < floor_thresh for v in valid)

    # KERNEL clause
    if isinstance(dt, float) and isinstance(dmatch, float):
        if dt >= rise and (taylor - matched) >= rise:
            kernel = "KERNEL APOYADA: taylor sube sobre baseline Y sobre elu_matched (misma dim) -> la FORMA del kernel es el lever, no el tamano"
        elif dt >= rise and dmatch >= rise:
            kernel = "KERNEL MIXTA: taylor sube PERO elu_matched (misma dim) tambien -> a esta dim es TAMANO, no forma (tension con exp010 a dim menor)"
        elif dt >= rise:
            kernel = "KERNEL APOYADA (parcial): taylor sube sobre baseline; elu_matched no separa"
        else:
            kernel = "KERNEL REFUTADA: el kernel Taylor NO sube el recall sobre el baseline a esta escala"
    else:
        kernel = "KERNEL INCONCLUSO: falta el dato de taylor o elu_matched"

    # INIT clause
    if isinstance(dmim, float):
        init = ("INIT APOYADA: la mimetic init sube el recall sobre el baseline"
                if dmim >= rise else
                "INIT REFUTADA: la mimetic init NO sube el recall sobre el baseline a esta escala")
    else:
        init = "INIT INCONCLUSO: falta el dato de elu_mimetic"

    lifts = [name for name, dd in (("taylor", dt), ("mimetic", dmim)) if isinstance(dd, float) and dd >= rise]
    if all_near_floor:
        overall = ("H-CEIL-3 INCONCLUSO (PISO de optim/budget): todo cerca del azar "
                   f"(<{floor_thresh:.3f}); a esta escala no se separa el efecto kernel/init del piso de aprendibilidad")
    elif lifts:
        overall = f"H-CEIL-3 APOYADA: {' y '.join(lifts)} levanta(n) el plateau a steps iguales (NO era solo el ancho del ELU+1)"
    else:
        overall = "H-CEIL-3 REFUTADA a esta escala: ni el kernel Taylor ni la mimetic init levantan el plateau (~0.18) a steps iguales"

    bits = []
    for nm, v in (("base", base), ("taylor", taylor), ("elu_matched", matched), ("mimetic", mimetic)):
        if isinstance(v, float):
            bits.append(f"{nm}={v:.3f}")
    headline = overall + ". " + " | ".join((kernel, init)) + ". " + "; ".join(bits) + "."

    return {
        "chance": chance,
        "baseline": BASELINE,
        "baseline_acc": base,
        "acc_by_name": acc_by_name,
        "delta_taylor": dt,
        "delta_elu_matched": dmatch,
        "delta_mimetic": dmim,
        "taylor_vs_matched": (taylor - matched) if isinstance(taylor, float) and isinstance(matched, float) else None,
        "rise_thresh": rise,
        "floor_thresh": floor_thresh,
        "all_near_floor": all_near_floor,
        "lifts": lifts,
        "kernel_verdict": kernel,
        "init_verdict": init,
        "headline": overall,
        "headline_full": headline,
    }


def _dump(grid, chance, args, steps, warmup, summary=None):
    out = {
        "experiment": "exp011_kernel_init",
        "hypothesis": ("H-CEIL-3: el plateau de recall del lineal (~0.18) se levanta con la FORMA del "
                       "kernel (Taylor 2do orden, Based) Y/O mimetic init (Trockman 2024) a steps "
                       "IGUALES — NO con el mero ancho del ELU+1 (refutado en exp010)."),
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
        "taylor_feature_dim": _TAYLOR_DIM,
        "matched_mult": _MATCHED_MULT,
        "grid": grid,
    }
    if summary is not None:
        out["summary"] = summary
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

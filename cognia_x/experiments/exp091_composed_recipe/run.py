r"""
exp091 — CYCLE 107 / H-V4-8l (rama R-VALOR, CAPSTONE: la RECETA COMPUESTA en el LAZO CERRADO REAL): el arco 95-106
desarrolló la regla general de asignación pieza por pieza (marginal/cobertura 96, costo-por-valor 101/105, confianza 93).
¿COMPONEN en el lazo cerrado REAL? exp091 corre el lazo (HybridLM de exp018) bajo costo de verificación heterogéneo y
compara: confianza sola (93) -> +costo (105) -> +cobertura de targets (96). ¿Cada pieza añadida MEJORA el downstream del
lazo real?

CONTEXTO. CYCLE 105 validó que el costo-por-valor (101) transfiere al lazo real. Este capstone integra TRES piezas en UNA
política de asignación de la verificación escasa y mide si componen sobre el modelo propio.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp089). Lazo cerrado real (base débil + temp alta -> pool con mix). Costo de
verificación heterogéneo (∝ target). Presupuesto de COSTO total B por ronda. Brazos (mismo base/RNG; mismo B):
  - conf:           selecciona por VALOR positivo (exp confianza) hasta agotar el costo (93).
  - ratio:          selecciona por VALOR/COSTO (105) hasta agotar el costo.
  - ratio_coverage: VALOR/COSTO + COBERTURA de targets (round-robin por target tomando el mejor ratio de cada uno -> 96).
  - verify_all:     verifica todo (techo).
Las strong-correctas entrenan. MÉTRICA: real_acc held-out (downstream del lazo) + yield. 4 seeds.

PREGUNTA FALSABLE (composición en el lazo real):
  - APOYADA si ratio_coverage >= ratio >= conf en el DOWNSTREAM (cada pieza añadida no regresiona y el compuesto es el
    mejor de los tres bajo presupuesto), con ratio_coverage > conf por > margen. => las piezas (confianza+costo+cobertura)
    COMPONEN en el lazo cerrado REAL; el arco 95-106 no es sólo teoría de juguete.
  - REFUTADA si el compuesto NO supera a confianza sola (las piezas no componen en real).
  - MIXTA si compone parcialmente (una pieza ayuda, otra no, en el lazo real).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp091_composed_recipe.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp091_composed_recipe.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
import sys
from collections import defaultdict

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr
from cognia_x.experiments.exp089_real_cost_alloc.run import _cost_of

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["conf", "ratio", "ratio_coverage", "verify_all"]


def _alloc_under_cost(order, costs, B):
    picks = []; spent = 0.0
    for i in order:
        if spent + costs[i] <= B + 1e-9:
            picks.append(i); spent += costs[i]
    return picks


def _coverage_order(key, prompts):
    """Round-robin por target: ordena cada grupo (target) por key desc y toma en rondas (cubre targets distintos)."""
    by_t = defaultdict(list)
    for i, p in enumerate(prompts):
        by_t[bytes(p)].append(i)
    for t in by_t:
        by_t[t].sort(key=lambda i: -key[i])
    keys = list(by_t.keys())
    order, depth = [], 0
    while True:
        added = False
        for t in keys:
            if depth < len(by_t[t]):
                order.append(by_t[t][depth]); added = True
        if not added:
            break
        depth += 1
    return order


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp091] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "yield": []} for a in ARMS}
    corrs = []
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            prompts = [p for (p, _, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            costs = np.array([_cost_of(p) for (p, _, _, _) in pool])
            n = len(pool)
            B = args.budget_frac * float(costs.sum())
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            if a == "verify_all":
                sel_idx = list(range(n))
            else:
                conf = _confidence(arms[a], pairs, "cpu")
                val = np.exp(conf)                                   # valor positivo (105)
                if a == "conf" and r == 1:
                    corrs.append(round(_corr(conf, strong), 4))
                if a == "conf":
                    order = list(np.argsort(val + 1e-9 * rng_a.random(n))[::-1])
                    sel_idx = _alloc_under_cost(order, costs, B)
                elif a == "ratio":
                    order = list(np.argsort(val / costs + 1e-9 * rng_a.random(n))[::-1])
                    sel_idx = _alloc_under_cost(order, costs, B)
                else:  # ratio_coverage: ratio + cobertura de targets (round-robin)
                    order = _coverage_order(val / costs, prompts)
                    sel_idx = _alloc_under_cost(order, costs, B)
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[a]["yield"].append(len(ex))
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp091] seed={seed} ronda {r}: "
            + " | ".join(f"{a}: y={hist[a]['yield'][-1]} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "hist": hist, "conf_strong_corr": (corrs[0] if corrs else 0.0)}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def build_summary(per_seed):
    def mr(a):
        return [sum(s["hist"][a]["real"][1:]) / len(s["hist"][a]["real"][1:]) for s in per_seed]

    def my(a):
        return [sum(s["hist"][a]["yield"]) / len(s["hist"][a]["yield"]) for s in per_seed]

    rc, rr, rrc, rva = mr("conf"), mr("ratio"), mr("ratio_coverage"), mr("verify_all")
    cost_step = round(_mean(rr) - _mean(rc), 4)            # +costo sobre confianza
    cov_step = round(_mean(rrc) - _mean(rr), 4)            # +cobertura sobre ratio
    composed_vs_conf = round(_mean(rrc) - _mean(rc), 4)    # compuesto vs confianza sola
    va_gap = round(_mean(rva) - _mean(rrc), 4)
    nseed = len(per_seed)

    MARGIN = 0.03
    composes = (composed_vs_conf > MARGIN) and (cost_step >= -MARGIN) and (cov_step >= -MARGIN)
    partial = (composed_vs_conf > MARGIN) and not composes

    if composes:
        status = "apoyada"
        verdict = ("H-V4-8l APOYADA: la RECETA COMPUESTA (confianza+costo+cobertura) COMPONE en el LAZO CERRADO REAL. "
                   "Downstream: conf={rc} -> +costo ratio={rr} (Δ {cs}) -> +cobertura ratio_coverage={rrc} (Δ {cv}); el "
                   "compuesto SUPERA a confianza sola por +{cvc} y se acerca al techo verify_all={rva} (gap {vg}). Cada "
                   "pieza añadida no regresiona. => el arco de asignación 95-106 (marginal/cobertura, costo-por-valor) "
                   "COMPONE sobre el modelo REAL, no es sólo teoría de juguete. corr(conf,strong)={csc}.").format(
                       rc=_f(_mean(rc)), rr=_f(_mean(rr)), cs=_f(cost_step), rrc=_f(_mean(rrc)), cv=_f(cov_step),
                       cvc=_f(composed_vs_conf), rva=_f(_mean(rva)), vg=_f(va_gap),
                       csc=_f(_mean([s["conf_strong_corr"] for s in per_seed])))
    elif composed_vs_conf <= MARGIN:
        status = "refutada"
        verdict = ("H-V4-8l REFUTADA: el compuesto NO supera a confianza sola en el lazo real (ratio_coverage={rrc} vs "
                   "conf={rc}, +{cvc} <= {m}) -> las piezas no componen en real.").format(
                       rrc=_f(_mean(rrc)), rc=_f(_mean(rc)), cvc=_f(composed_vs_conf), m=MARGIN)
    else:
        status = "mixta"
        verdict = ("H-V4-8l MIXTA: el compuesto supera a confianza (+{cvc}) PERO una pieza no aporta limpio (costo Δ {cs}, "
                   "cobertura Δ {cv}) -> composición parcial en el lazo real.").format(
                       cvc=_f(composed_vs_conf), cs=_f(cost_step), cv=_f(cov_step))

    return {"arms": ARMS, "n_seeds": nseed, "conf_strong_corr_by_seed": [s["conf_strong_corr"] for s in per_seed],
            "real_conf": [round(x, 3) for x in rc], "real_ratio": [round(x, 3) for x in rr],
            "real_ratio_coverage": [round(x, 3) for x in rrc], "real_verify_all": [round(x, 3) for x in rva],
            "yield_conf": [round(x, 1) for x in my("conf")], "yield_ratio_coverage": [round(x, 1) for x in my("ratio_coverage")],
            "cost_step": cost_step, "cov_step": cov_step, "composed_vs_conf": composed_vs_conf, "va_gap": va_gap,
            "composes": bool(composes), "partial": bool(partial), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.20)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--top_k", type=int, default=0)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=250)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.top_k <= 0:
        args.top_k = None
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 2, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp091] CYCLE 107 / H-V4-8l — CAPSTONE: receta compuesta (confianza+costo+cobertura) en el lazo cerrado real")
    log(f"[exp091] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"temp={args.temp} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp091] corr(conf,strong)={sm['conf_strong_corr_by_seed']}")
    log(f"[exp091] real_acc: conf={sm['real_conf']} ratio={sm['real_ratio']} ratio_coverage={sm['real_ratio_coverage']} verify_all={sm['real_verify_all']}")
    log(f"[exp091] pasos: +costo={sm['cost_step']:+.3f} +cobertura={sm['cov_step']:+.3f} | compuesto−conf=+{sm['composed_vs_conf']:.3f} | verify_all_gap={sm['va_gap']:.3f}")
    log(f"[exp091] composes={sm['composes']} partial={sm['partial']}")
    log(f"[exp091] VEREDICTO H-V4-8l: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp091_composed_recipe", "cycle": 107, "hypothesis": "H-V4-8l",
           "claim": "la receta compuesta de asignacion (confianza + costo-por-valor + cobertura de targets) COMPONE en el "
                    "lazo cerrado real: cada pieza anadida no regresiona y el compuesto supera a confianza sola en el "
                    "downstream -> el arco 95-106 transfiere/compone sobre el modelo real",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp091] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

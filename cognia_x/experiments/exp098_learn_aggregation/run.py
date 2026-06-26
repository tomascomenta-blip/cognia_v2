r"""
exp098 — CYCLE 114 / H-V4-8s (rama R-VALOR, cierra el pointer de CYCLE 113: APRENDER la agregación vence al HEDGE): 113
mostró que bajo agregación INCIERTA no hay supuesto universalmente seguro (depende de k/T). Pero en vez de ELEGIR un
supuesto (hedge fijo), el agente puede APRENDER cuál agregación es la verdadera del FEEDBACK (cf. CYCLE 102, que aprendió
la meta-política). ¿Un bandit sobre {assume_additive, assume_submodular} con reward = valor-verdadero de su selección logra
no-regret y vence a cualquier hedge fijo?

CONTEXTO. Converso de 113 (igual que 102 fue converso de 92): cuando ningún supuesto domina, descubrirlo del feedback es
mejor que comprometerse a uno. Cierra el sub-hilo de robustez de agregación.

DISEÑO (numpy). T_rounds; la agregación VERDADERA (additive o submodular) es FIJA pero DESCONOCIDA. Cada ronda: ítems
frescos; el agente elige una POLÍTICA (assume_additive=top-value / assume_submodular=cobertura-greedy), selecciona k, y
OBSERVA el valor-verdadero de su selección (normalizado por el oracle de esa verdad) = reward. Estrategias:
  - learn:      bandit ε-greedy sobre las 2 políticas con el reward observado.
  - always_add / always_sub: políticas fijas.
  - hedge:      regla fija de 113 por k/T (k<T -> submodular, si no additive).
  - best_fixed: la mejor política fija para esa verdad (oracle de política) = referencia.
Se promedia sobre AMBAS verdades. MÉTRICA: reward acumulado medio / best_fixed.

PREGUNTA FALSABLE:
  - APOYADA si learn ≈ best_fixed (no-regret: gap pequeño) Y learn > hedge (promediado sobre ambas verdades, porque el
    hedge fijo acierta en una verdad y falla en la otra, mientras learn se adapta a la verdad real). => bajo agregación
    incierta, APRENDER la agregación del feedback vence a comprometerse a un supuesto (hedge). Cierra 113 (converso, como
    102 cerró 92).
  - REFUTADA si learn no supera al hedge (aprender no aporta) o no alcanza a best_fixed (no-regret falla).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp098_learn_aggregation.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp098_learn_aggregation.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp097_aggregation_robust.run import (
    _pick_top_value, _pick_marginal_coverage, _additive_value, _submodular_value,
    _oracle_additive, _oracle_submodular,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
STRATS = ["learn", "always_add", "always_sub", "hedge", "best_fixed"]
TRUTHS = ["additive", "submodular"]
POLICIES = ["assume_additive", "assume_submodular"]


def _reward(policy, v, c, k, T, truth):
    sel = _pick_top_value(v, c, k, T) if policy == "assume_additive" else _pick_marginal_coverage(v, c, k, T)
    if truth == "additive":
        oracle = _additive_value(_oracle_additive(v, c, k, T), v)
        return _additive_value(sel, v) / oracle if oracle > 1e-9 else 0.0
    oracle = _submodular_value(_oracle_submodular(v, c, k, T), v, c, T)
    return _submodular_value(sel, v, c, T) / oracle if oracle > 1e-9 else 0.0


def _best_fixed_policy(truth):
    return "assume_additive" if truth == "additive" else "assume_submodular"


def run_truth(truth, n, k, T, rounds, eps, n_seeds):
    acc = {s: [] for s in STRATS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 907 + (0 if truth == "additive" else 53) + 3)
        q = {p: 0.0 for p in POLICIES}            # estimación de reward por política (learn)
        cnt = {p: 0 for p in POLICIES}
        cum = {s: 0.0 for s in STRATS}
        for r in range(rounds):
            v = rng.random(n)
            probs = rng.dirichlet(np.ones(T) * 0.6)
            c = rng.choice(T, size=n, p=probs)
            # learn: ε-greedy
            if rng.random() < eps or min(cnt.values()) == 0:
                pol = POLICIES[int(rng.integers(0, 2))]
            else:
                pol = max(POLICIES, key=lambda p: q[p])
            rw = _reward(pol, v, c, k, T, truth)
            cnt[pol] += 1
            q[pol] += (rw - q[pol]) / cnt[pol]
            cum["learn"] += rw
            cum["always_add"] += _reward("assume_additive", v, c, k, T, truth)
            cum["always_sub"] += _reward("assume_submodular", v, c, k, T, truth)
            hedge_pol = "assume_submodular" if k < T else "assume_additive"
            cum["hedge"] += _reward(hedge_pol, v, c, k, T, truth)
            cum["best_fixed"] += _reward(_best_fixed_policy(truth), v, c, k, T, truth)
        for s in STRATS:
            acc[s].append(cum[s] / rounds)
    return {s: float(np.mean(acc[s])) for s in STRATS}


def run(n, k, T, rounds, eps, n_seeds):
    per_truth = {t: run_truth(t, n, k, T, rounds, eps, n_seeds) for t in TRUTHS}
    avg = {s: round(float(np.mean([per_truth[t][s] for t in TRUTHS])), 4) for s in STRATS}
    per_truth = {t: {s: round(per_truth[t][s], 4) for s in STRATS} for t in TRUTHS}
    return {"per_truth": per_truth, "avg": avg, "k": k, "T": T}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    avg = grid["avg"]
    learn = avg["learn"]; hedge = avg["hedge"]; best = avg["best_fixed"]
    no_regret_gap = round(best - learn, 4)        # pequeño si learn ≈ best_fixed
    learn_vs_hedge = round(learn - hedge, 4)      # >0 si aprender vence al hedge

    NR_TOL = 0.05
    HEDGE_MARGIN = 0.03
    no_regret = no_regret_gap <= NR_TOL
    beats_hedge = learn_vs_hedge > HEDGE_MARGIN

    if no_regret and beats_hedge:
        status = "apoyada"
        verdict = ("H-V4-8s APOYADA: bajo agregación INCIERTA, APRENDER la agregación del feedback vence a comprometerse a "
                   "un supuesto (hedge). Promediado sobre ambas verdades: learn={l} ≈ best_fixed={b} (no-regret, gap {nr}) "
                   "y > hedge={h} (+{lvh}). El hedge fijo acierta en una verdad y falla en la otra (always_add={aa}, "
                   "always_sub={as_}); el learner se ADAPTA a la verdad real con un bandit ε-greedy. => cierra CYCLE 113 "
                   "(converso, como 102 cerró 92): cuando ningún supuesto de agregación domina, DESCUBRIRLO del feedback "
                   "es mejor que hedgear.").format(l=_f(learn), b=_f(best), nr=_f(no_regret_gap), h=_f(hedge),
                                                   lvh=_f(learn_vs_hedge), aa=_f(avg["always_add"]), as_=_f(avg["always_sub"]))
    elif not beats_hedge:
        status = "refutada"
        verdict = ("H-V4-8s REFUTADA: aprender NO supera al hedge (learn={l} vs hedge={h}, +{lvh} <= {m}) -> comprometerse "
                   "a un supuesto basta.").format(l=_f(learn), h=_f(hedge), lvh=_f(learn_vs_hedge), m=HEDGE_MARGIN)
    else:
        status = "mixta"
        verdict = ("H-V4-8s MIXTA: learn vence al hedge (+{lvh}) pero no-regret falla (gap a best_fixed {nr} > {tol}) -> el "
                   "learner aporta pero no converge al óptimo fijo.").format(lvh=_f(learn_vs_hedge), nr=_f(no_regret_gap), tol=NR_TOL)

    return {"grid": grid, "learn": learn, "hedge": hedge, "best_fixed": best, "no_regret_gap": no_regret_gap,
            "learn_vs_hedge": learn_vs_hedge, "no_regret": bool(no_regret), "beats_hedge": bool(beats_hedge),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--k", type=int, default=6)        # k<T para que el hedge (regla k/T) elija submodular
    ap.add_argument("--T", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--eps", type=float, default=0.1)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.rounds = 12, 30

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp098] CYCLE 114 / H-V4-8s — APRENDER la agregación del feedback vs HEDGE fijo (cierra 113)")
    log(f"[exp098] n={args.n} k={args.k} T={args.T} rounds={args.rounds} eps={args.eps} seeds={args.seeds} truths={TRUTHS}")

    grid = run(args.n, args.k, args.T, args.rounds, args.eps, args.seeds)
    sm = build_summary(grid)

    for t in TRUTHS:
        pt = grid["per_truth"][t]
        log(f"[exp098] verdad={t:>10}: learn={pt['learn']:.3f} always_add={pt['always_add']:.3f} always_sub={pt['always_sub']:.3f} "
            f"hedge={pt['hedge']:.3f} best_fixed={pt['best_fixed']:.3f}")
    log(f"[exp098] PROMEDIO: learn={sm['learn']:.3f} hedge={sm['hedge']:.3f} best_fixed={sm['best_fixed']:.3f} | "
        f"no_regret_gap={sm['no_regret_gap']:.3f} learn−hedge=+{sm['learn_vs_hedge']:.3f}")
    log(f"[exp098] no_regret={sm['no_regret']} beats_hedge={sm['beats_hedge']}")
    log(f"[exp098] VEREDICTO H-V4-8s: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp098_learn_aggregation", "cycle": 114, "hypothesis": "H-V4-8s",
           "claim": "bajo agregacion incierta, APRENDER la agregacion verdadera del feedback (bandit) logra no-regret y "
                    "vence a comprometerse a un supuesto (hedge fijo), promediado sobre ambas verdades -> cierra 113 "
                    "(converso, como 102 cerro 92)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp098] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

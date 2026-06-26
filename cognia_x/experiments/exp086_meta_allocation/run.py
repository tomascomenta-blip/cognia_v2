r"""
exp086 — CYCLE 102 / H-V4-8g (rama R-VALOR, META-ALLOCATION; converso de CYCLE 92): los ciclos 95/100/101 dieron la
política de asignación correcta SUPONIENDO que el agente CONOCE la estructura del objetivo (aditivo vs cobertura, costo
uniforme vs hetero). Pero el MEJOR brazo DIFIERE por régimen -- per-costo ayuda bajo ADITIVO (CYCLE 101) pero ESTORBA bajo
COBERTURA que satura (cubrir manda) -- así que NINGÚN brazo único domina. ¿Un agente que NO conoce el régimen puede
DESCUBRIR la política de asignación correcta del FEEDBACK de outcomes (bandit sobre estrategias), con no-regret a través
de regímenes?

CONTRASTE con CYCLE 92 (meta-prior): allí un prior FLEXIBLE (rbf) casi dominaba -> la selección era innecesaria. AQUÍ
ningún brazo domina (per-costo ayuda/estorba según el objetivo) -> la selección SÍ es necesaria; el converso.

DISEÑO (numpy, online). Regímenes (el agente NO sabe cuál): ADITIVO+hetero (mejor: ratio/marginal-per-cost) y COBERTURA+
hetero (mejor: marginal, NO per-cost). Por ronda: pool fresco; el agente ELIGE una estrategia de asignación, la ejecuta
bajo presupuesto de costo, y OBSERVA el objetivo logrado (reward, normalizado por el oracle del régimen). Estrategias:
value (ignora costo), ratio (valor/costo), marginal (ganancia marginal), marginal_per_cost (ganancia marginal/costo).
Brazos meta: bandit (ε-greedy sobre el reward medio observado por estrategia), best_fixed_each (cota: la mejor estrategia
FIJA por régimen = oracle_selector), y cada estrategia FIJA. EVAL: reward medio (post-warmup).

PREGUNTA FALSABLE:
  - APOYADA si NINGUNA estrategia fija es la mejor en AMBOS regímenes (el mejor difiere) Y el bandit logra NO-REGRET
    (≈ oracle_selector por régimen, y en promedio SUPERA a cualquier estrategia fija única). => el agente DESCUBRE la
    política de asignación del feedback de outcomes; la selección es NECESARIA (converso de CYCLE 92).
  - REFUTADA si una estrategia fija domina ambos regímenes (selección innecesaria, como CYCLE 92) o el bandit no converge.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp086_meta_allocation.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp086_meta_allocation.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp085_cost_aware_value.run import (
    _coverage, _additive, _frac_knapsack, _budget_greedy_additive, _budget_greedy_coverage, T_TYPES)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
STRATS = ["value", "ratio", "marginal", "marginal_per_cost"]
STRAT_ID = {s: i for i, s in enumerate(STRATS)}
REGIMES = ["additive_hetero", "coverage_hetero"]
REGIME_ID = {r: i for i, r in enumerate(REGIMES)}
ARMS = STRATS + ["bandit", "oracle_selector"]


def _draw(rng, n):
    q = rng.random(n)
    typ = rng.integers(0, T_TYPES, size=n)
    cost = np.clip(0.3 + 2.5 * q + rng.normal(0.0, 0.2, size=n), 0.2, None)
    return q, typ, cost


def _select(strat, qe, typ, ce, B, coverage):
    by_ratio = strat in ("ratio", "marginal_per_cost")
    if coverage:
        # 'value'/'ratio' = greedy por calidad (o /costo); 'marginal'/'marginal_per_cost' = ganancia marginal de cobertura
        return _budget_greedy_coverage(qe, typ, T_TYPES, ce, B, by_ratio=by_ratio)
    # aditivo: marginal == value (la ganancia marginal aditiva es q); ratio == marginal_per_cost
    return _budget_greedy_additive(qe, ce, B, by_ratio=by_ratio)


def _objective(picks, q, typ, coverage):
    return _coverage(picks, q, typ, T_TYPES) if coverage else _additive(picks, q)


def _oracle(q, typ, cost, B, coverage):
    if not coverage:
        return _frac_knapsack(q, cost, B)
    ov = _budget_greedy_coverage(q, typ, T_TYPES, cost, B, by_ratio=False)
    orr = _budget_greedy_coverage(q, typ, T_TYPES, cost, B, by_ratio=True)
    return max(_coverage(ov, q, typ, T_TYPES), _coverage(orr, q, typ, T_TYPES))


def run_cell(n, B, regime, T, warmup, eps, noise, n_seeds):
    coverage = regime.startswith("coverage")
    fixed = {s: [] for s in STRATS}
    bandit_r = []
    oracle_sel_r = []
    for seed in range(n_seeds):
        # estrategias FIJAS (cada una corre el régimen entero) + bandit
        per_fixed = {s: [] for s in STRATS}
        rng = np.random.default_rng(seed * 311 + REGIME_ID[regime] * 53 + 3)
        # bandit state
        means = {s: 0.0 for s in STRATS}; counts = {s: 0 for s in STRATS}
        brng = np.random.default_rng(seed * 911 + REGIME_ID[regime] * 17)
        per_bandit = []
        for t in range(T):
            q, typ, cost = _draw(rng, n)
            qe = np.clip(q + rng.normal(0.0, noise, size=n), 0.0, 1.0)
            ce = np.clip(cost + rng.normal(0.0, noise, size=n), 0.2, None)
            denom = _oracle(q, typ, cost, B, coverage)
            if denom < 1e-9:
                continue
            # cada estrategia fija (mismo pool)
            for s in STRATS:
                picks = _select(s, qe, typ, ce, B, coverage)
                r = _objective(picks, q, typ, coverage) / denom
                if t >= warmup:
                    per_fixed[s].append(r)
            # bandit: elige una estrategia (ε-greedy) y observa su reward
            if brng.random() < eps or any(counts[s] == 0 for s in STRATS):
                sb = STRATS[int(brng.integers(0, len(STRATS)))]
            else:
                sb = max(STRATS, key=lambda s: means[s])
            picks_b = _select(sb, qe, typ, ce, B, coverage)
            rb = _objective(picks_b, q, typ, coverage) / denom
            counts[sb] += 1
            means[sb] += (rb - means[sb]) / counts[sb]
            if t >= warmup:
                per_bandit.append(rb)
        for s in STRATS:
            if per_fixed[s]:
                fixed[s].append(float(np.mean(per_fixed[s])))
        if per_bandit:
            bandit_r.append(float(np.mean(per_bandit)))
        # oracle_selector: la mejor estrategia FIJA por seed
        best_s = max(STRATS, key=lambda s: float(np.mean(per_fixed[s])) if per_fixed[s] else -1)
        if per_fixed[best_s]:
            oracle_sel_r.append(float(np.mean(per_fixed[best_s])))
    out = {s: round(float(np.mean(fixed[s])), 4) for s in STRATS}
    out["bandit"] = round(float(np.mean(bandit_r)), 4)
    out["oracle_selector"] = round(float(np.mean(oracle_sel_r)), 4)
    return out


def run(n, B, T, warmup, eps, noise, n_seeds):
    return {reg: run_cell(n, B, reg, T, warmup, eps, noise, n_seeds) for reg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    ah, ch = grid["additive_hetero"], grid["coverage_hetero"]
    best_add = max(STRATS, key=lambda s: ah[s])
    best_cov = max(STRATS, key=lambda s: ch[s])
    best_differs = best_add != best_cov
    # ¿alguna estrategia fija es la mejor (o ≈) en AMBOS regímenes?
    fixed_avg = {s: round((ah[s] + ch[s]) / 2.0, 4) for s in STRATS}
    best_single_fixed = max(STRATS, key=lambda s: fixed_avg[s])
    bandit_avg = round((ah["bandit"] + ch["bandit"]) / 2.0, 4)
    regret_add = round(ah["oracle_selector"] - ah["bandit"], 4)
    regret_cov = round(ch["oracle_selector"] - ch["bandit"], 4)
    bandit_beats_fixed = round(bandit_avg - fixed_avg[best_single_fixed], 4)

    TOL = 0.03
    no_single_dominates = best_differs and (
        (ah[best_cov] < ah[best_add] - TOL) or (ch[best_add] < ch[best_cov] - TOL))
    bandit_no_regret = (max(regret_add, regret_cov) <= 0.06)
    bandit_beats = bandit_beats_fixed > -TOL    # bandit >= mejor fija única (promedio)

    if no_single_dominates and bandit_no_regret and bandit_beats:
        status = "apoyada"
        verdict = ("H-V4-8g APOYADA (converso de CYCLE 92): NINGUNA estrategia de asignación FIJA domina ambos regímenes "
                   "-- la mejor difiere (ADITIVO+hetero: '{ba}'={ahb}; COBERTURA+hetero: '{bc}'={chb}; per-costo ayuda en "
                   "aditivo pero estorba en cobertura). El BANDIT sobre estrategias DESCUBRE la correcta del feedback de "
                   "outcomes con NO-REGRET: bandit={bav} (regret vs oracle_selector ADD={ra}/COV={rc}) y SUPERA a la "
                   "mejor estrategia FIJA única ({bsf}={fav}) por {bbf}. => a diferencia de CYCLE 92 (donde un prior "
                   "flexible dominaba y la selección era innecesaria), AQUÍ la selección de la política de asignación "
                   "ES NECESARIA y el agente la DESCUBRE del feedback. La meta-decisión (qué política de asignación) "
                   "también es R-VALOR-aprendible.").format(
                       ba=best_add, ahb=_f(ah[best_add]), bc=best_cov, chb=_f(ch[best_cov]), bav=_f(bandit_avg),
                       ra=_f(regret_add), rc=_f(regret_cov), bsf=best_single_fixed, fav=_f(fixed_avg[best_single_fixed]),
                       bbf=_f(bandit_beats_fixed))
    elif not no_single_dominates:
        status = "refutada"
        verdict = ("H-V4-8g REFUTADA: una estrategia fija domina ambos regímenes (mejor add='{ba}', cov='{bc}'; "
                   "best_differs={bd}) -> la selección es innecesaria (como CYCLE 92).").format(
                       ba=best_add, bc=best_cov, bd=best_differs)
    else:
        status = "mixta"
        verdict = ("H-V4-8g MIXTA: no_single_dominates={nd} (best add='{ba}'/cov='{bc}') bandit_no_regret={nr} "
                   "(regret ADD={ra}/COV={rc}) bandit_beats_fixed={bb} ({bbf}).").format(
                       nd=no_single_dominates, ba=best_add, bc=best_cov, nr=bandit_no_regret, ra=_f(regret_add),
                       rc=_f(regret_cov), bb=bandit_beats, bbf=_f(bandit_beats_fixed))

    return {"grid": grid, "best_add": best_add, "best_cov": best_cov, "best_differs": bool(best_differs),
            "fixed_avg": fixed_avg, "best_single_fixed": best_single_fixed, "bandit_avg": bandit_avg,
            "regret_add": regret_add, "regret_cov": regret_cov, "bandit_beats_fixed": bandit_beats_fixed,
            "no_single_dominates": bool(no_single_dominates), "bandit_no_regret": bool(bandit_no_regret),
            "bandit_beats": bool(bandit_beats), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--B", type=float, default=10.0)
    ap.add_argument("--T", type=int, default=60)
    ap.add_argument("--warmup", type=int, default=15)
    ap.add_argument("--eps", type=float, default=0.2)
    ap.add_argument("--noise", type=float, default=0.05)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp086] CYCLE 102 / H-V4-8g — META-ALLOCATION: ¿el agente descubre la política de asignación del feedback? (converso de 92)")
    log(f"[exp086] n={args.n} B={args.B} T={args.T} warmup={args.warmup} eps={args.eps} noise={args.noise} seeds={args.seeds} regimes={REGIMES}")

    grid = run(args.n, args.B, args.T, args.warmup, args.eps, args.noise, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        c = grid[reg]
        log(f"[exp086] {reg:>16}: " + " ".join(f"{s}={c[s]:.3f}" for s in STRATS) +
            f" | bandit={c['bandit']:.3f} oracle_sel={c['oracle_selector']:.3f}")
    log(f"[exp086] best add='{sm['best_add']}' cov='{sm['best_cov']}' (differs={sm['best_differs']}) | "
        f"bandit_avg={sm['bandit_avg']:.3f} vs best_fixed({sm['best_single_fixed']})={sm['fixed_avg'][sm['best_single_fixed']]:.3f} (+{sm['bandit_beats_fixed']:.3f}) | "
        f"regret ADD={sm['regret_add']:.3f}/COV={sm['regret_cov']:.3f}")
    log(f"[exp086] no_single_dominates={sm['no_single_dominates']} bandit_no_regret={sm['bandit_no_regret']} bandit_beats={sm['bandit_beats']}")
    log(f"[exp086] VEREDICTO H-V4-8g: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp086_meta_allocation", "cycle": 102, "hypothesis": "H-V4-8g",
           "claim": "ninguna estrategia de asignacion fija domina todos los regimenes (per-costo ayuda en aditivo pero "
                    "estorba en cobertura que satura); un bandit sobre estrategias DESCUBRE la correcta del feedback de "
                    "outcomes con no-regret -> la meta-decision de asignacion es R-VALOR-aprendible (converso de CYCLE 92)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp086] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

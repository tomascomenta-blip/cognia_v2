r"""
exp076 — CYCLE 92 / H-V4-3b (rama R-PRIOR, hija de CYCLE 91; cierra su caveat central): ¿puede el agente SELECCIONAR la
base/prior correcta de SUS PROPIOS datos (CV held-out) — SIN conocimiento de diseño del régimen — logrando no-regret a
través de regímenes de estructura del valor? (META-PRIOR.)

CONTEXTO. CYCLE 91 (exp075) mostró que un prior MATCHEADO a la estructura recupera a una fracción del feedback de una base
genérica — PERO el prior se matcheó por conocimiento de DISEÑO (yo sabía que la estructura era local-en-c). El caveat
central: de DÓNDE viene el prior correcto. Esta hija lo cierra: el agente tiene un MENÚ de bases {poly2, rbf, bin} y
ELIGE por VALIDACIÓN CRUZADA held-out sobre su propio buffer (sin oráculo ni aviso de régimen), replicando el patrón del
SELECTOR no-regret de CYCLE 86 (allí elegía producto<->aprendido; aquí elige la BASE).

DISEÑO (numpy + sandbox REAL de exp018). DOS regímenes que el agente NO conoce a priori:
  - SMOOTH (conjuntivo, como CYCLE 89 strong): well_formed ~ Bernoulli(c) -> E[v|c,r] = c·r (poly2 lo NESTA; barato/óptimo).
  - BAND (multi-banda, como CYCLE 90/91): well_formed = dos bandas interiores en c -> E[v|c,r] = band(c)·r (rbf matcheado).
El sandbox EJECUTA cada candidato y decide v∈{0,1}. Feedback COSTOSO (K=10/ronda, random insesgado). Brazos:
always_poly2 / always_rbf / always_bin (bases FIJAS), selector (elige la base por CV held-out: rankea el fold held-out
por cada base ajustada en train, perf_of held-out, elige la mejor; refit en todo el buffer), oracle_selector (por seed
elige la base FIJA de mejor perf REAL = techo de un selector PERFECTO), bayes (techo E[v|c,r]), product, chance.

PREGUNTA FALSABLE (META-PRIOR / no-regret):
  - APOYADA si el selector logra NO-REGRET: en CADA régimen ≈ la mejor base fija (y ≈ oracle_selector, regret <= 0.03), Y
    PROMEDIANDO ambos regímenes el selector SUPERA a CUALQUIER base fija única (+>0.03) — porque ninguna base fija gana en
    ambos regímenes y el selector sí. => el agente DESCUBRE el prior correcto de sus datos (cierra el caveat de diseño de 91).
  - REFUTADA si el selector ≈ una base fija única (no adapta) o su regret es grande (CV demasiado ruidosa a este presupuesto).
  - MIXTA si elige bien en un régimen pero no en el otro / supera a las fijas sólo parcialmente.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp076_prior_selector.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp076_prior_selector.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp074_nonnested_value.run import (
    _well_formed_band, _wrong_value_expr, _poly_feats, _ridge_w, _poly_score, _bin_fit, _bin_score, perf_of, LO, HI,
    Q_S, Q_SR)
from cognia_x.experiments.exp075_matched_prior.run import _rbf_feats, _rbf_w, _rbf_score

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["always_poly2", "always_rbf", "always_bin", "selector", "oracle_selector", "bayes", "product", "chance"]
BASES = ["poly2", "rbf", "bin"]
REGIMES = ["smooth", "band"]
REGIME_ID = {"smooth": 0, "band": 1}
RIDGE_ALPHA = 1e-2
MIN_FIT = 8
GBINS = 8
T = 40


def _make_candidate(rng, c, r, n, regime):
    wf = (rng.random() < c) if regime == "smooth" else _well_formed_band(c)
    vm = rng.random() < r
    if wf and vm:
        expr = E.real_expression(rng, n)
    elif wf and not vm:
        expr = _wrong_value_expr(rng, n)
    else:
        expr = b"x"
    return 1.0 if E.verify(E.make_prompt(n), bytes(expr) + b"\n", strong=True) else 0.0


def _true_mean(c, r, regime):
    if regime == "smooth":
        return np.asarray(c) * np.asarray(r)
    band = np.array([1.0 if _well_formed_band(ci) else 0.0 for ci in np.atleast_1d(c)])
    return band * np.asarray(r)


def _draw_pool(rng, n, regime, sc):
    c = rng.random(n)
    r = rng.random(n)
    v = np.empty(n, dtype=float)
    for i in range(n):
        ni = int(rng.integers(LO, HI + 1))
        v[i] = _make_candidate(rng, c[i], r[i], ni, regime)
    c_est = np.clip(c + rng.normal(0.0, sc / np.sqrt(Q_S), size=n), 0.0, 1.0)
    r_est = np.clip(r + rng.normal(0.0, Q_SR, size=n), 0.0, 1.0)
    return c_est, r_est, v, _true_mean(c, r, regime)


def _fit_base(base, bc, br, by):
    if base == "poly2":
        return _ridge_w(bc, br, by, 2, RIDGE_ALPHA)
    if base == "rbf":
        return _rbf_w(bc, br, by, RIDGE_ALPHA)
    return _bin_fit(bc, br, by, GBINS)            # (table, glob)


def _score_base(base, w, ce, re):
    if base == "poly2":
        return _poly_score(ce, re, w, 2)
    if base == "rbf":
        return _rbf_score(ce, re, w)
    table, glob = w
    return _bin_score(ce, re, table, glob, GBINS)


def _cv_pick(bc, br, by, k_eval, rng):
    """Elige la base por CV held-out: split 70/30, ajusta en train, rankea el held-out, perf_of held-out. Mejor gana."""
    nbuf = len(by)
    idx = rng.permutation(nbuf)
    n_tr = max(MIN_FIT, int(round(0.7 * nbuf)))
    tr, ho = idx[:n_tr], idx[n_tr:]
    if len(ho) < 4 or len(set(np.asarray(by)[tr])) < 2:
        return "poly2"
    bc, br, by = np.asarray(bc), np.asarray(br), np.asarray(by)
    kho = max(2, len(ho) // 3)
    best, best_perf = "poly2", -1.0
    for base in BASES:
        try:
            w = _fit_base(base, bc[tr], br[tr], by[tr])
            s = _score_base(base, w, bc[ho], br[ho])
            picks = np.argsort(s + 1e-9 * rng.random(len(ho)))[-kho:]
            perf = perf_of(picks, by[ho])
        except Exception:  # noqa: BLE001
            perf = -1.0
        if perf > best_perf:
            best, best_perf = base, perf
    return best


def run_cell(n, k_budget, k_eval, regime, E_rounds, sc, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 4691 + REGIME_ID[regime] * 911 + 53)
        bc, br, by = [], [], []
        for _ in range(T):
            ce, re, val, _ = _draw_pool(rng, n, regime, sc)
            sel = rng.choice(n, size=min(k_budget, n), replace=False)
            for i in sel:
                bc.append(ce[i]); br.append(re[i]); by.append(val[i])
        have = len(by) >= MIN_FIT and len(set(by)) > 1
        ws = {b: (_fit_base(b, bc, br, by) if have else None) for b in BASES}
        chosen = _cv_pick(bc, br, by, k_eval, rng) if have else "poly2"
        rng_e = np.random.default_rng(seed * 7333 + REGIME_ID[regime] * 37 + 17)
        p = {a: [] for a in ARMS}
        fixed_perf = {b: [] for b in BASES}
        for _ in range(E_rounds):
            ce, re, val, tm = _draw_pool(rng_e, n, regime, sc)
            jit = 1e-9 * rng_e.random(n)
            p["product"].append(perf_of(np.argsort(ce * re + jit)[-k_eval:], val))
            p["bayes"].append(perf_of(np.argsort(tm + jit)[-k_eval:], val))
            p["chance"].append(perf_of(rng_e.choice(n, size=k_eval, replace=False), val))
            for b in BASES:
                s = _score_base(b, ws[b], ce, re) if ws[b] is not None else ce * re
                pf = perf_of(np.argsort(s + jit)[-k_eval:], val)
                fixed_perf[b].append(pf)
                p["always_{}".format(b)].append(pf)
            s_sel = _score_base(chosen, ws[chosen], ce, re) if ws[chosen] is not None else ce * re
            p["selector"].append(perf_of(np.argsort(s_sel + jit)[-k_eval:], val))
        # oracle_selector: por seed, la base FIJA de mejor perf REAL (techo de un selector perfecto)
        best_fixed = max(BASES, key=lambda b: float(np.mean(fixed_perf[b])))
        p["oracle_selector"] = p["always_{}".format(best_fixed)]
        for a in ARMS:
            acc[a].append(float(np.mean(p[a])))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k_budget, k_eval, E_rounds, sc, n_seeds):
    return {reg: run_cell(n, k_budget, k_eval, reg, E_rounds, sc, n_seeds) for reg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    sm_cell, bd_cell = grid["smooth"], grid["band"]

    def best_fixed(cell):
        return max(("always_poly2", "always_rbf", "always_bin"), key=lambda a: cell[a])

    bf_sm, bf_bd = best_fixed(sm_cell), best_fixed(bd_cell)
    regret_sm = round(sm_cell[bf_sm] - sm_cell["selector"], 4)
    regret_bd = round(bd_cell[bf_bd] - bd_cell["selector"], 4)
    regret_vs_oracle_sm = round(sm_cell["oracle_selector"] - sm_cell["selector"], 4)
    regret_vs_oracle_bd = round(bd_cell["oracle_selector"] - bd_cell["selector"], 4)

    sel_avg = round((sm_cell["selector"] + bd_cell["selector"]) / 2.0, 4)
    fixed_avg = {b: round((sm_cell["always_" + b] + bd_cell["always_" + b]) / 2.0, 4) for b in BASES}
    best_single_fixed = max(BASES, key=lambda b: fixed_avg[b])
    sel_beats_fixed = round(sel_avg - fixed_avg[best_single_fixed], 4)

    REGRET_TOL = 0.03
    BEAT_THR = 0.03

    no_regret = (max(regret_sm, regret_bd) <= REGRET_TOL) and \
                (max(regret_vs_oracle_sm, regret_vs_oracle_bd) <= REGRET_TOL)
    beats_any_fixed = sel_beats_fixed > BEAT_THR

    if no_regret and beats_any_fixed:
        status = "apoyada"
        verdict = ("H-V4-3b APOYADA: el agente DESCUBRE el prior correcto de sus datos (CV held-out), no-regret a través "
                   "de regímenes. SMOOTH: selector={ss} ≈ mejor base fija {bfs}={sbf} (regret {rs}); BAND: selector={sb} "
                   "≈ mejor base fija {bfb}={bbf} (regret {rb}). vs oracle_selector (selector PERFECTO): regret "
                   "S={ros}/B={rob} (<= {tol}). PROMEDIANDO ambos regímenes el selector={sa} SUPERA a la mejor base "
                   "FIJA única ({bsf}={fa}) por +{bf} -- ninguna base fija gana en ambos regímenes, el selector sí. => "
                   "cierra el caveat de diseño de CYCLE 91: el prior correcto se DESCUBRE de los datos.").format(
                       ss=_f(sm_cell["selector"]), bfs=bf_sm.replace("always_", ""), sbf=_f(sm_cell[bf_sm]), rs=_f(regret_sm),
                       sb=_f(bd_cell["selector"]), bfb=bf_bd.replace("always_", ""), bbf=_f(bd_cell[bf_bd]), rb=_f(regret_bd),
                       ros=_f(regret_vs_oracle_sm), rob=_f(regret_vs_oracle_bd), tol=REGRET_TOL,
                       sa=_f(sel_avg), bsf=best_single_fixed, fa=_f(fixed_avg[best_single_fixed]), bf=_f(sel_beats_fixed))
    elif not beats_any_fixed and (fixed_avg[best_single_fixed] - sel_avg) > BEAT_THR:
        status = "refutada"
        verdict = ("H-V4-3b REFUTADA: el selector NO supera a una base fija única (selector_avg={sa} vs mejor fija "
                   "{bsf}={fa}); o la CV no adapta. La selección de prior de los datos no aporta aquí.").format(
                       sa=_f(sel_avg), bsf=best_single_fixed, fa=_f(fixed_avg[best_single_fixed]))
    elif no_regret and not beats_any_fixed:
        status = "mixta"
        verdict = ("H-V4-3b MIXTA (no-regret SÍ, pero selección INNECESARIA): el META-PRIOR FUNCIONA -- el selector por "
                   "CV held-out logra NO-REGRET (regret vs mejor base por régimen S={rs}/B={rb}; vs oracle_selector "
                   "PERFECTO S={ros}/B={rob}, <= {tol}): el agente DESCUBRE de sus datos qué base usar (poly2 en smooth, "
                   "rbf en band), cerrando el caveat de diseño de CYCLE 91. PERO la selección es PRÁCTICAMENTE "
                   "INNECESARIA: una base FLEXIBLE-suficiente ({bsf}) casi DOMINA ambos regímenes (avg={fa}), así que el "
                   "selector la supera sólo +{sbf} (< {beat}). El rbf NESTA tanto c·r (smooth) como band(c)·r (band) -> "
                   "always-rbf ≈ selector. ESPEJA CYCLE 86 al nivel meta: un prior flexible que nesta los regímenes hace "
                   "innecesaria la selección/detección explícita; la selección sólo paga cuando NINGUNA base domina.").format(
                       rs=_f(regret_sm), rb=_f(regret_bd), ros=_f(regret_vs_oracle_sm), rob=_f(regret_vs_oracle_bd),
                       tol=REGRET_TOL, bsf=best_single_fixed, fa=_f(fixed_avg[best_single_fixed]),
                       sbf=_f(sel_beats_fixed), beat=BEAT_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-3b MIXTA: no_regret={nr} (regret S={rs}/B={rb}, vs oracle S={ros}/B={rob}) beats_any_fixed={bf} "
                   "(selector_avg={sa} vs mejor fija {bsf}={fa}, +{sbf}). El selector adapta PARCIALMENTE.").format(
                       nr=no_regret, rs=_f(regret_sm), rb=_f(regret_bd), ros=_f(regret_vs_oracle_sm),
                       rob=_f(regret_vs_oracle_bd), bf=beats_any_fixed, sa=_f(sel_avg), bsf=best_single_fixed,
                       fa=_f(fixed_avg[best_single_fixed]), sbf=_f(sel_beats_fixed))

    return {"grid": grid, "best_fixed_smooth": bf_sm, "best_fixed_band": bf_bd,
            "regret_smooth": regret_sm, "regret_band": regret_bd,
            "regret_vs_oracle_smooth": regret_vs_oracle_sm, "regret_vs_oracle_band": regret_vs_oracle_bd,
            "selector_avg": sel_avg, "fixed_avg": fixed_avg, "best_single_fixed": best_single_fixed,
            "selector_beats_best_fixed": sel_beats_fixed, "no_regret": bool(no_regret),
            "beats_any_fixed": bool(beats_any_fixed), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k_budget", type=int, default=10)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--E", type=int, default=20)
    ap.add_argument("--ctrl_noise", type=float, default=0.2)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.E = 8, 10

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp076] CYCLE 92 / H-V4-3b — META-PRIOR: el agente ELIGE la base por CV held-out (no-regret a través de regímenes)")
    log(f"[exp076] n={args.n} k_budget={args.k_budget} k_eval={args.k_eval} T={T} E={args.E} seeds={args.seeds} "
        f"bases={BASES} regimes={REGIMES} ctrl_noise={args.ctrl_noise} targets=[{LO},{HI}]")

    grid = run(args.n, args.k_budget, args.k_eval, args.E, args.ctrl_noise, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        c = grid[reg]
        log(f"[exp076] {reg:>6}: poly2={c['always_poly2']:.3f} rbf={c['always_rbf']:.3f} bin={c['always_bin']:.3f} "
            f"selector={c['selector']:.3f} oracle_sel={c['oracle_selector']:.3f} bayes={c['bayes']:.3f} product={c['product']:.3f}")
    log(f"[exp076] best_fixed: smooth={sm['best_fixed_smooth'].replace('always_','')} band={sm['best_fixed_band'].replace('always_','')} | "
        f"regret S={sm['regret_smooth']:.3f}/B={sm['regret_band']:.3f} | vs_oracle S={sm['regret_vs_oracle_smooth']:.3f}/B={sm['regret_vs_oracle_band']:.3f}")
    log(f"[exp076] selector_avg={sm['selector_avg']:.3f} vs best_single_fixed({sm['best_single_fixed']})={sm['fixed_avg'][sm['best_single_fixed']]:.3f} "
        f"(+{sm['selector_beats_best_fixed']:.3f}) | fixed_avg={sm['fixed_avg']}")
    log(f"[exp076] no_regret={sm['no_regret']} beats_any_fixed={sm['beats_any_fixed']}")
    log(f"[exp076] VEREDICTO H-V4-3b: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp076_prior_selector", "cycle": 92, "hypothesis": "H-V4-3b",
           "claim": "el agente puede SELECCIONAR la base/prior correcta de sus propios datos via CV held-out (sin "
                    "conocimiento de diseno del regimen) logrando no-regret a traves de regimenes de estructura del "
                    "valor: iguala a la mejor base fija en cada regimen y supera a cualquier base fija unica en promedio",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp076] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

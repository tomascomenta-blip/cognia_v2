r"""
exp075 — CYCLE 91 / H-V4-3a (rama R-PRIOR, ataca H-V4-3 ABIERTA; hija de CYCLE 90): ¿la FORMA/CALIDAD del prior (la base
del estimador) — no su capacidad cruda ni el volumen de datos — fija la eficiencia muestral? Un prior MATCHEADO a la
estructura del valor recupera el valor no-nesteable a una FRACCIÓN del feedback que una base no-paramétrica genérica.

CONTEXTO. CYCLE 90 (exp074) halló que sobre un valor REAL no-nesteable por el poly2 (dos bandas interiores en c), el
poly2 default FALLA y una base RICA GENÉRICA (binned 8×8) recupera sólo PARCIALMENTE y es DATA-HUNGRY (no alcanza el
techo bayes ni con T=1000). Dejó como próximo: un prior MATCHEADO a la estructura (features locales/kernel) que recupere
BARATO. Esta es justo la tesis de R-PRIOR / H-V4-3 (ABIERTA desde el reset): "la calidad/forma del prior fija la
eficiencia muestral; un prior correcto iguala a métodos generales caros a una fracción del costo".

DISEÑO (numpy + sandbox REAL de exp018; MISMO sustrato no-nesteable de exp074). Valor REAL = is_real_solution
(well_formed = c en [0.2,0.4)∪[0.6,0.8), no-monótona; value_match ~ Bernoulli(r)) -> E[v|c,r] = 1{c en banda}·r. Tres
PRIORS (bases) compitiendo con el MISMO feedback costoso (K random/ronda, buffer compartido):
  - learned_poly2: base GLOBAL equivocada (parábola; falla, CYCLE 90).
  - learned_bin:   base no-paramétrica GENÉRICA (grilla 8×8 dura, sin suavidad; recupera parcial y DATA-HUNGRY).
  - learned_rbf:   prior MATCHEADO = bumps GAUSSIANOS LOCALES en c × LINEAL en r (encode "suave/local en c, lineal en
                   r" = la estructura correcta de band(c)·r, sin conocer las bandas exactas). Pocos parámetros, suave.
Eje de presupuesto B ∈ {low T=20, high T=80}. Brazos extra: bayes (techo E[v|c,r]), product, oracle, chance. 48 seeds.

PREGUNTA FALSABLE (R-PRIOR):
  - APOYADA si el prior MATCHEADO (rbf) es SAMPLE-EFFICIENT: rbf a presupuesto BAJO ya iguala/supera a la base genérica
    (bin) a presupuesto ALTO (rbf_low >= bin_high − 0.02) Y rbf_low > bin_low + 0.03 (gana con pocos datos) Y rbf > poly2.
    => la FORMA/CALIDAD del prior (no el volumen/capacidad) fija la eficiencia muestral.
  - REFUTADA si rbf ≈ bin (la forma del prior no aporta) o rbf no supera a poly2.
  - MIXTA en otro caso (p.ej. rbf gana algo pero no a fracción del costo).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp075_matched_prior.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp075_matched_prior.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

# Reusa el sustrato no-nesteable de CYCLE 90 (verificador REAL + valor de dos bandas interiores).
from cognia_x.experiments.exp074_nonnested_value.run import (
    _draw_pool, _well_formed_band, _poly_feats, _ridge_w, _poly_score, _bin_fit, _bin_score, perf_of, LO, HI)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["product", "learned_poly2", "learned_bin", "learned_rbf", "bayes", "oracle", "chance"]
BUDGETS = {"low": 20, "high": 80}
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
GBINS = 8
RBF_C = np.linspace(0.0, 1.0, 9)         # 9 centros locales en c
RBF_W = 0.08                             # ancho del bump (resuelve bandas de ancho 0.2)


def _rbf_feats(c, r):
    """Prior MATCHEADO: bumps gaussianos LOCALES en c, en tensor con [1, r] (lineal en r). Encode 'suave/local en c,
    lineal en r' = la estructura de E[v]=band(c)·r, SIN conocer las bandas exactas (sólo el TIPO de estructura)."""
    c = np.asarray(c); r = np.asarray(r)
    bumps = np.exp(-((c[:, None] - RBF_C[None, :]) ** 2) / (2.0 * RBF_W ** 2))   # n × 9
    return np.concatenate([bumps, bumps * r[:, None]], axis=1)                   # n × 18


def _rbf_w(c_obs, r_obs, y, alpha):
    X = _rbf_feats(c_obs, r_obs)
    A = X.T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ np.asarray(y))


def _rbf_score(c_est, r_est, w):
    return _rbf_feats(c_est, r_est) @ w


def run_cell(n, k_budget, k_eval, T, E_rounds, sc, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 4231 + T * 19 + 211)
        bc, br, by = [], [], []
        for _ in range(T):
            ce, re, val, _ = _draw_pool(rng, n, sc)
            sel = rng.choice(n, size=min(k_budget, n), replace=False)
            for i in sel:
                bc.append(ce[i]); br.append(re[i]); by.append(val[i])
        have = len(by) >= MIN_FIT and len(set(by)) > 1
        w2 = _ridge_w(bc, br, by, 2, RIDGE_ALPHA) if have else None
        wr = _rbf_w(bc, br, by, RIDGE_ALPHA) if have else None
        table, glob = _bin_fit(bc, br, by, GBINS) if have else (None, 0.0)
        rng_e = np.random.default_rng(seed * 6577 + T * 37 + 13)
        p = {a: [] for a in ARMS}
        for _ in range(E_rounds):
            ce, re, val, tm = _draw_pool(rng_e, n, sc)
            jit = 1e-9 * rng_e.random(n)
            p["product"].append(perf_of(np.argsort(ce * re + jit)[-k_eval:], val))
            p["bayes"].append(perf_of(np.argsort(tm + jit)[-k_eval:], val))
            p["oracle"].append(perf_of(np.argsort(val + jit)[-k_eval:], val))
            p["chance"].append(perf_of(rng_e.choice(n, size=k_eval, replace=False), val))
            s2 = _poly_score(ce, re, w2, 2) if w2 is not None else ce * re
            sr = _rbf_score(ce, re, wr) if wr is not None else ce * re
            sb = _bin_score(ce, re, table, glob, GBINS) if table is not None else ce * re
            p["learned_poly2"].append(perf_of(np.argsort(s2 + jit)[-k_eval:], val))
            p["learned_rbf"].append(perf_of(np.argsort(sr + jit)[-k_eval:], val))
            p["learned_bin"].append(perf_of(np.argsort(sb + jit)[-k_eval:], val))
        for a in ARMS:
            acc[a].append(float(np.mean(p[a])))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k_budget, k_eval, E_rounds, sc, n_seeds):
    return {b: run_cell(n, k_budget, k_eval, T, E_rounds, sc, n_seeds) for b, T in BUDGETS.items()}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    hi = grid["high"]; lo = grid["low"]
    rbf_lo, rbf_hi = lo["learned_rbf"], hi["learned_rbf"]
    bin_lo, bin_hi = lo["learned_bin"], hi["learned_bin"]
    rbf_sample_eff = round(rbf_lo - bin_lo, 4)                  # >0: rbf gana con POCOS datos
    rbf_fraction_cost = round(rbf_lo - bin_hi, 4)              # >=~0: rbf a presupuesto BAJO iguala bin a presupuesto ALTO
    rbf_saturates = round(rbf_hi - rbf_lo, 4)                  # chico: rbf satura rápido (no data-hungry)
    bin_data_hungry = round(bin_hi - bin_lo, 4)               # grande: bin necesita datos
    rbf_vs_poly2 = round(rbf_hi - hi["learned_poly2"], 4)
    rbf_bayes_gap = round(hi["bayes"] - rbf_hi, 4)
    bin_bayes_gap = round(hi["bayes"] - bin_hi, 4)

    SAMPLE_EFF_THR = 0.03      # rbf gana sobre bin a bajo presupuesto
    FRACTION_TOL = 0.02        # rbf_low alcanza bin_high (mismo techo a fracción del costo)
    POLY2_THR = 0.03           # rbf supera a la base equivocada

    sample_efficient = rbf_sample_eff > SAMPLE_EFF_THR
    fraction_of_cost = rbf_fraction_cost >= -FRACTION_TOL
    beats_poly2 = rbf_vs_poly2 > POLY2_THR

    if sample_efficient and fraction_of_cost and beats_poly2:
        status = "apoyada"
        verdict = ("H-V4-3a APOYADA: la FORMA/CALIDAD del prior fija la eficiencia muestral. El prior MATCHEADO (rbf: "
                   "bumps locales en c × lineal en r) es SAMPLE-EFFICIENT: a presupuesto BAJO rbf={rl} ya iguala/supera "
                   "a la base genérica bin a presupuesto ALTO ({bh}) -- rbf a FRACCIÓN del costo (Δ={fc}) -- y gana a "
                   "bin a igual bajo presupuesto (+{se}). rbf SATURA rápido (high−low +{rs}) mientras bin es DATA-HUNGRY "
                   "(+{bd}). rbf supera a la base equivocada poly2 (+{vp}) y queda más cerca del techo bayes (gap rbf "
                   "{rbg} vs bin {bbg}). => el lever NO es el volumen de datos ni la capacidad cruda sino el MATCH del "
                   "prior con la estructura del valor (R-PRIOR/H-V4-3).").format(
                       rl=_f(rbf_lo), bh=_f(bin_hi), fc=_f(rbf_fraction_cost), se=_f(rbf_sample_eff), rs=_f(rbf_saturates),
                       bd=_f(bin_data_hungry), vp=_f(rbf_vs_poly2), rbg=_f(rbf_bayes_gap), bbg=_f(bin_bayes_gap))
    elif not beats_poly2 or (rbf_sample_eff <= 0 and rbf_fraction_cost < -FRACTION_TOL):
        status = "refutada"
        verdict = ("H-V4-3a REFUTADA: el prior matcheado (rbf={rh}) NO aporta sobre la base genérica/equivocada "
                   "(bin_high={bh}, poly2={p2}): rbf_sample_eff={se}, rbf_vs_poly2={vp}. La forma del prior no fija la "
                   "eficiencia muestral aquí.").format(rh=_f(rbf_hi), bh=_f(bin_hi), p2=_f(hi["learned_poly2"]),
                                                       se=_f(rbf_sample_eff), vp=_f(rbf_vs_poly2))
    else:
        status = "mixta"
        verdict = ("H-V4-3a MIXTA: sample_efficient={se}(+{sev}) fraction_of_cost={fc}(Δ={fcv}) beats_poly2={bp}(+{vp}). "
                   "El prior matcheado ayuda PARCIALMENTE pero no a clara fracción del costo.").format(
                       se=sample_efficient, sev=_f(rbf_sample_eff), fc=fraction_of_cost, fcv=_f(rbf_fraction_cost),
                       bp=beats_poly2, vp=_f(rbf_vs_poly2))

    return {"grid": grid, "rbf_sample_eff_vs_bin_low": rbf_sample_eff, "rbf_fraction_cost_vs_bin_high": rbf_fraction_cost,
            "rbf_saturates": rbf_saturates, "bin_data_hungry": bin_data_hungry, "rbf_vs_poly2": rbf_vs_poly2,
            "rbf_bayes_gap": rbf_bayes_gap, "bin_bayes_gap": bin_bayes_gap,
            "sample_efficient": bool(sample_efficient), "fraction_of_cost": bool(fraction_of_cost),
            "beats_poly2": bool(beats_poly2), "status": status, "verdict": verdict}


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

    log("[exp075] CYCLE 91 / H-V4-3a — la FORMA del prior fija la eficiencia muestral (prior MATCHEADO rbf vs bin/poly2)")
    log(f"[exp075] n={args.n} k_budget={args.k_budget} k_eval={args.k_eval} E={args.E} seeds={args.seeds} "
        f"RBF(centros={len(RBF_C)},w={RBF_W}) GBINS={GBINS} budgets={BUDGETS} ctrl_noise={args.ctrl_noise} targets=[{LO},{HI}]")

    grid = run(args.n, args.k_budget, args.k_eval, args.E, args.ctrl_noise, args.seeds)
    sm = build_summary(grid)

    for b in BUDGETS:
        c = grid[b]
        log(f"[exp075] {b:>4} (T={BUDGETS[b]}): product={c['product']:.3f} poly2={c['learned_poly2']:.3f} "
            f"bin={c['learned_bin']:.3f} rbf={c['learned_rbf']:.3f} bayes={c['bayes']:.3f} chance={c['chance']:.3f}")
    log(f"[exp075] rbf_sample_eff(vs bin_low)=+{sm['rbf_sample_eff_vs_bin_low']:.3f} | "
        f"rbf_fraction_cost(vs bin_high)={sm['rbf_fraction_cost_vs_bin_high']:.3f} | "
        f"rbf_saturates=+{sm['rbf_saturates']:.3f} vs bin_data_hungry=+{sm['bin_data_hungry']:.3f}")
    log(f"[exp075] rbf_vs_poly2=+{sm['rbf_vs_poly2']:.3f} | rbf_bayes_gap={sm['rbf_bayes_gap']:.3f} vs bin_bayes_gap={sm['bin_bayes_gap']:.3f}")
    log(f"[exp075] sample_efficient={sm['sample_efficient']} fraction_of_cost={sm['fraction_of_cost']} beats_poly2={sm['beats_poly2']}")
    log(f"[exp075] VEREDICTO H-V4-3a: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp075_matched_prior", "cycle": 91, "hypothesis": "H-V4-3a",
           "claim": "la forma/calidad del prior (la base del estimador), no el volumen de datos ni la capacidad cruda, "
                    "fija la eficiencia muestral: un prior matcheado a la estructura (rbf local en c x lineal en r) "
                    "recupera el valor no-nesteable a una fraccion del feedback que una base no-parametrica generica (bin)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp075] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

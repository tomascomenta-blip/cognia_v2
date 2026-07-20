r"""
exp096 — CYCLE 112 / H-V4-8q (rama R-VALOR, R-VALOR recursivo: el COSTO/ROI de ESTIMAR el valor): todo el arco supuso que
ya tenés un estimador de valor. Pero ESTIMAR no es gratis (computar confianza, probar, verificar para calibrar). ¿Cuándo
conviene PAGAR por estimar el valor (y luego asignar bien) vs ACTUAR sobre un prior barato (al azar)? Es el "valor de la
información sobre el valor": una decisión R-VALOR sobre la propia estimación.

CONTEXTO. Cierra el lazo conceptual del arco: R-VALOR no sólo gobierna QUÉ elegir / CUÁNDO gastar, también SI vale la pena
estimar. La estimación misma es una acción con costo y retorno.

DISEÑO (numpy). n ítems con valor REAL v = base + spread·z (z~U(−0.5,0.5)); 'spread' = HETEROGENEIDAD del valor.
Estrategias para elegir k:
  - estimate: pagar costo c_est, obtener estimador ruidoso e=v+N(0,σ), elegir top-k por e. gain = media(v de top-k) − c_est.
  - prior:    elegir k al AZAR (sin estimar, gratis). gain = media(v de los k al azar) ≈ base.
  - oracle:   top-k por v real, − c_est (referencia).
Se barre spread (heterogeneidad) × c_est (costo de estimar). gain en unidades de valor.

PREGUNTA FALSABLE:
  - APOYADA si hay un CRUCE: a BAJA heterogeneidad (o alto c_est) prior >= estimate (no vale la pena estimar -- todos los
    ítems valen parecido), y a ALTA heterogeneidad (y c_est bajo) estimate > prior (vale pagar por estimar y elegir el
    mejor); y el spread del cruce CRECE con c_est. => decidir SI estimar el valor es ella misma una decisión R-VALOR: el
    ROI de la estimación = ganancia-por-heterogeneidad − costo-de-estimar.
  - REFUTADA si estimate domina/pierde SIEMPRE (la heterogeneidad/el costo no cambian la decisión).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp096_value_of_estimation.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp096_value_of_estimation.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["estimate", "prior", "oracle"]
SPREADS = [0.1, 0.3, 0.6, 1.0]
C_ESTS = [0.05, 0.15]
BASE = 0.5


def run_cell(n, k, spread, c_est, sigma, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 733 + int(spread * 100) * 13 + int(c_est * 100) * 7 + 3)
        v = BASE + spread * (rng.random(n) - 0.5)
        e = v + rng.normal(0.0, sigma, size=n)
        top_est = np.argsort(e)[-k:]
        top_or = np.argsort(v)[-k:]
        rand_k = rng.choice(n, size=k, replace=False)
        acc["estimate"].append(float(np.mean(v[top_est])) - c_est)
        acc["prior"].append(float(np.mean(v[rand_k])))
        acc["oracle"].append(float(np.mean(v[top_or])) - c_est)
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, sigma, n_seeds):
    grid = {}
    for ce in C_ESTS:
        for sp in SPREADS:
            grid["c{}_s{}".format(ce, sp)] = run_cell(n, k, sp, ce, sigma, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def _crossover_spread(grid, ce):
    """Menor spread donde estimate supera a prior, para un c_est dado (None si nunca)."""
    for sp in SPREADS:
        c = grid["c{}_s{}".format(ce, sp)]
        if c["estimate"] > c["prior"]:
            return sp
    return None


def build_summary(grid):
    ce_lo, ce_hi = C_ESTS[0], C_ESTS[-1]
    # a c_est bajo: estimate debe perder a baja heterogeneidad y ganar a alta
    lo_lowspread = grid["c{}_s{}".format(ce_lo, SPREADS[0])]
    lo_highspread = grid["c{}_s{}".format(ce_lo, SPREADS[-1])]
    prior_wins_low_het = lo_lowspread["estimate"] <= lo_lowspread["prior"]
    estimate_wins_high_het = lo_highspread["estimate"] > lo_highspread["prior"]
    cross_lo = _crossover_spread(grid, ce_lo)
    cross_hi = _crossover_spread(grid, ce_hi)
    # el cruce sube con el costo (cross_hi >= cross_lo, tratando None como infinito)
    def _cv(x):
        return 99.0 if x is None else x
    cross_rises = _cv(cross_hi) >= _cv(cross_lo)

    has_crossover = prior_wins_low_het and estimate_wins_high_het

    if has_crossover and cross_rises:
        status = "apoyada"
        verdict = ("H-V4-8q APOYADA: decidir SI estimar el valor es ella misma una decisión R-VALOR (ROI = "
                   "ganancia-por-heterogeneidad − costo-de-estimar). A c_est={cl}: a BAJA heterogeneidad prior gana "
                   "(estimate={el} <= prior={pl}: no vale la pena estimar, todos valen parecido) y a ALTA heterogeneidad "
                   "estimate gana (estimate={eh} > prior={ph}: vale pagar por estimar y elegir el mejor). El spread del "
                   "CRUCE sube con el costo (c={cl}->cruce@{xl}, c={ch}->cruce@{xh}). => hay un RÉGIMEN donde conviene NO "
                   "estimar y actuar sobre el prior; la estimación misma es una acción con costo/retorno gobernada por "
                   "R-VALOR.").format(cl=ce_lo, el=_f(lo_lowspread["estimate"]), pl=_f(lo_lowspread["prior"]),
                                      eh=_f(lo_highspread["estimate"]), ph=_f(lo_highspread["prior"]),
                                      ch=ce_hi, xl=cross_lo, xh=cross_hi)
    elif not has_crossover:
        status = "refutada"
        verdict = ("H-V4-8q REFUTADA: no hay cruce -- prior_wins_low_het={pw}, estimate_wins_high_het={ew} -> la "
                   "heterogeneidad/el costo no cambian la decisión de estimar.").format(
                       pw=prior_wins_low_het, ew=estimate_wins_high_het)
    else:
        status = "mixta"
        verdict = ("H-V4-8q MIXTA: hay cruce (prior@baja, estimate@alta) pero el spread del cruce no sube con el costo "
                   "(c{cl}->@{xl}, c{ch}->@{xh}).").format(cl=ce_lo, xl=cross_lo, ch=ce_hi, xh=cross_hi)

    return {"grid": grid, "prior_wins_low_het": bool(prior_wins_low_het), "estimate_wins_high_het": bool(estimate_wins_high_het),
            "crossover_spread_lo_cost": cross_lo, "crossover_spread_hi_cost": cross_hi, "cross_rises_with_cost": bool(cross_rises),
            "has_crossover": bool(has_crossover), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=64)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--sigma", type=float, default=0.1)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 16

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp096] CYCLE 112 / H-V4-8q — ROI de ESTIMAR el valor: ¿cuándo conviene pagar por estimar vs actuar sobre el prior?")
    log(f"[exp096] n={args.n} k={args.k} sigma={args.sigma} base={BASE} spreads={SPREADS} c_ests={C_ESTS} seeds={args.seeds}")

    grid = run(args.n, args.k, args.sigma, args.seeds)
    sm = build_summary(grid)

    for ce in C_ESTS:
        for sp in SPREADS:
            c = grid["c{}_s{}".format(ce, sp)]
            mark = "estimate" if c["estimate"] > c["prior"] else "PRIOR"
            log(f"[exp096] c_est={ce} spread={sp}: estimate={c['estimate']:.3f} prior={c['prior']:.3f} oracle={c['oracle']:.3f} -> gana {mark}")
    log(f"[exp096] cruce(spread donde estimate>prior): c={C_ESTS[0]}->@{sm['crossover_spread_lo_cost']} | c={C_ESTS[-1]}->@{sm['crossover_spread_hi_cost']} (sube con costo={sm['cross_rises_with_cost']})")
    log(f"[exp096] VEREDICTO H-V4-8q: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp096_value_of_estimation", "cycle": 112, "hypothesis": "H-V4-8q",
           "claim": "decidir SI estimar el valor es una decision R-VALOR (ROI = ganancia-por-heterogeneidad - costo-de-"
                    "estimar): hay un regimen (baja heterogeneidad o alto costo de estimar) donde conviene NO estimar y "
                    "actuar sobre el prior; el cruce sube con el costo de estimar",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp096] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

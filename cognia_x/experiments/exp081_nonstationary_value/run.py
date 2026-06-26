r"""
exp081 — CYCLE 97 / H-V4-8c (rama R-VALOR, sintetiza el arco allocation 83-96 + el arco forgetting 58-74): todo el arco
de asignación R-VALOR (83-96) asumió que la estructura del valor es ESTACIONARIA. El valor real DERIVA (lo que vale la
pena cambia). ¿El combinador R-VALOR aprendido debe OLVIDAR (decay, reusando CYCLE 73) bajo drift -- y el full-history
(toda la experiencia) se vuelve STALE y FALLA?

CONTEXTO. El arco 58-74 mostró para la MEMORIA que el estimador de valor DEBE olvidar (descontar) bajo no-estacionariedad
(CYCLE 73 crossover full/decay; 74 selector no-regret). El arco 83-96 desarrolló el combinador R-VALOR (ridge poly2) para
la ASIGNACIÓN pero SIEMPRE bajo valor estacionario. Este ciclo une ambos: ¿el combinador de asignación necesita olvido
bajo drift de la estructura del valor?

DISEÑO (numpy, online). Por ronda un pool de n ítems con features (c,r)~U(0,1). El valor es un BUMP gaussiano centrado en
(mu_t, nu_t): value(c,r)=exp(-((c-mu)²+(r-nu)²)/(2σ²)). Régimen: ESTACIONARIO (el bump fijo) vs DRIFT (el centro se
RE-SORTEA cada D rondas -> lo que vale la pena se mueve). El agente OBSERVA k_obs ítems al azar (feedback insesgado),
acumula (c,r,value,ronda), y ajusta un ridge poly2; rankea el pool por el combinador. Brazos:
  - full_history: ajusta sobre TODA la experiencia (stale bajo drift -- mezcla bumps de fases distintas).
  - decay:        ajusta con pesos decay^(antigüedad) (olvida lo viejo, reusa CYCLE 73).
  - oracle:       rankea por el value REAL actual (techo).
  - chance:       orden aleatorio.
Perf = perf_of(top-k_eval por el combinador, value actual). Promedio sobre rondas (saltando el warmup).

PREGUNTA FALSABLE (crossover, cf. CYCLE 73):
  - APOYADA si bajo DRIFT decay >> full_history (+>0.05; el full es stale) Y bajo ESTACIONARIO full_history >= decay
    (−tol; el decay paga el costo de olvidar). => el combinador R-VALOR de asignación DEBE olvidar bajo no-estacionariedad,
    unificando el arco allocation (83-96) con el arco forgetting (58-74).
  - REFUTADA si bajo drift decay ≈ full_history (olvidar no aporta) o full nunca se degrada.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp081_nonstationary_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp081_nonstationary_value.run            # FULL
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
ARMS = ["full_history", "decay", "oracle", "chance"]
REGIMES = ["stationary", "drift"]
REGIME_ID = {"stationary": 0, "drift": 1}
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
SIGMA = 0.25


def _feats(c, r):
    c = np.asarray(c); r = np.asarray(r)
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _wridge(c_obs, r_obs, y, w, alpha):
    X = _feats(c_obs, r_obs)
    W = np.asarray(w)
    A = (X * W[:, None]).T @ X + alpha * np.eye(X.shape[1])
    b = (X * W[:, None]).T @ np.asarray(y)
    return np.linalg.solve(A, b)


def _score(c, r, wv):
    return _feats(c, r) @ wv


def _value(c, r, mu, nu):
    return np.exp(-(((c - mu) ** 2) + ((r - nu) ** 2)) / (2.0 * SIGMA ** 2))


def perf_of(picks, v):
    k = len(picks)
    best = np.sort(v)[-k:].sum()
    got = v[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _center(phase_rng):
    return float(phase_rng.random()), float(phase_rng.random())


def run_cell(n, T, D, warmup, k_obs, k_eval, decay, regime, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 2711 + REGIME_ID[regime] * 53 + 11)
        phase_rng = np.random.default_rng(seed * 99 + REGIME_ID[regime] * 7)
        mu, nu = _center(phase_rng)
        bc, br, by, bt = [], [], [], []
        per = {a: [] for a in ARMS}
        for t in range(T):
            if regime == "drift" and t > 0 and t % D == 0:
                mu, nu = _center(phase_rng)            # el valor se mueve
            c = rng.random(n); r = rng.random(n)
            val = _value(c, r, mu, nu)
            # observar k_obs al azar (feedback insesgado) -> acumular
            sel = rng.choice(n, size=min(k_obs, n), replace=False)
            for i in sel:
                bc.append(c[i]); br.append(r[i]); by.append(val[i]); bt.append(t)
            if len(by) >= MIN_FIT:
                wv_full = _wridge(bc, br, by, np.ones(len(by)), RIDGE_ALPHA)
                age = t - np.asarray(bt)
                wv_dec = _wridge(bc, br, by, np.power(decay, age), RIDGE_ALPHA)
            else:
                wv_full = wv_dec = None
            if t >= warmup:
                jit = 1e-9 * rng.random(n)
                sf = _score(c, r, wv_full) if wv_full is not None else c * r
                sd = _score(c, r, wv_dec) if wv_dec is not None else c * r
                per["full_history"].append(perf_of(np.argsort(sf + jit)[-k_eval:], val))
                per["decay"].append(perf_of(np.argsort(sd + jit)[-k_eval:], val))
                per["oracle"].append(perf_of(np.argsort(val + jit)[-k_eval:], val))
                per["chance"].append(perf_of(rng.choice(n, size=k_eval, replace=False), val))
        for a in ARMS:
            if per[a]:
                acc[a].append(float(np.mean(per[a])))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, T, D, warmup, k_obs, k_eval, decay, n_seeds):
    return {reg: run_cell(n, T, D, warmup, k_obs, k_eval, decay, reg, n_seeds) for reg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    st, dr = grid["stationary"], grid["drift"]
    drift_gain = round(dr["decay"] - dr["full_history"], 4)            # >0 esperado (decay rastrea el drift)
    stat_cost = round(st["full_history"] - st["decay"], 4)            # >=0 esperado (decay paga el costo de olvidar)
    full_degrades = round(st["full_history"] - dr["full_history"], 4)  # >0 esperado (el full cae con drift)
    decay_oracle_gap_dr = round(dr["oracle"] - dr["decay"], 4)

    DRIFT_THR = 0.05
    STAT_TOL = 0.03

    decay_wins_drift = drift_gain > DRIFT_THR
    full_ok_stat = stat_cost >= -STAT_TOL          # full no es PEOR que decay en estacionario (puede igualar o ganar)

    if decay_wins_drift and full_ok_stat:
        status = "apoyada"
        verdict = ("H-V4-8c APOYADA: el combinador R-VALOR de asignación DEBE OLVIDAR bajo no-estacionariedad. Bajo DRIFT "
                   "(el valor se mueve) decay={dd} >> full_history={df} (+{dg}): el full se vuelve STALE (mezcla bumps de "
                   "fases distintas; cae de {fs} estacionario a {df} con drift, −{fd}) y el decay RASTREA (≈ oracle, gap "
                   "{og}). Bajo ESTACIONARIO full_history={fs} >= decay={ds} (costo de olvidar {sc}). => unifica el arco "
                   "de ASIGNACIÓN (83-96) con el de FORGETTING (58-74): el estimador de valor (qué vale) y el olvido "
                   "(cuándo dejó de valer) son la misma señal en dos tiempos también para la asignación, no sólo para la "
                   "memoria.").format(dd=_f(dr["decay"]), df=_f(dr["full_history"]), dg=_f(drift_gain),
                                      fs=_f(st["full_history"]), fd=_f(full_degrades), og=_f(decay_oracle_gap_dr),
                                      ds=_f(st["decay"]), sc=_f(stat_cost))
    elif not decay_wins_drift:
        status = "refutada"
        verdict = ("H-V4-8c REFUTADA: bajo drift olvidar NO aporta (decay={dd} vs full={df}, +{dg} <= {thr}) -> el "
                   "combinador no necesita olvido aquí (o el full no se degrada).").format(
                       dd=_f(dr["decay"]), df=_f(dr["full_history"]), dg=_f(drift_gain), thr=DRIFT_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-8c MIXTA: decay_wins_drift={dw} (+{dg}) full_ok_stat={fo} (costo estacionario {sc}).").format(
                       dw=decay_wins_drift, dg=_f(drift_gain), fo=full_ok_stat, sc=_f(stat_cost))

    return {"grid": grid, "drift_gain": drift_gain, "stat_cost": stat_cost, "full_degrades": full_degrades,
            "decay_oracle_gap_drift": decay_oracle_gap_dr, "decay_wins_drift": bool(decay_wins_drift),
            "full_ok_stat": bool(full_ok_stat), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--T", type=int, default=40)
    ap.add_argument("--D", type=int, default=8)
    ap.add_argument("--warmup", type=int, default=4)
    ap.add_argument("--k_obs", type=int, default=10)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--decay", type=float, default=0.8)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp081] CYCLE 97 / H-V4-8c — no-estacionariedad en la asignación: ¿el combinador R-VALOR debe olvidar?")
    log(f"[exp081] n={args.n} T={args.T} D={args.D} warmup={args.warmup} k_obs={args.k_obs} k_eval={args.k_eval} "
        f"decay={args.decay} sigma={SIGMA} seeds={args.seeds} regimes={REGIMES}")

    grid = run(args.n, args.T, args.D, args.warmup, args.k_obs, args.k_eval, args.decay, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        c = grid[reg]
        log(f"[exp081] {reg:>10}: full_history={c['full_history']:.3f} decay={c['decay']:.3f} oracle={c['oracle']:.3f} chance={c['chance']:.3f}")
    log(f"[exp081] drift_gain(decay−full)=+{sm['drift_gain']:.3f} | stat_cost(full−decay)={sm['stat_cost']:+.3f} | "
        f"full_degrades(stat−drift)={sm['full_degrades']:.3f} | decay_oracle_gap_drift={sm['decay_oracle_gap_drift']:.3f}")
    log(f"[exp081] decay_wins_drift={sm['decay_wins_drift']} full_ok_stat={sm['full_ok_stat']}")
    log(f"[exp081] VEREDICTO H-V4-8c: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp081_nonstationary_value", "cycle": 97, "hypothesis": "H-V4-8c",
           "claim": "bajo no-estacionariedad (drift de la estructura del valor) el combinador R-VALOR de asignacion debe "
                    "OLVIDAR (decay): el full-history se vuelve stale y falla, el decay rastrea -> unifica el arco de "
                    "asignacion (83-96) con el arco de forgetting (58-74)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp081] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

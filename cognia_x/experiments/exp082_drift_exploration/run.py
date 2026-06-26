r"""
exp082 — CYCLE 98 / H-V4-7k (rama R-VALOR/R-INTERVENCIÓN, REVIERTE CYCLE 87-88 bajo no-estacionariedad): CYCLE 87-88
REFUTARON la necesidad de explorar (la explotación GREEDY del prior bastaba) bajo feedback ACTION-GATED -- pero SIEMPRE
en régimen ESTACIONARIO. CYCLE 97 mostró que el valor DERIVA. ¿Bajo action-gated + DRIFT, el greedy se ATRAPA (explota un
combinador STALE del viejo 'buen barrio', nunca re-observa el valor que se movió) y la EXPLORACIÓN RESCATA -- revirtiendo
87-88 y haciendo que R-INTERVENCIÓN por fin LIGUE?

CONTEXTO. 87-88: greedy ≈ random insesgado (no trap) -> exploración innecesaria, R-INTERVENCIÓN NO liga. PERO ítems
frescos/estacionario. 97: el combinador debe OLVIDAR bajo drift. Aquí se combina lo crítico: feedback ACTION-GATED (sólo
observás el valor de lo que SELECCIONÁS) + DRIFT (el valor se mueve). Bajo greedy, el combinador (incluso con decay) sólo
ve la región que el greedy SELECCIONA -> si esa región era buena y el valor se mudó, greedy sigue seleccionando ahí,
observa valor BAJO, y NUNCA observa la región nueva -> el decay no puede rastrear lo que no se observa -> TRAP. La
exploración observa la región nueva -> el combinador la descubre -> rastrea.

DISEÑO (numpy, online; combina exp081 drift + exp071/087 action-gating). Valor = bump gaussiano; centro fijo
(estacionario) o que se mueve cada D rondas (drift). El agente SELECCIONA k_obs ítems para OBSERVAR su valor (action-gated),
acumula, ajusta ridge poly2 con DECAY (per CYCLE 97). Estrategias de selección:
  - greedy:  top-k_obs por el combinador (explota; stale bajo drift).
  - explore: ε-greedy (parte al azar -> observa otras regiones).
  - random:  k_obs al azar (insesgado; siempre observa todo el espacio, = feedback libre).
  - oracle:  rankea por el valor REAL (techo).
EVAL: rank del pool por el combinador final de cada estrategia, perf_of vs valor actual, promedio sobre rondas.

Se BARRE k_obs (amplitud de observación) -- el trap es CONDICIONAL a observación ESTRECHA (como CYCLE 88 con la
concentración): a k_obs chico el greedy re-observa siempre el viejo barrio; a k_obs amplio observa lo suficiente para
auto-corregir.

PREGUNTA FALSABLE (reversión CONDICIONAL de 87-88):
  - APOYADA si bajo DRIFT a k_obs ESTRECHO el greedy se ATRAPA (random − greedy > 0.05) Y la exploración RESCATA
    (explore − greedy > 0.05), MIENTRAS a k_obs AMPLIO el greedy es robusto (no trap) y bajo ESTACIONARIO no atrapa a
    ningún k_obs (reproduce 87-88). => la exploración (R-INTERVENCIÓN) es necesaria bajo NO-estacionariedad + observación
    ESTRECHA; 87-88 era específico de la estacionariedad (o de observación amplia).
  - REFUTADA si bajo drift el greedy NO se atrapa a ningún k_obs (87-88 generaliza del todo).
  - MIXTA en otro caso (p.ej. atrapa pero la exploración no rescata a ningún k_obs).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp082_drift_exploration.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp082_drift_exploration.run            # FULL
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
ARMS = ["greedy", "explore", "random", "oracle"]
STRATS = ["greedy", "explore", "random"]
STRAT_ID = {"greedy": 0, "explore": 1, "random": 2}
REGIMES = ["stationary", "drift"]
REGIME_ID = {"stationary": 0, "drift": 1}
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
SIGMA = 0.25
K_OBS_LIST = [1, 2, 4, 8]
NARROW_KOBS = 2          # punto de observación estrecha donde se evalúa el trap/rescate
WIDE_KOBS = 8            # observación amplia: control de robustez (87-88)


def _feats(c, r):
    c = np.asarray(c); r = np.asarray(r)
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _wridge(c_obs, r_obs, y, w, alpha):
    X = _feats(c_obs, r_obs)
    W = np.asarray(w)
    A = (X * W[:, None]).T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, (X * W[:, None]).T @ np.asarray(y))


def _score(c, r, wv):
    return _feats(c, r) @ wv


def _value(c, r, mu, nu):
    return np.exp(-(((c - mu) ** 2) + ((r - nu) ** 2)) / (2.0 * SIGMA ** 2))


def perf_of(picks, v):
    k = len(picks)
    best = np.sort(v)[-k:].sum()
    got = v[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _select(c, r, wv, k, strat, eps, rng):
    n = len(c)
    if strat == "random" or wv is None:
        return rng.choice(n, size=min(k, n), replace=False)
    order = np.argsort(_score(c, r, wv) + 1e-9 * rng.random(n))[::-1]
    if strat == "explore":
        n_exp = int(round(eps * k))
        top = list(order[:k - n_exp])
        rest = [i for i in order if i not in set(top)]
        return np.array(top + list(rng.permutation(rest)[:n_exp]), dtype=int)
    return order[:k]


def run_cell(n, T, D, warmup, k_obs, k_eval, decay, eps, regime, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        phase_rng = np.random.default_rng(seed * 99 + REGIME_ID[regime] * 7)
        mu0, nu0 = float(phase_rng.random()), float(phase_rng.random())
        per = {a: [] for a in ARMS}
        for strat in STRATS:
            rng = np.random.default_rng(seed * 2087 + REGIME_ID[regime] * 997 + STRAT_ID[strat] * 41)
            ph = np.random.default_rng(seed * 99 + REGIME_ID[regime] * 7)   # misma secuencia de centros por seed/regime
            mu, nu = mu0, nu0
            bc, br, by, bt = [], [], [], []
            wv = None
            for t in range(T):
                if regime == "drift" and t > 0 and t % D == 0:
                    mu, nu = float(ph.random()), float(ph.random())
                c = rng.random(n); r = rng.random(n)
                val = _value(c, r, mu, nu)
                sel = _select(c, r, wv, k_obs, strat, eps, rng)        # ACTION-GATED: observa sólo lo seleccionado
                for i in sel:
                    bc.append(c[i]); br.append(r[i]); by.append(val[i]); bt.append(t)
                if len(by) >= MIN_FIT:
                    wv = _wridge(bc, br, by, np.power(decay, t - np.asarray(bt)), RIDGE_ALPHA)
                if t >= warmup:
                    jit = 1e-9 * rng.random(n)
                    s = _score(c, r, wv) if wv is not None else c * r
                    per[strat].append(perf_of(np.argsort(s + jit)[-k_eval:], val))
                    if strat == "greedy":
                        per["oracle"].append(perf_of(np.argsort(val + jit)[-k_eval:], val))
        for a in ARMS:
            if per[a]:
                acc[a].append(float(np.mean(per[a])))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, T, D, warmup, k_eval, decay, eps, n_seeds):
    grid = {}
    for reg in REGIMES:
        for ko in K_OBS_LIST:
            grid["{}_kobs{}".format(reg, ko)] = run_cell(n, T, D, warmup, ko, k_eval, decay, eps, reg, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    nd = grid["drift_kobs{}".format(NARROW_KOBS)]
    wd = grid["drift_kobs{}".format(WIDE_KOBS)]
    ns = grid["stationary_kobs{}".format(NARROW_KOBS)]

    drift_trap = round(nd["random"] - nd["greedy"], 4)        # >0.05: greedy se atrapa a k_obs estrecho bajo drift
    drift_rescue = round(nd["explore"] - nd["greedy"], 4)     # >0.05: explore rescata
    wide_trap = round(wd["random"] - wd["greedy"], 4)         # <=0.05: a k_obs amplio NO atrapa (robusto, 87-88)
    stat_trap = round(ns["random"] - ns["greedy"], 4)        # <=0.05: estacionario NO atrapa (87-88)
    trap_kobs = None                                          # mayor k_obs donde el drift atrapa
    for ko in K_OBS_LIST:
        if (grid["drift_kobs{}".format(ko)]["random"] - grid["drift_kobs{}".format(ko)]["greedy"]) > 0.05:
            trap_kobs = ko

    TRAP_THR = 0.05
    drift_traps = drift_trap > TRAP_THR
    explore_rescues = drift_rescue > TRAP_THR
    wide_robust = wide_trap <= TRAP_THR
    stat_robust = stat_trap <= TRAP_THR

    if drift_traps and explore_rescues and wide_robust and stat_robust:
        status = "apoyada"
        verdict = ("H-V4-7k APOYADA (REVIERTE 87-88 CONDICIONALMENTE): bajo DRIFT + observación ESTRECHA (k_obs={nk}) el "
                   "greedy se ATRAPA -- greedy={dg} << random insesgado={dr} (gap {dt}>0.05): explota un combinador STALE "
                   "del viejo 'buen barrio' y re-observa siempre la misma región estrecha (el decay no rastrea lo que no "
                   "se observa). La EXPLORACIÓN RESCATA: explore={de} > greedy (+{drr}). PERO a observación AMPLIA "
                   "(k_obs={wk}) el greedy es ROBUSTO (gap {wt}<=0.05: observa lo suficiente para auto-corregir) y bajo "
                   "ESTACIONARIO no atrapa a k_obs estrecho (gap {st}<=0.05: reproduce 87-88). Umbral de trap k_obs*<={tk}. "
                   "=> la exploración (R-INTERVENCIÓN) es NECESARIA bajo NO-estacionariedad + observación ESTRECHA; el "
                   "'exploración innecesaria' de 87-88 era específico de la estacionariedad O de observación amplia. "
                   "R-INTERVENCIÓN LIGA finalmente -- pero condicionado, como el trap de CYCLE 88.").format(
                       nk=NARROW_KOBS, dg=_f(nd["greedy"]), dr=_f(nd["random"]), dt=_f(drift_trap), de=_f(nd["explore"]),
                       drr=_f(drift_rescue), wk=WIDE_KOBS, wt=_f(wide_trap), st=_f(stat_trap), tk=trap_kobs)
    elif not drift_traps:
        status = "refutada"
        verdict = ("H-V4-7k REFUTADA: bajo drift el greedy NO se atrapa ni a k_obs estrecho (greedy={dg} ≈ random={dr}, "
                   "gap {dt}<=0.05) -> el 'exploración innecesaria' de 87-88 GENERALIZA también a no-estacionariedad.").format(
                       dg=_f(nd["greedy"]), dr=_f(nd["random"]), dt=_f(drift_trap))
    else:
        status = "mixta"
        verdict = ("H-V4-7k MIXTA: a k_obs estrecho drift_traps={dt}(gap {dtv}) pero explore_rescues={er}(+{drr}); "
                   "wide_robust={wr} stat_robust={sr}. La reversión es parcial (p.ej. atrapa pero la exploración no "
                   "rescata, o no es claramente condicional).").format(
                       dt=drift_traps, dtv=_f(drift_trap), er=explore_rescues, drr=_f(drift_rescue),
                       wr=wide_robust, sr=stat_robust)

    return {"grid": grid, "narrow_kobs": NARROW_KOBS, "wide_kobs": WIDE_KOBS, "drift_trap": drift_trap,
            "drift_rescue": drift_rescue, "wide_trap": wide_trap, "stat_trap": stat_trap, "trap_kobs": trap_kobs,
            "drift_traps": bool(drift_traps), "explore_rescues": bool(explore_rescues), "wide_robust": bool(wide_robust),
            "stat_robust": bool(stat_robust), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--T", type=int, default=40)
    ap.add_argument("--D", type=int, default=8)
    ap.add_argument("--warmup", type=int, default=4)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--decay", type=float, default=0.8)
    ap.add_argument("--eps", type=float, default=0.4)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp082] CYCLE 98 / H-V4-7k — ¿la exploración (R-INTERVENCIÓN) LIGA bajo drift action-gated? (revierte 87-88, condicional a k_obs)")
    log(f"[exp082] n={args.n} T={args.T} D={args.D} warmup={args.warmup} k_obs_sweep={K_OBS_LIST} k_eval={args.k_eval} "
        f"decay={args.decay} eps={args.eps} sigma={SIGMA} seeds={args.seeds} regimes={REGIMES}")

    grid = run(args.n, args.T, args.D, args.warmup, args.k_eval, args.decay, args.eps, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        for ko in K_OBS_LIST:
            c = grid["{}_kobs{}".format(reg, ko)]
            gp = c["random"] - c["greedy"]
            log(f"[exp082] {reg:>10} k_obs={ko}: greedy={c['greedy']:.3f} explore={c['explore']:.3f} "
                f"random={c['random']:.3f} oracle={c['oracle']:.3f} (random−greedy={gp:+.3f})")
    log(f"[exp082] @k_obs={sm['narrow_kobs']} (estrecho): drift_trap=+{sm['drift_trap']:.3f} drift_rescue=+{sm['drift_rescue']:.3f} | "
        f"@k_obs={sm['wide_kobs']} (amplio): wide_trap={sm['wide_trap']:+.3f} | stat_trap={sm['stat_trap']:+.3f} | trap_kobs*<={sm['trap_kobs']}")
    log(f"[exp082] drift_traps={sm['drift_traps']} explore_rescues={sm['explore_rescues']} wide_robust={sm['wide_robust']} stat_robust={sm['stat_robust']}")
    log(f"[exp082] VEREDICTO H-V4-7k: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp082_drift_exploration", "cycle": 98, "hypothesis": "H-V4-7k",
           "claim": "bajo feedback action-gated + DRIFT del valor, la explotacion greedy se atrapa (combinador stale del "
                    "viejo buen barrio, nunca re-observa el valor movido) y la exploracion rescata -> revierte el "
                    "'exploracion innecesaria' de 87-88 (especifico de la estacionariedad); R-INTERVENCION liga bajo drift",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp082] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

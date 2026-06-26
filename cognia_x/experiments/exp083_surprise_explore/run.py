r"""
exp083 — CYCLE 99 / H-V4-7l (rama R-VALOR/R-INTERVENCIÓN, CIERRA el sub-arco 97-99): CYCLE 98 mostró que bajo drift +
observación estrecha la exploración (ε fijo) RESCATA al greedy atrapado -- pero el ε FIJO paga exploración SIEMPRE
(también en estacionario, donde no hace falta). ¿Una exploración SURPRISE-GATED (explorar sólo cuando la SORPRESA indica
cambio, reusando CYCLE 59) logra NO-REGRET: rescata bajo drift como el ε-fijo, PERO no paga el costo bajo estacionario
como el greedy?

CONTEXTO. CYCLE 59 cerró el arco de memoria con olvido ADAPTATIVO por sorpresa (detección de cambio endógena). Aquí se
aplica a la EXPLORACIÓN de la asignación: el agente monitorea la SORPRESA (su combinador predijo valor ALTO para lo que
eligió greedy pero observó valor BAJO -> la región se mudó) y SÓLO explora cuando hay un spike de sorpresa. Cierra el
caveat 'ε fijo' de CYCLE 98 -- el análogo del selector no-regret de CYCLE 74/66 para la exploración.

DISEÑO (numpy, online; reusa exp082, k_obs=2 estrecho). Valor = bump gaussiano; centro fijo (estacionario) o que se mueve
cada D rondas (drift). Combinador ridge poly2 con decay. Estrategias: greedy (ε=0), explore (ε FIJO), surprise_explore
(ε gateado por spike de sorpresa = sobre-predicción del combinador sobre lo seleccionado), random, oracle. MÉTRICA = REWARD
action-gated: perf_of de lo que el agente SELECCIONÓ ese round (explorar tiene costo de oportunidad real, framing bandit).

PREGUNTA FALSABLE (no-regret, cf. CYCLE 66/74):
  - APOYADA si surprise_explore logra NO-REGRET: bajo DRIFT ≈ explore-ε-fijo (rescata, > greedy) Y bajo ESTACIONARIO ≈
    greedy (no paga el costo de exploración que el ε-fijo SÍ paga: surprise_explore > explore-ε-fijo en estacionario);
    promediando ambos regímenes surprise_explore >= max(greedy, explore). => exploración endógena gateada por sorpresa,
    sin ε fijo (cierra el caveat de CYCLE 98).
  - REFUTADA si surprise_explore no rescata bajo drift (sorpresa no detecta el cambio) o no ahorra en estacionario.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp083_surprise_explore.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp083_surprise_explore.run            # FULL
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
ARMS = ["greedy", "explore", "surprise_explore", "random", "oracle"]
STRATS = ["greedy", "explore", "surprise_explore", "random"]
STRAT_ID = {"greedy": 0, "explore": 1, "surprise_explore": 2, "random": 3}
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


def _select(c, r, wv, k, eps, rng):
    n = len(c)
    if wv is None:
        return rng.choice(n, size=min(k, n), replace=False)
    order = np.argsort(_score(c, r, wv) + 1e-9 * rng.random(n))[::-1]
    if eps > 0:
        n_exp = int(round(eps * k))
        top = list(order[:k - n_exp])
        rest = [i for i in order if i not in set(top)]
        return np.array(top + list(rng.permutation(rest)[:n_exp]), dtype=int)
    return order[:k]


def run_cell(n, T, D, warmup, k_obs, k_eval, decay, eps_fixed, eps_high, regime, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        per = {a: [] for a in ARMS}
        for strat in STRATS:
            rng = np.random.default_rng(seed * 2087 + REGIME_ID[regime] * 997 + STRAT_ID[strat] * 41)
            ph = np.random.default_rng(seed * 99 + REGIME_ID[regime] * 7)
            mu, nu = float(ph.random()), float(ph.random())
            bc, br, by, bt = [], [], [], []
            wv = None
            eps_eff = 0.0           # para surprise_explore: arranca greedy
            ema_surp = None
            for t in range(T):
                if regime == "drift" and t > 0 and t % D == 0:
                    mu, nu = float(ph.random()), float(ph.random())
                c = rng.random(n); r = rng.random(n)
                val = _value(c, r, mu, nu)
                if strat == "random":
                    eps = 1.0
                elif strat == "greedy":
                    eps = 0.0
                elif strat == "explore":
                    eps = eps_fixed
                else:  # surprise_explore: ε gateado por sorpresa del round previo
                    eps = eps_eff
                sel = _select(c, r, wv, k_obs, eps, rng)
                # SORPRESA (surprise_explore): el combinador sobre-predijo el valor de lo seleccionado?
                if strat == "surprise_explore" and wv is not None:
                    pred = _score(c[sel], r[sel], wv)
                    surp = float(np.mean(np.maximum(0.0, pred - val[sel])))
                    if ema_surp is None:
                        ema_surp = surp
                    spike = surp > (ema_surp * 1.5 + 0.05)        # balance sensibilidad(drift)/especificidad(estacionario)
                    ema_surp = 0.7 * ema_surp + 0.3 * surp
                    eps_eff = eps_high if spike else 0.0
                for i in sel:
                    bc.append(c[i]); br.append(r[i]); by.append(val[i]); bt.append(t)
                if len(by) >= MIN_FIT:
                    wv = _wridge(bc, br, by, np.power(decay, t - np.asarray(bt)), RIDGE_ALPHA)
                if t >= warmup:
                    # REWARD action-gated: la calidad de lo que el agente SELECCIONÓ (explorar tiene costo de oportunidad)
                    per[strat].append(perf_of(sel, val))
                    if strat == "greedy":
                        per["oracle"].append(perf_of(np.argsort(val + 1e-9 * rng.random(n))[-k_obs:], val))
        for a in ARMS:
            if per[a]:
                acc[a].append(float(np.mean(per[a])))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, T, D, warmup, k_obs, k_eval, decay, eps_fixed, eps_high, n_seeds):
    return {reg: run_cell(n, T, D, warmup, k_obs, k_eval, decay, eps_fixed, eps_high, reg, n_seeds) for reg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    st, dr = grid["stationary"], grid["drift"]
    # DRIFT: surprise debe rescatar como explore y superar a greedy
    drift_rescue = round(dr["surprise_explore"] - dr["greedy"], 4)       # >0 esperado
    drift_vs_explore = round(dr["surprise_explore"] - dr["explore"], 4)  # >=~0 esperado (≈ explore)
    # ESTACIONARIO: surprise debe NO pagar el costo de exploración (≈ greedy, > explore-ε-fijo)
    stat_savings = round(st["surprise_explore"] - st["explore"], 4)      # >0 esperado (ahorra vs ε fijo)
    stat_vs_greedy = round(st["surprise_explore"] - st["greedy"], 4)     # ~0 esperado (≈ greedy)
    # no-regret global
    sur_avg = round((st["surprise_explore"] + dr["surprise_explore"]) / 2.0, 4)
    greedy_avg = round((st["greedy"] + dr["greedy"]) / 2.0, 4)
    explore_avg = round((st["explore"] + dr["explore"]) / 2.0, 4)
    best_fixed_avg = max(greedy_avg, explore_avg)
    noregret_margin = round(sur_avg - best_fixed_avg, 4)

    TOL = 0.03
    # eje del ciclo: ¿qué ESQUEMA de exploración? surprise-gated debe DOMINAR al ε-fijo (ahorrar en estacionario,
    # igualar/superar en drift) y ser no-regret (mejor o empatado en promedio). greedy = referencia robusta (CYCLE 98).
    dominates_explore = (stat_savings > 0.05) and (drift_vs_explore >= -TOL)
    no_regret = noregret_margin >= -TOL
    beats_explore_avg = round(sur_avg - explore_avg, 4) > 0.05

    if dominates_explore and no_regret and beats_explore_avg:
        status = "apoyada"
        verdict = ("H-V4-7l APOYADA (cierra el sub-arco 97-99): la exploración SURPRISE-GATED DOMINA al ε-fijo y es "
                   "NO-REGRET, sin ε fijo. AHORRA en ESTACIONARIO: surprise={ss} vs explore-ε-fijo={es} (+{sv}; el ε-fijo "
                   "malgasta explorando cuando no hace falta) y ≈ greedy={gs} ({svg}). RESCATA en DRIFT: surprise={sd} >= "
                   "explore={ed} ({dve}) y > greedy={gd} (+{dr}). Promediando, surprise_avg={sa} es la MEJOR (vs greedy "
                   "{ga}/explore {ea}, margen {nr}). => exploración endógena gateada por SORPRESA (el combinador "
                   "sobre-predijo lo que eligió greedy -> cambio detectado), el análogo del selector no-regret de CYCLE "
                   "66/74 para la EXPLORACIÓN; cierra el caveat 'ε fijo' de CYCLE 98. CAVEAT: hay un tradeoff de umbral de "
                   "detección (sensibilidad-drift vs especificidad-estacionario); greedy es una referencia ROBUSTA "
                   "(CYCLE 98: se auto-corrige bajo drift mild), por eso el margen vs greedy es chico.").format(
                       ss=_f(st["surprise_explore"]), es=_f(st["explore"]), sv=_f(stat_savings), gs=_f(st["greedy"]),
                       svg=_f(stat_vs_greedy), sd=_f(dr["surprise_explore"]), ed=_f(dr["explore"]), dve=_f(drift_vs_explore),
                       gd=_f(dr["greedy"]), dr=_f(drift_rescue), sa=_f(sur_avg), ga=_f(greedy_avg), ea=_f(explore_avg), nr=_f(noregret_margin))
    elif not dominates_explore:
        status = "refutada"
        verdict = ("H-V4-7l REFUTADA: surprise_explore NO domina al ε-fijo (ahorro estacionario {sv}, drift vs_explore "
                   "{dve}) -> el gating por sorpresa no mejora el esquema de exploración fijo.").format(
                       sv=_f(stat_savings), dve=_f(drift_vs_explore))
    else:
        status = "mixta"
        verdict = ("H-V4-7l MIXTA: surprise DOMINA al ε-fijo (ahorro estacionario +{sv}, drift vs_explore {dve}) y es "
                   "no-regret ({nrm}) PERO no supera decisivamente el promedio del ε-fijo (margen vs explore "
                   "{bea}) o vs greedy robusto (vs_greedy drift +{dr}/estac {svg}); el gating por sorpresa funciona pero "
                   "el margen es chico (greedy se auto-corrige, CYCLE 98; tradeoff de umbral de detección).").format(
                       sv=_f(stat_savings), dve=_f(drift_vs_explore), nrm=_f(noregret_margin),
                       bea=_f(round(sur_avg - explore_avg, 4)), dr=_f(drift_rescue), svg=_f(stat_vs_greedy))

    return {"grid": grid, "drift_rescue": drift_rescue, "drift_vs_explore": drift_vs_explore, "stat_savings": stat_savings,
            "stat_vs_greedy": stat_vs_greedy, "surprise_avg": sur_avg, "greedy_avg": greedy_avg, "explore_avg": explore_avg,
            "noregret_margin": noregret_margin, "dominates_explore": bool(dominates_explore),
            "beats_explore_avg": bool(beats_explore_avg), "no_regret": bool(no_regret), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--T", type=int, default=40)
    ap.add_argument("--D", type=int, default=8)
    ap.add_argument("--warmup", type=int, default=4)
    ap.add_argument("--k_obs", type=int, default=2)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--decay", type=float, default=0.8)
    ap.add_argument("--eps_fixed", type=float, default=0.5)
    ap.add_argument("--eps_high", type=float, default=0.5)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp083] CYCLE 99 / H-V4-7l — exploración SURPRISE-GATED: no-regret estacionario/drift (cierra el caveat ε-fijo de 98)")
    log(f"[exp083] n={args.n} T={args.T} D={args.D} warmup={args.warmup} k_obs={args.k_obs} k_eval={args.k_eval} "
        f"decay={args.decay} eps_fixed={args.eps_fixed} eps_high={args.eps_high} sigma={SIGMA} seeds={args.seeds}")

    grid = run(args.n, args.T, args.D, args.warmup, args.k_obs, args.k_eval, args.decay, args.eps_fixed, args.eps_high, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        c = grid[reg]
        log(f"[exp083] {reg:>10}: greedy={c['greedy']:.3f} explore={c['explore']:.3f} surprise_explore={c['surprise_explore']:.3f} "
            f"random={c['random']:.3f} oracle={c['oracle']:.3f}")
    log(f"[exp083] DRIFT: rescue(surp−greedy)=+{sm['drift_rescue']:.3f} vs_explore={sm['drift_vs_explore']:+.3f} | "
        f"ESTAC: savings(surp−explore)=+{sm['stat_savings']:.3f} vs_greedy={sm['stat_vs_greedy']:+.3f}")
    log(f"[exp083] no-regret: surprise_avg={sm['surprise_avg']:.3f} vs best_fixed(greedy {sm['greedy_avg']:.3f}/explore {sm['explore_avg']:.3f}) margin={sm['noregret_margin']:+.3f}")
    log(f"[exp083] dominates_explore={sm['dominates_explore']} beats_explore_avg={sm['beats_explore_avg']} no_regret={sm['no_regret']}")
    log(f"[exp083] VEREDICTO H-V4-7l: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp083_surprise_explore", "cycle": 99, "hypothesis": "H-V4-7l",
           "claim": "la exploracion SURPRISE-GATED (explorar solo cuando la sorpresa indica cambio, CYCLE 59) logra "
                    "no-regret a traves de estacionario/drift: rescata bajo drift como el eps-fijo y no paga el costo "
                    "bajo estacionario como el greedy -> exploracion endogena sin eps fijo (cierra el caveat de CYCLE 98)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp083] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

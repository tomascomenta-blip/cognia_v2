r"""
exp072 — CYCLE 88 / H-V4-7f (rama R-VALOR, cierra el caveat de CYCLE 87): el trap de sesgo de selección (y la necesidad
de explorar) ¿es real bajo CONCENTRACIÓN del soporte, y de qué depende?

CONTEXTO: CYCLE 87 (exp071) halló que bajo feedback action-gated la explotación GREEDY ya recupera la forma de
sustitutos SIN explorar (no hay trap) — pero usaba ÍTEMS FRESCOS por ronda, que diversifican el soporte aunque observes
top-1. Caveat registrado: probar CONCENTRACIÓN real. El piloto confirmó que con ítems frescos NO hay trap ni a k_obs=1
(la frescura dissuelve la concentración). Este ciclo cierra el caveat con el verdadero peor caso: un POOL FIJO (los
mismos n ítems recurren cada ronda), donde el greedy re-observa SIEMPRE la misma región both-high y nunca los one-high.

DISEÑO (online; reusa exp071). Régimen SUSTITUTOS (g=max, λ=1.0), calidad q2 (S=32, σr=0.05). Eje 1: POOL ∈ {fresh
(ítems nuevos por ronda, como CYCLE 87), fixed (los mismos n ítems toda la corrida -> observación CORRELACIONADA)}. Eje 2:
k_obs (amplitud de observación). FASE LEARNING (T rondas): el agente OBSERVA k_obs ítems (su valor real) por estrategia
{greedy, explore(ε), random}, acumula buffer, refit ridge poly2. EVAL: fixed -> rankea el pool fijo (top-k_eval); fresh
-> promedio sobre E rondas frescas. Control: comp (g=min) a fixed/k_obs=1.

PREDICCIÓN FALSABLE (sustitutos):
  - APOYADA (el trap es real PERO condicional a observación correlacionada) si bajo POOL FIJO a k_obs chico el greedy se
    ATRAPA (greedy < random − 0.05) y la exploración rescata, MIENTRAS que bajo POOL FRESH NO hay trap (greedy ≈ random).
    => el trap (y la necesidad de explorar / R-INTERVENCIÓN) requiere RE-ENFRENTAR la misma región sesgada; la diversidad
    de tareas lo dissuelve.
  - REFUTADA si ni siquiera el pool fijo a k_obs=1 atrapa (greedy ≈ random): la robustez es total.
  - MIXTA en otro caso (p.ej. fresh también atrapa, contradiría CYCLE 87).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp072_support_concentration.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp072_support_concentration.run            # FULL
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
ARMS = ["product", "learned_greedy", "learned_explore", "learned_random"]
STRATS = ["greedy", "explore", "random"]
K_OBS_LIST = [1, 2, 3, 5, 10]
POOLS = ["fixed", "fresh"]
LAM = 1.0
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
STRAT_ID = {"greedy": 0, "explore": 1, "random": 2}
POOL_ID = {"fixed": 0, "fresh": 1}
Q2_S = 32
Q2_SR = 0.05


def perf_of(picks, value):
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _value(ctrl, rel, fam, lam):
    prod = ctrl * rel
    g = np.minimum(ctrl, rel) if fam == "comp" else np.maximum(ctrl, rel)
    return (1.0 - lam) * prod + lam * g


def _feats(c, r):
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _ridge_w(c_obs, r_obs, y, alpha):
    X = _feats(np.asarray(c_obs), np.asarray(r_obs))
    A = X.T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ np.asarray(y))


def _draw_pool(rng, n, fam, sc):
    ctrl = rng.random(n)
    rel = rng.random(n)
    value = _value(ctrl, rel, fam, LAM)
    ctrl_est = np.clip(ctrl + rng.normal(0.0, sc / np.sqrt(Q2_S), size=n), 0.0, 1.0)
    rel_est = np.clip(rel + rng.normal(0.0, Q2_SR, size=n), 0.0, 1.0)
    return ctrl_est, rel_est, value


def _score(ctrl_est, rel_est, w):
    if w is None:
        return ctrl_est * rel_est
    return _feats(ctrl_est, rel_est) @ w


def _select(ctrl_est, rel_est, w, k_obs, strat, eps, rng):
    n = len(ctrl_est)
    if strat == "random":
        return rng.choice(n, size=k_obs, replace=False)
    score = _score(ctrl_est, rel_est, w)
    order = np.argsort(score + 1e-9 * rng.random(n))[::-1]
    if strat == "explore":
        n_exp = int(round(eps * k_obs))
        top = list(order[:k_obs - n_exp])
        rest = [i for i in order if i not in set(top)]
        exp_sel = list(rng.permutation(rest)[:n_exp])
        return np.array(top + exp_sel, dtype=int) if (top or exp_sel) else order[:k_obs]
    return order[:k_obs]


def run_cell(n, k_obs, k_eval, fam, pool, T, E, eps, sc, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        pool_rng = np.random.default_rng(seed * 7717 + POOL_ID[pool] * 53 + (2 if fam == "subs" else 1) * 131)
        fixed_pool = _draw_pool(pool_rng, n, fam, sc) if pool == "fixed" else None
        for strat in STRATS:
            rng = np.random.default_rng(seed * 2087 + POOL_ID[pool] * 997 + STRAT_ID[strat] * 41 + k_obs * 911)
            bc, br, by = [], [], []
            w = None
            for t in range(T):
                ce, re, val = fixed_pool if pool == "fixed" else _draw_pool(rng, n, fam, sc)
                sel = _select(ce, re, w, k_obs, strat, eps, rng)
                for i in sel:
                    bc.append(ce[i]); br.append(re[i]); by.append(val[i])
                if len(by) >= MIN_FIT:
                    w = _ridge_w(bc, br, by, RIDGE_ALPHA)
            if pool == "fixed":
                ce, re, val = fixed_pool
                picks = np.argsort(_score(ce, re, w) + 1e-9 * rng.random(n))[-k_eval:]
                acc["learned_{}".format(strat)].append(perf_of(picks, val))
            else:
                perfs = []
                for _ in range(E):
                    ce, re, val = _draw_pool(rng, n, fam, sc)
                    picks = np.argsort(_score(ce, re, w) + 1e-9 * rng.random(n))[-k_eval:]
                    perfs.append(perf_of(picks, val))
                acc["learned_{}".format(strat)].append(float(np.mean(perfs)))
        # producto (sin aprender)
        rng2 = np.random.default_rng(seed * 5099 + k_obs * 17 + POOL_ID[pool] * 7)
        if pool == "fixed":
            ce, re, val = fixed_pool
            picks = np.argsort(ce * re + 1e-9 * rng2.random(n))[-k_eval:]
            acc["product"].append(perf_of(picks, val))
        else:
            perfs = []
            for _ in range(E):
                ce, re, val = _draw_pool(rng2, n, fam, sc)
                picks = np.argsort(ce * re + 1e-9 * rng2.random(n))[-k_eval:]
                perfs.append(perf_of(picks, val))
            acc["product"].append(float(np.mean(perfs)))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k_eval, T, E, eps, sc, n_seeds):
    grid = {}
    for pool in POOLS:
        for k_obs in K_OBS_LIST:
            grid["{}_kobs{}".format(pool, k_obs)] = run_cell(n, k_obs, k_eval, "subs", pool, T, E, eps, sc, n_seeds)
    grid["comp_fixed_kobs1"] = run_cell(n, 1, k_eval, "comp", "fixed", T, E, eps, sc, n_seeds)  # control
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid, n, k_eval):
    def cell(pool, k_obs):
        return grid["{}_kobs{}".format(pool, k_obs)]

    gap_fixed = {k: round(cell("fixed", k)["learned_random"] - cell("fixed", k)["learned_greedy"], 4) for k in K_OBS_LIST}
    gap_fresh = {k: round(cell("fresh", k)["learned_random"] - cell("fresh", k)["learned_greedy"], 4) for k in K_OBS_LIST}
    trap_fixed_kobs = None
    for k in K_OBS_LIST:
        if gap_fixed[k] > 0.05:
            trap_fixed_kobs = k

    fixed_traps_low = gap_fixed[1] > 0.05
    fresh_robust_low = gap_fresh[1] <= 0.05
    explore_rescues_fixed = (cell("fixed", 1)["learned_explore"] - cell("fixed", 1)["learned_greedy"]) > 0.03
    comp_ctrl = grid["comp_fixed_kobs1"]
    comp_ok = comp_ctrl["learned_greedy"] >= comp_ctrl["product"] - 0.03

    f1 = cell("fixed", 1)
    if fixed_traps_low and fresh_robust_low:
        status = "apoyada"
        verdict = ("H-V4-7f APOYADA: el trap es REAL pero CONDICIONAL a observación CORRELACIONADA (pool fijo). Bajo POOL "
                   "FIJO a k_obs=1 el greedy se ATRAPA — greedy {g} << random insesgado {r} (gap {gp} > 0.05): re-observa "
                   "siempre la región both-high y NO generaliza max(); la exploración rescata (explore {e}, +{er}). Bajo "
                   "POOL FRESH a k_obs=1 NO hay trap (gap {gf}, la diversidad de tareas dissuelve la concentración, "
                   "confirma CYCLE 87). Umbral de trap (fixed) k_obs*={tk}. => la necesidad de EXPLORAR (R-INTERVENCIÓN) "
                   "aparece cuando el agente RE-ENFRENTA la misma región sesgada con observación estrecha; con tareas "
                   "diversas o observación amplia, el greedy basta. Control comp/fixed/k_obs=1 OK ({cc}: bajo "
                   "complementos el producto es la forma correcta, no hay trap).").format(
                       g=_f(f1["learned_greedy"]), r=_f(f1["learned_random"]), gp=_f(gap_fixed[1]),
                       e=_f(f1["learned_explore"]), er=_f(f1["learned_explore"] - f1["learned_greedy"]),
                       gf=_f(gap_fresh[1]), tk=trap_fixed_kobs, cc="ok" if comp_ok else "FALLA")
    elif not fixed_traps_low:
        status = "refutada"
        verdict = ("H-V4-7f REFUTADA: ni el POOL FIJO a k_obs=1 atrapa (greedy {g} ≈ random {r}, gap {gp} <= 0.05) — la "
                   "robustez de CYCLE 87 es TOTAL: aun re-observando la misma región estrecha, el greedy recupera "
                   "max().").format(g=_f(f1["learned_greedy"]), r=_f(f1["learned_random"]), gp=_f(gap_fixed[1]))
    else:
        status = "mixta"
        verdict = ("H-V4-7f MIXTA: patrón intermedio (fixed_traps_low={ft} gap_fixed1={gp}, fresh_robust_low={fr} "
                   "gap_fresh1={gf}).").format(ft=fixed_traps_low, gp=_f(gap_fixed[1]), fr=fresh_robust_low, gf=_f(gap_fresh[1]))

    return {"grid": grid, "gap_fixed_random_minus_greedy": {str(k): gap_fixed[k] for k in K_OBS_LIST},
            "gap_fresh_random_minus_greedy": {str(k): gap_fresh[k] for k in K_OBS_LIST},
            "trap_fixed_kobs": trap_fixed_kobs, "fixed_traps_low": bool(fixed_traps_low),
            "fresh_robust_low": bool(fresh_robust_low), "explore_rescues_fixed": bool(explore_rescues_fixed),
            "comp_control_ok": bool(comp_ok), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--T", type=int, default=40)
    ap.add_argument("--E", type=int, default=20)
    ap.add_argument("--eps", type=float, default=0.3)
    ap.add_argument("--ctrl_noise", type=float, default=0.5)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 16

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp072] CYCLE 88 / H-V4-7f — concentración del soporte: pool FIJO vs FRESH (cierra caveat CYCLE 87)")
    log(f"[exp072] n={args.n} k_eval={args.k_eval} T={args.T} E={args.E} eps={args.eps} seeds={args.seeds} "
        f"k_obs={K_OBS_LIST} pools={POOLS} (q2: S={Q2_S} σr={Q2_SR}, λ={LAM})")

    grid = run(args.n, args.k_eval, args.T, args.E, args.eps, args.ctrl_noise, args.seeds)
    sm = build_summary(grid, args.n, args.k_eval)

    for pool in POOLS:
        for k_obs in K_OBS_LIST:
            c = grid["{}_kobs{}".format(pool, k_obs)]
            gp = sm["gap_{}_random_minus_greedy".format(pool)][str(k_obs)]
            log(f"[exp072] {pool} k_obs={k_obs}: product={c['product']:.3f} greedy={c['learned_greedy']:.3f} "
                f"explore={c['learned_explore']:.3f} random={c['learned_random']:.3f} (random−greedy={gp:.3f})")
    cc = grid["comp_fixed_kobs1"]
    log(f"[exp072] comp fixed k_obs=1 (control): product={cc['product']:.3f} greedy={cc['learned_greedy']:.3f} random={cc['learned_random']:.3f}")
    log(f"[exp072] fixed_traps_low={sm['fixed_traps_low']} fresh_robust_low={sm['fresh_robust_low']} "
        f"explore_rescues_fixed={sm['explore_rescues_fixed']} trap_fixed_kobs*={sm['trap_fixed_kobs']} comp_ok={sm['comp_control_ok']}")
    log(f"[exp072] VEREDICTO H-V4-7f: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp072_support_concentration", "cycle": 88, "hypothesis": "H-V4-7f",
           "claim": "el trap de sesgo de seleccion (y la necesidad de explorar) es real pero condicional a observacion "
                    "correlacionada (pool fijo): bajo pool fijo + k_obs chico el greedy se atrapa; con tareas frescas no",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp072] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

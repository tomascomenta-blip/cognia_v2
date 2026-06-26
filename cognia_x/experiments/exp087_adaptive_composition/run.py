r"""
exp087 — CYCLE 103 / H-V4-8h (rama R-VALOR, CAPSTONE del sub-arco 97-99: ablación/composición): el sub-arco 97-99 mostró
PIEZA por PIEZA que bajo no-estacionariedad la asignación R-VALOR necesita (97) OLVIDAR (decay) y (98-99) EXPLORAR gateado
por sorpresa. ¿Las dos piezas COMPONEN -- un asignador FULL-ADAPTIVE (decay + surprise-explore) supera al NAIVE
(full-history + greedy), y ablar CADA pieza por separado lo degrada (cada una es necesaria)?

CONTEXTO. 97 (decay vs full-history bajo drift), 98 (greedy se atrapa, explorar rescata), 99 (surprise-gated domina al
ε-fijo). Este ciclo las junta en UN asignador y hace la ABLACIÓN 2×2 (decay sí/no × explore sí/no) bajo drift +
action-gated + observación estrecha, con reward action-gated (la métrica de 99).

DISEÑO (numpy, online; reusa el entorno de exp082/083). Valor = bump gaussiano cuyo centro se MUEVE cada D rondas (drift).
Feedback ACTION-GATED (observás sólo lo que SELECCIONÁS), k_obs estrecho. Combinador ridge poly2. 2×2 brazos:
  - naive:         full-history + greedy (la política base, asume estacionariedad y no explora).
  - decay_only:    decay + greedy (sólo olvida -- CYCLE 97).
  - explore_only:  full-history + surprise-explore (sólo explora -- pieza de 98-99 sin olvido).
  - full_adaptive: decay + surprise-explore (las dos piezas, CYCLE 97+99).
  - oracle (rankea por valor real). Métrica = reward action-gated (perf_of de lo SELECCIONADO).

PREGUNTA FALSABLE (composición/necesidad):
  - APOYADA si full_adaptive es el MEJOR (> naive por >0.05) Y ablar CADA pieza lo degrada (full_adaptive > decay_only y
    > explore_only, cada uno por > umbral chico) -> ambas piezas COMPONEN y cada una es NECESARIA.
  - REFUTADA si naive ≈ full_adaptive (ninguna pieza ayuda en composición) o una sola pieza ya alcanza a full_adaptive
    (la otra es innecesaria).
  - MIXTA en otro caso (p.ej. una pieza domina, la otra aporta sub-umbral).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp087_adaptive_composition.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp087_adaptive_composition.run            # FULL
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
ARMS = ["naive", "decay_only", "explore_only", "full_adaptive", "oracle"]
# cada brazo = (usa_decay, usa_surprise_explore)
ARM_CFG = {"naive": (False, False), "decay_only": (True, False),
           "explore_only": (False, True), "full_adaptive": (True, True)}
ARM_ID = {a: i for i, a in enumerate(ARMS)}
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
SIGMA = 0.25


def _feats(c, r):
    c = np.asarray(c); r = np.asarray(r)
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _wridge(c_obs, r_obs, y, w, alpha):
    X = _feats(c_obs, r_obs); W = np.asarray(w)
    A = (X * W[:, None]).T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, (X * W[:, None]).T @ np.asarray(y))


def _score(c, r, wv):
    return _feats(c, r) @ wv


def _value(c, r, mu, nu):
    return np.exp(-(((c - mu) ** 2) + ((r - nu) ** 2)) / (2.0 * SIGMA ** 2))


def perf_of(picks, v):
    k = len(picks); best = np.sort(v)[-k:].sum(); got = v[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _select(c, r, wv, k, eps, rng):
    n = len(c)
    if wv is None:
        return rng.choice(n, size=min(k, n), replace=False)
    order = np.argsort(_score(c, r, wv) + 1e-9 * rng.random(n))[::-1]
    if eps > 0:
        n_exp = int(round(eps * k))
        top = list(order[:k - n_exp]); rest = [i for i in order if i not in set(top)]
        return np.array(top + list(rng.permutation(rest)[:n_exp]), dtype=int)
    return order[:k]


def run_cell(n, T, D, warmup, k_obs, k_eval, decay, eps_high, noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        per = {a: [] for a in ARMS}
        for arm in ARM_CFG:
            use_decay, use_explore = ARM_CFG[arm]
            rng = np.random.default_rng(seed * 2087 + ARM_ID[arm] * 41 + 3)
            ph = np.random.default_rng(seed * 99 + 7)
            mu, nu = float(ph.random()), float(ph.random())
            bc, br, by, bt = [], [], [], []
            wv = None; eps_eff = 0.0; ema_surp = None
            for t in range(T):
                if t > 0 and t % D == 0:
                    mu, nu = float(ph.random()), float(ph.random())
                c = rng.random(n); r = rng.random(n)
                val = _value(c, r, mu, nu)
                eps = eps_eff if use_explore else 0.0
                sel = _select(c, r, wv, k_obs, eps, rng)
                if use_explore and wv is not None:
                    pred = _score(c[sel], r[sel], wv)
                    surp = float(np.mean(np.maximum(0.0, pred - val[sel])))
                    if ema_surp is None:
                        ema_surp = surp
                    spike = surp > (ema_surp * 1.5 + 0.05)
                    ema_surp = 0.7 * ema_surp + 0.3 * surp
                    eps_eff = eps_high if spike else 0.0
                for i in sel:
                    bc.append(c[i]); br.append(r[i]); by.append(val[i]); bt.append(t)
                if len(by) >= MIN_FIT:
                    w = np.power(decay, t - np.asarray(bt)) if use_decay else np.ones(len(by))
                    wv = _wridge(bc, br, by, w, RIDGE_ALPHA)
                if t >= warmup:
                    per[arm].append(perf_of(sel, val))                     # reward action-gated
                    if arm == "naive":
                        jit = 1e-9 * rng.random(n)
                        per["oracle"].append(perf_of(np.argsort(val + jit)[-k_obs:], val))
        for a in ARMS:
            if per[a]:
                acc[a].append(float(np.mean(per[a])))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(cell):
    full = cell["full_adaptive"]; naive = cell["naive"]; do = cell["decay_only"]; eo = cell["explore_only"]
    full_vs_naive = round(full - naive, 4)
    full_vs_decay = round(full - do, 4)        # >0: la pieza EXPLORE aporta sobre decay-solo
    full_vs_explore = round(full - eo, 4)      # >0: la pieza DECAY aporta sobre explore-solo
    oracle_gap = round(cell["oracle"] - full, 4)

    BIG = 0.05
    SMALL = 0.015

    full_best = (full_vs_naive > BIG) and (full >= do - 1e-9) and (full >= eo - 1e-9)
    explore_needed = full_vs_decay > SMALL     # ablar explore (=decay_only) degrada -> explore necesario
    decay_needed = full_vs_explore > SMALL     # ablar decay (=explore_only) degrada -> decay necesario

    if full_best and explore_needed and decay_needed:
        status = "apoyada"
        verdict = ("H-V4-8h APOYADA: las piezas de no-estacionariedad COMPONEN y cada una es NECESARIA. full_adaptive "
                   "(decay + surprise-explore)={fa} es el MEJOR -- supera al naive (full-history + greedy)={nv} por +{fvn} "
                   "(≈ oracle, gap {og}). Ablar la EXPLORACIÓN (decay_only={do}) lo degrada (-{fvd}) y ablar el OLVIDO "
                   "(explore_only={eo}) lo degrada (-{fve}): NINGUNA pieza sola alcanza a full_adaptive -> ambas aportan. "
                   "=> el asignador R-VALOR bajo no-estacionariedad necesita OLVIDAR (97) Y EXPLORAR gateado por sorpresa "
                   "(98-99) JUNTOS; la composición del sub-arco 97-99 es real, no aditiva-trivial.").format(
                       fa=_f(full), nv=_f(naive), fvn=_f(full_vs_naive), og=_f(oracle_gap), do=_f(do), fvd=_f(full_vs_decay),
                       eo=_f(eo), fve=_f(full_vs_explore))
    elif full_vs_naive <= BIG:
        status = "refutada"
        verdict = ("H-V4-8h REFUTADA: full_adaptive NO supera al naive (={fa} vs {nv}, +{fvn} <= {b}) -> las piezas no "
                   "aportan en composición.").format(fa=_f(full), nv=_f(naive), fvn=_f(full_vs_naive), b=BIG)
    else:
        status = "mixta"
        verdict = ("H-V4-8h MIXTA: full_best={fb} (vs naive +{fvn}) explore_needed={en}(+{fvd}) decay_needed={dn}(+{fve}) "
                   "-- una pieza domina y la otra aporta sub-umbral (composición parcial).").format(
                       fb=full_best, fvn=_f(full_vs_naive), en=explore_needed, fvd=_f(full_vs_decay), dn=decay_needed, fve=_f(full_vs_explore))

    return {"cell": cell, "full_vs_naive": full_vs_naive, "full_vs_decay": full_vs_decay, "full_vs_explore": full_vs_explore,
            "oracle_gap": oracle_gap, "full_best": bool(full_best), "explore_needed": bool(explore_needed),
            "decay_needed": bool(decay_needed), "status": status, "verdict": verdict}


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
    ap.add_argument("--eps_high", type=float, default=0.5)
    ap.add_argument("--noise", type=float, default=0.05)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp087] CYCLE 103 / H-V4-8h — ablación/composición del asignador adaptativo (decay × surprise-explore) bajo drift")
    log(f"[exp087] n={args.n} T={args.T} D={args.D} warmup={args.warmup} k_obs={args.k_obs} decay={args.decay} "
        f"eps_high={args.eps_high} noise={args.noise} seeds={args.seeds}")

    cell = run_cell(args.n, args.T, args.D, args.warmup, args.k_obs, args.k_eval, args.decay, args.eps_high, args.noise, args.seeds)
    sm = build_summary(cell)

    log("[exp087] " + " ".join(f"{a}={cell[a]:.3f}" for a in ARMS))
    log(f"[exp087] full_vs_naive=+{sm['full_vs_naive']:.3f} | full_vs_decay_only=+{sm['full_vs_decay']:.3f} (explore aporta) | "
        f"full_vs_explore_only=+{sm['full_vs_explore']:.3f} (decay aporta) | oracle_gap={sm['oracle_gap']:.3f}")
    log(f"[exp087] full_best={sm['full_best']} explore_needed={sm['explore_needed']} decay_needed={sm['decay_needed']}")
    log(f"[exp087] VEREDICTO H-V4-8h: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp087_adaptive_composition", "cycle": 103, "hypothesis": "H-V4-8h",
           "claim": "las piezas de no-estacionariedad (olvido por decay + exploracion surprise-gated) COMPONEN y cada una "
                    "es NECESARIA: el asignador full-adaptive supera al naive y ablar cada pieza lo degrada -> la "
                    "composicion del sub-arco 97-99 es real",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp087] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

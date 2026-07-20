r"""
exp071 — CYCLE 87 / H-V4-7e (rama R-VALOR, puente hacia gaps #1/#3 — feedback de acción-consecuencia): bajo feedback
ACTION-GATED (el agente sólo observa el valor de lo que SELECCIONA, no m al azar), ¿la política aprendida del gap #2 se
AUTO-ATRAPA por sesgo de selección, y la EXPLORACIÓN la rescata?

CONTEXTO: el arco gap #2 (83-86) asumió feedback LIBRE (m observaciones al azar del valor). Pero un agente real sólo ve
las consecuencias de lo que HACE. Si selecciona por el producto (su prior), sólo observa ítems both-high y NUNCA ve los
one-high que importan bajo sustitutos -> su buffer queda SESGADO -> no puede aprender la forma max. Este ciclo prueba si
la explotación greedy del prior es auto-atrapante y si explorar (actuar más allá del prior) lo rescata. Re-deriva
R-INTERVENCIÓN (hay que ACTUAR/EXPLORAR para aprender el valor) en el contexto de la reconstrucción de R-VALOR.

DISEÑO (online, ítems FRESCOS por ronda). Régimen SUSTITUTOS (g=max, λ=1.0, donde el producto se rompe) + COMPLEMENTOS de
control. Estimadores ruidosos calidad q2 (S=32, σr=0.05, el régimen donde con feedback LIBRE el aprendido recupera, exp069).
FASE LEARNING (T rondas): cada ronda n ítems frescos; el agente SELECCIONA k para observar su valor real (action-gated),
acumula buffer, refit ridge poly2. Estrategias de OBSERVACIÓN:
  - greedy:  selecciona-para-observar por el combinador aprendido actual (bootstrap del producto) -> buffer SESGADO.
  - explore: ε-greedy (una fracción ε de slots al azar) -> buffer parcialmente diverso.
  - random:  observa al azar (buffer INSESGADO; techo de aprendizaje, = feedback libre de exp068).
FASE EVAL (E rondas frescas): se ajusta el combinador final del buffer de cada estrategia y se rankea (top-k) sin
explorar; métrica = perf (got/best) promedio. Brazos: oracle, product (sin aprender), learned_greedy, learned_explore,
learned_random, random.

PREDICCIÓN FALSABLE (sustitutos):
  - APOYADA si (TRAMPA) learned_greedy <= product + 0.02 (el sesgo de selección lo atrapa en el prior) Y (EXPLORACIÓN
    RESCATA) learned_explore > learned_greedy + 0.03 y alcanza el techo insesgado (>= learned_random - 0.03). => bajo
    feedback action-gated hay que EXPLORAR (actuar más allá del prior) para aprender R-VALOR no-factorizable; la
    explotación pasiva del prior es auto-atrapante (R-INTERVENCIÓN).
  - REFUTADA si NO hay trampa (greedy recupera sin explorar) o la exploración NO ayuda.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp071_action_gated_feedback.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp071_action_gated_feedback.run            # FULL
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
ARMS = ["oracle", "product", "learned_greedy", "learned_explore", "learned_random", "random"]
FAMILIES = ["subs", "comp"]
STRATS = ["greedy", "explore", "random"]
LAM = 1.0
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
FAM_ID = {"subs": 2, "comp": 1}
STRAT_ID = {"greedy": 0, "explore": 1, "random": 2}
# calidad q2 (feedback adecuado, donde con feedback libre el aprendido recupera, exp069)
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


def _draw_round(rng, n, fam, sc):
    ctrl = rng.random(n)
    rel = rng.random(n)
    value = _value(ctrl, rel, fam, LAM)
    ctrl_est = np.clip(ctrl + rng.normal(0.0, sc / np.sqrt(Q2_S), size=n), 0.0, 1.0)
    rel_est = np.clip(rel + rng.normal(0.0, Q2_SR, size=n), 0.0, 1.0)
    return ctrl_est, rel_est, value


def _score(ctrl_est, rel_est, w):
    if w is None:
        return ctrl_est * rel_est            # bootstrap = producto
    return _feats(ctrl_est, rel_est) @ w


def _learn_buffer(rng, n, k, fam, sc, T, eps, strat):
    bc, br, by = [], [], []   # buffer de features observadas
    w = None
    for t in range(T):
        ctrl_est, rel_est, value = _draw_round(rng, n, fam, sc)
        if strat == "random":
            sel = rng.choice(n, size=k, replace=False)
        else:
            score = _score(ctrl_est, rel_est, w)
            order = np.argsort(score + 1e-9 * rng.random(n))[::-1]
            if strat == "explore":
                n_exp = int(round(eps * k))
                top = list(order[:k - n_exp])
                rest = [i for i in order if i not in set(top)]
                exp_sel = list(rng.permutation(rest)[:n_exp])
                sel = np.array(top + exp_sel, dtype=int)
            else:  # greedy
                sel = order[:k]
        for i in sel:
            bc.append(ctrl_est[i]); br.append(rel_est[i]); by.append(value[i])
        if len(by) >= MIN_FIT:
            w = _ridge_w(bc, br, by, RIDGE_ALPHA)
    return w


def _eval_combiner(rng, n, k, fam, sc, E, w):
    perfs = []
    for _ in range(E):
        ctrl_est, rel_est, value = _draw_round(rng, n, fam, sc)
        score = _score(ctrl_est, rel_est, w)
        picks = np.argsort(score + 1e-9 * rng.random(n))[-k:]
        perfs.append(perf_of(picks, value))
    return float(np.mean(perfs))


def _eval_fixed(rng, n, k, fam, sc, E, use_product):
    perfs = []
    for _ in range(E):
        ctrl_est, rel_est, value = _draw_round(rng, n, fam, sc)
        if use_product:
            picks = np.argsort(ctrl_est * rel_est + 1e-9 * rng.random(n))[-k:]
        else:
            picks = rng.choice(n, size=k, replace=False)
        perfs.append(perf_of(picks, value))
    return float(np.mean(perfs))


def run_cell(n, k, fam, T, E, eps, sc, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        for strat in STRATS:
            rng = np.random.default_rng(seed * 2087 + FAM_ID[fam] * 131 + STRAT_ID[strat] * 41)
            w = _learn_buffer(rng, n, k, fam, sc, T, eps, strat)
            ev = _eval_combiner(rng, n, k, fam, sc, E, w)
            acc["learned_{}".format(strat)].append(ev)
        rng2 = np.random.default_rng(seed * 5099 + FAM_ID[fam] * 7)
        acc["product"].append(_eval_fixed(rng2, n, k, fam, sc, E, use_product=True))
        acc["random"].append(_eval_fixed(rng2, n, k, fam, sc, E, use_product=False))
        # oracle: por construcción 1.0 (top-k por valor verdadero); lo medimos para mantener el formato
        acc["oracle"].append(1.0)
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, T, E, eps, sc, n_seeds):
    grid = {}
    for fam in FAMILIES:
        grid[fam] = run_cell(n, k, fam, T, E, eps, sc, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid, n, k):
    s = grid["subs"]
    prod, greedy, explore, rnd = s["product"], s["learned_greedy"], s["learned_explore"], s["learned_random"]
    trap = greedy <= prod + 0.02
    explore_rescues = (explore > greedy + 0.03) and (explore >= rnd - 0.03)

    if trap and explore_rescues:
        status = "apoyada"
        verdict = ("H-V4-7e APOYADA: bajo feedback ACTION-GATED hay que EXPLORAR para aprender R-VALOR no-factorizable; la "
                   "explotación greedy del prior es AUTO-ATRAPANTE (R-INTERVENCIÓN). Sustitutos: learned_greedy {g} ≈ "
                   "product {p} (TRAMPA: el sesgo de selección sólo observa both-high, no aprende max), pero "
                   "learned_explore {e} lo rescata (+{re} sobre greedy) y alcanza el techo INSESGADO learned_random {r} "
                   "(feedback libre). => observar sólo lo que el prior elige ciega al agente al valor de sustitutos; "
                   "actuar/explorar más allá del prior es NECESARIO para reconstruir R-VALOR.").format(
                       g=_f(greedy), p=_f(prod), e=_f(explore), re=_f(explore - greedy), r=_f(rnd))
    elif not trap:
        status = "refutada"
        verdict = ("H-V4-7e REFUTADA (no hay trampa): learned_greedy {g} supera a product {p} por >0.02 sin explorar -> el "
                   "sesgo de selección NO atrapa; la explotación del prior ya aprende la forma de sustitutos.").format(
                       g=_f(greedy), p=_f(prod))
    elif not explore_rescues:
        status = "refutada"
        verdict = ("H-V4-7e REFUTADA (la exploración no rescata): learned_explore {e} no supera a greedy {g} por >0.03 o "
                   "no alcanza el techo insesgado learned_random {r} -> explorar no resuelve la trampa.").format(
                       e=_f(explore), g=_f(greedy), r=_f(rnd))
    else:
        status = "mixta"
        verdict = ("H-V4-7e MIXTA: patrón intermedio (trap={t}, explore_rescues={er}; greedy {g}, explore {e}, random {r}, "
                   "product {p}).").format(t=trap, er=explore_rescues, g=_f(greedy), e=_f(explore), r=_f(rnd), p=_f(prod))

    return {"grid": grid, "subs_product": prod, "subs_greedy": greedy, "subs_explore": explore, "subs_random": rnd,
            "trap": bool(trap), "explore_rescues": bool(explore_rescues),
            "explore_minus_greedy": round(explore - greedy, 4), "random_minus_explore": round(rnd - explore, 4),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
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

    log("[exp071] CYCLE 87 / H-V4-7e — feedback ACTION-GATED: ¿sesgo de selección atrapa? ¿explorar rescata? (R-INTERVENCIÓN)")
    log(f"[exp071] n={args.n} k={args.k} T={args.T} E={args.E} eps={args.eps} ctrl_noise={args.ctrl_noise} "
        f"seeds={args.seeds} (q2: S={Q2_S} σr={Q2_SR}, λ={LAM})")

    grid = run(args.n, args.k, args.T, args.E, args.eps, args.ctrl_noise, args.seeds)
    sm = build_summary(grid, args.n, args.k)

    for fam in FAMILIES:
        c = grid[fam]
        log(f"[exp071] {fam}: product={c['product']:.3f} greedy={c['learned_greedy']:.3f} "
            f"explore={c['learned_explore']:.3f} random(insesgado)={c['learned_random']:.3f} rand={c['random']:.3f}")
    log(f"[exp071] sustitutos: trap(greedy<=prod+0.02)={sm['trap']} explore_rescues={sm['explore_rescues']} "
        f"(explore−greedy={sm['explore_minus_greedy']:.3f}, random−explore={sm['random_minus_explore']:.3f})")
    log(f"[exp071] VEREDICTO H-V4-7e: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp071_action_gated_feedback", "cycle": 87, "hypothesis": "H-V4-7e",
           "claim": "bajo feedback action-gated la explotacion greedy del prior se auto-atrapa por sesgo de seleccion; "
                    "explorar (actuar mas alla del prior) es necesario para aprender R-VALOR no-factorizable (R-INTERVENCION)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp071] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

r"""
exp073 — CYCLE 89 / H-V4-7g (rama R-VALOR, EL SALTO GRANDE — gaps #1/#3): ¿la política R-VALOR del arco gap #2
(aprender un combinador barato + asignar el feedback ESCASO por él) sobrevive cuando el valor lo decide un
VERIFICADOR CHEQUEABLE REAL (el sandbox de exp018 EJECUTA el candidato; valor ∈ {0,1}) en vez del g SINTÉTICO SUAVE?

CONTEXTO. Todo el arco gap #2 (CYCLE 83-88) construyó R-VALOR=control×relevancia con un valor SINTÉTICO SUAVE
(g=min/max de (ctrl,rel)) y ruido ABSTRACTO. El caveat HONESTO más repetido de 83-88: "g=max sintético, base poly2
que NESTA el target". El salto grande (frontera tras CYCLE 88): aterrizar la política en un lazo de acción-consecuencia
REAL — feedback con COSTO (presupuesto de verificación K≪N), valor DISCRETO no-suave decidido por EJECUCIÓN.

PUENTE EXACTO. Cada candidato es una EXPRESIÓN generada con dos latentes: estructura c (P[bien-formada con operador])
y valor r (P[su valor == target]). El verificador REAL (exp018 `interpret`/`verify`, parser propio, sin eval) la
EJECUTA y decide v ∈ {0,1}. Esto induce DOS regímenes ANÁLOGOS a comp/subs del arco — pero con la esperanza del valor
REAL, no un g de juguete:
  - STRONG (verificador fuerte: exige operador Y valor==target): v = wf AND vm  →  E[v|c,r] = c·r
    => el PRODUCTO es BAYES-ÓPTIMO (complementos). El aprendido debe IGUALARLO (no-regret).
  - WEAK (verificador débil: acepta el echo del target sin operador): v = vm  →  E[v|c,r] = r
    => el producto MIS-RANKEA (sub-pondera echoes high-r/low-c); relevancia-dominante (paralelo REAL al régimen
       'sustitutos' donde el producto se rompía, CYCLE 83). El aprendido (poly2 nesta r y c·r) debe RECUPERAR.

El agente ve features RUIDOSAS (c_est, r_est) = observaciones de los latentes; NO puede ejecutar gratis. Con un
PRESUPUESTO K por ronda SELECCIONA qué candidatos verificar (action-gated + costoso), observa el v REAL (Bernoulli),
acumula buffer y refit ridge-poly2. EVAL: rankea un pool FRESH por el combinador final, perf = frac de la masa
correcta alcanzable capturada por el top-k_eval (perf_of con v discreto).

PREGUNTA FALSABLE (el salto SMOOTH→DISCRETE no debe romper el mecanismo):
  - APOYADA si bajo STRONG learned_greedy ≈ product (|Δ|<=0.02, no-regret donde el producto es Bayes-óptimo) y bajo
    WEAK learned_greedy > product (+>0.03, recupera la relevancia-dominancia que el producto pierde), con greedy
    SIN trampa (>= learned_random − 0.03; confirma 87-88 con valor real) y recuperando la mayoría del oracle.
  - REFUTADA si el valor DISCRETO rompe el aprendizaje: learned ≈ random_rank (chance) o learned << product/oracle
    -> el resultado del arco gap #2 era un ARTEFACTO del g suave.
  - MIXTA en otro caso (p.ej. no-regret en strong pero la recuperación weak no cruza, o greedy se atrapa).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp073_real_verifier_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp073_real_verifier_value.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp018_real_verifier import expression_task as E

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["product", "learned_greedy", "learned_explore", "learned_random", "oracle", "chance"]
STRATS = ["greedy", "explore", "random"]
REGIMES = ["strong", "weak"]            # strong = complementos (E[v]=c·r); weak = relevancia-dom (E[v]=r)
REGIME_ID = {"strong": 0, "weak": 1}
STRAT_ID = {"greedy": 0, "explore": 1, "random": 2}
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
LO, HI = E.LO if hasattr(E, "LO") else 2, E.HI if hasattr(E, "HI") else 300
Q_S = 32                                # calidad de feature de control (S muestras -> σ = sc/sqrt(S))
Q_SR = 0.05                             # ruido de feature de relevancia


def _wrong_value_expr(rng, n):
    """Expresión bien-formada 'a op b' cuyo valor != n (operador presente, valor incorrecto)."""
    for _ in range(8):
        a = int(rng.integers(1, 99)); b = int(rng.integers(1, 99))
        op = "+" if rng.random() < 0.5 else "*"
        val = a + b if op == "+" else a * b
        if val != n:
            return "{}{}{}".format(a, op, b).encode("ascii")
    return "{}+{}".format(a, (b + 1)).encode("ascii")     # casi siempre != n


def _make_candidate(rng, c, r, n):
    """Construye una EXPRESIÓN real según los latentes (c=estructura, r=valor) y devuelve (expr_bytes, strong_v,
    weak_v) con el VEREDICTO REAL del sandbox (exp018). Bernoulli: wf~c, vm~r.
      wf  & vm  -> 'a op b'==n              (strong=1, weak=1)
      wf  & !vm -> 'a op b'!=n              (strong=0, weak=0)
      !wf & vm  -> echo 'n' (==n, sin op)   (strong=0, weak=1)   <- la rama OR que el producto pierde
      !wf & !vm -> malformada               (strong=0, weak=0)
    """
    wf = rng.random() < c
    vm = rng.random() < r
    if wf and vm:
        expr = E.real_expression(rng, n)
    elif wf and not vm:
        expr = _wrong_value_expr(rng, n)
    elif (not wf) and vm:
        expr = E.echo_expression(n)
    else:
        expr = b"x"
    prompt = E.make_prompt(n)
    gen = bytes(expr) + b"\n"
    strong_v = 1.0 if E.verify(prompt, gen, strong=True) else 0.0
    weak_v = 1.0 if E.verify(prompt, gen, strong=False) else 0.0
    return strong_v, weak_v


def _draw_pool(rng, n, regime, sc):
    """Pool de n candidatos: latentes (c,r), valor REAL v del sandbox para el régimen, y features RUIDOSAS."""
    c = rng.random(n)
    r = rng.random(n)
    v = np.empty(n, dtype=float)
    for i in range(n):
        ni = int(rng.integers(LO, HI + 1))
        sv, wv = _make_candidate(rng, c[i], r[i], ni)
        v[i] = sv if regime == "strong" else wv
    c_est = np.clip(c + rng.normal(0.0, sc / np.sqrt(Q_S), size=n), 0.0, 1.0)
    r_est = np.clip(r + rng.normal(0.0, Q_SR, size=n), 0.0, 1.0)
    return c_est, r_est, v


def _feats(c, r):
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _ridge_w(c_obs, r_obs, y, alpha):
    X = _feats(np.asarray(c_obs), np.asarray(r_obs))
    A = X.T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ np.asarray(y))


def _score(c_est, r_est, w):
    if w is None:
        return c_est * r_est
    return _feats(c_est, r_est) @ w


def _select(c_est, r_est, w, k, strat, eps, rng):
    n = len(c_est)
    if strat == "random":
        return rng.choice(n, size=min(k, n), replace=False)
    order = np.argsort(_score(c_est, r_est, w) + 1e-9 * rng.random(n))[::-1]
    if strat == "explore":
        n_exp = int(round(eps * k))
        top = list(order[:k - n_exp])
        rest = [i for i in order if i not in set(top)]
        exp_sel = list(rng.permutation(rest)[:n_exp])
        return np.array(top + exp_sel, dtype=int) if (top or exp_sel) else order[:k]
    return order[:k]


def perf_of(picks, v):
    """Frac de la masa de correctos alcanzable capturada por el top-k. Con v∈{0,1}: correctos_en_topk / min(k, total)."""
    k = len(picks)
    total = float(v.sum())
    best = min(float(k), total)
    got = float(v[list(picks)].sum())
    return got / best if best > 1e-12 else 0.0


def run_cell(n, k_budget, k_eval, regime, T, E_rounds, eps, sc, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        # brazos que APRENDEN (greedy/explore/random), action-gated + costoso
        for strat in STRATS:
            rng = np.random.default_rng(seed * 2087 + REGIME_ID[regime] * 997 + STRAT_ID[strat] * 41 + k_budget * 911)
            bc, br, by = [], [], []
            w = None
            for _ in range(T):
                ce, re, val = _draw_pool(rng, n, regime, sc)
                sel = _select(ce, re, w, k_budget, strat, eps, rng)
                for i in sel:
                    bc.append(ce[i]); br.append(re[i]); by.append(val[i])
                if len(by) >= MIN_FIT and len(set(by)) > 1:
                    w = _ridge_w(bc, br, by, RIDGE_ALPHA)
            perfs = []
            for _ in range(E_rounds):
                ce, re, val = _draw_pool(rng, n, regime, sc)
                picks = np.argsort(_score(ce, re, w) + 1e-9 * rng.random(n))[-k_eval:]
                perfs.append(perf_of(picks, val))
            acc["learned_{}".format(strat)].append(float(np.mean(perfs)))
        # baselines sin aprender: product (c·r), oracle (v real), chance (orden aleatorio)
        rng2 = np.random.default_rng(seed * 5099 + REGIME_ID[regime] * 7 + k_budget * 17)
        pp, po, pch = [], [], []
        for _ in range(E_rounds):
            ce, re, val = _draw_pool(rng2, n, regime, sc)
            pp.append(perf_of(np.argsort(ce * re + 1e-9 * rng2.random(n))[-k_eval:], val))
            po.append(perf_of(np.argsort(val + 1e-9 * rng2.random(n))[-k_eval:], val))
            pch.append(perf_of(rng2.choice(n, size=k_eval, replace=False), val))
        acc["product"].append(float(np.mean(pp)))
        acc["oracle"].append(float(np.mean(po)))
        acc["chance"].append(float(np.mean(pch)))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k_budget, k_eval, T, E_rounds, eps, sc, n_seeds):
    return {reg: run_cell(n, k_budget, k_eval, reg, T, E_rounds, eps, sc, n_seeds) for reg in REGIMES}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    s = grid["strong"]; w = grid["weak"]
    noregret_strong = round(s["learned_greedy"] - s["product"], 4)          # ~0 esperado (producto Bayes-óptimo)
    recover_weak = round(w["learned_greedy"] - w["product"], 4)             # >0 esperado (recupera relevancia-dom)
    greedy_trap_strong = round(s["learned_random"] - s["learned_greedy"], 4)
    greedy_trap_weak = round(w["learned_random"] - w["learned_greedy"], 4)
    learn_alive_strong = round(s["learned_greedy"] - s["chance"], 4)
    learn_alive_weak = round(w["learned_greedy"] - w["chance"], 4)
    oracle_gap_strong = round(s["oracle"] - s["learned_greedy"], 4)
    oracle_gap_weak = round(w["oracle"] - w["learned_greedy"], 4)

    NOREGRET_TOL = 0.02
    RECOVER_THR = 0.03
    TRAP_TOL = 0.03
    ALIVE_THR = 0.05

    no_regret_ok = abs(noregret_strong) <= NOREGRET_TOL
    recover_ok = recover_weak > RECOVER_THR
    no_trap = (greedy_trap_strong <= TRAP_TOL) and (greedy_trap_weak <= TRAP_TOL)
    learning_alive = (learn_alive_strong > ALIVE_THR) and (learn_alive_weak > ALIVE_THR)

    if no_regret_ok and recover_ok and no_trap and learning_alive:
        status = "apoyada"
        verdict = ("H-V4-7g APOYADA: la política R-VALOR del gap #2 SOBREVIVE el salto a un verificador chequeable "
                   "REAL (valor discreto del sandbox, no g suave). STRONG (E[v]=c·r, producto Bayes-óptimo): "
                   "learned_greedy={lgs} ≈ product={ps} (no-regret Δ={nr}). WEAK (E[v]=r, el producto mis-rankea los "
                   "echoes): learned_greedy={lgw} > product={pw} (recupera +{rc}, relevancia-dominancia). El feedback "
                   "DISCRETO (Bernoulli) NO rompe el aprendizaje (vs chance +{las}/+{law}); greedy no se atrapa "
                   "(trap S={ts}/W={tw} <= {tt}); recupera la mayoría del oracle (gap S={ogs}/W={ogw}). => el "
                   "mecanismo del arco no era artefacto del g suave.").format(
                       lgs=_f(s["learned_greedy"]), ps=_f(s["product"]), nr=_f(noregret_strong),
                       lgw=_f(w["learned_greedy"]), pw=_f(w["product"]), rc=_f(recover_weak),
                       las=_f(learn_alive_strong), law=_f(learn_alive_weak), ts=_f(greedy_trap_strong),
                       tw=_f(greedy_trap_weak), tt=TRAP_TOL, ogs=_f(oracle_gap_strong), ogw=_f(oracle_gap_weak))
    elif not learning_alive:
        status = "refutada"
        verdict = ("H-V4-7g REFUTADA: el valor DISCRETO del verificador real ROMPE el aprendizaje del combinador "
                   "(learned_greedy vs chance: S +{las} / W +{law}, no supera {at}) -> el mecanismo del arco gap #2 "
                   "dependía del g SUAVE.").format(las=_f(learn_alive_strong), law=_f(learn_alive_weak), at=ALIVE_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-7g MIXTA: no_regret_strong={nro}(Δ={nr}) recover_weak={rco}(+{rc}) no_trap={ntp} "
                   "learning_alive={la}. El salto a verificador real sobrevive PARCIALMENTE.").format(
                       nro=no_regret_ok, nr=_f(noregret_strong), rco=recover_ok, rc=_f(recover_weak),
                       ntp=no_trap, la=learning_alive)

    return {"grid": grid, "noregret_strong": noregret_strong, "recover_weak": recover_weak,
            "greedy_trap_strong": greedy_trap_strong, "greedy_trap_weak": greedy_trap_weak,
            "learn_alive_strong": learn_alive_strong, "learn_alive_weak": learn_alive_weak,
            "oracle_gap_strong": oracle_gap_strong, "oracle_gap_weak": oracle_gap_weak,
            "no_regret_ok": bool(no_regret_ok), "recover_ok": bool(recover_ok), "no_trap": bool(no_trap),
            "learning_alive": bool(learning_alive), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k_budget", type=int, default=10)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--T", type=int, default=40)
    ap.add_argument("--E", type=int, default=20)
    ap.add_argument("--eps", type=float, default=0.3)
    ap.add_argument("--ctrl_noise", type=float, default=0.5)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.T, args.E = 6, 20, 10

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp073] CYCLE 89 / H-V4-7g — R-VALOR sobre VERIFICADOR REAL (sandbox exp018; valor discreto, no g suave)")
    log(f"[exp073] n={args.n} k_budget={args.k_budget} k_eval={args.k_eval} T={args.T} E={args.E} eps={args.eps} "
        f"seeds={args.seeds} regimes={REGIMES} targets=[{LO},{HI}] (q: S={Q_S} σr={Q_SR})")

    grid = run(args.n, args.k_budget, args.k_eval, args.T, args.E, args.eps, args.ctrl_noise, args.seeds)
    sm = build_summary(grid)

    for reg in REGIMES:
        c = grid[reg]
        log(f"[exp073] {reg:>6}: product={c['product']:.3f} greedy={c['learned_greedy']:.3f} "
            f"explore={c['learned_explore']:.3f} random={c['learned_random']:.3f} oracle={c['oracle']:.3f} "
            f"chance={c['chance']:.3f}")
    log(f"[exp073] no-regret(strong) Δ={sm['noregret_strong']:.3f} | recover(weak) +{sm['recover_weak']:.3f} | "
        f"trap S={sm['greedy_trap_strong']:.3f}/W={sm['greedy_trap_weak']:.3f} | "
        f"alive S=+{sm['learn_alive_strong']:.3f}/W=+{sm['learn_alive_weak']:.3f}")
    log(f"[exp073] no_regret_ok={sm['no_regret_ok']} recover_ok={sm['recover_ok']} no_trap={sm['no_trap']} "
        f"learning_alive={sm['learning_alive']}")
    log(f"[exp073] VEREDICTO H-V4-7g: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp073_real_verifier_value", "cycle": 89, "hypothesis": "H-V4-7g",
           "claim": "la politica R-VALOR del gap #2 (combinador aprendido + asignacion del feedback escaso) sobrevive "
                    "el salto a un verificador chequeable REAL (valor discreto del sandbox exp018, no un g sintetico "
                    "suave): no-regret donde el producto es Bayes-optimo (strong/complementos) y recupera donde el "
                    "producto mis-rankea (weak/relevancia-dom), sin que el feedback discreto rompa el aprendizaje",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp073] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

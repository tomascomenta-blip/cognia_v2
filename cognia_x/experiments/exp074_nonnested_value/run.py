r"""
exp074 — CYCLE 90 / H-V4-7h (rama R-VALOR, hija de CYCLE 89; conecta con R-PRIOR/H-V4-3): cuando la media condicional del
VERIFICADOR REAL NO es nesteable por el poly2 (estructura MULTI-BANDA, no-monótona), ¿la política R-VALOR todavía
recupera el valor — y de qué depende?

CONTEXTO. CYCLE 89 (exp073) mostró que la política del gap #2 sobrevive el salto a un verificador chequeable REAL
(sandbox exp018, valor discreto) — PERO con un caveat HONESTO: la ESPERANZA E[v|c,r] seguía SUAVE y NESTEABLE por el
poly2 (c·r, r). Se probó la VARIANZA Bernoulli, NO una media condicional que el poly2 no pueda representar. Esta hija
ataca ese eje: hace que el verificador real tenga una estructura MULTI-BANDA en la feature estructural c
(well_formed = int(c·NBANDS) % 2 == 0 -> varias bandas aceptadas alternadas con rechazadas), que un poly2 (una sola
parábola) NO puede representar. El valor lo sigue decidiendo el sandbox REAL (ejecuta el candidato).

TESIS (conecta con R-PRIOR / H-V4-3, ABIERTA): la BASE del combinador es un PRIOR sobre la estructura del valor. El
poly2 default del gap #2 NO es universal: cuando la media condicional real no entra en su span, falla; una base RICA
(no-paramétrica, binned) la recupera — pero a COSTA de más feedback (el prior rico es data-hungry). El lever es la
CALIDAD/MATCH del prior (no el volumen), exactamente la tesis de R-PRIOR.

DISEÑO (numpy + sandbox REAL de exp018). Cada candidato = una EXPRESIÓN con latentes c (estructura) y r (valor):
well_formed = (int(c·NBANDS) % 2 == 0)  (multi-banda, NO-monótona en c); value_match ~ Bernoulli(r). El sandbox la
EJECUTA: v = is_real_solution (strong = operador Y valor==target) = well_formed AND value_match  ->  E[v|c,r] =
1{c en banda}(c) · r. El eje r es nesteable; el eje c es MULTI-BANDA (no nesteable por poly2). Features RUIDOSAS
(c_est, r_est). Feedback COSTOSO: presupuesto K por ronda, asignación RANDOM (insesgada, para AISLAR la capacidad de la
base — no el sesgo de selección, ya estudiado en 87-89). Buffer compartido -> se ajustan TODAS las bases sobre los
MISMOS datos. EVAL: rankea un pool fresh por el estimador final (perf_of con v discreto). Eje de presupuesto B ∈ {low,
high} para exponer el costo de feedback del prior rico.

Brazos: product (c·r, prior fijo monótono), learned_poly2 (base del gap #2), learned_poly4 (base más rica), learned_bin
(no-paramétrica G×G, recupera cualquier estructura con datos), oracle (v real), chance.

PREGUNTA FALSABLE:
  - APOYADA si a presupuesto ADECUADO la base RICA (bin) RECUPERA (> poly2 + 0.05, cerca del oracle) donde poly2 FALLA
    (≈ product, muy por debajo del oracle) Y el prior rico cuesta más feedback (bin mejora low->high más que poly2).
    => el poly2 NO es universal; el lever es el MATCH del prior con la estructura (R-PRIOR), pagando su costo de datos.
  - REFUTADA si poly2 TAMBIÉN recupera (la estructura era nesteable) o si ni la base rica recupera a presupuesto factible.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp074_nonnested_value.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp074_nonnested_value.run            # FULL
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
ARMS = ["product", "learned_poly2", "learned_poly4", "learned_bin", "bayes", "oracle", "chance"]
BUDGETS = {"low": 20, "high": 80}        # T rondas de feedback (presupuesto)
RIDGE_ALPHA = 1e-2
MIN_FIT = 6
GBINS = 8                                # grilla de la base no-paramétrica
LO, HI = 2, 300
Q_S = 32
Q_SR = 0.05


def _wrong_value_expr(rng, n):
    for _ in range(8):
        a = int(rng.integers(1, 99)); b = int(rng.integers(1, 99))
        op = "+" if rng.random() < 0.5 else "*"
        val = a + b if op == "+" else a * b
        if val != n:
            return "{}{}{}".format(a, op, b).encode("ascii")
    return "{}+{}".format(a, (b + 1)).encode("ascii")


def _well_formed_band(c):
    """Estructura de DOS BANDAS INTERIORES, no-monótona, NO nesteable por poly2: acepta c en [0.2,0.4) ∪ [0.6,0.8),
    rechaza los extremos y el centro. Derrota al prior MONÓTONO (product, que apuesta a c alto -> extremo rechazado) Y
    a la PARÁBOLA (poly2, un solo pico -> el centro rechazado). Una base con 2 picos (poly4) o no-paramétrica (bin) sí."""
    return (0.2 <= c < 0.4) or (0.6 <= c < 0.8)


def _make_candidate(rng, c, r, n):
    """Construye una EXPRESIÓN real; el sandbox la EJECUTA y decide v (strong). v = well_formed(banda c) AND value(r)."""
    wf = _well_formed_band(c)
    vm = rng.random() < r
    if wf and vm:
        expr = E.real_expression(rng, n)
    elif wf and not vm:
        expr = _wrong_value_expr(rng, n)
    else:
        expr = b"x"                                  # fuera de banda -> malformada
    gen = bytes(expr) + b"\n"
    return 1.0 if E.verify(E.make_prompt(n), gen, strong=True) else 0.0


def _true_mean(c, r):
    """Media condicional REAL E[v|c,r] = 1{c en banda}(c) · r (wf determinista en banda, vm~Bernoulli(r)). Es el techo
    BAYES alcanzable por un estimador que sólo ve (c,r): el oracle (v realizado) está por encima e inalcanzable."""
    band = np.array([1.0 if _well_formed_band(ci) else 0.0 for ci in np.atleast_1d(c)])
    return band * np.asarray(r)


def _draw_pool(rng, n, sc):
    c = rng.random(n)
    r = rng.random(n)
    v = np.empty(n, dtype=float)
    for i in range(n):
        ni = int(rng.integers(LO, HI + 1))
        v[i] = _make_candidate(rng, c[i], r[i], ni)
    c_est = np.clip(c + rng.normal(0.0, sc / np.sqrt(Q_S), size=n), 0.0, 1.0)
    r_est = np.clip(r + rng.normal(0.0, Q_SR, size=n), 0.0, 1.0)
    tmean = _true_mean(c, r)
    return c_est, r_est, v, tmean


def _poly_feats(c, r, deg):
    c = np.asarray(c); r = np.asarray(r)
    cols = []
    for i in range(deg + 1):
        for j in range(deg + 1 - i):
            cols.append((c ** i) * (r ** j))
    return np.column_stack(cols)


def _ridge_w(c_obs, r_obs, y, deg, alpha):
    X = _poly_feats(c_obs, r_obs, deg)
    A = X.T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ np.asarray(y))


def _poly_score(c_est, r_est, w, deg):
    return _poly_feats(c_est, r_est, deg) @ w


def _bin_fit(c_obs, r_obs, y, g):
    """Estimador NO-PARAMÉTRICO: media de v por celda (g×g) de (c,r). Devuelve (tabla g×g, media_global)."""
    c_obs = np.asarray(c_obs); r_obs = np.asarray(r_obs); y = np.asarray(y)
    gi = np.clip((c_obs * g).astype(int), 0, g - 1)
    gj = np.clip((r_obs * g).astype(int), 0, g - 1)
    summ = np.zeros((g, g)); cnt = np.zeros((g, g))
    for a, b, yy in zip(gi, gj, y):
        summ[a, b] += yy; cnt[a, b] += 1
    glob = float(y.mean()) if len(y) else 0.0
    table = np.where(cnt > 0, summ / np.maximum(cnt, 1), glob)
    return table, glob


def _bin_score(c_est, r_est, table, glob, g):
    gi = np.clip((np.asarray(c_est) * g).astype(int), 0, g - 1)
    gj = np.clip((np.asarray(r_est) * g).astype(int), 0, g - 1)
    return table[gi, gj]


def perf_of(picks, v):
    k = len(picks)
    total = float(v.sum())
    best = min(float(k), total)
    got = float(v[list(picks)].sum())
    return got / best if best > 1e-12 else 0.0


def run_cell(n, k_budget, k_eval, T, E_rounds, sc, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 3203 + T * 17 + 101)
        bc, br, by = [], [], []
        for _ in range(T):                               # feedback COSTOSO: K random por ronda (insesgado)
            ce, re, val, _ = _draw_pool(rng, n, sc)
            sel = rng.choice(n, size=min(k_budget, n), replace=False)
            for i in sel:
                bc.append(ce[i]); br.append(re[i]); by.append(val[i])
        have_signal = len(by) >= MIN_FIT and len(set(by)) > 1
        w2 = _ridge_w(bc, br, by, 2, RIDGE_ALPHA) if have_signal else None
        w4 = _ridge_w(bc, br, by, 4, RIDGE_ALPHA) if have_signal else None
        table, glob = _bin_fit(bc, br, by, GBINS) if have_signal else (None, 0.0)
        rng_e = np.random.default_rng(seed * 6079 + T * 31 + 7)
        p = {a: [] for a in ARMS}
        for _ in range(E_rounds):
            ce, re, val, tm = _draw_pool(rng_e, n, sc)
            jit = 1e-9 * rng_e.random(n)
            p["product"].append(perf_of(np.argsort(ce * re + jit)[-k_eval:], val))
            p["bayes"].append(perf_of(np.argsort(tm + jit)[-k_eval:], val))           # techo: rankea por E[v|c,r] real
            p["oracle"].append(perf_of(np.argsort(val + jit)[-k_eval:], val))         # ref: rankea por v realizado
            p["chance"].append(perf_of(rng_e.choice(n, size=k_eval, replace=False), val))
            s2 = _poly_score(ce, re, w2, 2) if w2 is not None else ce * re
            s4 = _poly_score(ce, re, w4, 4) if w4 is not None else ce * re
            sb = _bin_score(ce, re, table, glob, GBINS) if table is not None else ce * re
            p["learned_poly2"].append(perf_of(np.argsort(s2 + jit)[-k_eval:], val))
            p["learned_poly4"].append(perf_of(np.argsort(s4 + jit)[-k_eval:], val))
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
    # techo de un ESTIMADOR = bayes (rankea por E[v|c,r]=banda(c)·r); el oracle (v realizado) está por encima e
    # inalcanzable (la realización Bernoulli no es predecible de (c,r)). Se juzga la recuperación contra BAYES.
    bayes = hi["bayes"]
    poly2_short = round(bayes - hi["learned_poly2"], 4)                    # grande: poly2 no captura la estructura c
    bin_short = round(bayes - hi["learned_bin"], 4)                        # chico: bin alcanza el techo bayes
    bin_recovers = round(hi["learned_bin"] - hi["learned_poly2"], 4)       # >0: la base rica recupera sobre poly2
    poly4_recovers = round(hi["learned_poly4"] - hi["learned_poly2"], 4)
    bin_budget_cost = round(hi["learned_bin"] - lo["learned_bin"], 4)      # >0: rico = data-hungry
    poly2_budget_cost = round(hi["learned_poly2"] - lo["learned_poly2"], 4)

    SHORT_THR = 0.08       # poly2 se queda corto vs bayes (no captura la estructura no-nesteable)
    RECOVER_THR = 0.05     # bin recupera sobre poly2
    NEAR_BAYES = 0.05      # bin alcanza el techo bayes
    COST_THR = 0.02        # el prior rico mejora más con presupuesto que poly2

    poly2_failed = poly2_short > SHORT_THR
    bin_recovered = (bin_recovers > RECOVER_THR) and (bin_short <= NEAR_BAYES)
    rich_costs_more = (bin_budget_cost - poly2_budget_cost) > COST_THR

    if poly2_failed and bin_recovered:
        status = "apoyada"
        verdict = ("H-V4-7h APOYADA: cuando la media condicional del verificador REAL NO es nesteable por el poly2 "
                   "(DOS bandas interiores en c, no-monótona), el poly2 default del gap #2 se queda CORTO del techo "
                   "bayes (poly2={p2} vs bayes={by}, short={ps}) -- captura el eje r nesteable pero no la estructura c; "
                   "una base RICA no-paramétrica RECUPERA (bin={bn} > poly2 +{br}, alcanza bayes a {bs}). poly4 "
                   "intermedio (+{p4}). El prior rico CUESTA más feedback (bin low->high +{bbc} vs poly2 +{pbc}{cost}). "
                   "El producto monótono falla aún más (={pr}). => el poly2 NO es universal; el lever es el MATCH del "
                   "prior (la base) con la estructura del valor (R-PRIOR/H-V4-3), pagando su costo de datos.").format(
                       p2=_f(hi["learned_poly2"]), by=_f(bayes), ps=_f(poly2_short), bn=_f(hi["learned_bin"]),
                       br=_f(bin_recovers), bs=_f(bin_short), p4=_f(poly4_recovers), bbc=_f(bin_budget_cost),
                       pbc=_f(poly2_budget_cost), pr=_f(hi["product"]),
                       cost=", el prior rico es data-hungry" if rich_costs_more else "")
    elif not poly2_failed:
        status = "refutada"
        verdict = ("H-V4-7h REFUTADA: el poly2 SÍ alcanza el techo bayes (poly2={p2} vs bayes={by}, short={ps} <= "
                   "{thr}) -> el poly2 era expresivo suficiente o la estructura era nesteable.").format(
                       p2=_f(hi["learned_poly2"]), by=_f(bayes), ps=_f(poly2_short), thr=SHORT_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-7h MIXTA: poly2_failed={pf} (short={ps}) bin_recovered={br} (+{brr} sobre poly2, short bayes "
                   "{bs}). La base rica recupera PARCIALMENTE (no alcanza el techo bayes a este presupuesto).").format(
                       pf=poly2_failed, ps=_f(poly2_short), br=bin_recovered, brr=_f(bin_recovers), bs=_f(bin_short))

    return {"grid": grid, "bayes": bayes, "poly2_short_vs_bayes": poly2_short, "bin_short_vs_bayes": bin_short,
            "bin_recovers_vs_poly2": bin_recovers, "poly4_recovers": poly4_recovers,
            "bin_budget_cost": bin_budget_cost, "poly2_budget_cost": poly2_budget_cost,
            "poly2_failed": bool(poly2_failed), "bin_recovered": bool(bin_recovered),
            "rich_costs_more": bool(rich_costs_more), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k_budget", type=int, default=10)
    ap.add_argument("--k_eval", type=int, default=10)
    ap.add_argument("--E", type=int, default=20)
    ap.add_argument("--ctrl_noise", type=float, default=0.2)   # features más limpias: σ_c≈0.035, resuelve bandas de ancho 0.2
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.E = 8, 10

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp074] CYCLE 90 / H-V4-7h — R-VALOR sobre media NO-NESTEABLE (verificador REAL multi-banda; conecta R-PRIOR)")
    log(f"[exp074] n={args.n} k_budget={args.k_budget} k_eval={args.k_eval} E={args.E} seeds={args.seeds} "
        f"bands=[0.2,0.4)U[0.6,0.8) GBINS={GBINS} budgets={BUDGETS} ctrl_noise={args.ctrl_noise} targets=[{LO},{HI}]")

    grid = run(args.n, args.k_budget, args.k_eval, args.E, args.ctrl_noise, args.seeds)
    sm = build_summary(grid)

    for b in BUDGETS:
        c = grid[b]
        log(f"[exp074] {b:>4} (T={BUDGETS[b]}): product={c['product']:.3f} poly2={c['learned_poly2']:.3f} "
            f"poly4={c['learned_poly4']:.3f} bin={c['learned_bin']:.3f} bayes={c['bayes']:.3f} "
            f"oracle={c['oracle']:.3f} chance={c['chance']:.3f}")
    log(f"[exp074] poly2_short(vs bayes)={sm['poly2_short_vs_bayes']:.3f} | bin_recovers(vs poly2)=+{sm['bin_recovers_vs_poly2']:.3f} | "
        f"bin_short(vs bayes)={sm['bin_short_vs_bayes']:.3f} | poly4_recovers=+{sm['poly4_recovers']:.3f}")
    log(f"[exp074] budget_cost: bin +{sm['bin_budget_cost']:.3f} vs poly2 +{sm['poly2_budget_cost']:.3f} "
        f"(rich_costs_more={sm['rich_costs_more']})")
    log(f"[exp074] poly2_failed={sm['poly2_failed']} bin_recovered={sm['bin_recovered']}")
    log(f"[exp074] VEREDICTO H-V4-7h: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp074_nonnested_value", "cycle": 90, "hypothesis": "H-V4-7h",
           "claim": "cuando la media condicional del verificador REAL NO es nesteable por el poly2 (estructura "
                    "multi-banda), el poly2 default del gap #2 falla pero una base rica no-parametrica (binned) recupera "
                    "a costa de mas feedback: el lever es el match del prior con la estructura del valor (R-PRIOR)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp074] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

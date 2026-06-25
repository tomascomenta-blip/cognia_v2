r"""
exp070 — CYCLE 86 / H-V4-7d (rama R-VALOR, CAPSTONE del gap #2): ¿hace falta DETECTAR el régimen (complementos vs
sustitutos) para conmutar producto<->aprendido, o el combinador aprendido DOMINA por encima de una compuerta de calidad
de feedback, volviendo la detección INNECESARIA?

CONTEXTO: el sub-arco 83-85 estableció: (83) el producto fijo es un prior de complementariedad (se rompe bajo
sustitutos); (84) un combinador aprendido recupera bajo sustitutos, noise-gated; (85) subir la calidad del feedback
destraba la recuperación decisiva. INCIDENTALMENTE 84-85 mostraron que bajo COMPLEMENTOS el aprendido ≈ producto. Si eso
se sostiene, ALWAYS-LEARN domina (≥ producto en complementos, > en sustitutos) y un detector de régimen es INNECESARIO:
la política práctica sería una COMPUERTA DE CALIDAD DE FEEDBACK (aprendido si el feedback es adecuado, producto si es
pobre), NO un switch por régimen.

TAREA: idéntica a exp067-069. Familias COMPLEMENTOS (g=min) y SUSTITUTOS (g=max), λ=1.0. Combinador aprendido por ridge
poly2 de m=20 obs de valor real. Eje: calidad del feedback (q0..clean, como exp069). Brazos:
  - oracle:           top-k por value verdadero (cota).
  - always_product:   ctrl_est × rel_est (el prior fijo).
  - always_learned:   learned_poly2 ajustado de las m obs.
  - selector:         DETECTA el régimen — CV held-out sobre las m obs (corr con valor observado) elige producto vs
                      aprendido, luego rankea con el elegido.
  - oracle_selector:  por seed, el mejor de {producto, aprendido} por perf REAL (cota de un detector PERFECTO).
  - random.

PREDICCIÓN FALSABLE (compuerta a calidad q2; tol=0.02):
  - APOYADA si (DOMINACIÓN) existe una compuerta de calidad no-perfecta sobre la cual always_learned >= always_product
    en complementos (>= -0.01) y > en sustitutos (+>0.02), Y (DETECCIÓN INNECESARIA) always_learned está dentro de tol
    del oracle_selector y el selector real NO supera a always_learned por > tol. => la política es una compuerta de
    feedback, no un detector de régimen.
  - REFUTADA si hay un régimen donde always_learned PIERDE vs producto con feedback adecuado (la dominación falla), o si
    el selector supera a always_learned por > tol (detectar el régimen SÍ aporta).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp070_regime_policy.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp070_regime_policy.run            # FULL
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
ARMS = ["oracle", "always_product", "always_learned", "selector", "oracle_selector", "random"]
FAMILIES = ["comp", "subs"]
QUAL = [("q0", 2, 0.20, False), ("q1", 8, 0.10, False), ("q2", 32, 0.05, False), ("clean", 0, 0.0, True)]
NONCLEAN = ["q0", "q1", "q2"]
LAM = 1.0
RIDGE_ALPHA = 1e-2
N_SPLITS = 4
QID = {"q0": 0, "q1": 1, "q2": 2, "clean": 3}
FAM_ID = {"comp": 1, "subs": 2}
TOL = 0.02


def perf_of(picks, value):
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _value(ctrl, rel, fam, lam):
    prod = ctrl * rel
    g = np.minimum(ctrl, rel) if fam == "comp" else np.maximum(ctrl, rel)
    return (1.0 - lam) * prod + lam * g


def _feats_poly2(c, r):
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _ridge_w(X, y, alpha):
    A = X.T @ X + alpha * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ y)


def _corr(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _select_regime(ctrl_est, rel_est, obs_idx, value, rng):
    # Detecta el régimen: CV held-out sobre las m obs. Compara corr(producto, valor) vs corr(aprendido, valor) en val.
    obs = np.asarray(obs_idx)
    prod_obs = ctrl_est[obs] * rel_est[obs]
    val_obs = value[obs]
    n_obs = len(obs)
    n_tr = max(3, int(round(0.6 * n_obs)))
    c_prod, c_learn = [], []
    for _ in range(N_SPLITS):
        perm = rng.permutation(n_obs)
        tr, va = perm[:n_tr], perm[n_tr:]
        if len(va) < 2:
            continue
        w = _ridge_w(_feats_poly2(ctrl_est[obs[tr]], rel_est[obs[tr]]), val_obs[tr], RIDGE_ALPHA)
        learn_va = _feats_poly2(ctrl_est[obs[va]], rel_est[obs[va]]) @ w
        c_prod.append(_corr(prod_obs[va], val_obs[va]))
        c_learn.append(_corr(learn_va, val_obs[va]))
    use_learned = (np.mean(c_learn) if c_learn else 0.0) >= (np.mean(c_prod) if c_prod else 0.0)
    if use_learned:
        w_full = _ridge_w(_feats_poly2(ctrl_est[obs], rel_est[obs]), val_obs, RIDGE_ALPHA)
        return _feats_poly2(ctrl_est, rel_est) @ w_full, "learned"
    return ctrl_est * rel_est, "product"


def run_cell(n, k, fam, label, S, sr, clean, sc, m, n_seeds):
    acc = {a: [] for a in ARMS}
    chose_learned = 0
    total = 0
    for seed in range(n_seeds):
        base = seed * 1009 + FAM_ID[fam] * 131 + QID[label] * 53 + m * 17 + S
        rng = np.random.default_rng(base)
        ctrl = rng.random(n)
        rel = rng.random(n)
        value = _value(ctrl, rel, fam, LAM)
        tb = rng.random(n)
        if clean:
            ctrl_est, rel_est = ctrl, rel
        else:
            ctrl_est = np.clip(ctrl + rng.normal(0.0, sc / np.sqrt(S), size=n), 0.0, 1.0)
            rel_est = np.clip(rel + rng.normal(0.0, sr, size=n), 0.0, 1.0)
        obs_idx = rng.choice(n, size=min(m, n), replace=False)
        w_all = _ridge_w(_feats_poly2(ctrl_est[obs_idx], rel_est[obs_idx]), value[obs_idx], RIDGE_ALPHA)
        learned_score = _feats_poly2(ctrl_est, rel_est) @ w_all
        prod_score = ctrl_est * rel_est
        sel_score, choice = _select_regime(ctrl_est, rel_est, obs_idx, value, rng)
        chose_learned += int(choice == "learned"); total += 1

        picks_prod = np.argsort(prod_score + 1e-9 * tb)[-k:]
        picks_learned = np.argsort(learned_score + 1e-9 * tb)[-k:]
        perf_prod = perf_of(picks_prod, value)
        perf_learned = perf_of(picks_learned, value)
        picks = {
            "oracle": np.argsort(value + 1e-9 * tb)[-k:],
            "always_product": picks_prod,
            "always_learned": picks_learned,
            "selector": np.argsort(sel_score + 1e-9 * tb)[-k:],
            "random": rng.choice(n, size=k, replace=False),
        }
        acc["oracle"].append(perf_of(picks["oracle"], value))
        acc["always_product"].append(perf_prod)
        acc["always_learned"].append(perf_learned)
        acc["selector"].append(perf_of(picks["selector"], value))
        acc["oracle_selector"].append(max(perf_prod, perf_learned))
        acc["random"].append(perf_of(picks["random"], value))
    out = {a: round(float(np.mean(acc[a])), 4) for a in ARMS}
    out["_frac_chose_learned"] = round(chose_learned / max(1, total), 3)
    return out


def run(n, k, sc, m, n_seeds):
    grid = {}
    for fam in FAMILIES:
        for (label, S, sr, clean) in QUAL:
            grid["{}_{}".format(fam, label)] = run_cell(n, k, fam, label, S, sr, clean, sc, m, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid, n, k, q_ref="q2"):
    def dom(fam, q):
        c = grid["{}_{}".format(fam, q)]
        return c["always_learned"] - c["always_product"]

    # compuerta de dominación: primer nivel NO-clean donde learned >= product-0.01 en comp y > +0.02 en subs
    gate = None
    for q in NONCLEAN:
        if dom("comp", q) >= -0.01 and dom("subs", q) > 0.02:
            gate = q
            break

    # a calidad de referencia: ¿el selector supera a always_learned? ¿always_learned ~ oracle_selector?
    sel_minus_al = np.mean([grid["{}_{}".format(f, q_ref)]["selector"] - grid["{}_{}".format(f, q_ref)]["always_learned"]
                            for f in FAMILIES])
    oraclesel_minus_al = np.mean([grid["{}_{}".format(f, q_ref)]["oracle_selector"] - grid["{}_{}".format(f, q_ref)]["always_learned"]
                                  for f in FAMILIES])
    detection_unnecessary = (sel_minus_al <= TOL) and (oraclesel_minus_al <= TOL)
    dominates = gate is not None

    dom_comp = round(dom("comp", q_ref), 4)
    dom_subs = round(dom("subs", q_ref), 4)
    sel_minus_al = round(float(sel_minus_al), 4)
    oraclesel_minus_al = round(float(oraclesel_minus_al), 4)

    if dominates and detection_unnecessary:
        status = "apoyada"
        verdict = ("H-V4-7d APOYADA: el combinador aprendido DOMINA por encima de una compuerta de calidad de feedback "
                   "(gate={gate}) -> la detección de régimen es INNECESARIA. A calidad {qr}: always_learned vence al "
                   "producto en sustitutos (+{ds}) y lo iguala en complementos ({dc}); el oracle_selector (detector "
                   "PERFECTO) supera a always_learned sólo por {os} (<= {tol}) y el selector real por {sl} (<= {tol}). "
                   "=> ni un detector perfecto aporta sobre 'siempre aprender': la política práctica de reconstrucción "
                   "de R-VALOR es una COMPUERTA DE CALIDAD DE FEEDBACK (aprendido si el feedback es adecuado, producto si "
                   "es pobre), NO un switch por régimen.").format(
                       gate=gate, qr=q_ref, ds=_f(dom_subs), dc=_f(dom_comp), os=_f(oraclesel_minus_al),
                       sl=_f(sel_minus_al), tol=_f(TOL))
    elif not dominates:
        status = "refutada"
        verdict = ("H-V4-7d REFUTADA (la dominación falla): hay un régimen donde always_learned NO domina al producto con "
                   "feedback adecuado (a {qr}: comp dom={dc}, subs dom={ds}) -> se necesita el producto en algún régimen; "
                   "un switch/compuerta es necesario.").format(qr=q_ref, dc=_f(dom_comp), ds=_f(dom_subs))
    elif sel_minus_al > TOL:
        status = "refutada"
        verdict = ("H-V4-7d REFUTADA (la detección SÍ aporta): el selector supera a always_learned por {sl} (> {tol}) -> "
                   "detectar el régimen mejora sobre 'siempre aprender'.").format(sl=_f(sel_minus_al), tol=_f(TOL))
    else:
        status = "mixta"
        verdict = ("H-V4-7d MIXTA: dominación parcial / patrón intermedio (gate={gate}, dom comp={dc}, subs={ds}, "
                   "oracle_selector−always_learned={os}, selector−always_learned={sl}).").format(
                       gate=gate, dc=_f(dom_comp), ds=_f(dom_subs), os=_f(oraclesel_minus_al), sl=_f(sel_minus_al))

    return {"grid": grid, "q_ref": q_ref, "gate_quality": gate, "dominates": bool(dominates),
            "detection_unnecessary": bool(detection_unnecessary), "dom_comp_qref": dom_comp, "dom_subs_qref": dom_subs,
            "selector_minus_always_learned": sel_minus_al, "oracle_selector_minus_always_learned": oraclesel_minus_al,
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--ctrl_noise", type=float, default=0.5)
    ap.add_argument("--m", type=int, default=20)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 16

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp070] CYCLE 86 / H-V4-7d — ¿detectar régimen o el aprendido domina sobre una compuerta de feedback?")
    log(f"[exp070] n={args.n} k={args.k} ctrl_noise={args.ctrl_noise} m={args.m} seeds={args.seeds} "
        f"qualities={[q[0] for q in QUAL]} (λ={LAM})")

    grid = run(args.n, args.k, args.ctrl_noise, args.m, args.seeds)
    sm = build_summary(grid, args.n, args.k)

    for fam in FAMILIES:
        for lab, _, _, _ in QUAL:
            c = grid["{}_{}".format(fam, lab)]
            log(f"[exp070] {fam}/{lab}: prod={c['always_product']:.3f} learned={c['always_learned']:.3f} "
                f"selector={c['selector']:.3f} oracle_sel={c['oracle_selector']:.3f} (chose_learned={c['_frac_chose_learned']})")
    log(f"[exp070] gate_dominación={sm['gate_quality']} | a {sm['q_ref']}: dom comp={sm['dom_comp_qref']:.3f} subs={sm['dom_subs_qref']:.3f} "
        f"| oracle_sel−learned={sm['oracle_selector_minus_always_learned']:.3f} selector−learned={sm['selector_minus_always_learned']:.3f} "
        f"| detection_unnecessary={sm['detection_unnecessary']}")
    log(f"[exp070] VEREDICTO H-V4-7d: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp070_regime_policy", "cycle": 86, "hypothesis": "H-V4-7d",
           "claim": "el combinador aprendido domina al producto sobre una compuerta de calidad de feedback en ambos "
                    "regimenes; la deteccion de regimen es innecesaria (politica = compuerta de feedback)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp070] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

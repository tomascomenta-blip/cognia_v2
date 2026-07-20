r"""
exp069 — CYCLE 85 / H-V4-7c (rama R-VALOR, cierre del noise-gating del gap #2): ¿subir la CALIDAD DEL FEEDBACK vuelve la
recuperación del combinador aprendido de PARCIAL a DECISIVA bajo sustitutos?

CONTEXTO: CYCLE 84 (exp068) mostró que un combinador APRENDIDO recupera el régimen de sustitutos (donde el producto se
rompe) pero la ganancia es NOISE-GATED: decisiva sólo con estimadores limpios. El constraint vinculante NO es el
presupuesto de observaciones m (que platea), sino el RUIDO DE LAS FEATURES (ctrl_est, rel_est): el combinador rankea
con features ruidosas en test, lo que pone un techo. Aquí se sube la calidad del feedback (más muestras S de control ->
ctrl_est menos ruidoso; menor σr de relevancia) y se pregunta: ¿a partir de qué nivel de calidad la recuperación pasa a
DECISIVA (+>0.03 sobre el producto), sin necesidad de feedback perfecto?

TAREA: idéntica a exp067/068, régimen SUSTITUTOS (g=max, λ=1.0, donde el producto fijo se rompe) + COMPLEMENTOS de
control. El agente aprende por ridge poly2 [1,c,r,c²,r²,cr] de m=20 observaciones de valor real. Eje primario: CALIDAD
DEL FEEDBACK, niveles (S muestras de control, σr ruido de relevancia):
  q0=(S=2,  σr=0.20)   feedback pobre
  q1=(S=8,  σr=0.10)   feedback realista (el punto de CYCLE 84)
  q2=(S=32, σr=0.05)   feedback moderado
  q3=(S=128,σr=0.02)   feedback alto
  clean=(perfecto)     cota
Brazos: oracle, empowerment, relevance, rvalue_prod, learned_lin, learned_poly2, random.

PREDICCIÓN FALSABLE (subs λ=1.0): adv = learned_poly2 − rvalue_prod.
  - APOYADA si adv cruza +0.03 (DECISIVO) en un nivel de feedback NO perfecto y MODERADO (q2 o antes) Y crece con la
    calidad (improves_with_quality): subir el feedback flip-ea la recuperación a decisiva sin necesitar feedback perfecto.
  - MIXTA si sólo cruza +0.03 en feedback ALTO (q3, casi perfecto): necesita feedback muy nítido.
  - REFUTADA si adv sólo cruza +0.03 con feedback PERFECTO (clean) o nunca: el noise-gating es una pared dura.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp069_feedback_quality.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp069_feedback_quality.run            # FULL
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
ARMS = ["oracle", "empowerment", "relevance", "rvalue_prod", "learned_lin", "learned_poly2", "random"]
FAMILIES = ["subs", "comp"]
# (label, S, sr, clean). Eje de calidad del feedback de peor a perfecto.
QUAL = [("q0", 2, 0.20, False), ("q1", 8, 0.10, False), ("q2", 32, 0.05, False),
        ("q3", 128, 0.02, False), ("clean", 0, 0.0, True)]
NONCLEAN = ["q0", "q1", "q2", "q3"]
LAM = 1.0
RIDGE_ALPHA = 1e-2
QID = {"q0": 0, "q1": 1, "q2": 2, "q3": 3, "clean": 4}
FAM_ID = {"subs": 2, "comp": 1}


def perf_of(picks, value):
    k = len(picks)
    best = np.sort(value)[-k:].sum()
    got = value[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _value(ctrl, rel, fam, lam):
    prod = ctrl * rel
    g = np.minimum(ctrl, rel) if fam == "comp" else np.maximum(ctrl, rel)
    return (1.0 - lam) * prod + lam * g


def _feats_lin(c, r):
    return np.column_stack([np.ones_like(c), c, r])


def _feats_poly2(c, r):
    return np.column_stack([np.ones_like(c), c, r, c * c, r * r, c * r])


def _ridge_predict(feat_fn, c, r, obs_idx, value, alpha):
    X = feat_fn(c[obs_idx], r[obs_idx])
    y = value[obs_idx]
    A = X.T @ X + alpha * np.eye(X.shape[1])
    w = np.linalg.solve(A, X.T @ y)
    return feat_fn(c, r) @ w


def run_cell(n, k, fam, label, S, sr, clean, sc, m, n_seeds):
    acc = {a: [] for a in ARMS}
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
        pred_lin = _ridge_predict(_feats_lin, ctrl_est, rel_est, obs_idx, value, RIDGE_ALPHA)
        pred_poly2 = _ridge_predict(_feats_poly2, ctrl_est, rel_est, obs_idx, value, RIDGE_ALPHA)
        picks = {
            "oracle": np.argsort(value + 1e-9 * tb)[-k:],
            "empowerment": np.argsort(ctrl_est + 1e-9 * tb)[-k:],
            "relevance": np.argsort(rel_est + 1e-9 * tb)[-k:],
            "rvalue_prod": np.argsort(ctrl_est * rel_est + 1e-9 * tb)[-k:],
            "learned_lin": np.argsort(pred_lin + 1e-9 * tb)[-k:],
            "learned_poly2": np.argsort(pred_poly2 + 1e-9 * tb)[-k:],
            "random": rng.choice(n, size=k, replace=False),
        }
        for a in ARMS:
            acc[a].append(perf_of(picks[a], value))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, sc, m, n_seeds):
    grid = {}
    for fam in FAMILIES:
        for (label, S, sr, clean) in QUAL:
            grid["{}_{}".format(fam, label)] = run_cell(n, k, fam, label, S, sr, clean, sc, m, n_seeds)
    return grid


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid, n, k):
    adv_subs = {lab: round(grid["subs_{}".format(lab)]["learned_poly2"] - grid["subs_{}".format(lab)]["rvalue_prod"], 4)
                for lab, _, _, _ in QUAL}
    # primer nivel NO-clean donde la recuperación es DECISIVA (adv>0.03)
    crossover = None
    for lab in NONCLEAN:
        if adv_subs[lab] > 0.03:
            crossover = lab
            break
    improves = adv_subs["q3"] > adv_subs["q0"] + 0.02
    # no-sacrifica complementos en todos los niveles (el producto ya gana en comp; aprender no debe destruirlo)
    comp_ok = all(grid["comp_{}".format(lab)]["learned_poly2"] >= grid["comp_{}".format(lab)]["rvalue_prod"] - 0.05
                  for lab, _, _, _ in QUAL)

    decisive_moderate = crossover in ("q0", "q1", "q2")
    decisive_high = crossover == "q3"

    if decisive_moderate and improves and comp_ok:
        status = "apoyada"
        verdict = ("H-V4-7c APOYADA: subir la CALIDAD DEL FEEDBACK vuelve la recuperación del combinador aprendido de "
                   "PARCIAL a DECISIVA bajo sustitutos, SIN necesitar feedback perfecto. adv(poly2−producto) por calidad: "
                   "q0={a0}, q1(realista)={a1}, q2={a2}, q3={a3}, clean={ac}. Cruza el umbral decisivo (+0.03) ya en "
                   "feedback MODERADO ({xo}: S/σr mejorados, no perfectos) y crece monótono con la calidad. No sacrifica "
                   "complementos. => el noise-gating de CYCLE 84 NO es una pared dura: con más muestras de control y menos "
                   "ruido de relevancia, aprender la forma no-factorizable recupera DECISIVAMENTE el valor de "
                   "sustitutos.").format(
                       a0=_f(adv_subs["q0"]), a1=_f(adv_subs["q1"]), a2=_f(adv_subs["q2"]), a3=_f(adv_subs["q3"]),
                       ac=_f(adv_subs["clean"]), xo=crossover)
    elif decisive_high and comp_ok:
        status = "mixta"
        verdict = ("H-V4-7c MIXTA: la recuperación se vuelve decisiva SÓLO con feedback ALTO/casi-perfecto (q3), no con "
                   "feedback moderado. adv por calidad: q0={a0}, q1={a1}, q2={a2}, q3={a3}, clean={ac}. El noise-gating "
                   "se afloja pero exige feedback muy nítido.").format(
                       a0=_f(adv_subs["q0"]), a1=_f(adv_subs["q1"]), a2=_f(adv_subs["q2"]), a3=_f(adv_subs["q3"]),
                       ac=_f(adv_subs["clean"]))
    else:
        status = "refutada"
        verdict = ("H-V4-7c REFUTADA: subir la calidad del feedback NO vuelve la recuperación decisiva salvo con feedback "
                   "PERFECTO (o nunca). adv por calidad: q0={a0}, q1={a1}, q2={a2}, q3={a3}, clean={ac} "
                   "(improves_with_quality={imp}, comp_ok={co}). El noise-gating es una pared dura: con features ruidosas "
                   "el techo persiste.").format(
                       a0=_f(adv_subs["q0"]), a1=_f(adv_subs["q1"]), a2=_f(adv_subs["q2"]), a3=_f(adv_subs["q3"]),
                       ac=_f(adv_subs["clean"]), imp=improves, co=comp_ok)

    return {"grid": grid, "adv_subs": {k2: v for k2, v in adv_subs.items()}, "crossover_quality": crossover,
            "improves_with_quality": bool(improves), "comp_no_sacrifice": bool(comp_ok),
            "decisive_moderate": bool(decisive_moderate), "decisive_high": bool(decisive_high),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=64)
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

    log("[exp069] CYCLE 85 / H-V4-7c — ¿subir la calidad del feedback vuelve decisiva la recuperación aprendida?")
    log(f"[exp069] n={args.n} k={args.k} ctrl_noise={args.ctrl_noise} m={args.m} seeds={args.seeds} "
        f"qualities={[q[0] for q in QUAL]} (λ={LAM})")

    grid = run(args.n, args.k, args.ctrl_noise, args.m, args.seeds)
    sm = build_summary(grid, args.n, args.k)

    for fam in FAMILIES:
        row = []
        for lab, _, _, _ in QUAL:
            c = grid["{}_{}".format(fam, lab)]
            row.append("{}: prod={:.3f} poly2={:.3f} bm={:.3f}".format(
                lab, c["rvalue_prod"], c["learned_poly2"], max(c["empowerment"], c["relevance"])))
        log(f"[exp069] {fam}/λ{LAM}: " + " | ".join(row))
    log(f"[exp069] subs adv(poly2−prod) por calidad: {sm['adv_subs']} | crossover decisivo (+0.03) = {sm['crossover_quality']} "
        f"| improves={sm['improves_with_quality']} comp_ok={sm['comp_no_sacrifice']}")
    log(f"[exp069] VEREDICTO H-V4-7c: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp069_feedback_quality", "cycle": 85, "hypothesis": "H-V4-7c",
           "claim": "subir la calidad del feedback (mas muestras S de control, menos ruido de relevancia) vuelve la "
                    "recuperacion del combinador aprendido de parcial a decisiva bajo sustitutos sin feedback perfecto",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp069] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

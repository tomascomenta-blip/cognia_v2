r"""
exp090 — CYCLE 106 / H-V4-8k (rama R-VALOR, ata CALIBRACIÓN con el arco de asignación): el lab mostró que la confianza
endógena CALIBRADA es una señal de valor (CYCLE 57/60). ¿Cuándo importa la CALIBRACIÓN (la ESCALA del valor estimado),
y cuándo basta el RANKING (el orden)? HIPÓTESIS: para decisiones de RANKING (top-k) sólo cuenta el orden -> la calibración
es IRRELEVANTE; para decisiones que comparan el valor con una ESCALA EXTERNA (ABSTENCIÓN/umbral, CYCLE 104; costo-vs-valor,
CYCLE 101) la calibración es NECESARIA (la escala debe ser correcta).

CONTEXTO. Une dos hilos: la calibración de la confianza (57/60) y el arco de asignación (101 cost-threshold, 104
abstención/timing). Distingue QUÉ propiedad del estimador de valor importa para QUÉ decisión: orden (ranking) vs escala
(abstención/costo).

DISEÑO (numpy). Ítems con valor REAL v~U(0,1). Estimador de valor:
  - calibrado:    v_est = v + ruido (escala correcta).
  - miscalibrado: v_est = g(v) + ruido, g monótona pero distorsiona la ESCALA (g(v)=v² -> mismo ORDEN, escala mal).
Dos tipos de DECISIÓN:
  - rank:    elegir top-k por v_est. perf = Σv_real(picks) / Σv_real(oracle top-k). (Sólo cuenta el orden.)
  - abstain: ACTUAR sobre el ítem sii v_est > c (c = costo/umbral externo en la escala REAL); reward = Σ(v−c) sobre los
             actuados / Σ(v−c) sobre {v>c} (oracle). (Cuenta la ESCALA: actuar sii el valor real supera el costo.)

PREGUNTA FALSABLE:
  - APOYADA si para RANK calibrado ≈ miscalibrado (|Δ|<=0.03; la calibración no importa para rankear) Y para ABSTAIN
    calibrado >> miscalibrado (+>0.05; la escala mal hace abstener/actuar mal). => la calibración del valor es NECESARIA
    exactamente para decisiones valor-vs-escala-externa (abstención/costo), no para ranking.
  - REFUTADA si la calibración no separa las dos decisiones (importa igual o nada en ambas).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp090_calibration_decisions.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp090_calibration_decisions.run            # FULL
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
ARMS = ["calibrated", "miscalibrated", "oracle", "chance"]
DECISIONS = ["rank", "abstain"]
DEC_ID = {"rank": 0, "abstain": 1}


def _rank_perf(picks, v, k):
    best = np.sort(v)[-k:].sum()
    got = v[list(picks)].sum()
    return float(got / best) if best > 1e-12 else 0.0


def _abstain_perf(acted_mask, v, c):
    opt = float(np.sum(np.maximum(0.0, v - c)))               # oracle: actuar sii v>c
    got = float(np.sum((v - c) * acted_mask))                 # lo logrado actuando donde v_est>c
    return got / opt if opt > 1e-12 else 0.0


def run_cell(n, k, c, decision, noise, n_seeds):
    acc = {a: [] for a in ARMS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed * 487 + DEC_ID[decision] * 31 + 5)
        v = rng.random(n)
        v_calib = np.clip(v + rng.normal(0.0, noise, size=n), 0.0, 1.0)
        v_miscal = np.clip(v ** 2 + rng.normal(0.0, noise, size=n), 0.0, 1.0)   # monótona, escala distorsionada
        if decision == "rank":
            acc["calibrated"].append(_rank_perf(np.argsort(v_calib)[-k:], v, k))
            acc["miscalibrated"].append(_rank_perf(np.argsort(v_miscal)[-k:], v, k))
            acc["oracle"].append(_rank_perf(np.argsort(v)[-k:], v, k))
            acc["chance"].append(_rank_perf(rng.choice(n, size=k, replace=False), v, k))
        else:
            acc["calibrated"].append(_abstain_perf((v_calib > c).astype(float), v, c))
            acc["miscalibrated"].append(_abstain_perf((v_miscal > c).astype(float), v, c))
            acc["oracle"].append(_abstain_perf((v > c).astype(float), v, c))
            acc["chance"].append(_abstain_perf((rng.random(n) > 0.5).astype(float), v, c))
    return {a: round(float(np.mean(acc[a])), 4) for a in ARMS}


def run(n, k, c, noise, n_seeds):
    return {d: run_cell(n, k, c, d, noise, n_seeds) for d in DECISIONS}


def _f(x):
    return "{:.3f}".format(x)


def build_summary(grid):
    rk, ab = grid["rank"], grid["abstain"]
    rank_gap = round(abs(rk["calibrated"] - rk["miscalibrated"]), 4)        # ~0 esperado (calibración irrelevante)
    abstain_gain = round(ab["calibrated"] - ab["miscalibrated"], 4)         # >0.05 esperado (calibración necesaria)

    RANK_TOL = 0.03
    ABSTAIN_THR = 0.05

    rank_indiff = rank_gap <= RANK_TOL
    abstain_needs_calib = abstain_gain > ABSTAIN_THR

    if rank_indiff and abstain_needs_calib:
        status = "apoyada"
        verdict = ("H-V4-8k APOYADA: la CALIBRACIÓN del valor estimado importa EXACTAMENTE para decisiones valor-vs-escala "
                   "(abstención/umbral), NO para ranking. RANK (top-k, sólo orden): calibrado={rc} ≈ miscalibrado={rm} (Δ "
                   "{rg}: la calibración es IRRELEVANTE -- el orden basta). ABSTAIN (actuar sii v_est>c, escala externa): "
                   "calibrado={ac} >> miscalibrado={am} (+{ag}: la escala mal hace actuar/abstener mal). => para rankear "
                   "(qué elegir) sólo se necesita el ORDEN del valor; para abstener / comparar con un costo se necesita la "
                   "ESCALA correcta (calibración, CYCLE 57/60). Distingue qué propiedad del estimador R-VALOR importa para "
                   "qué decisión del arco (ranking 83-103 vs costo 101 / abstención 104).").format(
                       rc=_f(rk["calibrated"]), rm=_f(rk["miscalibrated"]), rg=_f(rank_gap), ac=_f(ab["calibrated"]),
                       am=_f(ab["miscalibrated"]), ag=_f(abstain_gain))
    elif not abstain_needs_calib:
        status = "refutada"
        verdict = ("H-V4-8k REFUTADA: la calibración tampoco importa para abstención (calibrado={ac} ≈ miscalibrado={am}, "
                   "Δ {ag} <= {thr}) -> la escala del valor no cambia la decisión.").format(
                       ac=_f(ab["calibrated"]), am=_f(ab["miscalibrated"]), ag=_f(abstain_gain), thr=ABSTAIN_THR)
    else:
        status = "mixta"
        verdict = ("H-V4-8k MIXTA: rank_indiff={ri}(Δ {rg}) abstain_needs_calib={an}(+{ag}) -- la separación no es "
                   "limpia.").format(ri=rank_indiff, rg=_f(rank_gap), an=abstain_needs_calib, ag=_f(abstain_gain))

    return {"grid": grid, "rank_gap": rank_gap, "abstain_gain": abstain_gain, "rank_indiff": bool(rank_indiff),
            "abstain_needs_calib": bool(abstain_needs_calib), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--c", type=float, default=0.5)
    ap.add_argument("--noise", type=float, default=0.05)
    args = ap.parse_args()
    if args.smoke:
        args.seeds = 12

    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp090] CYCLE 106 / H-V4-8k — calibración del valor: irrelevante para ranking, necesaria para abstención/escala")
    log(f"[exp090] n={args.n} k={args.k} c={args.c} noise={args.noise} seeds={args.seeds} decisiones={DECISIONS}")

    grid = run(args.n, args.k, args.c, args.noise, args.seeds)
    sm = build_summary(grid)

    for d in DECISIONS:
        cc = grid[d]
        log(f"[exp090] decision={d:>8}: calibrated={cc['calibrated']:.3f} miscalibrated={cc['miscalibrated']:.3f} "
            f"oracle={cc['oracle']:.3f} chance={cc['chance']:.3f}")
    log(f"[exp090] RANK: |calib−miscal|={sm['rank_gap']:.3f} (calibración irrelevante) | ABSTAIN: calib−miscal=+{sm['abstain_gain']:.3f} (calibración necesaria)")
    log(f"[exp090] rank_indiff={sm['rank_indiff']} abstain_needs_calib={sm['abstain_needs_calib']}")
    log(f"[exp090] VEREDICTO H-V4-8k: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp090_calibration_decisions", "cycle": 106, "hypothesis": "H-V4-8k",
           "claim": "la calibracion (escala) del valor estimado importa exactamente para decisiones valor-vs-escala-externa "
                    "(abstencion/umbral CYCLE 104, costo-vs-valor CYCLE 101), NO para ranking (top-k, donde solo cuenta el "
                    "orden): un estimador miscalibrado pero bien-ordenado rankea igual pero abstiene/actua mal",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp090] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

r"""
exp043 — CYCLE 57 / H-V4-1c: ¿hay una señal de valor ENDÓGENA (la propia confianza del agente, SIN oráculo) que
(a) rankee info-gain por encima del azar-activo y (b) esté CALIBRADA (confiado => correcto)?

CONTEXTO: exp042 (CYCLE 56, H-V4-1b, APOYADA) aisló el valor de info-gain con post_on_cause = masa sobre la
causa VERDADERA — pero eso usa un ORÁCULO de evaluación (conocer c). Límite #1: ¿el AGENTE puede saber que
construyó un mejor modelo SIN conocer c? Su única señal endógena es su PROPIA confianza: max del posterior
(cuánta masa concentró en SU mejor hipótesis) y su entropía. Si esa confianza (1) rankea info-gain > azar igual
que el oráculo, y (2) es CALIBRADA (cuando está confiado, ACIERTA la causa real; pocas veces confiado-pero-
equivocado), entonces el agente tiene una señal de VALOR confiable y endógena -> base de R-VALOR.

PELIGRO a medir: confiado-PERO-equivocado (max_post alto pero argmax != c). En el mundo confundido un agente
podría concentrarse (alta confianza) en una feature ESPURIA del clúster. Si info-gain evita eso (intervención
discrimina) y el azar-activo cae más, info-gain tiene una señal endógena MÁS confiable.

DISEÑO (reusa exp022.run_agent / make_world). Régimen DURO (D=48, cluster=14, p_obs=0.20) y FÁCIL. Por
(seed, K, agente) corre el agente y registra: conf = max(posterior) [ENDÓGENA], correct = (argmax==c) [eval con
oráculo, SÓLO para validar la calibración], entropy. Agrega por agente: conf media, P(correct|confiado>=τ)
[calibración], confidently_wrong = P(conf>=τ AND wrong). 48 seeds. τ=0.5.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si en el régimen DURO: (a) conf media de B (info-gain) > C (azar) [la señal endógena RANKEA igual
    que el oráculo de exp042] Y (b) B está CALIBRADO (P(correct|confiado)>=0.80) con confidently_wrong_B BAJO
    (< confidently_wrong_C y < 0.15). => el agente puede SELECCIONAR la mejor política por su propia confianza,
    sin oráculo.
  - REFUTADA si la conf endógena NO rankea B>C (señal inútil) o B es MISCALIBRADO (confiado-pero-equivocado
    frecuente, >=0.30).
  - MIXTA si rankea B>C pero la calibración es imperfecta (0.15<=confidently_wrong_B<0.30).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp043_endogenous_signal.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp043_endogenous_signal.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp022_endogenous_value.run import make_world, run_agent

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
EASY = {"D": 12, "cluster": 4, "p_obs": 0.10}
HARD = {"D": 48, "cluster": 14, "p_obs": 0.20}
MODES = [("A_pasivo", "passive"), ("B_infogain", "infogain"), ("C_aleatorio", "random")]
MODE_OFFSET = {"passive": 1, "infogain": 2, "random": 3}


def entropy_bits(p):
    p = p[p > 1e-12]
    return float(-(p * np.log2(p)).sum())


def run_regime(reg, budgets, n_seeds, cand_pool):
    """Por (seed,K,agente): conf=max(post) ENDÓGENA, correct=(argmax==c) [validación], entropy."""
    D, cluster, p_obs = reg["D"], reg["cluster"], reg["p_obs"]
    rows = []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        c, cluster_idx = make_world(rng, D, cluster)
        for K in budgets:
            for name, mode in MODES:
                arng = np.random.default_rng(seed * 100003 + K * 101 + MODE_OFFSET[mode])
                post = run_agent(arng, mode, K, D, c, cluster_idx, p_obs, cand_pool)
                rows.append({"seed": seed, "K": K, "agent": name, "conf": float(post.max()),
                             "correct": int(int(np.argmax(post)) == c), "entropy": entropy_bits(post),
                             "post_on_cause": float(post[c])})
    return rows


def agg_regime(rows, budgets, tau):
    out = {}
    for K in budgets:
        cell = {}
        for name, _ in MODES:
            r = [x for x in rows if x["K"] == K and x["agent"] == name]
            conf = np.array([x["conf"] for x in r])
            corr = np.array([x["correct"] for x in r])
            confident = conf >= tau
            calib = float(corr[confident].mean()) if confident.any() else float("nan")
            cw = float((confident & (corr == 0)).mean())          # confiado-pero-equivocado
            cell[name] = {"conf_mean": float(conf.mean()), "correct_mean": float(corr.mean()),
                          "frac_confident": float(confident.mean()),
                          "calibration_P_correct_given_confident": calib, "confidently_wrong": cw,
                          "entropy_mean": float(np.mean([x["entropy"] for x in r]))}
        out[str(K)] = cell
    return out


def build_summary(easy_rows, hard_rows, budgets, n_seeds, tau):
    Kmax = max(budgets)
    e = agg_regime(easy_rows, budgets, tau)
    h = agg_regime(hard_rows, budgets, tau)
    B, C = h[str(Kmax)]["B_infogain"], h[str(Kmax)]["C_aleatorio"]
    endo_ranks = B["conf_mean"] > C["conf_mean"]
    calib_B = B["calibration_P_correct_given_confident"]
    cw_B, cw_C = B["confidently_wrong"], C["confidently_wrong"]
    well_calibrated = (calib_B >= 0.80) and (cw_B < 0.15) and (cw_B < cw_C + 1e-9)

    if (not endo_ranks) or (cw_B >= 0.30) or (not np.isnan(calib_B) and calib_B < 0.55):
        status = "refutada"
        verdict = ("H-V4-1c REFUTADA: la confianza ENDÓGENA no sirve para elegir la política — no rankea B>C "
                   "(conf B={:.3f} vs C={:.3f}) o B es miscalibrado (P(correct|confiado)={:.2f}, "
                   "confidently_wrong={:.2f}).").format(B["conf_mean"], C["conf_mean"], calib_B, cw_B)
    elif endo_ranks and well_calibrated:
        status = "apoyada"
        verdict = ("H-V4-1c APOYADA: la confianza ENDÓGENA (max posterior, SIN oráculo) es una señal de VALOR "
                   "usable: (a) RANKEA info-gain > azar (conf B={:.3f} > C={:.3f}, igual que el oráculo de "
                   "exp042) Y (b) está CALIBRADA (P(correct|confiado)_B={:.2f}, confidently_wrong_B={:.2f} < "
                   "C={:.2f}). El agente puede SELECCIONAR la mejor política por su propia confianza, sin "
                   "conocer la causa -> base de R-VALOR endógeno.").format(
                       B["conf_mean"], C["conf_mean"], calib_B, cw_B, cw_C)
    else:
        status = "mixta"
        verdict = ("H-V4-1c MIXTA: la confianza endógena rankea B>C (conf {:.3f} vs {:.3f}) pero la calibración "
                   "es imperfecta (P(correct|confiado)_B={:.2f}, confidently_wrong_B={:.2f}).").format(
                       B["conf_mean"], C["conf_mean"], calib_B, cw_B)

    return {"budgets": budgets, "n_seeds": n_seeds, "tau": tau, "easy_regime": EASY, "hard_regime": HARD,
            "easy_by_K": e, "hard_by_K": h, "endo_ranks_BgtC": bool(endo_ranks),
            "calibration_B": round(calib_B, 4) if not np.isnan(calib_B) else None,
            "confidently_wrong_B": round(cw_B, 4), "confidently_wrong_C": round(cw_C, 4),
            "well_calibrated": bool(well_calibrated), "Kmax": Kmax, "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--budgets", type=str, default="8,12,16,20,24")
    ap.add_argument("--candidates", type=int, default=128)
    ap.add_argument("--tau", type=float, default=0.5)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.budgets = 8, "8,16,24"

    budgets = [int(x) for x in args.budgets.split(",")]
    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp043] CYCLE 57 / H-V4-1c — señal de valor ENDÓGENA (confianza del agente) + calibración")
    log(f"[exp043] DURO={HARD} budgets={budgets} seeds={args.seeds} tau={args.tau}")

    easy_rows = run_regime(EASY, budgets, args.seeds, args.candidates)
    hard_rows = run_regime(HARD, budgets, args.seeds, args.candidates)
    sm = build_summary(easy_rows, hard_rows, budgets, args.seeds, args.tau)

    Kmax = sm["Kmax"]
    log(f"[exp043] DURO @Kmax={Kmax}: " + " | ".join(
        "{}: conf={:.3f} correct={:.3f} calib={:.2f} conf_wrong={:.2f}".format(
            n, sm["hard_by_K"][str(Kmax)][n]["conf_mean"], sm["hard_by_K"][str(Kmax)][n]["correct_mean"],
            sm["hard_by_K"][str(Kmax)][n]["calibration_P_correct_given_confident"],
            sm["hard_by_K"][str(Kmax)][n]["confidently_wrong"]) for n, _ in MODES))
    log(f"[exp043] conf endógena por K (DURO B vs C): " + " ".join(
        "K{}:{:.3f}/{:.3f}".format(K, sm["hard_by_K"][str(K)]["B_infogain"]["conf_mean"],
                                   sm["hard_by_K"][str(K)]["C_aleatorio"]["conf_mean"]) for K in budgets))
    log(f"[exp043] VEREDICTO H-V4-1c: {sm['status'].upper()}")
    log(f"[exp043] {sm['verdict']}")

    out = {"exp": "exp043_endogenous_signal", "cycle": 57, "hypothesis": "H-V4-1c",
           "claim": "la confianza endógena del agente (max posterior, sin oráculo) rankea info-gain>azar y está "
                    "calibrada -> señal de valor endógena usable para elegir política",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp043] escrito {path}")


if __name__ == "__main__":
    main()

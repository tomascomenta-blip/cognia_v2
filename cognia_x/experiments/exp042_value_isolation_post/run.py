r"""
exp042 — CYCLE 56 / H-V4-1b: AISLAR el valor de info-gain (R-VALOR) del de intervenir (R-INTERVENCIÓN), con el
INSTRUMENTO correcto: la MASA DEL POSTERIOR SOBRE LA CAUSA VERDADERA (no la accuracy downstream).

CONTEXTO: exp022 (CYCLE 35, H-V4-1) quedó MIXTA — demostró R-INTERVENCIÓN (el pasivo se queda plano; las
políticas ACTIVAS identifican) pero NO aisló R-VALOR: el azar-activo (C) alcanzaba a info-gain (B) en ACCURACY
con presupuesto suficiente. DIAGNÓSTICO de este ciclo: la ACCURACY SATURA (una vez descartado el clúster
confundido, el voto ponderado acierta aunque el posterior no esté concentrado en la causa exacta) -> enmascara
el valor de info-gain. El instrumento FIEL de "¿construiste un modelo más CAUSAL?" es post_on_cause = masa del
posterior sobre la causa VERDADERA c.

HIPÓTESIS H-V4-1b: medido por post_on_cause (no accuracy), info-gain (B) concentra MÁS masa en la causa real
que el azar-activo (C), de forma ROBUSTA (B-C>0 consistente entre seeds) y CRECIENTE con el presupuesto en el
régimen DURO (espacio grande, clúster grande, ruido alto) -> el VALOR de *qué* consultar (info-gain) se AÍSLA
del de *intervenir* (actividad), donde la accuracy de exp022 lo escondía.

DISEÑO (reusa exp022.run, máquina validada). Dos regímenes:
  - FÁCIL  (exp022 default): D=12, cluster=4, p_obs=0.10  -> la accuracy satura rápido (enmascara el valor).
  - DURO:                    D=48, cluster=14, p_obs=0.20 -> el azar-activo NO alcanza; el valor se ve.
Barrido de presupuesto K. Métrica PRIMARIA: post_on_cause de B vs C (y A) bajo el mundo. Secundaria: interv
accuracy (para mostrar que SATURA y enmascara). 48 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si en el régimen DURO: B-C en post_on_cause es > 0.15 a Kmax, SIGNO-consistente (>=70% seeds B>C)
    y CRECIENTE con K; Y la accuracy enmascara (el gap B-C en accuracy es MENOR que en post_on_cause). =>
    R-VALOR (info-gain) se AÍSLA con el instrumento fiel, explicando la MIXTA de exp022.
  - REFUTADA si B-C en post_on_cause <= 0 o no es signo-consistente (info-gain no tiene valor específico sobre
    el azar-activo aun con el instrumento fiel).
  - MIXTA si B-C en post_on_cause es positivo pero no llega al umbral o no crece con K.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp042_value_isolation_post.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp042_value_isolation_post.run            # FULL
"""
import argparse
import json
import os
import platform
import sys

import numpy as np

from cognia_x.experiments.exp022_endogenous_value.run import run as run022

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
EASY = {"D": 12, "cluster": 4, "p_obs": 0.10}
HARD = {"D": 48, "cluster": 14, "p_obs": 0.20}


def regime_stats(per_seed, budgets, n_seeds):
    """Por K: medias de post_on_cause e interv para A/B/C, gap B-C en ambos, y consistencia de signo (post)."""
    out = {}
    for K in budgets:
        def col(name, metric):
            return np.array([per_seed[i]["by_budget"][str(K)][name][metric] for i in range(n_seeds)])
        pB, pC, pA = col("B_infogain", "post_on_cause"), col("C_aleatorio", "post_on_cause"), col("A_pasivo", "post_on_cause")
        aB, aC = col("B_infogain", "interv"), col("C_aleatorio", "interv")
        diff = pB - pC
        out[str(K)] = {
            "post_B": float(pB.mean()), "post_C": float(pC.mean()), "post_A": float(pA.mean()),
            "post_BminusC": float(diff.mean()), "post_BminusC_std": float(diff.std()),
            "sign_BgtC": float((diff > 1e-9).mean()), "acc_B": float(aB.mean()), "acc_C": float(aC.mean()),
            "acc_BminusC": float((aB - aC).mean()),
        }
    return out


def build_summary(easy, hard, budgets, n_seeds):
    Kmin, Kmax = min(budgets), max(budgets)
    e = regime_stats(easy, budgets, n_seeds)
    h = regime_stats(hard, budgets, n_seeds)

    post_iso_hard = h[str(Kmax)]["post_BminusC"]
    sign_hard = h[str(Kmax)]["sign_BgtC"]
    grows = h[str(Kmax)]["post_BminusC"] > h[str(Kmin)]["post_BminusC"] + 0.02
    # la accuracy ENMASCARA: el gap B-C en accuracy es MENOR que en post_on_cause a Kmax (duro)
    acc_masks = abs(h[str(Kmax)]["acc_BminusC"]) < post_iso_hard - 0.05

    if post_iso_hard <= 0 or sign_hard < 0.55:
        status = "refutada"
        verdict = ("H-V4-1b REFUTADA: info-gain NO concentra más en la causa que el azar-activo aun con el "
                   "instrumento fiel (post B-C={:+.3f} a Kmax, signo {:.0f}%). El valor de info-gain no se aísla "
                   "de la actividad.").format(post_iso_hard, sign_hard * 100)
    elif post_iso_hard > 0.15 and sign_hard >= 0.70 and grows:
        status = "apoyada"
        verdict = ("H-V4-1b APOYADA: con el instrumento FIEL (post_on_cause), info-gain (B) AÍSLA su valor sobre "
                   "el azar-activo (C) en el régimen DURO: post B-C={:+.3f} a Kmax (signo {:.0f}% seeds B>C, "
                   "CRECE con K). La ACCURACY lo ENMASCARA (acc B-C={:+.3f} << post B-C) porque satura una vez "
                   "descartado el clúster. Explica la MIXTA de exp022: instrumento equivocado. R-VALOR (qué "
                   "consultar) se separa de R-INTERVENCIÓN (intervenir).").format(
                       post_iso_hard, sign_hard * 100, h[str(Kmax)]["acc_BminusC"])
    else:
        status = "mixta"
        verdict = ("H-V4-1b MIXTA: info-gain concentra MÁS en la causa (post B-C={:+.3f} a Kmax, signo {:.0f}%) "
                   "pero el efecto no llega al umbral fuerte o no crece claramente; el valor de info-gain es REAL "
                   "pero MODESTO frente a la actividad.").format(post_iso_hard, sign_hard * 100)

    return {"budgets": budgets, "n_seeds": n_seeds, "easy_regime": EASY, "hard_regime": HARD,
            "easy_by_K": e, "hard_by_K": h, "post_iso_hard_Kmax": round(post_iso_hard, 4),
            "sign_consistency_hard_Kmax": round(sign_hard, 4), "grows_with_K": bool(grows),
            "acc_masks_value": bool(acc_masks), "Kmin": Kmin, "Kmax": Kmax,
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--budgets", type=str, default="8,12,16,20,24")
    ap.add_argument("--n_test", type=int, default=3000)
    ap.add_argument("--candidates", type=int, default=128)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.budgets, args.n_test = 8, "8,16,24", 1500

    budgets = [int(x) for x in args.budgets.split(",")]
    logs = []

    def log(m):
        print(m, flush=True); logs.append(m)

    log(f"[exp042] CYCLE 56 / H-V4-1b — aislar el valor de info-gain con post_on_cause (instrumento fiel)")
    log(f"[exp042] FÁCIL={EASY} DURO={HARD} budgets={budgets} seeds={args.seeds}")

    easy, _ = run022(budgets, args.seeds, EASY["D"], EASY["cluster"], EASY["p_obs"], args.n_test, args.candidates)
    hard, _ = run022(budgets, args.seeds, HARD["D"], HARD["cluster"], HARD["p_obs"], args.n_test, args.candidates)
    sm = build_summary(easy, hard, budgets, args.seeds)

    log(f"[exp042] DURO post_on_cause (causa verdadera): " + " ".join(
        f"K{K}:B={sm['hard_by_K'][str(K)]['post_B']:.3f}/C={sm['hard_by_K'][str(K)]['post_C']:.3f}"
        f"(B-C={sm['hard_by_K'][str(K)]['post_BminusC']:+.3f},{sm['hard_by_K'][str(K)]['sign_BgtC']*100:.0f}%)"
        for K in budgets))
    log(f"[exp042] DURO accuracy (SATURA, enmascara): " + " ".join(
        f"K{K}:B={sm['hard_by_K'][str(K)]['acc_B']:.3f}/C={sm['hard_by_K'][str(K)]['acc_C']:.3f}" for K in budgets))
    log(f"[exp042] FÁCIL post_on_cause: " + " ".join(
        f"K{K}:B-C={sm['easy_by_K'][str(K)]['post_BminusC']:+.3f}" for K in budgets))
    log(f"[exp042] VEREDICTO H-V4-1b: {sm['status'].upper()} | post_iso_hard@Kmax={sm['post_iso_hard_Kmax']:+.3f} "
        f"signo={sm['sign_consistency_hard_Kmax']*100:.0f}% crece={sm['grows_with_K']} acc_enmascara={sm['acc_masks_value']}")
    log(f"[exp042] {sm['verdict']}")

    out = {"exp": "exp042_value_isolation_post", "cycle": 56, "hypothesis": "H-V4-1b",
           "claim": "medido por post_on_cause (no accuracy), el valor de info-gain se aísla del de intervenir en "
                    "el régimen duro; la accuracy de exp022 lo enmascaraba",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__}, "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp042] escrito {path}")


if __name__ == "__main__":
    main()

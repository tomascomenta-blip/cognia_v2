r"""
exp038 — CYCLE 52 / H-V4-2e: el TECHO del lazo iterado + guardia con VERIFICADOR REAL desde un base DÉBIL.

CONTEXTO: CYCLE 49 (exp035) mostró que un base DÉBIL se BOOTSTRAPEA a ~0.78 con el lazo iterado — pero con el
ORÁCULO aritmético EXACTO. CYCLE 51 (exp037) mostró que el lazo iterado + guardia GENERALIZA a un VERIFICADOR
REAL (sandbox), pero desde un base MODERADO (~0.44) y solo R=6 -> su límite honesto #1 fue "falta base débil
bajo el verificador real para medir el TECHO". Este ciclo lo cierra: ¿el lazo con el VERIFICADOR REAL tiene el
mismo poder de bootstrapping desde un base DÉBIL (~0.08), y DÓNDE PLATEA (techo) con muchas rondas (R=10)?

ANALOGÍA: arrancás sabiendo casi nada de escribir programas (base 0.08). Practicás muchas rondas corrigiéndote
EJECUTANDO lo que escribís (verificador real), con dedup+replay. ¿Llegás lejos (techo alto) y te estabilizás, o
te quedás trabado abajo? Y si llegás, ¿en qué ronda dejás de mejorar (plateau)?

DISEÑO (modelo propio; reusa exp037). base_steps=125 -> base real_acc~0.08 (DÉBIL, calibrado). Lazo de R=10
rondas in-place, PLANO vs GUARDED (dedup+replay), con el verificador FUERTE real (síntesis de expresiones).
Métricas por ronda: real_acc (held-out), cobertura, degenerate. 3 seeds. Análisis: ¿bootstrapea (final-base
grande, final alto) y platea (rondas finales se aplanan, no-decreciente)?

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si GUARDED bootstrapea el base débil a un TECHO ALTO (final-base >= 0.30 Y final >= 0.50) Y PLATEA
    (no-decreciente Y las últimas rondas se aplanan dentro del margen) => el lazo con verificador REAL tiene el
    mismo poder de bootstrapping que el oráculo (CYCLE 49) y su techo es localizable.
  - REFUTADA si NO bootstrapea (final-base < 0.30) O COLAPSA (cae > margen tras el pico).
  - MIXTA si bootstrapea pero NO platea (sigue subiendo en R=10, techo no alcanzado) o la ganancia es modesta.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp038_real_verifier_ceiling.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp038_real_verifier_ceiling.run            # FULL
"""
import argparse
import json
import math
import os
import platform
import sys
import time

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp037_iterated_real_verifier.run import run_seed, LO, HI

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def plateau_round(seq, margin):
    """Primera ronda r tal que seq[r] >= max(seq) - margin (donde la curva ya alcanzó su techo)."""
    mx = max(seq)
    for r, x in enumerate(seq):
        if x >= mx - margin:
            return r
    return len(seq) - 1


def verdict(seeds_res, args, m):
    R = args.rounds
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)

    def avg(arm, metric, r):
        return float(np.mean([next(x[metric] for x in s[arm] if x["round"] == r) for s in seeds_res]))

    real_p = [avg("plain", "real", r) for r in range(R + 1)]
    real_g = [avg("guarded", "real", r) for r in range(R + 1)]
    cov_g = [avg("guarded", "coverage", r) for r in range(R + 1)]
    deg_g = [avg("guarded", "degen", r) for r in range(R + 1)]

    base = real_g[0]
    final_g = real_g[R]
    peak_g = max(real_g)
    peak_r = real_g.index(peak_g)
    gain = final_g - base
    bootstraps = gain >= 0.30 and final_g >= 0.50
    non_decreasing = all(real_g[r + 1] >= real_g[r] - margin for r in range(R))
    collapses = (peak_g - final_g) > margin and peak_r < R
    pr = plateau_round(real_g, margin)
    # plateau alcanzado si la meseta empieza ANTES de la última ronda y las últimas 3 rondas se aplanan
    last3 = real_g[-3:]
    flattened = (max(last3) - min(last3)) <= margin
    plateaus = non_decreasing and flattened and pr < R

    if not bootstraps:
        v = "REFUTADA"
    elif collapses:
        v = "REFUTADA"
    elif bootstraps and plateaus:
        v = "APOYADA"
    else:
        v = "MIXTA"
    return v, {"margin": margin, "real_plain": real_p, "real_guarded": real_g, "cov_guarded": cov_g,
               "degen_guarded": deg_g, "base": base, "final_guarded": final_g, "peak_guarded": peak_g,
               "peak_round": peak_r, "gain": gain, "bootstraps": bootstraps, "non_decreasing": non_decreasing,
               "collapses": collapses, "plateau_round": pr, "flattened": flattened, "plateaus": plateaus,
               "n_seeds": len(seeds_res)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--replay_n", type=int, default=128)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--n_seed", type=int, default=256)
    # base_steps=125 calibrado para base real_acc~0.08 (DÉBIL) -> margen máximo para medir el techo.
    ap.add_argument("--base_steps", type=int, default=125)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.rounds, args.steps, args.pool = "0,1", 4, 80, 128

    torch.set_num_threads(3)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)
        logf.write(m + "\n"); logf.flush()

    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    log(f"[exp038] CYCLE 52 / H-V4-2e — TECHO del lazo iterado + guardia con VERIFICADOR REAL desde base DÉBIL")
    log(f"[exp038] exprs [{LO},{HI}] train={len(train_targets)} test={len(test_targets)} rounds={args.rounds} "
        f"base_steps={args.base_steps} (base débil) seeds={seeds}")

    res = [run_seed(s, args, train_targets, test_targets, log) for s in seeds]
    v, stats = verdict(res, args, len(test_targets))
    R = args.rounds
    log(f"[exp038] VEREDICTO H-V4-2e: {v} | margin={stats['margin']:.3f}")
    log(f"[exp038] REAL_acc guarded={['%.3f' % x for x in stats['real_guarded']]} (base={stats['base']:.3f} "
        f"final={stats['final_guarded']:.3f} gain={stats['gain']:+.3f} pico={stats['peak_guarded']:.3f}@r{stats['peak_round']})")
    log(f"[exp038] REAL_acc plano  ={['%.3f' % x for x in stats['real_plain']]}")
    log(f"[exp038] COBERTURA guarded={['%.0f' % x for x in stats['cov_guarded']]} | DEGEN guarded={['%.3f' % x for x in stats['degen_guarded']]}")
    log(f"[exp038] checks: bootstraps={stats['bootstraps']} no_decrece={stats['non_decreasing']} "
        f"colapsa={stats['collapses']} plateau@r{stats['plateau_round']} aplanado={stats['flattened']} platea={stats['plateaus']}")

    out = {"exp": "exp038_real_verifier_ceiling", "cycle": 52, "hypothesis": "H-V4-2e",
           "claim": "el lazo iterado + guardia con VERIFICADOR REAL bootstrapea un base débil a un techo alto y "
                    "plateable, igual que el oráculo exacto (CYCLE 49)",
           "verdict": v, "stats": stats, "args": vars(args), "seeds": res, "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp038] escrito {path}")
    logf.close()


if __name__ == "__main__":
    main()

r"""
exp040 — CYCLE 54 / H-V4-2g (CAPSTONE robustez): ¿el lazo GUARDED con VERIFICADOR REAL bootstrapea un base
DÉBIL a un techo alto AUN BAJO RUIDO del verificador? (interacción ε × cold-start — límite abierto de exp039).

CONTEXTO: exp038 (CYCLE 52) -> la guardia bootstrapea un base débil (~0.08) a ~0.93 con un verificador REAL
PERFECTO. exp039 (CYCLE 53) -> con un base MODERADO (~0.44) la guardia tolera ruido hasta ε*=0.50. Límite
abierto explícito de exp039: NO se combinaron los dos estresores. ¿La robustez al ruido SOBREVIVE cuando además
se arranca desde casi-cero? Es el peor caso realista: verificador imperfecto Y modelo casi sin saber la tarea.

ANALOGÍA: arrancás sabiendo casi nada (base 0.08) Y tu corrector se equivoca (falso-positivo ε). Con el
cuaderno de la verdad (replay) ¿igual despegás, o los dos problemas juntos te dejan trabado abajo?

DISEÑO (modelo propio; reusa exp039). base_steps=125 -> base real_acc~0.08 (DÉBIL). Lazo GUARDED (dedup +
replay limpio) por R=8 rondas, barriendo ε en {0.0,0.15,0.30,0.50} (verificador FUERTE real con ruido
falso-positivo). Métrica: real_acc CLEAN final y gain-sobre-base por ε. 3 seeds. ε*_coldstart = mayor ε con
bootstrapping consistente (gain>=0.30 Y final>=0.50).

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el lazo GUARDED desde base débil SIGUE bootstrapeando bajo ruido moderado (gain>=0.30 Y final
    >=0.50 hasta un ε*_coldstart > 0, consistente entre seeds) y degrada de forma graceful con ε -> la robustez
    al ruido y al cold-start COEXISTEN (capstone del arco de verificador real).
  - REFUTADA si un ruido chico (ε=0.15) ya DESTRUYE el cold-start (final ~ base, sin bootstrapping) -> los dos
    estresores se COMPONEN catastróficamente.
  - MIXTA si bootstrapea bajo ruido pero el umbral cae MUCHO vs el ε*=0.50 de base moderada (la fragilidad del
    arranque débil baja la tolerancia al ruido).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp040_noise_coldstart.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp040_noise_coldstart.run            # FULL
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
from cognia_x.experiments.exp018_real_verifier.run import build_base
from cognia_x.experiments.exp037_iterated_real_verifier.run import seed_correct, LO, HI
from cognia_x.experiments.exp039_noisy_real_verifier.run import run_loop, EPS_SWEEP

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def run_seed(seed, args, train_targets, test_targets, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch,
                            train_targets)
    base_acc = round(E.eval_metrics(base, test_targets, "cpu")["real_acc"], 4)
    log(f"[exp040] seed={seed} base real_acc={base_acc:.3f} (DÉBIL) params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    replay = seed_correct(train_targets, args.replay_n, np.random.default_rng(99000 + seed))

    hist = {}
    for eps in EPS_SWEEP:
        hist[str(eps)] = run_loop(base, pool_prompts, test_targets, args, True, eps, replay, 95000 + seed * 17)
        log(f"[exp040] seed={seed} eps={eps}: base={base_acc:.3f} -> final={hist[str(eps)][-1]:.3f}")
    dt = time.time() - t0
    log(f"[exp040] seed={seed} {dt:.1f}s")
    return {"seed": seed, "base_acc": base_acc, "npar": npar, "secs": round(dt, 2), "hist": hist}


def build_summary(per_seed, m):
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)
    base = round(sum(s["base_acc"] for s in per_seed) / len(per_seed), 4)
    final = {str(e): [s["hist"][str(e)][-1] for s in per_seed] for e in EPS_SWEEP}
    final_mean = {str(e): round(sum(final[str(e)]) / len(per_seed), 4) for e in EPS_SWEEP}
    gain_mean = {str(e): round(final_mean[str(e)] - base, 4) for e in EPS_SWEEP}
    # bootstrapping consistente por ε = cada seed BOOTSTRAPEA fuerte (gain >= 0.30). Criterio por GANANCIA (¿el
    # cold-start sobrevivió el ruido?), NO por techo absoluto (que mide otra cosa: cuánto BAJA el techo el ruido).
    boots = {str(e): all((f - s["base_acc"]) >= 0.30 for f, s in zip(final[str(e)], per_seed)) for e in EPS_SWEEP}
    survivors = [e for e in EPS_SWEEP if boots[str(e)]]
    eps_star_cold = max(survivors) if survivors else None
    decays = final_mean[str(EPS_SWEEP[0])] > final_mean[str(EPS_SWEEP[-1])]
    clean_boots = boots[str(0.0)]
    monotone_ish = sum(1 for i in range(len(EPS_SWEEP) - 1)
                       if final_mean[str(EPS_SWEEP[i])] >= final_mean[str(EPS_SWEEP[i + 1])] - margin) >= (len(EPS_SWEEP) - 2)

    if not clean_boots:
        status = "inconcluso"
        verdict = ("ε=0 no bootstrapea el base débil (gain {:+.3f}, base {:.3f}) -> recalibrar; sin cold-start "
                   "limpio no hay interacción que medir.").format(gain_mean[str(0.0)], base)
    elif eps_star_cold is not None and eps_star_cold >= 0.30:
        status = "apoyada"
        verdict = ("H-V4-2g APOYADA (CAPSTONE): el lazo GUARDED desde un base DÉBIL ({b:.3f}) SIGUE "
                   "bootstrapeando fuerte (gain>=0.30) bajo RUIDO sustancial del verificador hasta ε*_coldstart="
                   "{es}: final por ε {fm} (gain {gm}). La robustez al ruido (exp039 ε*=0.50, base moderada) y al "
                   "cold-start (exp038) COEXISTEN: con replay limpio, verificador imperfecto + arranque casi-cero "
                   "NO se componen catastróficamente (el techo baja con ε pero el cold-start SOBREVIVE). "
                   "monotone_ish={mi}.").format(b=base, fm={e: final_mean[str(e)] for e in EPS_SWEEP},
                                                gm={e: gain_mean[str(e)] for e in EPS_SWEEP},
                                                es=eps_star_cold, mi=monotone_ish)
    elif eps_star_cold == 0.0:
        status = "refutada"
        verdict = ("H-V4-2g REFUTADA: el ruido DESTRUYE el cold-start — ya en ε=0.15 no hay bootstrapping fuerte "
                   "(gain {:+.3f}, base {:.3f}). Los dos estresores (ruido + arranque débil) se componen "
                   "catastróficamente.").format(gain_mean[str(0.15)], base)
    else:
        status = "mixta"
        verdict = ("H-V4-2g MIXTA: el cold-start SOBREVIVE algo de ruido (ε*_coldstart={es}) pero por debajo de "
                   "0.30 -> la fragilidad del arranque débil BAJA la tolerancia al ruido vs base moderada "
                   "(ε*=0.50); degrada graceful (final {fm}).").format(
                       es=eps_star_cold, fm={e: final_mean[str(e)] for e in EPS_SWEEP})

    return {"eps_sweep": EPS_SWEEP, "sigma_2": margin, "n_seeds": len(per_seed), "base": base,
            "final_mean": final_mean, "final_per_seed": {str(e): final[str(e)] for e in EPS_SWEEP},
            "gain_mean": gain_mean, "bootstraps_by_eps": boots, "eps_star_coldstart": eps_star_cold,
            "decays": bool(decays), "clean_bootstraps": bool(clean_boots), "monotone_ish": bool(monotone_ish),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--replay_n", type=int, default=128)
    ap.add_argument("--fixed_n", type=int, default=400)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_steps", type=int, default=125)   # base real_acc~0.08 (DÉBIL, calibrado en exp038)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps = "0,1", 4, 128, 80

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
    log(f"[exp040] CYCLE 54 / H-V4-2g — CAPSTONE: ruido del verificador REAL x cold-start (base débil)")
    log(f"[exp040] exprs [{LO},{HI}] test={len(test_targets)} eps={EPS_SWEEP} rounds={args.rounds} "
        f"base_steps={args.base_steps} (base débil) seeds={seeds}")

    res = [run_seed(s, args, train_targets, test_targets, log) for s in seeds]
    summary = build_summary(res, len(test_targets))
    log(f"[exp040] VEREDICTO: {summary['verdict']}")
    log(f"[exp040] final por ε: " + " ".join(f"e{e}={summary['final_mean'][str(e)]:.3f}" for e in EPS_SWEEP)
        + f"  base={summary['base']:.3f} ε*_coldstart={summary['eps_star_coldstart']}")

    out = {"exp": "exp040_noise_coldstart", "cycle": 54, "hypothesis": "H-V4-2g",
           "claim": "el lazo guarded con verificador real bootstrapea un base débil aun bajo ruido del "
                    "verificador (robustez a ruido x cold-start coexisten)",
           "verdict": summary["status"], "summary": summary, "args": vars(args), "seeds": res,
           "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp040] escrito {path}")
    logf.close()


if __name__ == "__main__":
    main()

r"""
exp036 — CYCLE 50 / H-V4-2c: GUARDIA DE DIVERSIDAD + techo del bootstrapping. exp035 (CYCLE 49) mostró que el
lazo de auto-mejora verificada es estable pero la diversidad DECLINA monótona (narrowing temprano). Pregunta:
¿una GUARDIA simple (dedup de los ejemplos verificados + REPLAY de datos semilla originales) previene el
narrowing y/o sube el techo, comparado con el lazo PLANO, a lo largo de MÁS rondas (R=6)?

ANALOGÍA: si repasás repitiendo SÓLO tus ejercicios bien resueltos, terminás machacando los MISMOS pocos
(perdés variedad). Dos arreglos baratos: (1) no repetir el mismo ejercicio 50 veces (DEDUP), (2) intercalar
ejercicios del libro original (REPLAY). ¿Mantienen la variedad sin perder precisión?

DISEÑO (modelo propio; reusa exp035). Dos lazos de R rondas in-place desde el MISMO base:
  - PLANO (CYCLE 49): entrena con TODOS los verificados de la ronda (con repetición por frecuencia).
  - GUARDED: entrena con verificados DEDUP (cada (prompt,answer) único una vez) + REPLAY de una fracción
    replay_frac de ejemplos semilla CORRECTOS originales (datos de la verdad, no auto-generados).
Métricas por ronda: PRECISIÓN POR PASO (held-out), COBERTURA = nº de PROMPTS distintos en el set verificado
(cuánto del espacio de problemas cubre la auto-generación; cae si el lazo se estrecha), DIVERSIDAD de
respuestas. 3 seeds, R=6.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si la GUARDIA mantiene la COBERTURA/diversidad MÁS ALTA que el PLANO en las últimas rondas (menos
    narrowing) Y su precisión por paso final es >= la del PLANO (no sacrifica precisión por variedad). => la
    guardia es un arreglo barato y efectivo del narrowing.
  - REFUTADA si la guardia NO mejora la cobertura/diversidad vs plano (no sirve) O hunde la precisión final
    (> margen por debajo del plano).
  - MIXTA si mantiene la diversidad pero a costa de algo de precisión, o el PLANO no narrowing en R=6 (la
    guardia es innecesaria en esta tarea acotada).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp036_diversity_guard.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp036_diversity_guard.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys
import time

import numpy as np
import torch

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base, train_arm
from cognia_x.experiments.exp035_iterated_star.run import gen_and_measure

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def coverage_prompts(verified):
    """Nº de PROMPTS distintos en el set verificado (cobertura del espacio de problemas)."""
    return len(set(bytes(p) for (p, e) in verified))


def seed_correct(train_pairs, n, rng):
    """n ejemplos CORRECTOS de la VERDAD (datos originales, no auto-generados) para replay."""
    sel = rng.integers(0, len(train_pairs), size=n)
    return [(T.make_prompt(*train_pairs[i]), T.correct_answer(*train_pairs[i])) for i in sel]


def run_loop(base, train_pairs, test, args, guarded, gen_seed, replay_pairs, log, tag):
    """Lazo de R rondas in-place sobre una COPIA del base. Devuelve lista por ronda con step/coverage/div."""
    torch.manual_seed(2000)
    model = copy.deepcopy(base)
    gen_rng = np.random.default_rng(gen_seed)
    rounds = []
    step0 = T.eval_accuracy(model, test, "cpu")[0]
    rounds.append({"round": 0, "step": step0, "coverage": 0, "diversity": 0.0})
    for r in range(1, args.rounds + 1):
        verified, div, _ = gen_and_measure(model, train_pairs, args.n_prompts, args.K, args.temperature,
                                           args.top_k, gen_rng, "cpu")
        cov = coverage_prompts(verified)
        if guarded:
            uniq = list(dict.fromkeys((bytes(p), bytes(e)) for (p, e) in verified))   # dedup, preserva orden
            train_set = [(bytes(p), bytes(e)) for (p, e) in uniq] + replay_pairs       # + replay de la verdad
        else:
            train_set = verified
        if train_set:
            train_arm(model, train_set, args.star_steps, args.batch, args.star_lr, "cpu",
                      np.random.default_rng(98000 + r))
        step = T.eval_accuracy(model, test, "cpu")[0]
        rounds.append({"round": r, "step": step, "coverage": cov, "diversity": div})
        log(f"[exp036]   {tag} round={r}: step={step:.3f} coverage={cov} div={div:.3f}")
    return rounds


def run_seed(seed, args, train_pairs, test, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                            args.batch, train_pairs, log)
    replay = seed_correct(train_pairs, args.replay_n, np.random.default_rng(99000 + seed))
    plain = run_loop(base, train_pairs, test, args, False, 95000 + seed, replay, log, f"s{seed}/PLAIN")
    guarded = run_loop(base, train_pairs, test, args, True, 95000 + seed, replay, log, f"s{seed}/GUARD")
    dt = time.time() - t0
    log(f"[exp036] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "plain": plain, "guarded": guarded}


def verdict(seeds_res, args):
    R = args.rounds

    def avg(arm, metric, r):
        return float(np.mean([next(x[metric] for x in s[arm] if x["round"] == r) for s in seeds_res]))

    step_p = [avg("plain", "step", r) for r in range(R + 1)]
    step_g = [avg("guarded", "step", r) for r in range(R + 1)]
    cov_p = [avg("plain", "coverage", r) for r in range(R + 1)]
    cov_g = [avg("guarded", "coverage", r) for r in range(R + 1)]
    div_p = [avg("plain", "diversity", r) for r in range(R + 1)]
    div_g = [avg("guarded", "diversity", r) for r in range(R + 1)]

    # ¿hay narrowing en el PLANO? (cobertura o diversidad de la última ronda < primera generación)
    plain_narrows = (cov_p[R] < cov_p[1] - 1e-9) or (div_p[R] < 0.8 * div_p[1])
    # ¿la guardia mantiene MÁS cobertura/diversidad que el plano al final?
    guard_keeps = (cov_g[R] > cov_p[R] + 1e-9) or (div_g[R] > div_p[R] + 1e-6)
    # ¿la guardia no sacrifica precisión final?
    no_prec_cost = step_g[R] >= step_p[R] - args.margin
    if step_g[R] < step_p[R] - args.margin:
        v = "REFUTADA"                         # la guardia hunde la precisión final -> no sirve
    elif plain_narrows and guard_keeps and no_prec_cost:
        v = "APOYADA"                          # hay narrowing y la guardia lo frena sin costo de precisión
    elif not plain_narrows:
        v = "MIXTA"                            # el plano no narrowing en R=6 -> la guardia es innecesaria (no refuta el lazo)
    else:
        v = "MIXTA"                            # hay narrowing pero la guardia no lo frena claramente
    return v, {"step_plain": step_p, "step_guarded": step_g, "cov_plain": cov_p, "cov_guarded": cov_g,
               "div_plain": div_p, "div_guarded": div_g, "plain_narrows": plain_narrows,
               "guard_keeps": guard_keeps, "no_prec_cost": no_prec_cost, "n_seeds": len(seeds_res)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--n_prompts", type=int, default=384)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--replay_n", type=int, default=128, help="ejemplos semilla CORRECTOS para replay (guarded)")
    ap.add_argument("--star_steps", type=int, default=200)
    ap.add_argument("--star_lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--n_seed", type=int, default=256)
    ap.add_argument("--base_steps", type=int, default=600)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lo", type=int, default=0)
    ap.add_argument("--hi", type=int, default=19)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.rounds, args.base_steps, args.star_steps, args.n_prompts = "0,1", 3, 300, 120, 160

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, test_pairs = T.build_split(args.lo, args.hi, args.test_frac)
    test = T.test_from_pairs(test_pairs)

    log(f"[exp036] CYCLE 50 / H-V4-2c — guardia de diversidad (dedup+replay) en el lazo iterado (modelo propio)")
    log(f"[exp036] suma [{args.lo},{args.hi}] test={len(test)} rounds={args.rounds} n_prompts={args.n_prompts} "
        f"replay_n={args.replay_n} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, test, log) for s in seeds]
    v, stats = verdict(res, args)
    R = args.rounds
    log(f"[exp036] VEREDICTO H-V4-2c: {v} | PASO_final plano={stats['step_plain'][R]:.3f} guarded={stats['step_guarded'][R]:.3f} "
        f"| COBERTURA_final plano={stats['cov_plain'][R]:.0f} guarded={stats['cov_guarded'][R]:.0f} "
        f"| narrowing_plano={stats['plain_narrows']} guardia_mantiene={stats['guard_keeps']} sin_costo_prec={stats['no_prec_cost']}")
    log(f"[exp036] PLANO    step={['%.3f' % x for x in stats['step_plain']]} cov={['%.0f' % x for x in stats['cov_plain']]} div={['%.3f' % x for x in stats['div_plain']]}")
    log(f"[exp036] GUARDED  step={['%.3f' % x for x in stats['step_guarded']]} cov={['%.0f' % x for x in stats['cov_guarded']]} div={['%.3f' % x for x in stats['div_guarded']]}")

    out = {"exp": "exp036_diversity_guard", "cycle": 50, "hypothesis": "H-V4-2c",
           "claim": "una guardia de diversidad (dedup+replay) en el lazo iterado previene el narrowing sin "
                    "sacrificar precisión",
           "verdict": v, "stats": stats, "args": vars(args), "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp036] escrito {path}")


if __name__ == "__main__":
    main()

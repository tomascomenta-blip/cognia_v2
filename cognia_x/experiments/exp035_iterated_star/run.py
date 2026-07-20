r"""
exp035 — CYCLE 49 / H-V4-2b: ITERAR el lazo de auto-mejora VERIFICADA varias rondas. ¿La precisión por paso
SIGUE subiendo y PLATEA (motor estable) o COLAPSA (narrowing tipo STaR: el modelo se entrena sobre su propia
distribución estrecha y pierde diversidad/precisión)?

CONTEXTO: exp034 (CYCLE 48) mostró que UNA ronda de STaR verificado mejora la precisión por paso y se amplifica
en multi-paso. Para que sea un MOTOR de auto-mejora autónomo (no un truco de una vez), el lazo debe ser ESTABLE
a través de rondas. Riesgo conocido (exp019/literatura): iterar puede colapsar la diversidad y degradar.

ANALOGÍA: practicar repitiendo SÓLO tus propios ejercicios que salieron bien. Si te mantiene afilado y variado,
mejorás ronda a ronda y plateás en tu techo. Si te encierra en un puñado de patrones (perdés variedad), al
final empeorás. La pregunta es cuál de las dos pasa con el filtro de CORRECCIÓN.

DISEÑO (modelo propio; reusa exp034/exp016). Lazo de R rondas IN-PLACE: ronda r -> genera K completaciones por
prompt de train con el modelo ACTUAL, filtra las VERIFICADO-correctas (oráculo), fine-tunea el modelo actual
con ellas. Tras cada ronda mide: (a) PRECISIÓN POR PASO (suma held-out), (b) ACCURACY DE CADENA greedy (K=2),
(c) DIVERSIDAD = fracción de respuestas DISTINTAS generadas (señal de colapso: si cae, el modelo se estrecha),
(d) n_verified (cuánta data usable produce). Comparado contra el round 0 (base). 3 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA (motor ESTABLE) si la precisión por paso SUBE sobre el base y es NO-DECRECIENTE a lo largo de las
    rondas (plateau, no colapso), Y la diversidad NO se desploma (no cae por debajo de ~0.5× la inicial). =>
    el lazo verificado es un motor de auto-mejora sostenible.
  - REFUTADA (COLAPSA) si la precisión por paso CAE > margen tras su pico (degradación por iterar), O la
    diversidad se desploma (< 0.5× inicial) aunque la precisión aguante.
  - MIXTA si mejora pero satura inmediato (sólo la ronda 1 aporta; rondas 2+ planas) o la diversidad cae
    moderado sin desplomarse.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp035_iterated_star.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp035_iterated_star.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys
import time
from collections import Counter

import numpy as np
import torch

from cognia_x.experiments.exp016_verified_bootstrap import addition_task as T
from cognia_x.experiments.exp016_verified_bootstrap.run import build_base, generate_pool, train_arm
from cognia_x.experiments.exp030_multistep_reasoning.run import make_chain
from cognia_x.experiments.exp034_substrate_amplify.run import chain_acc_greedy

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def gen_and_measure(model, train_pairs, n_prompts, K, temperature, top_k, rng, device):
    """Genera K completaciones por prompt; devuelve (verified_examples, diversity, n_verified). diversity =
    fracción de respuestas DISTINTAS sobre el total generado (1.0 = todas distintas; ->0 = colapso)."""
    sel = rng.integers(0, len(train_pairs), size=n_prompts)
    prompts = [T.make_prompt(*train_pairs[i]) for i in sel]
    pool = generate_pool(model, prompts, K, temperature, top_k, device)  # [(prompt, emitted, is_correct)]
    verified = [(p, e) for (p, e, c) in pool if c]
    answers = [bytes(e) for (p, e, c) in pool]
    diversity = len(set(answers)) / max(1, len(answers))
    return verified, diversity, len(verified)


def run_seed(seed, args, train_pairs, test, log):
    t0 = time.time()
    model, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup,
                             args.batch, train_pairs, log)
    gen_rng = np.random.default_rng(95000 + seed)
    chain_rng = np.random.default_rng(60000 + seed * 31 + 2)         # MISMAS cadenas K=2 que el resto del arco
    chains = [make_chain(chain_rng, 2) for _ in range(args.M)]

    rounds = []
    # ronda 0 = base (medición inicial; diversidad medida con una generación de sondeo que NO se entrena)
    _, div0, _ = gen_and_measure(model, train_pairs, args.n_prompts, args.K, args.temperature,
                                 args.top_k, np.random.default_rng(96000 + seed), "cpu")
    step0 = T.eval_accuracy(model, test, "cpu")[0]
    chain0 = chain_acc_greedy(model, chains, "cpu")
    rounds.append({"round": 0, "step": step0, "chain": chain0, "diversity": div0, "n_verified": 0})
    log(f"[exp035]   seed={seed} round=0 (base): step={step0:.3f} chain={chain0:.3f} div={div0:.3f}")

    for r in range(1, args.rounds + 1):
        verified, div, nver = gen_and_measure(model, train_pairs, args.n_prompts, args.K, args.temperature,
                                              args.top_k, gen_rng, "cpu")
        if verified:
            train_arm(model, verified, args.star_steps, args.batch, args.star_lr, "cpu",
                      np.random.default_rng(97000 + seed * 11 + r))
        step = T.eval_accuracy(model, test, "cpu")[0]
        chain = chain_acc_greedy(model, chains, "cpu")
        rounds.append({"round": r, "step": step, "chain": chain, "diversity": div, "n_verified": nver})
        log(f"[exp035]   seed={seed} round={r}: step={step:.3f} chain={chain:.3f} div={div:.3f} n_ver={nver}")

    dt = time.time() - t0
    log(f"[exp035] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "rounds": rounds}


def verdict(seeds_res, args):
    R = args.rounds
    # promedio por ronda sobre seeds
    def avg(metric, r):
        return float(np.mean([next(x[metric] for x in s["rounds"] if x["round"] == r) for s in seeds_res]))
    step = [avg("step", r) for r in range(R + 1)]
    chain = [avg("chain", r) for r in range(R + 1)]
    div = [avg("diversity", r) for r in range(R + 1)]
    peak = max(step)
    peak_r = step.index(peak)
    final = step[-1]
    base = step[0]
    improves = (peak - base) >= args.margin
    # colapso de precisión: cae > margen tras el pico
    collapses_acc = (peak - final) > args.margin and peak_r < R
    # colapso de diversidad: cae por debajo de 0.5x la inicial
    div_collapse = div[-1] < 0.5 * div[0]
    non_decreasing = all(step[r + 1] >= step[r] - args.margin for r in range(R))
    saturates_immediately = improves and (step[-1] - step[1]) <= args.margin and (step[1] - step[0]) >= args.margin and R >= 2

    if improves and non_decreasing and not div_collapse and not collapses_acc:
        v = "APOYADA"
    elif collapses_acc or div_collapse:
        v = "REFUTADA"
    else:
        v = "MIXTA"
    return v, {"step": step, "chain": chain, "diversity": div, "peak": peak, "peak_round": peak_r,
               "final": final, "base": base, "improves": improves, "collapses_acc": collapses_acc,
               "div_collapse": div_collapse, "non_decreasing": non_decreasing,
               "saturates_immediately": saturates_immediately, "n_seeds": len(seeds_res)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--M", type=int, default=150, help="cadenas K=2 para medir")
    ap.add_argument("--n_prompts", type=int, default=384)
    ap.add_argument("--K", type=int, default=6, help="completaciones por prompt en la generación")
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
        args.seeds, args.rounds, args.M, args.base_steps, args.star_steps, args.n_prompts = "0,1", 2, 80, 300, 120, 160

    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    logs = []

    def log(m):
        print(m, flush=True)
        logs.append(m)

    train_pairs, test_pairs = T.build_split(args.lo, args.hi, args.test_frac)
    test = T.test_from_pairs(test_pairs)

    log(f"[exp035] CYCLE 49 / H-V4-2b — ITERAR el lazo de auto-mejora verificada (modelo propio)")
    log(f"[exp035] suma [{args.lo},{args.hi}] test={len(test)} rounds={args.rounds} M={args.M} "
        f"n_prompts={args.n_prompts} star_steps={args.star_steps} seeds={seeds}")

    res = [run_seed(s, args, train_pairs, test, log) for s in seeds]
    v, stats = verdict(res, args)
    log(f"[exp035] VEREDICTO H-V4-2b: {v} | PASO por ronda={['%.3f' % x for x in stats['step']]} "
        f"(base={stats['base']:.3f} pico={stats['peak']:.3f}@r{stats['peak_round']} final={stats['final']:.3f})")
    log(f"[exp035] CADENA por ronda={['%.3f' % x for x in stats['chain']]} | DIVERSIDAD={['%.3f' % x for x in stats['diversity']]} "
        f"(colapso_acc={stats['collapses_acc']} colapso_div={stats['div_collapse']} no_decrece={stats['non_decreasing']})")

    out = {"exp": "exp035_iterated_star", "cycle": 49, "hypothesis": "H-V4-2b",
           "claim": "iterar el lazo de auto-mejora verificada es un motor ESTABLE (la precisión por paso sube y "
                    "platea sin colapsar diversidad/precisión)",
           "verdict": v, "stats": stats, "args": vars(args), "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp035] escrito {path}")


if __name__ == "__main__":
    main()

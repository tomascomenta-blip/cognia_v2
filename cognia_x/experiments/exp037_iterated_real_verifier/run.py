r"""
exp037 — CYCLE 51 / H-V4-2d: ¿el LAZO ITERADO de auto-mejora con GUARDIA (sub-arco 48-50) sobrevive con un
VERIFICADOR REAL-CHEQUEABLE (sandbox, exp018) en vez del oráculo aritmético EXACTO? — y ¿hay plateau/techo?

CONTEXTO: el sub-arco AUTO-MEJORA (48-50) mostró que el lazo iterado es un motor estable (49) y que una guardia
barata (dedup+replay) controla el narrowing y sube el techo (50) — pero TODO sobre la SUMA con oráculo EXACTO.
Límite honesto del CYCLE 50: "falta verificador real-chequeable y medir el techo real". exp018 (H-LEARN-3) ya
mostró que UNA ronda de auto-mejora funciona con un verificador REAL (sandbox que EJECUTA la expresión). Este
ciclo FUNDE los dos arcos: corre el lazo ITERADO (R rondas) PLANO vs GUARDED sobre SÍNTESIS DE EXPRESIONES con
el verificador FUERTE real, y mide por ronda real_acc (held-out), COBERTURA (prompts distintos verificados) y
degenerate (echo = señal de reward-hack). Pregunta: ¿el motor generaliza del oráculo exacto a un verificador
real SOBRE ITERACIÓN, la guardia sigue controlando el narrowing, y NO emerge reward-hack al iterar?

ANALOGÍA: pasaste de practicar SUMAS (corregís mirando la tabla) a escribir PROGRAMAS (corregís EJECUTÁNDOLOS).
El corrector ya no es cerrado/perfecto. ¿Repetir rondas sobre tus propios programas que PASARON los tests te
sigue mejorando y variado, o te encerrás / aprendés a engañar al test (echo)?

DISEÑO (modelo propio; funde exp018 + exp036). Por seed, dos lazos de R rondas IN-PLACE desde el MISMO base:
  - PLANO: cada ronda genera K exprs/prompt, se queda con las STRONG-verificadas (sandbox: valor==target Y usa
    operador), entrena con TODAS (con repetición por frecuencia).
  - GUARDED: STRONG-verificadas DEDUP (cada (prompt,expr) único) + REPLAY de replay_n ejemplos semilla
    CORRECTOS de la VERDAD (datos originales, no auto-generados).
Métricas por ronda: real_acc (verificador FUERTE en test held-out DISJUNTO), COBERTURA = nº de prompts
distintos en el set verificado, degenerate (frac echo en test). 3 seeds, R=6.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si el lazo con verificador REAL (a) SUBE real_acc sobre base y es NO-DECRECIENTE (motor estable bajo
    un verificador REAL, no solo el oráculo) Y (b) la GUARDIA mantiene COBERTURA >= plano al final sin costo de
    real_acc Y (c) degenerate NO trepa con las rondas (no emerge reward-hack al iterar).
  - REFUTADA si real_acc COLAPSA tras su pico (iterar con el verificador real degrada) O degenerate trepa con
    las rondas (el lazo iterado aprende el echo) O la guardia NO controla la cobertura.
  - MIXTA si mejora pero satura inmediato, o la guardia es innecesaria (plano no narrowing), o señal ambigua.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp037_iterated_real_verifier.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp037_iterated_real_verifier.run            # FULL
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

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
LO, HI = 2, 300                              # mismos targets que exp018 -> test held-out grande


def coverage_prompts(verified):
    """Nº de PROMPTS distintos en el set verificado (cobertura del espacio de problemas; cae si narrowing)."""
    return len(set(bytes(p) for (p, e) in verified))


def seed_correct(train_targets, n, rng):
    """n ejemplos CORRECTOS de la VERDAD (expresión real, no auto-generada) para replay (guarded)."""
    sel = rng.integers(0, len(train_targets), size=n)
    return [(E.make_prompt(train_targets[i]), E.real_expression(rng, train_targets[i])) for i in sel]


def run_loop(base, pool_prompts, test_targets, args, guarded, gen_seed, replay_pairs, log, tag):
    """Lazo de R rondas in-place sobre una COPIA del base. Devuelve lista por ronda con real/cov/degen."""
    model = copy.deepcopy(base)
    train_rng = np.random.default_rng(gen_seed)
    rounds = []
    bm = E.eval_metrics(model, test_targets, "cpu")
    rounds.append({"round": 0, "real": round(bm["real_acc"], 4), "coverage": 0,
                   "degen": round(bm["degenerate"], 4)})
    for r in range(1, args.rounds + 1):
        torch.manual_seed(20000 + 13 * r)
        pool = generate_pool(model, pool_prompts, args.K, args.temperature, args.top_k, "cpu")
        strong = [(p, e) for (p, e, w, s) in pool if s]      # STRONG-verificadas (sandbox real)
        cov = coverage_prompts(strong)
        if guarded:
            uniq = list(dict.fromkeys((bytes(p), bytes(e)) for (p, e) in strong))  # dedup, preserva orden
            train_set = [(bytes(p), bytes(e)) for (p, e) in uniq] + replay_pairs   # + replay de la verdad
        else:
            train_set = strong
        if train_set:
            train_arm(model, train_set, args.steps, args.batch, args.lr, "cpu",
                      np.random.default_rng(98000 + r))
        mm = E.eval_metrics(model, test_targets, "cpu")
        rounds.append({"round": r, "real": round(mm["real_acc"], 4), "coverage": cov,
                       "degen": round(mm["degenerate"], 4)})
        log(f"[exp037]   {tag} round={r}: real={mm['real_acc']:.3f} cov={cov} degen={mm['degenerate']:.3f} "
            f"n_strong={len(strong)}")
    return rounds


def run_seed(seed, args, train_targets, test_targets, log):
    t0 = time.time()
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch,
                            train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp037] seed={seed} base real_acc={bm['real_acc']:.3f} degen={bm['degenerate']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    replay = seed_correct(train_targets, args.replay_n, np.random.default_rng(99000 + seed))
    plain = run_loop(base, pool_prompts, test_targets, args, False, 95000 + seed, replay, log, f"s{seed}/PLAIN")
    guarded = run_loop(base, pool_prompts, test_targets, args, True, 95000 + seed, replay, log, f"s{seed}/GUARD")
    dt = time.time() - t0
    log(f"[exp037] seed={seed} {dt:.1f}s npar={npar}")
    return {"seed": seed, "npar": npar, "secs": round(dt, 2), "base": bm, "plain": plain, "guarded": guarded}


def verdict(seeds_res, args, m):
    R = args.rounds
    margin = round(2 * math.sqrt(0.25 / max(1, m)), 4)        # 2σ del eval (p~0.5)

    def avg(arm, metric, r):
        return float(np.mean([next(x[metric] for x in s[arm] if x["round"] == r) for s in seeds_res]))

    real_p = [avg("plain", "real", r) for r in range(R + 1)]
    real_g = [avg("guarded", "real", r) for r in range(R + 1)]
    cov_p = [avg("plain", "coverage", r) for r in range(R + 1)]
    cov_g = [avg("guarded", "coverage", r) for r in range(R + 1)]
    deg_p = [avg("plain", "degen", r) for r in range(R + 1)]
    deg_g = [avg("guarded", "degen", r) for r in range(R + 1)]

    base = real_g[0]
    peak_g = max(real_g)
    peak_r = real_g.index(peak_g)
    # (a) motor estable bajo verificador REAL (config de producción = GUARDED)
    improves = (peak_g - base) >= margin
    non_decreasing = all(real_g[r + 1] >= real_g[r] - margin for r in range(R))
    collapses = (peak_g - real_g[R]) > margin and peak_r < R
    # (b) la guardia controla el narrowing: mantiene cobertura >= plano al final sin costo de real_acc
    guard_keeps_cov = cov_g[R] >= cov_p[R] - 1e-9
    no_prec_cost = real_g[R] >= real_p[R] - margin
    plain_narrows = cov_p[R] < cov_p[1] - 1e-9
    # (c) NO emerge reward-hack al iterar: degenerate no trepa con las rondas
    hack_g = (deg_g[R] - deg_g[0]) > 0.05
    hack_p = (deg_p[R] - deg_p[0]) > 0.10
    no_hack = not hack_g

    if collapses or hack_g:
        v = "REFUTADA"
    elif improves and non_decreasing and guard_keeps_cov and no_prec_cost and no_hack:
        v = "APOYADA"
    else:
        v = "MIXTA"
    return v, {"margin": margin, "real_plain": real_p, "real_guarded": real_g, "cov_plain": cov_p,
               "cov_guarded": cov_g, "degen_plain": deg_p, "degen_guarded": deg_g, "base": base,
               "peak_guarded": peak_g, "peak_round": peak_r, "improves": improves,
               "non_decreasing": non_decreasing, "collapses": collapses, "guard_keeps_cov": guard_keeps_cov,
               "no_prec_cost": no_prec_cost, "plain_narrows": plain_narrows, "hack_guarded": hack_g,
               "hack_plain": hack_p, "no_hack": no_hack, "n_seeds": len(seeds_res)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--K", type=int, default=6)
    ap.add_argument("--pool", type=int, default=256)
    ap.add_argument("--replay_n", type=int, default=128, help="ejemplos semilla CORRECTOS para replay (guarded)")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--top_k", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--n_seed", type=int, default=256)
    # base_steps=200 calibrado para base real_acc~0.44 (banda [0.15,0.55], con margen para mejorar);
    # 1500 satura cerca del techo y mata el poder del experimento.
    ap.add_argument("--base_steps", type=int, default=200)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()

    if args.smoke:
        args.seeds, args.rounds, args.base_steps, args.steps, args.pool = "0,1", 3, 400, 80, 128

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
    log(f"[exp037] CYCLE 51 / H-V4-2d — lazo ITERADO + guardia con VERIFICADOR REAL (sandbox) (modelo propio)")
    log(f"[exp037] exprs target [{LO},{HI}] train={len(train_targets)} test={len(test_targets)} "
        f"rounds={args.rounds} K={args.K} pool={args.pool} replay_n={args.replay_n} seeds={seeds}")

    res = [run_seed(s, args, train_targets, test_targets, log) for s in seeds]
    v, stats = verdict(res, args, len(test_targets))
    R = args.rounds
    log(f"[exp037] VEREDICTO H-V4-2d: {v} | margin={stats['margin']:.3f}")
    log(f"[exp037] REAL_acc  plano={['%.3f' % x for x in stats['real_plain']]} guarded={['%.3f' % x for x in stats['real_guarded']]} "
        f"(base={stats['base']:.3f} pico_g={stats['peak_guarded']:.3f}@r{stats['peak_round']} final_g={stats['real_guarded'][R]:.3f})")
    log(f"[exp037] COBERTURA plano={['%.0f' % x for x in stats['cov_plain']]} guarded={['%.0f' % x for x in stats['cov_guarded']]} "
        f"(narrowing_plano={stats['plain_narrows']} guardia_mantiene={stats['guard_keeps_cov']})")
    log(f"[exp037] DEGEN     plano={['%.3f' % x for x in stats['degen_plain']]} guarded={['%.3f' % x for x in stats['degen_guarded']]} "
        f"(hack_g={stats['hack_guarded']} hack_p={stats['hack_plain']})")
    log(f"[exp037] checks: improves={stats['improves']} no_decrece={stats['non_decreasing']} "
        f"colapsa={stats['collapses']} sin_costo_prec={stats['no_prec_cost']} sin_hack={stats['no_hack']}")

    out = {"exp": "exp037_iterated_real_verifier", "cycle": 51, "hypothesis": "H-V4-2d",
           "claim": "el lazo iterado de auto-mejora con guardia (dedup+replay) generaliza del oráculo aritmético "
                    "EXACTO a un VERIFICADOR REAL-CHEQUEABLE (sandbox) sobre iteración, sin colapso ni reward-hack",
           "verdict": v, "stats": stats, "args": vars(args), "seeds": res, "task_range": [LO, HI],
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    path = os.path.join(RESULTS, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp037] escrito {path}")
    logf.close()


if __name__ == "__main__":
    main()

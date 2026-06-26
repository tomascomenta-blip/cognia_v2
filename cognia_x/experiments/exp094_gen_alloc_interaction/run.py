r"""
exp094 — CYCLE 110 / H-V4-8o (rama R-VALOR, PIVOT generación↔asignación, bridge a creatividad pillar #4): todo el arco
asignó sobre un pool DADO. Pero el pool lo produce el GENERADOR, y su DIVERSIDAD (temperatura) es una palanca aparte.
¿La diversidad del generador y la calidad de la asignación son COMPLEMENTARIAS? Intuición: con BUENA asignación (verificar
lo más prometedor) podés permitirte MÁS diversidad (el filtro la aprovecha: más exploración, te quedás con lo bueno); con
asignación POBRE (verificar al azar) la diversidad DAÑA (entrenás en más basura). => interacción temp×alloc POSITIVA.

CONTEXTO. Conecta el lazo de auto-mejora (93-107) con la GENERACIÓN/creatividad: la política de asignación no sólo decide
qué verificar, también cambia cuánta EXPLORACIÓN del generador conviene. Es un puente generación–selección.

DISEÑO (PyTorch CPU; reusa exp018/exp077). Lazo cerrado real. 2×2: temperatura del generador ∈ {LOW, HIGH} ×
asignación ∈ {conf (top-k por confianza), random (top-k al azar)}, bajo presupuesto de verificación fijo (k por ronda). Las
strong-correctas entrenan. MÉTRICA: real_acc held-out (downstream). INTERACCIÓN = (conf_high − conf_low) − (random_high −
random_low): >0 si la diversidad paga MÁS bajo buena asignación. 4 seeds.

PREGUNTA FALSABLE:
  - APOYADA si INTERACCIÓN > 0 (margen): bajo conf-alloc subir la temperatura ayuda (o daña menos) MÁS que bajo
    random-alloc. => diversidad del generador y calidad de asignación son COMPLEMENTARIAS: buena asignación habilita más
    exploración. (Bridge generación–selección / R-VALOR gobierna cuánto explorar.)
  - REFUTADA si INTERACCIÓN <= 0 (la asignación no cambia el óptimo de diversidad).
  - MIXTA si el signo depende del seed/ruidoso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp094_gen_alloc_interaction.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp094_gen_alloc_interaction.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
import sys

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, train_arm, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
CONFIGS = ["conf_low", "conf_high", "random_low", "random_high"]


def _alloc(conf, strong, k, mode, rng):
    n = len(conf)
    if mode == "conf":
        order = np.argsort(conf + 1e-9 * rng.random(n))[::-1]
    else:
        order = rng.permutation(n)
    return list(order[:k])


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp094] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {c: copy.deepcopy(base) for c in CONFIGS}
    hist = {c: {"real": [round(bm["real_acc"], 4)], "yield": []} for c in CONFIGS}
    corrs = []
    train_rng = np.random.default_rng(seed + 99)
    temp = {"low": args.temp_low, "high": args.temp_high}

    for r in range(1, args.rounds + 1):
        for c in CONFIGS:
            mode, lvl = c.split("_")
            torch.manual_seed(10000 * seed + r + (0 if lvl == "low" else 5))
            pool = generate_pool(arms[c], pool_prompts, args.K, temp[lvl], args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            rng_a = np.random.default_rng(seed * 131 + r * 17 + CONFIGS.index(c))
            conf = _confidence(arms[c], pairs, "cpu")
            if c == "conf_low" and r == 1:
                corrs.append(round(_corr(conf, strong), 4))
            sel_idx = _alloc(conf, strong, k, mode, rng_a)
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[c]["yield"].append(len(ex))
            if ex:
                train_arm(arms[c], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[c], test_targets, "cpu")
            hist[c]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp094] seed={seed} ronda {r}: "
            + " | ".join(f"{c}: y={hist[c]['yield'][-1]} real={hist[c]['real'][-1]:.3f}" for c in CONFIGS))

    return {"seed": seed, "base": bm, "hist": hist, "conf_strong_corr": (corrs[0] if corrs else 0.0)}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def build_summary(per_seed):
    def mr(c):
        return [sum(s["hist"][c]["real"][1:]) / len(s["hist"][c]["real"][1:]) for s in per_seed]

    cl, chh = mr("conf_low"), mr("conf_high")
    rl, rh = mr("random_low"), mr("random_high")
    nseed = len(per_seed)
    conf_temp_effect = round(_mean(chh) - _mean(cl), 4)        # efecto de subir temp bajo conf-alloc
    rand_temp_effect = round(_mean(rh) - _mean(rl), 4)         # efecto de subir temp bajo random-alloc
    interaction = round(conf_temp_effect - rand_temp_effect, 4)
    # signo por seed
    inter_by_seed = [round((chh[i] - cl[i]) - (rh[i] - rl[i]), 4) for i in range(nseed)]
    pos_frac = sum(1 for x in inter_by_seed if x > 0) / nseed

    MARGIN = 0.02
    complementary = interaction > MARGIN and pos_frac >= 0.6

    if complementary:
        status = "apoyada"
        verdict = ("H-V4-8o APOYADA: la DIVERSIDAD del generador y la CALIDAD de la asignación son COMPLEMENTARIAS. Subir "
                   "la temperatura del generador ayuda (o daña menos) MÁS bajo buena asignación (conf): efecto-temp bajo "
                   "conf={cte} vs bajo random={rte} -> INTERACCIÓN=+{it} ({pf:.0%} de los seeds positiva). => con buena "
                   "asignación (verificar lo prometedor) conviene MÁS exploración del generador (el filtro la aprovecha); "
                   "con asignación pobre la diversidad daña (más basura sin filtrar). R-VALOR (la política de asignación) "
                   "gobierna cuánta EXPLORACIÓN del generador conviene -- puente generación–selección. "
                   "corr(conf,strong)={csc}.").format(cte=_f(conf_temp_effect), rte=_f(rand_temp_effect), it=_f(interaction),
                                                      pf=pos_frac, csc=_f(_mean([s["conf_strong_corr"] for s in per_seed])))
    elif interaction <= MARGIN and interaction >= -MARGIN:
        status = "refutada"
        verdict = ("H-V4-8o REFUTADA: la asignación NO cambia el óptimo de diversidad (interacción={it} ≈ 0; efecto-temp "
                   "conf={cte} vs random={rte}) -> generación y asignación no son complementarias en este lazo.").format(
                       it=_f(interaction), cte=_f(conf_temp_effect), rte=_f(rand_temp_effect))
    else:
        status = "mixta"
        verdict = ("H-V4-8o MIXTA: interacción={it} pero inconsistente por seed ({pf:.0%} positiva) o de signo "
                   "inesperado (conf-effect={cte}, random-effect={rte}).").format(
                       it=_f(interaction), pf=pos_frac, cte=_f(conf_temp_effect), rte=_f(rand_temp_effect))

    return {"configs": CONFIGS, "n_seeds": nseed, "conf_strong_corr_by_seed": [s["conf_strong_corr"] for s in per_seed],
            "real_conf_low": [round(x, 3) for x in cl], "real_conf_high": [round(x, 3) for x in chh],
            "real_random_low": [round(x, 3) for x in rl], "real_random_high": [round(x, 3) for x in rh],
            "conf_temp_effect": conf_temp_effect, "rand_temp_effect": rand_temp_effect, "interaction": interaction,
            "interaction_by_seed": inter_by_seed, "pos_frac": round(pos_frac, 3), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp_low", type=float, default=0.9)
    ap.add_argument("--temp_high", type=float, default=1.7)
    ap.add_argument("--top_k", type=int, default=0)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--n_seed", type=int, default=200)
    ap.add_argument("--base_steps", type=int, default=250)
    ap.add_argument("--base_lr", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--test_frac", type=float, default=0.30)
    args = ap.parse_args()
    if args.top_k <= 0:
        args.top_k = None
    if args.smoke:
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 2, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp094] CYCLE 110 / H-V4-8o — generación↔asignación: ¿diversidad del generador y calidad de asignación complementarias?")
    log(f"[exp094] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"temp_low={args.temp_low} temp_high={args.temp_high} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp094] corr(conf,strong)={sm['conf_strong_corr_by_seed']}")
    log(f"[exp094] real_acc: conf_low={sm['real_conf_low']} conf_high={sm['real_conf_high']} random_low={sm['real_random_low']} random_high={sm['real_random_high']}")
    log(f"[exp094] efecto-temp: conf={sm['conf_temp_effect']:+.3f} random={sm['rand_temp_effect']:+.3f} | INTERACCIÓN={sm['interaction']:+.3f} (pos {sm['pos_frac']:.0%})")
    log(f"[exp094] VEREDICTO H-V4-8o: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp094_gen_alloc_interaction", "cycle": 110, "hypothesis": "H-V4-8o",
           "claim": "la diversidad del generador (temperatura) y la calidad de la asignacion son COMPLEMENTARIAS: subir la "
                    "diversidad paga mas bajo buena asignacion (el filtro la aprovecha) que bajo asignacion pobre "
                    "(interaccion temp x alloc positiva) -> R-VALOR gobierna cuanta exploracion del generador conviene",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp094] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

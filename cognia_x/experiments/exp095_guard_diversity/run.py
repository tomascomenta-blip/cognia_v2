r"""
exp095 — CYCLE 111 / H-V4-8p (rama R-VALOR, RESUELVE el caveat de CYCLE 110): en 110 el MEJOR config absoluto fue
random+low (pool limpio+diverso), NO conf+high, porque conf-alloc SOLA NARROWS (CYCLE 93/94: se encasilla en sus
generaciones confiadas). El filtro 'bueno' COMPLETO incluye la GUARDIA DE DIVERSIDAD (CYCLE 94/exp078: dedup de
verificados + replay de verdad canónica). ¿conf + GUARDIA + alta diversidad del generador vence a random+low? Es decir,
¿el filtro completo HABILITA que la diversidad gane globalmente?

CONTEXTO. Cierra el bucle generación↔selección (110) usando la guardia anti-narrowing (94): si la guardia destraba el
narrowing de conf, entonces el filtro completo (conf+guardia) + alta diversidad debería ser el mejor config -- recuperando
la complementariedad como óptimo GLOBAL, no sólo como interacción.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp078). Lazo cerrado real, presupuesto de verificación por conteo (k/ronda).
Configs:
  - random_low:       random-alloc, temp BAJA (el ganador de 110).
  - conf_high:        conf-alloc SIN guardia, temp ALTA (narrows pese a la diversidad).
  - conf_guard_high:  conf-alloc + GUARDIA (dedup+replay) + temp ALTA (filtro COMPLETO + diversidad).
Las strong-correctas (+ replay para la guardia) entrenan. MÉTRICA: real_acc held-out (downstream). 4 seeds.

PREGUNTA FALSABLE:
  - APOYADA si conf_guard_high es el MEJOR: > conf_high (la guardia destraba el narrowing) Y >= random_low − margen (el
    filtro completo + diversidad iguala o vence al pool limpio+diverso). => el filtro COMPLETO (asignación por valor +
    guardia de diversidad) HABILITA que la alta diversidad del generador sea el óptimo global; resuelve el caveat de 110.
  - REFUTADA si conf_guard_high NO supera a conf_high (la guardia no ayuda) o queda muy por debajo de random_low.
  - MIXTA si la guardia ayuda pero no alcanza a random_low.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp095_guard_diversity.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp095_guard_diversity.run            # FULL
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
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
# config -> (alloc, guard, temp_level)
CONFIGS = {
    "random_low": ("random", False, "low"),
    "conf_high": ("conf", False, "high"),
    "conf_guard_high": ("conf", True, "high"),
}
ORDER = ["random_low", "conf_high", "conf_guard_high"]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp095] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))
    temp = {"low": args.temp_low, "high": args.temp_high}

    arms = {c: copy.deepcopy(base) for c in ORDER}
    hist = {c: {"real": [round(bm["real_acc"], 4)], "yield": [], "ntrain": []} for c in ORDER}
    corrs = []
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for c in ORDER:
            alloc, guard, lvl = CONFIGS[c]
            torch.manual_seed(10000 * seed + r + (0 if lvl == "low" else 5))
            pool = generate_pool(arms[c], pool_prompts, args.K, temp[lvl], args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            n = len(pool)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ORDER.index(c))
            if alloc == "random":
                sel_idx = rng_a.choice(n, size=min(k, n), replace=False)
            else:
                conf = _confidence(arms[c], pairs, "cpu")
                if c == "conf_high" and r == 1:
                    corrs.append(round(_corr(conf, strong), 4))
                sel_idx = np.argsort(conf + 1e-9 * rng_a.random(n))[-min(k, n):]
            ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
            hist[c]["yield"].append(len(ex))
            if guard:                                          # GUARDIA (CYCLE 94): dedup + replay de verdad canónica
                ex = _dedup(ex)
                ex = ex + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(ex)))))
            hist[c]["ntrain"].append(len(ex))
            if ex:
                train_arm(arms[c], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[c], test_targets, "cpu")
            hist[c]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp095] seed={seed} ronda {r}: "
            + " | ".join(f"{c}: y={hist[c]['yield'][-1]} ntr={hist[c]['ntrain'][-1]} real={hist[c]['real'][-1]:.3f}" for c in ORDER))

    return {"seed": seed, "base": bm, "hist": hist, "conf_strong_corr": (corrs[0] if corrs else 0.0)}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def build_summary(per_seed):
    def mr(c):
        return [sum(s["hist"][c]["real"][1:]) / len(s["hist"][c]["real"][1:]) for s in per_seed]

    rl, ch, cgh = mr("random_low"), mr("conf_high"), mr("conf_guard_high")
    nseed = len(per_seed)
    guard_vs_plain = round(_mean(cgh) - _mean(ch), 4)         # la guardia destraba el narrowing de conf
    guard_vs_random = round(_mean(cgh) - _mean(rl), 4)        # filtro completo+diversidad vs ganador de 110
    guard_best = all(cgh[i] >= max(rl[i], ch[i]) - 1e-9 for i in range(nseed))

    GUARD_MARGIN = 0.03
    RANDOM_MARGIN = 0.03
    guard_helps = guard_vs_plain > GUARD_MARGIN
    matches_or_beats_random = guard_vs_random >= -RANDOM_MARGIN

    if guard_helps and matches_or_beats_random:
        status = "apoyada"
        verdict = ("H-V4-8p APOYADA: el filtro COMPLETO (asignación por valor + GUARDIA de diversidad, CYCLE 94) HABILITA "
                   "que la alta diversidad del generador sea el óptimo GLOBAL -- resuelve el caveat de CYCLE 110. "
                   "conf_guard_high={cgh} > conf_high={ch} (+{gp}: la guardia DESTRABA el narrowing de conf) y "
                   "{rel} random_low={rl} ({gr}). => con el filtro completo, conf+guardia+alta-diversidad iguala o vence "
                   "al pool limpio+diverso (random_low); la complementariedad generación↔selección se vuelve óptimo "
                   "global, no sólo interacción. corr(conf,strong)={csc}.").format(
                       cgh=_f(_mean(cgh)), ch=_f(_mean(ch)), gp=_f(guard_vs_plain),
                       rel="iguala/supera a" if guard_vs_random >= 0 else "se acerca a", rl=_f(_mean(rl)),
                       gr=("+" + _f(guard_vs_random)) if guard_vs_random >= 0 else _f(guard_vs_random),
                       csc=_f(_mean([s["conf_strong_corr"] for s in per_seed])))
    elif not guard_helps:
        status = "refutada"
        verdict = ("H-V4-8p REFUTADA: la guardia NO destraba el narrowing (conf_guard_high={cgh} ≈ conf_high={ch}, +{gp} "
                   "<= {m}) -> el filtro completo no recupera la diversidad.").format(
                       cgh=_f(_mean(cgh)), ch=_f(_mean(ch)), gp=_f(guard_vs_plain), m=GUARD_MARGIN)
    else:
        status = "mixta"
        verdict = ("H-V4-8p MIXTA: la guardia ayuda (+{gp}) pero conf_guard_high={cgh} queda por debajo de random_low={rl} "
                   "({gr}) -> el filtro completo mejora pero no alcanza al pool limpio+diverso.").format(
                       gp=_f(guard_vs_plain), cgh=_f(_mean(cgh)), rl=_f(_mean(rl)), gr=_f(guard_vs_random))

    return {"configs": ORDER, "n_seeds": nseed, "conf_strong_corr_by_seed": [s["conf_strong_corr"] for s in per_seed],
            "real_random_low": [round(x, 3) for x in rl], "real_conf_high": [round(x, 3) for x in ch],
            "real_conf_guard_high": [round(x, 3) for x in cgh], "guard_vs_plain": guard_vs_plain,
            "guard_vs_random": guard_vs_random, "guard_best_all_seeds": bool(guard_best), "guard_helps": bool(guard_helps),
            "matches_or_beats_random": bool(matches_or_beats_random), "status": status, "verdict": verdict}


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
    ap.add_argument("--replay_frac", type=float, default=0.5)
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

    log("[exp095] CYCLE 111 / H-V4-8p — ¿conf+GUARDIA+alta-diversidad vence a random_low? (resuelve el caveat de 110)")
    log(f"[exp095] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"temp_low={args.temp_low} temp_high={args.temp_high} replay_frac={args.replay_frac} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp095] corr(conf,strong)={sm['conf_strong_corr_by_seed']}")
    log(f"[exp095] real_acc: random_low={sm['real_random_low']} conf_high={sm['real_conf_high']} conf_guard_high={sm['real_conf_guard_high']}")
    log(f"[exp095] guard_vs_plain=+{sm['guard_vs_plain']:.3f} | guard_vs_random={sm['guard_vs_random']:+.3f} | guard_best_all_seeds={sm['guard_best_all_seeds']}")
    log(f"[exp095] VEREDICTO H-V4-8p: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp095_guard_diversity", "cycle": 111, "hypothesis": "H-V4-8p",
           "claim": "el filtro COMPLETO (asignacion por valor + guardia de diversidad CYCLE 94) habilita que la alta "
                    "diversidad del generador sea el optimo global: conf+guardia+alta-diversidad destraba el narrowing de "
                    "conf e iguala/vence a random_low (ganador de 110) -> resuelve el caveat de 110",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp095] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

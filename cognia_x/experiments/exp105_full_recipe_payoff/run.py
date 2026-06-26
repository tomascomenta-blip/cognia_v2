r"""
exp105 — CYCLE 121 / H-V4-9a (rama R-VALOR, payoff END-TO-END de la RECETA COMPLETA): 120 mostró que el selector durable
SIN ancla no paga (calibración y capacidad son ejes separados). 119 mostró que CON ancla el unlikelihood preserva la
calibración a cero costo de capacidad (en 6 rondas el downstream fue ≈). La pregunta definitiva: con el ANCLA presente (que
sostiene la capacidad), ¿añadir el unlikelihood -- que mantiene el selector calibrado -- TRADUCE a un downstream
SOSTENIDAMENTE mejor sobre MUCHAS rondas bajo presupuesto AJUSTADO, vs la receta ancla-sola (la guardia de 115, el mejor
previo)? La intuición: bajo presupuesto ajustado, el selector mejor-calibrado encuentra más correctos (yield) ronda a
ronda y eso COMPONE en el downstream.

CONTEXTO. Es el test end-to-end CORRECTO de si la cura de durabilidad (119) PAGA en la práctica: corrige el confound de
120 (que quitó el ancla). Compara la receta COMPLETA vs el mejor previo (ancla-sola).

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp103). Lazo cerrado real, MUCHAS rondas, presupuesto AJUSTADO, selección por
confianza, replay-ANCLA en AMBOS brazos. Brazos:
  - anchor_only:  likelihood(verificado-correcto) + replay-ancla (la guardia de 115; mejor previo).
  - full:         lo mismo + unlikelihood ACOTADO sobre verificado-incorrecto (receta completa: ancla + 119).
MÉTRICA: trayectoria de real_acc (final + AUC), yield, corr. 4 seeds, 8 rondas.

PREGUNTA FALSABLE:
  - APOYADA si full SOSTIENE mejor el downstream que anchor_only (real_acc final +>margen Y AUC > 0), con corr/yield full >
    anchor_only. => la cura de durabilidad (unlikelihood) AÑADE valor sobre la receta ancla-sola: el selector
    mejor-calibrado compone en el downstream bajo presupuesto ajustado. La receta COMPLETA (ancla + unlikelihood) es el
    lazo de auto-mejora durable óptimo.
  - REFUTADA si full ≈ anchor_only en downstream (el unlikelihood no añade sobre el ancla -> con el ancla presente, la
    calibración extra no compone; el ancla ya basta).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp105_full_recipe_payoff.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp105_full_recipe_payoff.run            # FULL
"""
import argparse
import copy
import json
import math
import os
import platform
import sys

import numpy as np
import torch

from cognia_x.experiments.exp018_real_verifier import expression_task as E
from cognia_x.experiments.exp018_real_verifier.run import build_base, generate_pool, LO, HI
from cognia_x.experiments.exp077_closed_loop_budget.run import _confidence, _corr
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup, _replay_examples
from cognia_x.experiments.exp103_bounded_unlikelihood.run import _train

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["anchor_only", "full"]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp105] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "yield": [], "corr": []} for a in ARMS}
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            cc = _corr(conf, strong)
            hist[a]["corr"].append(round(cc, 4) if not math.isnan(cc) else 0.0)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * rng_a.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            hist[a]["yield"].append(len(pos))
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))  # ANCLA en ambos
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if a == "full" else []
            _train(arms[a], pos, neg, args.steps, args.batch, args.lr,
                   args.neg_w if a == "full" else 0.0, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp105] seed={seed} ronda {r}: "
            + " | ".join(f"{a}: y={hist[a]['yield'][-1]} corr={hist[a]['corr'][-1]:.3f} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "hist": hist}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def build_summary(per_seed):
    def real_final(a):
        return _mean([s["hist"][a]["real"][-1] for s in per_seed])

    def real_auc(a):
        return _mean([_mean(s["hist"][a]["real"][1:]) for s in per_seed])

    def yield_mean(a):
        return _mean([_mean(s["hist"][a]["yield"]) for s in per_seed])

    def corr_final(a):
        return _mean([s["hist"][a]["corr"][-1] for s in per_seed])

    rf_a, rf_f = real_final("anchor_only"), real_final("full")
    auc_a, auc_f = real_auc("anchor_only"), real_auc("full")
    y_a, y_f = yield_mean("anchor_only"), yield_mean("full")
    cf_a, cf_f = corr_final("anchor_only"), corr_final("full")
    final_gap = round(rf_f - rf_a, 4)
    auc_gap = round(auc_f - auc_a, 4)
    yield_gap = round(y_f - y_a, 4)
    corr_gap = round(cf_f - cf_a, 4)
    nseed = len(per_seed)

    MARGIN = 0.04
    adds_value = (final_gap > MARGIN) and (auc_gap > 0.0)
    no_value = (final_gap <= MARGIN) and (auc_gap <= 0.0)

    if adds_value:
        status = "apoyada"
        verdict = ("H-V4-9a APOYADA: con el ancla presente, añadir el unlikelihood (receta COMPLETA) SOSTIENE mejor el "
                   "downstream que la receta ancla-sola (115). real_acc final full={rff} vs anchor_only={rfa} (+{fg}); AUC "
                   "full={aucf} vs {auca} (+{ag}); yield full={yf} vs {ya} (+{yg}); corr final full={cff} vs {cfa} (+{cg}). "
                   "=> el selector mejor-calibrado (unlikelihood) compone en el downstream bajo presupuesto ajustado: la "
                   "receta COMPLETA (likelihood + replay-ancla + unlikelihood-acotado) es el lazo de auto-mejora durable "
                   "óptimo, mejor que el ancla-sola.").format(rff=_f(rf_f), rfa=_f(rf_a), fg=_f(final_gap), aucf=_f(auc_f),
                                                              auca=_f(auc_a), ag=_f(auc_gap), yf=_f(y_f), ya=_f(y_a),
                                                              yg=_f(yield_gap), cff=_f(cf_f), cfa=_f(cf_a), cg=_f(corr_gap))
    elif no_value:
        status = "refutada"
        verdict = ("H-V4-9a REFUTADA: con el ancla presente, el unlikelihood NO añade sobre el ancla-sola en downstream "
                   "(real_acc final full={rff} vs anchor_only={rfa}, +{fg}; AUC +{ag}; corr full={cff} vs {cfa}) -> con el "
                   "ancla ya holdeando capacidad y datos, la calibración extra no compone en este régimen.").format(
                       rff=_f(rf_f), rfa=_f(rf_a), fg=_f(final_gap), ag=_f(auc_gap), cff=_f(cf_f), cfa=_f(cf_a))
    else:
        status = "mixta"
        verdict = ("H-V4-9a MIXTA: señales mixtas (final_gap +{fg}, AUC +{ag}, yield +{yg}, corr +{cg}); el unlikelihood "
                   "añade parcialmente sobre el ancla-sola.").format(fg=_f(final_gap), ag=_f(auc_gap), yg=_f(yield_gap), cg=_f(corr_gap))

    return {"arms": ARMS, "n_seeds": nseed, "real_final_anchor": round(rf_a, 4), "real_final_full": round(rf_f, 4),
            "real_auc_anchor": round(auc_a, 4), "real_auc_full": round(auc_f, 4),
            "yield_anchor": round(y_a, 4), "yield_full": round(y_f, 4),
            "corr_final_anchor": round(cf_a, 4), "corr_final_full": round(cf_f, 4),
            "final_gap": final_gap, "auc_gap": auc_gap, "yield_gap": yield_gap, "corr_gap": corr_gap,
            "adds_value": bool(adds_value), "no_value": bool(no_value), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.10)
    ap.add_argument("--temp", type=float, default=1.3)
    ap.add_argument("--replay_frac", type=float, default=0.5)
    ap.add_argument("--neg_w", type=float, default=0.5)
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
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 5, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp105] CYCLE 121 / H-V4-9a — payoff de la RECETA COMPLETA (ancla + unlikelihood) vs ancla-sola (115)")
    log(f"[exp105] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"temp={args.temp} replay_frac={args.replay_frac} neg_w={args.neg_w} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp105] real_acc final: anchor_only={sm['real_final_anchor']:.3f} full={sm['real_final_full']:.3f} (gap +{sm['final_gap']:.3f})")
    log(f"[exp105] real_acc AUC: anchor_only={sm['real_auc_anchor']:.3f} full={sm['real_auc_full']:.3f} (gap +{sm['auc_gap']:.3f})")
    log(f"[exp105] yield: anchor={sm['yield_anchor']:.2f} full={sm['yield_full']:.2f} (+{sm['yield_gap']:.2f}) | corr final anchor={sm['corr_final_anchor']:.3f} full={sm['corr_final_full']:.3f} (+{sm['corr_gap']:.3f})")
    log(f"[exp105] adds_value={sm['adds_value']} no_value={sm['no_value']}")
    log(f"[exp105] VEREDICTO H-V4-9a: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp105_full_recipe_payoff", "cycle": 121, "hypothesis": "H-V4-9a",
           "claim": "con el ancla de replay presente (que sostiene la capacidad), anadir el unlikelihood acotado (receta "
                    "completa) sostiene mejor el downstream que la receta ancla-sola (115) bajo presupuesto ajustado: el "
                    "selector mejor-calibrado compone en el downstream -> la receta completa (likelihood + ancla + "
                    "unlikelihood) es el lazo de auto-mejora durable optimo",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp105] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

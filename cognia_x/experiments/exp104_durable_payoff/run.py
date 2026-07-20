r"""
exp104 — CYCLE 120 / H-V4-8z (rama R-VALOR, PAYOFF END-TO-END: el selector durable enabla auto-mejora SOSTENIDA): el arco
de fragilidad cerró con la cura (119: el unlikelihood ACOTADO mantiene la señal de valor calibrada). Pero, ¿esa cura
TRADUCE a un beneficio PRÁCTICO -- un lazo de auto-mejora que SOSTIENE la mejora del downstream a lo largo de muchas rondas,
bajo presupuesto AJUSTADO y SIN ancla de replay externa, donde el naive (selector que colapsa) desperdicia el presupuesto?

CONTEXTO. Es el cierre de cierres: ata la TEORÍA DE ASIGNACIÓN (asignar la verificación escasa por la señal de valor) con
la CURA DE DURABILIDAD (119). Sin replay externo, el lazo depende ENTERAMENTE del selector endógeno -> el selector durable
debería pagar.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp103). Lazo cerrado real, MUCHAS rondas, presupuesto AJUSTADO (k chico),
selección por confianza, SIN replay canónico (replay_frac=0: el lazo se sostiene solo por el selector). Brazos:
  - naive:   confianza-selección + likelihood-only (el selector colapsa, 115; bajo presupuesto desperdicia las picks).
  - durable: confianza-selección + likelihood + unlikelihood ACOTADO sobre verificado-incorrecto (119; el selector se
             mantiene calibrado -> sigue encontrando correctos bajo el presupuesto ajustado).
MÉTRICA: trayectoria de YIELD (correctos encontrados/ronda) y de real_acc; brecha final y AUC (área) de real_acc. 4 seeds,
8 rondas.

PREGUNTA FALSABLE:
  - APOYADA si durable SOSTIENE la auto-mejora mejor que naive: real_acc final durable > naive (+>margen) Y la brecha
    (AUC) es positiva/creciente, con yield durable > naive sostenido. => la cura de durabilidad (119) PAGA: el selector
    calibrado mantiene el lazo de auto-mejora productivo bajo presupuesto ajustado sin ancla externa, donde el naive se
    estanca/declina. Cierre end-to-end del arco R-VALOR.
  - REFUTADA si durable NO sostiene mejor (el selector durable no se traduce en downstream) -> la cura es de la señal pero
    no del lazo.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp104_durable_payoff.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp104_durable_payoff.run            # FULL
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
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup
from cognia_x.experiments.exp103_bounded_unlikelihood.run import _train

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["naive", "durable"]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp104] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
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
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])    # SIN replay canónico: sólo lo seleccionado-correcto
            hist[a]["yield"].append(len(pos))
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if a == "durable" else []
            _train(arms[a], pos, neg, args.steps, args.batch, args.lr,
                   args.neg_w if a == "durable" else 0.0, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp104] seed={seed} ronda {r}: "
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
        return _mean([_mean(s["hist"][a]["real"][1:]) for s in per_seed])   # promedio sobre rondas (excluye base)

    def yield_mean(a):
        return _mean([_mean(s["hist"][a]["yield"]) for s in per_seed])

    def corr_final(a):
        return _mean([s["hist"][a]["corr"][-1] for s in per_seed])

    rf_n, rf_d = real_final("naive"), real_final("durable")
    auc_n, auc_d = real_auc("naive"), real_auc("durable")
    y_n, y_d = yield_mean("naive"), yield_mean("durable")
    cf_n, cf_d = corr_final("naive"), corr_final("durable")
    final_gap = round(rf_d - rf_n, 4)
    auc_gap = round(auc_d - auc_n, 4)
    yield_gap = round(y_d - y_n, 4)
    nseed = len(per_seed)

    MARGIN = 0.04
    sustains_better = (final_gap > MARGIN) and (auc_gap > 0.0)

    if sustains_better:
        status = "apoyada"
        verdict = ("H-V4-8z APOYADA: la cura de durabilidad (119) PAGA end-to-end -- el selector durable SOSTIENE la "
                   "auto-mejora bajo presupuesto AJUSTADO y SIN replay externo. real_acc final durable={rfd} vs "
                   "naive={rfn} (+{fg}); AUC (promedio sobre rondas) durable={aucd} vs naive={aucn} (+{ag}); yield "
                   "durable={yd} vs naive={yn} (+{yg}); corr final durable={cfd} vs naive={cfn}. => el selector calibrado "
                   "por unlikelihood acotado mantiene el lazo productivo (sigue encontrando correctos bajo presupuesto "
                   "ajustado) donde el naive (selector que colapsa) desperdicia las picks y se estanca. CIERRE END-TO-END "
                   "del arco R-VALOR: la teoría de asignación + la cura de durabilidad componen en un lazo de auto-mejora "
                   "sostenido.").format(rfd=_f(rf_d), rfn=_f(rf_n), fg=_f(final_gap), aucd=_f(auc_d), aucn=_f(auc_n),
                                        ag=_f(auc_gap), yd=_f(y_d), yn=_f(y_n), yg=_f(yield_gap), cfd=_f(cf_d), cfn=_f(cf_n))
    elif final_gap <= MARGIN and auc_gap <= 0.0:
        status = "refutada"
        verdict = ("H-V4-8z REFUTADA: el selector durable NO sostiene mejor la auto-mejora (real_acc final durable={rfd} vs "
                   "naive={rfn}, +{fg}; AUC +{ag}) -> la cura es de la SEÑAL pero no se traduce en el lazo bajo este "
                   "régimen.").format(rfd=_f(rf_d), rfn=_f(rf_n), fg=_f(final_gap), ag=_f(auc_gap))
    else:
        status = "mixta"
        verdict = ("H-V4-8z MIXTA: señales mixtas de payoff (final_gap +{fg}, AUC +{ag}, yield +{yg}); el selector durable "
                   "ayuda parcialmente.").format(fg=_f(final_gap), ag=_f(auc_gap), yg=_f(yield_gap))

    return {"arms": ARMS, "n_seeds": nseed, "real_final_naive": round(rf_n, 4), "real_final_durable": round(rf_d, 4),
            "real_auc_naive": round(auc_n, 4), "real_auc_durable": round(auc_d, 4),
            "yield_naive": round(y_n, 4), "yield_durable": round(y_d, 4),
            "corr_final_naive": round(cf_n, 4), "corr_final_durable": round(cf_d, 4),
            "final_gap": final_gap, "auc_gap": auc_gap, "yield_gap": yield_gap, "sustains_better": bool(sustains_better),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.10)
    ap.add_argument("--temp", type=float, default=1.3)
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

    log("[exp104] CYCLE 120 / H-V4-8z — PAYOFF end-to-end: ¿el selector durable (119) sostiene la auto-mejora bajo presupuesto ajustado sin replay?")
    log(f"[exp104] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} budget_frac={args.budget_frac} "
        f"temp={args.temp} neg_w={args.neg_w} (SIN replay canónico) base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp104] real_acc final: naive={sm['real_final_naive']:.3f} durable={sm['real_final_durable']:.3f} (gap +{sm['final_gap']:.3f})")
    log(f"[exp104] real_acc AUC: naive={sm['real_auc_naive']:.3f} durable={sm['real_auc_durable']:.3f} (gap +{sm['auc_gap']:.3f})")
    log(f"[exp104] yield: naive={sm['yield_naive']:.2f} durable={sm['yield_durable']:.2f} (gap +{sm['yield_gap']:.2f}) | corr final naive={sm['corr_final_naive']:.3f} durable={sm['corr_final_durable']:.3f}")
    log(f"[exp104] sustains_better={sm['sustains_better']}")
    log(f"[exp104] VEREDICTO H-V4-8z: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp104_durable_payoff", "cycle": 120, "hypothesis": "H-V4-8z",
           "claim": "el selector durable (unlikelihood acotado, 119) PAGA end-to-end: sostiene la auto-mejora del "
                    "downstream bajo presupuesto ajustado y sin replay externo (mejor yield y real_acc sostenido) donde el "
                    "naive (selector que colapsa) desperdicia el presupuesto -> la teoria de asignacion + la cura de "
                    "durabilidad componen en un lazo de auto-mejora sostenido",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp104] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

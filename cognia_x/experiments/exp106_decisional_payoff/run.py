r"""
exp106 — CYCLE 122 / H-V4-9b (rama R-VALOR, CAPSTONE POSITIVO: la señal calibrada PAGA en una DECISIÓN externa): 121
re-localizó el valor de R-VALOR -- la señal calibrada NO acelera el self-training downstream (ancla-bound) sino que vale
por las DECISIONES que la USAN. Este ciclo lo confirma POSITIVAMENTE: en una decisión de ASIGNACIÓN de un recurso EXTERNO
escaso (un "submission budget": elegir m generaciones para someter a recompensa externa), ¿el selector durable (calibrado
por unlikelihood, 119) sostiene un payoff de decisión MAYOR que el naive (señal que colapsa) a lo largo de las rondas?

CONTEXTO. Es el complemento positivo de 121: muestra DÓNDE sí paga la cura de durabilidad -- en la decisión, no en el
descenso del loss. El payoff de submission depende SÓLO de la calibración del selector (qué someter), no del ancla de datos.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp103/exp105). Lazo cerrado real, ambos brazos self-trainan CON ancla (capacidad
igual). Cada ronda, ADEMÁS, se toma una DECISIÓN de submission: someter las top-m generaciones por confianza a recompensa
externa = #correctas entre las sometidas / m (precisión de submission, normalizada por el oracle). Brazos:
  - naive:   likelihood + ancla (selector colapsa, 115 -> decide peor cada ronda).
  - durable: likelihood + ancla + unlikelihood-acotado (selector calibrado, 119 -> decide bien sostenidamente).
MÉTRICA: payoff de submission (reward/oracle) por ronda -- final y AUC. 4 seeds, 8 rondas.

PREGUNTA FALSABLE:
  - APOYADA si el payoff de submission durable > naive sostenidamente (final +>margen Y AUC > 0). => la señal calibrada
    (cura 119) PAGA en una DECISIÓN de asignación de recurso externo: confirma POSITIVAMENTE la re-localización de 121 (el
    valor de R-VALOR es decisional). Cierra el arco con el payoff realizado donde corresponde.
  - REFUTADA si el payoff durable ≈ naive (la calibración no paga ni en la decisión) -> la re-localización de 121 no se
    sostiene.
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp106_decisional_payoff.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp106_decisional_payoff.run            # FULL
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
ARMS = ["naive", "durable"]


def _submission_payoff(conf, strong, m):
    """Decisión: someter las top-m por confianza. payoff = #correctas sometidas / min(m, #correctas) (vs oracle)."""
    n = len(conf)
    mm = min(m, n)
    top = np.argsort(conf)[-mm:]
    reward = float(np.sum(strong[top]))
    oracle = float(min(mm, np.sum(strong)))
    return reward / oracle if oracle > 0 else 0.0


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp106] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"payoff": [], "corr": []} for a in ARMS}
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
            hist[a]["payoff"].append(round(_submission_payoff(conf, strong, args.submit_m), 4))  # DECISIÓN externa
            # self-training CON ancla (capacidad igual en ambos)
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * rng_a.random(len(pool)))[-min(k, len(pool)):]
            pos = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            neg = _dedup([pairs[i] for i in sel_idx if strong[i] < 0.5]) if a == "durable" else []
            _train(arms[a], pos, neg, args.steps, args.batch, args.lr,
                   args.neg_w if a == "durable" else 0.0, "cpu", train_rng)
        log(f"[exp106] seed={seed} ronda {r}: "
            + " | ".join(f"{a}: payoff={hist[a]['payoff'][-1]:.3f} corr={hist[a]['corr'][-1]:.3f}" for a in ARMS))

    return {"seed": seed, "base": bm, "hist": hist}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def build_summary(per_seed):
    def payoff_final(a):
        return _mean([s["hist"][a]["payoff"][-1] for s in per_seed])

    def payoff_auc(a):
        return _mean([_mean(s["hist"][a]["payoff"]) for s in per_seed])

    def corr_final(a):
        return _mean([s["hist"][a]["corr"][-1] for s in per_seed])

    pf_n, pf_d = payoff_final("naive"), payoff_final("durable")
    auc_n, auc_d = payoff_auc("naive"), payoff_auc("durable")
    cf_n, cf_d = corr_final("naive"), corr_final("durable")
    final_gap = round(pf_d - pf_n, 4)
    auc_gap = round(auc_d - auc_n, 4)
    corr_gap = round(cf_d - cf_n, 4)
    nseed = len(per_seed)

    MARGIN = 0.04
    pays = (final_gap > MARGIN) and (auc_gap > 0.0)
    no_pay = (final_gap <= MARGIN) and (auc_gap <= 0.0)

    if pays:
        status = "apoyada"
        verdict = ("H-V4-9b APOYADA: la señal calibrada (cura 119) PAGA en una DECISIÓN de asignación de recurso EXTERNO. "
                   "El payoff de submission (correctas sometidas / oracle) durable={pfd} vs naive={pfn} (final +{fg}); AUC "
                   "durable={aucd} vs naive={aucn} (+{ag}); corr final durable={cfd} vs naive={cfn} (+{cg}). => el selector "
                   "calibrado (que el unlikelihood mantiene honesto, 119) sostiene MEJORES decisiones de submission a lo "
                   "largo de las rondas, donde el naive (señal que colapsa) decide cada vez peor. CONFIRMA POSITIVAMENTE la "
                   "re-localización de 121: el valor de R-VALOR es DECISIONAL -- la cura de durabilidad paga en la DECISIÓN "
                   "(asignar el recurso externo escaso), no en el descenso del loss.").format(
                       pfd=_f(pf_d), pfn=_f(pf_n), fg=_f(final_gap), aucd=_f(auc_d), aucn=_f(auc_n), ag=_f(auc_gap),
                       cfd=_f(cf_d), cfn=_f(cf_n), cg=_f(corr_gap))
    elif no_pay:
        status = "refutada"
        verdict = ("H-V4-9b REFUTADA: la señal calibrada NO paga ni en la decisión (payoff submission durable={pfd} vs "
                   "naive={pfn}, +{fg}; AUC +{ag}) -> la re-localización de 121 no se sostiene en este régimen.").format(
                       pfd=_f(pf_d), pfn=_f(pf_n), fg=_f(final_gap), ag=_f(auc_gap))
    else:
        status = "mixta"
        verdict = ("H-V4-9b MIXTA: payoff de decisión mixto (final +{fg}, AUC +{ag}, corr +{cg}).").format(
                       fg=_f(final_gap), ag=_f(auc_gap), cg=_f(corr_gap))

    return {"arms": ARMS, "n_seeds": nseed, "payoff_final_naive": round(pf_n, 4), "payoff_final_durable": round(pf_d, 4),
            "payoff_auc_naive": round(auc_n, 4), "payoff_auc_durable": round(auc_d, 4),
            "corr_final_naive": round(cf_n, 4), "corr_final_durable": round(cf_d, 4),
            "final_gap": final_gap, "auc_gap": auc_gap, "corr_gap": corr_gap, "pays": bool(pays), "no_pay": bool(no_pay),
            "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--submit_m", type=int, default=8)
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

    log("[exp106] CYCLE 122 / H-V4-9b — la señal calibrada (119) PAGA en una DECISIÓN externa (submission budget)? (confirma 121)")
    log(f"[exp106] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} submit_m={args.submit_m} "
        f"budget_frac={args.budget_frac} temp={args.temp} replay_frac={args.replay_frac} neg_w={args.neg_w}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp106] payoff submission final: naive={sm['payoff_final_naive']:.3f} durable={sm['payoff_final_durable']:.3f} (gap +{sm['final_gap']:.3f})")
    log(f"[exp106] payoff submission AUC: naive={sm['payoff_auc_naive']:.3f} durable={sm['payoff_auc_durable']:.3f} (gap +{sm['auc_gap']:.3f})")
    log(f"[exp106] corr final: naive={sm['corr_final_naive']:.3f} durable={sm['corr_final_durable']:.3f} (+{sm['corr_gap']:.3f})")
    log(f"[exp106] pays={sm['pays']} no_pay={sm['no_pay']}")
    log(f"[exp106] VEREDICTO H-V4-9b: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp106_decisional_payoff", "cycle": 122, "hypothesis": "H-V4-9b",
           "claim": "la senal calibrada (cura 119) PAGA en una decision de asignacion de recurso externo (submission "
                    "budget): el selector durable sostiene mejores decisiones de submission a lo largo de las rondas que "
                    "el naive (senal que colapsa) -> confirma positivamente que el valor de R-VALOR es DECISIONAL (121)",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp106] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

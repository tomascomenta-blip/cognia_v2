r"""
exp100 — CYCLE 116 / H-V4-8u (rama R-VALOR, cierra el pointer de CYCLE 115: ¿hay una señal de valor INTRÍNSECA durable?):
115 mostró que la CONFIANZA de una sola generación COLAPSA como señal de valor en lazos sostenidos (corr -> ~0) y que el
ancla de verdad externa rescata el outcome pero NO la señal. Pregunta abierta: ¿existe una señal INTRÍNSECA (sin verdad
externa) que sea MÁS durable que la confianza single-shot? Candidata: la AUTO-CONSISTENCIA (cuánto coinciden K generaciones
del mismo prompt) -- una señal agregada, no la logprob de una sola muestra.

CONTEXTO. Si la auto-consistencia es más durable, hay una señal de valor intrínseca usable en lazos largos; si TAMBIÉN
colapsa, la verdad externa es inevitable (refuerza 115). Cualquiera de los dos es valioso.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp099). Lazo cerrado real. El pool genera K muestras por prompt. Cada ronda se
miden DOS señales por candidato y su corr con la corrección (strong):
  - confidence:  logprob media de ESA generación (single-shot, la de 115).
  - self_consist: fracción de las K generaciones del MISMO prompt que dan la MISMA respuesta que el candidato (acuerdo).
Se entrena (con guardia/replay, como 115-guard, para aislar la durabilidad de la SEÑAL del colapso del downstream) y se
sigue la TENDENCIA de corr de cada señal sobre las rondas.

PREGUNTA FALSABLE:
  - APOYADA si la auto-consistencia es MÁS durable que la confianza single-shot: tendencia(self_consist) − tendencia(conf)
    > margen (la corr de self_consist cae menos / se mantiene), Y su corr final es mayor. => existe una señal de valor
    INTRÍNSECA más durable que la confianza single-shot para lazos sostenidos.
  - REFUTADA si self_consist NO es más durable (cae igual o peor) -> la verdad externa es inevitable (refuerza 115).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp100_durable_signal.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp100_durable_signal.run            # FULL
"""
import argparse
import copy
import json
import os
import platform
import sys
from collections import Counter, defaultdict

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
SIGNALS = ["confidence", "self_consist"]


def _self_consistency(prompts, exprs):
    """Por candidato: fracción de las generaciones del MISMO prompt cuya respuesta coincide con la del candidato."""
    groups = defaultdict(list)
    for i, p in enumerate(prompts):
        groups[bytes(p)].append(i)
    counts = {}
    for p, idxs in groups.items():
        c = Counter(bytes(exprs[i]) for i in idxs)
        counts[p] = (c, len(idxs))
    out = np.zeros(len(prompts))
    for i, p in enumerate(prompts):
        c, tot = counts[bytes(p)]
        out[i] = c[bytes(exprs[i])] / tot if tot > 0 else 0.0
    return out


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp100] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    model = copy.deepcopy(base)
    hist = {"corr_conf": [], "corr_sc": [], "real": [round(bm["real_acc"], 4)]}
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        torch.manual_seed(10000 * seed + r)
        pool = generate_pool(model, pool_prompts, args.K, args.temp, args.top_k, "cpu")
        prompts = [p for (p, _, _, _) in pool]
        exprs = [e for (_, e, _, _) in pool]
        pairs = [(p, e) for (p, e, _, _) in pool]
        strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
        conf = _confidence(model, pairs, "cpu")
        sc = _self_consistency(prompts, exprs)
        hist["corr_conf"].append(round(_corr(conf, strong), 4))
        hist["corr_sc"].append(round(_corr(sc, strong), 4))
        # selección por confianza + GUARDIA (aislar la durabilidad de la SEÑAL del colapso del downstream)
        rng_a = np.random.default_rng(seed * 131 + r * 17)
        sel_idx = np.argsort(conf + 1e-9 * rng_a.random(len(pool)))[-min(k, len(pool)):]
        ex = [pairs[i] for i in sel_idx if strong[i] > 0.5]
        ex = _dedup(ex) + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(_dedup(ex))))))
        if ex:
            train_arm(model, ex, args.steps, args.batch, args.lr, "cpu", train_rng)
        mm = E.eval_metrics(model, test_targets, "cpu")
        hist["real"].append(round(mm["real_acc"], 4))
        log(f"[exp100] seed={seed} ronda {r}: corr_conf={hist['corr_conf'][-1]:.3f} corr_sc={hist['corr_sc'][-1]:.3f} real={hist['real'][-1]:.3f}")

    return {"seed": seed, "base": bm, "hist": hist}


def _mean(xs):
    return float(np.mean(xs)) if len(xs) else 0.0


def _f(x):
    return "{:.3f}".format(x)


def _trend(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    h = n // 2
    return float(np.mean(xs[h:]) - np.mean(xs[:h]))


def build_summary(per_seed):
    t_conf = round(_mean([_trend(s["hist"]["corr_conf"]) for s in per_seed]), 4)
    t_sc = round(_mean([_trend(s["hist"]["corr_sc"]) for s in per_seed]), 4)
    conf_first = _mean([s["hist"]["corr_conf"][0] for s in per_seed])
    conf_last = _mean([s["hist"]["corr_conf"][-1] for s in per_seed])
    sc_first = _mean([s["hist"]["corr_sc"][0] for s in per_seed])
    sc_last = _mean([s["hist"]["corr_sc"][-1] for s in per_seed])
    durability = round(t_sc - t_conf, 4)              # >0 si self_consist cae menos
    final_gap = round(sc_last - conf_last, 4)         # >0 si self_consist termina mejor
    nseed = len(per_seed)

    DUR = 0.05
    FIN = 0.03
    more_durable = (durability > DUR) and (final_gap > FIN)
    not_durable = (durability <= 0) and (final_gap <= 0)

    if more_durable:
        status = "apoyada"
        verdict = ("H-V4-8u APOYADA: la AUTO-CONSISTENCIA es una señal de valor INTRÍNSECA MÁS DURABLE que la confianza "
                   "single-shot. corr con la corrección: confidence {cf}->{cl} (tendencia {tc}) vs self_consist {sf}->{sl} "
                   "(tendencia {ts}); durabilidad (Δtendencia) +{d}, brecha final +{fg}. => en lazos sostenidos, donde la "
                   "confianza single-shot colapsa (115), el ACUERDO entre K generaciones se mantiene como señal de valor "
                   "intrínseca (sin verdad externa). Hay una señal durable mejor que la logprob de una "
                   "muestra.").format(cf=_f(conf_first), cl=_f(conf_last), tc=_f(t_conf), sf=_f(sc_first), sl=_f(sc_last),
                                      ts=_f(t_sc), d=_f(durability), fg=_f(final_gap))
    elif not_durable:
        status = "refutada"
        verdict = ("H-V4-8u REFUTADA: la auto-consistencia NO es más durable (durabilidad Δtendencia {d}, brecha final "
                   "{fg}): confidence {cl} vs self_consist {sl} al final. => la verdad EXTERNA es inevitable para sostener "
                   "la señal en lazos largos (refuerza 115).").format(d=_f(durability), fg=_f(final_gap), cl=_f(conf_last), sl=_f(sc_last))
    else:
        status = "mixta"
        verdict = ("H-V4-8u MIXTA: señales mixtas de durabilidad (Δtendencia {d}, brecha final {fg}; confidence {cl} vs "
                   "self_consist {sl}).").format(d=_f(durability), fg=_f(final_gap), cl=_f(conf_last), sl=_f(sc_last))

    return {"signals": SIGNALS, "n_seeds": nseed, "trend_conf": t_conf, "trend_sc": t_sc,
            "corr_conf_first": round(conf_first, 4), "corr_conf_last": round(conf_last, 4),
            "corr_sc_first": round(sc_first, 4), "corr_sc_last": round(sc_last, 4),
            "durability": durability, "final_gap": final_gap, "more_durable": bool(more_durable),
            "not_durable": bool(not_durable), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2,3")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--pool", type=int, default=64)
    ap.add_argument("--budget_frac", type=float, default=0.15)
    ap.add_argument("--temp", type=float, default=1.3)
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
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 4, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp100] CYCLE 116 / H-V4-8u — ¿auto-consistencia más durable que confianza single-shot? (cierra 115)")
    log(f"[exp100] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} temp={args.temp} "
        f"replay_frac={args.replay_frac} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp100] corr(confidence,strong): {sm['corr_conf_first']:.3f}->{sm['corr_conf_last']:.3f} (tendencia {sm['trend_conf']:+.3f})")
    log(f"[exp100] corr(self_consist,strong): {sm['corr_sc_first']:.3f}->{sm['corr_sc_last']:.3f} (tendencia {sm['trend_sc']:+.3f})")
    log(f"[exp100] durabilidad (Δtendencia sc−conf)=+{sm['durability']:.3f} | brecha final (sc−conf)=+{sm['final_gap']:.3f}")
    log(f"[exp100] more_durable={sm['more_durable']} not_durable={sm['not_durable']}")
    log(f"[exp100] VEREDICTO H-V4-8u: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp100_durable_signal", "cycle": 116, "hypothesis": "H-V4-8u",
           "claim": "la auto-consistencia (acuerdo entre K generaciones) es una senal de valor intrinseca mas durable que "
                    "la confianza single-shot en lazos sostenidos (donde la confianza colapsa, 115); si no lo es, la "
                    "verdad externa es inevitable",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp100] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

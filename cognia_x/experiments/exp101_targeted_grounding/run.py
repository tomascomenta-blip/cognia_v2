r"""
exp101 — CYCLE 117 / H-V4-8w (rama R-VALOR, cierre constructivo de la fragilidad 115-116): 115 mostró que la confianza
COLAPSA bajo auto-entrenamiento y que el replay de verdad canónica ALEATORIO (guardia 94) rescata el outcome pero NO la
SEÑAL. 116: la auto-consistencia es mejor nivel pero tampoco durable. La fragilidad viene de la SOBRECONFIANZA: el modelo
se vuelve confiado-pero-equivocado en ciertos prompts. ¿Y si el grounding se DIRIGE a los FALLOS -- replay de verdad
canónica para los prompts que el modelo ERRÓ (donde la confianza engaña) -- en vez de aleatorio? ¿Preserva mejor la
calibración (corr confianza-corrección)?

CONTEXTO. Test de un corrector ESTABLE (sigue siendo imitación de verdad canónica, no cambia el objetivo): re-anclar donde
el modelo está sobreconfiado-equivocado. Cierra el sub-arco de fragilidad con una receta práctica.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp078/exp099). Lazo cerrado real, selección por confianza. Cada ronda se mide
corr(confianza, strong) sobre el pool. Brazos (mismo presupuesto de replay):
  - guard_random:   replay de verdad canónica para targets AL AZAR (la guardia de 115).
  - guard_targeted: replay de verdad canónica para los targets que el modelo ERRÓ esta ronda (fallos -> donde la confianza
                    engaña).
MÉTRICA: tendencia de corr(confianza,strong) sobre las rondas + real_acc final. 4 seeds, 6 rondas.

PREGUNTA FALSABLE:
  - APOYADA si guard_targeted preserva la corr MEJOR que guard_random (tendencia_targeted − tendencia_random > margen) Y/O
    su corr final es mayor, sin perder downstream. => DIRIGIR el grounding a los fallos (donde el modelo está
    sobreconfiado-equivocado) re-calibra la señal mejor que el replay aleatorio: una receta práctica para la durabilidad.
  - REFUTADA si guard_targeted NO mejora la corr sobre guard_random (dirigir no ayuda; el colapso es inevitable con replay
    positivo).
  - MIXTA en otro caso (p.ej. mejora downstream pero no la señal).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp101_targeted_grounding.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp101_targeted_grounding.run            # FULL
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
from cognia_x.experiments.exp078_closed_loop_guard.run import _dedup

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["guard_random", "guard_targeted"]


def _replay_canonical(rng, targets, count):
    if count <= 0 or len(targets) == 0:
        return []
    sel = rng.integers(0, len(targets), size=count)
    return [(E.make_prompt(targets[i]), E.real_expression(rng, targets[i])) for i in sel]


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp101] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_targets = [int(train_targets[i]) for i in sel]
    pool_prompts = [E.make_prompt(t) for t in pool_targets]
    prompt2target = {bytes(E.make_prompt(t)): t for t in pool_targets}
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "corr": []} for a in ARMS}
    train_rng = np.random.default_rng(seed + 99)

    for r in range(1, args.rounds + 1):
        for a in ARMS:
            torch.manual_seed(10000 * seed + r)
            pool = generate_pool(arms[a], pool_prompts, args.K, args.temp, args.top_k, "cpu")
            pairs = [(p, e) for (p, e, _, _) in pool]
            prompts = [p for (p, _, _, _) in pool]
            strong = np.array([1.0 if s else 0.0 for (_, _, _, s) in pool])
            conf = _confidence(arms[a], pairs, "cpu")
            hist[a]["corr"].append(round(_corr(conf, strong), 4))
            rng_a = np.random.default_rng(seed * 131 + r * 17 + ARMS.index(a))
            sel_idx = np.argsort(conf + 1e-9 * rng_a.random(len(pool)))[-min(k, len(pool)):]
            ex = _dedup([pairs[i] for i in sel_idx if strong[i] > 0.5])
            n_replay = int(round(args.replay_frac * max(1, len(ex))))
            if a == "guard_random":
                replay = _replay_canonical(train_rng, train_targets, n_replay)
            else:  # guard_targeted: verdad canónica de los targets ERRADOS esta ronda
                failed_targets = sorted({prompt2target[bytes(prompts[i])] for i in range(len(pool)) if strong[i] < 0.5})
                replay = _replay_canonical(train_rng, failed_targets if failed_targets else train_targets, n_replay)
            ex = ex + replay
            if ex:
                train_arm(arms[a], ex, args.steps, args.batch, args.lr, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp101] seed={seed} ronda {r}: "
            + " | ".join(f"{a}: corr={hist[a]['corr'][-1]:.3f} real={hist[a]['real'][-1]:.3f}" for a in ARMS))

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
    t_rand = round(_mean([_trend(s["hist"]["guard_random"]["corr"]) for s in per_seed]), 4)
    t_targ = round(_mean([_trend(s["hist"]["guard_targeted"]["corr"]) for s in per_seed]), 4)
    corr_last_rand = _mean([s["hist"]["guard_random"]["corr"][-1] for s in per_seed])
    corr_last_targ = _mean([s["hist"]["guard_targeted"]["corr"][-1] for s in per_seed])
    real_last_rand = _mean([s["hist"]["guard_random"]["real"][-1] for s in per_seed])
    real_last_targ = _mean([s["hist"]["guard_targeted"]["real"][-1] for s in per_seed])
    trend_gain = round(t_targ - t_rand, 4)
    corr_gain = round(corr_last_targ - corr_last_rand, 4)
    real_gain = round(real_last_targ - real_last_rand, 4)
    nseed = len(per_seed)

    SIG_MARGIN = 0.04
    signal_better = (trend_gain > SIG_MARGIN) or (corr_gain > SIG_MARGIN)
    real_not_worse = real_gain >= -0.03

    if signal_better and real_not_worse:
        status = "apoyada"
        verdict = ("H-V4-8w APOYADA: DIRIGIR el grounding a los FALLOS re-calibra la señal mejor que el replay aleatorio. "
                   "corr(confianza,corrección) -- guard_targeted termina en {clt} (tendencia {tt}) vs guard_random {clr} "
                   "(tendencia {tr}); ganancia de señal: tendencia +{tg}, corr final +{cg}. Sin perder downstream "
                   "(real_acc targeted={rlt} vs random={rlr}, Δ{rg}). => re-anclar la verdad canónica DONDE el modelo está "
                   "sobreconfiado-equivocado (sus fallos) preserva la calibración mejor que re-anclar al azar -- receta "
                   "práctica para mitigar la fragilidad de 115-116.").format(
                       clt=_f(corr_last_targ), tt=_f(t_targ), clr=_f(corr_last_rand), tr=_f(t_rand), tg=_f(trend_gain),
                       cg=_f(corr_gain), rlt=_f(real_last_targ), rlr=_f(real_last_rand), rg=_f(real_gain))
    elif not signal_better:
        status = "refutada"
        verdict = ("H-V4-8w REFUTADA: dirigir el grounding a los fallos NO mejora la señal sobre el replay aleatorio "
                   "(tendencia +{tg}, corr final +{cg}, ambos <= {m}) -> el colapso de la señal es inevitable con replay "
                   "positivo (refuerza 115-116: hace falta otra cosa, p.ej. negativos).").format(
                       tg=_f(trend_gain), cg=_f(corr_gain), m=SIG_MARGIN)
    else:
        status = "mixta"
        verdict = ("H-V4-8w MIXTA: el grounding dirigido mejora la señal (tendencia +{tg}, corr final +{cg}) pero el "
                   "downstream regresiona (Δreal {rg}).").format(tg=_f(trend_gain), cg=_f(corr_gain), rg=_f(real_gain))

    return {"arms": ARMS, "n_seeds": nseed, "trend_random": t_rand, "trend_targeted": t_targ,
            "corr_last_random": round(corr_last_rand, 4), "corr_last_targeted": round(corr_last_targ, 4),
            "real_last_random": round(real_last_rand, 4), "real_last_targeted": round(real_last_targ, 4),
            "trend_gain": trend_gain, "corr_gain": corr_gain, "real_gain": real_gain,
            "signal_better": bool(signal_better), "real_not_worse": bool(real_not_worse), "status": status, "verdict": verdict}


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

    log("[exp101] CYCLE 117 / H-V4-8w — grounding DIRIGIDO a los fallos vs aleatorio (cierre constructivo de 115-116)")
    log(f"[exp101] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} temp={args.temp} "
        f"replay_frac={args.replay_frac} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp101] corr final: random={sm['corr_last_random']:.3f} (tend {sm['trend_random']:+.3f}) targeted={sm['corr_last_targeted']:.3f} (tend {sm['trend_targeted']:+.3f})")
    log(f"[exp101] ganancia señal: tendencia=+{sm['trend_gain']:.3f} corr_final=+{sm['corr_gain']:.3f} | real Δ={sm['real_gain']:+.3f}")
    log(f"[exp101] signal_better={sm['signal_better']} real_not_worse={sm['real_not_worse']}")
    log(f"[exp101] VEREDICTO H-V4-8w: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp101_targeted_grounding", "cycle": 117, "hypothesis": "H-V4-8w",
           "claim": "dirigir el grounding (replay de verdad canonica) a los FALLOS del modelo -- donde esta "
                    "sobreconfiado-equivocado -- re-calibra la senal (corr confianza-correccion) mejor que el replay "
                    "aleatorio (guardia 115), sin perder downstream: receta practica para mitigar la fragilidad de 115-116",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp101] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

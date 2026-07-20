r"""
exp102 — CYCLE 118 / H-V4-8x (rama R-VALOR, ataca la FRONTERA de 115-117: ¿el CONTRASTIVO cura el colapso de la señal?):
115-117 hallaron que la señal de valor (confianza) COLAPSA bajo auto-entrenamiento y que ningún corrector de imitación de
POSITIVOS (replay random/dirigido) lo cura -- imitar lo correcto enseña a SUBIR la prob de lo bueno pero NO a BAJAR la
confianza en lo incorrecto. La hipótesis viva: una señal NEGATIVA/CONTRASTIVA (penalizar lo verificado-INCORRECTO, no sólo
imitar lo correcto) PRESERVA la calibración. Este ciclo lo testea directamente.

CONTEXTO. Es la pregunta más importante que abrió el arco de fragilidad. Requiere cambiar el objetivo de entrenamiento
(añadir un término de unlikelihood sobre negativos) -- se hace con peso CHICO + grad-clip, y se reporta HONESTAMENTE lo que
pase (incluida inestabilidad).

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp078). Lazo cerrado real, selección por confianza, replay canónico (guardia) en
ambos brazos. Cada ronda se mide corr(confianza, strong). Brazos:
  - pos_only:    train sólo sobre verificado-CORRECTO + replay canónico (como 115-guard; colapsa).
  - contrastive: lo mismo + término NEGATIVO sobre verificado-INCORRECTO (ascenso de gradiente sobre su CE, peso CHICO,
                 grad-clip): empuja al modelo a BAJAR la prob de las respuestas equivocadas que generó.
MÉTRICA: tendencia de corr(confianza,strong) sobre las rondas + real_acc. Guarda de estabilidad: si real_acc o corr -> nan
o colapsa a ~0 en ambos, se reporta inestabilidad. 4 seeds, 6 rondas.

PREGUNTA FALSABLE:
  - APOYADA si contrastive PRESERVA la calibración mejor que pos_only (tendencia_contrastive − tendencia_pos > margen y/o
    corr final mayor) SIN desestabilizar (real_acc no peor que pos_only). => la señal NEGATIVA/contrastiva CURA (o mitiga
    fuerte) el colapso que la imitación-positiva no puede; identifica el mecanismo de durabilidad.
  - REFUTADA si contrastive NO preserva mejor la señal (o desestabiliza el entrenamiento) -> el contrastivo simple tampoco
    cura; la durabilidad necesita otra cosa (recalibración externa).
  - MIXTA en otro caso.

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp102_contrastive_grounding.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp102_contrastive_grounding.run            # FULL
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

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
ARMS = ["pos_only", "contrastive"]


def _train_contrastive(model, pos, neg, steps, batch, lr, neg_w, device, rng):
    """Positivos: likelihood normal. Negativos: ascenso de gradiente sobre su CE (peso chico) -> baja su prob. grad-clip."""
    if not pos:
        return
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    for _ in range(steps):
        idx = rng.integers(0, len(pos), size=batch)
        x, y = E.batch_from_examples([pos[i] for i in idx], device)
        _, loss_pos = model(x, y)
        loss = loss_pos
        if neg and neg_w > 0:
            jdx = rng.integers(0, len(neg), size=min(batch, len(neg)))
            xn, yn = E.batch_from_examples([neg[j] for j in jdx], device)
            _, loss_neg = model(xn, yn)
            loss = loss_pos - neg_w * loss_neg          # ascenso sobre el CE de los negativos
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp102] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
    pool_rng = np.random.default_rng(seed + 7)
    sel = pool_rng.integers(0, len(train_targets), size=args.pool)
    pool_prompts = [E.make_prompt(train_targets[i]) for i in sel]
    k = max(1, int(args.budget_frac * args.pool * args.K))

    arms = {a: copy.deepcopy(base) for a in ARMS}
    hist = {a: {"real": [round(bm["real_acc"], 4)], "corr": []} for a in ARMS}
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
            pos = pos + _replay_examples(train_rng, train_targets, int(round(args.replay_frac * max(1, len(pos)))))
            neg = _dedup([pairs[i] for i in range(len(pool)) if strong[i] < 0.5]) if a == "contrastive" else []
            _train_contrastive(arms[a], pos, neg, args.steps, args.batch, args.lr,
                               args.neg_w if a == "contrastive" else 0.0, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp102] seed={seed} ronda {r}: "
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
    t_pos = round(_mean([_trend(s["hist"]["pos_only"]["corr"]) for s in per_seed]), 4)
    t_con = round(_mean([_trend(s["hist"]["contrastive"]["corr"]) for s in per_seed]), 4)
    corr_last_pos = _mean([s["hist"]["pos_only"]["corr"][-1] for s in per_seed])
    corr_last_con = _mean([s["hist"]["contrastive"]["corr"][-1] for s in per_seed])
    real_last_pos = _mean([s["hist"]["pos_only"]["real"][-1] for s in per_seed])
    real_last_con = _mean([s["hist"]["contrastive"]["real"][-1] for s in per_seed])
    trend_gain = round(t_con - t_pos, 4)
    corr_gain = round(corr_last_con - corr_last_pos, 4)
    real_gain = round(real_last_con - real_last_pos, 4)
    nseed = len(per_seed)
    # guarda de estabilidad: contrastive desestabiliza si su real_acc cae MUY por debajo de pos_only
    destabilized = real_gain < -0.10

    SIG = 0.04
    signal_better = (trend_gain > SIG) or (corr_gain > SIG)
    real_ok = real_gain >= -0.05

    if destabilized:
        status = "refutada"
        verdict = ("H-V4-8x REFUTADA (inestable): el término contrastivo DESESTABILIZA el entrenamiento -- real_acc "
                   "contrastive={rc} << pos_only={rp} (Δ{rg}). El contrastivo simple (ascenso de gradiente sobre negativos) "
                   "no es viable en el tiny model; la durabilidad necesita otra cosa (recalibración externa).").format(
                       rc=_f(real_last_con), rp=_f(real_last_pos), rg=_f(real_gain))
    elif signal_better and real_ok:
        status = "apoyada"
        verdict = ("H-V4-8x APOYADA: la señal NEGATIVA/CONTRASTIVA preserva la calibración mejor que la imitación-positiva. "
                   "corr(confianza,corrección) -- contrastive {clc} (tendencia {tcon}) vs pos_only {clp} (tendencia {tpos}); "
                   "ganancia señal tendencia +{tg}, corr final +{cg}; downstream real_acc contrastive={rc} vs pos={rp} "
                   "(Δ{rg}). => penalizar lo verificado-INCORRECTO (no sólo imitar lo correcto) CURA/mitiga fuerte el "
                   "colapso de la señal que 115-117 dejaron abierto: identifica el mecanismo de durabilidad "
                   "(contrastivo).").format(clc=_f(corr_last_con), tcon=_f(t_con), clp=_f(corr_last_pos), tpos=_f(t_pos),
                                            tg=_f(trend_gain), cg=_f(corr_gain), rc=_f(real_last_con), rp=_f(real_last_pos), rg=_f(real_gain))
    elif not signal_better:
        status = "refutada"
        verdict = ("H-V4-8x REFUTADA: el contrastivo NO preserva mejor la señal (tendencia +{tg}, corr final +{cg}, ambos "
                   "<= {m}; corr contrastive {clc} vs pos {clp}) -> el contrastivo simple tampoco cura; la durabilidad "
                   "necesita recalibración externa.").format(tg=_f(trend_gain), cg=_f(corr_gain), m=SIG,
                                                             clc=_f(corr_last_con), clp=_f(corr_last_pos))
    else:
        status = "mixta"
        verdict = ("H-V4-8x MIXTA: el contrastivo mejora la señal (tendencia +{tg}, corr +{cg}) pero con costo de "
                   "downstream (Δreal {rg}).").format(tg=_f(trend_gain), cg=_f(corr_gain), rg=_f(real_gain))

    return {"arms": ARMS, "n_seeds": nseed, "trend_pos": t_pos, "trend_contrastive": t_con,
            "corr_last_pos": round(corr_last_pos, 4), "corr_last_contrastive": round(corr_last_con, 4),
            "real_last_pos": round(real_last_pos, 4), "real_last_contrastive": round(real_last_con, 4),
            "trend_gain": trend_gain, "corr_gain": corr_gain, "real_gain": real_gain, "destabilized": bool(destabilized),
            "signal_better": bool(signal_better), "real_ok": bool(real_ok), "status": status, "verdict": verdict}


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
    ap.add_argument("--neg_w", type=float, default=0.2)
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

    log("[exp102] CYCLE 118 / H-V4-8x — ¿el CONTRASTIVO (positivos + negativos verificados) cura el colapso de la señal? (frontera 115-117)")
    log(f"[exp102] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} temp={args.temp} "
        f"replay_frac={args.replay_frac} neg_w={args.neg_w} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp102] corr final: pos_only={sm['corr_last_pos']:.3f} (tend {sm['trend_pos']:+.3f}) contrastive={sm['corr_last_contrastive']:.3f} (tend {sm['trend_contrastive']:+.3f})")
    log(f"[exp102] ganancia señal: tendencia=+{sm['trend_gain']:.3f} corr_final=+{sm['corr_gain']:.3f} | real Δ={sm['real_gain']:+.3f} (destabilized={sm['destabilized']})")
    log(f"[exp102] signal_better={sm['signal_better']} real_ok={sm['real_ok']}")
    log(f"[exp102] VEREDICTO H-V4-8x: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp102_contrastive_grounding", "cycle": 118, "hypothesis": "H-V4-8x",
           "claim": "una senal NEGATIVA/CONTRASTIVA (penalizar lo verificado-incorrecto, no solo imitar lo correcto) "
                    "preserva la calibracion de la senal de valor que la imitacion-positiva no cura (115-117): ataca la "
                    "frontera de la durabilidad",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp102] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

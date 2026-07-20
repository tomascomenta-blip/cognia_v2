r"""
exp103 — CYCLE 119 / H-V4-8y (rama R-VALOR, RESUELVE la frontera concreta de 118): 118 mostró que los NEGATIVOS curan la
calibración de la señal (corr_gain +0.398, dirección EXACTAMENTE correcta) PERO el contrastivo NAIVE (ascenso de gradiente
sobre el CE de negativos) DESTRUYE la capacidad (real_acc->0). La frontera concreta: un unlikelihood ACOTADO -- penalizar
-log(1-p(token_incorrecto)) (una pérdida acotada a MINIMIZAR, no un ascenso de CE) -- que capture el beneficio de
calibración SIN colapsar la capacidad. Este ciclo lo testea.

CONTEXTO. Es la resolución constructiva del arco de fragilidad (115-118): ¿hay una forma ESTABLE de usar los negativos que
preserve la durabilidad de la señal sin sacrificar la capacidad? El método importa (118 lo probó), no sólo la dirección.

DISEÑO (PyTorch CPU; reusa exp018/exp077/exp078). Lazo cerrado real, selección por confianza, replay canónico (guardia) en
ambos. Cada ronda se mide corr(confianza, strong). Brazos:
  - pos_only:  train sólo sobre verificado-CORRECTO + replay canónico (como 115-guard; colapsa).
  - unlik:     lo mismo + término de UNLIKELIHOOD ACOTADO sobre verificado-INCORRECTO: minimizar -log(1-p) de los tokens de
               las respuestas equivocadas en sus posiciones supervisadas (baja su prob SIN ascenso de CE).
MÉTRICA: tendencia de corr(confianza,strong) + real_acc final. Guarda de estabilidad (real_acc no debe colapsar como en
118). 4 seeds, 6 rondas.

PREGUNTA FALSABLE:
  - APOYADA si unlik PRESERVA la calibración mejor que pos_only (tendencia/corr final +>margen) Y mantiene la capacidad
    (real_acc NO colapsa: real_gain >= -0.05). => el unlikelihood ACOTADO es la forma ESTABLE de usar negativos que CURA
    la durabilidad de la señal sin sacrificar capacidad -- resuelve la frontera de 115-118.
  - REFUTADA si unlik NO preserva mejor la señal, o si TAMBIÉN colapsa la capacidad (como el naive de 118) -> el
    unlikelihood acotado tampoco resuelve en el tiny model.
  - MIXTA en otro caso (mejora la señal pero con algún costo de capacidad).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp103_bounded_unlikelihood.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp103_bounded_unlikelihood.run            # FULL
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
import torch.nn.functional as F

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
ARMS = ["pos_only", "unlik"]


def _bounded_unlikelihood(model, neg, batch, device, rng):
    """-log(1 - p(token)) en las posiciones supervisadas de los negativos. Pérdida ACOTADA a minimizar (baja su prob)."""
    jdx = rng.integers(0, len(neg), size=min(batch, len(neg)))
    xn, yn = E.batch_from_examples([neg[j] for j in jdx], device)
    logits, _ = model(xn)                                   # targets=None -> (logits, None)
    p = F.softmax(logits, dim=-1)
    mask = (yn != -100)
    yn_c = yn.clamp(min=0)
    p_tgt = p.gather(-1, yn_c.unsqueeze(-1)).squeeze(-1)    # [B,L] prob asignada al token (incorrecto)
    unlik = -torch.log((1.0 - p_tgt).clamp(min=1e-4))
    denom = mask.sum().clamp(min=1)
    return (unlik * mask).sum() / denom


def _train(model, pos, neg, steps, batch, lr, neg_w, device, rng):
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
            loss = loss_pos + neg_w * _bounded_unlikelihood(model, neg, batch, device, rng)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()


def run_seed(seed, args, test_targets, train_targets, log):
    base, npar = build_base(seed, args.n_seed, args.base_steps, args.base_lr, args.warmup, args.batch, train_targets)
    bm = E.eval_metrics(base, test_targets, "cpu")
    log(f"[exp103] seed={seed} base real_acc={bm['real_acc']:.3f} params={npar:,}")
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
            neg = _dedup([pairs[i] for i in range(len(pool)) if strong[i] < 0.5]) if a == "unlik" else []
            _train(arms[a], pos, neg, args.steps, args.batch, args.lr,
                   args.neg_w if a == "unlik" else 0.0, "cpu", train_rng)
            mm = E.eval_metrics(arms[a], test_targets, "cpu")
            hist[a]["real"].append(round(mm["real_acc"], 4))
        log(f"[exp103] seed={seed} ronda {r}: "
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
    t_unl = round(_mean([_trend(s["hist"]["unlik"]["corr"]) for s in per_seed]), 4)
    corr_last_pos = _mean([s["hist"]["pos_only"]["corr"][-1] for s in per_seed])
    corr_last_unl = _mean([s["hist"]["unlik"]["corr"][-1] for s in per_seed])
    real_last_pos = _mean([s["hist"]["pos_only"]["real"][-1] for s in per_seed])
    real_last_unl = _mean([s["hist"]["unlik"]["real"][-1] for s in per_seed])
    trend_gain = round(t_unl - t_pos, 4)
    corr_gain = round(corr_last_unl - corr_last_pos, 4)
    real_gain = round(real_last_unl - real_last_pos, 4)
    nseed = len(per_seed)
    destabilized = real_gain < -0.10           # como 118 (capacidad colapsada)

    SIG = 0.04
    signal_better = (trend_gain > SIG) or (corr_gain > SIG)
    capacity_ok = real_gain >= -0.05

    if destabilized:
        status = "refutada"
        verdict = ("H-V4-8y REFUTADA: el unlikelihood acotado TAMBIÉN colapsa la capacidad (real_acc unlik={ru} << "
                   "pos_only={rp}, Δ{rg}) -> tampoco resuelve en el tiny model; la durabilidad necesita recalibración "
                   "externa.").format(ru=_f(real_last_unl), rp=_f(real_last_pos), rg=_f(real_gain))
    elif signal_better and capacity_ok:
        status = "apoyada"
        verdict = ("H-V4-8y APOYADA: el unlikelihood ACOTADO es la forma ESTABLE de usar negativos que CURA la durabilidad "
                   "de la señal SIN sacrificar la capacidad -- resuelve la frontera de 115-118. corr(confianza,corrección) "
                   "unlik={clu} (tendencia {tu}) vs pos_only={clp} (tendencia {tp}): ganancia señal tendencia +{tg}, corr "
                   "final +{cg}; capacidad PRESERVADA (real_acc unlik={ru} vs pos={rp}, Δ{rg} -- NO colapsa como el naive "
                   "de 118). => penalizar lo verificado-incorrecto con una pérdida ACOTADA (no ascenso de CE) mantiene la "
                   "confianza calibrada en lazos sostenidos sin degenerar: la pieza que faltaba para la durabilidad "
                   "endógena de R-VALOR.").format(clu=_f(corr_last_unl), tu=_f(t_unl), clp=_f(corr_last_pos), tp=_f(t_pos),
                                                  tg=_f(trend_gain), cg=_f(corr_gain), ru=_f(real_last_unl), rp=_f(real_last_pos), rg=_f(real_gain))
    elif not signal_better:
        status = "refutada"
        verdict = ("H-V4-8y REFUTADA: el unlikelihood acotado NO preserva mejor la señal (tendencia +{tg}, corr +{cg} <= "
                   "{m}; corr unlik={clu} vs pos {clp}) -> no cura la durabilidad pese a no colapsar la capacidad.").format(
                       tg=_f(trend_gain), cg=_f(corr_gain), m=SIG, clu=_f(corr_last_unl), clp=_f(corr_last_pos))
    else:
        status = "mixta"
        verdict = ("H-V4-8y MIXTA: el unlikelihood acotado mejora la señal (tendencia +{tg}, corr +{cg}) con algún costo de "
                   "capacidad (Δreal {rg}, no colapso pero por debajo de pos_only).").format(
                       tg=_f(trend_gain), cg=_f(corr_gain), rg=_f(real_gain))

    return {"arms": ARMS, "n_seeds": nseed, "trend_pos": t_pos, "trend_unlik": t_unl,
            "corr_last_pos": round(corr_last_pos, 4), "corr_last_unlik": round(corr_last_unl, 4),
            "real_last_pos": round(real_last_pos, 4), "real_last_unlik": round(real_last_unl, 4),
            "trend_gain": trend_gain, "corr_gain": corr_gain, "real_gain": real_gain, "destabilized": bool(destabilized),
            "signal_better": bool(signal_better), "capacity_ok": bool(capacity_ok), "status": status, "verdict": verdict}


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
        args.seeds, args.rounds, args.pool, args.steps, args.base_steps = "0,1", 4, 48, 60, 200

    seeds = [int(s) for s in args.seeds.split(",")]
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    logs = []

    def log(mm):
        print(mm, flush=True); logs.append(mm)

    log("[exp103] CYCLE 119 / H-V4-8y — unlikelihood ACOTADO sobre negativos: ¿cura la señal SIN colapsar la capacidad? (resuelve 118)")
    log(f"[exp103] seeds={seeds} rango=[{LO},{HI}] rounds={args.rounds} K={args.K} pool={args.pool} temp={args.temp} "
        f"replay_frac={args.replay_frac} neg_w={args.neg_w} base_steps={args.base_steps}")

    per_seed = [run_seed(s, args, test_targets, train_targets, log) for s in seeds]
    sm = build_summary(per_seed)

    log(f"[exp103] corr final: pos_only={sm['corr_last_pos']:.3f} (tend {sm['trend_pos']:+.3f}) unlik={sm['corr_last_unlik']:.3f} (tend {sm['trend_unlik']:+.3f})")
    log(f"[exp103] ganancia señal: tendencia=+{sm['trend_gain']:.3f} corr_final=+{sm['corr_gain']:.3f} | real Δ={sm['real_gain']:+.3f} (destabilized={sm['destabilized']})")
    log(f"[exp103] real_acc final: pos_only={sm['real_last_pos']:.3f} unlik={sm['real_last_unlik']:.3f}")
    log(f"[exp103] signal_better={sm['signal_better']} capacity_ok={sm['capacity_ok']}")
    log(f"[exp103] VEREDICTO H-V4-8y: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp103_bounded_unlikelihood", "cycle": 119, "hypothesis": "H-V4-8y",
           "claim": "un unlikelihood ACOTADO (-log(1-p) sobre los tokens verificado-incorrectos, perdida a minimizar) cura "
                    "la durabilidad de la senal de valor (preserva corr confianza-correccion) SIN colapsar la capacidad "
                    "(a diferencia del contrastivo naive de 118) -> resuelve la frontera de 115-118",
           "verdict": sm["status"], "summary": sm, "args": vars(args),
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp103] escrito {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()

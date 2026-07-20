r"""
exp048 — CYCLE 63 / H-V4-4 (raíz fresca): el TECHO de recall es de OPTIMIZACIÓN, no de capacidad — un CURRÍCULO
(fácil→difícil) MUEVE el plateau, a IGUAL capacidad y cómputo.

CONTEXTO: el thesis v4 degradó el "techo de recall = d²" a SÍNTOMA (exp010 refutó d²: 16× estado -> +0.0003).
H-V4-4 propone que lo que limita el recall en la práctica es la OPTIMIZACIÓN: un modelo con capacidad suficiente
se queda CLAVADO en azar si se lo entrena de arranque en la carga DURA (el optimizador no encuentra el circuito
de recall), pero un CURRÍCULO (empezar con pocas asociaciones y subir) lo lleva al mismo modelo a un plateau
ALTO. Verificado en calibración: a d=32, n_pairs=40, 500 steps, el híbrido entrenado DIRECTO en duro queda en
azar (0.061 ≈ 0.062).

ANALOGÍA: querés memorizar 40 pares clave→valor de golpe y no aprendés NADA (te abruma). Si empezás con 8 y vas
subiendo, formás el "hábito" de buscar-y-recuperar y al final manejás los 40 — mismo cerebro, mismas horas. El
techo no era tu capacidad; era CÓMO te lo enseñaron.

DISEÑO (reusa cognia_x/train/recall_task). MISMO modelo (híbrido, d fijo) y MISMO cómputo (steps). 3 brazos:
  - baseline:     entrena n_pairs = HARD todo el tiempo (la carga dura de arranque).
  - curriculum:   entrena n_pairs rampando EASY→HARD a lo largo de los steps; eval en HARD.
  - baseline_2x:  baseline con el DOBLE de steps (control de cómputo: ¿es el currículo o sólo más cómputo?).
Eval: recall acc en la carga HARD (held-out). 3 seeds.

PREDICCIÓN FALSABLE (pre-registrada):
  - APOYADA si curriculum >> baseline (acc final, a IGUAL cómputo) Y curriculum >= baseline_2x - margen (el
    currículo gana incluso al baseline con DOBLE cómputo) => el techo de recall es de OPTIMIZACIÓN (el currículo
    mueve el plateau), no de capacidad; el modelo SIEMPRE tuvo la capacidad.
  - REFUTADA si curriculum ~ baseline (el currículo no ayuda) O baseline_2x alcanza a curriculum (era sólo
    cómputo, no el currículo).
  - MIXTA si el currículo ayuda pero baseline_2x lo alcanza parcialmente (cómputo + currículo).

Uso:
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp048_recall_curriculum.run --smoke
  .\venv312\Scripts\python.exe -m cognia_x.experiments.exp048_recall_curriculum.run            # FULL
"""
import argparse
import json
import math
import os
import platform
import sys

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM
from cognia_x.train.recall_task import make_recall_batch, eval_recall

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")


def n_pairs_schedule(kind, step, steps, easy, hard):
    if kind == "curriculum":
        frac = step / max(1, steps)
        return int(round(easy + (hard - easy) * frac))      # rampa lineal easy->hard
    return hard                                              # baseline / baseline_2x: siempre duro


def train_recall(seed, kind, steps, args, log):
    """Entrena un híbrido (d fijo) con un schedule de n_pairs; eval en HARD. Reusa make_recall_batch/eval_recall."""
    rng = np.random.default_rng(seed)
    eval_rng = np.random.default_rng(seed + 10**6)
    torch.manual_seed(seed)
    L_hard = 2 * args.n_pairs_hard + args.n_queries
    vocab = 1 + args.n_keys + args.n_vals
    chance = 1.0 / args.n_vals
    cfg = HybridConfig(vocab_size=vocab, d_model=args.d_model, n_layers=args.n_layers, n_heads=args.n_heads,
                       window=L_hard + 1, attn_every=args.attn_every, max_seq_len=L_hard + 1)
    model = HybridLM(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    model.train()
    for step in range(1, steps + 1):
        if args.warmup > 0 and step <= args.warmup:
            for g in opt.param_groups:
                g["lr"] = args.lr * step / args.warmup
        np_step = n_pairs_schedule(kind, step, steps, args.n_pairs_easy, args.n_pairs_hard)
        x, y = make_recall_batch(rng, args.batch, np_step, args.n_queries, args.n_keys, args.n_vals, "cpu")
        _, loss = model(x, y)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
    acc = eval_recall(model, eval_rng, args.n_pairs_hard, args.n_queries, args.n_keys, args.n_vals, "cpu", batches=20)
    log(f"[exp048]   seed={seed} {kind:>12} (steps={steps}): recall_HARD={acc:.3f} (azar {chance:.3f}) params={model.num_params():,}")
    return round(acc, 4), round(chance, 4)


def run_seed(seed, args, log):
    base, chance = train_recall(seed, "baseline", args.steps, args, log)
    curri, _ = train_recall(seed, "curriculum", args.steps, args, log)
    base2x, _ = train_recall(seed, "baseline_2x", 2 * args.steps, args, log)
    return {"seed": seed, "baseline": base, "curriculum": curri, "baseline_2x": base2x, "chance": chance}


def build_summary(per_seed, args):
    margin = round(2 * math.sqrt(0.25 / (20 * 32)), 4)       # ~2σ del eval (20 batches × 32)
    def m(k):
        return round(float(np.mean([s[k] for s in per_seed])), 4)
    base, curri, base2x, chance = m("baseline"), m("curriculum"), m("baseline_2x"), m("chance")
    curri_beats_base = (curri - base) > 0.15                 # el currículo mueve el plateau MUCHO
    curri_beats_base2x = curri >= base2x - margin            # gana incluso al doble de cómputo
    base_stuck = base <= chance + 0.10                       # el baseline directo se queda ~azar

    if curri_beats_base and curri_beats_base2x:
        status = "apoyada"
        verdict = ("H-V4-4 APOYADA: el techo de recall es de OPTIMIZACIÓN, no de capacidad. A IGUAL modelo (d="
                   "{d}) y cómputo, el baseline (carga dura de arranque) queda {bs} (azar {ch}) mientras el "
                   "CURRÍCULO (easy→hard) llega a {cu} (+{g:.3f}). Y el currículo GANA al baseline con DOBLE "
                   "cómputo ({b2}) -> no es cómputo, es el CURRÍCULO: el modelo SIEMPRE tuvo la capacidad; el "
                   "optimizador necesitaba el orden fácil→difícil para encontrar el circuito de recall. Mueve el "
                   "plateau.").format(d=args.d_model, bs=("CLAVADO en azar" if base_stuck else "en {:.3f}".format(base)),
                                      ch=chance, cu=curri, g=curri - base, b2=base2x)
    elif (curri - base) <= 0.15:
        status = "refutada"
        verdict = ("H-V4-4 REFUTADA: el currículo no mueve el plateau (curriculum {cu} ~ baseline {bs}) -> a esta "
                   "escala el límite no se levanta con currículo.").format(cu=curri, bs=base)
    else:
        status = "mixta"
        verdict = ("H-V4-4 MIXTA: el currículo ayuda (curriculum {cu} vs baseline {bs}) pero el baseline con doble "
                   "cómputo lo ALCANZA ({b2}) -> el lever es cómputo + currículo, no el currículo solo.").format(
                       cu=curri, bs=base, b2=base2x)

    return {"margin": margin, "baseline": base, "curriculum": curri, "baseline_2x": base2x, "chance": chance,
            "curri_minus_base": round(curri - base, 4), "curri_beats_base": bool(curri_beats_base),
            "curri_beats_base2x": bool(curri_beats_base2x), "base_stuck": bool(base_stuck),
            "n_seeds": len(per_seed), "status": status, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=str, default="0,1,2")
    ap.add_argument("--steps", type=int, default=700)
    ap.add_argument("--d_model", type=int, default=32)
    ap.add_argument("--n_layers", type=int, default=4)
    ap.add_argument("--n_heads", type=int, default=4)
    ap.add_argument("--attn_every", type=int, default=3)
    ap.add_argument("--n_keys", type=int, default=160)
    ap.add_argument("--n_vals", type=int, default=16)
    ap.add_argument("--n_pairs_easy", type=int, default=8)
    ap.add_argument("--n_pairs_hard", type=int, default=40)
    ap.add_argument("--n_queries", type=int, default=16)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=40)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.steps = "0,1", 400

    torch.set_num_threads(3)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip() != ""]
    os.makedirs(RESULTS, exist_ok=True)
    logf = open(os.path.join(RESULTS, "run.log"), "a", encoding="utf-8")
    logs = []

    def log(m):
        print(m, flush=True); logs.append(m); logf.write(m + "\n"); logf.flush()

    log(f"[exp048] CYCLE 63 / H-V4-4 — techo de recall = OPTIMIZACIÓN (currículo mueve el plateau)")
    log(f"[exp048] d={args.d_model} ae={args.attn_every} n_pairs {args.n_pairs_easy}->{args.n_pairs_hard} "
        f"steps={args.steps} seeds={seeds}")

    res = [run_seed(s, args, log) for s in seeds]
    sm = build_summary(res, args)
    log(f"[exp048] FINAL (media): baseline={sm['baseline']:.3f} curriculum={sm['curriculum']:.3f} "
        f"baseline_2x={sm['baseline_2x']:.3f} (azar {sm['chance']:.3f})")
    log(f"[exp048] VEREDICTO H-V4-4: {sm['status'].upper()} | {sm['verdict']}")

    out = {"exp": "exp048_recall_curriculum", "cycle": 63, "hypothesis": "H-V4-4",
           "claim": "el techo de recall es de optimización, no de capacidad: un currículo easy->hard mueve el "
                    "plateau a igual modelo y cómputo",
           "verdict": sm["status"], "summary": sm, "args": vars(args), "seeds": res,
           "platform": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__},
           "log": logs}
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log(f"[exp048] escrito {os.path.join(RESULTS, 'results.json')}")
    logf.close()


if __name__ == "__main__":
    main()

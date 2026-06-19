"""
CYCLE 7 — entrena el char-LM hibrido sobre el corpus GRANDE (17.4MB de prosa de dominio público,
cognia_x/data/corpus/) para mostrar MENOS sobreajuste que CYCLE 5 (778KB markdown, sobreajustó a
~29 épocas). Mismo modelo (6.3M params) — la variable es el TAMAÑO/diversidad del corpus.

Loguea train loss y val loss a la par para medir el GAP (señal de sobreajuste), guarda el mejor
checkpoint por val, muestrea a distintos pasos, y escribe summary.json al cerrar.

Uso:
  python -m cognia_x.train.run_cycle7 --deadline <epoch>            # corre hasta el deadline
  python -m cognia_x.train.run_cycle7 --hours 5                     # 5 horas de pared
  python -m cognia_x.train.run_cycle7 --smoke                       # smoke corto
Requiere el corpus: python -m cognia_x.data.get_corpus
"""
import argparse
import json
import os
import time

import torch

from cognia_x.train import charlm

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CORPUS = os.path.join(ROOT, "cognia_x", "data", "corpus")
RUN_DIR = os.path.join(ROOT, "cognia_x", "runs", "cycle7")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline", type=float, default=None, help="epoch time límite")
    ap.add_argument("--hours", type=float, default=None, help="horas de pared")
    ap.add_argument("--smoke", action="store_true")
    # config (defaults = receta CYCLE 7; overridable)
    ap.add_argument("--d_model", type=int, default=256)
    ap.add_argument("--n_layers", type=int, default=8)
    ap.add_argument("--n_heads", type=int, default=8)
    ap.add_argument("--window", type=int, default=128)
    ap.add_argument("--attn_every", type=int, default=4)
    ap.add_argument("--L", type=int, default=192)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--max_steps", type=int, default=12000,
                    help="tope por épocas (~2.3 épocas a 17MB): corta por pasos, no solo por reloj, "
                         "para no reproducir el sobreajuste de CYCLE 5 (~29 épocas)")
    ap.add_argument("--ckpt_every", type=int, default=200)
    ap.add_argument("--sample_every", type=int, default=1000)
    args = ap.parse_args()

    torch.set_num_threads(3)
    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(os.path.join(RUN_DIR, "run.log"), "a", encoding="utf-8")

    def log(s):
        print(s, flush=True)
        logf.write(s + "\n"); logf.flush()

    if args.smoke:
        deadline = time.time() + 60
        args.ckpt_every, args.sample_every, args.warmup, args.max_steps = 30, 60, 20, 80
    elif args.hours:
        deadline = time.time() + args.hours * 3600
    elif args.deadline:
        deadline = args.deadline
    else:
        deadline = time.time() + 5 * 3600  # default 5h

    log(f"[cycle7] inicio. corpus={CORPUS} deadline en {(deadline-time.time())/3600:.2f}h "
        f"d={args.d_model} layers={args.n_layers} warmup={args.warmup} lr={args.lr} "
        f"L={args.L} batch={args.batch}")
    t0 = time.time()
    res = charlm.train(
        root=ROOT, run_dir=RUN_DIR, corpus_dir=CORPUS, warmup=args.warmup, log=log,
        deadline=deadline, max_steps=args.max_steps,
        d_model=args.d_model, n_layers=args.n_layers, n_heads=args.n_heads,
        window=args.window, attn_every=args.attn_every, L=args.L, batch=args.batch, lr=args.lr,
        ckpt_every=args.ckpt_every, sample_every=args.sample_every)
    res["wall_hours"] = round((time.time() - t0) / 3600, 3)
    res["config"] = {k: getattr(args, k) for k in
                     ("d_model", "n_layers", "n_heads", "window", "attn_every", "L", "batch",
                      "lr", "warmup")}
    with open(os.path.join(RUN_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    log(f"[cycle7] FIN {res}")
    logf.close()


if __name__ == "__main__":
    main()

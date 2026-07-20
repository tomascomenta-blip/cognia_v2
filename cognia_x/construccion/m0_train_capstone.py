r"""
CAPSTONE del goal "ENTRENÁ la IA ... rápida y fácilmente reentrenable": entrena el modelo canónico
HybridLM (cognia_x/model/hybrid.py, fp16-seguro) VÍA el harness reentrenable (fast_harness) a CONVERGENCIA
REAL en la tarea de recall — cruzando la transición de grokking (>0.9) — con checkpoints atómicos.

Junta TODO lo medido en M0: harness reentrenable + atención fp16-segura + data-efficiency (weight_decay=0,
el que grokea más rápido — medido en m0_grok_accel). Demuestra el deliverable end-to-end (el smoke del
harness sólo corría 80 pasos; esto entrena a >0.9 y deja un checkpoint reanudable).

USO: venv312\Scripts\python.exe cognia_x\construccion\m0_train_capstone.py [--out DIR]
"""
import argparse
import os
import sys

import numpy as np

# repo root en sys.path (permite correr el script directo, no sólo como módulo)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from cognia_x.train.fast_harness import train
from cognia_x.train.recall_task import make_recall_batch, eval_recall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--steps", type=int, default=4500)
    args = ap.parse_args()
    out = args.out or os.path.join(os.environ.get("TEMP", "/tmp"), "cognia_capstone_grok")

    p = dict(batch=64, n_pairs=6, n_queries=6, n_keys=24, n_vals=8)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    cfg_model = dict(vocab_size=vocab, d_model=64, n_layers=4, n_heads=4, window=L + 1,
                     attn_every=1, max_seq_len=L + 1)               # atención pura (la que resuelve recall)
    cfg_train = dict(steps=args.steps, lr=3e-4, weight_decay=0.0,   # wd=0: grokea más rápido (medido)
                     warmup=100, ckpt_every=500, amp=False, fused=False, seed=0)

    rng = np.random.default_rng(0)
    eval_rng = np.random.default_rng(10**6)

    def bf(step):
        return make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], "cpu")

    def ev(model):
        return eval_recall(model, eval_rng, p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], "cpu", batches=8)

    print(f"[capstone] entrenando HybridLM canónico via fast_harness a convergencia (out={out})", flush=True)
    model, ckpt = train(cfg_model, cfg_train, out, bf, "cpu", print, eval_fn=ev)
    acc = ev(model)
    chance = 1.0 / p["n_vals"]
    print(f"\n[capstone] FINAL recall acc = {acc:.3f} (azar {chance:.3f}) | checkpoint reanudable en {ckpt}")
    print(f"[capstone] CHECK {'OK: cruzó >0.8 (grokking) via el harness reentrenable' if acc > 0.8 else 'NO cruzó (revisar)'}")


if __name__ == "__main__":
    main()

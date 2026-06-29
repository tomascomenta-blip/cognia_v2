r"""
PALANCA DE VELOCIDAD: DATA-EFFICIENCY = acelerar el GROKKING (menos pasos para converger, a igual calidad).

Hallazgo (M0_G2_RESULTADO): el recall asociativo GROKEA — meseta larga a acc baja y luego transición
abrupta a >0.9. El costo de entreno DOMINANTE de esta tarea es el #pasos-hasta-la-transición. Reducirlo =
entrenar más rápido SIN tocar la calidad final (Pareto puro). La literatura del grokking (Power/Nanda et al.)
señala al WEIGHT DECAY (y al LR) como aceleradores. Este experimento lo MIDE en el HybridLM (atención pura):
para cada weight_decay, cuántos pasos hasta cruzar acc 0.8 (steps-to-grok) y la acc final.

Corre LOCAL en CPU (tarea chica que grokea ~3600 pasos; estable, sin la muerte de sesión de Colab free).
USO: venv312\Scripts\python.exe cognia_x\construccion\m0_grok_accel.py [--smoke]
"""
import argparse
import json
import time

import numpy as np
import torch

from m0_g2_recall_colab import HybridLM, build_layer_types, make_recall_batch, eval_recall


def steps_to_grok(wd, lr, p, max_steps, eval_every, device, log, thresh=0.8, seed=0):
    rng = np.random.default_rng(seed)
    eval_rng = np.random.default_rng(seed + 10**6)
    torch.manual_seed(seed)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    layer_types = build_layer_types(p["n_layers"], 1, "linear_first")   # atención pura
    model = HybridLM(vocab, p["d_model"], p["n_heads"], layer_types, L + 1, L + 1).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    warmup = 100
    model.train()
    grok_step, best = None, 0.0
    t0 = time.time()
    for step in range(1, max_steps + 1):
        if step <= warmup:
            for g in opt.param_groups:
                g["lr"] = lr * step / warmup
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        _, loss = model(x, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % eval_every == 0:
            acc = eval_recall(model, eval_rng, p, device, batches=8)
            best = max(best, acc)
            if grok_step is None and acc >= thresh:
                grok_step = step
                log(f"  [wd={wd}] GROK en step {step} (acc {acc:.3f})")
                break
    acc_final = eval_recall(model, eval_rng, p, device, batches=16)
    dt = time.time() - t0
    log(f"  [wd={wd}] grok_step={grok_step} best={best:.3f} final={acc_final:.3f} ({dt:.0f}s)")
    return {"weight_decay": wd, "lr": lr, "grok_step": grok_step, "best_acc": round(best, 4),
            "final_acc": round(acc_final, 4), "sec": round(dt, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)

    # tarea CHICA que grokea (~3600 pasos con wd=0.01): atención pura, chance=1/8=0.125
    p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=24, n_vals=8, n_pairs=6, n_queries=6, batch=64)
    if args.smoke:
        wds = [0.01, 1.0]
        max_steps, eval_every = 800, 200
    else:
        wds = [0.0, 0.01, 0.1, 0.3, 1.0]     # barrido de weight decay (acelerador clásico del grokking)
        max_steps, eval_every = 10000, 100
    lr = 3e-4

    def log(s):
        print(s, flush=True)
    log(f"[grok] device={device} task={p} lr={lr} max_steps={max_steps}")

    runs = []
    for wd in wds:
        runs.append(steps_to_grok(wd, lr, p, max_steps, eval_every, device, log))
        with open("g2_grok_accel_results.json", "w", encoding="utf-8") as f:
            json.dump({"task": p, "lr": lr, "runs": runs}, f, indent=2, ensure_ascii=False)

    # veredicto: ¿qué weight_decay minimiza steps-to-grok manteniendo la calidad final?
    grokked = [r for r in runs if r["grok_step"] is not None]
    print("\n===== DATA-EFFICIENCY via WEIGHT DECAY (steps-to-grok, menor = más rápido) =====", flush=True)
    for r in runs:
        print(f"  wd={r['weight_decay']:<5} grok_step={r['grok_step']} final_acc={r['final_acc']}", flush=True)
    if grokked:
        best = min(grokked, key=lambda r: r["grok_step"])
        base = next((r for r in runs if r["weight_decay"] == 0.01), None)
        msg = f"\nMejor: wd={best['weight_decay']} grokea en {best['grok_step']} pasos (final {best['final_acc']})."
        if base and base["grok_step"] and best["grok_step"]:
            msg += f" vs wd=0.01 ({base['grok_step']} pasos) = {base['grok_step']/best['grok_step']:.2f}× más rápido."
        print(msg, flush=True)
    print(">>> GROK JSON:")
    print(json.dumps({"runs": runs}, ensure_ascii=False))


if __name__ == "__main__":
    main()

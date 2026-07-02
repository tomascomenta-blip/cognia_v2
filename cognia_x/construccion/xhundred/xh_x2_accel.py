r"""
X2 (04_MOM_GROKKING §6) — ¿el grok-step se compra barato con optimizador/estabilidad?

Brazos × 2 seeds sobre la MISMA tarea MQAR de X1 (baseline wd=0, α=1 → grok ~3600):
  adamw        baseline (el de X1 α=1)
  grokfast_l2  Grokfast-EMA λ=2, α=0.98 (amplificar componente lenta del gradiente)
  grokfast_l5  Grokfast-EMA λ=5
  stablemax    CE con StableMax en la salida (anti softmax-collapse, ICLR 2025)
  muon         Muon (matrices 2D ocultas) + AdamW resto — el optimizador de la receta K3

Métrica congelada: steps-to-grok (acc≥0.8) y WALL a igual calidad final (≥0.80); overhead por
step (si >5% y no acelera, se descarta). PREDICCIÓN: algún brazo baja ≥2×; Muon ~1.5×; riesgo:
Grokfast-EMA inestable. Si nada baja ≥1.3×, los aceleradores de paper no transfieren.
DESVÍO DECLARADO vs plan (~60 min T4): corre LOCAL en CPU — mismo harness que X1 (donde el
baseline replica exacto), cero quota GPU, comparabilidad directa con X1.
USO: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_x2_accel.py [--smoke]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from m0_g2_recall_colab import HybridLM, build_layer_types, make_recall_batch, eval_recall  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent / "results_x1" / "xh_x2_results.json"
LR = 3e-4
WD = 0.0
THRESH = 0.8
SEEDS = (0, 1)


@torch.no_grad()
def ns5(G, steps=5, eps=1e-7):
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.float()
    X = X / (X.norm() + eps)
    t = X.size(0) > X.size(1)
    if t:
        X = X.mT
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * A @ A
        X = a * X + B @ X
    return X.mT if t else X


class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr=0.02, momentum=0.95):
        super().__init__(params, dict(lr=lr, momentum=momentum))

    @torch.no_grad()
    def step(self, closure=None):
        for g in self.param_groups:
            for p in g["params"]:
                if p.grad is None:
                    continue
                st = self.state[p]
                if "buf" not in st:
                    st["buf"] = torch.zeros_like(p.grad)
                buf = st["buf"]
                buf.mul_(g["momentum"]).add_(p.grad)
                gg = p.grad.add(buf, alpha=g["momentum"])
                O = ns5(gg.reshape(gg.size(0), -1)).reshape_as(gg)
                p.add_(O, alpha=-g["lr"] * max(1, p.size(0) / p.size(1)) ** 0.5)


def stablemax_ce(logits, targets):
    """StableMax (2501.04697): s(x)=x+1 si x>=0, 1/(1-x) si x<0; CE = -log s_t/sum s."""
    s = torch.where(logits >= 0, logits + 1.0, 1.0 / (1.0 - logits))
    p_t = s.gather(1, targets[:, None]).squeeze(1) / s.sum(1)
    return -torch.log(p_t.clamp_min(1e-12)).mean()


def run_arm(name, p, max_steps, eval_every, device, seed):
    rng = np.random.default_rng(seed)
    eval_master = seed + 10 ** 6
    torch.manual_seed(seed)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    model = HybridLM(vocab, p["d_model"], p["n_heads"],
                     build_layer_types(p["n_layers"], 1, "linear_first"), L + 1, L + 1).to(device)
    if name == "muon":
        body = [q for q in model.parameters() if q.ndim >= 2]
        rest = [q for q in model.parameters() if q.ndim < 2]
        opts = [Muon(body, lr=0.02, momentum=0.95),
                torch.optim.AdamW(rest, lr=LR, weight_decay=WD)]
        base_lrs = [0.02, LR]
    else:
        opts = [torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)]
        base_lrs = [LR]
    grok_lam = {"grokfast_l2": 2.0, "grokfast_l5": 5.0}.get(name)
    ema_g = None
    warmup = 100
    model.train()
    grok_step, best, t_grok = None, 0.0, None
    t0 = time.time()
    for step in range(1, max_steps + 1):
        if step <= warmup:
            for o, bl in zip(opts, base_lrs):
                for g in o.param_groups:
                    g["lr"] = bl * step / warmup
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], device)
        if name == "stablemax":
            logits, _ = model(x)
            m = y != -100
            loss = stablemax_ce(logits[m].float(), y[m])
        else:
            _, loss = model(x, y)
        for o in opts:
            o.zero_grad(set_to_none=True)
        loss.backward()
        if grok_lam is not None:                 # Grokfast-EMA (2405.20233)
            with torch.no_grad():
                if ema_g is None:
                    ema_g = [q.grad.clone() for q in model.parameters() if q.grad is not None]
                grads = [q.grad for q in model.parameters() if q.grad is not None]
                torch._foreach_mul_(ema_g, 0.98)
                torch._foreach_add_(ema_g, grads, alpha=0.02)
                torch._foreach_add_(grads, ema_g, alpha=grok_lam)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        for o in opts:
            o.step()
        if step % eval_every == 0:
            er = np.random.default_rng(eval_master)
            acc = eval_recall(model, er, p, device, batches=8)
            best = max(best, acc)
            if grok_step is None and acc >= THRESH:
                grok_step, t_grok = step, time.time() - t0
                break
    er = np.random.default_rng(eval_master)
    final_acc = eval_recall(model, er, p, device, batches=16)
    dt = time.time() - t0
    ms_step = dt / (grok_step or max_steps) * 1000
    print(f"  [{name} s{seed}] grok_step={grok_step} wall_grok={t_grok and round(t_grok, 1)}s "
          f"best={best:.3f} final={final_acc:.3f} ({ms_step:.0f} ms/step)", flush=True)
    return {"arm": name, "seed": seed, "grok_step": grok_step,
            "wall_to_grok_s": round(t_grok, 1) if t_grok else None,
            "best_acc": round(best, 4), "final_acc": round(final_acc, 4),
            "ms_per_step": round(ms_step, 1), "sec": round(dt, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=24, n_vals=8, n_pairs=6,
             n_queries=6, batch=64)
    arms = ("adamw", "grokfast_l2", "grokfast_l5", "stablemax", "muon")
    seeds = (0,) if args.smoke else SEEDS
    max_steps, eval_every = (300, 100) if args.smoke else (10000, 100)
    if args.smoke:
        arms = ("adamw", "grokfast_l2", "stablemax", "muon")
    print(f"[x2] device={device} arms={arms} seeds={seeds}", flush=True)
    out = {"experiment": "xh_x2_accel", "task": p, "lr": LR, "wd": WD,
           "baseline_x1": {"alpha1_grok": 3600}, "runs": []}
    t0 = time.time()
    for a in arms:
        for s in seeds:
            out["runs"].append(run_arm(a, p, max_steps, eval_every, device, s))
            out["minutes_total"] = round((time.time() - t0) / 60, 1)
            RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                    encoding="utf-8")

    if not args.smoke:
        byarm = {}
        for r in out["runs"]:
            byarm.setdefault(r["arm"], []).append(r)
        base = [r["grok_step"] for r in byarm.get("adamw", []) if r["grok_step"]]
        base_mean = sum(base) / len(base) if base else None
        ver = {}
        for a, rs in byarm.items():
            gs = [r["grok_step"] for r in rs if r["grok_step"]]
            ver[a] = {"grok_steps": [r["grok_step"] for r in rs],
                      "mean": (sum(gs) / len(gs)) if gs else None,
                      "speedup_vs_adamw": (round(base_mean / (sum(gs) / len(gs)), 2)
                                           if gs and base_mean else None),
                      "final_accs": [r["final_acc"] for r in rs]}
        out["veredicto"] = ver
        print(f"\n[x2] VEREDICTO: {json.dumps(ver, ensure_ascii=False)}", flush=True)
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[x2] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()

r"""
X1 (04_MOM_GROKKING §6) — ¿el plateau del grokking es ARTEFACTO de la parametrización?

Barrido Omnigrok de escala de init α∈{0.25,0.5,1,2,4} (pesos ndim≥2 multiplicados por α tras el
init; norms/bias intactos) sobre la tarea MQAR que grokea (baseline conocido: wd=0 → grok step
~3600, acc~0.82, m0_grok_accel + results_g2). wd=0, lr=3e-4, seed=0 — solo cambia α.

Progress measure por eval: LOGIT-GAP medio del target (logit correcto − max logit otro) en las
posiciones de query — si mejora suave ≥1000 steps antes del salto de accuracy, el "eureka" es de
la métrica, no del aprendizaje (predicción pre-registrada).

PREDICCIÓN congelada: α<1 reduce steps-to-grok ≥30% vs α=1; α>1 lo alarga; el gap adelanta ≥1000
steps. FALSACIÓN: si α chica NO mueve el grok-step, nuestra transición no es artefacto de init y
"pagar el plateau" revive (acotado a esta tarea).
Regla común: curva completa hasta grok + 3 evals extra; sin plateau_stop.
USO: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_x1_initscale.py [--smoke]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from m0_g2_recall_colab import HybridLM, build_layer_types, make_recall_batch, eval_recall  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent / "results_x1" / "xh_x1_results.json"
ALPHAS = (0.25, 0.5, 1.0, 2.0, 4.0)
LR = 3e-4
WD = 0.0
THRESH = 0.8


@torch.no_grad()
def eval_acc_gap(model, rng, p, device, batches=8):
    """accuracy + logit-gap medio del target en posiciones de query (progress measure X1)."""
    model.eval()
    hits = total = 0
    gaps = []
    for _ in range(batches):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], device)
        logits, _ = model(x)
        m = y != -100
        lg = logits[m].float()
        tgt = y[m]
        hits += int((lg.argmax(-1) == tgt).sum())
        total += int(m.sum())
        correct = lg.gather(1, tgt[:, None]).squeeze(1)
        lg2 = lg.clone()
        lg2.scatter_(1, tgt[:, None], float("-inf"))
        gaps.append(float((correct - lg2.max(1).values).mean()))
    model.train()
    return hits / max(1, total), sum(gaps) / len(gaps)


def run_arm(alpha, p, max_steps, eval_every, device, seed=0):
    rng = np.random.default_rng(seed)
    eval_rng_master = seed + 10 ** 6
    torch.manual_seed(seed)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    layer_types = build_layer_types(p["n_layers"], 1, "linear_first")
    model = HybridLM(vocab, p["d_model"], p["n_heads"], layer_types, L + 1, L + 1).to(device)
    with torch.no_grad():                       # Omnigrok: escala SOLO matrices (ndim>=2)
        for prm in model.parameters():
            if prm.ndim >= 2:
                prm.mul_(alpha)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WD)
    warmup = 100
    model.train()
    curve, grok_step, best = [], None, 0.0
    extra_evals = 0
    t0 = time.time()
    for step in range(1, max_steps + 1):
        if step <= warmup:
            for g in opt.param_groups:
                g["lr"] = LR * step / warmup
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], device)
        _, loss = model(x, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % eval_every == 0:
            er = np.random.default_rng(eval_rng_master)     # mismo eval set SIEMPRE
            acc, gap = eval_acc_gap(model, er, p, device)
            best = max(best, acc)
            curve.append({"step": step, "acc": round(acc, 4), "gap": round(gap, 4),
                          "loss": round(float(loss.detach()), 4)})
            if grok_step is None and acc >= THRESH:
                grok_step = step
                print(f"  [a={alpha}] GROK en step {step} (acc {acc:.3f}, gap {gap:.2f})",
                      flush=True)
            elif grok_step is not None:
                extra_evals += 1
                if extra_evals >= 3:            # curva completa hasta grok + 3 evals de contexto
                    break
    er = np.random.default_rng(eval_rng_master)
    final_acc = eval_recall(model, er, p, device, batches=16)
    dt = time.time() - t0
    # adelanto de la progress measure: primer step donde el gap cruza el 50% de su recorrido
    lead = None
    if grok_step is not None and len(curve) > 2:
        g0 = curve[0]["gap"]
        g_at = next(c["gap"] for c in curve if c["step"] == grok_step)
        half = g0 + 0.5 * (g_at - g0)
        cross = next((c["step"] for c in curve if c["gap"] >= half), None)
        lead = grok_step - cross if cross else None
    print(f"  [a={alpha}] grok_step={grok_step} best={best:.3f} final={final_acc:.3f} "
          f"lead_gap50={lead} ({dt:.0f}s)", flush=True)
    return {"alpha": alpha, "grok_step": grok_step, "best_acc": round(best, 4),
            "final_acc": round(final_acc, 4), "lead_gap50_steps": lead,
            "sec": round(dt, 1), "curve": curve}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=24, n_vals=8, n_pairs=6,
             n_queries=6, batch=64)              # tarea EXACTA del baseline (grok wd=0 @ ~3600)
    alphas = (1.0,) if args.smoke else ALPHAS
    max_steps, eval_every = (300, 100) if args.smoke else (10000, 100)
    print(f"[x1] device={device} alphas={alphas} wd={WD} lr={LR} max_steps={max_steps}", flush=True)
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    out = {"experiment": "xh_x1_initscale", "task": p, "wd": WD, "lr": LR,
           "baseline_conocido": {"wd0_grok_step": 3600}, "runs": []}
    t0 = time.time()
    for a in alphas:
        out["runs"].append(run_arm(a, p, max_steps, eval_every, device))
        out["minutes_total"] = round((time.time() - t0) / 60, 1)
        RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # veredicto pre-registrado
    by_a = {r["alpha"]: r for r in out["runs"]}
    if not args.smoke and by_a.get(1.0, {}).get("grok_step"):
        g1 = by_a[1.0]["grok_step"]
        red = {a: (1 - by_a[a]["grok_step"] / g1) if by_a[a]["grok_step"] else None
               for a in by_a if a < 1}
        out["veredicto"] = {
            "grok_steps": {str(a): by_a[a]["grok_step"] for a in by_a},
            "reduccion_alpha_chica": {str(a): (round(v, 3) if v is not None else "NO_GROK")
                                      for a, v in red.items()},
            "P_alpha_chica_reduce_30pct": any(v is not None and v >= 0.30 for v in red.values()),
            "P_alpha_grande_alarga": all(
                (by_a[a]["grok_step"] or 10 ** 9) > g1 for a in by_a if a > 1),
            "P_gap_adelanta_1000": {str(a): by_a[a]["lead_gap50_steps"] for a in by_a},
        }
        print(f"\n[x1] VEREDICTO: {json.dumps(out['veredicto'], ensure_ascii=False)}", flush=True)
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[x1] LISTO en {out['minutes_total']} min -> {RESULTS_PATH}", flush=True)


if __name__ == "__main__":
    main()

r"""
M0 — CURVA params ↔ VELOCIDAD, MEDIDA (el baseline de "más params = más lento", no asumido).

Por qué: el goal ataca la raíz "más parámetros = más lento". Para atacarla hay que MEDIRLA primero: cómo
escala el costo de entreno (y de forward/inferencia) con el #params del HybridLM, en el hardware real (T4).
Esta curva es el BASELINE contra el que se prueban las palancas de DESACOPLE (cuant/MoE/distil/RAG): una
palanca "desacopla" si mueve un punto FUERA de esta curva (mismo #params, menos tiempo — o más params,
mismo tiempo).

Qué mide, por tamaño (varía d_model con n_layers fijo, y opcionalmente n_layers):
  - num_params (sin contar embedding atado)
  - TRAIN: ms/step y tok/s con AMP fp16 (la config rápida MEDIDA en el profile; fwd+bwd+opt, con sync)
  - FWD: tok/s de forward puro (inferencia batch, sin autoregresión) — el costo de "leer los pesos"
  - ajuste log-log: exponente α en tok/s ∝ params^(-α) (1.0 = lineal "más params = proporcional más lento")

Importa el modelo EXACTO de m0_g2_recall_colab (single source). Corre en Colab T4 o CPU (--smoke).
USO (Colab T4): subir m0_g2_recall_colab.py + este archivo a /content; %run m0_paramspeed_curve.py
USO (CPU):      venv312\Scripts\python.exe cognia_x/construccion/m0_paramspeed_curve.py --smoke
"""
import argparse
import json
import math
import time

import numpy as np
import torch

from m0_g2_recall_colab import HybridLM, build_layer_types, make_recall_batch


def sync(device):
    if device == "cuda":
        torch.cuda.synchronize()


def build(d_model, n_layers, n_heads, attn_every, L, vocab, device):
    layer_types = build_layer_types(n_layers, attn_every, "linear_first")
    return HybridLM(vocab, d_model, n_heads, layer_types, L + 1, L + 1).to(device)


def measure_train(model, batch, L, vocab, device, amp, steps=25, warmup=8):
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    use_amp = amp and device == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    g = torch.Generator(device="cpu"); g.manual_seed(0)
    tok = batch * L

    def batch_xy():
        x = torch.randint(0, vocab, (batch, L), generator=g).to(device)
        y = torch.randint(0, vocab, (batch, L), generator=g).to(device)
        return x, y

    def step():
        x, y = batch_xy()
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
        else:
            _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()

    for _ in range(warmup):
        step()
    sync(device)
    t0 = time.time()
    for _ in range(steps):
        step()
    sync(device)
    dt = (time.time() - t0) / steps
    return {"ms_per_step": dt * 1000.0, "tok_per_s": tok / dt}


@torch.no_grad()
def measure_fwd(model, batch, L, vocab, device, amp, iters=25, warmup=8):
    model.eval()
    use_amp = amp and device == "cuda"
    g = torch.Generator(device="cpu"); g.manual_seed(1)
    x = torch.randint(0, vocab, (batch, L), generator=g).to(device)
    tok = batch * L

    def fwd():
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                model(x)
        else:
            model(x)

    for _ in range(warmup):
        fwd()
    sync(device)
    t0 = time.time()
    for _ in range(iters):
        fwd()
    sync(device)
    dt = (time.time() - t0) / iters
    model.train()
    return {"ms_per_fwd": dt * 1000.0, "tok_per_s": tok / dt}


def fit_alpha(params_list, toks_list):
    """Ajuste log-log: tok/s ∝ params^(-α). α=1 => 'más params = proporcional más lento' (lineal)."""
    lp = np.log(np.array(params_list, dtype=float))
    lt = np.log(np.array(toks_list, dtype=float))
    A = np.vstack([lp, np.ones_like(lp)]).T
    slope, _ = np.linalg.lstsq(A, lt, rcond=None)[0]
    return -slope     # tok/s baja con params => slope negativo => α = -slope


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-amp", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    amp = not args.no_amp
    if device == "cpu":
        torch.set_num_threads(3)

    out = {"device": device, "torch": torch.__version__, "amp": amp and device == "cuda"}
    if device == "cuda":
        out["gpu_name"] = torch.cuda.get_device_name(0)
        print(f"[curve] GPU={out['gpu_name']} amp={out['amp']}", flush=True)
    else:
        print(f"[curve] CPU torch={torch.__version__}", flush=True)

    # Eje: d_model creciente (n_layers, n_heads, attn_every fijos = backbone híbrido 25% attn).
    n_layers, n_heads, attn_every = 12, 8, 4
    L, vocab, batch = 80, 289, 64
    if args.smoke:
        sizes = [64, 128]
        n_layers = 4
        steps, warmup, iters = 5, 2, 5
    else:
        sizes = [128, 192, 256, 384, 512, 768]
        steps, warmup, iters = 25, 8, 25

    rows = []
    for d in sizes:
        if d % n_heads != 0 or (d // n_heads) % 2 != 0:
            continue
        torch.manual_seed(0)
        model = build(d, n_layers, n_heads, attn_every, L, vocab, device)
        npar = model.num_params()
        tr = measure_train(model, batch, L, vocab, device, amp, steps=steps, warmup=warmup)
        fw = measure_fwd(model, batch, L, vocab, device, amp, iters=iters, warmup=warmup)
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        row = {"d_model": d, "n_layers": n_layers, "params": npar,
               "train_ms_step": round(tr["ms_per_step"], 3), "train_tok_s": round(tr["tok_per_s"], 1),
               "fwd_ms": round(fw["ms_per_fwd"], 3), "fwd_tok_s": round(fw["tok_per_s"], 1)}
        rows.append(row)
        print(f"  d={d:4} params={npar:>11,} | train {row['train_ms_step']:7.2f} ms/step "
              f"{row['train_tok_s']:>9.0f} tok/s | fwd {row['fwd_ms']:6.2f} ms {row['fwd_tok_s']:>9.0f} tok/s",
              flush=True)
        del model
        if device == "cuda":
            torch.cuda.empty_cache()

    if len(rows) >= 2:
        out["alpha_train"] = round(fit_alpha([r["params"] for r in rows],
                                             [r["train_tok_s"] for r in rows]), 3)
        out["alpha_fwd"] = round(fit_alpha([r["params"] for r in rows],
                                           [r["fwd_tok_s"] for r in rows]), 3)
    out["rows"] = rows
    with open("g2_paramspeed_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[curve] alpha_train={out.get('alpha_train')} alpha_fwd={out.get('alpha_fwd')} "
          f"(alpha=1 => 'mas params = proporcional mas lento'; alpha<1 => sub-lineal)", flush=True)
    print(">>> CURVE JSON:", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

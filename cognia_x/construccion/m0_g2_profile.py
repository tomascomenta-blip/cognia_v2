r"""
G2 SPEED PROFILER — mide DÓNDE se va el tiempo de entreno de G2 (regla 10×: medir la raíz, no asumir).

Por qué existe: la corrida G2 en T4 fue ~1 step/s para un modelo de ~9.5M params (10-50× más lento de
lo esperado). Antes de "arreglar" hay que MEDIR el cuello. Este script:
  1) Confirma que la GPU se usa de verdad (device name, capability) — descarta el fallback a CPU.
  2) Desglosa el step en componentes (data-gen, H2D, forward, backward, optimizer) con
     torch.cuda.synchronize() — sin sync, el wall-clock miente porque CUDA es asíncrono.
  3) Mide PALANCAS de velocidad de a una, cada una con su steps/s y tok/s, y proyecta el tiempo de 8000
     pasos: AMP fp16, data-gen en GPU (sin numpy ni H2D), batch grande, torch.compile, y el combo.

Importa el modelo EXACTO de m0_g2_recall_colab (single source of truth — perfila lo que de verdad corre).

USO (Colab T4):  subir m0_g2_recall_colab.py + este archivo a /content, luego  %run m0_g2_profile.py
USO (CPU smoke): venv312\Scripts\python.exe cognia_x/construccion/m0_g2_profile.py --smoke
"""
import argparse
import json
import time

import numpy as np
import torch

from m0_g2_recall_colab import HybridLM, build_layer_types, make_recall_batch


def sync(device):
    if device == "cuda":
        torch.cuda.synchronize()


def gpu_make_recall_batch(g, batch, n_pairs, n_queries, n_keys, n_vals, device):
    """Idéntica semántica a make_recall_batch pero TODO en GPU con torch (sin numpy, sin H2D).
    Layout por fila: [k0,v0,...,k_{P-1},v_{P-1}, q0,...,q_{Q-1}]; target = val asociado por query."""
    KEY0, VAL0 = 1, 1 + n_keys
    B, P, Q = batch, n_pairs, n_queries
    keys = torch.argsort(torch.rand(B, n_keys, device=device, generator=g), dim=1)[:, :P]  # (B,P) distintas
    vals = torch.randint(0, n_vals, (B, P), device=device, generator=g)
    qidx = torch.randint(0, P, (B, Q), device=device, generator=g)
    qkeys = torch.gather(keys, 1, qidx)
    qvals = torch.gather(vals, 1, qidx)
    pair = torch.empty(B, 2 * P, dtype=torch.long, device=device)
    pair[:, 0::2] = KEY0 + keys
    pair[:, 1::2] = VAL0 + vals
    seq = torch.cat([pair, KEY0 + qkeys], dim=1)
    tgt = torch.full((B, 2 * P + Q), -100, dtype=torch.long, device=device)
    tgt[:, 2 * P:] = VAL0 + qvals
    return seq, tgt


def build_model(p, attn_every, device):
    layer_types = build_layer_types(p["n_layers"], attn_every, "linear_first")
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    window = L + 1
    return HybridLM(vocab, p["d_model"], p["n_heads"], layer_types, window, L + 1).to(device)


def component_breakdown(p, attn_every, device, steps=30, warmup=10):
    """Desglosa el step en data-gen / H2D / fwd / bwd / opt (con sync entre cada uno)."""
    model = build_model(p, attn_every, device)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=0.01)
    rng = np.random.default_rng(0)
    L = 2 * p["n_pairs"] + p["n_queries"]
    tok = p["batch"] * L

    def one_numpy_batch():
        return make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], device)

    # warmup
    for _ in range(warmup):
        x, y = one_numpy_batch()
        _, loss = model(x, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    sync(device)

    t = {"datagen": 0.0, "fwd": 0.0, "bwd": 0.0, "opt": 0.0}
    for _ in range(steps):
        t0 = time.time()
        x, y = one_numpy_batch()       # numpy + .to(device) (incluye H2D)
        sync(device); t1 = time.time()
        _, loss = model(x, y)
        sync(device); t2 = time.time()
        opt.zero_grad(set_to_none=True)
        loss.backward()
        sync(device); t3 = time.time()
        opt.step()
        sync(device); t4 = time.time()
        t["datagen"] += t1 - t0
        t["fwd"] += t2 - t1
        t["bwd"] += t3 - t2
        t["opt"] += t4 - t3
    for k in t:
        t[k] = t[k] / steps * 1000.0     # ms/step
    total = sum(t.values())
    t["total_ms"] = total
    t["steps_per_s"] = 1000.0 / total
    t["tok_per_s"] = tok / (total / 1000.0)
    return t


def time_variant(p, attn_every, device, amp=False, gpu_gen=False, batch=None,
                 compiled=False, steps=30, warmup=10):
    """Mide steps/s y tok/s de UNA config de palancas (todo medido con sync)."""
    pp = dict(p)
    if batch is not None:
        pp["batch"] = batch
    model = build_model(pp, attn_every, device)
    if compiled:
        model = torch.compile(model)
    opt = torch.optim.AdamW(model.parameters(), lr=pp["lr"], weight_decay=0.01)
    use_amp = amp and device == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    L = 2 * pp["n_pairs"] + pp["n_queries"]
    tok = pp["batch"] * L
    rng = np.random.default_rng(0)
    g = torch.Generator(device=device); g.manual_seed(0)

    def gen():
        if gpu_gen:
            return gpu_make_recall_batch(g, pp["batch"], pp["n_pairs"], pp["n_queries"],
                                         pp["n_keys"], pp["n_vals"], device)
        return make_recall_batch(rng, pp["batch"], pp["n_pairs"], pp["n_queries"],
                                 pp["n_keys"], pp["n_vals"], device)

    def step():
        x, y = gen()
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
        return loss

    for _ in range(warmup):    # warmup (incl. compilación si compiled=True)
        step()
    sync(device)
    t0 = time.time()
    for _ in range(steps):
        step()
    sync(device)
    dt = (time.time() - t0) / steps
    return {"ms_per_step": dt * 1000.0, "steps_per_s": 1.0 / dt, "tok_per_s": tok / dt,
            "batch": pp["batch"], "proj_8000_min": 8000 * dt / 60.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="tiny en CPU para verificar que corre")
    ap.add_argument("--steps", type=int, default=30)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    out = {"device": device, "torch": torch.__version__}
    print(f"[profile] torch={torch.__version__} cuda_available={torch.cuda.is_available()}", flush=True)
    if device == "cuda":
        out["gpu_name"] = torch.cuda.get_device_name(0)
        out["capability"] = list(torch.cuda.get_device_capability(0))
        print(f"[profile] GPU = {out['gpu_name']}  capability={out['capability']}", flush=True)
    else:
        torch.set_num_threads(3)
        print("[profile] CORRIENDO EN CPU (sin CUDA)", flush=True)

    if args.smoke:
        p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=12,
                 n_queries=8, batch=32, lr=1e-3)
        steps, warmup = 8, 3
    else:
        p = dict(d_model=256, n_heads=8, n_layers=12, n_keys=256, n_vals=32, n_pairs=32,
                 n_queries=16, batch=64, lr=1e-3)
        steps, warmup = args.steps, 10
    out["scale"] = p
    L = 2 * p["n_pairs"] + p["n_queries"]
    print(f"[profile] scale d_model={p['d_model']} layers={p['n_layers']} batch={p['batch']} L={L}", flush=True)

    # ── 1) DESGLOSE por componente (config lineal-puro = la que fue lenta, y atención-pura) ──
    print("\n==== DESGLOSE DEL STEP (ms) — baseline fp32, data-gen numpy+H2D ====", flush=True)
    out["breakdown"] = {}
    for tag, ae in [("lineal_puro_ae0", 0), ("attn_puro_ae1", 1)]:
        bd = component_breakdown(p, ae, device, steps=steps, warmup=warmup)
        out["breakdown"][tag] = bd
        print(f"  [{tag}] datagen={bd['datagen']:.2f} fwd={bd['fwd']:.2f} bwd={bd['bwd']:.2f} "
              f"opt={bd['opt']:.2f} | total={bd['total_ms']:.2f}ms -> {bd['steps_per_s']:.1f} step/s "
              f"({bd['tok_per_s']:.0f} tok/s)", flush=True)

    # ── 2) PALANCAS (sobre lineal_puro_ae0, el caso lento) ──
    print("\n==== PALANCAS DE VELOCIDAD (lineal_puro ae0) — steps/s, tok/s, proyección 8000 pasos ====", flush=True)
    variants = [
        ("baseline_fp32",            dict(amp=False, gpu_gen=False)),
        ("amp_fp16",                 dict(amp=True,  gpu_gen=False)),
        ("gpu_datagen",              dict(amp=False, gpu_gen=True)),
        ("amp+gpudatagen",           dict(amp=True,  gpu_gen=True)),
        ("amp+gpudatagen+batch256",  dict(amp=True,  gpu_gen=True, batch=256)),
        ("amp+gpudatagen+batch512",  dict(amp=True,  gpu_gen=True, batch=512)),
    ]
    out["levers"] = {}
    for name, kw in variants:
        try:
            r = time_variant(p, 0, device, steps=steps, warmup=warmup, **kw)
            out["levers"][name] = r
            print(f"  [{name:28}] {r['ms_per_step']:.2f} ms/step  {r['steps_per_s']:.1f} step/s  "
                  f"{r['tok_per_s']:.0f} tok/s  (8000 pasos ~ {r['proj_8000_min']:.1f} min)", flush=True)
        except Exception as e:  # noqa: BLE001
            out["levers"][name] = {"error": repr(e)}
            print(f"  [{name:28}] ERROR {e!r}", flush=True)

    # torch.compile aparte (puede tardar en la 1ra compilación; lo aislamos)
    if device == "cuda":
        for name, kw in [("amp+gpudatagen+batch512+compile",
                          dict(amp=True, gpu_gen=True, batch=512, compiled=True))]:
            try:
                r = time_variant(p, 0, device, steps=steps, warmup=max(15, warmup), **kw)
                out["levers"][name] = r
                print(f"  [{name:28}] {r['ms_per_step']:.2f} ms/step  {r['steps_per_s']:.1f} step/s  "
                      f"{r['tok_per_s']:.0f} tok/s  (8000 pasos ~ {r['proj_8000_min']:.1f} min)", flush=True)
            except Exception as e:  # noqa: BLE001
                out["levers"][name] = {"error": repr(e)}
                print(f"  [{name:28}] ERROR {e!r}", flush=True)

    if device == "cuda":
        out["gpu_mem_max_mb"] = torch.cuda.max_memory_allocated() / 1e6

    with open("g2_profile_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("\n>>> PROFILE JSON:", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

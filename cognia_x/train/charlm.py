"""
char/byte-level language model sobre texto LOCAL (sin descargas). Demuestra que el hibrido
APRENDE lenguaje: la loss baja y las muestras se vuelven texto plausible.

Corpus: todos los .md del repo (docs, wiki, manager) concatenados como bytes (vocab 256).
Auto-contenido y reproducible. Modelo hibrido byte-level (vocab 256, lm_head atado).
"""
import glob
import os
import time

import numpy as np
import torch

from cognia_x.model.hybrid import HybridConfig, HybridLM

_EXCLUDE = (".git", "node_modules", "venv", "venv312", "__pycache__", "dist", "build",
            os.path.join("cognia_x", "runs"))


def load_corpus(root, max_bytes=3_000_000):
    data = bytearray()
    for f in sorted(glob.glob(os.path.join(root, "**", "*.md"), recursive=True)):
        rel = os.path.relpath(f, root)
        if any(part in rel for part in _EXCLUDE):
            continue
        try:
            with open(f, "rb") as fh:
                data += fh.read() + b"\n\n"
        except Exception:
            continue
        if len(data) >= max_bytes:
            break
    return bytes(data[:max_bytes])


def get_batch(data_t, batch, L, device):
    ix = torch.randint(0, data_t.numel() - L - 1, (batch,))
    x = torch.stack([data_t[i:i + L] for i in ix]).to(device)
    y = torch.stack([data_t[i + 1:i + 1 + L] for i in ix]).to(device)
    return x.long(), y.long()


def train(root, run_dir, log, deadline, device="cpu", seed=0,
          d_model=256, n_layers=8, n_heads=8, window=128, attn_every=4,
          L=192, batch=16, lr=3e-4, max_steps=10_000_000,
          ckpt_every=200, sample_every=500):
    torch.manual_seed(seed)
    os.makedirs(run_dir, exist_ok=True)
    raw = load_corpus(root)
    if len(raw) < 10_000:
        log(f"[charlm] corpus muy chico ({len(raw)} bytes); abortando fase")
        return {"error": "corpus too small", "bytes": len(raw)}
    n = len(raw)
    split = int(0.9 * n)
    train_t = torch.frombuffer(bytearray(raw[:split]), dtype=torch.uint8)
    val_t = torch.frombuffer(bytearray(raw[split:]), dtype=torch.uint8)
    log(f"[charlm] corpus {n:,} bytes (train {split:,}/val {n-split:,})")

    cfg = HybridConfig(vocab_size=256, d_model=d_model, n_layers=n_layers, n_heads=n_heads,
                       window=window, attn_every=attn_every, max_seq_len=L)
    model = HybridLM(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    types = cfg.layer_types()
    log(f"[charlm] params={model.num_params():,} d={d_model} layers={n_layers} "
        f"({types.count('linear')}lin/{types.count('attn')}attn,W={window}) L={L} batch={batch}")

    best_val = float("inf")
    step = 0
    t0 = time.time()
    model.train()
    while step < max_steps and time.time() < deadline:
        step += 1
        x, y = get_batch(train_t, batch, L, device)
        _, loss = model(x, y)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

        if step % 50 == 0:
            sps = step / (time.time() - t0)
            log(f"[charlm] step {step} loss {loss.item():.4f} ({sps:.2f} steps/s)")
        if step % ckpt_every == 0:
            vl = _val_loss(model, val_t, L, batch, device)
            log(f"[charlm] step {step} VAL loss {vl:.4f}")
            torch.save({"step": step, "model": model.state_dict(), "cfg": cfg.__dict__,
                        "val_loss": vl}, os.path.join(run_dir, "charlm_last.pt"))
            if vl < best_val:
                best_val = vl
                torch.save({"step": step, "model": model.state_dict(), "cfg": cfg.__dict__,
                            "val_loss": vl}, os.path.join(run_dir, "charlm_best.pt"))
        if step % sample_every == 0:
            try:
                s = sample(model, device, n_new=300)
                with open(os.path.join(run_dir, "charlm_samples.txt"), "a", encoding="utf-8") as fh:
                    fh.write(f"\n===== step {step} (val_best {best_val:.4f}) =====\n{s}\n")
                log(f"[charlm] muestra guardada (step {step})")
            except Exception as e:  # noqa: BLE001
                log(f"[charlm] sample fallo (no critico): {e!r}")

    vl = _val_loss(model, val_t, L, batch, device)
    torch.save({"step": step, "model": model.state_dict(), "cfg": cfg.__dict__, "val_loss": vl},
               os.path.join(run_dir, "charlm_last.pt"))
    log(f"[charlm] FIN step {step} val {vl:.4f} best {best_val:.4f}")
    return {"steps": step, "final_val_loss": vl, "best_val_loss": min(best_val, vl),
            "params": model.num_params(), "corpus_bytes": n}


@torch.no_grad()
def _val_loss(model, data_t, L, batch, device, iters=20):
    model.eval()
    tot = 0.0
    for _ in range(iters):
        x, y = get_batch(data_t, batch, L, device)
        _, loss = model(x, y)
        tot += loss.item()
    model.train()
    return tot / iters


@torch.no_grad()
def sample(model, device, n_new=300, prompt=b"Cognia-X "):
    idx = torch.tensor([list(prompt)], dtype=torch.long, device=device)
    out = model.generate(idx, n_new=n_new, temperature=0.8, top_k=40)
    return bytes(out[0].tolist()).decode("utf-8", errors="replace")

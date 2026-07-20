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


def _strip_gutenberg(b):
    """Quita el boilerplate legal de Project Gutenberg (header + footer idénticos entre libros;
    si no se quita, el modelo memoriza ese texto repetido)."""
    start = b.find(b"*** START")
    if start != -1:
        nl = b.find(b"\n", start)
        if nl != -1:
            b = b[nl + 1:]
    end = b.find(b"*** END")
    if end != -1:
        b = b[:end]
    return b.strip()


def load_corpus_dir(corpus_dir, strip_gutenberg=True):
    """Carga todos los *.txt de un directorio como lista de (nombre, bytes). El split per-archivo
    (en train()) usa esta estructura para que el set de validación abarque TODOS los dominios."""
    docs = []
    for f in sorted(glob.glob(os.path.join(corpus_dir, "*.txt"))):
        try:
            with open(f, "rb") as fh:
                raw = fh.read()
        except Exception:
            continue
        if strip_gutenberg:
            raw = _strip_gutenberg(raw)
        if len(raw) > 1000:
            docs.append((os.path.basename(f), raw))
    return docs


def get_batch(data_t, batch, L, device):
    ix = torch.randint(0, data_t.numel() - L - 1, (batch,))
    x = torch.stack([data_t[i:i + L] for i in ix]).to(device)
    y = torch.stack([data_t[i + 1:i + 1 + L] for i in ix]).to(device)
    return x.long(), y.long()


def train(root, run_dir, log, deadline, device="cpu", seed=0, corpus_dir=None, warmup=0,
          val_books=("es_49836", "en_alice"),
          d_model=256, n_layers=8, n_heads=8, window=128, attn_every=4,
          L=192, batch=16, lr=3e-4, max_steps=10_000_000,
          ckpt_every=200, sample_every=500):
    torch.manual_seed(seed)
    os.makedirs(run_dir, exist_ok=True)
    SEP = b"\n\n"   # separador entre libros (evita ventanas a caballo entre dos obras/idiomas)
    if corpus_dir:
        docs = load_corpus_dir(corpus_dir)
        if not docs:
            log(f"[charlm] sin .txt en {corpus_dir}; abortando")
            return {"error": "no corpus files", "dir": corpus_dir}
        # holdout CROSS-BOOK: 1-2 libros ENTEROS (1 es + 1 en) nunca vistos en train -> val es
        # generalización a OBRA NUEVA (sin leakage de autocorrelación intra-obra que tendría un
        # split del 10% final del mismo libro).
        train_b, val_b = bytearray(), bytearray()
        train_docs, val_docs = [], []
        for name, b in docs:
            if any(v in name for v in val_books):
                val_b += b + SEP; val_docs.append(name)
            else:
                train_b += b + SEP; train_docs.append(name)
        n = len(train_b) + len(val_b)
        log(f"[charlm] corpus {len(docs)} docs {n:,}B | train {len(train_docs)} docs {len(train_b):,}B "
            f"| val CROSS-BOOK {val_docs} {len(val_b):,}B")
    else:
        raw = load_corpus(root)
        if len(raw) < 10_000:
            log(f"[charlm] corpus muy chico ({len(raw)} bytes); abortando fase")
            return {"error": "corpus too small", "bytes": len(raw)}
        n = len(raw)
        sp = int(0.9 * n)
        train_b, val_b = bytearray(raw[:sp]), bytearray(raw[sp:])
        log(f"[charlm] corpus {n:,} bytes (train {len(train_b):,}/val {len(val_b):,})")
    if len(train_b) <= L + 1 or len(val_b) <= L + 1:
        log(f"[charlm] split muy chico para L={L} (train {len(train_b)}/val {len(val_b)}); abortando")
        return {"error": "split too small for L", "train": len(train_b), "val": len(val_b)}
    train_t = torch.frombuffer(train_b, dtype=torch.uint8)
    val_t = torch.frombuffer(val_b, dtype=torch.uint8)
    # baseline de compresión (contexto: cuánto del val es entropía irreducible)
    base = {"gzip_train_bpb": gzip_bits_per_byte(train_b), "gzip_val_bpb": gzip_bits_per_byte(val_b)}
    log(f"[charlm] baseline gzip: train {base['gzip_train_bpb']:.3f} bits/byte, "
        f"val {base['gzip_val_bpb']:.3f} bits/byte")

    cfg = HybridConfig(vocab_size=256, d_model=d_model, n_layers=n_layers, n_heads=n_heads,
                       window=window, attn_every=attn_every, max_seq_len=L)
    model = HybridLM(cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    types = cfg.layer_types()
    log(f"[charlm] params={model.num_params():,} d={d_model} layers={n_layers} "
        f"({types.count('linear')}lin/{types.count('attn')}attn,W={window}) L={L} batch={batch}")

    LN2 = 0.6931471805599453
    bytes_per_epoch = len(train_b)
    csv_path = os.path.join(run_dir, "metrics.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("step,epoch,train_nats,val_nats,gap_nats,val_bpb\n")
    metrics = []
    best_val = float("inf")
    step = 0
    t0 = time.time()
    model.train()

    def checkpoint(step):
        # GAP train-val con eval DETERMINISTA (mismo método en ambos) — la señal central del ciclo
        nonlocal best_val
        tr = eval_loss(model, train_t, L, device)
        vl = eval_loss(model, val_t, L, device)
        gap = vl - tr
        epoch = step * batch * L / bytes_per_epoch
        log(f"[charlm] step {step} ep {epoch:.2f} train {tr:.4f} VAL {vl:.4f} gap {gap:+.4f} "
            f"({vl/LN2:.3f} bits/byte)")
        with open(csv_path, "a", encoding="utf-8") as f:
            f.write(f"{step},{epoch:.3f},{tr:.4f},{vl:.4f},{gap:.4f},{vl/LN2:.4f}\n")
        metrics.append({"step": step, "epoch": round(epoch, 3), "train_nats": round(tr, 4),
                        "val_nats": round(vl, 4), "gap_nats": round(gap, 4)})
        torch.save({"step": step, "model": model.state_dict(), "cfg": cfg.__dict__, "val_loss": vl},
                   os.path.join(run_dir, "charlm_last.pt"))
        if vl < best_val:
            best_val = vl
            torch.save({"step": step, "model": model.state_dict(), "cfg": cfg.__dict__,
                        "val_loss": vl}, os.path.join(run_dir, "charlm_best.pt"))
        return vl

    while step < max_steps and time.time() < deadline:
        step += 1
        if warmup > 0 and step <= warmup:
            for g in opt.param_groups:
                g["lr"] = lr * step / warmup
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
            checkpoint(step)
        if step % sample_every == 0:
            try:
                s = sample(model, device, n_new=300)
                with open(os.path.join(run_dir, "charlm_samples.txt"), "a", encoding="utf-8") as fh:
                    fh.write(f"\n===== step {step} (val_best {best_val:.4f}) =====\n{s}\n")
                log(f"[charlm] muestra guardada (step {step})")
            except Exception as e:  # noqa: BLE001
                log(f"[charlm] sample fallo (no critico): {e!r}")

    vl = checkpoint(step)
    log(f"[charlm] FIN step {step} val {vl:.4f} best {best_val:.4f} ({best_val/LN2:.3f} bits/byte)")
    return {"steps": step, "final_val_nats": vl, "best_val_nats": best_val,
            "best_val_bpb": round(best_val / LN2, 4), "final_epoch": round(metrics[-1]["epoch"], 3),
            "final_gap_nats": metrics[-1]["gap_nats"], "params": model.num_params(),
            "corpus_bytes": n, "gzip_baseline": base, "val_books": list(val_docs) if corpus_dir else None,
            "metrics": metrics}


def gzip_bits_per_byte(data_bytes):
    """Baseline de compresión: bits/byte de gzip-9. Contextualiza cuánta de la pérdida del modelo
    es entropía irreducible del corpus (un char-LM debería bajar de este número)."""
    import gzip
    comp = gzip.compress(bytes(data_bytes), 9)
    return round(8.0 * len(comp) / max(1, len(data_bytes)), 4)


@torch.no_grad()
def eval_loss(model, data_t, L, device, max_windows=400):
    """Pérdida DETERMINISTA: barrido de ventanas CONTIGUAS no solapadas (stride=L) que cubren
    data_t una sola vez (submuestreo uniforme determinista si hay más de max_windows). Reproducible
    (no muestrea al azar), así best_val/gap no se eligen por suerte de muestreo."""
    model.eval()
    n = data_t.numel()
    starts = list(range(0, n - L - 1, L))
    if not starts:
        model.train()
        return float("nan")
    if len(starts) > max_windows:
        stride = len(starts) / max_windows
        starts = [starts[int(i * stride)] for i in range(max_windows)]
    tot, cnt = 0.0, 0
    bs = 16
    for j in range(0, len(starts), bs):
        chunk = starts[j:j + bs]
        x = torch.stack([data_t[s:s + L] for s in chunk]).long().to(device)
        y = torch.stack([data_t[s + 1:s + 1 + L] for s in chunk]).long().to(device)
        _, loss = model(x, y)
        tot += loss.item() * len(chunk)
        cnt += len(chunk)
    model.train()
    return tot / max(1, cnt)


@torch.no_grad()
def sample(model, device, n_new=300, prompt=b"Cognia-X "):
    idx = torch.tensor([list(prompt)], dtype=torch.long, device=device)
    out = model.generate(idx, n_new=n_new, temperature=0.8, top_k=40)
    return bytes(out[0].tolist()).decode("utf-8", errors="replace")

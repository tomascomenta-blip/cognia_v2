r"""
XARCH A/B — Loop Transformer x Chimera-banded, decidido con números en T4 (goal OLMo/Chimera).

HIPÓTESIS (pre-registradas, cada una cae o queda por evidencia):
  H-LOOP: iterar pocas capas compartidas (Universal/Looped Transformer) compra profundidad efectiva
    sin params → looped2x4 (2 capas únicas, 4 vueltas) supera a vanilla2 (mismos params) y se acerca
    a vanilla8 (mismos FLOPs de profundidad) — más en tareas estructuradas (recall) que en LM.
    Evidencia previa: Dehghani 2018 (UT), Giannou 2023 (looped TF ejecutan programas).
  H-CHIMERA: atención banded (mayoría sliding-window LOCAL + minoría GLOBAL — la traducción a nivel
    arquitectura del Chimera interno del repo: band router LOCAL/MEDIA/GLOBAL, fase 53) mantiene la
    calidad de LM de vanilla a menor costo por token largo Y retiene recall lejano vía las capas
    globales. Evidencia: Gemma-2/Longformer; gate G1 del repo (SWA retención 0.597 vs full 0.525).
  H-COMBO: banded + loop se componen sin interferir (si ambas quedan).
  Sonda extra: extrapolación de longitud (train 512 → eval 1024) por arquitectura (RoPE OOD).

Protocolo: mismas dims (d=256, 8 heads, byte-level vocab 256), mismo optimizador/steps/datos.
  Tarea 1: LM sobre texto REAL (es-wiki streaming; fallback wikitext-2) seq 512 → val bits/byte.
  Tarea 2: recall MQAR largo (L=416 > window 256: obliga a usar las capas globales) → acc final.
  Métricas: params, bpb@512, bpb@1024 (extrapolación), recall_acc, tok/s de entreno.

Self-contained, kernel Kaggle T4 con INTERNET (dataset). Resultados incrementales a xarch_results.json.
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xarch_kernel.py --smoke
"""
import argparse
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS_PATH = "xarch_results.json"
TIME_BUDGET_MIN = 85.0


# ───────────────────────── modelo: transformer puro con SWA opcional y loops ───────────────────────


def build_rope_cache(seq_len, dh, device, base=10000.0):
    half = dh // 2
    inv_freq = 1.0 / (base ** (torch.arange(0, half, device=device).float() / half))
    pos = torch.arange(seq_len, device=device).float()
    ang = torch.outer(pos, inv_freq)
    emb = torch.cat([ang, ang], dim=-1)
    return emb.cos(), emb.sin()


def apply_rope(x, cos, sin):
    L = x.shape[-2]
    cos = cos[:L].view(1, 1, L, -1)
    sin = sin[:L].view(1, 1, L, -1)
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half], x[..., half:]
    rot = torch.cat([-x2, x1], dim=-1)
    return x * cos + rot * sin


class RMSNorm(nn.Module):
    def __init__(self, d, eps=1e-5):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))
        self.eps = eps

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.w


class SwiGLU(nn.Module):
    def __init__(self, d, d_ff):
        super().__init__()
        self.w1 = nn.Linear(d, d_ff, bias=False)
        self.w2 = nn.Linear(d, d_ff, bias=False)
        self.w3 = nn.Linear(d_ff, d, bias=False)

    def forward(self, x):
        return self.w3(F.silu(self.w1(x)) * self.w2(x))


class Attn(nn.Module):
    """Atención causal SDPA con RoPE; window=None => global, int => sliding window."""

    def __init__(self, d, n_heads, window=None):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos, sin):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)
        if self.window is None or self.window >= L:
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:
            idx = torch.arange(L, device=x.device)
            mask = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - self.window))
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.o(out.transpose(1, 2).reshape(B, L, D))


class Block(nn.Module):
    def __init__(self, d, n_heads, d_ff, window=None):
        super().__init__()
        self.norm1 = RMSNorm(d)
        self.attn = Attn(d, n_heads, window)
        self.norm2 = RMSNorm(d)
        self.mlp = SwiGLU(d, d_ff)

    def forward(self, x, cos, sin):
        x = x + self.attn(self.norm1(x), cos, sin)
        x = x + self.mlp(self.norm2(x))
        return x


class TinyLM(nn.Module):
    """layer_windows: lista de window (None=global) por capa ÚNICA; loops: cuántas vueltas se itera
    la pila completa (loops>1 = Looped Transformer, pesos COMPARTIDOS entre vueltas)."""

    def __init__(self, vocab, d, n_heads, layer_windows, loops=1, max_seq=2048, d_ff=None):
        super().__init__()
        d_ff = d_ff or max(16, int(round(8 * d / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w) for w in layer_windows])
        self.loops = loops
        cos, sin = build_rope_cache(max_seq, d // n_heads, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        for _ in range(self.loops):
            for b in self.blocks:
                x = b(x, cos, sin)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1),
                                   ignore_index=-100)
        return logits, loss

    def num_params(self):
        return sum(p.numel() for p in self.parameters()) - self.embed.weight.numel()


# ───────────────────────── datos ────────────────────────────────────────────────────────────────────


def get_text(smoke, target_bytes=9_000_000):
    if smoke:
        return ("la casa es azul y el cielo se llena de nubes blancas cuando llueve en la ciudad. "
                "los gatos duermen al sol mientras los perros corren por el parque verde. " * 800)
    try:
        from datasets import load_dataset
        ds = load_dataset("wikimedia/wikipedia", "20231101.es", split="train", streaming=True)
        parts, total = [], 0
        for a in ds:
            t = a.get("text", "")
            if len(t) > 500:
                parts.append(t)
                total += len(t)
            if total >= target_bytes:
                break
        print(f"[data] es-wiki: {total} bytes de {len(parts)} articulos", flush=True)
        return "\n\n".join(parts)
    except Exception as e:  # noqa: BLE001
        print(f"[data] es-wiki fallo ({e!r}) -> fallback wikitext-2", flush=True)
        from datasets import load_dataset
        ds = load_dataset("wikitext", "wikitext-103-raw-v1", split="train")
        parts, total = [], 0
        for t in ds["text"]:
            if t.strip():
                parts.append(t)
                total += len(t)
            if total >= target_bytes:
                break
        return "\n".join(parts)


def to_bytes_tensor(text, device):
    arr = np.frombuffer(text.encode("utf-8", "ignore"), dtype=np.uint8)
    return torch.from_numpy(arr.copy()).long().to(device)


def lm_batch(ids, seq, batch, g):
    starts = torch.randint(0, len(ids) - seq - 1, (batch,), generator=g, device=ids.device)
    x = torch.stack([ids[s:s + seq] for s in starts])
    y = torch.stack([ids[s + 1:s + seq + 1] for s in starts])
    return x, y


def make_recall_batch(rng, batch, n_pairs, n_queries, n_keys, n_vals, device):
    KEY0, VAL0 = 1, 1 + n_keys
    B, P, Q = batch, n_pairs, n_queries
    keys = np.argsort(rng.random((B, n_keys)), axis=1)[:, :P]
    vals = rng.integers(0, n_vals, size=(B, P))
    qidx = rng.integers(0, P, size=(B, Q))
    qkeys = np.take_along_axis(keys, qidx, axis=1)
    qvals = np.take_along_axis(vals, qidx, axis=1)
    pair = np.empty((B, 2 * P), dtype=np.int64)
    pair[:, 0::2] = KEY0 + keys
    pair[:, 1::2] = VAL0 + vals
    seq = np.concatenate([pair, KEY0 + qkeys], axis=1)
    tgt = np.full((B, 2 * P + Q), -100, dtype=np.int64)
    tgt[:, 2 * P:] = VAL0 + qvals
    return torch.from_numpy(seq).to(device), torch.from_numpy(tgt).to(device)


# ───────────────────────── entreno/eval ─────────────────────────────────────────────────────────────


def make_scaler(enabled):
    try:
        return torch.amp.GradScaler("cuda", enabled=enabled)
    except (AttributeError, TypeError):
        return torch.cuda.amp.GradScaler(enabled=enabled)


def train_lm(model, ids_tr, ids_va, seq, batch, steps, lr, device, log, eval_every):
    use_amp = device == "cuda"
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01,
                            fused=use_amp or None)
    scaler = make_scaler(use_amp)
    g = torch.Generator(device=device)
    g.manual_seed(0)
    model.train()
    t0 = time.time()
    warmup = min(100, steps // 10)
    for step in range(1, steps + 1):
        if step <= warmup:
            for gr in opt.param_groups:
                gr["lr"] = lr * step / warmup
        x, y = lm_batch(ids_tr, seq, batch, g)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
        else:
            _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        if step % eval_every == 0 or step == steps:
            bpb = eval_bpb(model, ids_va, seq, device)
            log(f"    step {step}/{steps} loss {float(loss):.3f} val_bpb {bpb:.3f}")
    wall = time.time() - t0
    return {"tok_per_s": round(steps * batch * seq / wall), "wall_s": round(wall, 1)}


@torch.no_grad()
def eval_bpb(model, ids, seq, device, n_windows=16):
    """bits/byte en ventanas disjuntas del held-out."""
    model.eval()
    use_amp = device == "cuda"
    nll, n = 0.0, 0
    for i in range(n_windows):
        s = i * seq
        if s + seq + 1 > len(ids):
            break
        x = ids[s:s + seq].unsqueeze(0)
        y = ids[s + 1:s + seq + 1].unsqueeze(0)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
        else:
            _, loss = model(x, y)
        nll += float(loss) * seq
        n += seq
    model.train()
    return round(nll / max(1, n) / math.log(2), 4)


@torch.no_grad()
def eval_recall(model, rng, p, device, batches=12):
    model.eval()
    hits = total = 0
    use_amp = device == "cuda"
    for _ in range(batches):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], device)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                logits, _ = model(x)
        else:
            logits, _ = model(x)
        pred = logits.argmax(-1)
        m = y != -100
        hits += int((pred[m] == y[m]).sum())
        total += int(m.sum())
    model.train()
    return hits / max(1, total)


def train_recall(model, p, steps, device, log):
    use_amp = device == "cuda"
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01, fused=use_amp or None)
    scaler = make_scaler(use_amp)
    rng = np.random.default_rng(0)
    eval_rng = np.random.default_rng(10**6)
    warmup = min(100, steps // 10)
    model.train()
    best = 0.0
    for step in range(1, steps + 1):
        if step <= warmup:
            for gr in opt.param_groups:
                gr["lr"] = 1e-3 * step / warmup
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"],
                                 p["n_keys"], p["n_vals"], device)
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
        else:
            _, loss = model(x, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        if step % max(1, steps // 8) == 0 or step == steps:
            acc = eval_recall(model, eval_rng, p, device, batches=8)
            best = max(best, acc)
            log(f"    recall step {step}/{steps} loss {float(loss):.3f} acc {acc:.3f}")
    return {"recall_acc": round(eval_recall(model, eval_rng, p, device, batches=16), 4),
            "recall_best": round(best, 4)}


# ───────────────────────── main ─────────────────────────────────────────────────────────────────────


def save(out):
    try:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    smoke = args.smoke
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    t0 = time.time()
    out = {"experiment": "xarch_ab", "torch": torch.__version__, "device": device}
    print(f"[xarch] smoke={smoke} device={device}", flush=True)

    if smoke:
        d, heads, seq, batch, lm_steps, rec_steps, win = 32, 4, 64, 8, 20, 20, 16
        rec_p = dict(batch=8, n_pairs=12, n_queries=4, n_keys=32, n_vals=8)
        max_seq = 256
    else:
        d, heads, seq, batch, lm_steps, rec_steps, win = 256, 8, 512, 32, 2000, 1500, 256
        # L = 2*200+16 = 416 > window 256: el recall lejano OBLIGA a las capas globales (H-CHIMERA)
        rec_p = dict(batch=32, n_pairs=200, n_queries=16, n_keys=256, n_vals=32)
        max_seq = 2048

    text = get_text(smoke)
    ids = to_bytes_tensor(text, device)
    n_val = min(len(ids) // 10, 300_000)
    ids_tr, ids_va = ids[:-n_val], ids[-n_val:]
    out["data_bytes"] = int(len(ids))
    print(f"[xarch] datos: {len(ids_tr)} train / {len(ids_va)} val bytes", flush=True)
    save(out)

    VARIANTS = [
        ("vanilla8",       dict(layer_windows=[None] * 8, loops=1)),
        ("banded8",        dict(layer_windows=[win, win, win, None, win, win, win, None], loops=1)),
        ("vanilla2",       dict(layer_windows=[None] * 2, loops=1)),
        ("looped2x4",      dict(layer_windows=[None] * 2, loops=4)),
        ("banded_loop2x4", dict(layer_windows=[win, None], loops=4)),
    ]
    rec_vocab = 1 + rec_p["n_keys"] + rec_p["n_vals"]

    def over():
        return (time.time() - t0) / 60 > TIME_BUDGET_MIN

    out["variants"] = {}
    for name, kw in VARIANTS:
        if over():
            out["variants"][name] = {"skipped": "budget"}
            save(out)
            continue
        print(f"\n==== {name} ====", flush=True)
        r = {}
        try:
            torch.manual_seed(0)
            m = TinyLM(256, d, heads, max_seq=max_seq, **kw).to(device)
            r["params"] = m.num_params()
            print(f"  params={r['params']:,}", flush=True)
            r["lm"] = train_lm(m, ids_tr, ids_va, seq, batch, lm_steps, 6e-4, device,
                               lambda s: print(s, flush=True), eval_every=max(1, lm_steps // 4))
            r["bpb_512"] = eval_bpb(m, ids_va, seq, device)
            r["bpb_1024"] = eval_bpb(m, ids_va, seq * 2, device, n_windows=8)   # extrapolación 2x
            print(f"  bpb@{seq}={r['bpb_512']}  bpb@{seq * 2}={r['bpb_1024']} (extrapolación)", flush=True)
            del m
            if device == "cuda":
                torch.cuda.empty_cache()
            torch.manual_seed(0)
            m2 = TinyLM(rec_vocab, d, heads, max_seq=max_seq, **kw).to(device)
            r.update(train_recall(m2, rec_p, rec_steps, device, lambda s: print(s, flush=True)))
            print(f"  recall_acc={r['recall_acc']} (azar={1 / rec_p['n_vals']:.3f})", flush=True)
            del m2
            if device == "cuda":
                torch.cuda.empty_cache()
        except Exception as e:  # noqa: BLE001
            r["error"] = repr(e)[:300]
            print(f"  ERROR {e!r}", flush=True)
        out["variants"][name] = r
        save(out)

    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save(out)
    print(f"\n[xarch] LISTO en {out['minutes_total']} min", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

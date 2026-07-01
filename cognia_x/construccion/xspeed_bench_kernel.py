r"""
XSPEED BENCH — matriz de palancas de velocidad de entreno del HybridLM en Kaggle T4 (TAREA 1).

Qué cierra (huecos explícitos de M0_VELOCIDAD_SINTESIS.md §8 y M0_G2_PROFILE_RESULTADO.md):
  1. Re-mide el speedup AMP con el fix fp16-SEGURO aplicado (el 1.9x/4.1x previo era PRE-fix).
  2. Mide palancas NUEVAS en T4: torch.compile mode="reduce-overhead" (CUDA graphs — apunta directo
     al diagnóstico raíz "overhead/launch-bound"), max-autotune, batch 768/1024, AdamW fused,
     gradient checkpointing (costo vs memoria), SDPA (F.scaled_dot_product_attention) para la
     atención softmax, y DataParallel 2x T4.
  3. GATES DE CALIDAD: (a) paridad de loss fp32 vs fp16-seguro vs +compile (misma seed, mismos
     datos, mismo batch) sobre el híbrido ae4; (b) grokking end-to-end a escala tiny (la config
     rápida debe cruzar el mismo recall que fp32 en ~los mismos steps).

Self-contained (embebe HybridLM fiel a cognia_x/model/hybrid.py con el fix fp16-seguro, y la tarea
de recall de cognia_x/train/recall_task.py). Corre como kernel "script" de Kaggle (2x T4) sin
internet ni datasets. Resultados incrementales a xspeed_results.json (sobrevive cortes).

USO Kaggle:  push via cognia_x/construccion/run_kaggle_xspeed.py
USO local:   venv312\Scripts\python.exe cognia_x/construccion/xspeed_bench_kernel.py --smoke
"""
import argparse
import contextlib
import gc
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint as torch_checkpoint

RESULTS_PATH = "xspeed_results.json"
TIME_BUDGET_MIN = 75.0          # red de seguridad: pasado esto, las variantes restantes se marcan skipped

# ───────────────────────── modelo (fiel a hybrid.py, path elu, fix fp16-seguro) ─────────────────────


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
        n = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return n * self.w


class SwiGLU(nn.Module):
    def __init__(self, d, d_ff):
        super().__init__()
        self.w1 = nn.Linear(d, d_ff, bias=False)
        self.w2 = nn.Linear(d, d_ff, bias=False)
        self.w3 = nn.Linear(d_ff, d, bias=False)

    def forward(self, x):
        return self.w3(F.silu(self.w1(x)) * self.w2(x))


class LinearAttention(nn.Module):
    """Atención lineal causal (elu+1). fp16_safe=True = fix canónico (núcleo en fp32, ver hybrid.py).
    fp16_safe=False existe SOLO para medir el costo de velocidad del fix (calidad INVÁLIDA: NaN ~step 1664)."""

    def __init__(self, d, n_heads, fp16_safe=True):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.fp16_safe = fp16_safe
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos=None, sin=None):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        ctx = (torch.autocast(device_type=x.device.type, enabled=False) if self.fp16_safe
               else contextlib.nullcontext())
        with ctx:
            if self.fp16_safe:
                q, k, v = q.float(), k.float(), v.float()
            q = F.elu(q) + 1.0
            k = F.elu(k) + 1.0
            scores = torch.matmul(q, k.transpose(-1, -2))
            mask = torch.tril(torch.ones(L, L, device=x.device, dtype=torch.bool))
            scores = scores.masked_fill(~mask, 0.0)
            denom = scores.sum(-1, keepdim=True) + 1e-6
            out = torch.matmul(scores, v) / denom
        out = out.transpose(1, 2).reshape(B, L, D).to(x.dtype)
        return self.o(out)


class SlidingWindowAttention(nn.Module):
    """Atención softmax causal con ventana W. use_sdpa=True reemplaza el núcleo manual por
    F.scaled_dot_product_attention (kernel fusionado; en sm75 usa mem-efficient attention, estable
    en fp16 SIN el upcast manual a fp32 — palanca que recupera el costo del fix fp16-seguro)."""

    def __init__(self, d, n_heads, window, fp16_safe=True, use_sdpa=False):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.fp16_safe = fp16_safe
        self.use_sdpa = use_sdpa
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos=None, sin=None):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        if self.use_sdpa:
            if cos is not None:
                q = apply_rope(q, cos, sin)
                k = apply_rope(k, cos, sin)
            if self.window >= L:
                out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
            else:
                idx = torch.arange(L, device=x.device)
                mask = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - self.window))
                out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
            out = out.transpose(1, 2).reshape(B, L, D).to(x.dtype)
            return self.o(out)
        ctx = (torch.autocast(device_type=x.device.type, enabled=False) if self.fp16_safe
               else contextlib.nullcontext())
        with ctx:
            if self.fp16_safe:
                q, k, v = q.float(), k.float(), v.float()
            if cos is not None:
                c = cos.float() if self.fp16_safe else cos
                s = sin.float() if self.fp16_safe else sin
                q = apply_rope(q, c, s)
                k = apply_rope(k, c, s)
            scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(self.dh)
            idx = torch.arange(L, device=x.device)
            causal = idx[None, :] <= idx[:, None]
            windowed = idx[None, :] > (idx[:, None] - self.window)
            mask = causal & windowed
            scores = scores.masked_fill(~mask, float("-inf"))
            attn = F.softmax(scores, dim=-1)
            out = torch.matmul(attn, v)
        out = out.transpose(1, 2).reshape(B, L, D).to(x.dtype)
        return self.o(out)


class Block(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, kind, window, fp16_safe=True, use_sdpa=False):
        super().__init__()
        self.kind = kind
        self.norm1 = RMSNorm(d_model)
        self.mixer = (SlidingWindowAttention(d_model, n_heads, window, fp16_safe, use_sdpa) if kind == "attn"
                      else LinearAttention(d_model, n_heads, fp16_safe))
        self.norm2 = RMSNorm(d_model)
        self.mlp = SwiGLU(d_model, d_ff)

    def forward(self, x, cos=None, sin=None):
        x = x + self.mixer(self.norm1(x), cos, sin)
        x = x + self.mlp(self.norm2(x))
        return x


def build_layer_types(n_layers, attn_every, arrangement="linear_first"):
    if attn_every <= 0:
        return ["linear"] * n_layers
    if attn_every == 1:
        return ["attn"] * n_layers
    return ["attn" if (i % attn_every == attn_every - 1) else "linear" for i in range(n_layers)]


class HybridLM(nn.Module):
    def __init__(self, vocab, d_model, n_heads, layer_types, window, max_seq_len, d_ff=None,
                 fp16_safe=True, use_sdpa=False, grad_ckpt=False):
        super().__init__()
        d_ff = d_ff or max(16, int(round(8 * d_model / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d_model)
        self.blocks = nn.ModuleList([Block(d_model, n_heads, d_ff, t, window, fp16_safe, use_sdpa)
                                     for t in layer_types])
        self.dh = d_model // n_heads
        cos, sin = build_rope_cache(max_seq_len, self.dh, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab, bias=False)
        self.lm_head.weight = self.embed.weight     # tied
        self.layer_types = layer_types
        self.grad_ckpt = grad_ckpt
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        for b in self.blocks:
            if self.grad_ckpt and self.training and torch.is_grad_enabled():
                x = torch_checkpoint(b, x, cos, sin, use_reentrant=False)
            else:
                x = b(x, cos, sin)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-100)
        return logits, loss

    def num_params(self):
        n = sum(p.numel() for p in self.parameters())
        return n - self.embed.weight.numel()


# ───────────────────────── tarea de recall (fiel a recall_task.py) ──────────────────────────────────


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


def gpu_make_recall_batch(g, batch, n_pairs, n_queries, n_keys, n_vals, device):
    """Idéntica semántica pero TODO en device (sin numpy ni H2D)."""
    KEY0, VAL0 = 1, 1 + n_keys
    B, P, Q = batch, n_pairs, n_queries
    keys = torch.argsort(torch.rand(B, n_keys, device=device, generator=g), dim=1)[:, :P]
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


@torch.no_grad()
def eval_recall(model, rng, p, device, batches=12, amp=False):
    model.eval()
    hits = total = 0
    for _ in range(batches):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        if amp:
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


# ───────────────────────── infra de medición ────────────────────────────────────────────────────────


def sync(device):
    if device == "cuda":
        torch.cuda.synchronize()


def make_scaler(enabled):
    try:
        return torch.amp.GradScaler("cuda", enabled=enabled)
    except (AttributeError, TypeError):
        return torch.cuda.amp.GradScaler(enabled=enabled)


def build_model(p, attn_every, device, fp16_safe=True, use_sdpa=False, grad_ckpt=False):
    layer_types = build_layer_types(p["n_layers"], attn_every)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    window = L + 1
    return HybridLM(vocab, p["d_model"], p["n_heads"], layer_types, window, L + 1,
                    fp16_safe=fp16_safe, use_sdpa=use_sdpa, grad_ckpt=grad_ckpt).to(device)


def cleanup(device):
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def component_breakdown(p, attn_every, device, amp=False, steps=30, warmup=10):
    """Desglosa el step en datagen(+H2D)/fwd/bwd/opt con sync entre componentes."""
    model = build_model(p, attn_every, device)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=0.01)
    use_amp = amp and device == "cuda"
    scaler = make_scaler(use_amp)
    rng = np.random.default_rng(0)
    L = 2 * p["n_pairs"] + p["n_queries"]
    tok = p["batch"] * L

    def fwd_bwd_opt(x, y, timers=None):
        t1 = time.time()
        if use_amp:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                _, loss = model(x, y)
        else:
            _, loss = model(x, y)
        sync(device)
        t2 = time.time()
        opt.zero_grad(set_to_none=True)
        if use_amp:
            scaler.scale(loss).backward()
        else:
            loss.backward()
        sync(device)
        t3 = time.time()
        if use_amp:
            scaler.step(opt)
            scaler.update()
        else:
            opt.step()
        sync(device)
        t4 = time.time()
        if timers is not None:
            timers["fwd"] += t2 - t1
            timers["bwd"] += t3 - t2
            timers["opt"] += t4 - t3

    for _ in range(warmup):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        fwd_bwd_opt(x, y)
    sync(device)
    t = {"datagen": 0.0, "fwd": 0.0, "bwd": 0.0, "opt": 0.0}
    for _ in range(steps):
        t0 = time.time()
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
        sync(device)
        t["datagen"] += time.time() - t0
        fwd_bwd_opt(x, y, t)
    for k in t:
        t[k] = t[k] / steps * 1000.0
    total = sum(t.values())
    t["total_ms"] = total
    t["steps_per_s"] = 1000.0 / total
    t["tok_per_s"] = tok / (total / 1000.0)
    return t


def time_variant(p, attn_every, device, amp=False, gpu_gen=False, batch=None, compile_mode=None,
                 fused=False, grad_ckpt=False, sdpa=False, fp16_safe=True, dp=False,
                 steps=30, warmup=10):
    """Mide UNA config de palancas: ms/step, steps/s, tok/s, memoria pico y costo de warmup (compile)."""
    pp = dict(p)
    if batch is not None:
        pp["batch"] = batch
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    torch.manual_seed(0)
    model = build_model(pp, attn_every, device, fp16_safe=fp16_safe, use_sdpa=sdpa, grad_ckpt=grad_ckpt)
    if compile_mode is not None:
        torch._dynamo.reset()
        model = torch.compile(model, mode=None if compile_mode == "default" else compile_mode)
    if dp:
        model = nn.DataParallel(model)
    opt = torch.optim.AdamW(model.parameters(), lr=pp["lr"], weight_decay=0.01, fused=fused or None)
    use_amp = amp and device == "cuda"
    scaler = make_scaler(use_amp)
    L = 2 * pp["n_pairs"] + pp["n_queries"]
    tok = pp["batch"] * L
    rng = np.random.default_rng(0)
    g = torch.Generator(device=device)
    g.manual_seed(0)

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
            if loss.dim() > 0:          # DataParallel junta un loss por réplica
                loss = loss.mean()
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
        else:
            _, loss = model(x, y)
            if loss.dim() > 0:
                loss = loss.mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        return loss

    tw0 = time.time()
    loss = None
    for _ in range(warmup):             # incluye compilación / captura de CUDA graphs
        loss = step()
    sync(device)
    warmup_s = time.time() - tw0
    t0 = time.time()
    for _ in range(steps):
        loss = step()
    sync(device)
    dt = (time.time() - t0) / steps
    out = {"ms_per_step": round(dt * 1000.0, 2), "steps_per_s": round(1.0 / dt, 2),
           "tok_per_s": round(tok / dt), "batch": pp["batch"], "warmup_s": round(warmup_s, 1),
           "loss_finite": bool(torch.isfinite(loss.detach()).all().item())}
    if device == "cuda":
        out["mem_max_mb"] = round(torch.cuda.max_memory_allocated() / 1e6)
    return out


# ───────────────────────── gates de calidad ─────────────────────────────────────────────────────────


def parity_run(p, attn_every, device, amp, compile_mode, steps, log_every=25):
    """Entrena con seed y DATOS idénticos (numpy rng CPU) y devuelve la curva de loss.
    Compara numéricamente fp32 vs fp16-seguro vs +compile: misma init (manual_seed), mismo batch."""
    torch.manual_seed(0)
    model = build_model(p, attn_every, device)
    if compile_mode is not None:
        torch._dynamo.reset()
        model = torch.compile(model, mode=None if compile_mode == "default" else compile_mode)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=0.01)
    use_amp = amp and device == "cuda"
    scaler = make_scaler(use_amp)
    rng = np.random.default_rng(123)
    losses = []
    t0 = time.time()
    for step in range(1, steps + 1):
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
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
        if step % log_every == 0:
            losses.append(round(loss.item(), 4))
    tail = losses[-4:]
    eval_rng = np.random.default_rng(999)
    acc = eval_recall(model, eval_rng, p, device, batches=12, amp=use_amp)
    return {"losses": losses, "final_loss": round(sum(tail) / len(tail), 4),
            "eval_acc": round(acc, 4), "wall_s": round(time.time() - t0, 1)}


def grok_run(p, device, amp, compile_mode, steps, eval_every, target=0.8, stop=0.95, log=print):
    """Calidad END-TO-END: la config debe CRUZAR el recall (grokking) igual que fp32.
    Devuelve el step del cruce (primera eval >= target) y best_acc."""
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    eval_rng = np.random.default_rng(10**6)
    model = build_model(p, 1, device)      # atención pura: grokea confiable (g2_confirm)
    if compile_mode is not None:
        torch._dynamo.reset()
        model = torch.compile(model, mode=None if compile_mode == "default" else compile_mode)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=p.get("wd", 0.0))
    use_amp = amp and device == "cuda"
    scaler = make_scaler(use_amp)
    warmup = p.get("warmup", 100)
    best_acc, grok_step = 0.0, None
    t0 = time.time()
    for step in range(1, steps + 1):
        if warmup > 0 and step <= warmup:
            for gp in opt.param_groups:
                gp["lr"] = p["lr"] * step / warmup
        x, y = make_recall_batch(rng, p["batch"], p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
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
            acc = eval_recall(model, eval_rng, p, device, batches=8, amp=use_amp)
            best_acc = max(best_acc, acc)
            if grok_step is None and acc >= target:
                grok_step = step
            log(f"    step {step}/{steps} loss {loss.item():.3f} acc {acc:.3f}")
            if acc >= stop:
                break
    return {"grok_step": grok_step, "best_acc": round(best_acc, 4), "steps_run": step,
            "wall_s": round(time.time() - t0, 1)}


# ───────────────────────── main ─────────────────────────────────────────────────────────────────────


def save(out):
    try:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser(description="XSPEED — matriz de palancas de velocidad en T4")
    ap.add_argument("--smoke", action="store_true", help="tiny en CPU para verificar que corre")
    ap.add_argument("--steps", type=int, default=30)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    t_start = time.time()
    out = {"experiment": "xspeed_bench", "device": device, "torch": torch.__version__}
    print(f"[xspeed] torch={torch.__version__} cuda={torch.cuda.is_available()}", flush=True)
    n_gpu = 0
    if device == "cuda":
        n_gpu = torch.cuda.device_count()
        out["gpu_name"] = torch.cuda.get_device_name(0)
        out["gpu_count"] = n_gpu
        out["capability"] = list(torch.cuda.get_device_capability(0))
        print(f"[xspeed] GPU={out['gpu_name']} x{n_gpu} cap={out['capability']}", flush=True)
    else:
        torch.set_num_threads(3)
        print("[xspeed] CPU (smoke)", flush=True)

    if args.smoke:
        p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=12,
                 n_queries=8, batch=32, lr=1e-3)
        steps, warmup, parity_steps = 4, 2, 30
        grok_p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=6,
                      n_queries=8, batch=32, lr=3e-4, wd=0.0, warmup=10)
        grok_steps, grok_eval = 40, 20
    else:
        p = dict(d_model=256, n_heads=8, n_layers=12, n_keys=256, n_vals=32, n_pairs=32,
                 n_queries=16, batch=64, lr=1e-3)
        steps, warmup, parity_steps = args.steps, 10, 600
        # config de grokking validada (g2_grok_accel: wd=0 grokea ~step 3600 a esta escala tiny)
        grok_p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=6,
                      n_queries=8, batch=64, lr=3e-4, wd=0.0, warmup=100)
        grok_steps, grok_eval = 6000, 200
    out["scale"] = p
    L = 2 * p["n_pairs"] + p["n_queries"]
    print(f"[xspeed] scale d={p['d_model']} layers={p['n_layers']} batch={p['batch']} L={L}", flush=True)

    def over_budget():
        return (time.time() - t_start) / 60.0 > TIME_BUDGET_MIN

    # ── 1) DESGLOSE por componente: fp32 y AMP fp16-SEGURO (el hueco: números POST-fix) ──
    print("\n==== DESGLOSE (ae0 lineal-puro): fp32 vs AMP fp16-seguro ====", flush=True)
    out["breakdown"] = {}
    for tag, amp in [("fp32_ae0", False), ("amp_safe_ae0", True)]:
        bd = component_breakdown(p, 0, device, amp=amp, steps=steps, warmup=warmup)
        out["breakdown"][tag] = bd
        print(f"  [{tag}] datagen={bd['datagen']:.2f} fwd={bd['fwd']:.2f} bwd={bd['bwd']:.2f} "
              f"opt={bd['opt']:.2f} | {bd['total_ms']:.1f}ms -> {bd['steps_per_s']:.1f} step/s "
              f"({bd['tok_per_s']:.0f} tok/s)", flush=True)
        cleanup(device)
        save(out)

    # ── 2) MATRIZ DE PALANCAS (ae0 salvo indicado) ──
    print("\n==== PALANCAS (30 steps medidos con sync; warmup incluye compile) ====", flush=True)
    is_cuda = device == "cuda"
    variants = [
        # (nombre, attn_every, kwargs) — los primeros replican el profile previo para comparabilidad
        ("baseline_fp32_b64",            0, dict()),
        ("amp_safe_b64",                 0, dict(amp=True)),
        ("amp_UNSAFE_fp16_b64",          0, dict(amp=True, fp16_safe=False)),   # SOLO velocidad: mide el costo del fix
        ("amp_gpugen_b64",               0, dict(amp=True, gpu_gen=True)),
        ("amp_gpugen_b256",              0, dict(amp=True, gpu_gen=True, batch=256)),
        ("amp_gpugen_b512",              0, dict(amp=True, gpu_gen=True, batch=512)),
        ("amp_gpugen_b768",              0, dict(amp=True, gpu_gen=True, batch=768)),
        ("amp_gpugen_b1024",             0, dict(amp=True, gpu_gen=True, batch=1024)),
        ("amp_gpugen_b512_fused",        0, dict(amp=True, gpu_gen=True, batch=512, fused=True)),
        ("amp_gpugen_b512_gradckpt",     0, dict(amp=True, gpu_gen=True, batch=512, grad_ckpt=True)),
        ("ae1_amp_b512_manual",          1, dict(amp=True, gpu_gen=True, batch=512)),
        ("ae1_amp_b512_sdpa",            1, dict(amp=True, gpu_gen=True, batch=512, sdpa=True)),
    ]
    if is_cuda:
        variants += [
            ("amp_gpugen_b512_compile",         0, dict(amp=True, gpu_gen=True, batch=512, compile_mode="default")),
            ("amp_gpugen_b512_compile_reduce",  0, dict(amp=True, gpu_gen=True, batch=512, compile_mode="reduce-overhead")),
            ("amp_gpugen_b64_compile_reduce",   0, dict(amp=True, gpu_gen=True, batch=64, compile_mode="reduce-overhead")),
            ("amp_gpugen_b512_compile_maxauto", 0, dict(amp=True, gpu_gen=True, batch=512, compile_mode="max-autotune")),
            ("combo_b512_reduce_fused",         0, dict(amp=True, gpu_gen=True, batch=512, compile_mode="reduce-overhead", fused=True)),
            ("combo_b1024_reduce_fused",        0, dict(amp=True, gpu_gen=True, batch=1024, compile_mode="reduce-overhead", fused=True)),
        ]
    if is_cuda and n_gpu >= 2:
        variants += [
            ("dp2_amp_gpugen_b1024",     0, dict(amp=True, gpu_gen=True, batch=1024, dp=True)),
        ]
    out["levers"] = {}
    for name, ae, kw in variants:
        if over_budget():
            out["levers"][name] = {"skipped": "time_budget"}
            print(f"  [{name:34}] SKIPPED (budget {TIME_BUDGET_MIN} min)", flush=True)
            continue
        wu = max(15, warmup) if kw.get("compile_mode") else warmup
        try:
            r = time_variant(p, ae, device, steps=steps, warmup=wu, **kw)
            out["levers"][name] = r
            print(f"  [{name:34}] {r['ms_per_step']:8.2f} ms/step  {r['steps_per_s']:7.2f} st/s  "
                  f"{r['tok_per_s']:>8} tok/s  mem={r.get('mem_max_mb', 0)}MB  warmup={r['warmup_s']}s  "
                  f"finite={r['loss_finite']}", flush=True)
        except Exception as e:  # noqa: BLE001
            msg = repr(e)
            oom = "out of memory" in msg.lower()
            out["levers"][name] = {"error": msg[:300], "oom": oom}
            print(f"  [{name:34}] {'OOM' if oom else 'ERROR'} {msg[:120]}", flush=True)
        cleanup(device)
        save(out)

    # ── 3) GATE calidad A: paridad de loss (híbrido ae4, mismos datos/seed/batch) ──
    print("\n==== PARIDAD DE LOSS (ae4 híbrido, batch fijo, mismos datos) ====", flush=True)
    out["parity"] = {}
    parity_variants = [("fp32", False, None)]
    if is_cuda:
        parity_variants += [("amp_safe", True, None), ("amp_safe_compile", True, "default")]
    for tag, amp, cm in parity_variants:
        if over_budget():
            out["parity"][tag] = {"skipped": "time_budget"}
            continue
        try:
            r = parity_run(p, 4, device, amp, cm, parity_steps)
            out["parity"][tag] = r
            print(f"  [{tag:18}] final_loss={r['final_loss']} eval_acc={r['eval_acc']} wall={r['wall_s']}s", flush=True)
        except Exception as e:  # noqa: BLE001
            out["parity"][tag] = {"error": repr(e)[:300]}
            print(f"  [{tag:18}] ERROR {e!r}", flush=True)
        cleanup(device)
        save(out)
    base = out["parity"].get("fp32", {}).get("final_loss")
    if base:
        for tag in ("amp_safe", "amp_safe_compile"):
            fl = out["parity"].get(tag, {}).get("final_loss")
            if fl:
                out["parity"][f"rel_diff_{tag}"] = round(abs(fl - base) / base, 4)

    # ── 4) GATE calidad B: grokking end-to-end (la config rápida cruza el mismo recall) ──
    print("\n==== GROKKING E2E (tiny, wd=0, la config rápida debe cruzar igual) ====", flush=True)
    out["grok_quality"] = {}
    grok_variants = [("fp32", False, None)]
    if is_cuda:
        grok_variants += [("amp_safe", True, None), ("amp_safe_compile_reduce", True, "reduce-overhead")]
    for tag, amp, cm in grok_variants:
        if over_budget():
            out["grok_quality"][tag] = {"skipped": "time_budget"}
            continue
        print(f"  [{tag}]", flush=True)
        try:
            r = grok_run(grok_p, device, amp, cm, grok_steps, grok_eval,
                         log=lambda s: print(s, flush=True))
            out["grok_quality"][tag] = r
            print(f"  [{tag:24}] grok_step={r['grok_step']} best_acc={r['best_acc']} wall={r['wall_s']}s", flush=True)
        except Exception as e:  # noqa: BLE001
            out["grok_quality"][tag] = {"error": repr(e)[:300]}
            print(f"  [{tag:24}] ERROR {e!r}", flush=True)
        cleanup(device)
        save(out)

    out["minutes_total"] = round((time.time() - t_start) / 60.0, 1)
    save(out)
    print(f"\n[xspeed] LISTO en {out['minutes_total']} min. Resultados en {RESULTS_PATH}", flush=True)
    print(">>> JSON:", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

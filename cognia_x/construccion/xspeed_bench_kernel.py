r"""
XSPEED BENCH v2 — palancas de velocidad de entreno del HybridLM en Kaggle T4 (TAREA 1, ronda 2).

Ronda 1 (results_xspeed/xspeed_results_v1.json): ganador seguro = AMP fp16-seguro + gpugen + b512 +
compile + fused = 114.1k tok/s (3.13x vs fp32 36.5k). El fix fp16-SEGURO (núcleo en fp32) cuesta
13-23% y duplica memoria (b512=10.4GB, b768 OOM). CUDA-graphs a b64 rinde ~b512 (launch-bound
confirmado). Descartados con números: max-autotune, grad-ckpt, DP b1024.

Ronda 2 prueba las apuestas que salen de esos números:
  1. LinearAttention "cheap16": TODO fp16 con pre-escalado NEUTRO de q — out = (q@k^T·v)/denom es
     invariante a escalar q (numerador y denominador escalan igual), así que q *= 1/(L·sqrt(dh))
     mantiene scores y denom lejos del techo fp16 (65504, el overflow eran las SUMAS O(L·dh)) sin
     cambiar la matemática. La precisión no se degrada: los matmul fp16 acumulan en fp32 (tensor
     cores). Se VERIFICA la invariancia numérica (safe32 vs cheap16 en fp32, mismos pesos) y la
     estabilidad (NaN-watch 3000 steps en la config exacta que NaNeaba: ae4 a escala, AMP).
  2. Híbrido "fast16" = cheap16 (capas lineales) + SDPA (capas de atención) — el combo del backbone real.
  3. Fix del crash CUDA-graphs en los gates (leer float(loss) por step, no tensores stale).
  4. Gate de grokking con la config VALIDADA de m0_grok_accel (n_keys=24/n_vals=8, grokea ~3600 local);
     la v1 usó una tarea más difícil por error y nadie cruzó.
  5. DP 2xT4 a b512 (el b1024 dio OOM).

Self-contained (modelo fiel a cognia_x/model/hybrid.py + tarea de recall). Kernel "script" de Kaggle
sin internet. Resultados incrementales a xspeed_results.json.

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

RESULTS_PATH = "xspeed_results.json"
TIME_BUDGET_MIN = 75.0          # red de seguridad: pasado esto, las variantes restantes se marcan skipped

# ───────────────────────── modelo (fiel a hybrid.py, path elu) ──────────────────────────────────────


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
    """Atención lineal causal (elu+1). Modos:
      safe32  = fix canónico (núcleo en fp32 con autocast OFF; el que corre hoy en hybrid.py)
      cheap16 = núcleo fp16 con pre-escalado NEUTRO de q (invariante: numerador y denominador de
                out=(q@k^T·v)/denom escalan igual) -> sin overflow y sin pagar el upcast."""

    def __init__(self, d, n_heads, lin_mode="safe32"):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.lin_mode = lin_mode
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos=None, sin=None):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        ctx = (torch.autocast(device_type=x.device.type, enabled=False) if self.lin_mode == "safe32"
               else contextlib.nullcontext())
        with ctx:
            if self.lin_mode == "safe32":
                q, k, v = q.float(), k.float(), v.float()
            q = F.elu(q) + 1.0
            k = F.elu(k) + 1.0
            if self.lin_mode == "cheap16":
                # el overflow fp16 (>65504) venía de las sumas O(L·dh) de scores/denom, no de los
                # productos; escalar q los encoge a ambos por igual y el cociente NO cambia.
                q = q * (1.0 / (L * math.sqrt(self.dh)))
            scores = torch.matmul(q, k.transpose(-1, -2))
            mask = torch.tril(torch.ones(L, L, device=x.device, dtype=torch.bool))
            scores = scores.masked_fill(~mask, 0.0)
            denom = scores.sum(-1, keepdim=True) + 1e-6
            out = torch.matmul(scores, v) / denom
        out = out.transpose(1, 2).reshape(B, L, D).to(x.dtype)
        return self.o(out)


class SlidingWindowAttention(nn.Module):
    """Atención softmax causal con ventana W. use_sdpa=True usa F.scaled_dot_product_attention
    (kernel fusionado, +36% medido en v1; estable en fp16 sin upcast manual)."""

    def __init__(self, d, n_heads, window, use_sdpa=False):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
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
        # núcleo fp16-SEGURO (softmax con -inf en fp32); consistente con hybrid.py
        with torch.autocast(device_type=x.device.type, enabled=False):
            q, k, v = q.float(), k.float(), v.float()
            if cos is not None:
                q = apply_rope(q, cos.float(), sin.float())
                k = apply_rope(k, cos.float(), sin.float())
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
    def __init__(self, d_model, n_heads, d_ff, kind, window, lin_mode="safe32", use_sdpa=False):
        super().__init__()
        self.kind = kind
        self.norm1 = RMSNorm(d_model)
        self.mixer = (SlidingWindowAttention(d_model, n_heads, window, use_sdpa) if kind == "attn"
                      else LinearAttention(d_model, n_heads, lin_mode))
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
                 lin_mode="safe32", use_sdpa=False):
        super().__init__()
        d_ff = d_ff or max(16, int(round(8 * d_model / 3 / 16)) * 16)
        self.embed = nn.Embedding(vocab, d_model)
        self.blocks = nn.ModuleList([Block(d_model, n_heads, d_ff, t, window, lin_mode, use_sdpa)
                                     for t in layer_types])
        self.dh = d_model // n_heads
        cos, sin = build_rope_cache(max_seq_len, self.dh, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab, bias=False)
        self.lm_head.weight = self.embed.weight     # tied
        self.layer_types = layer_types
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


def build_model(p, attn_every, device, lin_mode="safe32", use_sdpa=False):
    layer_types = build_layer_types(p["n_layers"], attn_every)
    L = 2 * p["n_pairs"] + p["n_queries"]
    vocab = 1 + p["n_keys"] + p["n_vals"]
    window = L + 1
    return HybridLM(vocab, p["d_model"], p["n_heads"], layer_types, window, L + 1,
                    lin_mode=lin_mode, use_sdpa=use_sdpa).to(device)


def cleanup(device):
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def time_variant(p, attn_every, device, amp=False, gpu_gen=False, batch=None, compile_mode=None,
                 fused=False, lin_mode="safe32", sdpa=False, dp=False, steps=30, warmup=10):
    """Mide UNA config de palancas: ms/step, steps/s, tok/s, memoria pico y costo de warmup (compile)."""
    pp = dict(p)
    if batch is not None:
        pp["batch"] = batch
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    torch.manual_seed(0)
    model = build_model(pp, attn_every, device, lin_mode=lin_mode, use_sdpa=sdpa)
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


# ───────────────────────── verificaciones de la apuesta cheap16 ─────────────────────────────────────


@torch.no_grad()
def invariance_check(p, device):
    """safe32 vs cheap16 con LOS MISMOS pesos, en fp32 puro: la matemática es idéntica (el escalado
    de q se cancela en el cociente) -> la diferencia debe ser solo redondeo float."""
    torch.manual_seed(0)
    m_safe = build_model(p, 0, device, lin_mode="safe32")
    torch.manual_seed(0)
    m_cheap = build_model(p, 0, device, lin_mode="cheap16")
    m_cheap.load_state_dict(m_safe.state_dict())
    rng = np.random.default_rng(7)
    x, _ = make_recall_batch(rng, 8, p["n_pairs"], p["n_queries"], p["n_keys"], p["n_vals"], device)
    la, _ = m_safe(x)
    lb, _ = m_cheap(x)
    diff = (la - lb).abs().max().item()
    rel = diff / la.abs().max().item()
    return {"max_abs_diff": diff, "max_rel_diff": rel, "pass": rel < 1e-3}


def nan_watch(p, device, steps=3000, log=print):
    """Estabilidad de cheap16+SDPA (fast16) bajo AMP en la config exacta que NaNeaba con fp16 pleno
    (híbrido ae4 a escala, batch 64, lr 1e-3, wd 0.01, clip 1.0; el NaN original fue en step 1664)."""
    torch.manual_seed(0)
    model = build_model(p, 4, device, lin_mode="cheap16", use_sdpa=True)
    opt = torch.optim.AdamW(model.parameters(), lr=p["lr"], weight_decay=0.01)
    use_amp = device == "cuda"
    scaler = make_scaler(use_amp)
    rng = np.random.default_rng(0)
    losses, first_nan = [], None
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
        lv = float(loss.detach())
        if not math.isfinite(lv) and first_nan is None:
            first_nan = step
            log(f"    NaN/inf en step {step}")
            break
        if step % 100 == 0:
            losses.append(round(lv, 4))
    return {"steps_run": step, "first_nan_step": first_nan, "loss_every100": losses[-10:],
            "final_loss": losses[-1] if losses else None, "wall_s": round(time.time() - t0, 1)}


# ───────────────────────── gates de calidad ─────────────────────────────────────────────────────────


def parity_run(p, attn_every, device, amp, compile_mode, steps, lin_mode="safe32", sdpa=False,
               log_every=25):
    """Entrena con seed y DATOS idénticos (numpy rng CPU) y devuelve la curva de loss."""
    torch.manual_seed(0)
    model = build_model(p, attn_every, device, lin_mode=lin_mode, use_sdpa=sdpa)
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
        lv = float(loss.detach())       # leer YA (con CUDA graphs el tensor se pisa en el próximo step)
        if step % log_every == 0:
            losses.append(round(lv, 4))
    tail = losses[-4:]
    eval_rng = np.random.default_rng(999)
    acc = eval_recall(model, eval_rng, p, device, batches=12, amp=use_amp)
    return {"losses": losses, "final_loss": round(sum(tail) / len(tail), 4),
            "eval_acc": round(acc, 4), "wall_s": round(time.time() - t0, 1)}


def grok_run(p, device, amp, compile_mode, steps, eval_every, lin_mode="safe32", sdpa=False,
             target=0.8, log=print):
    """Calidad END-TO-END con la config VALIDADA de m0_grok_accel (grokea ~3600 local): la config
    rápida debe CRUZAR el recall igual que fp32. Corta al cruzar target (ese step ES el dato)."""
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    eval_rng = np.random.default_rng(10**6)
    model = build_model(p, 1, device, lin_mode=lin_mode, use_sdpa=sdpa)   # atención pura (como m0_grok_accel)
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
        lv = float(loss.detach())       # leer YA (CUDA graphs pisa el buffer en el próximo step)
        if step % eval_every == 0 or step == steps:
            acc = eval_recall(model, eval_rng, p, device, batches=8, amp=use_amp)
            best_acc = max(best_acc, acc)
            if step % (eval_every * 5) == 0:
                log(f"    step {step}/{steps} loss {lv:.3f} acc {acc:.3f}")
            if grok_step is None and acc >= target:
                grok_step = step
                log(f"    GROK en step {step} (acc {acc:.3f})")
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
    ap = argparse.ArgumentParser(description="XSPEED v2 — cheap16/fast16 + gates corregidos en T4")
    ap.add_argument("--smoke", action="store_true", help="tiny en CPU para verificar que corre")
    ap.add_argument("--steps", type=int, default=30)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    t_start = time.time()
    out = {"experiment": "xspeed_bench_v2", "device": device, "torch": torch.__version__}
    print(f"[xspeed2] torch={torch.__version__} cuda={torch.cuda.is_available()}", flush=True)
    n_gpu = 0
    if device == "cuda":
        n_gpu = torch.cuda.device_count()
        out["gpu_name"] = torch.cuda.get_device_name(0)
        out["gpu_count"] = n_gpu
    else:
        torch.set_num_threads(3)
        print("[xspeed2] CPU (smoke)", flush=True)

    if args.smoke:
        p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=64, n_vals=16, n_pairs=12,
                 n_queries=8, batch=32, lr=1e-3)
        steps, warmup, parity_steps, nan_steps = 4, 2, 30, 60
        grok_p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=24, n_vals=8, n_pairs=6,
                      n_queries=6, batch=32, lr=3e-4, wd=0.0, warmup=10)
        grok_steps, grok_eval = 60, 20
        b_hi, b_mid = 64, 48
    else:
        p = dict(d_model=256, n_heads=8, n_layers=12, n_keys=256, n_vals=32, n_pairs=32,
                 n_queries=16, batch=64, lr=1e-3)
        steps, warmup, parity_steps, nan_steps = args.steps, 10, 600, 3000
        # config VALIDADA de m0_grok_accel (grokea ~3600 local con wd=0.01; chance=0.125)
        grok_p = dict(d_model=64, n_heads=4, n_layers=4, n_keys=24, n_vals=8, n_pairs=6,
                      n_queries=6, batch=64, lr=3e-4, wd=0.0, warmup=100)
        grok_steps, grok_eval = 10000, 100
        b_hi, b_mid = 1024, 512
    out["scale"] = p
    L = 2 * p["n_pairs"] + p["n_queries"]
    print(f"[xspeed2] scale d={p['d_model']} layers={p['n_layers']} batch={p['batch']} L={L}", flush=True)

    def over_budget():
        return (time.time() - t_start) / 60.0 > TIME_BUDGET_MIN

    # ── 0) INVARIANCIA cheap16 (mismos pesos, fp32: la diferencia debe ser redondeo) ──
    out["invariance"] = invariance_check(p, device)
    print(f"[xspeed2] invariancia cheap16: rel={out['invariance']['max_rel_diff']:.2e} "
          f"pass={out['invariance']['pass']}", flush=True)
    save(out)
    cleanup(device)

    # ── 1) MATRIZ DE PALANCAS v2 ──
    print("\n==== PALANCAS v2 ====", flush=True)
    is_cuda = device == "cuda"
    variants = [
        ("baseline_fp32_b64",             0, dict()),                                            # ref v1
        ("cheap16_amp_b64",               0, dict(amp=True, lin_mode="cheap16")),                # vs safe 59k / unsafe 68k
        ("cheap16_amp_gpugen_bmid",       0, dict(amp=True, gpu_gen=True, batch=b_mid, lin_mode="cheap16")),
    ]
    if is_cuda:
        variants += [
            ("safe_bmid_compile_fused",       0, dict(amp=True, gpu_gen=True, batch=b_mid, compile_mode="default", fused=True)),
            ("safe_bmid_reduce_fused",        0, dict(amp=True, gpu_gen=True, batch=b_mid, compile_mode="reduce-overhead", fused=True)),  # ganador v1
            ("cheap16_bmid_compile_fused",    0, dict(amp=True, gpu_gen=True, batch=b_mid, compile_mode="default", fused=True, lin_mode="cheap16")),
            ("cheap16_bmid_reduce_fused",     0, dict(amp=True, gpu_gen=True, batch=b_mid, compile_mode="reduce-overhead", fused=True, lin_mode="cheap16")),
            ("cheap16_bhi_reduce_fused",      0, dict(amp=True, gpu_gen=True, batch=b_hi, compile_mode="reduce-overhead", fused=True, lin_mode="cheap16")),
            ("ae4_safe_bmid_reduce_fused",    4, dict(amp=True, gpu_gen=True, batch=b_mid, compile_mode="reduce-overhead", fused=True)),
            ("ae4_fast16_bmid_reduce_fused",  4, dict(amp=True, gpu_gen=True, batch=b_mid, compile_mode="reduce-overhead", fused=True, lin_mode="cheap16", sdpa=True)),
        ]
    if is_cuda and n_gpu >= 2:
        variants += [
            ("dp2_safe_bmid",             0, dict(amp=True, gpu_gen=True, batch=b_mid, dp=True)),
            ("dp2_cheap16_bhi",           0, dict(amp=True, gpu_gen=True, batch=b_hi, dp=True, lin_mode="cheap16")),
        ]
    out["levers"] = {}
    for name, ae, kw in variants:
        if over_budget():
            out["levers"][name] = {"skipped": "time_budget"}
            print(f"  [{name:34}] SKIPPED (budget)", flush=True)
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

    # ── 2) NaN-WATCH: fast16 en la config que NaNeaba (ae4 a escala, AMP, 3000 steps) ──
    print("\n==== NaN-WATCH fast16 (ae4, AMP, config del NaN original step 1664) ====", flush=True)
    try:
        out["nan_watch_fast16"] = nan_watch(p, device, steps=nan_steps, log=lambda s: print(s, flush=True))
        print(f"  steps={out['nan_watch_fast16']['steps_run']} first_nan={out['nan_watch_fast16']['first_nan_step']} "
              f"final_loss={out['nan_watch_fast16']['final_loss']}", flush=True)
    except Exception as e:  # noqa: BLE001
        out["nan_watch_fast16"] = {"error": repr(e)[:300]}
    cleanup(device)
    save(out)

    # ── 3) GATE calidad A: paridad de loss (ae4 híbrido, mismos datos/seed/batch) ──
    print("\n==== PARIDAD DE LOSS (ae4, batch fijo, mismos datos) ====", flush=True)
    out["parity"] = {}
    parity_variants = [("fp32", False, None, "safe32", False)]
    if is_cuda:
        parity_variants += [
            ("amp_safe", True, None, "safe32", False),
            ("amp_fast16", True, None, "cheap16", True),
            ("amp_fast16_compile", True, "default", "cheap16", True),
        ]
    for tag, amp, cm, lm, sd in parity_variants:
        if over_budget():
            out["parity"][tag] = {"skipped": "time_budget"}
            continue
        try:
            r = parity_run(p, 4, device, amp, cm, parity_steps, lin_mode=lm, sdpa=sd)
            out["parity"][tag] = r
            print(f"  [{tag:20}] final_loss={r['final_loss']} eval_acc={r['eval_acc']} wall={r['wall_s']}s", flush=True)
        except Exception as e:  # noqa: BLE001
            out["parity"][tag] = {"error": repr(e)[:300]}
            print(f"  [{tag:20}] ERROR {e!r}", flush=True)
        cleanup(device)
        save(out)
    base = out["parity"].get("fp32", {}).get("final_loss")
    if base:
        for tag in ("amp_safe", "amp_fast16", "amp_fast16_compile"):
            fl = out["parity"].get(tag, {}).get("final_loss")
            if fl:
                out["parity"][f"rel_diff_{tag}"] = round(abs(fl - base) / base, 4)

    # ── 4) GATE calidad B: grokking e2e con la config VALIDADA (m0_grok_accel) ──
    print("\n==== GROKKING E2E (config m0_grok_accel: n_keys=24/n_vals=8, ~3600 local) ====", flush=True)
    out["grok_quality"] = {}
    grok_variants = [("fp32", False, None, "safe32", False)]
    if is_cuda:
        grok_variants += [
            ("amp_safe", True, None, "safe32", False),
            ("amp_fast16", True, None, "cheap16", True),
            ("amp_fast16_compile_reduce", True, "reduce-overhead", "cheap16", True),
        ]
    for tag, amp, cm, lm, sd in grok_variants:
        if over_budget():
            out["grok_quality"][tag] = {"skipped": "time_budget"}
            continue
        print(f"  [{tag}]", flush=True)
        try:
            r = grok_run(grok_p, device, amp, cm, grok_steps, grok_eval, lin_mode=lm, sdpa=sd,
                         log=lambda s: print(s, flush=True))
            out["grok_quality"][tag] = r
            print(f"  [{tag:26}] grok_step={r['grok_step']} best_acc={r['best_acc']} wall={r['wall_s']}s", flush=True)
        except Exception as e:  # noqa: BLE001
            out["grok_quality"][tag] = {"error": repr(e)[:300]}
            print(f"  [{tag:26}] ERROR {e!r}", flush=True)
        cleanup(device)
        save(out)

    out["minutes_total"] = round((time.time() - t_start) / 60.0, 1)
    save(out)
    print(f"\n[xspeed2] LISTO en {out['minutes_total']} min. Resultados en {RESULTS_PATH}", flush=True)
    print(">>> JSON:", flush=True)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

r"""
XH-BENCH (K1) — gates de ingeniería de 00_DISENO.md §4.6, ANTES de gastar brazos K2:
  1. tok/s batch {32,48,64} + VRAM pico → fija batch y el MFU real del 110M.
  2. Newton-Schulz de Muon en fp16: invariancia vs fp32 + overhead <10% del step (gate R1).
  3. Warmup de compile medido (gate <3 min).
  4. Paridad de loss fp16 vs fp32 (250 steps, mismo seed/datos, gate ≤1%) + skips del scaler <1%.
  5. bf16 100 steps: cerrar el descarte aritmético con número (SM75 sin tensor cores bf16).
  6. Test unitario: AMBOS param_groups (Muon+AdamW) decaen con el schedule (bug R8).

Modelo = receta v1 EXACTA (§4): d=768 12L 12H SwiGLU-2048, banded 3:1 w=256 (globals is_causal,
máscara-buffer), RoPE, QK-norm, zero-init o_proj/w3, z-loss 1e-4 fp32, CE chunked ×4, tied 32k.
Consume el output de cognia-xh-data. Salida: xh_bench_results.json.
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_bench_kernel.py --smoke
"""
import argparse
import gc
import json
import math
import os
import time

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")  # anti-fragmentación T4

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS_PATH = "xh_bench_results.json"


def find_data_dir():
    """El mount de kernel_sources no siempre cae en /kaggle/input/<slug> — descubrir en runtime."""
    base = "/kaggle/input"
    try:
        print(f"[data] /kaggle/input: {os.listdir(base)}", flush=True)
    except OSError:
        pass
    for root, _dirs, files in os.walk(base):
        if "xh_data_meta.json" in files:
            print(f"[data] dir: {root}", flush=True)
            return root
    raise FileNotFoundError("xh_data_meta.json no está bajo /kaggle/input (¿attach falló?)")
TIME_BUDGET_MIN = 38.0
T4_PEAK_FP16 = 65e12
T4_PEAK_FP32 = 8.1e12

ARCH_D = 768
ARCH_HEADS = 12
ARCH_LAYERS = 12
ARCH_WINDOW = 256
GLOBAL_LAYERS = (3, 7, 11)
SEQ = 512
MUON_LR = 0.02
ADAMW_LR = 3e-3
ZLOSS = 1e-4
WARMUP_STEPS = 200


# ───────────────────────── modelo v1 (fuente canónica para K2/K3) ─────────────────────────


def build_rope_cache(seq_len, dh, base=10000.0):
    half = dh // 2
    inv_freq = 1.0 / (base ** (torch.arange(0, half).float() / half))
    pos = torch.arange(seq_len).float()
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
    def __init__(self, d, n_heads, window=None):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)
        self.q_norm = RMSNorm(self.dh)     # QK-norm (§4.1): habilita el régimen de LR agresivo
        self.k_norm = RMSNorm(self.dh)

    def forward(self, x, cos, sin, mask):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = apply_rope(self.q_norm(q), cos, sin)
        k = apply_rope(self.k_norm(k), cos, sin)
        if mask is None:
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.o(out.transpose(1, 2).reshape(B, L, D))


class Block(nn.Module):
    def __init__(self, d, n_heads, d_ff, window=None):
        super().__init__()
        self.norm1 = RMSNorm(d)
        self.attn = Attn(d, n_heads, window)
        self.norm2 = RMSNorm(d)
        self.mlp = SwiGLU(d, d_ff)

    def forward(self, x, cos, sin, mask):
        x = x + self.attn(self.norm1(x), cos, sin, mask)
        x = x + self.mlp(self.norm2(x))
        return x


class XHLM(nn.Module):
    """Receta v1: banded 3:1 (globals en GLOBAL_LAYERS con is_causal), QK-norm, zero-init
    o_proj/w3, tied head, CE chunked ×4 + z-loss fp32 (logits 32k nunca materializados enteros)."""

    def __init__(self, vocab, d=ARCH_D, n_heads=ARCH_HEADS, n_layers=ARCH_LAYERS,
                 window=ARCH_WINDOW, global_layers=GLOBAL_LAYERS, d_ff=None, max_seq=2048):
        super().__init__()
        d_ff = d_ff or max(64, int(round(8 * d / 3 / 64)) * 64)
        windows = [None if i in global_layers else window for i in range(n_layers)]
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w) for w in windows])
        self.layer_windows = windows
        self.dh = d // n_heads
        self.max_seq = max_seq
        cos, sin = build_rope_cache(max_seq, self.dh)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init)
        for b in self.blocks:                      # ZERO-init (§4.2): arranque ≈identidad
            nn.init.zeros_(b.attn.o.weight)
            nn.init.zeros_(b.mlp.w3.weight)
        for w in sorted({w for w in windows if w is not None}):
            idx = torch.arange(max_seq)
            m = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - w))
            self.register_buffer(f"mask_{w}", m, persistent=False)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def _ce_chunk(self, xc, tc):
        lg = self.lm_head(xc).float()
        return (F.cross_entropy(lg, tc, reduction="sum"),
                (torch.logsumexp(lg, dim=-1) ** 2).sum())

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos = self.rope_cos[:L].to(x.dtype)
        sin = self.rope_sin[:L].to(x.dtype)
        for b, w in zip(self.blocks, self.layer_windows):
            mask = None if (w is None or w >= L) else getattr(self, f"mask_{w}")[:L, :L]
            x = b(x, cos, sin, mask)
        x = self.norm_f(x)
        if targets is None:
            return self.lm_head(x), None, None
        xf = x.reshape(-1, x.shape[-1])
        tf = targets.reshape(-1)
        n = xf.shape[0]
        ce = xf.new_zeros((), dtype=torch.float32)
        zl = xf.new_zeros((), dtype=torch.float32)
        for i in range(4):
            # CE chunked ×4. SIN checkpoint: compile+checkpoint OOMeó a b48 donde el no-checkpoint
            # corría a 13.08GB (medido K1 v2 vs v3) — AOTAutograd+AC retiene MÁS, no menos.
            sl = slice(i * n // 4, (i + 1) * n // 4)
            ce_i, zl_i = self._ce_chunk(xf[sl], tf[sl])
            ce = ce + ce_i
            zl = zl + zl_i
        ce = ce / n
        total = ce + ZLOSS * (zl / n)               # z-loss fp32 (§4.2)
        return None, ce, total

    def num_params(self):
        total = sum(p.numel() for p in self.parameters())
        return total, total - self.embed.weight.numel()


# ───────────────────────── Muon + schedule (fuente canónica para K2/K3) ─────────────────────────


@torch.no_grad()
def ns5(G, steps=5, eps=1e-7, dtype=torch.float16):
    """Newton-Schulz quintic. dtype=fp16 usa tensor cores en T4 (gate K1-2 valida invariancia)."""
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.to(dtype)
    X = X / (X.norm() + eps)
    transposed = X.size(0) > X.size(1)
    if transposed:
        X = X.mT
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * A @ A
        X = a * X + B @ X
    if transposed:
        X = X.mT
    return X


class Muon(torch.optim.Optimizer):
    """Muon (speedrun 124M; Moonlight 3B/16B = escalable). Solo matrices 2D ocultas;
    momentum fp32, NS en fp16 (§4.3). LR 0.02, nesterov 0.95, wd 0."""

    def __init__(self, params, lr=MUON_LR, momentum=0.95, nesterov=True,
                 weight_decay=0.0, ns_dtype=torch.float16):
        super().__init__(params, dict(lr=lr, momentum=momentum, nesterov=nesterov,
                                      weight_decay=weight_decay))
        self.ns_dtype = ns_dtype

    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            lr, mu, wd = group["lr"], group["momentum"], group["weight_decay"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                st = self.state[p]
                if "buf" not in st:
                    st["buf"] = torch.zeros_like(g, dtype=torch.float32)
                buf = st["buf"]
                buf.mul_(mu).add_(g)
                gg = g.add(buf, alpha=mu) if group["nesterov"] else buf
                O = ns5(gg.reshape(gg.size(0), -1), dtype=self.ns_dtype).reshape_as(gg).to(p.dtype)
                if wd:
                    p.mul_(1 - lr * wd)
                p.add_(O, alpha=-lr * max(1, p.size(0) / p.size(1)) ** 0.5)


def make_v1_optimizers(model, device, muon_lr=MUON_LR, adamw_lr=ADAMW_LR):
    """Muon en matrices 2D ocultas; AdamW fused en emb tied + norms/gains (wd 0 en 1D)."""
    body2d, emb, oned = [], [], []
    for n, p in model.named_parameters():
        if "embed" in n or "lm_head" in n:
            emb.append(p)
        elif p.ndim >= 2:
            body2d.append(p)
        else:
            oned.append(p)
    muon = Muon(body2d, lr=muon_lr, momentum=0.95, weight_decay=0.0)
    fused = device == "cuda"
    adamw = torch.optim.AdamW(
        [{"params": emb, "weight_decay": 0.01}, {"params": oned, "weight_decay": 0.0}],
        lr=adamw_lr, betas=(0.9, 0.95), fused=fused or None)
    return muon, adamw, [muon_lr, adamw_lr]


def lr_factor(step, progress):
    """Warmup 200 steps → constante → decay lineal a 0 en el último 20% del wall (WSD, §4.3).
    Factor COMPARTIDO por ambos grupos (gate K1-6 lo verifica)."""
    if step <= WARMUP_STEPS:
        return step / WARMUP_STEPS
    if progress >= 0.8:
        return max(0.0, (1.0 - progress) / 0.2)
    return 1.0


def set_lrs(opts, base_lrs, factor):
    for opt, base in zip(opts, base_lrs):
        for gr in opt.param_groups:
            gr["lr"] = base * factor


# ───────────────────────── datos / harness ─────────────────────────


def load_tokens(smoke, device):
    if smoke:
        g = torch.Generator().manual_seed(0)
        return torch.randint(0, 500, (300_000,), generator=g).to(torch.int32).to(device), 512
    data_dir = find_data_dir()
    arr = np.fromfile(f"{data_dir}/train_mix_32k.bin", dtype=np.uint16)
    meta = json.loads(open(f"{data_dir}/xh_data_meta.json", encoding="utf-8").read())
    vocab = meta["vocabs"]["32k"]["vocab_size"]
    print(f"[data] {len(arr):,} tokens mezcla (vocab {vocab})", flush=True)
    return torch.from_numpy(arr.astype(np.int32)).to(device), vocab


def make_step_fn(model, data, opts, scaler, batch, seq, device, g, use_amp):
    arange = torch.arange(seq, device=device, dtype=torch.int32)

    def step():
        starts = torch.randint(0, len(data) - seq - 1, (batch,), generator=g,
                               device=device, dtype=torch.int32)
        idx = starts[:, None] + arange[None, :]
        x, y = data[idx].long(), data[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=use_amp):
            _, ce, total = model(x, y)
        for o in opts:
            o.zero_grad(set_to_none=True)
        scaler.scale(total).backward()
        for o in opts:
            scaler.unscale_(o)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        for o in opts:
            scaler.step(o)
        scaler.update()
        return ce.detach()

    return step


def hard_cleanup(device):
    """Suelta cachés de dynamo (retienen VRAM tras un OOM — lección K1 v2) + allocator."""
    torch._dynamo.reset()
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()


def bench_arm(name, data, vocab, device, batch, opt_kind="adamw", use_amp=True,
              compile_=True, n_steps=100, seq=SEQ, smoke=False, amp_dtype=torch.float16):
    hard_cleanup(device)
    torch.manual_seed(0)
    kw = dict(d=64, n_heads=4, n_layers=2, global_layers=(1,)) if smoke else {}
    model = XHLM(vocab, **kw).to(device)
    total, nonemb = model.num_params()
    if compile_ and not smoke:
        model = torch.compile(model, mode="default", fullgraph=True, dynamic=False)
    if opt_kind == "muon":
        muon, adamw, _ = make_v1_optimizers(model, device)
        opts = [muon, adamw]
    else:
        opts = [torch.optim.AdamW(model.parameters(), lr=1.5e-3, betas=(0.9, 0.95),
                                  weight_decay=0.1, fused=(device == "cuda") or None)]
    scaler = torch.amp.GradScaler(device, enabled=use_amp and device == "cuda")
    g = torch.Generator(device=device)
    g.manual_seed(0)
    arange = torch.arange(seq, device=device, dtype=torch.int32)

    def step():
        starts = torch.randint(0, len(data) - seq - 1, (batch,), generator=g,
                               device=device, dtype=torch.int32)
        idx = starts[:, None] + arange[None, :]
        x, y = data[idx].long(), data[idx + 1].long()
        with torch.autocast(device_type=device, dtype=amp_dtype,
                            enabled=use_amp and device == "cuda"):
            _, ce, tot = model(x, y)
        for o in opts:
            o.zero_grad(set_to_none=True)
        scaler.scale(tot).backward()
        for o in opts:
            scaler.unscale_(o)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        for o in opts:
            scaler.step(o)
        scaler.update()
        return ce.detach()

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    loss0 = float(step())
    warmup_s = time.time() - t0
    for _ in range(9 if not smoke else 2):
        step()
    if device == "cuda":
        torch.cuda.synchronize()
    t1 = time.time()
    n = n_steps if not smoke else 3
    last = loss0
    for _ in range(n):
        last = step()
    if device == "cuda":
        torch.cuda.synchronize()
    dt = time.time() - t1
    last = float(last)
    tps = batch * seq * n / dt
    mfu = tps * 6 * total / (T4_PEAK_FP16 if use_amp else T4_PEAK_FP32)
    vram = torch.cuda.max_memory_allocated() / 1e9 if device == "cuda" else 0.0
    res = {"name": name, "batch": batch, "opt": opt_kind, "amp": use_amp, "compile": compile_,
           "params_total": total, "params_nonemb": nonemb,
           "ms_per_step": round(dt / n * 1000, 1), "tok_per_s": round(tps),
           "mfu_approx": round(mfu, 3), "vram_gb": round(vram, 2),
           "compile_warmup_s": round(warmup_s, 1), "loss_first": round(loss0, 4),
           "loss_last": round(last, 4), "loss_finite": math.isfinite(last),
           "scaler_scale": float(scaler.get_scale()) if scaler.is_enabled() else None}
    print(f"[{name}] {res['tok_per_s']:,} tok/s MFU~{mfu:.2f} VRAM {vram:.1f}GB "
          f"warmup {warmup_s:.0f}s loss {loss0:.3f}->{last:.3f}", flush=True)
    del model, opts
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return res


def parity_gate(data, vocab, device, batch=16, n_steps=250, smoke=False):
    """fp16 vs fp32, mismo seed/datos → diff relativa de loss final ≤1% (método XSPEED).
    b16: el fp32 duplica activaciones — a b32 reventaba la T4 (OOM de K1 v2)."""
    finals = {}
    for tag, amp in (("fp32", False), ("fp16", True)):
        hard_cleanup(device)
        torch.manual_seed(0)
        kw = dict(d=64, n_heads=4, n_layers=2, global_layers=(1,)) if smoke else {}
        model = XHLM(vocab, **kw).to(device)
        muon, adamw, base_lrs = make_v1_optimizers(model, device)
        opts = [muon, adamw]
        scaler = torch.amp.GradScaler(device, enabled=amp and device == "cuda")
        g = torch.Generator(device=device)
        g.manual_seed(0)
        seq = SEQ if not smoke else 64
        arange = torch.arange(seq, device=device, dtype=torch.int32)
        n = n_steps if not smoke else 5
        skips = 0
        last = None
        for s in range(1, n + 1):
            set_lrs(opts, base_lrs, lr_factor(s, s / n * 0.5))
            starts = torch.randint(0, len(data) - seq - 1, (batch if not smoke else 4,),
                                   generator=g, device=device, dtype=torch.int32)
            idx = starts[:, None] + arange[None, :]
            x, y = data[idx].long(), data[idx + 1].long()
            with torch.autocast(device_type=device, dtype=torch.float16,
                                enabled=amp and device == "cuda"):
                _, ce, tot = model(x, y)
            for o in opts:
                o.zero_grad(set_to_none=True)
            scale_before = scaler.get_scale() if scaler.is_enabled() else 1.0
            scaler.scale(tot).backward()
            for o in opts:
                scaler.unscale_(o)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            for o in opts:
                scaler.step(o)
            scaler.update()
            if scaler.is_enabled() and scaler.get_scale() < scale_before:
                skips += 1
            last = float(ce.detach())
        finals[tag] = {"loss": last, "skips": skips}
        print(f"[parity-{tag}] loss@{n}={last:.4f} skips={skips}", flush=True)
        del model, opts
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
    rel = abs(finals["fp16"]["loss"] - finals["fp32"]["loss"]) / max(1e-9, finals["fp32"]["loss"])
    n_total = n_steps if not smoke else 5
    return {"fp32": finals["fp32"], "fp16": finals["fp16"], "rel_diff": round(rel, 5),
            "pass": rel <= 0.01 and finals["fp16"]["skips"] / n_total <= 0.01}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    torch.backends.cudnn.benchmark = True
    t0 = time.time()
    out = {"experiment": "xh_bench_v2", "device": device, "torch": torch.__version__,
           "gates": {}, "arms": []}

    # gate 6 — schedule sobre AMBOS grupos (unit test sin GPU)
    tiny = XHLM(64, d=32, n_heads=2, n_layers=2, global_layers=(1,))
    muon, adamw, base_lrs = make_v1_optimizers(tiny, "cpu")
    set_lrs([muon, adamw], base_lrs, lr_factor(WARMUP_STEPS + 1, 0.9))
    f_expected = lr_factor(WARMUP_STEPS + 1, 0.9)
    ok6 = (abs(muon.param_groups[0]["lr"] - base_lrs[0] * f_expected) < 1e-12
           and all(abs(gr["lr"] - base_lrs[1] * f_expected) < 1e-12 for gr in adamw.param_groups))
    out["gates"]["g6_dual_schedule"] = {"factor": f_expected, "pass": bool(ok6)}
    print(f"[gate6] dual-optimizer schedule: {'PASS' if ok6 else 'FAIL'}", flush=True)
    del tiny, muon, adamw

    # gate 2a — invariancia NS fp16 vs fp32 (matrices con forma real)
    torch.manual_seed(1)
    inv = []
    for shape in ((2304, 768), (2048, 768), (768, 2048)):
        Gm = torch.randn(shape, device=device) * 0.02
        o16 = ns5(Gm, dtype=torch.float16).float()
        o32 = ns5(Gm, dtype=torch.float32).float()
        rel = float((o16 - o32).norm() / (o32.norm() + 1e-9))
        inv.append({"shape": list(shape), "rel_diff": round(rel, 5)})
    max_rel = max(i["rel_diff"] for i in inv)
    out["gates"]["g2a_ns_invariance"] = {"shapes": inv, "max_rel_diff": max_rel,
                                         "pass": max_rel < 0.05}
    print(f"[gate2a] NS fp16 invariancia: max_rel={max_rel:.4f} "
          f"{'PASS' if max_rel < 0.05 else 'FAIL'}", flush=True)

    data, vocab = load_tokens(args.smoke, device)
    loss_ini_esperada = math.log(vocab)
    out["arch"] = {"d": ARCH_D, "layers": ARCH_LAYERS, "vocab": vocab,
                   "ln_vocab": round(loss_ini_esperada, 2)}

    # gate 1 — batch sweep (orden por prioridad: si algo OOMea, lo crítico ya corrió)
    arms = [
        ("adamw_b48_compile", 48, "adamw", True, True),
        ("muon_b48_compile", 48, "muon", True, True),      # gate 2b: overhead NS vs adamw_b48
        ("bf16_b48_nocompile", 48, "adamw", True, False),  # gate 5: número del descarte bf16
        ("adamw_b32_nocompile", 32, "adamw", True, False),
    ]                                                       # b64: OOM probado en K1 v2 — fuera
    if args.smoke:
        arms = [("smoke_adamw", 4, "adamw", False, False),
                ("smoke_muon", 4, "muon", False, False)]
    for name, b, ok, amp, comp in arms:
        if (time.time() - t0) / 60 > TIME_BUDGET_MIN:
            print("[bench] BUDGET — corto", flush=True)
            break
        dtype = torch.bfloat16 if name.startswith("bf16") else torch.float16
        try:
            out["arms"].append(bench_arm(name, data, vocab, device, b, opt_kind=ok,
                                         use_amp=amp, compile_=comp, smoke=args.smoke,
                                         amp_dtype=dtype))
        except torch.cuda.OutOfMemoryError as e:
            peak = torch.cuda.max_memory_allocated() / 1e9
            print(f"[{name}] OOM (pico {peak:.2f}GB): {str(e)[:200]}", flush=True)
            out["arms"].append({"name": name, "oom": True, "peak_gb": round(peak, 2),
                                "msg": str(e)[:200]})
            hard_cleanup(device)
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    byname = {a["name"]: a for a in out["arms"] if not a.get("oom")}
    if "muon_b48_compile" in byname and "adamw_b48_compile" in byname:
        t_m = byname["muon_b48_compile"]["ms_per_step"]
        t_a = byname["adamw_b48_compile"]["ms_per_step"]
        ov = (t_m - t_a) / t_a
        out["gates"]["g2b_ns_overhead"] = {"muon_ms": t_m, "adamw_ms": t_a,
                                           "overhead": round(ov, 4), "pass": ov < 0.10}
        print(f"[gate2b] overhead Muon: {ov * 100:.1f}% {'PASS' if ov < 0.10 else 'FAIL'}", flush=True)
    warm = [a.get("compile_warmup_s", 0) for a in out["arms"] if a.get("compile")]
    if warm:
        out["gates"]["g3_compile_warmup"] = {"max_s": max(warm), "pass": max(warm) < 180}
        print(f"[gate3] compile warmup max {max(warm):.0f}s "
              f"{'PASS' if max(warm) < 180 else 'FAIL'}", flush=True)

    # gate 4 — paridad fp16 vs fp32 con la receta v1 (Muon+AdamW, LRs reales)
    if (time.time() - t0) / 60 < TIME_BUDGET_MIN:
        try:
            out["gates"]["g4_parity"] = parity_gate(data, vocab, device, smoke=args.smoke)
            print(f"[gate4] paridad: {out['gates']['g4_parity']}", flush=True)
        except torch.cuda.OutOfMemoryError:
            out["gates"]["g4_parity"] = {"oom": True, "pass": False}
            print("[gate4] OOM", flush=True)
            hard_cleanup(device)

    ok_arms = [a for a in out["arms"] if a.get("tok_per_s") and a.get("loss_finite")
               and not a["name"].startswith("bf16")]
    if ok_arms:
        best = max(ok_arms, key=lambda a: a["tok_per_s"])
        out["best"] = {"name": best["name"], "batch": best["batch"],
                       "tok_per_s": best["tok_per_s"],
                       "tokens_in_25min": int(best["tok_per_s"] * 1500),
                       "mfu": best["mfu_approx"]}
        print(f"[bench] MEJOR: {best['name']} {best['tok_per_s']:,} tok/s "
              f"(MFU {best['mfu_approx']:.2f}) -> {out['best']['tokens_in_25min']:,} tok/25min",
              flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[xh-bench] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()

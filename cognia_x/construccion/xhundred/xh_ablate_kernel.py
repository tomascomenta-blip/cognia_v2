r"""
XH-ABLATE (K2) — brazos pre-registrados de 00_DISENO.md §5, a IGUAL WALL-CLOCK (12 min de train
por brazo; la comparación es a mismo reloj, NUNCA a mismo step). Consume cognia-xh-data.

Brazos (orden = prioridad; si el budget corta, caen los últimos):
  v1_muon      receta v1 completa + free-rider W (eval last vs EMA-0.998 vs LAWA-k5)
  A_adamw_ctl  control: AdamW único LR 1.5e-3 wd 0.1 TUNEADO (mismo WSD/QK-norm/init)
  D_byte256    vocab 256 (train_bytes.bin) — byte-vs-BPE, la decisión más estructural
  G_wiki_solo  100% wiki (train_wiki_32k.bin) — ¿la mezcla con cuentos paga?
  E_bpe16k     vocab 16,384
  C_muon_lr04  Muon LR 0.04
  F_8Lx1024    8L × d=1024 × 16H, d_ff 2048 (~117M) — forma
  H_attn micro 150 steps × {buffer-mask, causal-full, chunked-SWA} + gate de extrapolación

Métrica primaria: val bpb WIKI held-out normalizado por BYTES (cruces de vocab comparables):
bpb = CE_nats/token × (val_tokens/val_bytes) / ln2. Secundaria: bpb cuentos, muestras, distinct-2.
NaN = el brazo muere y queda registrado. Salida: xh_ablate_results.json (guardado incremental).
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_ablate_kernel.py --smoke
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

RESULTS_PATH = "xh_ablate_results.json"
_DATA_DIR_CACHE = []


def find_data_dir():
    """El mount de kernel_sources no siempre cae en /kaggle/input/<slug> — descubrir en runtime."""
    if _DATA_DIR_CACHE:
        return _DATA_DIR_CACHE[0]
    base = "/kaggle/input"
    try:
        print(f"[data] /kaggle/input: {os.listdir(base)}", flush=True)
    except OSError:
        pass
    for root, _dirs, files in os.walk(base):
        if "xh_data_meta.json" in files:
            print(f"[data] dir: {root}", flush=True)
            _DATA_DIR_CACHE.append(root)
            return root
    raise FileNotFoundError("xh_data_meta.json no está bajo /kaggle/input (¿attach falló?)")


TIME_BUDGET_MIN = 150.0
TRAIN_WALL_S = 720.0
EVAL_EVERY_S = 120.0

ARCH_D = 768
ARCH_HEADS = 12
ARCH_LAYERS = 12
ARCH_WINDOW = 256
GLOBAL_LAYERS = (3, 7, 11)
SEQ = 512
BASE_BATCH = 48                  # <- confirmar con xh_bench_results.json antes de pushear
BASE_COMPILE = True
MUON_LR = 0.02
ADAMW_LR = 3e-3
ZLOSS = 1e-4
WARMUP_STEPS = 200
EMA_DECAY = 0.998
GEN_PROMPTS = ("Había una vez un niño que ", "La historia de ")

ARMS = [
    {"name": "v1_muon", "free_rider": True},
    {"name": "A_adamw_ctl", "opt": "adamw_ctl"},
    {"name": "D_byte256", "data": "bytes"},
    {"name": "G_wiki_solo", "data": "wiki"},
    {"name": "E_bpe16k", "data": "16k"},
    {"name": "C_muon_lr04", "muon_lr": 0.04},
    {"name": "F_8Lx1024", "shape": {"d": 1024, "heads": 16, "layers": 8,
                                    "d_ff": 2048, "globals": (3, 7)}},
]


# ───────────────────────── modelo v1 (canónico de xh_bench_kernel + attn_mode + generate) ──────────


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


def chunked_swa(q, k, v, w):
    """SWA de ventana EXACTA w por bloques (2 bloques de k/v por query-block). Matemática
    idéntica a la máscara banded (assert al inicio); candidata por velocidad (00_DISENO §5-H)."""
    B, h, L, dh = q.shape
    nb = L // w
    qb = q.view(B, h, nb, w, dh).transpose(1, 2).reshape(B * nb, h, w, dh)
    kb = k.view(B, h, nb, w, dh)
    vb = v.view(B, h, nb, w, dh)
    kprev = torch.cat([torch.zeros_like(kb[:, :, :1]), kb[:, :, :-1]], dim=2)
    vprev = torch.cat([torch.zeros_like(vb[:, :, :1]), vb[:, :, :-1]], dim=2)
    kk = torch.cat([kprev, kb], dim=3).transpose(1, 2).reshape(B * nb, h, 2 * w, dh)
    vv = torch.cat([vprev, vb], dim=3).transpose(1, 2).reshape(B * nb, h, 2 * w, dh)
    i = torch.arange(w, device=q.device)
    m = torch.arange(2 * w, device=q.device)
    base = (m[None, :] > i[:, None]) & (m[None, :] <= w + i[:, None])   # ventana exacta w
    m0 = base & (m[None, :] >= w)                                        # bloque 0: sin keys virtuales
    mask = torch.stack([m0] + [base] * (nb - 1)).repeat(B, 1, 1)         # (B·nb, w, 2w)
    out = F.scaled_dot_product_attention(qb, kk, vv, attn_mask=mask[:, None, :, :])
    return out.view(B, nb, h, w, dh).transpose(1, 2).reshape(B, h, L, dh)


class Attn(nn.Module):
    def __init__(self, d, n_heads, window=None, attn_mode="mask"):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.attn_mode = attn_mode
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)
        self.q_norm = RMSNorm(self.dh)
        self.k_norm = RMSNorm(self.dh)

    def forward(self, x, cos, sin, mask):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = apply_rope(self.q_norm(q), cos, sin)
        k = apply_rope(self.k_norm(k), cos, sin)
        if (self.window is not None and self.attn_mode == "chunked"
                and L % self.window == 0 and L > self.window):
            out = chunked_swa(q, k, v, self.window)
        elif mask is None:
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:
            out = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        return self.o(out.transpose(1, 2).reshape(B, L, D))


class Block(nn.Module):
    def __init__(self, d, n_heads, d_ff, window=None, attn_mode="mask"):
        super().__init__()
        self.norm1 = RMSNorm(d)
        self.attn = Attn(d, n_heads, window, attn_mode)
        self.norm2 = RMSNorm(d)
        self.mlp = SwiGLU(d, d_ff)

    def forward(self, x, cos, sin, mask):
        x = x + self.attn(self.norm1(x), cos, sin, mask)
        x = x + self.mlp(self.norm2(x))
        return x


class XHLM(nn.Module):
    def __init__(self, vocab, d=ARCH_D, n_heads=ARCH_HEADS, n_layers=ARCH_LAYERS,
                 window=ARCH_WINDOW, global_layers=GLOBAL_LAYERS, d_ff=None,
                 attn_mode="mask", max_seq=2048):
        super().__init__()
        d_ff = d_ff or max(64, int(round(8 * d / 3 / 64)) * 64)
        if attn_mode == "causal_full":
            windows = [None] * n_layers
        else:
            windows = [None if i in global_layers else window for i in range(n_layers)]
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w, attn_mode) for w in windows])
        self.layer_windows = windows
        self.attn_mode = attn_mode
        self.dh = d // n_heads
        self.max_seq = max_seq
        cos, sin = build_rope_cache(max_seq, self.dh)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init)
        for b in self.blocks:
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

    def set_rope_base(self, base):
        """NTK en EVAL: recompute in-place (misma identidad de buffer → sin recompile)."""
        cos, sin = build_rope_cache(self.max_seq, self.dh, base=base)
        self.rope_cos.copy_(cos.to(self.rope_cos.device))
        self.rope_sin.copy_(sin.to(self.rope_sin.device))

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos = self.rope_cos[:L].to(x.dtype)
        sin = self.rope_sin[:L].to(x.dtype)
        for b, w in zip(self.blocks, self.layer_windows):
            use_mask = (w is not None and w < L and self.attn_mode == "mask")
            mask = getattr(self, f"mask_{w}")[:L, :L] if use_mask else None
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
            # SIN checkpoint: compile+checkpoint OOMeó a b48 donde el no-checkpoint corría a
            # 13.08GB (medido K1 v2 vs v3) — AOTAutograd+AC retiene MÁS, no menos.
            sl = slice(i * n // 4, (i + 1) * n // 4)
            ce_i, zl_i = self._ce_chunk(xf[sl], tf[sl])
            ce = ce + ce_i
            zl = zl + zl_i
        ce = ce / n
        return None, ce, ce + ZLOSS * (zl / n)

    def _ce_chunk(self, xc, tc):
        lg = self.lm_head(xc).float()
        return (F.cross_entropy(lg, tc, reduction="sum"),
                (torch.logsumexp(lg, dim=-1) ** 2).sum())

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=0.8, top_p=0.95, eos_id=None):
        self.eval()
        for _ in range(n_new):
            logits, _, _ = self(idx[:, -SEQ:])
            logits = logits[:, -1, :].float() / max(1e-6, temperature)
            probs = F.softmax(logits, dim=-1)
            sp, si = torch.sort(probs, descending=True)
            keep = (sp.cumsum(-1) - sp) <= top_p
            keep[..., 0] = True
            sp = sp * keep
            nxt = si.gather(-1, torch.multinomial(sp / sp.sum(-1, keepdim=True), 1))
            idx = torch.cat([idx, nxt], dim=1)
            if eos_id is not None and int(nxt[0, 0]) == eos_id:
                break
        self.train()
        return idx

    def num_params(self):
        total = sum(p.numel() for p in self.parameters())
        return total, total - self.embed.weight.numel()


# ───────────────────────── optimizers / schedule (canónicos de xh_bench_kernel) ─────────────────────


@torch.no_grad()
def ns5(G, steps=5, eps=1e-7, dtype=torch.float16):
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


def make_optimizers(model, arm, device):
    fused = device == "cuda"
    if arm.get("opt") == "adamw_ctl":
        opt = torch.optim.AdamW(model.parameters(), lr=1.5e-3, betas=(0.9, 0.95),
                                weight_decay=0.1, fused=fused or None)
        return [opt], [1.5e-3]
    body2d, emb, oned = [], [], []
    for n, p in model.named_parameters():
        if "embed" in n or "lm_head" in n:
            emb.append(p)
        elif p.ndim >= 2:
            body2d.append(p)
        else:
            oned.append(p)
    muon_lr = arm.get("muon_lr", MUON_LR)
    muon = Muon(body2d, lr=muon_lr, momentum=0.95, weight_decay=0.0)
    adamw = torch.optim.AdamW(
        [{"params": emb, "weight_decay": 0.01}, {"params": oned, "weight_decay": 0.0}],
        lr=ADAMW_LR, betas=(0.9, 0.95), fused=fused or None)
    return [muon, adamw], [muon_lr, ADAMW_LR]


def lr_factor(step, progress):
    if step <= WARMUP_STEPS:
        return step / WARMUP_STEPS
    if progress >= 0.8:
        return max(0.0, (1.0 - progress) / 0.2)
    return 1.0


def set_lrs(opts, base_lrs, factor):
    for opt, base in zip(opts, base_lrs):
        for gr in opt.param_groups:
            gr["lr"] = base * factor


# ───────────────────────── datos / eval ─────────────────────────


def load_arm_data(kind, device, smoke):
    """→ (train_int32_gpu, val_wiki, val_stories, vocab, tokens_per_byte_wiki,
         tokens_per_byte_stories, tokenizer_path, eos_id)"""
    if smoke:
        g = torch.Generator().manual_seed(0)
        vocab = 256 if kind == "bytes" else 500
        tr = torch.randint(1, vocab, (300_000,), generator=g).to(torch.int32).to(device)
        va = torch.randint(1, vocab, (30_000,), generator=g).to(torch.int32).to(device)
        return tr, va, va, vocab, 1.0, 1.0, None, 0
    data_dir = find_data_dir()
    meta = json.loads(open(f"{data_dir}/xh_data_meta.json", encoding="utf-8").read())
    if kind == "bytes":
        tr = np.fromfile(f"{data_dir}/train_bytes.bin", dtype=np.uint8)
        vw = np.frombuffer(open(f"{data_dir}/val_wiki.txt", encoding="utf-8").read()
                           .encode("utf-8"), dtype=np.uint8)
        vs = np.frombuffer(open(f"{data_dir}/val_stories.txt", encoding="utf-8").read()
                           .encode("utf-8"), dtype=np.uint8)
        return (torch.from_numpy(tr.astype(np.int32)).to(device),
                torch.from_numpy(vw.astype(np.int32).copy()).to(device),
                torch.from_numpy(vs.astype(np.int32).copy()).to(device),
                256, 1.0, 1.0, None, 0)
    tag = "16k" if kind == "16k" else "32k"
    fn = f"train_wiki_{tag}.bin" if kind == "wiki" else f"train_mix_{tag}.bin"
    m = meta["vocabs"][tag]
    tr = np.fromfile(f"{data_dir}/{fn}", dtype=np.uint16)
    vw = np.fromfile(f"{data_dir}/val_wiki_{tag}.bin", dtype=np.uint16)
    vs = np.fromfile(f"{data_dir}/val_stories_{tag}.bin", dtype=np.uint16)
    tpb_w = m["val_wiki_tokens"] / meta["val_wiki_bytes"]
    tpb_s = m["val_stories_tokens"] / meta["val_stories_bytes"]
    return (torch.from_numpy(tr.astype(np.int32)).to(device),
            torch.from_numpy(vw.astype(np.int32)).to(device),
            torch.from_numpy(vs.astype(np.int32)).to(device),
            m["vocab_size"], tpb_w, tpb_s, f"{data_dir}/tokenizer_{tag}.json", m["eos_id"])


@torch.no_grad()
def eval_bpb(model, va, seq, tokens_per_byte, device, n_windows=24, eval_batch=8):
    model.eval()
    nll, n = 0.0, 0
    for s in range(0, n_windows, eval_batch):
        k = min(eval_batch, n_windows - s)
        idx = (torch.arange(k, device=device)[:, None] * seq
               + torch.arange(seq, device=device)[None, :]) + s * seq
        if int(idx.max()) + 1 >= len(va):
            break
        x, y = va[idx].long(), va[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, ce, _ = model(x, y)
        nll += float(ce) * k * seq
        n += k * seq
    model.train()
    return round(nll / n * tokens_per_byte / math.log(2), 4) if n else None


def distinct_n(ids, n=2):
    if len(ids) < n + 1:
        return 0.0
    grams = [tuple(ids[i:i + n]) for i in range(len(ids) - n + 1)]
    return round(len(set(grams)) / len(grams), 3)


def swap_eval(base, new_params, fn):
    """Evalúa fn() con otros pesos y restaura (para EMA/LAWA)."""
    old = [p.detach().clone() for p in base.parameters()]
    with torch.no_grad():
        for p, q in zip(base.parameters(), new_params):
            p.copy_(q)
    out = fn()
    with torch.no_grad():
        for p, o in zip(base.parameters(), old):
            p.copy_(o)
    return out


def hard_cleanup(device):
    """Suelta cachés de dynamo (retienen VRAM tras un OOM — lección K1 v2) + allocator."""
    torch._dynamo.reset()
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()


def run_arm(arm, device, smoke, dynamo_reset):
    hard_cleanup(device)
    kind = arm.get("data", "mix")
    tr, vw, vs, vocab, tpb_w, tpb_s, tok_path, eos_id = load_arm_data(kind, device, smoke)
    torch.manual_seed(0)
    if smoke:
        model = XHLM(vocab, d=64, n_heads=4, n_layers=2, global_layers=(1,))
    elif arm.get("shape"):
        s = arm["shape"]
        model = XHLM(vocab, d=s["d"], n_heads=s["heads"], n_layers=s["layers"],
                     d_ff=s["d_ff"], global_layers=s["globals"])
    else:
        model = XHLM(vocab)
    model = model.to(device)
    total, nonemb = model.num_params()
    base = model
    if BASE_COMPILE and not smoke:
        model = torch.compile(model, mode="default", fullgraph=True, dynamic=False)
    opts, base_lrs = make_optimizers(model, arm, device)
    scaler = torch.amp.GradScaler(device, enabled=device == "cuda")
    g = torch.Generator(device=device)
    g.manual_seed(0)
    batch = 8 if smoke else BASE_BATCH
    wall = 8.0 if smoke else TRAIN_WALL_S
    seq = 64 if smoke else SEQ
    arange = torch.arange(seq, device=device, dtype=torch.int32)
    res = {"name": arm["name"], "arm": {k: str(v) for k, v in arm.items()}, "vocab": vocab,
           "params_total": total, "params_nonemb": nonemb, "curve": [], "died": None,
           "scaler_skips": 0}
    print(f"[{arm['name']}] vocab={vocab} params={total / 1e6:.1f}M (nonemb {nonemb / 1e6:.1f}M) "
          f"ln(V)={math.log(vocab):.2f}", flush=True)

    ema = None
    lawa_snaps = []
    lawa_marks = [0.60, 0.70, 0.80, 0.90]
    if arm.get("free_rider"):
        ema = [p.detach().clone() for p in base.parameters()]

    t0 = time.time()
    next_eval = EVAL_EVERY_S if not smoke else 4.0
    step, tokens_seen = 0, 0
    compile_warmup_s = None
    while (time.time() - t0) < wall:
        step += 1
        progress = (time.time() - t0) / wall
        set_lrs(opts, base_lrs, lr_factor(step, progress))
        starts = torch.randint(0, len(tr) - seq - 1, (batch,), generator=g,
                               device=device, dtype=torch.int32)
        idx = starts[:, None] + arange[None, :]
        x, y = tr[idx].long(), tr[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
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
            res["scaler_skips"] += 1
        if step == 1:
            compile_warmup_s = round(time.time() - t0, 1)
        if ema is not None and step > WARMUP_STEPS:
            with torch.no_grad():
                torch._foreach_lerp_(ema, [p.detach() for p in base.parameters()],
                                     1 - EMA_DECAY)
        if lawa_marks and arm.get("free_rider") and progress >= lawa_marks[0]:
            lawa_marks.pop(0)
            lawa_snaps.append([p.detach().to("cpu", copy=True) for p in base.parameters()])
        tokens_seen += batch * seq
        lf = float(ce.detach())
        if not math.isfinite(lf):
            res["died"] = {"step": step, "loss": lf}
            print(f"[{arm['name']}] NaN/inf en step {step} — brazo MUERE", flush=True)
            break
        if (time.time() - t0) >= next_eval:
            next_eval += EVAL_EVERY_S if not smoke else 4.0
            bpb = eval_bpb(base, vw, seq, tpb_w, device)
            res["curve"].append({"s": round(time.time() - t0), "step": step,
                                 "loss": round(lf, 4), "bpb_wiki": bpb,
                                 "tokens_seen": tokens_seen,
                                 "lr_factor": round(lr_factor(step, progress), 3)})
            print(f"  [{arm['name']}] {res['curve'][-1]}", flush=True)

    res["steps"] = step
    res["tokens_seen"] = tokens_seen
    res["compile_warmup_s"] = compile_warmup_s
    res["tok_per_s"] = round(tokens_seen / max(1e-9, time.time() - t0))
    res["train_wall_s"] = round(time.time() - t0, 1)
    res["bpb_wiki"] = eval_bpb(base, vw, seq, tpb_w, device)
    res["bpb_stories"] = eval_bpb(base, vs, seq, tpb_s, device)

    if arm.get("free_rider") and not res["died"]:
        fr = {"last": res["bpb_wiki"]}
        if ema is not None:
            fr["ema"] = swap_eval(base, ema, lambda: eval_bpb(base, vw, seq, tpb_w, device))
        if lawa_snaps:
            snaps = lawa_snaps + [[p.detach().to("cpu", copy=True) for p in base.parameters()]]
            avg = [torch.stack([s[i].float() for s in snaps]).mean(0).to(device)
                   for i in range(len(snaps[0]))]
            fr["lawa"] = swap_eval(base, avg, lambda: eval_bpb(base, vw, seq, tpb_w, device))
        res["free_rider_W"] = fr
        best_kind = min((k for k in fr if fr[k] is not None), key=lambda k: fr[k])
        res["free_rider_best"] = best_kind
        print(f"  [W] last/ema/lawa: {fr} -> mejor: {best_kind}", flush=True)
        if best_kind == "ema" and ema is not None:
            with torch.no_grad():
                for p, q in zip(base.parameters(), ema):
                    p.copy_(q)

    # muestras + distinct-n (anti-degeneración G3)
    try:
        if kind == "bytes":
            for prompt in GEN_PROMPTS if not smoke else ():
                pi = torch.from_numpy(np.frombuffer(prompt.encode(), dtype=np.uint8)
                                      .astype(np.int32).copy()).to(device).long().unsqueeze(0)
                y = base.generate(pi.clone(), 200, eos_id=0)
                ids = y[0].tolist()
                res.setdefault("samples", []).append(
                    {"prompt": prompt,
                     "text": bytes(t % 256 for t in ids).decode("utf-8", "ignore"),
                     "distinct2": distinct_n(ids, 2), "distinct3": distinct_n(ids, 3)})
        elif tok_path:
            from tokenizers import Tokenizer
            tok = Tokenizer.from_file(tok_path)
            for prompt in GEN_PROMPTS if not smoke else ():
                pi = torch.tensor([tok.encode(prompt).ids], dtype=torch.long, device=device)
                y = base.generate(pi.clone(), 200, eos_id=eos_id)
                ids = y[0].tolist()
                res.setdefault("samples", []).append(
                    {"prompt": prompt, "text": tok.decode(ids),
                     "distinct2": distinct_n(ids, 2), "distinct3": distinct_n(ids, 3)})
        for smp in res.get("samples", []):
            print(f"  [{arm['name']}] d2={smp['distinct2']} d3={smp['distinct3']} "
                  f"{ascii(smp['text'])[:220]}", flush=True)
    except Exception as e:  # noqa: BLE001
        res["sample_error"] = repr(e)
        print(f"  [{arm['name']}] sample_error: {e!r}", flush=True)
    print(f"[{arm['name']}] FINAL bpb_wiki={res['bpb_wiki']} bpb_stories={res['bpb_stories']} "
          f"steps={step} tok={tokens_seen:,} ({res['tok_per_s']:,} tok/s) "
          f"skips={res['scaler_skips']}", flush=True)

    del model, base, opts, tr, vw, vs, ema, lawa_snaps
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return res


def run_h_micro(device, smoke):
    """H: buffer-mask vs causal-full vs chunked-SWA (150 steps c/u) + gate de extrapolación."""
    out = {"name": "H_attn_micro", "variants": []}
    tr, vw, _, vocab, tpb_w, _, _, _ = load_arm_data("mix", device, smoke)
    n_steps = 8 if smoke else 150
    for mode in ("mask", "causal_full", "chunked"):
        hard_cleanup(device)
        torch.manual_seed(0)
        kw = dict(d=64, n_heads=4, n_layers=2, global_layers=(1,), window=16) if smoke else {}
        model = XHLM(vocab, attn_mode=mode, **kw).to(device)
        base = model
        if BASE_COMPILE and not smoke:
            model = torch.compile(model, mode="default", fullgraph=True, dynamic=False)
        opts, base_lrs = make_optimizers(model, {}, device)
        scaler = torch.amp.GradScaler(device, enabled=device == "cuda")
        g = torch.Generator(device=device)
        g.manual_seed(0)
        batch = 8 if smoke else BASE_BATCH
        seq = 64 if smoke else SEQ
        arange = torch.arange(seq, device=device, dtype=torch.int32)
        t_warm = time.time()
        t_timed = None
        for s in range(1, n_steps + 1):
            set_lrs(opts, base_lrs, lr_factor(s, 0.5 * s / n_steps))
            starts = torch.randint(0, len(tr) - seq - 1, (batch,), generator=g,
                                   device=device, dtype=torch.int32)
            idx = starts[:, None] + arange[None, :]
            x, y = tr[idx].long(), tr[idx + 1].long()
            with torch.autocast(device_type=device, dtype=torch.float16,
                                enabled=device == "cuda"):
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
            if s == 10:
                if device == "cuda":
                    torch.cuda.synchronize()
                t_timed = time.time()
        if device == "cuda":
            torch.cuda.synchronize()
        tps = batch * seq * max(0, n_steps - 10) / max(1e-9, time.time() - (t_timed or t_warm))
        v = {"mode": mode, "tok_per_s": round(tps),
             "warmup_s": round((t_timed or time.time()) - t_warm, 1),
             "bpb_512": eval_bpb(base, vw, seq, tpb_w, device)}
        # gate de extrapolación 512→1024 con NTK×2 (fuera de smoke)
        if not smoke:
            v["bpb_1024"] = eval_bpb(base, vw, seq * 2, tpb_w, device, n_windows=12)
            base.set_rope_base(10000.0 * (2.0 ** (base.dh / max(1, base.dh - 2))))
            v["bpb_1024_ntk2"] = eval_bpb(base, vw, seq * 2, tpb_w, device, n_windows=12)
            base.set_rope_base(10000.0)
        out["variants"].append(v)
        print(f"[H-{mode}] {v}", flush=True)
        del model, base, opts
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
    del tr, vw
    gc.collect()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    torch.backends.cudnn.benchmark = True
    t0 = time.time()

    # invariancia chunked-SWA == máscara banded (misma matemática, assert SIEMPRE)
    torch.manual_seed(3)
    q = torch.randn(2, 2, 128, 16)
    k = torch.randn(2, 2, 128, 16)
    v = torch.randn(2, 2, 128, 16)
    w = 32
    o_chunk = chunked_swa(q, k, v, w)
    i = torch.arange(128)
    m = (i[None, :] <= i[:, None]) & (i[None, :] > (i[:, None] - w))
    o_mask = F.scaled_dot_product_attention(q, k, v, attn_mask=m)
    rel = float((o_chunk - o_mask).norm() / o_mask.norm())
    assert rel < 1e-4, f"chunked != mask (rel {rel})"
    print(f"[check] chunked-SWA == banded-mask (rel {rel:.2e}) OK", flush=True)

    out = {"experiment": "xh_ablate", "device": device, "torch": torch.__version__,
           "config": {"d": ARCH_D, "layers": ARCH_LAYERS, "window": ARCH_WINDOW,
                      "seq": SEQ, "batch": BASE_BATCH, "compile": BASE_COMPILE,
                      "muon_lr": MUON_LR, "adamw_lr": ADAMW_LR, "warmup": WARMUP_STEPS,
                      "train_wall_s": TRAIN_WALL_S, "ema": EMA_DECAY},
           "arms": []}
    arms = ARMS if not args.smoke else [
        {"name": "v1_muon", "free_rider": True}, {"name": "A_adamw_ctl", "opt": "adamw_ctl"},
        {"name": "D_byte256", "data": "bytes"}]
    prev_shape_key = None
    for arm in arms:
        if (time.time() - t0) / 60 > TIME_BUDGET_MIN:
            print("[ablate] BUDGET — corto", flush=True)
            break
        shape_key = (str(arm.get("shape")), arm.get("data", "mix"))
        try:
            out["arms"].append(run_arm(arm, device, args.smoke,
                                       dynamo_reset=shape_key != prev_shape_key))
            prev_shape_key = shape_key
        except torch.cuda.OutOfMemoryError as e:
            peak = torch.cuda.max_memory_allocated() / 1e9
            print(f"[{arm['name']}] OOM (pico {peak:.2f}GB): {str(e)[:200]}", flush=True)
            out["arms"].append({"name": arm["name"], "oom": True, "peak_gb": round(peak, 2)})
            hard_cleanup(device)
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    if (time.time() - t0) / 60 < TIME_BUDGET_MIN:
        try:
            out["h_micro"] = run_h_micro(device, args.smoke)
        except Exception as e:  # noqa: BLE001
            out["h_micro"] = {"error": repr(e)}
            print(f"[H] error: {e!r}", flush=True)

    ok = [a for a in out["arms"] if a.get("bpb_wiki") and not a.get("died")]
    if ok:
        ranked = sorted(ok, key=lambda a: a["bpb_wiki"])
        out["ranking_bpb_wiki"] = [
            {"name": a["name"], "bpb_wiki": a["bpb_wiki"], "bpb_stories": a["bpb_stories"],
             "tokens_seen": a["tokens_seen"], "tok_per_s": a["tok_per_s"]} for a in ranked]
        print("[ablate] RANKING bpb_wiki (menor=mejor):", flush=True)
        for r in out["ranking_bpb_wiki"]:
            print(f"  {r['name']}: {r['bpb_wiki']} (stories {r['bpb_stories']}, "
                  f"{r['tokens_seen']:,} tok)", flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[xh-ablate] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()

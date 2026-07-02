r"""
XH-ABLATE — kernel GPU T4: ablaciones del 100M a IGUAL WALL-CLOCK por brazo (la métrica honesta
cuando el goal es minutos, no steps). Consume el output de cognia-xh-data.

Cada brazo entrena TRAIN_WALL_S segundos con la MISMA arquitectura salvo la palanca que cambia,
y cierra con: val bpb (normalizado por BYTES → byte-level y BPE comparables), curva de val,
muestras generadas y distinct-2 (anti-degeneración). NaN = brazo muere y se registra (honesto).

Palancas: optimizer (AdamW fused / Muon / Lion), LR schedule (cosine / WSD / constante),
init (escalada GPT-2 / plana 0.02), tokenizer (BPE 32k / BPE 16k / bytes), curriculum de seq,
LR alto. Config base (batch/compile) se fija con xh_bench_results.json ANTES de pushear.

Salida: xh_ablate_results.json (guardado incremental por brazo).
USO local:  venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_ablate_kernel.py --smoke
"""
import argparse
import gc
import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS_PATH = "xh_ablate_results.json"
DATA_DIR = "/kaggle/input/cognia-xh-data"
TIME_BUDGET_MIN = 95.0
TRAIN_WALL_S = 330.0            # 5.5 min de entreno por brazo
EVAL_EVERY_S = 60.0

# ── config base (batch/compile SE FIJAN con xh_bench_results.json antes de pushear) ──
ARCH_D = 768
ARCH_HEADS = 12
ARCH_LAYERS = 12
ARCH_WINDOW = 256
SEQ = 512
BASE_BATCH = 64                  # <- ajustar con bench
BASE_COMPILE = True              # <- ajustar con bench
BASE_LR = 1e-3
WARMUP_STEPS = 150
WD = 0.1
CLIP = 1.0

ARMS = [
    # name, overrides — la base es: BPE 32k, banded 3:1, init escalada, AdamW fused, cosine
    {"name": "base_adamw_cos"},
    {"name": "muon",            "opt": "muon"},
    {"name": "lion",            "opt": "lion"},
    {"name": "sched_wsd",       "sched": "wsd"},
    {"name": "sched_const",     "sched": "none"},      # control = precedente xfinal (solo warmup)
    {"name": "init_flat",       "init": "flat"},
    {"name": "bytes",           "tok": "bytes"},        # brazo byte-level (vocab 256)
    {"name": "vocab16k",        "tok": "16k"},
    {"name": "seq_curriculum",  "curr": True},
    {"name": "lr_2x",           "lr_mult": 2.0},
]


# ───────────────────────── modelo (idéntico a xh_bench_kernel.XHLM) ─────────────────────────


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
    def __init__(self, d, n_heads, window=None):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos, sin, mask):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)
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
    def __init__(self, vocab, d, n_heads, layer_windows, max_seq=2048, scaled_init=True):
        super().__init__()
        d_ff = max(64, int(round(8 * d / 3 / 64)) * 64)
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w) for w in layer_windows])
        self.layer_windows = list(layer_windows)
        self.dh = d // n_heads
        self.max_seq = max_seq
        cos, sin = build_rope_cache(max_seq, self.dh, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(d)
        self.lm_head = nn.Linear(d, vocab, bias=False)
        self.lm_head.weight = self.embed.weight
        self.apply(self._init_flat)
        if scaled_init:
            n_res = 2 * len(layer_windows)
            for b in self.blocks:
                nn.init.normal_(b.attn.o.weight, mean=0.0, std=0.02 / math.sqrt(n_res))
                nn.init.normal_(b.mlp.w3.weight, mean=0.0, std=0.02 / math.sqrt(n_res))
        for w in sorted({w for w in layer_windows if w is not None}):
            idx = torch.arange(max_seq)
            m = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - w))
            self.register_buffer(f"mask_{w}", m, persistent=False)

    @staticmethod
    def _init_flat(m):
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        cos = self.rope_cos[:L].to(x.dtype)
        sin = self.rope_sin[:L].to(x.dtype)
        for b, w in zip(self.blocks, self.layer_windows):
            mask = None if (w is None or w >= L) else getattr(self, f"mask_{w}")[:L, :L]
            x = b(x, cos, sin, mask)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.float().view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=0.7, top_k=40):
        self.eval()
        for _ in range(n_new):
            logits, _ = self(idx[:, -SEQ:])
            logits = logits[:, -1, :].float() / max(1e-6, temperature)
            v, _ = torch.topk(logits, top_k)
            logits[logits < v[:, [-1]]] = float("-inf")
            nxt = torch.multinomial(F.softmax(logits, dim=-1), 1)
            idx = torch.cat([idx, nxt], dim=1)
        self.train()
        return idx

    def num_params(self):
        total = sum(p.numel() for p in self.parameters())
        return total, total - self.embed.weight.numel()


# ───────────────────────── optimizers alternativos (embebidos, sin deps) ─────────────────────────


@torch.no_grad()
def ns5(G, steps=5, eps=1e-7):
    """Newton-Schulz quintic (Muon): ortogonaliza el update. fp32 en T4 (sin bf16 rápido)."""
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.float()
    X = X / (X.norm() + eps)
    transposed = X.size(0) > X.size(1)
    if transposed:
        X = X.T
    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X


class Muon(torch.optim.Optimizer):
    """Muon (Keller Jordan / nanoGPT speedrun; escalable — Moonshot lo usó a 1T params).
    SOLO para matrices 2D del cuerpo; embed/norms/head van en un AdamW aparte."""

    def __init__(self, params, lr=0.02, momentum=0.95, nesterov=True, weight_decay=0.0):
        super().__init__(params, dict(lr=lr, momentum=momentum, nesterov=nesterov,
                                      weight_decay=weight_decay))

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
                    st["buf"] = torch.zeros_like(g)
                buf = st["buf"]
                buf.mul_(mu).add_(g)
                gg = g.add(buf, alpha=mu) if group["nesterov"] else buf
                O = ns5(gg.reshape(gg.size(0), -1)).reshape_as(gg).to(p.dtype)
                if wd:
                    p.mul_(1 - lr * wd)
                p.add_(O, alpha=-lr * max(1, p.size(0) / p.size(1)) ** 0.5)


class Lion(torch.optim.Optimizer):
    """Lion (Chen et al. 2023): sign(interp(m, g)); memoria = 1 estado (vs 2 de Adam)."""

    def __init__(self, params, lr=1e-4, betas=(0.9, 0.99), weight_decay=0.0):
        super().__init__(params, dict(lr=lr, betas=betas, weight_decay=weight_decay))

    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            lr, (b1, b2), wd = group["lr"], group["betas"], group["weight_decay"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                st = self.state[p]
                if "m" not in st:
                    st["m"] = torch.zeros_like(p)
                m = st["m"]
                if wd:
                    p.mul_(1 - lr * wd)
                p.add_(torch.sign(m.mul(b1).add(g, alpha=1 - b1)), alpha=-lr)
                m.mul_(b2).add_(g, alpha=1 - b2)


def make_optimizers(model, arm, device):
    """Devuelve lista de optimizers + lr base por grupo (para el schedule)."""
    kind = arm.get("opt", "adamw")
    lr = BASE_LR * arm.get("lr_mult", 1.0)
    fused = device == "cuda"
    if kind == "adamw":
        opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95),
                                weight_decay=WD, fused=fused or None)
        return [opt], [lr]
    body2d, rest = [], []
    for n, p in model.named_parameters():
        if p.ndim == 2 and "embed" not in n and "lm_head" not in n:
            body2d.append(p)
        else:
            rest.append(p)
    if kind == "muon":
        muon_lr = 0.02 * arm.get("lr_mult", 1.0)
        o1 = Muon(body2d, lr=muon_lr, momentum=0.95, weight_decay=WD)
        o2 = torch.optim.AdamW(rest, lr=lr, betas=(0.9, 0.95), weight_decay=WD,
                               fused=fused or None)
        return [o1, o2], [muon_lr, lr]
    if kind == "lion":
        lion_lr = lr / 4                      # regla estándar: lr/3..10, wd compensado
        opt = Lion(model.parameters(), lr=lion_lr, betas=(0.9, 0.99), weight_decay=WD * 4)
        return [opt], [lion_lr]
    raise ValueError(kind)


def lr_at(arm, step, progress, base_lrs):
    """Warmup por steps + decay por PROGRESO de wall (el budget es tiempo, no steps)."""
    sched = arm.get("sched", "cosine")
    outs = []
    for base in base_lrs:
        if step <= WARMUP_STEPS:
            outs.append(base * step / WARMUP_STEPS)
        elif sched == "none":
            outs.append(base)
        elif sched == "wsd":
            outs.append(base if progress < 0.8 else
                        base * (1 - 0.9 * (progress - 0.8) / 0.2))
        else:                                  # cosine → 10%
            outs.append(base * (0.1 + 0.45 * (1 + math.cos(math.pi * min(1.0, progress)))))
    return outs


# ───────────────────────── datos / eval ─────────────────────────


def load_arm_data(tok_tag, device, smoke):
    """tokens de train + val (int32 en GPU) + normalización bpb (tokens/byte del val)."""
    if smoke:
        g = torch.Generator().manual_seed(0)
        tr = torch.randint(0, 500, (300_000,), generator=g).to(torch.int32).to(device)
        va = torch.randint(0, 500, (20_000,), generator=g).to(torch.int32).to(device)
        return tr, va, 512, 1.0, None
    if tok_tag == "bytes":
        tr = np.fromfile(f"{DATA_DIR}/train_bytes.bin", dtype=np.uint8)
        va_txt = open(f"{DATA_DIR}/val.txt", encoding="utf-8").read()
        va = np.frombuffer(va_txt.encode("utf-8"), dtype=np.uint8)
        tr_t = torch.from_numpy(tr.astype(np.int32)).to(device)
        va_t = torch.from_numpy(va.astype(np.int32).copy()).to(device)
        return tr_t, va_t, 256, 1.0, None
    meta = json.loads(open(f"{DATA_DIR}/xh_data_meta.json", encoding="utf-8").read())
    m = meta["vocabs"][tok_tag]
    tr = np.fromfile(f"{DATA_DIR}/train_{tok_tag}.bin", dtype=np.uint16)
    va = np.fromfile(f"{DATA_DIR}/val_{tok_tag}.bin", dtype=np.uint16)
    tokens_per_byte = m["val_tokens"] / meta["val_text_bytes"]
    tr_t = torch.from_numpy(tr.astype(np.int32)).to(device)
    va_t = torch.from_numpy(va.astype(np.int32)).to(device)
    return tr_t, va_t, m["vocab_size"], tokens_per_byte, f"{DATA_DIR}/tokenizer_{tok_tag}.json"


@torch.no_grad()
def eval_bpb(model, va, seq, tokens_per_byte, device, n_windows=24, eval_batch=8):
    """CE media por token × tokens/byte / ln2 = bits por BYTE (comparable entre tokenizers)."""
    model.eval()
    nll, n = 0.0, 0
    for s in range(0, n_windows, eval_batch):
        k = min(eval_batch, n_windows - s)
        idx = torch.arange(k, device=device)[:, None] * seq + torch.arange(seq, device=device)[None, :]
        idx = idx + s * seq
        if int(idx.max()) + 1 >= len(va):
            break
        x = va[idx].long()
        y = va[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, loss = model(x, y)
        nll += float(loss) * k * seq
        n += k * seq
    model.train()
    if n == 0:
        return None
    return round(nll / n * tokens_per_byte / math.log(2), 4)


def distinct2(ids):
    if len(ids) < 3:
        return 0.0
    pairs = list(zip(ids[:-1], ids[1:]))
    return round(len(set(pairs)) / len(pairs), 3)


def run_arm(arm, device, smoke):
    tok_tag = arm.get("tok", "32k")
    tr, va, vocab, tokens_per_byte, tok_path = load_arm_data(tok_tag, device, smoke)
    torch.manual_seed(0)
    d, heads, layers = (64, 4, 2) if smoke else (ARCH_D, ARCH_HEADS, ARCH_LAYERS)
    windows = [ARCH_WINDOW, ARCH_WINDOW, ARCH_WINDOW, None] * max(1, layers // 4)
    windows = windows[:layers]
    model = XHLM(vocab, d, heads, windows, scaled_init=arm.get("init", "scaled") != "flat").to(device)
    total, nonemb = model.num_params()
    if BASE_COMPILE and not smoke:
        torch._dynamo.reset()
        model = torch.compile(model, dynamic=arm.get("curr", False) or None)
    opts, base_lrs = make_optimizers(model, arm, device)
    scaler = torch.amp.GradScaler(device, enabled=device == "cuda")
    g = torch.Generator(device=device)
    g.manual_seed(0)
    batch = 8 if smoke else BASE_BATCH
    wall = 6.0 if smoke else TRAIN_WALL_S
    res = {"name": arm["name"], "arm": arm, "vocab": vocab, "params_total": total,
           "params_nonemb": nonemb, "tokens_per_byte": round(tokens_per_byte, 4),
           "curve": [], "died": None}
    print(f"[{arm['name']}] vocab={vocab} params={total / 1e6:.1f}M "
          f"(nonemb {nonemb / 1e6:.1f}M)", flush=True)

    t0 = time.time()
    next_eval = EVAL_EVERY_S if not smoke else 3.0
    step = 0
    tokens_seen = 0
    while (time.time() - t0) < wall:
        step += 1
        progress = (time.time() - t0) / wall
        if arm.get("curr"):
            seq = 128 if progress < 0.25 else (256 if progress < 0.5 else SEQ)
        else:
            seq = SEQ if not smoke else 64
        for opt, lr in zip(opts, lr_at(arm, step, progress, base_lrs)):
            for gr in opt.param_groups:
                gr["lr"] = lr
        starts = torch.randint(0, len(tr) - seq - 1, (batch,), generator=g,
                               device=device, dtype=torch.int32)
        idx = starts[:, None] + torch.arange(seq, device=device, dtype=torch.int32)[None, :]
        x, y = tr[idx].long(), tr[idx + 1].long()
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, loss = model(x, y)
        for opt in opts:
            opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        for opt in opts:
            scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
        for opt in opts:
            scaler.step(opt)
        scaler.update()
        tokens_seen += batch * seq
        lf = float(loss.detach())
        if not math.isfinite(lf):
            res["died"] = {"step": step, "loss": lf}
            print(f"[{arm['name']}] NaN/inf en step {step} — brazo MUERE", flush=True)
            break
        if (time.time() - t0) >= next_eval:
            next_eval += EVAL_EVERY_S if not smoke else 3.0
            bpb = eval_bpb(model, va, SEQ if not smoke else 64, tokens_per_byte, device)
            res["curve"].append({"s": round(time.time() - t0), "step": step,
                                 "loss": round(lf, 4), "val_bpb": bpb,
                                 "tokens_seen": tokens_seen})
            print(f"  [{arm['name']}] {res['curve'][-1]}", flush=True)

    res["steps"] = step
    res["tokens_seen"] = tokens_seen
    res["final_bpb"] = eval_bpb(model, va, SEQ if not smoke else 64, tokens_per_byte, device)
    res["train_wall_s"] = round(time.time() - t0, 1)

    # muestras (anti-degeneración): decodificables solo con tokenizer real o bytes
    base_model = getattr(model, "_orig_mod", model)
    gen_ids = None
    try:
        if tok_tag == "bytes":
            prompt = torch.from_numpy(np.frombuffer("La historia de ".encode(), dtype=np.uint8)
                                      .astype(np.int32).copy()).to(device).unsqueeze(0)
            y = base_model.generate(prompt.clone(), 150 if not smoke else 20)
            gen_ids = y[0].tolist()
            res["sample"] = bytes(t % 256 for t in gen_ids).decode("utf-8", "ignore")
        elif tok_path:
            from tokenizers import Tokenizer
            tok = Tokenizer.from_file(tok_path)
            ids = tok.encode("La historia de").ids
            prompt = torch.tensor([ids], dtype=torch.long, device=device)
            y = base_model.generate(prompt.clone(), 60 if not smoke else 10)
            gen_ids = y[0].tolist()
            res["sample"] = tok.decode(gen_ids)
        if gen_ids:
            res["distinct2"] = distinct2(gen_ids)
            print(f"  [{arm['name']}] distinct2={res['distinct2']} muestra: "
                  f"{ascii(res.get('sample', ''))[:200]}", flush=True)
    except Exception as e:  # noqa: BLE001
        res["sample_error"] = repr(e)
    print(f"[{arm['name']}] FINAL bpb={res['final_bpb']} steps={step} "
          f"tokens={tokens_seen:,}", flush=True)

    del model, opts, tr, va
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    torch.backends.cudnn.benchmark = True
    t0 = time.time()
    out = {"experiment": "xh_ablate", "device": device, "torch": torch.__version__,
           "config": {"d": ARCH_D, "heads": ARCH_HEADS, "layers": ARCH_LAYERS,
                      "window": ARCH_WINDOW, "seq": SEQ, "batch": BASE_BATCH,
                      "compile": BASE_COMPILE, "lr": BASE_LR, "warmup": WARMUP_STEPS,
                      "wd": WD, "train_wall_s": TRAIN_WALL_S},
           "arms": []}
    arms = ARMS if not args.smoke else [
        {"name": "base_adamw_cos"}, {"name": "muon", "opt": "muon"},
        {"name": "lion", "opt": "lion"}, {"name": "seq_curriculum", "curr": True}]
    for arm in arms:
        if (time.time() - t0) / 60 > TIME_BUDGET_MIN:
            print("[ablate] BUDGET — corto", flush=True)
            break
        try:
            out["arms"].append(run_arm(arm, device, args.smoke))
        except torch.cuda.OutOfMemoryError:
            print(f"[{arm['name']}] OOM", flush=True)
            out["arms"].append({"name": arm["name"], "oom": True})
            gc.collect()
            torch.cuda.empty_cache()
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    ok = [a for a in out["arms"] if a.get("final_bpb") and not a.get("died")]
    if ok:
        ranked = sorted(ok, key=lambda a: a["final_bpb"])
        out["ranking"] = [{"name": a["name"], "final_bpb": a["final_bpb"],
                           "tokens_seen": a["tokens_seen"]} for a in ranked]
        print("[ablate] RANKING (bpb, menor=mejor):", flush=True)
        for r in out["ranking"]:
            print(f"  {r['name']}: {r['final_bpb']} ({r['tokens_seen']:,} tokens)", flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[xh-ablate] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()

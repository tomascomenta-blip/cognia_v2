r"""
X3 (04_MOM_GROKKING §6) — MoM-mínimo: ¿la especialización DENSA paga su nicho más que un
LoRA-control sobre el generalista? La decisión estructural de la idea MoM del dueño.

7 modelos, receta K3 congelada (Muon 0.02 dual, BPE-16k 3dom, d768 12L banded, b48, WSD):
  gen           generalista, mezcla de tercios (train_gen_mix3), 12 min
  exp_{d}       experto denso 100% su dominio, 12 min c/u          (d ∈ stories,wiki,code)
  lora_{d}      LoRA r=32 α=64 sobre los pesos de gen, 6 min c/u   (AdamW 2e-3 — desvío
                declarado: Muon no aplica a adapters; el generalista compartido amortiza)

Métrica congelada: matriz bpb (7 modelos × 3 vals de dominio, normalizado por BYTES con la
fertilidad medida por dominio). Decisión pre-registrada: experto gana su nicho ≥0.10 bpb vs
gen y pierde ≥0.3 fuera; si lora ≥ experto en el nicho, el MoM denso NO paga (gana diseño 08).
Checkpoints fp16 de los 7 se guardan para X4 (selector vs fusión, local).
USO local: venv312\Scripts\python.exe cognia_x/construccion/xhundred/xh_x3_mom.py --smoke
"""
import argparse
import gc
import json
import math
import os
import time

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS_PATH = "xh_x3_results.json"
_DD = []


def find_data_dir():
    if _DD:
        return _DD[0]
    for root, _d, files in os.walk("/kaggle/input"):
        if "xh_x3data_meta.json" in files:
            _DD.append(root)
            print(f"[data] dir: {root}", flush=True)
            return root
    raise FileNotFoundError("xh_x3data_meta.json no está bajo /kaggle/input")


TIME_BUDGET_MIN = 115.0
ARCH_D = 768
ARCH_HEADS = 12
ARCH_LAYERS = 12
ARCH_WINDOW = 256
GLOBAL_LAYERS = (3, 7, 11)
SEQ = 512
BATCH = 48
MUON_LR = 0.02
ADAMW_LR = 3e-3
ZLOSS = 1e-4
WARMUP_STEPS = 200
TRAIN_FULL_S = 720.0
TRAIN_LORA_S = 360.0
LORA_R, LORA_ALPHA, LORA_LR = 32, 64, 2e-3
DOMS = ("stories", "wiki", "code")


# ── modelo (canónico de xh_final_kernel) ──


def build_rope_cache(seq_len, dh, base=10000.0):
    half = dh // 2
    inv = 1.0 / (base ** (torch.arange(0, half).float() / half))
    ang = torch.outer(torch.arange(seq_len).float(), inv)
    emb = torch.cat([ang, ang], dim=-1)
    return emb.cos(), emb.sin()


def apply_rope(x, cos, sin):
    L = x.shape[-2]
    cos = cos[:L].view(1, 1, L, -1)
    sin = sin[:L].view(1, 1, L, -1)
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half], x[..., half:]
    return x * cos + torch.cat([-x2, x1], dim=-1) * sin


class RMSNorm(nn.Module):
    def __init__(self, d, eps=1e-5):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))
        self.eps = eps

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.w


class LoRALinear(nn.Module):
    """base congelada + B(A(x))·α/r. A~N(0,0.02), B=0 (estándar)."""

    def __init__(self, base, r=LORA_R, alpha=LORA_ALPHA):
        super().__init__()
        self.base = base
        self.A = nn.Parameter(torch.randn(r, base.in_features) * 0.02)
        self.B = nn.Parameter(torch.zeros(base.out_features, r))
        self.scale = alpha / r

    def forward(self, x):
        return self.base(x) + F.linear(F.linear(x, self.A), self.B) * self.scale


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
        self.q_norm = RMSNorm(self.dh)
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
    def __init__(self, vocab, d=ARCH_D, n_heads=ARCH_HEADS, n_layers=ARCH_LAYERS,
                 window=ARCH_WINDOW, global_layers=GLOBAL_LAYERS, max_seq=2048):
        super().__init__()
        d_ff = max(64, int(round(8 * d / 3 / 64)) * 64)
        windows = [None if i in global_layers else window for i in range(n_layers)]
        self.embed = nn.Embedding(vocab, d)
        self.blocks = nn.ModuleList([Block(d, n_heads, d_ff, w) for w in windows])
        self.layer_windows = windows
        self.dh = d // n_heads
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

    def add_lora(self):
        for p in self.parameters():
            p.requires_grad_(False)
        for b in self.blocks:
            b.attn.qkv = LoRALinear(b.attn.qkv)
            b.attn.o = LoRALinear(b.attn.o)
            b.mlp.w1 = LoRALinear(b.mlp.w1)
            b.mlp.w2 = LoRALinear(b.mlp.w2)
            b.mlp.w3 = LoRALinear(b.mlp.w3)
        return [p for p in self.parameters() if p.requires_grad]

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
            sl = slice(i * n // 4, (i + 1) * n // 4)
            lg = self.lm_head(xf[sl]).float()
            ce = ce + F.cross_entropy(lg, tf[sl], reduction="sum")
            zl = zl + (torch.logsumexp(lg, dim=-1) ** 2).sum()
        ce = ce / n
        return None, ce, ce + ZLOSS * (zl / n)

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=0.8, top_p=0.95, eos_id=0):
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
            if int(nxt[0, 0]) == eos_id:
                break
        self.train()
        return idx


@torch.no_grad()
def ns5(G, steps=5, eps=1e-7, dtype=torch.float16):
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.to(dtype)
    X = X / (X.norm() + eps)
    t = X.size(0) > X.size(1)
    if t:
        X = X.mT
    for _ in range(steps):
        A = X @ X.mT
        B = b * A + c * A @ A
        X = a * X + B @ X
    return X.mT if t else X


class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr=MUON_LR, momentum=0.95):
        super().__init__(params, dict(lr=lr, momentum=momentum))

    @torch.no_grad()
    def step(self, closure=None):
        for g in self.param_groups:
            for p in g["params"]:
                if p.grad is None:
                    continue
                st = self.state[p]
                if "buf" not in st:
                    st["buf"] = torch.zeros_like(p.grad, dtype=torch.float32)
                buf = st["buf"]
                buf.mul_(g["momentum"]).add_(p.grad)
                gg = p.grad.add(buf, alpha=g["momentum"])
                O = ns5(gg.reshape(gg.size(0), -1)).reshape_as(gg).to(p.dtype)
                p.add_(O, alpha=-g["lr"] * max(1, p.size(0) / p.size(1)) ** 0.5)


def lr_factor(step, progress, warmup):
    if step <= warmup:
        return step / warmup
    if progress >= 0.8:
        return max(0.0, (1.0 - progress) / 0.2)
    return 1.0


def hard_cleanup(device):
    torch._dynamo.reset()
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()


def load_bin(path, device):
    return torch.from_numpy(np.fromfile(path, dtype=np.uint16).astype(np.int32)).to(device)


@torch.no_grad()
def eval_bpb(model, va, tpb, device, n_windows=24, eval_batch=8):
    model.eval()
    nll = n = 0
    for s in range(0, n_windows, eval_batch):
        k = min(eval_batch, n_windows - s)
        idx = (torch.arange(k, device=device)[:, None] * SEQ
               + torch.arange(SEQ, device=device)[None, :]) + s * SEQ
        if int(idx.max()) + 1 >= len(va):
            break
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, ce, _ = model(va[idx].long(), va[idx + 1].long())
        nll += float(ce) * k * SEQ
        n += k * SEQ
    model.train()
    return round(nll / n * tpb / math.log(2), 4) if n else None


def train_clock(model, base, data, opts, base_lrs, wall, warmup, device, tag, smoke):
    scaler = torch.amp.GradScaler(device, enabled=device == "cuda")
    g = torch.Generator(device=device)
    g.manual_seed(0)
    batch = 8 if smoke else BATCH
    seq = 64 if smoke else SEQ
    ar = torch.arange(seq, device=device, dtype=torch.int32)
    t0 = time.time()
    step = tokens = 0
    while (time.time() - t0) < wall:
        step += 1
        prog = (time.time() - t0) / wall
        f = lr_factor(step, prog, warmup)
        for o, bl in zip(opts, base_lrs):
            for gr in o.param_groups:
                gr["lr"] = bl * f
        starts = torch.randint(0, len(data) - seq - 1, (batch,), generator=g,
                               device=device, dtype=torch.int32)
        idx = starts[:, None] + ar[None, :]
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            _, ce, tot = model(data[idx].long(), data[idx + 1].long())
        for o in opts:
            o.zero_grad(set_to_none=True)
        scaler.scale(tot).backward()
        for o in opts:
            scaler.unscale_(o)
        torch.nn.utils.clip_grad_norm_([p for p in base.parameters() if p.requires_grad], 1.0)
        for o in opts:
            scaler.step(o)
        scaler.update()
        tokens += batch * seq
        if not math.isfinite(float(ce.detach())):
            print(f"[{tag}] NaN step {step} — muere", flush=True)
            return step, tokens, False
        if step % 200 == 0:
            print(f"  [{tag}] step {step} ce {float(ce.detach()):.3f} "
                  f"({tokens / (time.time() - t0):.0f} tok/s)", flush=True)
    return step, tokens, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    smoke = args.smoke
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(3)
    torch.backends.cudnn.benchmark = True
    t0 = time.time()

    if smoke:
        vocab = 512
        g0 = torch.Generator().manual_seed(0)
        trains = {d: torch.randint(1, vocab, (200_000,), generator=g0).to(torch.int32).to(device)
                  for d in DOMS}
        gen_data = torch.randint(1, vocab, (300_000,), generator=g0).to(torch.int32).to(device)
        vals = {d: torch.randint(1, vocab, (30_000,), generator=g0).to(torch.int32).to(device)
                for d in DOMS}
        tpb = {d: 1.0 for d in DOMS}
        wall_full, wall_lora, warmup = 6.0, 4.0, 5
    else:
        dd = find_data_dir()
        meta = json.loads(open(f"{dd}/xh_x3data_meta.json", encoding="utf-8").read())
        vocab = meta["vocab"]
        trains = {d: load_bin(f"{dd}/train_dom_{d}.bin", device) for d in DOMS}
        gen_data = load_bin(f"{dd}/train_gen_mix3.bin", device)
        vals = {d: load_bin(f"{dd}/val_{d}_3dom.bin", device) for d in DOMS}
        tpb = {d: meta["domains"][d]["val_tokens"] / meta["domains"][d]["val_bytes"]
               for d in DOMS}
        wall_full, wall_lora, warmup = TRAIN_FULL_S, TRAIN_LORA_S, WARMUP_STEPS

    out = {"experiment": "xh_x3_mom", "device": device, "vocab": vocab,
           "config": {"lora_r": LORA_R, "lora_alpha": LORA_ALPHA, "lora_lr": LORA_LR,
                      "wall_full_s": wall_full, "wall_lora_s": wall_lora},
           "models": {}, "bpb_matrix": {}}

    def save_out():
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    def build():
        torch.manual_seed(0)
        kw = dict(d=64, n_heads=4, n_layers=2, global_layers=(1,)) if smoke else {}
        return XHLM(vocab, **kw).to(device)

    def make_muon_opts(model):
        body = [p for n_, p in model.named_parameters()
                if p.ndim >= 2 and "embed" not in n_ and "lm_head" not in n_]
        rest = [p for n_, p in model.named_parameters()
                if not (p.ndim >= 2 and "embed" not in n_ and "lm_head" not in n_)]
        return ([Muon(body), torch.optim.AdamW(rest, lr=ADAMW_LR, betas=(0.9, 0.95),
                                               weight_decay=0.01,
                                               fused=(device == "cuda") or None)],
                [MUON_LR, ADAMW_LR])

    def eval_row(model, name):
        row = {d: eval_bpb(model, vals[d], tpb[d], device) for d in DOMS}
        out["bpb_matrix"][name] = row
        print(f"[{name}] bpb: {row}", flush=True)
        save_out()

    # ── (a) generalista ──
    hard_cleanup(device)
    gen = build()
    model = torch.compile(gen, mode="default", fullgraph=True, dynamic=False) \
        if not smoke else gen
    opts, lrs = make_muon_opts(model)
    st, tk, ok = train_clock(model, gen, gen_data, opts, lrs, wall_full, warmup, device,
                             "gen", smoke)
    out["models"]["gen"] = {"steps": st, "tokens": tk, "ok": ok}
    eval_row(gen, "gen")
    gen_sd = {k: v.detach().clone() for k, v in gen.state_dict().items()}
    torch.save({k: v.half().cpu() for k, v in gen_sd.items()}, "x3_gen.pt")
    del opts
    hard_cleanup(device)

    # ── (b) expertos densos ──
    for d in DOMS:
        if (time.time() - t0) / 60 > TIME_BUDGET_MIN:
            print("[x3] BUDGET — corto", flush=True)
            break
        base = build()
        model = torch.compile(base, mode="default", fullgraph=True, dynamic=False) \
            if not smoke else base
        opts, lrs = make_muon_opts(model)
        st, tk, ok = train_clock(model, base, trains[d], opts, lrs, wall_full, warmup,
                                 device, f"exp_{d}", smoke)
        out["models"][f"exp_{d}"] = {"steps": st, "tokens": tk, "ok": ok}
        eval_row(base, f"exp_{d}")
        torch.save({k: v.half().cpu() for k, v in base.state_dict().items()}, f"x3_exp_{d}.pt")
        del base, model, opts
        hard_cleanup(device)

    # ── (c) LoRA por dominio sobre gen ──
    for d in DOMS:
        if (time.time() - t0) / 60 > TIME_BUDGET_MIN:
            print("[x3] BUDGET — corto", flush=True)
            break
        base = build()
        base.load_state_dict(gen_sd)
        lora_params = base.add_lora()
        base = base.to(device)
        n_lora = sum(p.numel() for p in lora_params)
        model = torch.compile(base, mode="default", fullgraph=True, dynamic=False) \
            if not smoke else base
        opts = [torch.optim.AdamW(lora_params, lr=LORA_LR, betas=(0.9, 0.95),
                                  weight_decay=0.0)]
        st, tk, ok = train_clock(model, base, trains[d], opts, [LORA_LR], wall_lora,
                                 max(20, warmup // 4), device, f"lora_{d}", smoke)
        out["models"][f"lora_{d}"] = {"steps": st, "tokens": tk, "ok": ok,
                                      "lora_params": n_lora}
        eval_row(base, f"lora_{d}")
        torch.save({k: v.half().cpu() for k, v in base.state_dict().items()
                    if ".A" in k or ".B" in k}, f"x3_lora_{d}.pt")
        del base, model, opts
        hard_cleanup(device)

    # ── veredicto pre-registrado ──
    m = out["bpb_matrix"]
    if "gen" in m and all(f"exp_{d}" in m for d in DOMS):
        ver = {}
        for d in DOMS:
            e, g_, others = m[f"exp_{d}"][d], m["gen"][d], \
                [m[f"exp_{d}"][o] - m["gen"][o] for o in DOMS if o != d]
            ver[d] = {"experto_gana_nicho_bpb": round(g_ - e, 4),
                      "P_gana_010": bool(g_ - e >= 0.10),
                      "experto_pierde_fuera": [round(x, 4) for x in others],
                      "lora_vs_experto_nicho": (round(m[f"lora_{d}"][d] - e, 4)
                                                if f"lora_{d}" in m else None)}
        ver["mom_denso_paga"] = all(v["P_gana_010"] for v in ver.values() if isinstance(v, dict))
        if all(f"lora_{d}" in m for d in DOMS):
            ver["lora_empata"] = all(m[f"lora_{d}"][d] <= m[f"exp_{d}"][d] + 0.01 for d in DOMS)
        out["veredicto"] = ver
        print(f"[x3] VEREDICTO: {json.dumps(ver, ensure_ascii=False)}", flush=True)
    out["minutes_total"] = round((time.time() - t0) / 60, 1)
    save_out()
    print(f"[x3] LISTO en {out['minutes_total']} min", flush=True)


if __name__ == "__main__":
    main()

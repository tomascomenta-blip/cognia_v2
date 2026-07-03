"""XHLM — la arquitectura de la flota (copia canónica de construccion/xhundred/xh_x3_mom.py;
los checkpoints fleet_*.pt / x3_*.pt cargan acá tal cual). d768 12L 12H SwiGLU banded 3:1
w256 (globals 3/7/11), RoPE, QK-norm, tied head. Receta validada en K2/K3."""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

ARCH = dict(d=768, n_heads=12, n_layers=12, window=256, global_layers=(3, 7, 11))
SEQ = 512


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
    def __init__(self, vocab, d=ARCH["d"], n_heads=ARCH["n_heads"],
                 n_layers=ARCH["n_layers"], window=ARCH["window"],
                 global_layers=ARCH["global_layers"], max_seq=2048):
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
        for w in sorted({w for w in windows if w is not None}):
            idx = torch.arange(max_seq)
            m = (idx[None, :] <= idx[:, None]) & (idx[None, :] > (idx[:, None] - w))
            self.register_buffer(f"mask_{w}", m, persistent=False)

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
        if targets is None:
            return logits, None
        loss = F.cross_entropy(logits.float().view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=0.8, top_p=0.95, eos_id=0):
        self.eval()
        for _ in range(n_new):
            logits, _ = self(idx[:, -SEQ:])
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
        return idx

    @torch.no_grad()
    def mean_nll(self, ids):
        """NLL media por token de una secuencia (para eval bpb del CLI)."""
        x = ids[:-1].unsqueeze(0)
        y = ids[1:].unsqueeze(0)
        _, loss = self(x, y)
        return float(loss)

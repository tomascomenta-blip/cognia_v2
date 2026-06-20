"""
Cognia-X v0 — modelo de secuencia HIBRIDO (PyTorch, CPU-first).

Encarna las decisiones del ciclo-1 (ver cognia_x/manager/architecture.md):
- Backbone HIBRIDO: mayoria de capas de mezcla LINEAL (estado fijo, O(L) en inferencia, recall
  acotado por su estado — exp002) + una MINORIA de capas de ATENCION (recall exacto, KV-cache).
  Ratio recurrente:atencion ~3:1 (D-007). Es el optimo coste<->recall medido (exp005).
- Pre-norm RMSNorm + residuales + MLP SwiGLU. lm_head atado al embedding (barato, D-008).
- Byte-level por defecto (vocab 256): sin tokenizador que entrenar (mas facil + robusto).

Nota de coste: la atencion LINEAL se computa aqui en su forma PARALELA O(L^2) (simple y correcta
para entrenar); es matematicamente identica a su forma recurrente O(L) de inferencia (estado d x d).
La ventaja de banda del hibrido es de INFERENCIA (forma recurrente) — esto es entrenamiento.

Objetivo del proyecto: barata, facil de entrenar, inteligente.
"""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class HybridConfig:
    vocab_size: int = 256
    d_model: int = 256
    n_layers: int = 8
    n_heads: int = 8
    d_ff: int = None          # default ~8/3 * d_model (SwiGLU)
    window: int = 128         # ventana de la atencion deslizante; >= max_seq_len => atencion global
    attn_every: int = 4       # 1 de cada `attn_every` capas es atencion; resto lineal. <=0 => todo lineal; ==1 => todo atencion
    max_seq_len: int = 512
    tie_embeddings: bool = True
    abs_pos_emb: bool = False   # embeddings de posicion absolutos aprendidos (ademas de RoPE en attn)
    # Lever de FRONTERA DE RECALL (Arora et al. 2024, "Based", arXiv:2402.18668): la dimension del
    # FEATURE MAP de la atencion lineal controla cuanto recall asociativo entra en el estado. Con
    # mult=1 (default) NADA cambia: q,k pasan directo por elu+1 sobre d_head (comportamiento previo).
    # Con mult>1 se proyectan q,k a d_head*mult ANTES de elu+1 -> feature map mas ancho -> el estado
    # recurrente crece de d_head^2 a (mult*d_head)^2. Coste por token O(d) -> O(mult*d). Solo afecta
    # capas LINEALES (la atencion softmax no usa este lever). Ver exp010.
    linear_feature_mult: int = 1

    def __post_init__(self):
        if self.d_ff is None:
            self.d_ff = max(16, int(round(8 * self.d_model / 3 / 16)) * 16)
        assert self.d_model % self.n_heads == 0, "d_model debe ser divisible por n_heads"
        # RoPE rota pares (i, i+d_head/2): d_head debe ser par o apply_rope rompe por shape.
        assert (self.d_model // self.n_heads) % 2 == 0, \
            "d_head (d_model//n_heads) debe ser par para RoPE"

    def layer_types(self):
        types = []
        for i in range(self.n_layers):
            if self.attn_every <= 0:
                types.append("linear")
            elif self.attn_every == 1:
                types.append("attn")
            else:
                types.append("attn" if (i % self.attn_every == self.attn_every - 1) else "linear")
        return types


def build_rope_cache(seq_len, dh, device, base=10000.0):
    """Tabla RoPE (cos,sin) de forma (L, dh). dh debe ser par."""
    half = dh // 2
    inv_freq = 1.0 / (base ** (torch.arange(0, half, device=device).float() / half))
    pos = torch.arange(seq_len, device=device).float()
    ang = torch.outer(pos, inv_freq)            # L, half
    emb = torch.cat([ang, ang], dim=-1)         # L, dh
    return emb.cos(), emb.sin()


def apply_rope(x, cos, sin):
    """Aplica RoPE a x de forma (B,h,L,dh). cos/sin: (L,dh)."""
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
    """Atencion lineal causal multi-cabeza (feature map elu+1). Estado acotado d_head x d_head.
    Forma paralela O(L^2) para entrenar = identica a la recurrente O(L) de inferencia.

    feature_mult (default 1): dimension del FEATURE MAP por cabeza (lever de frontera de recall,
    Based/Arora 2024). Con mult==1 NO hay proyeccion extra y el codigo es identico al previo. Con
    mult>1 se proyecta q,k de d_head a d_head*mult (Linear sin bias) ANTES de elu+1: feature map mas
    ancho -> el estado recurrente crece de d_head^2 a (mult*d_head)^2 y el coste de la feature por
    token de O(d_head) a O(mult*d_head). v y la salida o quedan en d_head (no cambia el ancho del
    residual): solo cambia el ANCHO de q,k que arma el estado clave-valor."""

    def __init__(self, d, n_heads, feature_mult=1):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.feature_mult = feature_mult
        self.df = self.dh * feature_mult                  # dimension del feature map por cabeza
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)
        # Proyeccion de feature SOLO si mult>1 (mult==1 -> None -> exacto comportamiento previo).
        if feature_mult > 1:
            self.q_proj = nn.Linear(self.dh, self.df, bias=False)
            self.k_proj = nn.Linear(self.dh, self.df, bias=False)
        else:
            self.q_proj = self.k_proj = None

    def forward(self, x, cos=None, sin=None):       # cos/sin ignorados (kernel positivo)
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]           # B,h,L,dh
        if self.q_proj is not None:                # feature map ancho: q,k -> d_head*mult ANTES de elu+1
            q = self.q_proj(q)
            k = self.k_proj(k)
        q = F.elu(q) + 1.0                          # B,h,L,df  (df = dh si mult==1)
        k = F.elu(k) + 1.0
        scores = torch.matmul(q, k.transpose(-1, -2))     # B,h,L,L  (no normalizado)
        mask = torch.tril(torch.ones(L, L, device=x.device, dtype=torch.bool))
        scores = scores.masked_fill(~mask, 0.0)
        denom = scores.sum(-1, keepdim=True) + 1e-6
        out = torch.matmul(scores, v) / denom             # B,h,L,dh
        out = out.transpose(1, 2).reshape(B, L, D)
        return self.o(out)


class SlidingWindowAttention(nn.Module):
    """Atencion softmax causal restringida a una ventana W (KV-cache O(W) en inferencia).
    Si window >= L, es atencion global."""

    def __init__(self, d, n_heads, window):
        super().__init__()
        self.h = n_heads
        self.dh = d // n_heads
        self.window = window
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)

    def forward(self, x, cos=None, sin=None):
        B, L, D = x.shape
        qkv = self.qkv(x).view(B, L, 3, self.h, self.dh).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        if cos is not None:
            q = apply_rope(q, cos, sin)
            k = apply_rope(k, cos, sin)
        scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(self.dh)   # B,h,L,L
        idx = torch.arange(L, device=x.device)
        causal = idx[None, :] <= idx[:, None]
        windowed = idx[None, :] > (idx[:, None] - self.window)
        mask = causal & windowed                                            # L,L
        scores = scores.masked_fill(~mask, float("-inf"))
        attn = F.softmax(scores, dim=-1)
        out = torch.matmul(attn, v)
        out = out.transpose(1, 2).reshape(B, L, D)
        return self.o(out)


class Block(nn.Module):
    def __init__(self, cfg, kind):
        super().__init__()
        self.kind = kind
        self.norm1 = RMSNorm(cfg.d_model)
        if kind == "attn":
            self.mixer = SlidingWindowAttention(cfg.d_model, cfg.n_heads, cfg.window)
        else:
            self.mixer = LinearAttention(cfg.d_model, cfg.n_heads,
                                         feature_mult=getattr(cfg, "linear_feature_mult", 1))
        self.norm2 = RMSNorm(cfg.d_model)
        self.mlp = SwiGLU(cfg.d_model, cfg.d_ff)

    def forward(self, x, cos=None, sin=None):
        x = x + self.mixer(self.norm1(x), cos, sin)
        x = x + self.mlp(self.norm2(x))
        return x


class HybridLM(nn.Module):
    def __init__(self, cfg: HybridConfig):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos_emb = nn.Embedding(cfg.max_seq_len, cfg.d_model) if cfg.abs_pos_emb else None
        self.blocks = nn.ModuleList([Block(cfg, t) for t in cfg.layer_types()])
        self.dh = cfg.d_model // cfg.n_heads
        cos, sin = build_rope_cache(cfg.max_seq_len, self.dh, device="cpu")
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.norm_f = RMSNorm(cfg.d_model)
        self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        if cfg.tie_embeddings:
            self.lm_head.weight = self.embed.weight
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward_features(self, idx):
        """Devuelve los estados ocultos finales (post norm_f) ANTES de lm_head: (B,L,d_model).
        WHY: el router-LM de CYCLE 19 usa el modelo como ENCODER (representacion del texto), no como
        generador. No toca forward()/generate() -> ningun ciclo previo cambia."""
        x = self.embed(idx)
        L = idx.shape[1]
        if self.pos_emb is not None:
            x = x + self.pos_emb(torch.arange(L, device=idx.device))
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        for b in self.blocks:
            x = b(x, cos, sin)
        return self.norm_f(x)            # (B,L,d_model) pre-lm_head

    def forward(self, idx, targets=None):
        x = self.embed(idx)
        L = idx.shape[1]
        if self.pos_emb is not None:
            x = x + self.pos_emb(torch.arange(L, device=idx.device))
        cos, sin = self.rope_cos[:L].to(x.dtype), self.rope_sin[:L].to(x.dtype)
        for b in self.blocks:
            x = b(x, cos, sin)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-100
            )
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, n_new, temperature=1.0, top_k=None):
        self.eval()
        for _ in range(n_new):
            ctx = idx[:, -self.cfg.max_seq_len:]
            logits, _ = self(ctx)
            logits = logits[:, -1, :] / max(1e-6, temperature)
            if top_k is not None:
                v, _ = torch.topk(logits, top_k)
                logits[logits < v[:, [-1]]] = float("-inf")
            probs = F.softmax(logits, dim=-1)
            nxt = torch.multinomial(probs, 1)
            idx = torch.cat([idx, nxt], dim=1)
        return idx

    def num_params(self):
        n = sum(p.numel() for p in self.parameters())
        if self.cfg.tie_embeddings:
            n -= self.embed.weight.numel()  # contada una sola vez (atada)
        return n

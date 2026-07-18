"""
bdraft/model.py
===============
Cognia-BDraft: block-diffusion draft model (~110M trainable params with the
default config), per planes/DSPARK_GEMMA_DRAFT_MODEL.md section 2.2.

Architecture (DFlash-style, DSpark confidence head):
  - Token embedding + LM head SHARED with the target and FROZEN when passed
    (Qwen2.5-7B-Instruct: d 3584, vocab 152,064). If not passed, the model
    creates its own small trainable ones (test mode, mini config).
  - down_proj target_d_model->d_model brings token embeddings into draft space.
  - mask_embedding: one learned d_model vector for masked canvas positions.
  - n_layers bidirectional transformer blocks (NO causal mask inside the
    block): RMSNorm, RoPE, SwiGLU FFN. Queries come from the canvas only;
    keys/values are [projected target context ; canvas] -> every canvas
    position attends to the verified context AND to every other canvas
    position (this is the "cross-attention to the context" injected in K/V).
  - up_proj d_model->target_d_model so the frozen target LM head applies.
  - confidence head (DSpark): MLP d_model->256->1 + sigmoid per position,
    trained in phase 2 to predict P(token accepted).

Inference: the 8-token canvas is de-masked in ONE forward pass (flash mode);
the target's verification is the "second denoising step".
"""

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class BDraftConfig:
    d_model: int = 1024
    n_layers: int = 6
    n_heads: int = 16
    ffn_dim: int = 4096
    block_size: int = 8
    target_d_model: int = 3584       # Qwen2.5-7B-Instruct hidden size
    vocab_size: int = 152064         # Qwen2.5-7B-Instruct vocab
    rope_theta: float = 1000000.0
    mask_token_id: int = -1          # internal sentinel, NOT a vocab id

    @classmethod
    def mini(cls) -> "BDraftConfig":
        # Tiny config for CPU tests / synthetic overfit runs (<5 min).
        return cls(d_model=64, n_layers=2, n_heads=4, ffn_dim=128,
                   block_size=8, target_d_model=96, vocab_size=512)

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads


class _RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x):
        # Compute in fp32 for stability, cast back (Qwen/Llama style).
        dt = x.dtype
        x = x.float()
        x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return (x * self.weight.float()).to(dt)


def _rope_cos_sin(positions: torch.Tensor, head_dim: int, theta: float,
                  device, dtype):
    # positions: [P] absolute positions -> cos/sin [P, head_dim]
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device,
                                             dtype=torch.float32) / head_dim))
    freqs = positions.to(torch.float32)[:, None] * inv_freq[None, :]  # [P, hd/2]
    emb = torch.cat([freqs, freqs], dim=-1)                           # [P, hd]
    return emb.cos().to(dtype), emb.sin().to(dtype)


def _rotate_half(x):
    half = x.shape[-1] // 2
    return torch.cat([-x[..., half:], x[..., :half]], dim=-1)


def _apply_rope(x, cos, sin):
    # x: [B, n_heads, P, head_dim], cos/sin: [P, head_dim]
    return x * cos[None, None] + _rotate_half(x) * sin[None, None]


class _Block(nn.Module):
    """One bidirectional transformer block with context K/V injection."""

    def __init__(self, cfg: BDraftConfig):
        super().__init__()
        d = cfg.d_model
        self.n_heads = cfg.n_heads
        self.head_dim = cfg.head_dim
        self.attn_norm = _RMSNorm(d)
        self.ctx_norm = _RMSNorm(d)      # normalizes the (static) projected context
        self.q_proj = nn.Linear(d, d, bias=False)
        self.k_proj = nn.Linear(d, d, bias=False)
        self.v_proj = nn.Linear(d, d, bias=False)
        self.o_proj = nn.Linear(d, d, bias=False)
        self.ffn_norm = _RMSNorm(d)
        self.gate_proj = nn.Linear(d, cfg.ffn_dim, bias=False)
        self.up_proj = nn.Linear(d, cfg.ffn_dim, bias=False)
        self.down_proj = nn.Linear(cfg.ffn_dim, d, bias=False)

    def _split(self, x):
        # [B, P, d] -> [B, n_heads, P, head_dim]
        B, P, _ = x.shape
        return x.view(B, P, self.n_heads, self.head_dim).transpose(1, 2)

    def forward(self, x, ctx, cos_ctx, sin_ctx, cos_can, sin_can):
        # x:   [B, block, d]  canvas hidden states (evolve through layers)
        # ctx: [B, T, d]      projected target context (static across layers)
        B = x.shape[0]
        h = self.attn_norm(x)
        c = self.ctx_norm(ctx)
        q = _apply_rope(self._split(self.q_proj(h)), cos_can, sin_can)
        k_can = _apply_rope(self._split(self.k_proj(h)), cos_can, sin_can)
        k_ctx = _apply_rope(self._split(self.k_proj(c)), cos_ctx, sin_ctx)
        v_can = self._split(self.v_proj(h))
        v_ctx = self._split(self.v_proj(c))
        k = torch.cat([k_ctx, k_can], dim=2)   # [B, nh, T+block, hd]
        v = torch.cat([v_ctx, v_can], dim=2)
        # No mask at all: fully bidirectional inside the block + full view
        # of the context. This is the whole point vs a causal draft.
        attn = F.scaled_dot_product_attention(q, k, v)
        attn = attn.transpose(1, 2).reshape(B, -1, self.n_heads * self.head_dim)
        x = x + self.o_proj(attn)
        h = self.ffn_norm(x)
        x = x + self.down_proj(F.silu(self.gate_proj(h)) * self.up_proj(h))
        return x


class BDraft(nn.Module):
    def __init__(self, cfg: BDraftConfig,
                 target_embedding: nn.Embedding | None = None,
                 target_lm_head: nn.Linear | None = None):
        super().__init__()
        self.cfg = cfg
        # Embedding / LM head: shared with the target and FROZEN when passed
        # (freezing mutates the passed module — the target is frozen anyway).
        # When None, create own trainable ones (test mode, mini config).
        if target_embedding is not None:
            target_embedding.requires_grad_(False)
            self.embedding = target_embedding
        else:
            self.embedding = nn.Embedding(cfg.vocab_size, cfg.target_d_model)
        if target_lm_head is not None:
            target_lm_head.requires_grad_(False)
            self.lm_head = target_lm_head
        else:
            self.lm_head = nn.Linear(cfg.target_d_model, cfg.vocab_size, bias=False)
        # Trainable core (~110M with the default config).
        self.down_proj = nn.Linear(cfg.target_d_model, cfg.d_model, bias=False)
        self.ctx_proj = nn.Linear(cfg.target_d_model, cfg.d_model, bias=False)
        self.mask_embedding = nn.Parameter(torch.zeros(cfg.d_model))
        self.layers = nn.ModuleList(_Block(cfg) for _ in range(cfg.n_layers))
        self.final_norm = _RMSNorm(cfg.d_model)
        self.up_proj = nn.Linear(cfg.d_model, cfg.target_d_model, bias=False)
        # DSpark-style confidence head: per-position P(token accepted).
        self.conf_head = nn.Sequential(
            nn.Linear(cfg.d_model, 256), nn.SiLU(), nn.Linear(256, 1))
        self.reset_parameters()

    def reset_parameters(self):
        # nn.Linear default init is fine for the projections; just give the
        # mask embedding a small random start so it is not a dead zero vector.
        nn.init.normal_(self.mask_embedding, std=0.02)

    def forward_hidden(self, ctx_hidden: torch.Tensor,
                       canvas_tokens: torch.Tensor,
                       canvas_mask: torch.Tensor) -> torch.Tensor:
        """Backbone only: returns draft hidden states [B, block, d_model]
        (post final_norm, pre up_proj). Used by confidence() and by the
        training loop for chunked cross-entropy."""
        cfg = self.cfg
        B, T, _ = ctx_hidden.shape
        block = canvas_tokens.shape[1]
        # Canvas embeddings: masked positions may carry the -1 sentinel, so
        # clamp before the embedding lookup and overwrite them right after.
        safe_tokens = canvas_tokens.clamp_min(0)
        tok = self.down_proj(self.embedding(safe_tokens))      # [B, block, d]
        mask_vec = self.mask_embedding.to(tok.dtype).expand_as(tok)
        x = torch.where(canvas_mask.unsqueeze(-1), mask_vec, tok)
        # Target context projected once, K/V-injected in every layer.
        ctx = self.ctx_proj(ctx_hidden)                        # [B, T, d]
        # RoPE positions: context occupies 0..T-1, canvas T..T+block-1.
        dev, dt = x.device, x.dtype
        cos_ctx, sin_ctx = _rope_cos_sin(
            torch.arange(T, device=dev), cfg.head_dim, cfg.rope_theta, dev, dt)
        cos_can, sin_can = _rope_cos_sin(
            torch.arange(T, T + block, device=dev), cfg.head_dim,
            cfg.rope_theta, dev, dt)
        for layer in self.layers:
            x = layer(x, ctx, cos_ctx, sin_ctx, cos_can, sin_can)
        return self.final_norm(x)

    def forward(self, ctx_hidden: torch.Tensor, canvas_tokens: torch.Tensor,
                canvas_mask: torch.Tensor) -> torch.Tensor:
        """ctx_hidden [B,T,target_d_model], canvas_tokens [B,block],
        canvas_mask [B,block] (True = masked) -> logits [B,block,vocab]."""
        hidden = self.forward_hidden(ctx_hidden, canvas_tokens, canvas_mask)
        return self.lm_head(self.up_proj(hidden))

    def confidence(self, draft_hidden_or_logits: torch.Tensor) -> torch.Tensor:
        """[B, block, d_model] draft hidden states (from forward_hidden) ->
        [B, block] in [0,1]: estimated P(token survives verification)."""
        if draft_hidden_or_logits.shape[-1] != self.cfg.d_model:
            raise ValueError(
                "confidence() expects d_model=%d hidden states, got last dim %d"
                % (self.cfg.d_model, draft_hidden_or_logits.shape[-1]))
        return torch.sigmoid(self.conf_head(draft_hidden_or_logits)).squeeze(-1)

    def num_trainable_params(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

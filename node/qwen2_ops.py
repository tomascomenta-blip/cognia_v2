"""
node/qwen2_ops.py
=================
Qwen2 numpy operators for shard-local inference without PyTorch.

INT4Weights      — nibble-packed weights with dequantize-on-demand matmul.
RealTransformerLayer — full Qwen2 decoder layer (RMSNorm, RoPE, GQA, SwiGLU).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Tuple

from shattering.quantization import quantize_int4, dequantize_int4


# ── INT4 weight storage ──────────────────────────────────────────────────────

@dataclass
class INT4Weights:
    packed:    np.ndarray   # (out_features, ceil(in_features/2)) uint8
    scale:     np.ndarray   # (out_features, 1) float32
    orig_cols: int          # in_features before nibble padding

    @classmethod
    def from_float32(cls, W: np.ndarray) -> "INT4Weights":
        packed, scale = quantize_int4(W.astype(np.float32))
        return cls(packed=packed, scale=scale, orig_cols=W.shape[1])

    def dequantize(self) -> np.ndarray:
        return dequantize_int4(self.packed, self.scale, self.orig_cols)

    def linear(self, x: np.ndarray) -> np.ndarray:
        """Compute x @ W^T with on-demand dequantization to float32."""
        return x @ self.dequantize().T


# ── Qwen2 math primitives ────────────────────────────────────────────────────

def _rms_norm(x: np.ndarray, weight: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    rms = np.sqrt((x * x).mean(-1, keepdims=True) + eps)
    return (x / rms) * weight


def _silu(x: np.ndarray) -> np.ndarray:
    return x * (1.0 / (1.0 + np.exp(-x.clip(-30, 30))))


def _rotate_half(x: np.ndarray) -> np.ndarray:
    h = x.shape[-1] // 2
    return np.concatenate([-x[..., h:], x[..., :h]], axis=-1)


def _precompute_rope(
    seq_len: int, head_dim: int, rope_theta: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns (cos, sin) each of shape (seq_len, head_dim) float32.
    Frequencies are repeated so the same array applies to both halves.
    """
    half  = head_dim // 2
    freq  = 1.0 / (rope_theta ** (np.arange(0, half, dtype=np.float32) / half))
    t     = np.outer(np.arange(seq_len, dtype=np.float32), freq)  # (seq, half)
    cos   = np.concatenate([np.cos(t), np.cos(t)], axis=-1).astype(np.float32)
    sin   = np.concatenate([np.sin(t), np.sin(t)], axis=-1).astype(np.float32)
    return cos, sin


def _apply_rope(
    x: np.ndarray, cos: np.ndarray, sin: np.ndarray
) -> np.ndarray:
    """x: (seq, n_heads, head_dim); cos/sin: (seq, head_dim)."""
    return x * cos[:, None, :] + _rotate_half(x) * sin[:, None, :]


# ── Qwen2 decoder layer ──────────────────────────────────────────────────────

class RealTransformerLayer:
    """
    Single Qwen2 transformer decoder layer in pure numpy.

    All projection weights are stored as INT4Weights (nibble-packed).
    Norm weights stay float32 (negligible size).
    """

    def __init__(
        self,
        n_heads: int,
        n_kv_heads: int,
        head_dim: int,
        rope_theta: float,
        rms_norm_eps: float,
        w_q: INT4Weights,
        w_k: INT4Weights,
        w_v: INT4Weights,
        w_o: INT4Weights,
        w_gate: INT4Weights,
        w_up: INT4Weights,
        w_down: INT4Weights,
        norm1: np.ndarray,
        norm2: np.ndarray,
    ):
        self.n_heads    = n_heads
        self.n_kv_heads = n_kv_heads
        self.head_dim   = head_dim
        self.rope_theta = rope_theta
        self.rms_eps    = rms_norm_eps
        self.w_q = w_q;  self.w_k = w_k;  self.w_v = w_v;  self.w_o = w_o
        self.w_gate = w_gate;  self.w_up = w_up;  self.w_down = w_down
        self.norm1 = norm1.astype(np.float32)
        self.norm2 = norm2.astype(np.float32)

    def forward(self, x: np.ndarray) -> np.ndarray:
        """x: (seq, hidden_dim) float32 → (seq, hidden_dim) float32."""
        x = x.astype(np.float32)
        x = x + self._attention(_rms_norm(x, self.norm1, self.rms_eps))
        x = x + self._mlp(_rms_norm(x, self.norm2, self.rms_eps))
        return x

    def _attention(self, x: np.ndarray) -> np.ndarray:
        seq   = x.shape[0]
        H, KH, D = self.n_heads, self.n_kv_heads, self.head_dim
        group = H // KH

        Q    = self.w_q.linear(x).reshape(seq, H, D)
        k_raw = self.w_k.linear(x)
        if getattr(self, "_lora_k", None) is not None:
            k_raw = k_raw + self._lora_k.delta(x)
        K = k_raw.reshape(seq, KH, D)
        v_raw = self.w_v.linear(x)
        if getattr(self, "_lora_v", None) is not None:
            v_raw = v_raw + self._lora_v.delta(x)
        V = v_raw.reshape(seq, KH, D)

        cos, sin = _precompute_rope(seq, D, self.rope_theta)
        Q = _apply_rope(Q, cos, sin)
        K = _apply_rope(K, cos, sin)

        # GQA: expand K, V to match n_heads
        K = np.repeat(K, group, axis=1)   # (seq, H, D)
        V = np.repeat(V, group, axis=1)   # (seq, H, D)

        # Scaled dot-product with causal mask
        scores  = np.einsum("qhd,khd->hqk", Q, K) / np.sqrt(D)  # (H, seq, seq)
        mask    = np.triu(np.full((seq, seq), -1e9, dtype=np.float32), k=1)
        scores += mask[None]
        scores -= scores.max(-1, keepdims=True)
        probs   = np.exp(scores); probs /= probs.sum(-1, keepdims=True)

        out = np.einsum("hqk,khd->qhd", probs, V).reshape(seq, H * D)
        return self.w_o.linear(out)

    def _mlp(self, x: np.ndarray) -> np.ndarray:
        return self.w_down.linear(_silu(self.w_gate.linear(x)) * self.w_up.linear(x))

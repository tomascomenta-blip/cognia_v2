"""
node/nano_draft.py
==================
NanoDraft — 2-layer transformer with hidden=256, same vocab as Qwen2.5.
Used for speculative decoding: generates N draft tokens in ~2 ms, which the
main model then verifies in a single batched forward pass.

Build weights once with: python scripts/build_draft_model.py

KV-cache: context is cached between consecutive draft() calls so only
new tokens (typically 1-2 per step) are processed, not the full prefix.
This keeps draft generation fast even as generated_ids grows.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np


_NANO_HIDDEN  = 256
_NANO_HEADS   = 4
_NANO_KV_HEADS = 1
_NANO_HEAD_DIM = _NANO_HIDDEN // _NANO_HEADS   # 64
_NANO_MLP     = 1024
_VOCAB        = 151936
_MAX_CTX      = 64    # max context tokens fed to draft model per call


def _rms_norm(x: np.ndarray, w: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    x32 = x.astype(np.float32)
    rms = np.sqrt((x32 * x32).mean(-1, keepdims=True) + eps)
    return (x32 / rms) * w


def _silu(x: np.ndarray) -> np.ndarray:
    x32 = x.astype(np.float32)
    return x32 * (1.0 / (1.0 + np.exp(-x32.clip(-30, 30))))


def _rope(x: np.ndarray, offset: int = 0, theta: float = 10_000.0) -> np.ndarray:
    """Apply RoPE to x: (seq, n_heads, head_dim) float32."""
    seq, H, D = x.shape
    half = D // 2
    freq = 1.0 / (theta ** (np.arange(half, dtype=np.float32) / half))
    t    = np.arange(offset, offset + seq, dtype=np.float32)
    cos  = np.cos(np.outer(t, freq))
    sin  = np.sin(np.outer(t, freq))
    cos  = np.concatenate([cos, cos], axis=-1)   # (seq, D)
    sin  = np.concatenate([sin, sin], axis=-1)
    rot  = np.concatenate([-x[..., half:], x[..., :half]], axis=-1)
    return x * cos[:, None, :] + rot * sin[:, None, :]


# ── per-layer KV state ─────────────────────────────────────────────────────

# Each entry is (K_raw, V_raw): (total_seq, KH, D) float32.
# Not GQA-expanded — expanded on-the-fly during attention.
_LayerKV = Tuple[np.ndarray, np.ndarray]


class NanoDraft:
    """
    2-layer 256-dim transformer for speculative draft generation.
    Weights are distilled from the first 2 layers of shard_0 via PCA projection.

    Incremental KV-cache: consecutive draft() calls on growing context
    only process the NEW tokens (past K/V reused for the cached prefix).
    """

    def __init__(self, weights_path: str):
        w = np.load(weights_path)
        self._embed   = w["embed"].astype(np.float32)     # (vocab, 256)
        self._lm_head = w["lm_head"].astype(np.float32)  # (vocab, 256)
        self._norm_f  = w["norm_f"].astype(np.float32)   # (256,)
        self._layers  = []
        for i in range(2):
            self._layers.append({
                "q":    w[f"l{i}_q"].astype(np.float32),     # (256, 256)
                "k":    w[f"l{i}_k"].astype(np.float32),     # (64, 256)
                "v":    w[f"l{i}_v"].astype(np.float32),     # (64, 256)
                "o":    w[f"l{i}_o"].astype(np.float32),     # (256, 256)
                "gate": w[f"l{i}_gate"].astype(np.float32),  # (1024, 256)
                "up":   w[f"l{i}_up"].astype(np.float32),    # (1024, 256)
                "down": w[f"l{i}_down"].astype(np.float32),  # (256, 1024)
                "n1":   w[f"l{i}_n1"].astype(np.float32),    # (256,)
                "n2":   w[f"l{i}_n2"].astype(np.float32),    # (256,)
            })

        # Incremental KV-cache for the context prefix
        self._ctx_kv:  List[Optional[_LayerKV]] = [None] * 2
        self._ctx_ids: np.ndarray = np.empty(0, dtype=np.int32)

    # ── Public API ─────────────────────────────────────────────────────────

    def draft(self, context_ids: np.ndarray, n: int = 6) -> list:
        """
        Generate n draft token IDs autoregressively from context.
        Context is truncated to _MAX_CTX tokens.
        Incremental: only processes tokens beyond the cached prefix.
        """
        ids = context_ids[-_MAX_CTX:] if len(context_ids) > _MAX_CTX else context_ids

        # Determine how many tokens are already in the KV-cache
        cached_n = self._cached_prefix_len(ids)
        if cached_n < len(ids):
            new_ids  = ids[cached_n:]
            x_emb    = self._embed[new_ids]   # (new_seq, 256)
            x, kv    = self._forward_incremental(x_emb, self._ctx_kv, offset=cached_n)
            self._ctx_kv  = kv
            self._ctx_ids = ids.copy()
        else:
            # Context unchanged — recover last hidden from cache
            x_emb = self._embed[ids[-1:]]     # (1, 256)
            x, kv = self._forward_incremental(x_emb, self._ctx_kv, offset=len(ids) - 1)
            # Don't update _ctx_kv (kv already has the full context)

        x = _rms_norm(x[-1:], self._norm_f)   # (1, 256) — last position

        # Generate N draft tokens; accumulate their KV but don't save to _ctx_kv
        draft_kv = [
            (kv[i][0].copy(), kv[i][1].copy()) if kv[i] is not None else None
            for i in range(len(self._layers))
        ]
        tokens   = []
        base_len = len(ids)

        for step in range(n):
            logits = x @ self._lm_head.T
            tok_id = int(np.argmax(logits[0]))
            tokens.append(tok_id)

            x_in          = self._embed[tok_id:tok_id + 1]   # (1, 256)
            x, draft_kv   = self._forward_incremental(x_in, draft_kv,
                                                       offset=base_len + step)

            x = _rms_norm(x, self._norm_f)

        return tokens

    def reset_cache(self) -> None:
        """Clear the KV-cache (call when context is unrelated to previous calls)."""
        self._ctx_kv  = [None] * len(self._layers)
        self._ctx_ids = np.empty(0, dtype=np.int32)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _cached_prefix_len(self, ids: np.ndarray) -> int:
        """
        Return how many leading tokens of `ids` match the cached context.
        Returns 0 if no prefix matches (triggers full rebuild).
        """
        prev = self._ctx_ids
        if len(prev) == 0 or self._ctx_kv[0] is None:
            return 0
        min_len = min(len(prev), len(ids))
        if not np.array_equal(ids[:min_len], prev[:min_len]):
            return 0
        return min_len

    def _forward_incremental(
        self,
        x_in: np.ndarray,
        kv_list: List[Optional[_LayerKV]],
        offset: int,
    ) -> Tuple[np.ndarray, List[_LayerKV]]:
        """
        Forward `x_in` (seq, 256) through all layers using past KV from kv_list.
        Returns (output, updated_kv_list).
        `offset` is the absolute position of x_in[0] in the full sequence.
        """
        x        = x_in.astype(np.float32)
        new_kvs: List[_LayerKV] = []

        for i, L in enumerate(self._layers):
            kv_past = kv_list[i] if kv_list else None
            x_n     = _rms_norm(x, L["n1"])
            attn_out, K_full, V_full = self._attn_kv(x_n, L, offset, kv_past)
            x       = x + attn_out
            x_n     = _rms_norm(x, L["n2"])
            x       = x + self._mlp(x_n, L)
            new_kvs.append((K_full, V_full))

        return x, new_kvs

    def _attn_kv(
        self,
        x: np.ndarray,
        L: dict,
        offset: int,
        kv_past: Optional[_LayerKV],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Attention with optional past K/V.
        Returns (output, K_full_raw, V_full_raw) where K_full_raw is (total, KH, D).
        """
        seq = x.shape[0]
        H, KH, D = _NANO_HEADS, _NANO_KV_HEADS, _NANO_HEAD_DIM

        Q     = (x @ L["q"].T).reshape(seq, H, D).astype(np.float32)
        K_new = (x @ L["k"].T).reshape(seq, KH, D).astype(np.float32)
        V_new = (x @ L["v"].T).reshape(seq, KH, D).astype(np.float32)

        Q     = _rope(Q, offset=offset)
        K_new = _rope(K_new, offset=offset)

        if kv_past is not None:
            K_past, V_past = kv_past
            K_full = np.concatenate([K_past, K_new], axis=0)   # (past+seq, KH, D)
            V_full = np.concatenate([V_past, V_new], axis=0)
        else:
            K_full, V_full = K_new, V_new

        past_len = K_full.shape[0] - seq

        # GQA expand for attention scoring
        K_exp = np.repeat(K_full, H // KH, axis=1)   # (total, H, D)
        V_exp = np.repeat(V_full, H // KH, axis=1)

        scale  = 1.0 / np.sqrt(D)
        scores = np.einsum("qhd,khd->hqk", Q, K_exp) * scale   # (H, seq, total)

        if seq > 1 or past_len > 0:
            total = K_full.shape[0]
            q_abs = np.arange(past_len, past_len + seq,  dtype=np.int32).reshape(-1, 1)
            k_abs = np.arange(0,        total,            dtype=np.int32).reshape(1, -1)
            future = (k_abs > q_abs).astype(np.float32) * -1e9
            scores = scores + future[None]

        scores -= scores.max(-1, keepdims=True)
        probs   = np.exp(scores); probs /= probs.sum(-1, keepdims=True)

        out = np.einsum("hqk,khd->qhd", probs, V_exp).reshape(seq, H * D)
        return out @ L["o"].T, K_full, V_full

    def _mlp(self, x: np.ndarray, L: dict) -> np.ndarray:
        return _silu(x @ L["gate"].T) * (x @ L["up"].T) @ L["down"].T

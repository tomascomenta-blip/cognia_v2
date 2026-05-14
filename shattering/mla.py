"""
shattering/mla.py
==================
Multi-Head Latent Attention (MLA) — compressed KV-cache for ShardEngine.

Based on DeepSeek-V3 MLA design: instead of caching full K and V tensors per
layer, we cache a compressed latent representation (dimension d_c << n_kv_heads*head_dim).
K and V are reconstructed from the latent via learned up-projection matrices.

Memory comparison (per layer at T=512, Llama 3.2-3B defaults):
  Standard GQA:  n_kv_heads(8) * T * head_dim(128) * 2 = 1 MB/layer * 28 = 28 MB
  MLA (d_c=512): d_c * T * 2 bytes = 0.5 MB/layer * 28 = 14 MB

Primary benefit on Llama 3.2-3B (already GQA): enables longer contexts by
halving the per-token cache cost, rather than a dramatic memory reduction.

Simulation mode:
  All weight matrices default to identity/zeros — no RAM wasted on large tensors.
  The cache is still populated and cleared per session, so the interface is
  exercised in tests without needing real model weights.

Integration:
  1. Create MLAModule per shard layer.
  2. Call patch_shard_engine_mla(engine) to replace each layer's self_attn.
  3. Thread session_id through forward() calls — ShardEngine.forward() gains
     a session_id parameter; ShardEngine.clear_cache(session_id) on expiry.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

import numpy as np

from shattering.model_constants import (
    LLAMA_32_3B,
    MLA_D_C,
    MLA_D_C_PRIME,
    MLA_HEAD_DIM_ASSUMED,
    MLA_N_HEADS_ASSUMED,
    MLA_N_KV_HEADS_ASSUMED,
)

logger = logging.getLogger(__name__)

_HIDDEN_DIM = LLAMA_32_3B["hidden_dim"]   # 3072


# ── Compressed KV Cache ─────────────────────────────────────────────────

class CompressedKVCache:
    """
    Per-session KV cache storing compressed latents (d_c dim) per layer.

    Storage layout:
      _cache[session_id][layer_idx] = (c_kv, position)
      c_kv:     (seq_len, d_c) float32 — compressed KV latent
      position: int — number of tokens cached so far
    """

    def __init__(self):
        self._cache: Dict[str, Dict[int, Tuple[np.ndarray, int]]] = {}
        self._last_access: Dict[str, float] = {}

    def get(self, session_id: str, layer_idx: int) -> Optional[Tuple[np.ndarray, int]]:
        self._last_access[session_id] = time.monotonic()
        return self._cache.get(session_id, {}).get(layer_idx)

    def put(self, session_id: str, layer_idx: int,
            c_kv: np.ndarray, position: int) -> None:
        if session_id not in self._cache:
            self._cache[session_id] = {}
        self._cache[session_id][layer_idx] = (c_kv, position)
        self._last_access[session_id] = time.monotonic()

    def clear(self, session_id: str) -> None:
        self._cache.pop(session_id, None)
        self._last_access.pop(session_id, None)

    def evict_stale(self, max_age_seconds: float = 3600.0) -> int:
        """Remove sessions not accessed within max_age_seconds. Returns eviction count."""
        now = time.monotonic()
        stale = [
            sid for sid, t in self._last_access.items()
            if now - t > max_age_seconds
        ]
        for sid in stale:
            self._cache.pop(sid, None)
            self._last_access.pop(sid, None)
        if stale:
            logger.debug("[MLA] Evicted %d stale KV-cache sessions", len(stale))
        return len(stale)

    def active_sessions(self) -> int:
        return len(self._cache)


# ── MLA Module ──────────────────────────────────────────────────────────

class MLAModule:
    """
    Drop-in replacement for LlamaAttention that uses a compressed KV cache.

    In simulation mode weight matrices are None and the module acts as a
    pass-through while still populating the cache with zero-compressed latents
    so the session lifecycle is exercised.
    """

    def __init__(
        self,
        layer_idx: int,
        kv_cache: CompressedKVCache,
        hidden_dim: int = _HIDDEN_DIM,
        d_c: int = MLA_D_C,
        d_c_prime: int = MLA_D_C_PRIME,
        n_heads: int = MLA_N_HEADS_ASSUMED,
        n_kv_heads: int = MLA_N_KV_HEADS_ASSUMED,
        head_dim: int = MLA_HEAD_DIM_ASSUMED,
        simulation: bool = True,
    ):
        self.layer_idx  = layer_idx
        self.kv_cache   = kv_cache
        self.hidden_dim = hidden_dim
        self.d_c        = d_c
        self.d_c_prime  = d_c_prime
        self.n_heads    = n_heads
        self.n_kv_heads = n_kv_heads
        self.head_dim   = head_dim
        self.simulation = simulation

        # Projection matrices — None until load_weights() is called
        self._W_DKV: Optional[np.ndarray] = None  # (hidden_dim, d_c)
        self._W_UK:  Optional[np.ndarray] = None  # (d_c, n_kv_heads * head_dim)
        self._W_UV:  Optional[np.ndarray] = None  # (d_c, n_kv_heads * head_dim)
        self._W_DQ:  Optional[np.ndarray] = None  # (hidden_dim, d_c_prime)
        self._W_UQ:  Optional[np.ndarray] = None  # (d_c_prime, n_heads * head_dim)

    def load_weights(
        self,
        W_DKV: np.ndarray,
        W_UK:  np.ndarray,
        W_UV:  np.ndarray,
        W_DQ:  np.ndarray,
        W_UQ:  np.ndarray,
    ) -> None:
        """Load MLA projection matrices from numpy arrays."""
        self._W_DKV = np.asarray(W_DKV, dtype=np.float32)
        self._W_UK  = np.asarray(W_UK,  dtype=np.float32)
        self._W_UV  = np.asarray(W_UV,  dtype=np.float32)
        self._W_DQ  = np.asarray(W_DQ,  dtype=np.float32)
        self._W_UQ  = np.asarray(W_UQ,  dtype=np.float32)
        self.simulation = False

    def forward(
        self,
        hidden: np.ndarray,
        session_id: Optional[str] = None,
        position: int = 0,
    ) -> np.ndarray:
        """
        Forward pass with optional KV-cache population.

        Args:
            hidden:     (seq_len, hidden_dim) float32
            session_id: if provided, cache the compressed KV latent for this layer
            position:   token position offset (for cache retrieval)

        Returns:
            (seq_len, hidden_dim) float32 — pass-through in simulation mode
        """
        seq_len = hidden.shape[0]

        if session_id is not None:
            if self.simulation or self._W_DKV is None:
                # Simulation: cache a zero latent to exercise the lifecycle
                c_kv = np.zeros((seq_len, self.d_c), dtype=np.float32)
            else:
                c_kv = hidden @ self._W_DKV                  # (seq, d_c)

            self.kv_cache.put(session_id, self.layer_idx, c_kv, position + seq_len)

        if self.simulation or self._W_DKV is None:
            return hidden                                      # pass-through

        # Full MLA forward (real weights):
        # 1. Compress KV
        c_kv  = hidden @ self._W_DKV                         # (seq, d_c)
        K_up  = c_kv  @ self._W_UK                           # (seq, n_kv*head)
        V_up  = c_kv  @ self._W_UV                           # (seq, n_kv*head)

        # 2. Compress Q
        c_q   = hidden @ self._W_DQ                          # (seq, d_c')
        Q_up  = c_q   @ self._W_UQ                           # (seq, n_h*head)

        # 3. Scaled dot-product attention (simplified: no masking / RoPE)
        n_h, n_kv, hd = self.n_heads, self.n_kv_heads, self.head_dim
        Q = Q_up.reshape(seq_len, n_h,  hd)
        K = K_up.reshape(seq_len, n_kv, hd)
        V = V_up.reshape(seq_len, n_kv, hd)

        # GQA: repeat K/V heads to match Q heads
        repeats = n_h // n_kv
        K = np.repeat(K, repeats, axis=1)                    # (seq, n_h, hd)
        V = np.repeat(V, repeats, axis=1)

        scale  = hd ** -0.5
        scores = np.einsum("shd,thd->sht", Q, K) * scale    # (seq, n_h, seq)
        attn   = self._softmax(scores, axis=-1)
        out    = np.einsum("sht,thd->shd", attn, V)          # (seq, n_h, hd)
        return out.reshape(seq_len, self.hidden_dim)

    @staticmethod
    def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
        x_shifted = x - x.max(axis=axis, keepdims=True)
        exp_x     = np.exp(x_shifted.clip(-30, 30))
        return exp_x / exp_x.sum(axis=axis, keepdims=True).clip(1e-9)


# ── Patch helper ────────────────────────────────────────────────────────

def patch_shard_engine_mla(shard_engine, kv_cache: Optional[CompressedKVCache] = None):
    """
    Replace each layer's self_attn with an MLAModule and attach the shared
    kv_cache to the engine.

    In simulation mode the MLAModule acts as pass-through but still populates
    the cache, so session lifecycle tests work without real weights.

    Args:
        shard_engine: ShardEngine instance (real or simulation)
        kv_cache:     shared CompressedKVCache; a new one is created if None

    Returns:
        The kv_cache instance used (create-or-reuse pattern).
    """
    if kv_cache is None:
        kv_cache = CompressedKVCache()

    simulation = getattr(shard_engine, "mode", "sim") != "real"
    patched    = 0

    for i, layer in enumerate(getattr(shard_engine, "_layers", [])):
        layer_idx = shard_engine.config.layer_start + i
        mla       = MLAModule(
            layer_idx  = layer_idx,
            kv_cache   = kv_cache,
            simulation = simulation,
        )
        if hasattr(layer, "self_attn"):
            layer.self_attn = mla
            patched += 1

    # Attach cache and clear helper to the engine for session management
    shard_engine._kv_cache = kv_cache

    if not hasattr(shard_engine, "clear_cache"):
        def _clear(session_id: str) -> None:
            shard_engine._kv_cache.clear(session_id)
        shard_engine.clear_cache = _clear

    logger.info(
        "[MLA] Patched %d attention layers in shard %d (sim=%s)",
        patched, shard_engine.config.shard_index, simulation,
    )
    return kv_cache

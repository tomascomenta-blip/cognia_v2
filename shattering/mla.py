"""
shattering/mla.py
==================
Multi-Head Latent Attention (MLA) — compressed KV-cache for ShardEngine.

Based on DeepSeek-V3 MLA design: instead of caching full K and V tensors per
layer, we cache a compressed latent representation (dimension d_c << n_kv_heads*head_dim).
K and V are reconstructed from the latent via learned up-projection matrices.

Memory comparison (per layer at T=512, Qwen2.5-Coder-3B defaults):
  Standard GQA:  n_kv_heads(2) * T * head_dim(128) * 2 = 0.25 MB/layer * 36 = 9 MB
  MLA (d_c=512): d_c * T * 2 bytes = 0.5 MB/layer * 36 = 18 MB

Note: Qwen already uses aggressive GQA (n_kv_heads=2), so MLA's primary benefit
here is enabling longer contexts with stable cache growth, not memory reduction.

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
import threading
import time
from typing import Dict, Optional, Tuple

import numpy as np

from shattering.model_constants import (
    QWEN25_CODER_3B,
    MLA_D_C,
    MLA_D_C_PRIME,
    MLA_HEAD_DIM_ASSUMED,
    MLA_N_HEADS_ASSUMED,
    MLA_N_KV_HEADS_ASSUMED,
)

logger = logging.getLogger(__name__)

_HIDDEN_DIM = QWEN25_CODER_3B["hidden_dim"]   # 2048


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
        # The inference token loop runs in a thread pool (orchestrator.ainfer ->
        # run_in_executor) and eviction is triggered from infer() on any thread,
        # so concurrent put()/get() vs evict_stale() can mutate these dicts while
        # evict_stale() iterates them (RuntimeError: dictionary changed size).
        # Mirror the lock idiom used by every other shared cache (LPC, router,
        # FragmentManager, DynamicWeights).
        self._lock = threading.RLock()

    def get(self, session_id: str, layer_idx: int) -> Optional[Tuple[np.ndarray, int]]:
        with self._lock:
            self._last_access[session_id] = time.monotonic()
            return self._cache.get(session_id, {}).get(layer_idx)

    def put(self, session_id: str, layer_idx: int,
            c_kv: np.ndarray, position: int) -> None:
        with self._lock:
            if session_id not in self._cache:
                self._cache[session_id] = {}
            self._cache[session_id][layer_idx] = (c_kv, position)
            self._last_access[session_id] = time.monotonic()

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._cache.pop(session_id, None)
            self._last_access.pop(session_id, None)

    def evict_stale(self, max_age_seconds: float = 3600.0) -> int:
        """Remove sessions not accessed within max_age_seconds. Returns eviction count."""
        now = time.monotonic()
        with self._lock:
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
        with self._lock:
            return len(self._cache)

    def truncate(self, session_id: str, layer_idx: int, max_len: int) -> None:
        """Truncate cached KV latent to max_len tokens (speculative decoding rollback)."""
        with self._lock:
            entry = self._cache.get(session_id, {}).get(layer_idx)
            if entry is not None:
                c_kv, _ = entry
                self._cache[session_id][layer_idx] = (c_kv[:max_len], max_len)


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
        rope_theta: float = 10_000_000.0,
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
        self.rope_theta = rope_theta
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
        Forward pass with KV-cache retrieval and update.

        Args:
            hidden:     (seq_len, hidden_dim) float32 — current tokens only
            session_id: if provided, retrieve past KV latents and cache new ones
            position:   token position offset (for RoPE; inferred from cache if 0)

        Returns:
            (seq_len, hidden_dim) float32 — pass-through in simulation mode
        """
        seq_len = hidden.shape[0]

        if self.simulation or self._W_DKV is None:
            # Simulation: cache zero latent to exercise lifecycle, then pass through
            if session_id is not None:
                c_kv_new = np.zeros((seq_len, self.d_c), dtype=np.float32)
                cached    = self.kv_cache.get(session_id, self.layer_idx)
                if cached is not None:
                    c_kv_past, past_pos = cached
                    c_kv_full = np.concatenate([c_kv_past, c_kv_new], axis=0)
                    new_pos   = past_pos + seq_len
                else:
                    c_kv_full = c_kv_new
                    new_pos   = seq_len
                self.kv_cache.put(session_id, self.layer_idx, c_kv_full, new_pos)
            return hidden

        # ── Real weights path ─────────────────────────────────────────────

        from node.qwen2_ops import _precompute_rope, _apply_rope

        n_h, n_kv, hd = self.n_heads, self.n_kv_heads, self.head_dim

        # 1. Compress current input into KV latent
        c_kv_new = hidden @ self._W_DKV                      # (seq, d_c)

        # 2. Retrieve and extend past KV latent from cache
        if session_id is not None:
            cached = self.kv_cache.get(session_id, self.layer_idx)
            if cached is not None:
                c_kv_past, past_pos = cached
                c_kv_full = np.concatenate([c_kv_past, c_kv_new], axis=0)
                offset    = past_pos          # RoPE start position for current tokens
            else:
                c_kv_full = c_kv_new
                offset    = position
            total_len = c_kv_full.shape[0]
            self.kv_cache.put(session_id, self.layer_idx, c_kv_full, total_len)
        else:
            c_kv_full = c_kv_new
            offset    = position
            total_len = seq_len

        # 3. Expand K and V from full latent (past + current)
        K_up = c_kv_full @ self._W_UK                        # (total, n_kv*hd)
        V_up = c_kv_full @ self._W_UV                        # (total, n_kv*hd)

        # 4. Compress Q from current input only
        c_q  = hidden  @ self._W_DQ                          # (seq, d_c')
        Q_up = c_q     @ self._W_UQ                          # (seq, n_h*hd)

        Q = Q_up.reshape(seq_len,   n_h,  hd)
        K = K_up.reshape(total_len, n_kv, hd)
        V = V_up.reshape(total_len, n_kv, hd)

        # 5. RoPE on Q (positions offset..offset+seq) and K (positions 0..total_len)
        cos_k, sin_k = _precompute_rope(total_len, hd, self.rope_theta)
        K = _apply_rope(K, cos_k, sin_k)

        cos_q, sin_q = _precompute_rope(offset + seq_len, hd, self.rope_theta)
        Q = _apply_rope(Q, cos_q[offset:], sin_q[offset:])

        # 6. GQA: repeat K/V to match Q heads
        repeats = n_h // n_kv
        K = np.repeat(K, repeats, axis=1)                    # (total, n_h, hd)
        V = np.repeat(V, repeats, axis=1)

        # 7. Scaled dot-product — Q attends to full K/V (past + current)
        scale  = hd ** -0.5
        scores = np.einsum("shd,thd->sht", Q, K) * scale    # (seq, n_h, total)

        # Causal mask: current position s must not attend to future positions
        # Positions: past tokens [0..offset-1] are always visible; current [offset..offset+seq-1]
        if seq_len > 1:
            # Prefill: apply causal mask within current tokens only
            causal = np.zeros((seq_len, total_len), dtype=np.float32)
            cur_block = np.triu(
                np.full((seq_len, seq_len), -1e9, dtype=np.float32), k=1
            )
            causal[:, -seq_len:] = cur_block
            scores = scores + causal[:, None, :]

        attn = self._softmax(scores, axis=-1)
        out  = np.einsum("sht,thd->shd", attn, V)            # (seq, n_h, hd)
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

    cfg = shard_engine.config
    for i, layer in enumerate(getattr(shard_engine, "_layers", [])):
        layer_idx = cfg.layer_start + i
        mla       = MLAModule(
            layer_idx  = layer_idx,
            kv_cache   = kv_cache,
            hidden_dim = cfg.hidden_dim,
            n_heads    = cfg.n_heads,
            n_kv_heads = cfg.n_kv_heads,
            head_dim   = cfg.head_dim,
            rope_theta = cfg.rope_theta,
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

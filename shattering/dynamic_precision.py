"""
shattering/dynamic_precision.py
Dynamic precision cache for Qwen2 weight matrices.

Access frequency determines the in-RAM precision tier of each weight matrix:

  INT4  (<  DYN_QUANT_THRESH_INT8)  — no cache; dequantize nibble-packed on every call.
  INT8  (<  DYN_QUANT_THRESH_FP16)  — int8 + per-row scale cache; avoids nibble decode.
  FP16  (<  DYN_QUANT_THRESH_FP32)  — float16 cache; cheap fp16->fp32 cast before matmul.
  FP32  (>= DYN_QUANT_THRESH_FP32)  — float32 cache; direct matmul, maximum throughput.

Auto-decay: after DYN_QUANT_IDLE_DECAY_S without access the counter resets and the
cache is dropped on the next linear() call. Call PrecisionManager.decay_all() during
the sleep cycle for immediate decay across all weights.

DynamicWeights.linear(x) is a drop-in for INT4Weights.linear(x). No PyTorch.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from shattering.model_constants import (
    DYN_QUANT_IDLE_DECAY_S,
    DYN_QUANT_THRESH_FP16,
    DYN_QUANT_THRESH_FP32,
    DYN_QUANT_THRESH_INT8,
)

PREC_INT4 = "int4"
PREC_INT8 = "int8"
PREC_FP16 = "fp16"
PREC_FP32 = "fp32"


@dataclass
class _Int8Cache:
    q:     np.ndarray  # (out_features, in_features) int8
    scale: np.ndarray  # (out_features, 1)           float32


class DynamicWeights:
    """
    Wraps an INT4Weights matrix. Tracks per-call access frequency and maintains
    an optional in-RAM precision cache to avoid repeated nibble-unpack overhead.

    Thread-safe via a per-instance RLock. The matmul runs outside the lock so
    two threads can compute in parallel once the cache is built.
    """

    __slots__ = (
        "_w4", "_lock", "_access_count", "_last_access",
        "_cache", "_cache_prec",
    )

    def __init__(self, int4_weights) -> None:
        self._w4           = int4_weights
        self._lock         = threading.RLock()
        self._access_count = 0
        self._last_access  = time.monotonic()
        self._cache        = None   # np.ndarray | _Int8Cache | None
        self._cache_prec   = PREC_INT4

    # ── Public API ────────────────────────────────────────────────────────

    def linear(self, x: np.ndarray) -> np.ndarray:
        """
        Compute x @ W^T. Promotes or uses precision cache based on access count.
        Drop-in replacement for INT4Weights.linear(x).
        """
        with self._lock:
            now = time.monotonic()
            if now - self._last_access > DYN_QUANT_IDLE_DECAY_S:
                self._reset()
            self._access_count += 1
            self._last_access  = now
            target = self._target_prec()
            if target != self._cache_prec or (target != PREC_INT4 and self._cache is None):
                self._build_cache(target)
            prec  = self._cache_prec
            cache = self._cache

        # Matmul outside the lock: threads can overlap once cache is ready
        x32 = x.astype(np.float32)
        if prec == PREC_FP32:
            return x32 @ cache.T
        if prec == PREC_FP16:
            return x32 @ cache.astype(np.float32).T
        if prec == PREC_INT8:
            return x32 @ (cache.q.astype(np.float32) * cache.scale).T
        # PREC_INT4: always dequantize from nibble-packed source
        return self._w4.linear(x32)

    def decay(self, factor: float = 0.3) -> None:
        """
        Reduce access counter by factor and drop the cache if the tier changes.
        Called during the sleep cycle via PrecisionManager.decay_all().
        """
        with self._lock:
            self._access_count = int(self._access_count * factor)
            if self._target_prec() != self._cache_prec:
                self._drop_cache()

    def drop_cache(self) -> None:
        """Immediately free cached arrays and return to INT4 on-demand mode."""
        with self._lock:
            self._reset()

    def precision(self) -> str:
        with self._lock:
            return self._cache_prec

    def access_count(self) -> int:
        with self._lock:
            return self._access_count

    # ── Private ───────────────────────────────────────────────────────────

    def _target_prec(self) -> str:
        c = self._access_count
        if c >= DYN_QUANT_THRESH_FP32:
            return PREC_FP32
        if c >= DYN_QUANT_THRESH_FP16:
            return PREC_FP16
        if c >= DYN_QUANT_THRESH_INT8:
            return PREC_INT8
        return PREC_INT4

    def _build_cache(self, prec: str) -> None:
        self._drop_cache()
        W_fp32 = self._w4.dequantize()
        if prec == PREC_FP32:
            self._cache = W_fp32
        elif prec == PREC_FP16:
            self._cache = W_fp32.astype(np.float16)
        elif prec == PREC_INT8:
            from shattering.quantization import quantize_int8
            q, scale    = quantize_int8(W_fp32)
            self._cache = _Int8Cache(q=q, scale=scale)
        self._cache_prec = prec

    def _drop_cache(self) -> None:
        self._cache      = None
        self._cache_prec = PREC_INT4

    def _reset(self) -> None:
        self._access_count = 0
        self._drop_cache()


# ── PrecisionManager ─────────────────────────────────────────────────────────

class PrecisionManager:
    """
    Registry of DynamicWeights for all weight matrices in a ShardEngine.
    Key convention: "l{layer_index}_{weight_name}" — e.g. "l0_q", "l11_down".
    """

    def __init__(self) -> None:
        self._weights: Dict[str, DynamicWeights] = {}

    def register(self, key: str, int4_weights) -> DynamicWeights:
        dw = DynamicWeights(int4_weights)
        self._weights[key] = dw
        return dw

    def get(self, key: str) -> Optional[DynamicWeights]:
        return self._weights.get(key)

    def decay_all(self, factor: float = 0.3) -> None:
        """Decay all counters and drop demoted caches. Call during the sleep cycle."""
        for dw in self._weights.values():
            dw.decay(factor)

    def drop_all_caches(self) -> None:
        """Immediately free all cached arrays. Use under memory pressure."""
        for dw in self._weights.values():
            dw.drop_cache()

    def stats(self) -> dict:
        counts: Dict[str, int] = {PREC_INT4: 0, PREC_INT8: 0, PREC_FP16: 0, PREC_FP32: 0}
        for dw in self._weights.values():
            counts[dw.precision()] += 1
        return {
            "total_weights": len(self._weights),
            "by_precision":  counts,
        }

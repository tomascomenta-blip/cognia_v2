"""
shattering/quantization.py
===========================
Pure-numpy Neural Precision Quantization (NPQ) for MoE expert weights
and Qwen2 shard transformer layers.

INT4  — default for transformer layer weights (MLP + attention projections).
         Nibble-packed: 2 weights per byte. Per-row symmetric.
         Scale = max(|W_row|) / 7. Range [-8, 7]. 50% smaller than INT8.
         Dequantize to float32 on-demand before matmul.

INT8  — used for embedding and LM-head vicinity (higher precision needed).
         Per-row linear quantization: q = round(clip(x / scale, -128, 127)).

Ternary — 1.58-bit; available for maximum compression on factual shards.

No torch or bitsandbytes dependency: all operations are numpy-only so they
work in simulation mode and on devices without GPU drivers.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


# ── INT8 ────────────────────────────────────────────────────────────────

def quantize_int8(W: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Per-row INT8 linear symmetric quantization.

    Args:
        W: (rows, cols) float32 weight matrix

    Returns:
        q:     (rows, cols) int8  — quantized values in [-128, 127]
        scale: (rows, 1)   float32 — per-row dequantization scale
    """
    W = np.asarray(W, dtype=np.float32)
    abs_max = np.abs(W).max(axis=-1, keepdims=True).clip(1e-9)  # (rows, 1)
    scale   = abs_max / 127.0
    q       = np.round(W / scale).clip(-128, 127).astype(np.int8)
    return q, scale.astype(np.float32)


def dequantize_int8(q: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """
    Dequantize INT8 matrix back to float32.

    Args:
        q:     (rows, cols) int8
        scale: (rows, 1)   float32

    Returns:
        (rows, cols) float32
    """
    return q.astype(np.float32) * scale


# ── Ternary ─────────────────────────────────────────────────────────────

def quantize_ternary(W: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Per-row ternary (1.58-bit) quantization.

    Threshold per row: alpha = mean(|W|, axis=-1).
    Values -> +1 where W > alpha, -1 where W < -alpha, 0 otherwise.
    Scale per row: mean of |W| over non-zero positions.

    Args:
        W: (rows, cols) float32 weight matrix

    Returns:
        q:     (rows, cols) int8  — ternary values in {-1, 0, +1}
        scale: (rows, 1)   float32 — per-row dequantization scale
    """
    W       = np.asarray(W, dtype=np.float32)
    abs_W   = np.abs(W)
    alpha   = abs_W.mean(axis=-1, keepdims=True)              # (rows, 1) threshold

    q = np.zeros_like(W, dtype=np.int8)
    q[W >  alpha] =  1
    q[W < -alpha] = -1

    nonzero_mask = q != 0
    # Scale = mean of |W| at non-zero positions (per row). Fall back to alpha if all zero.
    scale = np.where(
        nonzero_mask.any(axis=-1, keepdims=True),
        np.where(nonzero_mask, abs_W, 0.0).sum(axis=-1, keepdims=True)
        / nonzero_mask.sum(axis=-1, keepdims=True).clip(1),
        alpha,
    ).astype(np.float32)

    return q, scale


def dequantize_ternary(q: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """
    Dequantize ternary matrix back to float32.

    Args:
        q:     (rows, cols) int8 with values in {-1, 0, +1}
        scale: (rows, 1)   float32

    Returns:
        (rows, cols) float32
    """
    return q.astype(np.float32) * scale


# ── INT4 (nibble-packed) ─────────────────────────────────────────────────

def quantize_int4(W: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Per-row INT4 symmetric quantization with nibble packing (2 weights/byte).

    Range: [-8, 7] (signed 4-bit). Scale = max(|W_row|) / 7.
    Two consecutive values (even, odd column) are packed into one uint8:
      high nibble = even column, low nibble = odd column.
    Columns are zero-padded to even count before packing.

    Args:
        W: (rows, cols) float32 weight matrix

    Returns:
        packed: (rows, ceil(cols/2)) uint8 — nibble-packed INT4
        scale:  (rows, 1)           float32 — per-row dequantization scale
    """
    W    = np.asarray(W, dtype=np.float32)
    rows, cols = W.shape

    abs_max = np.abs(W).max(axis=-1, keepdims=True).clip(1e-9)
    scale   = abs_max / 7.0
    q_int   = np.round(W / scale).clip(-8, 7).astype(np.int8)

    # Pad to even number of columns
    if cols % 2 != 0:
        q_int = np.pad(q_int, ((0, 0), (0, 1)))

    # Shift signed [-8, 7] → unsigned [0, 15] for nibble storage
    u      = (q_int + 8).astype(np.uint8)
    packed = (u[:, 0::2] << 4) | (u[:, 1::2] & 0x0F)

    return packed, scale.astype(np.float32)


def dequantize_int4(packed: np.ndarray, scale: np.ndarray,
                    orig_cols: Optional[int] = None) -> np.ndarray:
    """
    Dequantize nibble-packed INT4 back to float32.

    Args:
        packed:    (rows, ceil(orig_cols/2)) uint8
        scale:     (rows, 1)                float32
        orig_cols: original column count before padding (trims padding if odd)

    Returns:
        (rows, orig_cols) float32
    """
    rows = packed.shape[0]
    high = ((packed >> 4) & 0x0F).astype(np.int8) - 8   # even columns
    low  = (packed & 0x0F).astype(np.int8) - 8           # odd columns

    out           = np.empty((rows, packed.shape[1] * 2), dtype=np.float32)
    out[:, 0::2]  = high
    out[:, 1::2]  = low

    if orig_cols is not None and orig_cols < out.shape[1]:
        out = out[:, :orig_cols]

    return out * scale

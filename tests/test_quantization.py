"""
tests/test_quantization.py
==========================
Correctness tests for shattering/quantization.py -- the foundational NPQ math every
model weight passes through (INT4 nibble-packed for all transformer projections, INT8
for embeddings/LM-head vicinity, ternary for max compression). This module had NO
dedicated coverage; a silent regression in the packing or scale math would corrupt every
inference. These pin the round-trip error bounds, the nibble packing, odd-column trimming,
zero-row safety, and the full quantize->dequantize->matmul chain via INT4Weights.linear.
"""
from __future__ import annotations

import numpy as np
import pytest

from shattering.quantization import (
    quantize_int4, dequantize_int4,
    quantize_int8, dequantize_int8,
    quantize_ternary, dequantize_ternary,
)
from node.qwen2_ops import INT4Weights


# ── INT4 ──────────────────────────────────────────────────────────────────────

class TestInt4:
    def test_roundtrip_error_within_half_step(self):
        rng = np.random.default_rng(0)
        W = (rng.standard_normal((32, 128)) * 0.1).astype(np.float32)
        packed, scale = quantize_int4(W)
        deq = dequantize_int4(packed, scale, orig_cols=W.shape[1])
        # Per-row scale = max|row|/7; symmetric rounding => |err| <= scale/2. No clipping
        # occurs because the max element maps to exactly 7.
        assert (np.abs(W - deq) <= scale / 2 + 1e-5).all()

    def test_packed_shape_and_dtype(self):
        W = np.zeros((5, 10), dtype=np.float32)
        packed, scale = quantize_int4(W)
        assert packed.shape == (5, 5)           # ceil(10/2)
        assert packed.dtype == np.uint8
        assert scale.shape == (5, 1)
        assert scale.dtype == np.float32

    def test_odd_columns_roundtrip_trims_padding(self):
        rng = np.random.default_rng(1)
        W = (rng.standard_normal((4, 7)) * 0.2).astype(np.float32)   # odd cols
        packed, scale = quantize_int4(W)
        assert packed.shape == (4, 4)           # ceil(7/2) = 4
        deq = dequantize_int4(packed, scale, orig_cols=7)
        assert deq.shape == (4, 7)              # padding column trimmed
        assert (np.abs(W - deq) <= scale / 2 + 1e-5).all()

    def test_nibble_range_is_signed_4bit(self):
        # Reconstructed values / scale must be integers in [-8, 7].
        rng = np.random.default_rng(2)
        W = (rng.standard_normal((8, 16))).astype(np.float32)
        packed, scale = quantize_int4(W)
        deq = dequantize_int4(packed, scale, orig_cols=16)
        codes = np.round(deq / scale).astype(int)
        assert codes.min() >= -8 and codes.max() <= 7

    def test_zero_row_stays_zero(self):
        W = np.zeros((3, 8), dtype=np.float32)
        W[1] = 0.0
        packed, scale = quantize_int4(W)
        deq = dequantize_int4(packed, scale, orig_cols=8)
        assert np.array_equal(deq, np.zeros_like(W))   # clip(1e-9) avoids div-by-zero

    def test_exact_when_values_are_on_the_grid(self):
        # A row whose values are integer multiples of s (max abs = 7s) round-trips
        # exactly: derived scale == s and every code is an exact integer.
        s = 0.25  # exactly representable in float32
        W = (np.array([[7, -7, 2, -4, 0, 3, 1, -1]], dtype=np.float32) * s)
        packed, scale = quantize_int4(W)
        assert float(scale[0, 0]) == pytest.approx(s, abs=1e-7)
        deq = dequantize_int4(packed, scale, orig_cols=8)
        assert np.allclose(deq, W, atol=1e-7)

    def test_high_nibble_is_even_column(self):
        # Packing contract: high nibble = even column, low nibble = odd column.
        # Row [7, -3] with max abs 7 -> scale 1.0 -> codes 7 (even) and -3 (odd).
        # unsigned: 7+8=15 (0xF) high nibble, -3+8=5 (0x5) low nibble -> byte 0xF5.
        W = np.array([[7.0, -3.0]], dtype=np.float32)
        packed, scale = quantize_int4(W)
        assert float(scale[0, 0]) == pytest.approx(1.0, abs=1e-6)
        assert packed[0, 0] == (15 << 4) | 5   # 0xF5 == 245

    def test_int4weights_linear_matches_dequantized_matmul(self):
        # The real production path: INT4Weights.linear(x) must equal x @ dequant(W).T
        # on whichever backend tier is active (numba / C / numpy).
        rng = np.random.default_rng(3)
        W = (rng.standard_normal((24, 40)) * 0.1).astype(np.float32)
        x = (rng.standard_normal((3, 40)) * 0.5).astype(np.float32)
        w = INT4Weights.from_float32(W)
        ref = x @ w.dequantize().T
        out = w.linear(x)
        assert out.shape == (3, 24)
        assert np.allclose(out, ref, atol=1e-4, rtol=1e-4)

    def test_int4weights_roundtrip_close_to_original(self):
        rng = np.random.default_rng(4)
        W = (rng.standard_normal((16, 33)) * 0.3).astype(np.float32)  # odd cols
        w = INT4Weights.from_float32(W)
        deq = w.dequantize()
        assert deq.shape == W.shape
        # within one quantization step of the original per row
        rowmax = np.abs(W).max(axis=1, keepdims=True)
        assert (np.abs(W - deq) <= rowmax / 7 / 2 + 1e-5).all()


# ── INT8 ──────────────────────────────────────────────────────────────────────

class TestInt8:
    def test_roundtrip_error_within_half_step(self):
        rng = np.random.default_rng(5)
        W = (rng.standard_normal((10, 64)) * 0.4).astype(np.float32)
        q, scale = quantize_int8(W)
        deq = dequantize_int8(q, scale)
        assert q.dtype == np.int8
        assert (np.abs(W - deq) <= scale / 2 + 1e-5).all()

    def test_range_is_signed_8bit(self):
        rng = np.random.default_rng(6)
        W = (rng.standard_normal((4, 32)) * 2.0).astype(np.float32)
        q, _ = quantize_int8(W)
        assert q.min() >= -128 and q.max() <= 127

    def test_zero_row_stays_zero(self):
        W = np.zeros((2, 16), dtype=np.float32)
        q, scale = quantize_int8(W)
        assert np.array_equal(dequantize_int8(q, scale), np.zeros_like(W))

    def test_int8_more_precise_than_int4(self):
        rng = np.random.default_rng(7)
        W = (rng.standard_normal((8, 128)) * 0.5).astype(np.float32)
        e8 = np.abs(W - dequantize_int8(*quantize_int8(W))).mean()
        p4, s4 = quantize_int4(W)
        e4 = np.abs(W - dequantize_int4(p4, s4, orig_cols=W.shape[1])).mean()
        assert e8 < e4


# ── Ternary ─────────────────────────────────────────────────────────────────

class TestTernary:
    def test_values_are_ternary(self):
        rng = np.random.default_rng(8)
        W = (rng.standard_normal((6, 50))).astype(np.float32)
        q, _ = quantize_ternary(W)
        assert set(np.unique(q)).issubset({-1, 0, 1})

    def test_sign_structure_follows_threshold(self):
        W = np.array([[3.0, -3.0, 0.1, -0.1]], dtype=np.float32)
        # alpha = mean(|W|) = (3+3+0.1+0.1)/4 = 1.55
        q, scale = quantize_ternary(W)
        assert q[0, 0] == 1 and q[0, 1] == -1          # |3| > 1.55
        assert q[0, 2] == 0 and q[0, 3] == 0           # |0.1| < 1.55
        # scale = mean(|W|) over nonzero positions = (3+3)/2 = 3.0
        assert float(scale[0, 0]) == pytest.approx(3.0, abs=1e-5)
        deq = dequantize_ternary(q, scale)
        assert np.allclose(deq[0], [3.0, -3.0, 0.0, 0.0], atol=1e-5)

    def test_zero_row_stays_zero_and_no_nan(self):
        W = np.zeros((2, 12), dtype=np.float32)
        q, scale = quantize_ternary(W)
        deq = dequantize_ternary(q, scale)
        assert np.array_equal(deq, np.zeros_like(W))
        assert np.isfinite(scale).all()                # fallback to alpha, no div-by-zero

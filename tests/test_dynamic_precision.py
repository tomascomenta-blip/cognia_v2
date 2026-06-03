"""
tests/test_dynamic_precision.py
Tests for shattering/dynamic_precision.py — DynamicWeights and PrecisionManager.

No real model weights needed: we construct minimal INT4Weights stubs.
All shapes use small dimensions to keep tests fast.
"""

import threading
import time

import numpy as np
import pytest

from shattering.model_constants import (
    DYN_QUANT_THRESH_FP16,
    DYN_QUANT_THRESH_FP32,
    DYN_QUANT_THRESH_INT8,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_int4_weights(out_features=8, in_features=16, seed=42):
    """Return a real INT4Weights from a small random float32 matrix."""
    from node.qwen2_ops import INT4Weights
    rng = np.random.default_rng(seed)
    W = rng.standard_normal((out_features, in_features)).astype(np.float32)
    return INT4Weights.from_float32(W), (out_features, in_features)


def _make_dw(out_features=8, in_features=16, seed=42):
    """Return (DynamicWeights, (out_features, in_features))."""
    from shattering.dynamic_precision import DynamicWeights
    w4, shape = _make_int4_weights(out_features, in_features, seed)
    return DynamicWeights(w4), shape


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_initial_precision_is_int4():
    dw, _ = _make_dw()
    assert dw.precision() == "int4"


def test_initial_access_count_is_zero():
    dw, _ = _make_dw()
    assert dw.access_count() == 0


# ---------------------------------------------------------------------------
# dequantize — shape and dtype
# ---------------------------------------------------------------------------

def test_dequantize_shape():
    from node.qwen2_ops import INT4Weights
    out_f, in_f = 8, 16
    w4, _ = _make_int4_weights(out_f, in_f)
    result = w4.dequantize()
    assert result.shape == (out_f, in_f)
    assert result.dtype == np.float32


# ---------------------------------------------------------------------------
# linear — basic correctness (INT4 path, no C kernel)
# ---------------------------------------------------------------------------

def test_linear_output_shape(monkeypatch):
    """linear(x) should return (batch, out_features) regardless of precision tier."""
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    from shattering.dynamic_precision import DynamicWeights
    w4, (out_f, in_f) = _make_int4_weights(8, 16)
    dw = DynamicWeights(w4)

    batch = 3
    x = np.ones((batch, in_f), dtype=np.float32)
    out = dw.linear(x)
    assert out.shape == (batch, out_f), f"expected ({batch}, {out_f}), got {out.shape}"
    assert out.dtype == np.float32


def test_linear_increments_access_count(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    x = np.ones((1, in_f), dtype=np.float32)
    dw.linear(x)
    assert dw.access_count() == 1
    dw.linear(x)
    assert dw.access_count() == 2


# ---------------------------------------------------------------------------
# Precision tier promotion
# ---------------------------------------------------------------------------

def _pump_accesses(dw, in_f, n):
    """Drive n linear() calls on dw (bypassing C kernel via monkeypatching done by caller)."""
    x = np.ones((1, in_f), dtype=np.float32)
    for _ in range(n):
        dw.linear(x)


def test_promotes_to_int8_after_threshold(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    _pump_accesses(dw, in_f, DYN_QUANT_THRESH_INT8)
    assert dw.precision() in ("int8", "fp16", "fp32")


def test_promotes_to_fp16_after_threshold(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    _pump_accesses(dw, in_f, DYN_QUANT_THRESH_FP16)
    assert dw.precision() in ("fp16", "fp32")


def test_promotes_to_fp32_after_threshold(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    _pump_accesses(dw, in_f, DYN_QUANT_THRESH_FP32)
    assert dw.precision() == "fp32"


def test_promoted_linear_output_shape(monkeypatch):
    """After reaching FP32 tier, linear() still returns the correct shape."""
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    out_f, in_f = 8, 16
    dw, _ = _make_dw(out_f, in_f)
    x = np.ones((1, in_f), dtype=np.float32)
    for _ in range(DYN_QUANT_THRESH_FP32):
        out = dw.linear(x)
    assert out.shape == (1, out_f)
    assert out.dtype == np.float32


# ---------------------------------------------------------------------------
# decay()
# ---------------------------------------------------------------------------

def test_decay_reduces_access_count(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    _pump_accesses(dw, in_f, 20)
    before = dw.access_count()
    dw.decay(factor=0.3)
    assert dw.access_count() < before
    assert dw.access_count() == int(before * 0.3)


def test_decay_drops_cache_when_tier_changes(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    _pump_accesses(dw, in_f, DYN_QUANT_THRESH_FP32)
    assert dw.precision() == "fp32"

    dw.decay(factor=0.0)
    assert dw.precision() == "int4"


# ---------------------------------------------------------------------------
# drop_cache()
# ---------------------------------------------------------------------------

def test_drop_cache_returns_to_int4(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw()
    _pump_accesses(dw, in_f, DYN_QUANT_THRESH_FP32)
    assert dw.precision() == "fp32"

    dw.drop_cache()
    assert dw.precision() == "int4"


# ---------------------------------------------------------------------------
# Idle decay (reset on stale access)
# ---------------------------------------------------------------------------

def test_idle_reset_drops_cache(monkeypatch):
    """When last access > DYN_QUANT_IDLE_DECAY_S ago, the next linear() resets counter."""
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    import shattering.dynamic_precision as dp_mod

    dw, (_, in_f) = _make_dw()

    x = np.ones((1, in_f), dtype=np.float32)
    for _ in range(DYN_QUANT_THRESH_FP32):
        dw.linear(x)
    assert dw.precision() == "fp32"

    # Fake the last_access timestamp to be far in the past
    dw._last_access = time.monotonic() - (dp_mod.DYN_QUANT_IDLE_DECAY_S + 1.0)
    # Manually override the module constant so the next call triggers reset immediately
    original = dp_mod.DYN_QUANT_IDLE_DECAY_S
    # Trigger via _lock-path in linear(); just call access_count after injecting old ts
    # The reset happens inside linear() → _reset(), which re-initialises _access_count=0
    dw.linear(x)
    assert dw.access_count() == 1  # reset to 0, then incremented once


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

def test_concurrent_reads_no_deadlock(monkeypatch):
    """Multiple threads calling linear() concurrently must not deadlock."""
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw(32, 64)
    x = np.ones((2, in_f), dtype=np.float32)
    errors = []

    def worker():
        try:
            for _ in range(10):
                dw.linear(x)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, f"Thread errors: {errors}"


def test_concurrent_decay_and_linear_no_deadlock(monkeypatch):
    """decay() and linear() running concurrently must not deadlock."""
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    dw, (_, in_f) = _make_dw(16, 32)
    x = np.ones((1, in_f), dtype=np.float32)
    stop = threading.Event()
    errors = []

    def linear_worker():
        while not stop.is_set():
            try:
                dw.linear(x)
            except Exception as e:
                errors.append(e)
                break

    def decay_worker():
        for _ in range(5):
            time.sleep(0.01)
            try:
                dw.decay(0.5)
            except Exception as e:
                errors.append(e)

    lt = threading.Thread(target=linear_worker)
    dt = threading.Thread(target=decay_worker)
    lt.start()
    dt.start()
    dt.join(timeout=5)
    stop.set()
    lt.join(timeout=5)
    assert not errors, f"Thread errors: {errors}"


# ---------------------------------------------------------------------------
# PrecisionManager
# ---------------------------------------------------------------------------

def test_precision_manager_register_and_get():
    from shattering.dynamic_precision import PrecisionManager, DynamicWeights
    w4, _ = _make_int4_weights()
    pm = PrecisionManager()
    dw = pm.register("l0_q", w4)
    assert isinstance(dw, DynamicWeights)
    assert pm.get("l0_q") is dw


def test_precision_manager_get_missing_returns_none():
    from shattering.dynamic_precision import PrecisionManager
    pm = PrecisionManager()
    assert pm.get("nonexistent") is None


def test_precision_manager_stats_initial():
    from shattering.dynamic_precision import PrecisionManager
    w4a, _ = _make_int4_weights(seed=1)
    w4b, _ = _make_int4_weights(seed=2)
    pm = PrecisionManager()
    pm.register("l0_q", w4a)
    pm.register("l0_v", w4b)
    s = pm.stats()
    assert s["total_weights"] == 2
    assert s["by_precision"]["int4"] == 2


def test_precision_manager_decay_all(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    from shattering.dynamic_precision import PrecisionManager
    w4a, (_, in_f) = _make_int4_weights(8, 16, seed=1)
    w4b, _ = _make_int4_weights(8, 16, seed=2)
    pm = PrecisionManager()
    dwa = pm.register("l0_q", w4a)
    dwb = pm.register("l0_v", w4b)

    x = np.ones((1, in_f), dtype=np.float32)
    for _ in range(20):
        dwa.linear(x)
        dwb.linear(x)

    pm.decay_all(factor=0.0)
    assert dwa.access_count() == 0
    assert dwb.access_count() == 0


def test_precision_manager_drop_all_caches(monkeypatch):
    import node.qwen2_ops as ops
    monkeypatch.setattr(ops, "_CLIB", None, raising=False)

    from shattering.dynamic_precision import PrecisionManager
    w4, (_, in_f) = _make_int4_weights(8, 16)
    pm = PrecisionManager()
    dw = pm.register("l0_q", w4)

    x = np.ones((1, in_f), dtype=np.float32)
    for _ in range(DYN_QUANT_THRESH_FP32):
        dw.linear(x)
    assert dw.precision() == "fp32"

    pm.drop_all_caches()
    assert dw.precision() == "int4"

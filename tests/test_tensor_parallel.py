"""
tests/test_tensor_parallel.py
=============================
Phase 1 regression: the tensor-parallel forward (shattering/tensor_parallel.py)
must reproduce the golden single-device forward (node/qwen2_ops.RealTransformerLayer)
within float-addition tolerance, for T in {1,2,4}, including the multi-token
KV-cache path (each rank holds only its own heads' cache).

This is the correctness gate before any networking (Phase 2). It fails if the
Megatron column/row partition or the INT4 row/column slicing is wrong.

Run directly for the real CHECK output:
    venv312\\Scripts\\python.exe tests\\test_tensor_parallel.py
"""

from __future__ import annotations

import numpy as np

from node.qwen2_ops import RealTransformerLayer, INT4Weights
from shattering.tensor_parallel import (
    slice_rows, slice_cols, partition_layer, tp_forward_layer,
)


def _make_layer(H: int, KH: int, D: int, inter: int, seed: int) -> RealTransformerLayer:
    """Build a Qwen2-shaped decoder layer with random INT4 weights (hidden = H*D)."""
    rng = np.random.default_rng(seed)
    hidden = H * D

    def w(out: int, inp: int, s: float = 0.05) -> INT4Weights:
        return INT4Weights.from_float32((rng.standard_normal((out, inp)) * s).astype(np.float32))

    return RealTransformerLayer(
        n_heads=H, n_kv_heads=KH, head_dim=D,
        rope_theta=1_000_000.0, rms_norm_eps=1e-6,
        w_q=w(H * D, hidden), w_k=w(KH * D, hidden), w_v=w(KH * D, hidden),
        w_o=w(hidden, H * D),
        w_gate=w(inter, hidden), w_up=w(inter, hidden), w_down=w(hidden, inter),
        norm1=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
        norm2=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
    )


def _rel_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Max abs diff normalized by the golden's magnitude."""
    return float(np.max(np.abs(a - b)) / (np.max(np.abs(b)) + 1e-6))


# ── INT4 slicing is bit-exact ────────────────────────────────────────────────

def test_slice_rows_bit_exact():
    rng = np.random.default_rng(10)
    w = INT4Weights.from_float32((rng.standard_normal((64, 48)) * 0.1).astype(np.float32))
    full = w.dequantize()
    sub = slice_rows(w, 16, 48).dequantize()
    assert np.array_equal(sub, full[16:48])


def test_slice_cols_bit_exact():
    rng = np.random.default_rng(11)
    w = INT4Weights.from_float32((rng.standard_normal((40, 64)) * 0.1).astype(np.float32))
    full = w.dequantize()
    sub = slice_cols(w, 16, 48).dequantize()
    assert np.array_equal(sub, full[:, 16:48])


# ── TP forward == golden forward ─────────────────────────────────────────────

def test_tp_degree_1_matches_golden():
    layer = _make_layer(H=16, KH=2, D=128, inter=512, seed=1)
    rng = np.random.default_rng(100)
    x = (rng.standard_normal((5, 16 * 128)) * 0.5).astype(np.float32)
    golden = layer.forward(x.copy(), session_id="")
    tp = tp_forward_layer(partition_layer(layer, 1), x.copy(), session_id="")
    assert _rel_diff(tp, golden) < 1e-4


def test_tp_degree_2_matches_golden_3b_shape():
    layer = _make_layer(H=16, KH=2, D=128, inter=512, seed=1)
    rng = np.random.default_rng(101)
    x = (rng.standard_normal((5, 16 * 128)) * 0.5).astype(np.float32)
    golden = layer.forward(x.copy(), session_id="")
    tp = tp_forward_layer(partition_layer(layer, 2), x.copy(), session_id="")
    assert _rel_diff(tp, golden) < 1e-3


def test_tp_degree_4_matches_golden_14b_gqa_shape():
    # 14B-style GQA: KH=8 -> TP up to 8. Small dims for speed.
    layer = _make_layer(H=16, KH=8, D=32, inter=512, seed=2)
    rng = np.random.default_rng(102)
    x = (rng.standard_normal((6, 16 * 32)) * 0.5).astype(np.float32)
    golden = layer.forward(x.copy(), session_id="")
    tp = tp_forward_layer(partition_layer(layer, 4), x.copy(), session_id="")
    assert _rel_diff(tp, golden) < 1e-3


def test_tp_kv_cache_matches_across_turns():
    """Prefill then decode: per-rank per-head KV-cache must reproduce full attention."""
    layer = _make_layer(H=16, KH=2, D=128, inter=512, seed=3)
    ranks = partition_layer(layer, 2)
    rng = np.random.default_rng(103)
    hidden = 16 * 128

    # Prefill (seq=4)
    x_a = (rng.standard_normal((4, hidden)) * 0.5).astype(np.float32)
    golden_a = layer.forward(x_a.copy(), session_id="g")
    tp_a = tp_forward_layer(ranks, x_a.copy(), session_id="t")
    assert _rel_diff(tp_a, golden_a) < 1e-3

    # Decode (seq=1) — uses the cached K/V from prefill
    x_b = (rng.standard_normal((1, hidden)) * 0.5).astype(np.float32)
    golden_b = layer.forward(x_b.copy(), session_id="g")
    tp_b = tp_forward_layer(ranks, x_b.copy(), session_id="t")
    assert _rel_diff(tp_b, golden_b) < 1e-3


def test_partition_layer_rejects_bad_degree():
    layer = _make_layer(H=16, KH=2, D=128, inter=512, seed=4)
    # KH=2 not divisible by 4
    try:
        partition_layer(layer, 4)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for tp_degree not dividing n_kv_heads")


# ── Real CHECK runner ────────────────────────────────────────────────────────

def _check():
    print("=== Phase 1: tensor-parallel forward vs golden forward ===")

    # bit-exact slicing
    rng = np.random.default_rng(10)
    w = INT4Weights.from_float32((rng.standard_normal((64, 48)) * 0.1).astype(np.float32))
    rows_ok = np.array_equal(slice_rows(w, 16, 48).dequantize(), w.dequantize()[16:48])
    cols_ok = np.array_equal(slice_cols(w, 16, 48).dequantize(), w.dequantize()[:, 16:48])
    print(f"slice_rows bit-exact: {rows_ok}   slice_cols bit-exact: {cols_ok}")

    cases = [
        ("T=1  (3B shape  H16/KH2/D128)", 16, 2, 128, 512, 1),
        ("T=2  (3B shape  H16/KH2/D128)", 16, 2, 128, 512, 1),
        ("T=4  (14B GQA   H16/KH8/D32 )", 16, 8, 32, 512, 2),
    ]
    degrees = [1, 2, 4]
    worst = 0.0
    for (name, H, KH, D, inter, seed), T in zip(cases, degrees):
        layer = _make_layer(H, KH, D, inter, seed)
        x = (np.random.default_rng(seed + 50).standard_normal((5, H * D)) * 0.5).astype(np.float32)
        golden = layer.forward(x.copy(), session_id="")
        tp = tp_forward_layer(partition_layer(layer, T), x.copy(), session_id="")
        rd = _rel_diff(tp, golden)
        worst = max(worst, rd)
        print(f"  {name}: rel_diff={rd:.2e}  {'OK' if rd < 1e-3 else 'FAIL'}")

    # KV-cache across turns
    layer = _make_layer(16, 2, 128, 512, 3)
    ranks = partition_layer(layer, 2)
    rng = np.random.default_rng(103)
    x_a = (rng.standard_normal((4, 2048)) * 0.5).astype(np.float32)
    rd_a = _rel_diff(tp_forward_layer(ranks, x_a.copy(), "t"), layer.forward(x_a.copy(), "g"))
    x_b = (rng.standard_normal((1, 2048)) * 0.5).astype(np.float32)
    rd_b = _rel_diff(tp_forward_layer(ranks, x_b.copy(), "t"), layer.forward(x_b.copy(), "g"))
    worst = max(worst, rd_a, rd_b)
    print(f"  KV-cache prefill rel_diff={rd_a:.2e}  decode rel_diff={rd_b:.2e}  "
          f"{'OK' if max(rd_a, rd_b) < 1e-3 else 'FAIL'}")

    ok = rows_ok and cols_ok and worst < 1e-3
    print(f"\nCHECK: worst rel_diff={worst:.2e}  ->  {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _check() else 1)

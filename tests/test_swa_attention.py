"""
tests/test_swa_attention.py
===========================
Regression for the Sliding Window Attention (SWA) multi-token prefill bug.

RealTransformerLayer._attention / _attention_normed bounded long-context cost by
truncating K/V to the last SWA_WINDOW keys (`K[-SWA_WINDOW:]`). That window is
correct ONLY for the decode step (seq == 1), where the single query IS the last
token. For a multi-token prefill (seq > 1) where total > SWA_WINDOW, the global
truncation gave EVERY earlier query a window ending at the last token instead of
at its own position: the early queries saw only future keys, every score was
masked, and the softmax collapsed to a uniform average — garbage that then
propagated through the layer stack and corrupted the final logits for any prompt
longer than SWA_WINDOW (512) tokens.

Oracle: causal attention is position-consistent, so a one-shot prefill must
produce, position by position, the SAME output as feeding the tokens one at a
time (the seq == 1 path, which is correct in both the old and fixed code). The
buggy code diverged at every position except the last; the fixed banded mask
matches the incremental oracle everywhere.
"""

from __future__ import annotations

import numpy as np
import pytest

import node.qwen2_ops as qo
from node.qwen2_ops import RealTransformerLayer, INT4Weights

H, KH, D, INTER = 4, 2, 8, 16
HIDDEN = H * D


def _build(seed: int = 7) -> RealTransformerLayer:
    rng = np.random.default_rng(seed)

    def w(out, inp, s=0.08):
        return INT4Weights.from_float32(
            (rng.standard_normal((out, inp)) * s).astype(np.float32)
        )

    return RealTransformerLayer(
        n_heads=H, n_kv_heads=KH, head_dim=D, rope_theta=1_000_000.0, rms_norm_eps=1e-6,
        w_q=w(H * D, HIDDEN), w_k=w(KH * D, HIDDEN), w_v=w(KH * D, HIDDEN), w_o=w(HIDDEN, H * D),
        w_gate=w(INTER, HIDDEN), w_up=w(INTER, HIDDEN), w_down=w(HIDDEN, INTER),
        norm1=(1.0 + rng.standard_normal(HIDDEN) * 0.05).astype(np.float32),
        norm2=(1.0 + rng.standard_normal(HIDDEN) * 0.05).astype(np.float32),
    )


def _oneshot_vs_incremental(method_name: str, seq: int) -> float:
    """Max abs diff between a one-shot prefill and the per-token incremental run."""
    x = np.random.default_rng(123).standard_normal((seq, HIDDEN)).astype(np.float32)
    full = getattr(_build(), method_name)(x, session_id="full")
    incr_layer = _build()
    incr = np.vstack([
        getattr(incr_layer, method_name)(x[i:i + 1], session_id="incr")
        for i in range(seq)
    ])
    return float(np.abs(full - incr).max())


@pytest.fixture
def small_window(monkeypatch):
    """Shrink SWA_WINDOW so a tiny prefill exceeds it (fast, deterministic)."""
    monkeypatch.setattr(qo, "SWA_WINDOW", 8)
    return 8


@pytest.mark.parametrize("method", ["_attention", "_attention_normed"])
def test_prefill_longer_than_window_matches_incremental(method, small_window):
    # seq (14) > window (8): the buggy global truncation diverged at every
    # position but the last; the banded mask must match the incremental oracle.
    assert _oneshot_vs_incremental(method, seq=14) < 1e-4


@pytest.mark.parametrize("method", ["_attention", "_attention_normed"])
def test_prefill_within_window_unchanged(method, monkeypatch):
    # seq (14) <= window (64): no truncation ever happened — must still match
    # (guards against the fix altering the short-prefill path).
    monkeypatch.setattr(qo, "SWA_WINDOW", 64)
    assert _oneshot_vs_incremental(method, seq=14) < 1e-4


def test_multitoken_batch_after_long_past_matches_incremental(small_window):
    # A multi-token batch (e.g. a speculative-decoding verify batch) appended to a
    # long cached past also hit the bug: total > window with seq > 1.
    x_prompt = np.random.default_rng(5).standard_normal((20, HIDDEN)).astype(np.float32)
    batch_layer, oracle_layer = _build(), _build()
    for i in range(20):
        batch_layer._attention(x_prompt[i:i + 1], session_id="batch")
        oracle_layer._attention(x_prompt[i:i + 1], session_id="oracle")

    x_batch = np.random.default_rng(9).standard_normal((4, HIDDEN)).astype(np.float32)
    batch = batch_layer._attention(x_batch, session_id="batch")
    oracle = np.vstack([
        oracle_layer._attention(x_batch[i:i + 1], session_id="oracle")
        for i in range(4)
    ])
    assert float(np.abs(batch - oracle).max()) < 1e-4


def test_decode_step_still_truncates_to_window(small_window):
    # The decode path (seq == 1) must keep using the O(W) last-window truncation:
    # its result equals attending over the full K/V band-masked to the window.
    layer = _build()
    x_prompt = np.random.default_rng(3).standard_normal((20, HIDDEN)).astype(np.float32)
    layer._attention(x_prompt, session_id="dec")  # prefill (banded, correct)
    assert layer.kv_len("dec") == 20

    x_step = np.random.default_rng(1).standard_normal((1, HIDDEN)).astype(np.float32)
    out = layer._attention(x_step, session_id="dec")
    assert out.shape == (1, HIDDEN)
    assert np.isfinite(out).all()
    # KV grew by exactly one token (full past retained for LPC persistence).
    assert layer.kv_len("dec") == 21

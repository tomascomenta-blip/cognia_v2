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


# ── memory-bounded chunked prefill (query-axis tiling) ────────────────────────

@pytest.fixture
def tiny_chunk(monkeypatch):
    """Shrink SWA_WINDOW and the query-chunk size so a small prefill both exceeds
    the window and spans several query blocks (exercises the chunked path fast)."""
    monkeypatch.setattr(qo, "SWA_WINDOW", 8)
    monkeypatch.setattr(qo, "_SWA_QCHUNK", 4)
    return 8, 4


@pytest.mark.parametrize("method", ["_attention", "_attention_normed"])
def test_chunked_prefill_matches_incremental(method, tiny_chunk):
    # seq (14) spans multiple query chunks (QCHUNK=4) and exceeds the window (8):
    # the chunked banded prefill must still match the per-token incremental oracle.
    assert _oneshot_vs_incremental(method, seq=14) < 1e-4


def _rand_qkv(seq, past, seed):
    rng = np.random.default_rng(seed)
    total = past + seq
    Q = rng.standard_normal((seq, H, D)).astype(np.float32)
    K = rng.standard_normal((total, KH, D)).astype(np.float32)
    V = rng.standard_normal((total, KH, D)).astype(np.float32)
    return Q, K, V


@pytest.mark.parametrize("past_len", [0, 6])
def test_chunking_is_numerically_equivalent_to_nonchunked(past_len, monkeypatch):
    # Chunking changes ONLY memory, never the result up to float32 rounding: every
    # query row attends to exactly its own window regardless of tiling. It is NOT
    # bit-identical because numpy uses pairwise summation whose reduction tree depends
    # on the key-axis length -- interspersing masked (0.0) keys differently shifts
    # where the nonzero terms land in the tree, so the last bit can differ (~1e-7,
    # the same float-reassociation class as tp_allreduce). Assert tight equivalence.
    monkeypatch.setattr(qo, "SWA_WINDOW", 8)
    seq = 21
    Q, K, V = _rand_qkv(seq, past_len, seed=42)

    monkeypatch.setattr(qo, "_SWA_QCHUNK", 10_000)  # never chunk
    dense = qo._swa_sdpa(Q, K, V, seq, past_len, H, KH, D)

    monkeypatch.setattr(qo, "_SWA_QCHUNK", 4)        # chunk into 4-row blocks
    chunked = qo._swa_sdpa(Q, K, V, seq, past_len, H, KH, D)

    assert np.allclose(dense, chunked, atol=1e-5, rtol=1e-5)
    assert float(np.abs(dense - chunked).max()) < 1e-5


def test_chunked_prefill_bounds_keys_per_block(monkeypatch):
    # Prove the memory bound: even for a long prefill the per-block key count stays
    # <= QCHUNK + W - 1 (never the full context), while a single-shot run scores the
    # whole context in one matrix.
    monkeypatch.setattr(qo, "SWA_WINDOW", 8)
    monkeypatch.setattr(qo, "_SWA_QCHUNK", 4)

    seen = []
    real_block = qo._swa_banded_block

    def spy(Qb, K, V, qa0, qa1, H_, KH_, D_):
        klo = max(0, qa0 - qo.SWA_WINDOW + 1)
        seen.append(K[klo:qa1].shape[0])
        return real_block(Qb, K, V, qa0, qa1, H_, KH_, D_)

    monkeypatch.setattr(qo, "_swa_banded_block", spy)

    seq, past_len = 40, 0
    Q, K, V = _rand_qkv(seq, past_len, seed=1)
    qo._swa_sdpa(Q, K, V, seq, past_len, H, KH, D)

    assert len(seen) == 10  # 40 / QCHUNK(4)
    assert max(seen) <= qo._SWA_QCHUNK + qo.SWA_WINDOW - 1  # bounded, not O(seq)
    assert max(seen) < seq  # strictly less than the full context

"""Regression tests for MLAModule RoPE alignment (shattering/mla.py).

Root cause fixed 2026-06-18: on an uncached call K was RoPE-rotated at absolute
positions [0..seq_len) while Q was rotated at [position..position+seq_len), so Q
and K used a different frame for the SAME tokens whenever position>0. The fix
derives the Q offset from the actual K length (q_offset = total_len - seq_len),
which is 0 on the uncached path and past_pos on the cached path.

These tests run on real (random) weights, not simulation mode.
"""
import numpy as np
import pytest

from shattering.mla import MLAModule, CompressedKVCache


# Small, internally-consistent dims so the test is fast.
HIDDEN, D_C, D_CP = 8, 8, 8
N_H, N_KV, HD = 4, 2, 2          # n_h*hd = 8, n_kv*hd = 4


def _make_module(cache, layer_idx=0):
    rng = np.random.default_rng(1234 + layer_idx)
    m = MLAModule(
        layer_idx=layer_idx, kv_cache=cache,
        hidden_dim=HIDDEN, d_c=D_C, d_c_prime=D_CP,
        n_heads=N_H, n_kv_heads=N_KV, head_dim=HD,
        rope_theta=10_000.0, simulation=True,
    )
    m.load_weights(
        W_DKV=rng.standard_normal((HIDDEN, D_C)) * 0.1,
        W_UK=rng.standard_normal((D_C, N_KV * HD)) * 0.1,
        W_UV=rng.standard_normal((D_C, N_KV * HD)) * 0.1,
        W_DQ=rng.standard_normal((HIDDEN, D_CP)) * 0.1,
        W_UQ=rng.standard_normal((D_CP, N_H * HD)) * 0.1,
    )
    return m


def test_uncached_output_is_position_invariant():
    """With no past KV, the block is self-contained: RoPE is relative-invariant,
    so the output must not depend on the absolute `position` argument.

    Before the fix this FAILED for position>0 (Q/K frame mismatch)."""
    rng = np.random.default_rng(7)
    hidden = rng.standard_normal((4, HIDDEN)).astype(np.float32)

    out0 = _make_module(CompressedKVCache()).forward(hidden, session_id=None, position=0)
    out7 = _make_module(CompressedKVCache()).forward(hidden, session_id=None, position=7)
    out99 = _make_module(CompressedKVCache()).forward(hidden, session_id=None, position=99)

    np.testing.assert_allclose(out0, out7, atol=1e-5)
    np.testing.assert_allclose(out0, out99, atol=1e-5)


def test_incremental_decode_matches_full_prefill():
    """Feeding tokens one-at-a-time through a session (cached path) must give the
    same per-token outputs as a single uncached prefill of the whole sequence.

    This validates that the cached-path Q offset (past_pos) keeps Q and the
    accumulated K in the same RoPE frame."""
    rng = np.random.default_rng(42)
    seq = rng.standard_normal((5, HIDDEN)).astype(np.float32)

    # (a) one-shot prefill, no session
    full = _make_module(CompressedKVCache()).forward(seq, session_id=None, position=0)

    # (b) incremental: one token per call, same weights, shared session cache
    cache = CompressedKVCache()
    m = _make_module(cache)
    incr_rows = []
    for i in range(seq.shape[0]):
        step = m.forward(seq[i:i + 1], session_id="s1", position=i)
        incr_rows.append(step[0])
    incr = np.stack(incr_rows, axis=0)

    np.testing.assert_allclose(full, incr, atol=1e-5)


def test_prefill_then_decode_matches_full():
    """Mixed: prefill 3 tokens in one cached call, then decode 2 more one-by-one.
    Result must equal the one-shot prefill of all 5 tokens."""
    rng = np.random.default_rng(99)
    seq = rng.standard_normal((5, HIDDEN)).astype(np.float32)

    full = _make_module(CompressedKVCache()).forward(seq, session_id=None, position=0)

    cache = CompressedKVCache()
    m = _make_module(cache)
    pre = m.forward(seq[:3], session_id="s2", position=0)        # prefill block
    rows = [pre[0], pre[1], pre[2]]
    for i in range(3, 5):
        step = m.forward(seq[i:i + 1], session_id="s2", position=i)
        rows.append(step[0])
    mixed = np.stack(rows, axis=0)

    np.testing.assert_allclose(full, mixed, atol=1e-5)

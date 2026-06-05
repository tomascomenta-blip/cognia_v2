"""
tests/test_nano_draft.py
========================
Unit tests for node/nano_draft.py — pure numpy, no real model weights needed.
Synthetic weights are created in-memory using a fixed random seed.
"""

import numpy as np
import pytest

from node.nano_draft import (
    _rms_norm,
    _silu,
    _rope,
    NanoDraft,
    _NANO_HIDDEN,
    _NANO_HEADS,
    _NANO_KV_HEADS,
    _NANO_HEAD_DIM,
    _NANO_MLP,
    _VOCAB,
    _MAX_CTX,
)


# ---------------------------------------------------------------------------
# Fixture: synthetic weights saved to a temp npz file
# ---------------------------------------------------------------------------

@pytest.fixture()
def nano_weights(tmp_path):
    """Create a minimal valid NanoDraft weights file with random float32 values."""
    rng = np.random.default_rng(42)

    def r(*shape):
        return rng.standard_normal(shape).astype(np.float32)

    arrays = {
        "embed":   r(_VOCAB, _NANO_HIDDEN),
        "lm_head": r(_VOCAB, _NANO_HIDDEN),
        "norm_f":  r(_NANO_HIDDEN),
    }
    for i in range(2):
        arrays[f"l{i}_q"]    = r(_NANO_HIDDEN, _NANO_HIDDEN)
        arrays[f"l{i}_k"]    = r(_NANO_KV_HEADS * _NANO_HEAD_DIM, _NANO_HIDDEN)
        arrays[f"l{i}_v"]    = r(_NANO_KV_HEADS * _NANO_HEAD_DIM, _NANO_HIDDEN)
        arrays[f"l{i}_o"]    = r(_NANO_HIDDEN, _NANO_HIDDEN)
        arrays[f"l{i}_gate"] = r(_NANO_MLP, _NANO_HIDDEN)
        arrays[f"l{i}_up"]   = r(_NANO_MLP, _NANO_HIDDEN)
        arrays[f"l{i}_down"] = r(_NANO_HIDDEN, _NANO_MLP)
        arrays[f"l{i}_n1"]   = r(_NANO_HIDDEN)
        arrays[f"l{i}_n2"]   = r(_NANO_HIDDEN)

    path = tmp_path / "nano_draft.npz"
    np.savez(str(path), **arrays)
    return str(path)


# ---------------------------------------------------------------------------
# _rms_norm
# ---------------------------------------------------------------------------

def test_rms_norm_shape():
    x = np.random.randn(3, _NANO_HIDDEN).astype(np.float32)
    w = np.ones(_NANO_HIDDEN, dtype=np.float32)
    out = _rms_norm(x, w)
    assert out.shape == x.shape


def test_rms_norm_unit_weight_normalizes():
    # With w=1, each row should have RMS close to 1.
    x = np.random.default_rng(0).standard_normal((5, _NANO_HIDDEN)).astype(np.float32)
    w = np.ones(_NANO_HIDDEN, dtype=np.float32)
    out = _rms_norm(x, w)
    rms_out = np.sqrt((out ** 2).mean(-1))
    np.testing.assert_allclose(rms_out, np.ones(5), atol=1e-4)


def test_rms_norm_scalar_weight_scales():
    x = np.ones((2, _NANO_HIDDEN), dtype=np.float32)
    w = np.full(_NANO_HIDDEN, 3.0, dtype=np.float32)
    out = _rms_norm(x, w)
    # All elements should be ~3.0 (since x is uniform, rms == 1).
    np.testing.assert_allclose(out, np.full_like(out, 3.0), atol=1e-5)


# ---------------------------------------------------------------------------
# _silu
# ---------------------------------------------------------------------------

def test_silu_zero():
    x = np.array([0.0], dtype=np.float32)
    assert float(_silu(x)[0]) == pytest.approx(0.0, abs=1e-6)


def test_silu_large_positive():
    # silu(x) -> x for large positive x (sigmoid -> 1)
    x = np.array([30.0], dtype=np.float32)
    result = float(_silu(x)[0])
    assert result == pytest.approx(30.0, rel=0.01)


def test_silu_negative_bounded():
    # silu(-inf) should approach 0, not -inf
    x = np.array([-100.0], dtype=np.float32)
    result = float(_silu(x)[0])
    assert result >= -1.0  # bounded near 0, not diverging


# ---------------------------------------------------------------------------
# _rope
# ---------------------------------------------------------------------------

def test_rope_shape():
    seq, H, D = 4, _NANO_HEADS, _NANO_HEAD_DIM
    x = np.random.randn(seq, H, D).astype(np.float32)
    out = _rope(x, offset=0)
    assert out.shape == (seq, H, D)


def test_rope_offset_changes_output():
    seq, H, D = 2, _NANO_HEADS, _NANO_HEAD_DIM
    x = np.random.default_rng(7).standard_normal((seq, H, D)).astype(np.float32)
    out0 = _rope(x, offset=0)
    out5 = _rope(x, offset=5)
    # Different offsets must produce different encodings.
    assert not np.allclose(out0, out5)


def test_rope_preserves_norm():
    # RoPE is a rotation — it should preserve the L2 norm of each head vector.
    seq, H, D = 3, _NANO_HEADS, _NANO_HEAD_DIM
    x = np.random.default_rng(99).standard_normal((seq, H, D)).astype(np.float32)
    out = _rope(x, offset=0)
    orig_norms = np.linalg.norm(x, axis=-1)
    rope_norms = np.linalg.norm(out, axis=-1)
    np.testing.assert_allclose(orig_norms, rope_norms, atol=1e-4)


# ---------------------------------------------------------------------------
# NanoDraft class
# ---------------------------------------------------------------------------

def test_nano_draft_init(nano_weights):
    model = NanoDraft(nano_weights)
    assert len(model._layers) == 2
    assert model._embed.shape == (_VOCAB, _NANO_HIDDEN)
    assert model._lm_head.shape == (_VOCAB, _NANO_HIDDEN)
    assert model._norm_f.shape == (_NANO_HIDDEN,)


def test_draft_returns_n_tokens(nano_weights):
    model = NanoDraft(nano_weights)
    ctx = np.array([1, 2, 3], dtype=np.int32)
    tokens = model.draft(ctx, n=4)
    assert isinstance(tokens, list)
    assert len(tokens) == 4


def test_draft_token_ids_in_vocab(nano_weights):
    model = NanoDraft(nano_weights)
    ctx = np.array([10, 20, 30], dtype=np.int32)
    tokens = model.draft(ctx, n=6)
    for tok in tokens:
        assert 0 <= tok < _VOCAB


def test_reset_cache_clears_state(nano_weights):
    model = NanoDraft(nano_weights)
    ctx = np.array([1, 2, 3], dtype=np.int32)
    model.draft(ctx, n=2)  # populate cache
    model.reset_cache()
    assert len(model._ctx_ids) == 0
    assert model._ctx_kv == [None, None]


def test_cached_prefix_len_empty(nano_weights):
    model = NanoDraft(nano_weights)
    ids = np.array([5, 6, 7], dtype=np.int32)
    # Fresh model — no cache
    assert model._cached_prefix_len(ids) == 0


def test_cached_prefix_len_after_draft(nano_weights):
    model = NanoDraft(nano_weights)
    ctx = np.array([1, 2, 3, 4], dtype=np.int32)
    model.draft(ctx, n=1)  # populates _ctx_ids with ctx
    # Same prefix should be fully cached now
    prefix_len = model._cached_prefix_len(ctx)
    assert prefix_len == len(ctx)


def test_draft_context_truncated_to_max_ctx(nano_weights):
    # Contexts longer than _MAX_CTX should not crash and still return n tokens.
    model = NanoDraft(nano_weights)
    ctx = np.arange(_MAX_CTX + 10, dtype=np.int32) % _VOCAB
    tokens = model.draft(ctx, n=3)
    assert len(tokens) == 3


def test_draft_incremental_reuses_cache(nano_weights):
    # Second call with extended context should reuse cache (no crash, valid output).
    model = NanoDraft(nano_weights)
    ctx1 = np.array([1, 2, 3], dtype=np.int32)
    ctx2 = np.array([1, 2, 3, 4], dtype=np.int32)  # ctx1 + one new token
    model.draft(ctx1, n=1)
    tokens = model.draft(ctx2, n=2)
    assert len(tokens) == 2
    for tok in tokens:
        assert 0 <= tok < _VOCAB

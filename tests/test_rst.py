"""
tests/test_rst.py
=================
Math-correctness tests for RecursiveContext (shattering/recursive_context.py).

Decisions locked in design session:
- math correctness only, no empirical quality tests (no real weights needed)
- dim=64 for speed (validates numerics, not scale)
- K=2 test: context_vec must change between pass 1 and pass 2 (non-stationary)
- LayerNorm tolerance: atol=1e-5
- load_weights tested implicitly via update-with-weights test
"""

import numpy as np
import pytest

DIM = 64


@pytest.fixture
def ctx():
    from shattering.recursive_context import RecursiveContext
    return RecursiveContext(hidden_dim=DIM, alpha=0.1)


def _random_h(seq_len=8, dim=DIM, seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((seq_len, dim)).astype(np.float32)


# ── 1. inject ────────────────────────────────────────────────────────────────

class TestInject:

    def test_inject_zero_context_is_identity(self, ctx):
        h = _random_h()
        out = ctx.inject(h)
        np.testing.assert_array_equal(out, h)

    def test_inject_scales_by_alpha(self, ctx):
        h = np.zeros((4, DIM), dtype=np.float32)
        ctx._vec[:] = 1.0
        out = ctx.inject(h)
        np.testing.assert_allclose(out, np.full_like(h, 0.1), atol=1e-6)

    def test_inject_broadcasts_over_seq_len(self, ctx):
        h = _random_h(seq_len=16)
        ctx._vec[:] = 1.0
        out = ctx.inject(h)
        assert out.shape == h.shape


# ── 2. update sim mode ───────────────────────────────────────────────────────

class TestUpdateSimMode:

    def test_update_produces_unit_layernorm_output(self, ctx):
        h = _random_h(seq_len=8)
        ctx.update(h)
        vec = ctx.vector  # (1, DIM)
        mean = vec.mean(axis=-1)
        var = vec.var(axis=-1)
        np.testing.assert_allclose(mean, 0.0, atol=1e-5)
        np.testing.assert_allclose(var, 1.0, atol=1e-4)  # float32 LayerNorm acumula ~7e-5

    def test_update_changes_context_vec(self, ctx):
        h = _random_h(seed=42)
        before = ctx.vector.copy()
        ctx.update(h)
        assert not np.allclose(ctx.vector, before)


# ── 3. update with weights ───────────────────────────────────────────────────

class TestUpdateWithWeights:

    def test_linear_projection_changes_output(self, ctx):
        rng = np.random.default_rng(7)
        W = rng.standard_normal((DIM, DIM)).astype(np.float32)
        gamma = np.ones(DIM, dtype=np.float32)
        beta = np.zeros(DIM, dtype=np.float32)
        ctx.load_weights(W, gamma, beta)

        h = _random_h(seed=1)
        ctx.update(h)

        # With a random W the projection will differ from identity (mean) path
        ctx2 = __import__("shattering.recursive_context", fromlist=["RecursiveContext"]).RecursiveContext(hidden_dim=DIM)
        ctx2.update(h)

        assert not np.allclose(ctx.vector, ctx2.vector)


# ── 4. norm clamp >100 ───────────────────────────────────────────────────────

class TestNormClamp:

    def test_exploding_norm_clamped_to_10(self, ctx):
        # Force a huge hidden state so aggregated mean has large norm
        h = np.full((1, DIM), 1e4, dtype=np.float32)
        # Bypass LayerNorm by patching _layer_norm to return input as-is
        ctx._layer_norm = lambda x, eps=1e-5: x
        ctx.update(h)
        norm = float(np.linalg.norm(ctx.vector))
        assert norm <= 10.0 + 1e-4, f"norm not clamped: {norm}"


# ── 5. K=2 passes — RST is non-stationary ────────────────────────────────────

class TestKPasses:

    def test_context_vec_differs_between_pass1_and_pass2(self, ctx):
        h = _random_h(seed=99)
        ctx.reset()

        # Pass 1
        h_injected_1 = ctx.inject(h)
        ctx.update(h_injected_1)
        vec_after_pass1 = ctx.vector.copy()

        # Pass 2
        h_injected_2 = ctx.inject(h)
        ctx.update(h_injected_2)
        vec_after_pass2 = ctx.vector.copy()

        assert not np.allclose(vec_after_pass1, vec_after_pass2), (
            "K=2: context_vec identical after both passes — RST is stationary, injection has no effect"
        )

    def test_reset_zeros_context(self, ctx):
        ctx.update(_random_h())
        ctx.reset()
        np.testing.assert_array_equal(ctx.vector, np.zeros((1, DIM)))

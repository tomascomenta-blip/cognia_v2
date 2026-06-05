"""
tests/test_rank_expansion.py
============================
Tests for node/rank_expansion.py (ARA -- Adaptive Rank Amplification).
Pure numpy, no external deps, no I/O.
"""

import numpy as np
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.rank_expansion import (
    is_saturated,
    expand_lora_weights,
    _orthogonal_extension,
    MAX_RANK,
    _N_PLATEAU,
    _VAR_RATIO_MAX,
    _MIN_LOSS_EXPAND,
)


# ── is_saturated ──────────────────────────────────────────────────────────────

class TestIsSaturated:
    def test_too_short_history_returns_false(self):
        # Needs at least _N_PLATEAU + 2 elements
        assert is_saturated([0.3, 0.3, 0.3, 0.3, 0.3]) is False

    def test_minimum_length_required(self):
        # Exactly _N_PLATEAU + 2 elements with plateau
        history = [0.3] * (_N_PLATEAU + 2)
        # All equal values: var=0, mean=0.3 > MIN_LOSS_EXPAND -- should be saturated
        assert is_saturated(history) is True

    def test_not_saturated_when_loss_decreasing(self):
        # High variance tail -- not plateaued
        history = [0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05]
        assert is_saturated(history) is False

    def test_not_saturated_when_loss_below_min(self):
        # Converged well below MIN_LOSS_EXPAND -- not "non-trivial"
        history = [0.01] * (_N_PLATEAU + 3)
        assert is_saturated(history) is False

    def test_saturated_with_stable_high_loss(self):
        # Flat tail well above MIN_LOSS_EXPAND
        history = [0.8, 0.9, 0.82, 0.81, 0.81, 0.81, 0.81, 0.81]
        # variance of tail is very small relative to mean
        assert is_saturated(history) is True

    def test_empty_history_returns_false(self):
        assert is_saturated([]) is False

    def test_only_zeros_returns_false(self):
        # mean < MIN_LOSS_EXPAND
        history = [0.0] * 10
        assert is_saturated(history) is False

    def test_high_variance_tail_not_saturated(self):
        # Last _N_PLATEAU values oscillate strongly
        history = [0.3] * 5 + [0.5, 0.1, 0.5, 0.1, 0.5]
        assert is_saturated(history) is False


# ── _orthogonal_extension ─────────────────────────────────────────────────────

class TestOrthogonalExtension:
    def test_output_shape(self):
        A = np.random.randn(4, 64).astype(np.float32)
        result = _orthogonal_extension(A, 2)
        assert result.shape == (2, 64)

    def test_orthogonal_to_existing_rows(self):
        A = np.random.randn(2, 32).astype(np.float32)
        ext = _orthogonal_extension(A, 3)
        # Normalise A rows before checking cosine-like dot products
        A_normed = A / np.linalg.norm(A, axis=1, keepdims=True).clip(1e-8)
        dots = np.abs(ext @ A_normed.T)  # (3, 2)
        assert np.all(dots < 0.2), f"Not sufficiently orthogonal: max dot={dots.max():.4f}"

    def test_new_rows_are_unit_vectors(self):
        A = np.random.randn(3, 64).astype(np.float32)
        ext = _orthogonal_extension(A, 2)
        norms = np.linalg.norm(ext, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    def test_new_rows_mutually_orthogonal(self):
        A = np.random.randn(2, 128).astype(np.float32)
        ext = _orthogonal_extension(A, 4)
        gram = ext @ ext.T
        # Off-diagonal should be near zero
        off_diag = gram - np.diag(np.diag(gram))
        assert np.abs(off_diag).max() < 0.05

    def test_output_dtype_float32(self):
        A = np.random.randn(2, 64).astype(np.float32)
        ext = _orthogonal_extension(A, 2)
        assert ext.dtype == np.float32


# ── expand_lora_weights ───────────────────────────────────────────────────────

class TestExpandLoraWeights:
    def _make_weights(self, rank=4, hidden=64, proj_out=128):
        A = np.random.randn(rank, hidden).astype(np.float32)
        B = np.random.randn(proj_out, rank).astype(np.float32)
        return A, B

    def test_output_shapes_default_n_new(self):
        A, B = self._make_weights(rank=4, hidden=64, proj_out=128)
        A_exp, B_exp = expand_lora_weights(A, B, n_new=4)
        assert A_exp.shape == (8, 64)
        assert B_exp.shape == (128, 8)

    def test_output_shapes_custom_n_new(self):
        A, B = self._make_weights(rank=2, hidden=32, proj_out=64)
        A_exp, B_exp = expand_lora_weights(A, B, n_new=2)
        assert A_exp.shape == (4, 32)
        assert B_exp.shape == (64, 4)

    def test_existing_rows_preserved(self):
        A, B = self._make_weights(rank=4, hidden=64, proj_out=128)
        A_exp, B_exp = expand_lora_weights(A, B, n_new=2)
        np.testing.assert_array_equal(A_exp[:4], A)
        np.testing.assert_array_equal(B_exp[:, :4], B)

    def test_new_B_columns_are_zero(self):
        A, B = self._make_weights(rank=4, hidden=64, proj_out=128)
        A_exp, B_exp = expand_lora_weights(A, B, n_new=3)
        np.testing.assert_array_equal(B_exp[:, 4:], 0.0)

    def test_new_A_rows_small_scale(self):
        # New rows should be scaled by 0.02 -- small magnitude
        A, B = self._make_weights(rank=4, hidden=128, proj_out=64)
        A_exp, _ = expand_lora_weights(A, B, n_new=4)
        new_rows = A_exp[4:]
        norms = np.linalg.norm(new_rows, axis=1)
        # Each row is a unit vector * 0.02
        assert np.all(norms < 0.05), f"New rows too large: {norms}"

    def test_output_dtype_float32(self):
        A, B = self._make_weights(rank=4, hidden=32, proj_out=16)
        A_exp, B_exp = expand_lora_weights(A, B, n_new=2)
        assert A_exp.dtype == np.float32
        assert B_exp.dtype == np.float32

    def test_max_rank_constant(self):
        # Sanity: MAX_RANK is 8 per spec
        assert MAX_RANK == 8

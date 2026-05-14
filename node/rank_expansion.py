"""
node/rank_expansion.py
======================
ARA -- Adaptive Rank Amplification.

Detects LoRA adapter saturation from training loss history and expands
the rank using directions orthogonal to the current weight space.

Called by LoRATrainer.train() after the main training loop.
Pure numpy. No PyTorch.
"""

import numpy as np
from typing import List, Tuple

_N_PLATEAU       = 5     # epochs to look back for plateau detection
_VAR_RATIO_MAX   = 0.02  # variance/mean < 2% of mean = plateau
_MIN_LOSS_EXPAND = 0.05  # only expand if loss is still meaningfully above zero

MAX_RANK = 8             # hard cap — double the default r=4


def is_saturated(loss_history: List[float]) -> bool:
    """
    Returns True when the adapter has plateaued at a non-trivial loss.

    Plateau: variance of last N_PLATEAU epochs < VAR_RATIO_MAX * mean.
    Non-trivial: mean > MIN_LOSS_EXPAND (real capacity gap, not just convergence).
    """
    if len(loss_history) < _N_PLATEAU + 2:
        return False
    tail = np.array(loss_history[-_N_PLATEAU:], dtype=np.float64)
    mean = float(np.mean(tail))
    if mean < _MIN_LOSS_EXPAND:
        return False
    return float(np.var(tail)) < _VAR_RATIO_MAX * mean


def _orthogonal_extension(A: np.ndarray, n_new: int) -> np.ndarray:
    """
    Returns n_new unit row-vectors in R^hidden_dim, each orthogonal to all
    existing rows of A and to each other.

    Strategy: draw random vectors, project out the A-space component,
    then QR-orthonormalize the remainder.
    A: (rank, hidden_dim) -> result: (n_new, hidden_dim)
    """
    _, hidden_dim = A.shape
    rng = np.random.default_rng(42)

    R = rng.standard_normal((n_new * 2, hidden_dim)).astype(np.float32)
    A_normed = A / np.linalg.norm(A, axis=1, keepdims=True).clip(1e-8)
    R = R - (R @ A_normed.T) @ A_normed    # project out A-space

    Q, _ = np.linalg.qr(R.T)              # (hidden_dim, 2*n_new)
    return Q[:, :n_new].T.astype(np.float32)  # (n_new, hidden_dim)


def expand_lora_weights(
    A: np.ndarray,
    B: np.ndarray,
    n_new: int = 4,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Expand LoRA weight pair (A, B) by n_new rank slots.

    New A rows: orthogonal to existing rows, scaled at 0.02 (same as zero_init).
      These explore directions the current adapter does not cover.
    New B columns: zero.
      The output delta is zero for new slots at init; learned via fine-tuning.

    A: (rank, hidden_dim)  ->  (rank + n_new, hidden_dim)
    B: (proj_out, rank)    ->  (proj_out, rank + n_new)
    """
    new_rows = _orthogonal_extension(A, n_new) * 0.02
    A_exp = np.concatenate([A, new_rows], axis=0)
    B_exp = np.concatenate([B, np.zeros((B.shape[0], n_new), dtype=np.float32)], axis=1)
    return A_exp, B_exp

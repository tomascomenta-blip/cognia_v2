"""
shattering/recursive_context.py
================================
Recursive Shared Transformer (RST) context vector.

Each recursive pass of the shard chain injects a context vector into the
hidden state before the forward pass, then updates it from the output.

Injection:  h = h + alpha * context_vec
Update:     context_vec = LayerNorm(linear(h_output))

alpha is initialized small (RST_ALPHA_INIT) to allow the recursive pass
to be a near-identity at initialization, preventing training instability.
In simulation mode only the injection/update math runs; no weight matrices
are loaded, so RAM cost is negligible.
"""

from __future__ import annotations

import numpy as np

from shattering.model_constants import LLAMA_32_3B, RST_ALPHA_INIT


class RecursiveContext:
    """
    Manages the context vector state across K recursive shard-chain passes.

    Not thread-safe: one instance per active inference call.
    """

    def __init__(self, hidden_dim: int = LLAMA_32_3B["hidden_dim"],
                 alpha: float = RST_ALPHA_INIT):
        self.hidden_dim = hidden_dim
        self.alpha      = float(alpha)
        self._vec       = np.zeros((1, hidden_dim), dtype=np.float32)
        # Linear projection + LayerNorm weights (None = identity projection in sim mode)
        self._W_proj: np.ndarray | None = None   # (hidden_dim, hidden_dim)
        self._ln_gamma: np.ndarray | None = None  # (hidden_dim,)
        self._ln_beta:  np.ndarray | None = None  # (hidden_dim,)

    # ── Context operations ───────────────────────────────────────────

    def reset(self) -> None:
        """Zero the context vector. Call once before the first pass."""
        self._vec[:] = 0.0

    def inject(self, h: np.ndarray) -> np.ndarray:
        """
        Inject context vector into hidden state.

        Args:
            h: (seq_len, hidden_dim) float32

        Returns:
            h + alpha * context_vec  (same shape, broadcast over seq_len)
        """
        return h + self.alpha * self._vec

    def update(self, h: np.ndarray) -> None:
        """
        Update context vector from the output of one shard-chain pass.

        In simulation mode (no projection weights): context_vec = mean(h, axis=0)
        with LayerNorm applied (prevents magnitude blow-up across passes).

        Args:
            h: (seq_len, hidden_dim) float32 — output of the shard chain pass
        """
        aggregated = h.mean(axis=0, keepdims=True)          # (1, hidden_dim)

        if self._W_proj is not None:
            aggregated = aggregated @ self._W_proj           # linear projection

        self._vec = self._layer_norm(aggregated)

    # ── Weight loading ───────────────────────────────────────────────

    def load_weights(self, W_proj: np.ndarray,
                     ln_gamma: np.ndarray, ln_beta: np.ndarray) -> None:
        """
        Load trained RST projection weights.

        Args:
            W_proj:   (hidden_dim, hidden_dim) float32
            ln_gamma: (hidden_dim,) float32 — LayerNorm scale
            ln_beta:  (hidden_dim,) float32 — LayerNorm shift
        """
        self._W_proj   = np.asarray(W_proj,   dtype=np.float32)
        self._ln_gamma = np.asarray(ln_gamma, dtype=np.float32)
        self._ln_beta  = np.asarray(ln_beta,  dtype=np.float32)

    # ── Internal ─────────────────────────────────────────────────────

    def _layer_norm(self, x: np.ndarray, eps: float = 1e-5) -> np.ndarray:
        mean  = x.mean(axis=-1, keepdims=True)
        var   = x.var(axis=-1, keepdims=True)
        x_hat = (x - mean) / np.sqrt(var + eps)
        if self._ln_gamma is not None:
            x_hat = x_hat * self._ln_gamma + self._ln_beta
        return x_hat

    @property
    def vector(self) -> np.ndarray:
        """Current context vector, shape (1, hidden_dim)."""
        return self._vec

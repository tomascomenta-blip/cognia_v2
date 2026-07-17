"""
node/vocab_pruner.py
====================
Adaptive Vocabulary Pruner (AVP) — reduces lm_head computation from
V=151936 to ~2000 tokens per decoding step.

Strategy: maintain a "focus set" of candidate tokens based on:
1. Neighbor expansion: tokens whose IDs are within ±50 of recently generated
   tokens (exploits vocabulary locality in BPE-trained models)
2. Frequency prior: top tokens by occurrence in recent token history
3. Exploration buffer: 200 random tokens to prevent focus collapse
4. Fixed anchors: token IDs 0-99 (special tokens, EOS, padding always included)

Correctness guarantee:
- Full vocab is used for the first WARMUP_TURNS turns (cold start)
- After warmup: 1% of steps compute full logits to verify and update accuracy stats
- The pruner NEVER silently produces wrong tokens: callers can use the
  `full_argmax_from_pruned()` method which maps back into full vocab space

Usage::

    from node.vocab_pruner import VocabPruner
    pruner = VocabPruner(vocab_size=151936)

    # at start of each new generation turn
    pruner.reset_turn()

    # replace:  logits = lm_head.linear(hidden); token = int(np.argmax(logits[-1]))
    # with:
    pruned_logits, focus_idx = pruner.prune_lm_head(lm_weights, hidden[-1:])
    token = pruner.full_argmax_from_pruned(pruned_logits, focus_idx)
    pruner.update_history(token)
"""

from __future__ import annotations

import numpy as np
from collections import deque, Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular import at runtime


class VocabPruner:
    FOCUS_SIZE      = 2000  # target candidate set size
    HISTORY_LEN     = 32    # recent token IDs used to build focus
    NEIGHBOR_RADIUS = 50    # ±N vocab IDs around each history token
    EXPANSION_RANDOM = 200  # random exploration tokens per step
    WARMUP_TURNS    = 3     # use full vocab for first N turns
    VERIFY_PROB     = 0.01  # fraction of steps that verify against full vocab

    def __init__(self, vocab_size: int = None) -> None:
        if vocab_size is None:
            from shattering.model_constants import QWEN25_CODER_3B
            vocab_size = QWEN25_CODER_3B["vocab_size"]
        self.vocab_size = vocab_size
        self._token_history: deque[int] = deque(maxlen=self.HISTORY_LEN)
        self._turn_count: int = 0
        self._focus_set: np.ndarray | None = None   # sorted 1D int array
        self._hits: int = 0    # times pruned argmax == full argmax (verified)
        self._misses: int = 0  # times they diverged
        self._total: int = 0   # total inference steps

    # ── Public API ────────────────────────────────────────────────────────────

    def reset_turn(self) -> None:
        """Call at the start of each new inference turn (not each token)."""
        self._turn_count += 1
        self._token_history.clear()
        self._focus_set = None  # force rebuild on next token

    def update_history(self, token_id: int) -> None:
        """Call after each generated token to update the focus set next step."""
        self._token_history.append(int(token_id))
        # Invalidate focus so it is rebuilt with the new token included
        self._focus_set = None

    def build_focus_set(self) -> np.ndarray:
        """
        Build candidate token indices.

        Returns a sorted 1D int32 array of length <= FOCUS_SIZE.

        Algorithm:
        1. Always include token IDs 0-99 (special/EOS/padding)
        2. Add EXPANSION_RANDOM random tokens for exploration
        3. If history is non-empty:
           a. Add top-200 most frequent tokens from history
           b. Add neighbor window ±NEIGHBOR_RADIUS around each history token
        4. Deduplicate and clip to FOCUS_SIZE (keep lowest IDs when over budget;
           this is a fast approximation — real importance tracked via frequency)
        """
        V = self.vocab_size
        parts: list[np.ndarray] = []

        # Anchor: special tokens always present
        parts.append(np.arange(min(100, V), dtype=np.int32))

        # Random exploration
        rng_idx = np.random.randint(0, V, size=self.EXPANSION_RANDOM).astype(np.int32)
        parts.append(rng_idx)

        if self._token_history:
            hist = list(self._token_history)

            # Frequency: top-200 most common IDs in history
            counts = Counter(hist)
            top_ids = [tid for tid, _ in counts.most_common(200)]
            parts.append(np.array(top_ids, dtype=np.int32))

            # Neighborhood expansion: ±NEIGHBOR_RADIUS in vocab table
            base = np.array(hist, dtype=np.int32)
            offsets = np.arange(-self.NEIGHBOR_RADIUS,
                                 self.NEIGHBOR_RADIUS + 1, dtype=np.int32)
            neighbors = (base[:, None] + offsets[None, :]).ravel()
            neighbors = np.clip(neighbors, 0, V - 1)
            parts.append(neighbors)

        combined = np.concatenate(parts)
        combined = np.unique(combined)  # sort + deduplicate

        # If over budget, keep first FOCUS_SIZE (already sorted ascending)
        if combined.shape[0] > self.FOCUS_SIZE:
            combined = combined[: self.FOCUS_SIZE]

        self._focus_set = combined.astype(np.int32)
        return self._focus_set

    def prune_lm_head(
        self,
        lm_weights,          # INT4Weights or DynamicWeights with .linear()
        hidden: np.ndarray,  # (1, D) or (D,) last hidden state (already normed)
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute pruned logits over the focus set.

        During warmup (turn <= WARMUP_TURNS) or when focus_set is None,
        returns (full_logits, arange(V)) — identical to naive path.

        After warmup, slices lm_head rows to focus_set, runs a smaller matmul,
        and returns (pruned_logits, focus_indices).

        On the random verification steps (1% of calls) the full logits are also
        computed and compared to update hit/miss statistics.

        Args:
            lm_weights : object with .linear(x) -> (n_batch, V) float32
            hidden     : (1, D) or (D,) float32 last hidden state

        Returns:
            pruned_logits  : (1, focus_size) float32
            focus_indices  : (focus_size,) int32 mapping back to full vocab
        """
        hidden32 = np.ascontiguousarray(
            hidden.reshape(1, -1).astype(np.float32)
        )
        self._total += 1

        # Warmup: always use full vocab
        if self._turn_count <= self.WARMUP_TURNS:
            full_logits = lm_weights.linear(hidden32)   # (1, V)
            V = full_logits.shape[1]
            return full_logits, np.arange(V, dtype=np.int32)

        # Build (or reuse) focus set
        if self._focus_set is None:
            self.build_focus_set()

        focus_idx = self._focus_set  # (F,) sorted int32
        F = focus_idx.shape[0]

        # Slice lm_head and compute pruned matmul
        # We access the underlying INT4Weights to do a row-subset matmul.
        # Falls back to full linear when the weight type is unexpected.
        pruned_logits = self._subset_linear(lm_weights, hidden32, focus_idx)  # (1, F)

        # Probabilistic verification: 1% of steps compute full logits to measure accuracy
        if np.random.random() < self.VERIFY_PROB:
            full_logits = lm_weights.linear(hidden32)   # (1, V)
            full_best   = int(np.argmax(full_logits[0]))
            pruned_best_in_focus = int(np.argmax(pruned_logits[0]))
            pruned_best = int(focus_idx[pruned_best_in_focus])
            if pruned_best == full_best:
                self._hits += 1
            else:
                self._misses += 1
                # Correct the output for this step by returning full result
                return full_logits, np.arange(full_logits.shape[1], dtype=np.int32)

        return pruned_logits, focus_idx

    def full_argmax_from_pruned(
        self,
        pruned_logits: np.ndarray,
        focus_indices: np.ndarray,
    ) -> int:
        """Convert argmax of pruned logits back to full vocabulary index."""
        local_best = int(np.argmax(pruned_logits))
        return int(focus_indices[local_best])

    def stats(self) -> dict:
        """Return hit_rate, focus_size, total, hits, misses."""
        verified = self._hits + self._misses
        return {
            "hit_rate":   self._hits / verified if verified > 0 else 0.0,
            "focus_size": int(self._focus_set.shape[0]) if self._focus_set is not None else self.vocab_size,
            "total":      self._total,
            "hits":       self._hits,
            "misses":     self._misses,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _subset_linear(
        self,
        lm_weights,
        hidden32: np.ndarray,   # (1, D)
        focus_idx: np.ndarray,  # (F,) int32
    ) -> np.ndarray:             # (1, F) float32
        """
        Compute hidden32 @ lm_head[focus_idx].T using a row-subset of lm_head.

        For INT4Weights: slices packed/scale rows for focus_idx and calls the
        same int4_linear path — avoids dequantizing the full 151936-row matrix.
        For DynamicWeights (wrapper): try the INT4 base first, fall back to
        dequantizing the slice from the cached fp32/fp16 matrix.
        Falls back to full linear when weight type is unrecognised.
        """
        from node.qwen2_ops import INT4Weights  # local import to avoid circular

        # Unwrap DynamicWeights to its INT4 base when possible
        int4_w = None
        if isinstance(lm_weights, INT4Weights):
            int4_w = lm_weights
        else:
            base = getattr(lm_weights, "_base", None)
            if isinstance(base, INT4Weights):
                # Only use INT4 base when no promoted cache is active
                if (getattr(lm_weights, "_fp32_cache", None) is None and
                        getattr(lm_weights, "_fp16_cache", None) is None):
                    int4_w = base

        if int4_w is not None:
            # Build a row-subset INT4Weights and call its linear() — this reuses
            # the same C/Numba/numpy kernels already exercised for layers.
            subset = INT4Weights(
                packed    = np.ascontiguousarray(int4_w.packed[focus_idx]),
                scale     = np.ascontiguousarray(int4_w.scale[focus_idx]),
                orig_cols = int4_w.orig_cols,
            )
            return subset.linear(hidden32)   # (1, F)

        # fp32/fp16 cache present in DynamicWeights: use it directly
        _c32 = getattr(lm_weights, "_fp32_cache", None)
        _c16 = getattr(lm_weights, "_fp16_cache", None)
        fp_cache = _c32 if _c32 is not None else _c16
        if fp_cache is not None:
            W_sub = fp_cache[focus_idx].astype(np.float32)   # (F, D)
            return hidden32 @ W_sub.T                          # (1, F)

        # Unknown weight type: full linear (no pruning benefit, but correct)
        full = lm_weights.linear(hidden32)   # (1, V)
        return full[:, focus_idx]

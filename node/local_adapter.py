"""
node/local_adapter.py
=====================
ELC -- Episodic LoRA Cascade.

Micro-LoRA adapters trained from episodic memory during the sleep cycle.
Applied at K/V projections to personalize shard inference without modifying
INT4 base weights.

Pure numpy. No PyTorch.

Architecture (Qwen2.5-Coder-3B):
  - A: (rank=4, hidden_dim=2048)   shared initializer for K and V paths
  - B_k: (kv_proj_out=256, rank=4) K-projection delta
  - B_v: (kv_proj_out=256, rank=4) V-projection delta
  - delta_k(x) = x @ A.T @ B_k.T  (seq, kv_proj_out)
  - delta_v(x) = x @ A.T @ B_v.T  (seq, kv_proj_out)
  - Applied uniformly across all layers in the shard

Training uses surrogate hidden states: episode vectors (ep_dim, typically 384)
projected to hidden_dim via a fixed per-user random matrix. Triplet margin loss
pulls same-label episodes together and pushes different-label ones apart.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional, List

from node.rank_expansion import is_saturated, expand_lora_weights, MAX_RANK

_RANK        = 4
_HIDDEN_DIM  = 2048     # Qwen2.5-Coder-3B hidden_dim
_KV_PROJ_OUT = 256      # n_kv_heads=2 * head_dim=128
_LR          = 1e-3
_MARGIN      = 0.5
_EPOCHS      = 30


@dataclass
class LoRAWeights:
    A: np.ndarray   # (rank, hidden_dim) float32
    B: np.ndarray   # (proj_out, rank) float32

    def delta(self, x: np.ndarray) -> np.ndarray:
        """x: (seq, hidden_dim) → (seq, proj_out) additive delta."""
        return (x @ self.A.T) @ self.B.T

    @classmethod
    def zero_init(cls, rank: int = _RANK, hidden_dim: int = _HIDDEN_DIM,
                  proj_out: int = _KV_PROJ_OUT, seed: int = 0) -> "LoRAWeights":
        """A initialized with small normal noise; B initialized to zero (delta=0 at init)."""
        rng = np.random.default_rng(seed)
        return cls(
            A=rng.normal(0, 0.02, (rank, hidden_dim)).astype(np.float32),
            B=np.zeros((proj_out, rank), dtype=np.float32),
        )


class LoRAAdapter:
    """
    Per-user ELC adapter: K and V LoRA weights applied uniformly across shard layers.
    """

    def __init__(self, lora_k: LoRAWeights, lora_v: LoRAWeights, user_id: str):
        self.lora_k  = lora_k
        self.lora_v  = lora_v
        self.user_id = user_id

    def apply_k(self, x: np.ndarray) -> np.ndarray:
        return self.lora_k.delta(x)

    def apply_v(self, x: np.ndarray) -> np.ndarray:
        return self.lora_v.delta(x)

    def save(self, path: str) -> None:
        np.savez_compressed(
            path,
            k_A=self.lora_k.A, k_B=self.lora_k.B,
            v_A=self.lora_v.A, v_B=self.lora_v.B,
            user_id=np.array([self.user_id]),
        )

    @classmethod
    def load(cls, path: str) -> "LoRAAdapter":
        data    = np.load(path, allow_pickle=False)
        user_id = str(data["user_id"][0])
        return cls(
            lora_k=LoRAWeights(A=data["k_A"].copy(), B=data["k_B"].copy()),
            lora_v=LoRAWeights(A=data["v_A"].copy(), B=data["v_B"].copy()),
            user_id=user_id,
        )

    def size_bytes(self) -> int:
        return sum(w.nbytes for w in (
            self.lora_k.A, self.lora_k.B, self.lora_v.A, self.lora_v.B,
        ))


class LoRATrainer:
    """
    Trains LoRA K/V adapter from episodic memory using surrogate hidden states.

    Episode vectors (ep_dim) are projected to hidden_dim via a fixed per-user
    random matrix. Triplet margin loss is minimized with vanilla SGD over
    shuffled batches for `epochs` iterations.
    """

    def __init__(
        self,
        rank:        int   = _RANK,
        hidden_dim:  int   = _HIDDEN_DIM,
        kv_proj_out: int   = _KV_PROJ_OUT,
        lr:          float = _LR,
        margin:      float = _MARGIN,
        epochs:      int   = _EPOCHS,
    ):
        self.rank        = rank
        self.hidden_dim  = hidden_dim
        self.kv_proj_out = kv_proj_out
        self.lr          = lr
        self.margin      = margin
        self.epochs      = epochs

    def _proj_matrix(self, user_id: str, ep_dim: int) -> np.ndarray:
        """Fixed (hidden_dim, ep_dim) per-user projection, column-unit-normalized."""
        seed  = int(abs(hash(user_id))) % (2 ** 31)
        rng   = np.random.default_rng(seed)
        P     = rng.standard_normal((self.hidden_dim, ep_dim)).astype(np.float32)
        norms = np.linalg.norm(P, axis=0, keepdims=True).clip(1e-8)
        return P / norms

    def _forward(self, H: np.ndarray, A: np.ndarray, B: np.ndarray) -> np.ndarray:
        """H: (N, hidden_dim) → (N, kv_proj_out)."""
        return (H @ A.T) @ B.T

    def _triplet_grads(self, f_a: np.ndarray, f_p: np.ndarray, f_n: np.ndarray):
        """
        Margin triplet gradients for one (anchor, positive, negative) triple.
        Returns (loss_scalar, grad_a, grad_p, grad_n). All zeros if margin inactive.
        """
        d_ap = f_a - f_p
        d_an = f_a - f_n
        loss = float(np.dot(d_ap, d_ap) - np.dot(d_an, d_an) + self.margin)
        if loss <= 0.0:
            z = np.zeros(self.kv_proj_out, dtype=np.float32)
            return 0.0, z, z, z
        return loss, 2.0 * (d_ap - d_an), -2.0 * d_ap, 2.0 * d_an

    def _sgd_step(
        self,
        H:      np.ndarray,
        labels: list,
        A:      np.ndarray,
        B:      np.ndarray,
    ):
        """One SGD pass over H using random triplets. Returns (A, B, mean_loss)."""
        N = H.shape[0]
        if N < 2:
            return A, B, 0.0

        interm  = H @ A.T       # (N, rank)
        outputs = interm @ B.T  # (N, kv_proj_out)

        dA = np.zeros_like(A)
        dB = np.zeros_like(B)
        total, n = 0.0, 0

        for i in range(N):
            pos_idx = [j for j in range(N) if j != i and labels[j] == labels[i]]
            neg_idx = [j for j in range(N) if labels[j] != labels[i]]
            if not pos_idx or not neg_idx:
                continue
            j = pos_idx[int(np.random.randint(len(pos_idx)))]
            k = neg_idx[int(np.random.randint(len(neg_idx)))]

            loss, ga, gp, gn = self._triplet_grads(outputs[i], outputs[j], outputs[k])
            total += loss
            n     += 1

            for gx, idx in ((ga, i), (gp, j), (gn, k)):
                dB += np.outer(gx, interm[idx])
                d_inter = gx @ B                    # (rank,)
                dA += np.outer(d_inter, H[idx])     # (rank, hidden_dim)

        if n:
            dA /= n
            dB /= n

        return A - self.lr * dA, B - self.lr * dB, total / max(n, 1)

    def train(
        self,
        episodes: List[dict],
        user_id:  str,
        existing: Optional[LoRAAdapter] = None,
    ) -> Optional[LoRAAdapter]:
        """
        Returns a trained LoRAAdapter or None when insufficient labeled data.
        Each episode dict must have "vector" (np.ndarray) and "label" (str).
        If existing adapter is provided, its weights serve as the warm start.
        """
        valid = [e for e in episodes
                 if e.get("vector") is not None and e.get("label")]
        if len(valid) < 4:
            return None

        vecs   = np.array([e["vector"] for e in valid], dtype=np.float32)
        labels = [e["label"] for e in valid]
        ep_dim = vecs.shape[1]

        P = self._proj_matrix(user_id, ep_dim)
        H = vecs @ P.T              # (N, hidden_dim)

        seed = int(abs(hash(user_id))) % (2 ** 31)
        rng  = np.random.default_rng(seed)

        if existing is not None:
            Ak, Bk = existing.lora_k.A.copy(), existing.lora_k.B.copy()
            Av, Bv = existing.lora_v.A.copy(), existing.lora_v.B.copy()
        else:
            Ak = rng.normal(0, 0.02, (self.rank, self.hidden_dim)).astype(np.float32)
            Bk = np.zeros((self.kv_proj_out, self.rank), dtype=np.float32)
            Av = Ak.copy()
            Bv = np.zeros((self.kv_proj_out, self.rank), dtype=np.float32)

        loss_hist: List[float] = []
        for _ in range(self.epochs):
            perm   = np.random.permutation(len(valid))
            H_s    = H[perm]
            labs_s = [labels[i] for i in perm]
            Ak, Bk, lk = self._sgd_step(H_s, labs_s, Ak, Bk)
            Av, Bv, lv = self._sgd_step(H_s, labs_s, Av, Bv)
            loss_hist.append((lk + lv) * 0.5)

        current_rank = Ak.shape[0]
        if current_rank < MAX_RANK and is_saturated(loss_hist):
            n_new = min(4, MAX_RANK - current_rank)
            Ak, Bk = expand_lora_weights(Ak, Bk, n_new)
            Av, Bv = expand_lora_weights(Av, Bv, n_new)
            finetune_epochs = max(self.epochs // 3, 5)
            for _ in range(finetune_epochs):
                perm   = np.random.permutation(len(valid))
                H_s    = H[perm]
                labs_s = [labels[i] for i in perm]
                Ak, Bk, _ = self._sgd_step(H_s, labs_s, Ak, Bk)
                Av, Bv, _ = self._sgd_step(H_s, labs_s, Av, Bv)

        return LoRAAdapter(
            lora_k=LoRAWeights(A=Ak, B=Bk),
            lora_v=LoRAWeights(A=Av, B=Bv),
            user_id=user_id,
        )

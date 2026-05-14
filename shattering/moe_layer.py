"""
shattering/moe_layer.py
========================
True Mixture-of-Experts upgrade for the Shattering architecture.

Replaces the dense FFN sublayer in each transformer block with a MoE layer
that dynamically routes each token to the best expert at inference time,
rather than routing the whole prompt to one sub-model (the Phase 1-2 approach).

Sixteen experts are grouped into three domain clusters:
  logos  0-4   (reasoning / knowledge — 5 experts)
  techne 5-9   (code / technical       — 5 experts)
  rhetor 10-15 (writing / language     — 6 experts)

Design follows GShard (top-2 routing) with domain-clustered initialization.
top_k=1 (Switch-style) is also supported.

Memory model:
  - Simulation mode: zero weight matrices (pass-through FFN, router still runs).
    Router stats are tracked without wasting RAM on full weight tensors.
  - Real mode: numpy float32 weight matrices loaded from the dense checkpoint.

Integration path:
  1. Load a dense ShardEngine with real weights.
  2. Call patch_shard_engine(engine, config, primary_expert_idx) to swap each
     layer's .mlp for a MoELayer that copies the original weights to the primary
     expert and adds random-init copies for the others.
  3. Fine-tune to specialize experts per domain.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from shattering.quantization import (
    dequantize_int8,
    dequantize_ternary,
    quantize_int8,
    quantize_ternary,
)
from shattering.model_constants import (
    LLAMA_32_3B,
    MICRO_MOE_NUM_EXPERTS,
    MICRO_MOE_TOP_K,
    MICRO_MOE_INTERMEDIATE_DIM,
    DOMAIN_EXPERT_CLUSTERS,
)

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────

def _default_expert_names() -> Tuple[str, ...]:
    names = []
    for domain, indices in DOMAIN_EXPERT_CLUSTERS.items():
        for i in indices:
            names.append(f"{domain}_{i}")
    return tuple(names)


@dataclass
class ShatteringMoEConfig:
    """Hyperparameters for the Shattering MoE layer."""
    num_experts:           int   = MICRO_MOE_NUM_EXPERTS
    top_k:                 int   = MICRO_MOE_TOP_K
    hidden_dim:            int   = LLAMA_32_3B["hidden_dim"]
    intermediate_dim:      int   = MICRO_MOE_INTERMEDIATE_DIM
    router_aux_loss_coef:  float = 0.01
    router_z_loss_coef:    float = 0.001
    expert_names:          Tuple[str, ...] = field(default_factory=_default_expert_names)
    router_init_scale:     float = 0.02
    domain_clusters:       Dict[str, List[int]] = field(
        default_factory=lambda: dict(DOMAIN_EXPERT_CLUSTERS)
    )


# ── Router ─────────────────────────────────────────────────────────────

class MoERouter:
    """
    Token-level router: projects hidden states to expert logits,
    applies softmax, selects top-k experts per token.

    Works entirely in numpy (no torch dependency) so it runs in
    simulation mode and can be serialized / inspected easily.
    """

    def __init__(self, config: ShatteringMoEConfig, seed: int = 42):
        self.config = config
        rng = np.random.default_rng(seed)
        # (hidden_dim, num_experts) — small matrix (~36 KB for default config)
        self._W = rng.standard_normal(
            (config.hidden_dim, config.num_experts)
        ).astype(np.float32) * config.router_init_scale
        self._total_tokens: int   = 0
        self._expert_counts: Dict[int, int] = defaultdict(int)

    def load_weights(self, W: np.ndarray) -> None:
        """Load a real router weight matrix (hidden_dim, num_experts)."""
        self._W = np.asarray(W, dtype=np.float32)

    def route(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        Args:
            x: (seq_len, hidden_dim) float32

        Returns:
            expert_ids:  (seq_len, top_k) int32  -- expert indices per token
            weights:     (seq_len, top_k) float32 -- normalized routing weights
            aux_loss:    float -- Switch/GShard load-balancing loss
        """
        seq_len = x.shape[0]
        k       = self.config.top_k
        n_exp   = self.config.num_experts

        # Router logits & softmax
        logits        = x @ self._W                                       # (seq, n_exp)
        logits_stable = logits - logits.max(axis=-1, keepdims=True)
        exp_l         = np.exp(logits_stable)
        probs         = exp_l / exp_l.sum(axis=-1, keepdims=True)        # (seq, n_exp)

        # Top-k selection
        expert_ids = np.argsort(-probs, axis=-1)[:, :k].astype(np.int32) # (seq, k)

        # Gather and renormalise selected probabilities
        sel_probs = np.take_along_axis(probs, expert_ids, axis=-1)        # (seq, k)
        row_sums  = sel_probs.sum(axis=-1, keepdims=True).clip(1e-9)
        weights   = (sel_probs / row_sums).astype(np.float32)

        # Load-balancing aux loss — uses primary expert for both Switch (k=1) and GShard (k=2).
        # f_i = fraction of tokens with expert i as primary dispatch
        # P_i = mean softmax probability for expert i
        one_hot = np.zeros((seq_len, n_exp), dtype=np.float32)
        one_hot[np.arange(seq_len), expert_ids[:, 0]] = 1.0
        f_i      = one_hot.mean(axis=0)   # (n_exp,)
        P_i      = probs.mean(axis=0)     # (n_exp,)
        aux_loss = float(n_exp * np.dot(f_i, P_i))

        # Track per-primary-expert counts only (fraction semantics: sums to 1.0 across experts)
        self._total_tokens += seq_len
        for eid in expert_ids[:, 0]:
            self._expert_counts[int(eid)] += 1

        return expert_ids, weights, aux_loss

    def routing_stats(self) -> Dict:
        """Per-expert dispatch counts since last reset."""
        total = self._total_tokens or 1
        names = self.config.expert_names
        return {
            "total_tokens": self._total_tokens,
            "per_expert": {
                names[i] if i < len(names) else str(i): {
                    "count": self._expert_counts.get(i, 0),
                    "fraction": round(self._expert_counts.get(i, 0) / total, 3),
                }
                for i in range(self.config.num_experts)
            },
        }

    def reset_stats(self) -> None:
        self._total_tokens = 0
        self._expert_counts = defaultdict(int)


# ── Expert ─────────────────────────────────────────────────────────────

@dataclass
class QuantizedStorage:
    """Holds one quantized weight matrix (INT8 or ternary) plus its per-row scale."""
    q:      np.ndarray   # (rows, cols) int8
    scale:  np.ndarray   # (rows, 1)   float32
    mode:   str          # "int8" | "ternary"

    def dequantize(self) -> np.ndarray:
        if self.mode == "int8":
            return dequantize_int8(self.q, self.scale)
        return dequantize_ternary(self.q, self.scale)


class MoEExpert:
    """
    One FFN expert: SwiGLU (gate_proj, up_proj, down_proj).

    Simulation mode: weight matrices are NOT allocated (pass-through).
    FP32 mode:       full float32 weight matrices via load_weights().
    Quantized mode:  INT8 or ternary storage via load_weights_int8() /
                     load_weights_ternary(); dequantized on each forward call.
    """

    def __init__(self, config: ShatteringMoEConfig,
                 name: str = "expert", simulation: bool = True):
        self.name       = name
        self.simulation = simulation
        # FP32 path (None until load_weights() is called)
        self._W_gate: Optional[np.ndarray] = None   # (hidden, intermediate)
        self._W_up:   Optional[np.ndarray] = None   # (hidden, intermediate)
        self._W_down: Optional[np.ndarray] = None   # (intermediate, hidden)
        # Quantized path (None until load_weights_int8/ternary() is called)
        self._q_gate: Optional[QuantizedStorage] = None
        self._q_up:   Optional[QuantizedStorage] = None
        self._q_down: Optional[QuantizedStorage] = None

    def load_weights(self, W_gate, W_up, W_down) -> None:
        """
        Load FFN weight matrices from numpy arrays or torch tensors (FP32 path).
        HuggingFace stores Linear weights transposed: shape (out, in).
        We transpose to (in, out) for x @ W matmul convention.
        """
        def _np(t) -> np.ndarray:
            if hasattr(t, "detach"):                    # torch tensor
                return t.detach().cpu().float().numpy()
            return np.asarray(t, dtype=np.float32)

        self._W_gate  = _np(W_gate).T                  # (H, I)
        self._W_up    = _np(W_up).T                    # (H, I)
        self._W_down  = _np(W_down).T                  # (I, H)
        self.simulation = False

    def load_weights_int8(self, W_gate, W_up, W_down) -> None:
        """Quantize and store weight matrices as INT8 (critical shards 0, 3)."""
        def _np(t) -> np.ndarray:
            if hasattr(t, "detach"):
                return t.detach().cpu().float().numpy()
            return np.asarray(t, dtype=np.float32)

        for attr_q, attr_fp, W in (
            ("_q_gate", "_W_gate", W_gate),
            ("_q_up",   "_W_up",   W_up),
            ("_q_down", "_W_down", W_down),
        ):
            mat = _np(W).T
            q, scale = quantize_int8(mat)
            setattr(self, attr_q, QuantizedStorage(q=q, scale=scale, mode="int8"))
            setattr(self, attr_fp, None)  # release FP32 copy

        self.simulation = False

    def load_weights_ternary(self, W_gate, W_up, W_down) -> None:
        """Quantize and store weight matrices as ternary (factual shards 1, 2)."""
        def _np(t) -> np.ndarray:
            if hasattr(t, "detach"):
                return t.detach().cpu().float().numpy()
            return np.asarray(t, dtype=np.float32)

        for attr_q, attr_fp, W in (
            ("_q_gate", "_W_gate", W_gate),
            ("_q_up",   "_W_up",   W_up),
            ("_q_down", "_W_down", W_down),
        ):
            mat = _np(W).T
            q, scale = quantize_ternary(mat)
            setattr(self, attr_q, QuantizedStorage(q=q, scale=scale, mode="ternary"))
            setattr(self, attr_fp, None)

        self.simulation = False

    def _get_weights(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """Return (W_gate, W_up, W_down) in FP32, dequantizing if needed."""
        def _resolve(fp_attr: str, q_attr: str) -> Optional[np.ndarray]:
            fp = getattr(self, fp_attr)
            if fp is not None:
                return fp
            q_store = getattr(self, q_attr)
            if q_store is not None:
                return q_store.dequantize()
            return None

        return (
            _resolve("_W_gate", "_q_gate"),
            _resolve("_W_up",   "_q_up"),
            _resolve("_W_down", "_q_down"),
        )

    @staticmethod
    def _silu(x: np.ndarray) -> np.ndarray:
        return x / (1.0 + np.exp(-x.clip(-30, 30)))    # clip avoids exp overflow

    def forward(self, x: np.ndarray) -> np.ndarray:
        """
        Args:
            x: (n_tokens, hidden_dim) float32 — only the tokens routed here
        Returns:
            (n_tokens, hidden_dim) float32
        """
        if self.simulation:
            return x                                    # pass-through in sim mode

        W_gate, W_up, W_down = self._get_weights()
        if W_gate is None:
            return x                                    # no weights loaded yet

        gate = self._silu(x @ W_gate)                  # (n, I)
        up   = x @ W_up                                # (n, I)
        return (gate * up) @ W_down                    # (n, H)

    def perturb_from(self, source: "MoEExpert", noise_scale: float = 0.02,
                     seed: int = 0) -> None:
        """
        Initialize this expert by adding Gaussian noise to source's FP32 weights.
        Used by convert_ffn_to_moe() to initialise non-primary experts.
        Dequantizes source first if source stores quantized weights.
        """
        rng = np.random.default_rng(seed)
        src_gate, src_up, src_down = source._get_weights()
        for attr, src in (
            ("_W_gate", src_gate),
            ("_W_up",   src_up),
            ("_W_down", src_down),
        ):
            if src is not None:
                setattr(self, attr,
                        src + rng.standard_normal(src.shape).astype(np.float32) * noise_scale)
        self.simulation = False


# ── MoE Layer ──────────────────────────────────────────────────────────

class MoELayer:
    """
    Sparse Mixture-of-Experts layer: drop-in replacement for a transformer FFN.

    Forward pass:
      1. Router assigns each token to top-k experts.
      2. Each expert processes only the tokens assigned to it.
      3. Outputs are weighted-summed per token.

    The aux_loss returned by forward() must be added (scaled by
    config.router_aux_loss_coef) to the training loss to encourage
    balanced expert utilisation.

    In simulation mode the layer correctly tracks routing statistics
    without allocating large weight tensors.
    """

    def __init__(self, config: ShatteringMoEConfig, simulation: bool = True,
                 router_seed: int = 42):
        self.config     = config
        self.simulation = simulation
        self.router     = MoERouter(config, seed=router_seed)
        self.experts: List[MoEExpert] = [
            MoEExpert(config, name=name, simulation=simulation)
            for name in config.expert_names
        ]

    # ── Forward ───────────────────────────────────────────────────────

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Args:
            x: (seq_len, hidden_dim) float32
        Returns:
            output:   (seq_len, hidden_dim) float32
            aux_loss: scalar — add config.router_aux_loss_coef * aux_loss to training loss
        """
        expert_ids, weights, aux_loss = self.router.route(x)
        output = np.zeros_like(x)

        if self.config.top_k == 1:
            for e_idx, expert in enumerate(self.experts):
                mask = expert_ids[:, 0] == e_idx
                if not mask.any():
                    continue
                out = expert.forward(x[mask])          # (n, H)
                output[mask] += out * weights[mask, 0:1]
        else:
            for e_idx, expert in enumerate(self.experts):
                for k in range(self.config.top_k):
                    mask = expert_ids[:, k] == e_idx
                    if not mask.any():
                        continue
                    out = expert.forward(x[mask])
                    output[mask] += out * weights[mask, k:k+1]

        return output, aux_loss

    def __call__(self, x: np.ndarray) -> Tuple[np.ndarray, float]:
        return self.forward(x)

    def routing_stats(self) -> Dict:
        return self.router.routing_stats()

    def reset_stats(self) -> None:
        self.router.reset_stats()

    def check_balance(self, warn_threshold: float = 2.0) -> Dict:
        """
        Check if any expert is receiving disproportionate traffic.

        Returns imbalance ratios per expert. Logs WARNING if any expert
        exceeds warn_threshold * expected_fraction.
        """
        stats = self.router.routing_stats()
        n = self.config.num_experts
        expected = 1.0 / n
        ratios: Dict[str, float] = {}
        for name, info in stats["per_expert"].items():
            ratio = info["fraction"] / expected if expected > 0 else 0.0
            ratios[name] = round(ratio, 3)

        max_ratio = max(ratios.values()) if ratios else 0.0
        if max_ratio > warn_threshold:
            overloaded = [k for k, v in ratios.items() if v > warn_threshold]
            logger.warning(
                "[MoE] Load imbalance detected: %s have ratio > %.1fx expected",
                overloaded, warn_threshold,
            )

        return {"imbalance_ratios": ratios, "max_ratio": round(max_ratio, 3)}


# ── Conversion helpers ──────────────────────────────────────────────────

def convert_ffn_to_moe(
    ffn_layer,
    config: ShatteringMoEConfig,
    primary_domain: str = "logos",
    noise_scale: float = 0.02,
) -> MoELayer:
    """
    Convert a dense HuggingFace LlamaMLP to a MoELayer:
      - first expert of primary_domain gets the original weights (preserves behaviour)
      - same-domain experts get small noise (noise_scale) for intra-domain specialisation
      - cross-domain experts get larger noise (noise_scale * 3.0) to allow domain divergence

    Args:
        ffn_layer:      HuggingFace LlamaMLP with .gate_proj/.up_proj/.down_proj
        config:         MoE config (must have domain_clusters)
        primary_domain: domain name ("logos", "techne", "rhetor") that owns this shard
        noise_scale:    base perturbation std; cross-domain experts receive 3x this value

    Returns:
        MoELayer ready to replace ffn_layer.
    """
    moe = MoELayer(config, simulation=False)

    clusters        = config.domain_clusters
    primary_indices = set(clusters.get(primary_domain, [0]))
    primary_idx     = min(primary_indices)

    primary = moe.experts[primary_idx]
    primary.load_weights(
        ffn_layer.gate_proj.weight,
        ffn_layer.up_proj.weight,
        ffn_layer.down_proj.weight,
    )

    for idx, expert in enumerate(moe.experts):
        if idx == primary_idx:
            continue
        scale = noise_scale if idx in primary_indices else noise_scale * 3.0
        expert.perturb_from(primary, noise_scale=scale, seed=idx)

    logger.info(
        "[MoE] Converted FFN -> MoELayer (domain=%s, primary_idx=%d, n_experts=%d)",
        primary_domain, primary_idx, config.num_experts,
    )
    return moe


def patch_shard_engine(
    shard_engine,
    config: ShatteringMoEConfig,
    primary_domain: str = "logos",
    noise_scale: float = 0.02,
) -> None:
    """
    Patch a real-mode ShardEngine to use MoE FFN sublayers.
    Each layer's .mlp is replaced with a MoELayer wrapped to match
    the torch nn.Module interface expected by the decoder.

    No-op in simulation mode (no real weights to split into experts).

    Args:
        shard_engine:   ShardEngine instance (real mode only)
        config:         MoE config
        primary_domain: domain name ("logos", "techne", "rhetor") for this shard
        noise_scale:    base perturbation std for non-primary expert init
    """
    if shard_engine.mode != "real":
        logger.debug("[MoE] patch_shard_engine: no-op in simulation mode")
        return

    patched = 0
    for i, layer in enumerate(shard_engine._layers):
        if hasattr(layer, "mlp"):
            moe       = convert_ffn_to_moe(layer.mlp, config, primary_domain, noise_scale)
            layer.mlp = _TorchMoEAdapter(moe)
            patched  += 1

    logger.info(
        "[MoE] Patched %d/%d layers (domain=%s, shard=%d)",
        patched, len(shard_engine._layers), primary_domain, shard_engine.config.shard_index,
    )


class _TorchMoEAdapter:
    """
    Wraps a numpy MoELayer to match the torch.nn.Module.forward() interface
    expected by HuggingFace LlamaDecoderLayer when it calls self.mlp(hidden).

    Extracts the numpy array from the torch tensor, runs MoE, re-wraps.
    The aux_loss is stored as an attribute (the decoder doesn't collect it;
    a custom training loop must retrieve it separately).
    """

    def __init__(self, moe: MoELayer):
        self._moe     = moe
        self.aux_loss = 0.0

    def __call__(self, hidden_states, **kwargs):
        try:
            import torch
            # hidden_states shape from HF: (batch, seq, hidden)
            batch = hidden_states.shape[0]
            x_np  = hidden_states.squeeze(0).detach().cpu().float().numpy()  # (seq, H)
            out_np, aux = self._moe(x_np)                                    # (seq, H)
            self.aux_loss = aux
            out = torch.from_numpy(out_np).to(hidden_states.dtype)
            if batch > 1:
                out = out.unsqueeze(0).expand(batch, -1, -1)
            else:
                out = out.unsqueeze(0)
            return out
        except ImportError:
            return hidden_states     # graceful: torch not available

    def routing_stats(self) -> Dict:
        return self._moe.routing_stats()


# ── Standalone smoke test ───────────────────────────────────────────────

def _demo():
    """Quick validation: route a batch of tokens and check shapes."""
    import json

    cfg = ShatteringMoEConfig()
    moe = MoELayer(cfg, simulation=True)

    # Simulate 10 tokens of hidden_dim=3072
    x       = np.random.randn(10, cfg.hidden_dim).astype(np.float32)
    out, loss = moe(x)

    assert out.shape == x.shape, f"Output shape mismatch: {out.shape}"
    assert 0.0 <= loss <= cfg.num_experts, f"aux_loss out of range: {loss}"

    stats = moe.routing_stats()
    total = sum(v["count"] for v in stats["per_expert"].values())
    assert total == 10, f"Token count mismatch: {total}"

    print(f"[MoE demo] input={x.shape}  output={out.shape}  aux_loss={loss:.4f}")
    print(f"[MoE demo] routing: {json.dumps(stats['per_expert'], indent=2)}")
    print("[MoE demo] OK")


if __name__ == "__main__":
    _demo()

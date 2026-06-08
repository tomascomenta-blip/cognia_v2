"""
shattering/tensor_parallel.py
=============================
Megatron-style tensor parallelism for Qwen2 INT4 decoder layers, pure numpy.

This is the core of Shattering v2 (see SHATTERING_V2_DESIGN.md): instead of
splitting the model *by layers* across devices (the legacy pipeline relay), each
weight *matrix* is split across T ranks and the partial results are summed with
an all-reduce. That is what lets a single prompt's forward pass be computed
faster by more (weak) devices on a LAN.

Partition scheme (matches Megatron-LM), per decoder layer:
  - q_proj, k_proj, v_proj : COLUMN-parallel  — split by output rows = attention
        heads. Rank i owns H/T query heads and KH/T kv-heads. Each rank runs the
        attention math for its heads independently (RoPE + causal mask + GQA are
        per-head identical, so a head-subset is bit-exact) and keeps the KV-cache
        of ONLY its heads.
  - o_proj                 : ROW-parallel     — split by input columns = the same
        head groups. Each rank produces a (seq, hidden) partial; ALL-REDUCE sums.
  - gate_proj, up_proj     : COLUMN-parallel  — split the intermediate dim by T.
  - down_proj              : ROW-parallel     — split input columns (intermediate)
        by T. Each rank produces a (seq, hidden) partial; ALL-REDUCE sums.

So exactly 2 all-reduces per layer (after o_proj, after down_proj).

INT4 compatibility (verified, bit-exact — see SHATTERING_V2_DESIGN.md):
  Quantization is per-row (per output channel), scale shape (rows, 1).
  - COLUMN-parallel cuts output rows  -> each rank keeps whole rows with their own
    scales. Slicing rows of the packed array is exact.
  - ROW-parallel cuts input columns   -> all ranks share the per-row scale vector;
    each holds a column-slice of the nibbles. dequant(col-slice, shared scale) ==
    the matching columns of the full dequant, so the summed partials are exact
    (modulo float addition order, ~1e-6).

This module runs all T ranks in-process (the all-reduce is just a sum). Phase 2
replaces the in-process sum with a centralized socket reducer; the math here is
the golden reference that the networked version must reproduce.
"""

from __future__ import annotations

from typing import List

import numpy as np

from node.qwen2_ops import RealTransformerLayer, INT4Weights, _rms_norm


# ── INT4 slicing (bit-exact) ─────────────────────────────────────────────────

def slice_rows(w: INT4Weights, r0: int, r1: int) -> INT4Weights:
    """COLUMN-parallel slice: keep output rows [r0:r1].

    Each kept row carries its own per-row scale, so this is bit-exact: the
    dequantized slice equals rows [r0:r1] of the full dequantized matrix.
    """
    return INT4Weights(
        packed=np.ascontiguousarray(w.packed[r0:r1]),
        scale=np.ascontiguousarray(w.scale[r0:r1]),
        orig_cols=w.orig_cols,
    )


def slice_cols(w: INT4Weights, c0: int, c1: int) -> INT4Weights:
    """ROW-parallel slice: keep input columns [c0:c1] for ALL output rows.

    The per-row scale is shared (kept whole). Boundaries must be even so the
    nibble-packed columns fall on byte boundaries (2 weights/byte); every TP cut
    point here is a head_dim or intermediate-fraction multiple, which is even.
    Bit-exact: dequant(this, shared scale) == columns [c0:c1] of the full dequant.
    """
    if c0 % 2 != 0 or c1 % 2 != 0:
        raise ValueError(
            f"row-parallel column cut must be byte-aligned (even): got [{c0}:{c1}]"
        )
    if c1 > w.orig_cols:
        raise ValueError(f"column cut {c1} exceeds orig_cols {w.orig_cols}")
    return INT4Weights(
        packed=np.ascontiguousarray(w.packed[:, c0 // 2: c1 // 2]),
        scale=np.ascontiguousarray(w.scale),
        orig_cols=c1 - c0,
    )


# ── Layer partitioning ───────────────────────────────────────────────────────

def partition_layer(layer: RealTransformerLayer, tp_degree: int) -> List[RealTransformerLayer]:
    """Split one Qwen2 decoder layer into `tp_degree` rank-local layers.

    Each returned layer is a real RealTransformerLayer holding only its share of
    the heads (q/k/v column-parallel, o row-parallel) and intermediate dim
    (gate/up column-parallel, down row-parallel). norm weights are replicated.

    Requires tp_degree to divide n_kv_heads and the intermediate dim. (Dividing
    n_kv_heads also divides n_heads since GQA keeps n_heads a multiple of n_kv_heads.)
    """
    T = tp_degree
    H, KH, D = layer.n_heads, layer.n_kv_heads, layer.head_dim
    inter = layer.w_gate.packed.shape[0]  # intermediate dim (gate_proj output rows)

    if T < 1:
        raise ValueError(f"tp_degree must be >= 1, got {T}")
    if KH % T != 0:
        raise ValueError(f"tp_degree {T} must divide n_kv_heads {KH}")
    if H % T != 0:
        raise ValueError(f"tp_degree {T} must divide n_heads {H}")
    if inter % T != 0:
        raise ValueError(f"tp_degree {T} must divide intermediate dim {inter}")

    H_r = H // T          # query heads per rank
    KH_r = KH // T        # kv heads per rank
    I_r = inter // T      # intermediate slice per rank

    ranks: List[RealTransformerLayer] = []
    for i in range(T):
        q_lo, q_hi = i * H_r * D, (i + 1) * H_r * D        # query/o head-dim span
        kv_lo, kv_hi = i * KH_r * D, (i + 1) * KH_r * D    # kv head-dim span
        in_lo, in_hi = i * I_r, (i + 1) * I_r              # intermediate span

        rank = RealTransformerLayer(
            n_heads=H_r,
            n_kv_heads=KH_r,
            head_dim=D,
            rope_theta=layer.rope_theta,
            rms_norm_eps=layer.rms_eps,
            w_q=slice_rows(layer.w_q, q_lo, q_hi),          # column-parallel
            w_k=slice_rows(layer.w_k, kv_lo, kv_hi),        # column-parallel
            w_v=slice_rows(layer.w_v, kv_lo, kv_hi),        # column-parallel
            w_o=slice_cols(layer.w_o, q_lo, q_hi),          # row-parallel
            w_gate=slice_rows(layer.w_gate, in_lo, in_hi),  # column-parallel
            w_up=slice_rows(layer.w_up, in_lo, in_hi),      # column-parallel
            w_down=slice_cols(layer.w_down, in_lo, in_hi),  # row-parallel
            norm1=layer.norm1,                              # replicated
            norm2=layer.norm2,                              # replicated
        )
        ranks.append(rank)
    return ranks


# ── Tensor-parallel forward (in-process all-reduce = sum) ────────────────────

def tp_forward_layer(
    ranks: List[RealTransformerLayer],
    x: np.ndarray,
    session_id: str = "",
) -> np.ndarray:
    """Run one decoder layer split across `ranks`, reproducing the golden forward.

    x: (seq, hidden) float32 -> (seq, hidden) float32.

    Mirrors RealTransformerLayer.forward (unfused path) but with the projections
    distributed: norm + residual happen once ("at the seeder"), each rank computes
    its partial attention/MLP output, and the partials are summed (the all-reduce).
    Each rank holds the KV-cache of its own heads under `session_id`.
    """
    x = np.ascontiguousarray(x.astype(np.float32))
    eps = ranks[0].rms_eps

    # Attention: column-parallel q/k/v -> per-head attention -> row-parallel o -> all-reduce.
    normed1 = _rms_norm(x, ranks[0].norm1, eps)
    attn_out = ranks[0]._attention(normed1, session_id)
    for r in ranks[1:]:
        attn_out = attn_out + r._attention(normed1, session_id)
    x = x + attn_out

    # MLP: column-parallel gate/up -> SiLU -> row-parallel down -> all-reduce.
    normed2 = _rms_norm(x, ranks[0].norm2, eps)
    mlp_out = ranks[0]._mlp(normed2)
    for r in ranks[1:]:
        mlp_out = mlp_out + r._mlp(normed2)
    x = x + mlp_out

    return x


def tp_forward_layer_distributed(
    rank_layer: RealTransformerLayer,
    x: np.ndarray,
    all_reduce,
    session_id: str = "",
) -> np.ndarray:
    """One decoder layer from the point of view of a SINGLE rank.

    `rank_layer` is this rank's share from partition_layer(). `all_reduce(partial)`
    must return the element-wise sum of every rank's partial (e.g. an
    AllReduceClient.all_reduce over sockets). The norm + residual are replicated:
    every rank holds the (small) norm weights and the broadcast input x, so each
    independently reconstructs the identical full hidden state after each
    all-reduce. Running this in T processes reproduces tp_forward_layer exactly.
    """
    x = np.ascontiguousarray(x.astype(np.float32))
    eps = rank_layer.rms_eps

    normed1 = _rms_norm(x, rank_layer.norm1, eps)
    attn_out = all_reduce(rank_layer._attention(normed1, session_id))
    x = x + attn_out

    normed2 = _rms_norm(x, rank_layer.norm2, eps)
    mlp_out = all_reduce(rank_layer._mlp(normed2))
    x = x + mlp_out

    return x

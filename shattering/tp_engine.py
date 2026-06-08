"""
shattering/tp_engine.py
=======================
Full-model tensor-parallel generation: ties the per-layer TP forward
(shattering/tensor_parallel.py) into an end-to-end token loop.

A model is embedding + N decoder layers + final RMSNorm + lm_head. In Shattering
v2 the "seeder" owns the embedding and lm_head (Decision 11) and the swarm runs
the layer stack split across T tensor-parallel ranks. This module provides the
in-process version of that loop and verifies it against a single-device reference.

generate_reference  — the golden single-device greedy loop.
generate_tp         — same loop with every layer split into T ranks via
                      tp_forward_layer. Because tp_forward_layer reproduces
                      RealTransformerLayer.forward (Phase 1), the generated token
                      sequence is identical to the reference.

(The cross-process / on-LAN version drives this same loop with the socket
all-reduce from shattering/tp_allreduce.py — see scripts/tp_two_proc_demo.py and
Phase 3b. The real latency thesis needs physical devices; loopback timing here is
only a plumbing/throughput sanity check, not the LAN comparison.)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from node.qwen2_ops import RealTransformerLayer, INT4Weights, _rms_norm
from shattering.quantization import dequantize_int4
from shattering.tensor_parallel import partition_layer, tp_forward_layer


@dataclass
class TPModelWeights:
    """A minimal decoder LM: embedding + layers + final norm + lm_head (all INT4)."""
    embed: INT4Weights           # (vocab, hidden)
    layers: List[RealTransformerLayer]
    final_norm: np.ndarray       # (hidden,)
    lm_head: INT4Weights         # (vocab, hidden)
    rms_eps: float = 1e-6


def embed_lookup(embed: INT4Weights, token_ids) -> np.ndarray:
    """Gather + dequantize the embedding rows for `token_ids` -> (seq, hidden)."""
    ids = np.asarray(token_ids, dtype=np.int64)
    return dequantize_int4(embed.packed[ids], embed.scale[ids], embed.orig_cols)


def _logits_last(model: TPModelWeights, hidden_last: np.ndarray) -> np.ndarray:
    """final RMSNorm + lm_head on the last position -> (vocab,) logits."""
    normed = _rms_norm(hidden_last, model.final_norm, model.rms_eps)
    return model.lm_head.linear(normed)[-1]


def generate_reference(
    model: TPModelWeights, prompt_ids: List[int], n_new: int, session_id: str = "ref",
) -> List[int]:
    """Single-device greedy generation (the golden token sequence)."""
    x = embed_lookup(model.embed, prompt_ids)
    for layer in model.layers:
        x = layer.forward(x, session_id)
    out: List[int] = []
    nxt = int(np.argmax(_logits_last(model, x[-1:])))
    out.append(nxt)
    for _ in range(n_new - 1):
        x = embed_lookup(model.embed, [nxt])
        for layer in model.layers:
            x = layer.forward(x, session_id)
        nxt = int(np.argmax(_logits_last(model, x[-1:])))
        out.append(nxt)
    return out


def generate_tp(
    model: TPModelWeights, prompt_ids: List[int], n_new: int, tp_degree: int,
    session_id: str = "tp",
) -> List[int]:
    """Greedy generation with every layer split into `tp_degree` tensor-parallel ranks.

    Embedding + lm_head stay on the seeder (computed here directly); the layer
    stack runs in TP. Token sequence must match generate_reference exactly.
    """
    ranks_by_layer = [partition_layer(layer, tp_degree) for layer in model.layers]

    x = embed_lookup(model.embed, prompt_ids)
    for ranks in ranks_by_layer:
        x = tp_forward_layer(ranks, x, session_id)
    out: List[int] = []
    nxt = int(np.argmax(_logits_last(model, x[-1:])))
    out.append(nxt)
    for _ in range(n_new - 1):
        x = embed_lookup(model.embed, [nxt])
        for ranks in ranks_by_layer:
            x = tp_forward_layer(ranks, x, session_id)
        nxt = int(np.argmax(_logits_last(model, x[-1:])))
        out.append(nxt)
    return out


def timed_generate_tp(
    model: TPModelWeights, prompt_ids: List[int], n_new: int, tp_degree: int,
) -> Tuple[List[int], float]:
    """Returns (token_ids, tokens_per_second). In-process / loopback timing only."""
    t0 = time.perf_counter()
    ids = generate_tp(model, prompt_ids, n_new, tp_degree, session_id="bench")
    dt = time.perf_counter() - t0
    return ids, (n_new / dt if dt > 0 else 0.0)

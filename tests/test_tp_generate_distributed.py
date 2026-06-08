"""
tests/test_tp_generate_distributed.py
=====================================
Phase 3b regression: full-model TEXT GENERATION split across T ranks talking
through the socket all-reduce must produce the IDENTICAL greedy token sequence
as the single-device reference.

Ranks run in threads here (deterministic, CI-friendly); the true multi-process
run is scripts/tp_generate_demo.py. This covers the broadcast-via-all-reduce
trick (seeder contributes the embedded hidden, others contribute zeros) and the
seeder owning embedding + lm_head across the whole generation loop.
"""

from __future__ import annotations

import threading

import numpy as np

from node.qwen2_ops import RealTransformerLayer, INT4Weights
from shattering.tensor_parallel import partition_layer, tp_forward_layer_distributed
from shattering.tp_engine import TPModelWeights, embed_lookup, _logits_last, generate_reference
from shattering.tp_allreduce import AllReduceServer, AllReduceClient

VOCAB, H, KH, D, INTER, N_LAYERS = 512, 16, 8, 16, 256, 3
HIDDEN = H * D
PROMPT = [3, 17, 42, 8, 100]
N_NEW = 8
SID = "gen"


def _build_model(seed: int) -> TPModelWeights:
    rng = np.random.default_rng(seed)

    def w(out, inp, s=0.05):
        return INT4Weights.from_float32((rng.standard_normal((out, inp)) * s).astype(np.float32))

    layers = [
        RealTransformerLayer(
            n_heads=H, n_kv_heads=KH, head_dim=D, rope_theta=1_000_000.0, rms_norm_eps=1e-6,
            w_q=w(H * D, HIDDEN), w_k=w(KH * D, HIDDEN), w_v=w(KH * D, HIDDEN), w_o=w(HIDDEN, H * D),
            w_gate=w(INTER, HIDDEN), w_up=w(INTER, HIDDEN), w_down=w(HIDDEN, INTER),
            norm1=(1.0 + rng.standard_normal(HIDDEN) * 0.05).astype(np.float32),
            norm2=(1.0 + rng.standard_normal(HIDDEN) * 0.05).astype(np.float32),
        )
        for _ in range(N_LAYERS)
    ]
    return TPModelWeights(
        embed=w(VOCAB, HIDDEN), layers=layers,
        final_norm=(1.0 + rng.standard_normal(HIDDEN) * 0.05).astype(np.float32),
        lm_head=w(VOCAB, HIDDEN), rms_eps=1e-6,
    )


def _run_rank(rank, tp, model, host, port, result):
    my_layers = [partition_layer(layer, tp)[rank] for layer in model.layers]
    is_seeder = (rank == 0)
    client = AllReduceClient(host, port, rank=rank)
    schedule = [len(PROMPT)] + [1] * (N_NEW - 1)
    tokens, last_tok = [], None
    for step, seq_len in enumerate(schedule):
        if is_seeder:
            ids = PROMPT if step == 0 else [last_tok]
            x_seed = embed_lookup(model.embed, ids)
        else:
            x_seed = np.zeros((seq_len, HIDDEN), np.float32)
        x = client.all_reduce(x_seed)
        for my_layer in my_layers:
            x = tp_forward_layer_distributed(my_layer, x, client.all_reduce, session_id=SID)
        if is_seeder:
            last_tok = int(np.argmax(_logits_last(model, x[-1:])))
            tokens.append(last_tok)
    client.close()
    if is_seeder:
        result["tokens"] = tokens


def _distributed_generate(tp: int, seed: int = 2026):
    model = _build_model(seed)
    ref = generate_reference(model, PROMPT, N_NEW)
    srv = AllReduceServer(world_size=tp)
    srv.start()
    result: dict = {}
    threads = [threading.Thread(target=_run_rank, args=(r, tp, model, srv.host, srv.port, result))
               for r in range(tp)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    srv.close()
    return result.get("tokens"), ref


def test_distributed_generation_t2_matches_reference():
    got, ref = _distributed_generate(tp=2)
    assert got == ref, f"T=2 diverged: {got} != {ref}"


def test_distributed_generation_t4_matches_reference():
    got, ref = _distributed_generate(tp=4)
    assert got == ref, f"T=4 diverged: {got} != {ref}"

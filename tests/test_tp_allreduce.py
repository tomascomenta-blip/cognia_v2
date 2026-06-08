"""
tests/test_tp_allreduce.py
==========================
Phase 2: centralized socket all-reduce (shattering/tp_allreduce.py) and the
per-rank distributed forward (tp_forward_layer_distributed).

The reducer and clients talk over real TCP loopback; ranks run in threads here
for a deterministic test (a true 2-process run is scripts/tp_two_proc_demo.py).
The gate: a distributed forward across 2 rank-clients reproduces the in-process
tp_forward_layer (already proven == golden in Phase 1), and the sanity check
rejects a NaN-poisoned contribution instead of corrupting the sum.
"""

from __future__ import annotations

import threading

import numpy as np

from node.qwen2_ops import RealTransformerLayer, INT4Weights
from shattering.tensor_parallel import (
    partition_layer, tp_forward_layer, tp_forward_layer_distributed,
)
from shattering.tp_allreduce import AllReduceServer, AllReduceClient, is_sane


def _make_layer(H, KH, D, inter, seed) -> RealTransformerLayer:
    rng = np.random.default_rng(seed)
    hidden = H * D

    def w(out, inp, s=0.05):
        return INT4Weights.from_float32((rng.standard_normal((out, inp)) * s).astype(np.float32))

    return RealTransformerLayer(
        n_heads=H, n_kv_heads=KH, head_dim=D, rope_theta=1_000_000.0, rms_norm_eps=1e-6,
        w_q=w(H * D, hidden), w_k=w(KH * D, hidden), w_v=w(KH * D, hidden), w_o=w(hidden, H * D),
        w_gate=w(inter, hidden), w_up=w(inter, hidden), w_down=w(hidden, inter),
        norm1=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
        norm2=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
    )


def _rel_diff(a, b):
    return float(np.max(np.abs(a - b)) / (np.max(np.abs(b)) + 1e-6))


# ── reducer basics ───────────────────────────────────────────────────────────

def test_allreduce_sums_multi_round():
    srv = AllReduceServer(world_size=3)
    srv.start()
    results: dict = {}

    def rank(idx):
        c = AllReduceClient(srv.host, srv.port, rank=idx)
        r1 = c.all_reduce(np.full((2, 2), idx + 1, np.float32))      # sum = 1+2+3 = 6
        r2 = c.all_reduce(np.full((2, 2), (idx + 1) * 10, np.float32))  # sum = 60
        results[idx] = (r1, r2)
        c.close()

    threads = [threading.Thread(target=rank, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    srv.close()

    for i in range(3):
        assert np.allclose(results[i][0], 6.0)
        assert np.allclose(results[i][1], 60.0)


def test_sanity_check_unit():
    ok, _ = is_sane(np.ones((3, 3), np.float32))
    assert ok
    bad = np.ones((3, 3), np.float32); bad[1, 1] = np.nan
    ok, reason = is_sane(bad)
    assert not ok and "non-finite" in reason
    ok, reason = is_sane(np.full((2, 2), 1e9, np.float32))
    assert not ok and "magnitude" in reason


def test_sanity_rejects_nan_contribution():
    srv = AllReduceServer(world_size=2)
    srv.start()
    errors: dict = {}

    def good():
        c = AllReduceClient(srv.host, srv.port, rank=0)
        try:
            c.all_reduce(np.ones((2, 2), np.float32))
        except RuntimeError as e:
            errors["good"] = str(e)
        c.close()

    def bad():
        c = AllReduceClient(srv.host, srv.port, rank=1)
        arr = np.ones((2, 2), np.float32); arr[0, 0] = np.nan
        try:
            c.all_reduce(arr)
        except RuntimeError as e:
            errors["bad"] = str(e)
        c.close()

    tg, tb = threading.Thread(target=good), threading.Thread(target=bad)
    tg.start(); tb.start(); tg.join(5.0); tb.join(5.0)
    srv.close()

    # The poisoned round is rejected for everyone (visible expulsion), not summed.
    assert srv.expelled_rank is not None
    assert "good" in errors and "bad" in errors


# ── distributed forward == in-process forward ────────────────────────────────

def test_distributed_forward_matches_inprocess():
    layer = _make_layer(H=16, KH=2, D=128, inter=512, seed=7)
    hidden = 16 * 128
    rng = np.random.default_rng(700)
    x_a = (rng.standard_normal((4, hidden)) * 0.5).astype(np.float32)  # prefill
    x_b = (rng.standard_normal((1, hidden)) * 0.5).astype(np.float32)  # decode

    # Reference: in-process TP (proven == golden in Phase 1)
    ranks_ref = partition_layer(layer, 2)
    ref_a = tp_forward_layer(ranks_ref, x_a, session_id="s")
    ref_b = tp_forward_layer(ranks_ref, x_b, session_id="s")

    # Distributed: 2 rank-threads over a real socket reducer
    ranks_dist = partition_layer(layer, 2)
    srv = AllReduceServer(world_size=2)
    srv.start()
    outs: dict = {}

    def run_rank(idx):
        c = AllReduceClient(srv.host, srv.port, rank=idx)
        oa = tp_forward_layer_distributed(ranks_dist[idx], x_a, c.all_reduce, session_id="s")
        ob = tp_forward_layer_distributed(ranks_dist[idx], x_b, c.all_reduce, session_id="s")
        outs[idx] = (oa, ob)
        c.close()

    threads = [threading.Thread(target=run_rank, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    srv.close()

    for idx in range(2):
        assert _rel_diff(outs[idx][0], ref_a) < 1e-5
        assert _rel_diff(outs[idx][1], ref_b) < 1e-5

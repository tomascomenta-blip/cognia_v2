"""
scripts/tp_two_proc_demo.py
===========================
Phase 2 REAL check: run a tensor-parallel decoder layer across TWO SEPARATE OS
PROCESSES that all-reduce over real TCP sockets, and verify the result matches
the in-process reference (which Phase 1 proved == the golden forward).

The parent is the reducer (AllReduceServer) and holds the reference. It launches
two child processes; each rebuilds the same seeded layer, takes its rank's slice,
connects as an AllReduceClient, runs the distributed forward (prefill + decode),
and saves its final hidden to a .npy. The parent compares both to the reference.

(The deterministic seed stands in for the seeder streaming each rank its slice;
the point being verified here is the socket all-reduce, not weight distribution.)

Usage:
    venv312\\Scripts\\python.exe scripts\\tp_two_proc_demo.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

from node.qwen2_ops import RealTransformerLayer, INT4Weights  # noqa: E402
from shattering.tensor_parallel import (  # noqa: E402
    partition_layer, tp_forward_layer, tp_forward_layer_distributed,
)
from shattering.tp_allreduce import AllReduceServer, AllReduceClient  # noqa: E402

H, KH, D, INTER, TP = 16, 2, 128, 512, 2
SID = "demo"


def build_layer(seed: int) -> RealTransformerLayer:
    rng = np.random.default_rng(seed)
    hidden = H * D

    def w(out, inp, s=0.05):
        return INT4Weights.from_float32((rng.standard_normal((out, inp)) * s).astype(np.float32))

    return RealTransformerLayer(
        n_heads=H, n_kv_heads=KH, head_dim=D, rope_theta=1_000_000.0, rms_norm_eps=1e-6,
        w_q=w(H * D, hidden), w_k=w(KH * D, hidden), w_v=w(KH * D, hidden), w_o=w(hidden, H * D),
        w_gate=w(INTER, hidden), w_up=w(INTER, hidden), w_down=w(hidden, INTER),
        norm1=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
        norm2=(1.0 + rng.standard_normal(hidden) * 0.05).astype(np.float32),
    )


def build_inputs(seed: int):
    rng = np.random.default_rng(seed * 99 + 1)
    hidden = H * D
    x_a = (rng.standard_normal((4, hidden)) * 0.5).astype(np.float32)  # prefill
    x_b = (rng.standard_normal((1, hidden)) * 0.5).astype(np.float32)  # decode
    return x_a, x_b


def run_child(rank: int, host: str, port: int, seed: int, out: str) -> None:
    rank_layer = partition_layer(build_layer(seed), TP)[rank]
    x_a, x_b = build_inputs(seed)
    c = AllReduceClient(host, port, rank=rank)
    oa = tp_forward_layer_distributed(rank_layer, x_a, c.all_reduce, session_id=SID)
    ob = tp_forward_layer_distributed(rank_layer, x_b, c.all_reduce, session_id=SID)
    c.close()
    np.save(out, np.concatenate([oa, ob], axis=0))


def run_parent(seed: int) -> bool:
    layer = build_layer(seed)
    x_a, x_b = build_inputs(seed)
    ranks_ref = partition_layer(layer, TP)
    ref = np.concatenate([
        tp_forward_layer(ranks_ref, x_a, session_id=SID),
        tp_forward_layer(ranks_ref, x_b, session_id=SID),
    ], axis=0)

    srv = AllReduceServer(world_size=TP)
    srv.start()
    tmp = tempfile.mkdtemp(prefix="tp_demo_")
    env = dict(os.environ, PYTHONPATH=str(_ROOT))
    procs, outs = [], []
    for r in range(TP):
        out = os.path.join(tmp, f"rank_{r}.npy")
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "--rank", str(r), "--host", srv.host,
             "--port", str(srv.port), "--seed", str(seed), "--out", out],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        ))
    ok = True
    for r, p in enumerate(procs):
        _, err = p.communicate(timeout=180)
        if p.returncode != 0:
            ok = False
            print(f"  rank {r} process FAILED (exit {p.returncode}):\n{err.decode('utf-8','replace')[-800:]}")
    srv.close()

    print("=== Phase 2: 2-process tensor-parallel all-reduce over TCP ===")
    print(f"reducer (parent): {srv.host}:{srv.port}   world_size={TP}   ranks = 2 separate OS processes")
    for r in range(TP):
        if not os.path.exists(outs[r]):
            print(f"  rank {r}: no output produced  FAIL")
            ok = False
            continue
        got = np.load(outs[r])
        rd = float(np.max(np.abs(got - ref)) / (np.max(np.abs(ref)) + 1e-6))
        status = "OK" if rd < 1e-4 else "FAIL"
        if rd >= 1e-4:
            ok = False
        print(f"  rank {r} (PID-separate process): rel_diff vs in-process reference = {rd:.2e}  {status}")
    print(f"\nCHECK: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", type=int, default=None)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    if args.rank is None:
        return 0 if run_parent(args.seed) else 1
    run_child(args.rank, args.host, args.port, args.seed, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

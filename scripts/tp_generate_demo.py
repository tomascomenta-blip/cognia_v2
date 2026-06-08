"""
scripts/tp_generate_demo.py
===========================
Phase 3b REAL check: full-model token generation split across T SEPARATE OS
PROCESSES that all-reduce over real TCP sockets, verified to produce the IDENTICAL
greedy token sequence as the single-device reference.

Topology mirrors the design (SHATTERING_V2_DESIGN.md):
  - rank 0 doubles as the SEEDER: it owns embedding + final_norm + lm_head and
    decides each next token.
  - every rank owns its tensor-parallel slice of every decoder layer.

Broadcast trick: the seeder's embedded hidden is distributed to all ranks by
reusing the all-reduce itself — the seeder contributes the real hidden, every
other rank contributes zeros, so the sum delivered to everyone IS the hidden.
No extra primitive. Per token: 1 broadcast all-reduce + 2 per layer.

Usage:
    venv312\\Scripts\\python.exe scripts\\tp_generate_demo.py
    venv312\\Scripts\\python.exe scripts\\tp_generate_demo.py --tp 4
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

from node.qwen2_ops import RealTransformerLayer, INT4Weights  # noqa: E402
from shattering.tensor_parallel import partition_layer, tp_forward_layer_distributed  # noqa: E402
from shattering.tp_engine import (  # noqa: E402
    TPModelWeights, embed_lookup, _logits_last, generate_reference,
)
from shattering.tp_allreduce import AllReduceServer, AllReduceClient  # noqa: E402

# Same model on every process (deterministic seed stands in for the seeder
# streaming each rank its slice). KH=8 -> TP in {1,2,4,8}.
VOCAB, H, KH, D, INTER, N_LAYERS = 512, 16, 8, 16, 256, 3
HIDDEN = H * D
PROMPT = [3, 17, 42, 8, 100]
N_NEW = 10
SID = "gen"


def build_model(seed: int) -> TPModelWeights:
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


def run_child(rank: int, host: str, port: int, seed: int, tp: int, out: str) -> None:
    model = build_model(seed)
    my_layers = [partition_layer(layer, tp)[rank] for layer in model.layers]
    is_seeder = (rank == 0)
    client = AllReduceClient(host, port, rank=rank)

    # schedule of sequence lengths: prefill (len(PROMPT)) then N_NEW-1 single-token decodes
    schedule = [len(PROMPT)] + [1] * (N_NEW - 1)
    tokens: list = []
    last_tok = None

    for step, seq_len in enumerate(schedule):
        if is_seeder:
            ids = PROMPT if step == 0 else [last_tok]
            x_seed = embed_lookup(model.embed, ids)
        else:
            x_seed = np.zeros((seq_len, HIDDEN), np.float32)
        x = client.all_reduce(x_seed)                       # broadcast seeder's embed
        for my_layer in my_layers:
            x = tp_forward_layer_distributed(my_layer, x, client.all_reduce, session_id=SID)
        if is_seeder:
            last_tok = int(np.argmax(_logits_last(model, x[-1:])))
            tokens.append(last_tok)

    client.close()
    if is_seeder:
        Path(out).write_text(json.dumps(tokens))


def run_parent(seed: int, tp: int) -> bool:
    model = build_model(seed)
    ref = generate_reference(model, PROMPT, N_NEW)

    srv = AllReduceServer(world_size=tp)
    srv.start()
    tmp = tempfile.mkdtemp(prefix="tp_gen_")
    out0 = os.path.join(tmp, "tokens.json")
    env = dict(os.environ, PYTHONPATH=str(_ROOT))
    procs = []
    for r in range(tp):
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "--rank", str(r), "--host", srv.host,
             "--port", str(srv.port), "--seed", str(seed), "--tp", str(tp), "--out", out0],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        ))
    ok = True
    for r, p in enumerate(procs):
        _, err = p.communicate(timeout=240)
        if p.returncode != 0:
            ok = False
            print(f"  rank {r} FAILED (exit {p.returncode}):\n{err.decode('utf-8','replace')[-800:]}")
    srv.close()

    print(f"=== Phase 3b: {tp}-process tensor-parallel TEXT GENERATION over TCP ===")
    print(f"reducer (parent): {srv.host}:{srv.port}   world_size={tp}   rank0 = seeder (embed+lm_head)")
    print(f"  reference (single-device) : {ref}")
    if os.path.exists(out0):
        got = json.loads(Path(out0).read_text())
        match = got == ref
        ok = ok and match
        print(f"  distributed ({tp} processes): {got}")
        print(f"  tokens {'MATCH' if match else 'DIVERGE'}")
    else:
        ok = False
        print("  no tokens produced by seeder  FAIL")
    print(f"\nCHECK: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", type=int, default=None)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--tp", type=int, default=2)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    if args.rank is None:
        return 0 if run_parent(args.seed, args.tp) else 1
    run_child(args.rank, args.host, args.port, args.seed, args.tp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

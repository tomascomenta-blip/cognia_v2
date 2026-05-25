"""
scripts/benchmark_inference.py
================================
Benchmark Cognia shard inference components.

Usage:
    python scripts/benchmark_inference.py              # matmul kernels only
    python scripts/benchmark_inference.py --shards     # full shard forward pass

Reports:
  - Active kernel backend (numba / c_kernel / numpy_chunked)
  - INT4 matmul latency for typical Qwen weight shapes
  - RMSNorm and SiLU latency
  - Full shard-0 forward pass (if --shards and SHARD_WEIGHTS_DIR set)
  - DynamicWeights precision distribution after warmup
  - Projected full-model tok/s estimate
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def _hdr(title: str) -> None:
    print(f"\n--- {title} ---")


# ── Kernel backend benchmark ────────────────────────────────────────────────

def bench_int4_matmul() -> None:
    _hdr("INT4 matmul kernels")
    from node.qwen2_ops import INT4Weights, _NUMBA, _CLIB

    backend = "numba" if _NUMBA else ("c_kernel" if _CLIB else "numpy_chunked")
    print(f"Backend: {backend}")

    shapes = [
        ("q_proj  (2048 in, 2048 out)", 2048, 2048),
        ("gate    (2048 in, 8960 out)", 2048, 8960),
        ("lm_head (2048 in, 151936 out)", 2048, 151936),
    ]

    for label, in_dim, out_dim in shapes:
        np.random.seed(0)
        W  = (np.random.randn(out_dim, in_dim) * 0.02).astype(np.float32)
        w4 = INT4Weights.from_float32(W)
        x  = np.random.randn(1, in_dim).astype(np.float32)

        for _ in range(3):
            w4.linear(x)

        N  = 10 if out_dim < 100_000 else 3
        t0 = time.perf_counter()
        for _ in range(N):
            w4.linear(x)
        ms = (time.perf_counter() - t0) / N * 1000
        print(f"  {label}: {ms:.1f} ms")


# ── Primitive benchmark ─────────────────────────────────────────────────────

def bench_primitives() -> None:
    _hdr("RMSNorm + SiLU + 21.4 fusion")
    from node.qwen2_ops import _rms_norm, _silu, _rms_norm_linear, _silu_mul, _CLIB_FUSED, INT4Weights

    w  = np.ones(2048, dtype=np.float32)
    x  = np.random.randn(1, 2048).astype(np.float32)
    g  = np.random.randn(1, 8960).astype(np.float32)
    up = np.random.randn(1, 8960).astype(np.float32)

    print(f"  Fusion kernels active: {_CLIB_FUSED}")

    for _ in range(5):
        _rms_norm(x, w)
        _silu(g)

    N = 500
    t0 = time.perf_counter()
    for _ in range(N):
        _rms_norm(x, w)
    print(f"  RMSNorm (1x2048): {(time.perf_counter()-t0)/N*1000:.3f} ms")

    t0 = time.perf_counter()
    for _ in range(N):
        _silu(g)
    print(f"  SiLU    (1x8960): {(time.perf_counter()-t0)/N*1000:.3f} ms")

    # 21.4 fusion benchmarks
    np.random.seed(1)
    W_q = (np.random.randn(2048, 2048) * 0.02).astype(np.float32)
    w4q = INT4Weights.from_float32(W_q)
    for _ in range(3):
        _rms_norm_linear(x, w, w4q, 1e-6)
        _silu_mul(g.copy(), up)

    t0 = time.perf_counter()
    for _ in range(N):
        _rms_norm(x, w)
        w4q.linear(x)
    ms_unfused = (time.perf_counter() - t0) / N * 1000
    print(f"  RMSNorm+linear unfused (1x2048->2048): {ms_unfused:.3f} ms")

    t0 = time.perf_counter()
    for _ in range(N):
        _rms_norm_linear(x, w, w4q, 1e-6)
    ms_fused = (time.perf_counter() - t0) / N * 1000
    print(f"  rms_norm_linear fused  (1x2048->2048): {ms_fused:.3f} ms  "
          f"({ms_unfused/max(ms_fused,1e-9):.2f}x {'speedup' if ms_fused < ms_unfused else 'overhead'})")

    t0 = time.perf_counter()
    for _ in range(N):
        _silu(g) * up
    ms_unfused_s = (time.perf_counter() - t0) / N * 1000
    print(f"  SiLU*up unfused  (1x8960): {ms_unfused_s:.3f} ms")

    t0 = time.perf_counter()
    for _ in range(N):
        _silu_mul(g.copy(), up)
    ms_fused_s = (time.perf_counter() - t0) / N * 1000
    print(f"  silu_mul fused   (1x8960): {ms_fused_s:.3f} ms  "
          f"({ms_unfused_s/max(ms_fused_s,1e-9):.2f}x {'speedup' if ms_fused_s < ms_unfused_s else 'overhead'})")


# ── Shard forward benchmark ─────────────────────────────────────────────────

def bench_shards(shard_dir: str) -> None:
    _hdr("Full shard-0 forward pass")

    from node.shard_engine import ShardEngine, ShardConfig
    from shattering.model_constants import QWEN25_CODER_3B

    cfg_d = QWEN25_CODER_3B
    shard_path = Path(shard_dir) / "shard_0.npz"

    if not shard_path.is_file():
        print(f"  SKIP: {shard_path} not found")
        print("  Set SHARD_WEIGHTS_DIR env var or pass --shard-dir")
        return

    cfg = ShardConfig(
        model_name       = "qwen-coder-3b-q4",
        shard_index      = 0,
        n_shards         = cfg_d["n_shards"],
        total_layers     = cfg_d["total_layers"],
        hidden_dim       = cfg_d["hidden_dim"],
        intermediate_dim = cfg_d["intermediate_dim"],
        n_heads          = cfg_d["n_heads"],
        n_kv_heads       = cfg_d["n_kv_heads"],
        head_dim         = cfg_d["head_dim"],
        rope_theta       = cfg_d["rope_theta"],
        rms_norm_eps     = cfg_d["rms_norm_eps"],
    )

    print(f"  Loading shard_0 ...")
    t0 = time.perf_counter()
    engine = ShardEngine(cfg, shard_dir)
    load_s = time.perf_counter() - t0
    print(f"  Load time: {load_s:.1f} s")

    session_id  = "bench"
    prompt_ids  = np.array([1, 100, 200, 300, 500, 1000, 2000], dtype=np.int32)
    single_tok  = np.array([100], dtype=np.int32)

    # Cold prefill (INT4 dequant, no KV-cache)
    t0 = time.perf_counter()
    engine.process(None, token_ids=prompt_ids, session_id=session_id)
    cold_ms = (time.perf_counter() - t0) * 1000
    print(f"  Cold 7-token prefill: {cold_ms:.0f} ms")

    # Warm up DynamicWeights: 30 decode steps fill the FP32 tier
    print(f"  Warming DynamicWeights to FP32 tier (30 decode steps)...")
    for _ in range(30):
        engine.process(None, token_ids=single_tok, session_id=session_id)

    # Hot single-token decode (FP32 cached)
    N = 20
    t0 = time.perf_counter()
    for _ in range(N):
        engine.process(None, token_ids=single_tok, session_id=session_id)
    hot_ms = (time.perf_counter() - t0) / N * 1000
    print(f"  Hot single-token decode: {hot_ms:.1f} ms")
    print(f"  Speedup cold/hot: {cold_ms/7/hot_ms:.1f}x")

    # Projected full-model tok/s (rough: 4 shards, last shard has lm_head ~1.5x slower)
    # Assumes other shards are similar to shard-0; last shard adds lm_head overhead
    est_ms_per_tok = hot_ms * 3 + hot_ms * 1.5  # 3 normal + 1 lm_head shard
    est_tok_s = 1000 / est_ms_per_tok
    print(f"  Projected full-model tok/s: ~{est_tok_s:.2f} tok/s (4-shard estimate)")

    # Precision stats
    pm = getattr(engine, "_precision_manager", None)
    if pm is not None:
        stats = pm.stats()
        print(f"  DynQuant after warmup: {stats['by_precision']}")


# ── KV-cache effectiveness ──────────────────────────────────────────────────

def bench_kv_cache(shard_dir: str) -> None:
    _hdr("KV-cache effectiveness (intra-turn)")

    from node.shard_engine import ShardEngine, ShardConfig
    from shattering.model_constants import QWEN25_CODER_3B

    cfg_d = QWEN25_CODER_3B
    if not (Path(shard_dir) / "shard_0.npz").is_file():
        print("  SKIP: no shard_0.npz")
        return

    cfg = ShardConfig(
        model_name       = "qwen-coder-3b-q4",
        shard_index      = 0,
        n_shards         = cfg_d["n_shards"],
        total_layers     = cfg_d["total_layers"],
        hidden_dim       = cfg_d["hidden_dim"],
        intermediate_dim = cfg_d["intermediate_dim"],
        n_heads          = cfg_d["n_heads"],
        n_kv_heads       = cfg_d["n_kv_heads"],
        head_dim         = cfg_d["head_dim"],
        rope_theta       = cfg_d["rope_theta"],
        rms_norm_eps     = cfg_d["rms_norm_eps"],
    )
    engine = ShardEngine(cfg, shard_dir)

    # Warm up
    for _ in range(35):
        engine.process(None, token_ids=np.array([100], dtype=np.int32), session_id="bench")

    # With KV-cache (tokens accumulate in session)
    N, session_kv = 10, "kv_bench"
    ids_seq = np.arange(1, N + 2, dtype=np.int32)
    t0 = time.perf_counter()
    for tok in ids_seq:
        engine.process(None, token_ids=np.array([tok], dtype=np.int32), session_id=session_kv)
    kv_ms = (time.perf_counter() - t0) / (N + 1) * 1000

    # Without KV-cache (fresh session each call simulates no-cache)
    t0 = time.perf_counter()
    for tok in ids_seq:
        fresh_sid = f"fresh_{tok}"
        engine.process(None, token_ids=np.array([tok], dtype=np.int32), session_id=fresh_sid)
    no_kv_ms = (time.perf_counter() - t0) / (N + 1) * 1000

    print(f"  Single-token with KV-cache:    {kv_ms:.1f} ms")
    print(f"  Single-token without KV-cache: {no_kv_ms:.1f} ms")
    print(f"  KV-cache overhead: {kv_ms - no_kv_ms:+.1f} ms (KV concat)")


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Cognia inference benchmark")
    parser.add_argument(
        "--shards", action="store_true",
        help="Run full shard forward-pass benchmark (loads shard_0.npz, may take minutes)",
    )
    parser.add_argument(
        "--shard-dir", default=None,
        help="Directory with shard_*.npz (defaults to SHARD_WEIGHTS_DIR env var)",
    )
    args = parser.parse_args()

    bench_int4_matmul()
    bench_primitives()

    if args.shards:
        shard_dir = args.shard_dir or os.environ.get("SHARD_WEIGHTS_DIR", "")
        bench_shards(shard_dir)
        bench_kv_cache(shard_dir)

    print("\nBenchmark complete.")


if __name__ == "__main__":
    main()

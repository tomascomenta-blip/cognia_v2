#!/usr/bin/env python3
"""
scripts/scale_shards.py
Phase 20.3 Depth Up-Scaling (DUS) -- merge two adjacent INT4 .npz shards with
alpha-blended boundary layer into one deeper shard.

Usage:
    python scripts/scale_shards.py \
        --shard-dir model_shards/qwen-coder-3b-q4 \
        --shard-a 0 --shard-b 1 \
        --out model_shards/qwen-coder-3b-q4/shard_merged_01.npz \
        [--alpha 0.5] [--out-shard-index 0]

Output shard has (L_a + L_b - 1) layers: the shared boundary is blended,
not duplicated. Compatible with ShardEngine layer key format l{i}_*.
"""

import argparse
import os
import sys

import numpy as np


# ── INT4 helpers ─────────────────────────────────────────────────────────────

def _dequant_int4(packed: np.ndarray, scales: np.ndarray) -> np.ndarray:
    """
    Unpack nibble-packed INT4 weights and apply per-row scales -> float32.
    packed: uint8 array shape (n_rows, ceil(n_cols/2))
    scales: float16 array shape (n_rows,)
    Returns float32 (n_rows, n_cols_packed*2) -- last col may be padding.
    """
    n_rows = packed.shape[0]
    # low nibble + high nibble
    lo = (packed & 0x0F).astype(np.int8)
    hi = ((packed >> 4) & 0x0F).astype(np.int8)
    # signed: 0-7 positive, 8-15 -> -8..-1
    lo = np.where(lo > 7, lo - 16, lo)
    hi = np.where(hi > 7, hi - 16, hi)
    # interleave: col 0 = lo nibble, col 1 = hi nibble of each byte
    interleaved = np.empty((n_rows, packed.shape[1] * 2), dtype=np.float32)
    interleaved[:, 0::2] = lo.astype(np.float32)
    interleaved[:, 1::2] = hi.astype(np.float32)
    # per-row scale
    s = scales.astype(np.float32).reshape(n_rows, 1)
    return interleaved * s


def _requant_int4(weight: np.ndarray):
    """
    Quantize float32 weight matrix to INT4 nibble-packed format.
    weight: float32 (n_rows, n_cols)
    Returns (packed uint8, scales float16).
    per-row symmetric: scale = max(|row|) / 7, clamp to [-7,7], pack nibbles.
    """
    n_rows, n_cols = weight.shape
    abs_max = np.abs(weight).max(axis=1, keepdims=True)
    # avoid div-by-zero for zero rows
    abs_max = np.where(abs_max == 0, 1.0, abs_max)
    scales = (abs_max / 7.0).astype(np.float32)
    quantized = np.clip(np.round(weight / scales), -7, 7).astype(np.int8)
    # pack pairs of cols into nibbles: col j -> lo nibble, col j+1 -> hi nibble
    # pad to even col count
    if n_cols % 2 != 0:
        quantized = np.concatenate(
            [quantized, np.zeros((n_rows, 1), dtype=np.int8)], axis=1
        )
    n_cols_padded = quantized.shape[1]
    lo = quantized[:, 0::2] & 0x0F          # low nibble
    hi = (quantized[:, 1::2] & 0x0F) << 4   # high nibble
    packed = (lo | hi).astype(np.uint8)
    return packed, scales.squeeze(1).astype(np.float16)


# ── Layer helpers ─────────────────────────────────────────────────────────────

_WEIGHT_SUFFIXES = ("q", "k", "v", "o", "g", "u", "d")
_NORM_SUFFIXES   = ("n1", "n2")


def _layer_keys(data, idx: int) -> list:
    prefix = f"l{idx}_"
    return [k for k in data.files if k.startswith(prefix)]


def _layer_indices(data) -> list:
    seen = set()
    for k in data.files:
        if k.startswith("l") and "_" in k:
            try:
                seen.add(int(k[1:k.index("_")]))
            except ValueError:
                pass
    return sorted(seen)


def _copy_layer(src, src_idx: int, dst: dict, dst_idx: int) -> None:
    prefix_src = f"l{src_idx}_"
    prefix_dst = f"l{dst_idx}_"
    for k in src.files:
        if k.startswith(prefix_src):
            suffix = k[len(prefix_src):]
            dst[f"{prefix_dst}{suffix}"] = src[k]


def _blend_layer(
    a_data,
    a_idx: int,
    b_data,
    b_idx: int,
    dst: dict,
    dst_idx: int,
    alpha: float,
) -> None:
    """
    Write a blended boundary layer into dst at dst_idx.
    For INT4 weight arrays (_p + _s pairs): dequant both, blend float32,
    requant to INT4. For norm arrays (n1, n2): linear blend float32.
    _oc (original cols) taken from A side (shape should match).
    """
    prefix_a = f"l{a_idx}_"
    prefix_b = f"l{b_idx}_"
    prefix_d = f"l{dst_idx}_"

    # collect all suffixes present in both layers
    keys_a = {k[len(prefix_a):] for k in a_data.files if k.startswith(prefix_a)}
    keys_b = {k[len(prefix_b):] for k in b_data.files if k.startswith(prefix_b)}
    all_suffixes = keys_a | keys_b

    # process weight tensor groups: q, k, v, o, g, u, d
    for w in _WEIGHT_SUFFIXES:
        p_key = f"{w}_p"
        s_key = f"{w}_s"
        oc_key = f"{w}_oc"
        if p_key not in all_suffixes or s_key not in all_suffixes:
            continue
        a_p = a_data[f"{prefix_a}{p_key}"]
        a_s = a_data[f"{prefix_a}{s_key}"]
        b_p = b_data[f"{prefix_b}{p_key}"]
        b_s = b_data[f"{prefix_b}{s_key}"]

        a_f = _dequant_int4(a_p, a_s)
        b_f = _dequant_int4(b_p, b_s)

        # shapes may differ in padded cols; trim to min for blending
        n_rows = min(a_f.shape[0], b_f.shape[0])
        n_cols = min(a_f.shape[1], b_f.shape[1])
        blended = alpha * a_f[:n_rows, :n_cols] + (1.0 - alpha) * b_f[:n_rows, :n_cols]

        new_p, new_s = _requant_int4(blended)
        dst[f"{prefix_d}{p_key}"] = new_p
        dst[f"{prefix_d}{s_key}"] = new_s

        # _oc carries original (unpadded) col count -- keep A's value
        if oc_key in keys_a:
            dst[f"{prefix_d}{oc_key}"] = a_data[f"{prefix_a}{oc_key}"]

    # norm arrays: simple float32 blend
    for n in _NORM_SUFFIXES:
        if n not in all_suffixes:
            continue
        a_n = a_data[f"{prefix_a}{n}"].astype(np.float32)
        b_n = b_data[f"{prefix_b}{n}"].astype(np.float32)
        n_elem = min(a_n.size, b_n.size)
        blended_n = alpha * a_n[:n_elem] + (1.0 - alpha) * b_n[:n_elem]
        dst[f"{prefix_d}{n}"] = blended_n.astype(a_data[f"{prefix_a}{n}"].dtype)


# ── Main merge ────────────────────────────────────────────────────────────────

def merge_shards(
    shard_dir: str,
    shard_a_idx: int,
    shard_b_idx: int,
    out_path: str,
    alpha: float,
    out_shard_index: int,
) -> None:
    path_a = os.path.join(shard_dir, f"shard_{shard_a_idx}.npz")
    path_b = os.path.join(shard_dir, f"shard_{shard_b_idx}.npz")

    for p, label in ((path_a, "shard-a"), (path_b, "shard-b")):
        if not os.path.exists(p):
            print(f"ERROR: {label} not found: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"Loading {path_a}")
    da = np.load(path_a, allow_pickle=False)
    print(f"Loading {path_b}")
    db = np.load(path_b, allow_pickle=False)

    layers_a = _layer_indices(da)
    layers_b = _layer_indices(db)

    if not layers_a:
        print("ERROR: shard-a has no transformer layers", file=sys.stderr)
        sys.exit(1)
    if not layers_b:
        print("ERROR: shard-b has no transformer layers", file=sys.stderr)
        sys.exit(1)

    n_a = len(layers_a)
    n_b = len(layers_b)
    last_a = layers_a[-1]  # absolute layer index of boundary in A
    first_b = layers_b[0]  # absolute layer index of boundary in B

    # DUS output layer count: N_a + N_b - 1  (boundary blended, not duplicated)
    n_out = n_a + n_b - 1

    print(f"  shard-a  : layers {layers_a[0]}..{last_a} ({n_a} layers, file index {shard_a_idx})")
    print(f"  shard-b  : layers {first_b}..{layers_b[-1]} ({n_b} layers, file index {shard_b_idx})")
    print(f"  merged   : {n_out} layers -> output shard index {out_shard_index}")
    print(f"  alpha    : {alpha}  (boundary blend: {alpha:.2f}*A + {1-alpha:.2f}*B)")

    merged: dict = {}

    # embed_* from shard-a when it is the first shard in the model
    if shard_a_idx == 0:
        for k in da.files:
            if k.startswith("embed_"):
                merged[k] = da[k]

    # Layers 0..N_a-2 from shard A (all except the last layer), re-keyed to 0-based
    for local_i, abs_i in enumerate(layers_a[:-1]):
        _copy_layer(da, abs_i, merged, local_i)

    # Boundary layer: blend last layer of A and first layer of B -> dst index N_a-1
    boundary_dst = n_a - 1
    _blend_layer(da, last_a, db, first_b, merged, boundary_dst, alpha)

    # Layers 1..N_b-1 from shard B (all except the first layer), re-keyed after boundary
    for local_j, abs_j in enumerate(layers_b[1:], start=1):
        dst_idx = n_a - 1 + local_j  # boundary at n_a-1, then n_a, n_a+1, ...
        _copy_layer(db, abs_j, merged, dst_idx)

    # lm_*/final_norm from shard-b when it is the last shard in the model
    if shard_b_idx == 3:
        for k in db.files:
            if k.startswith("lm_") or k == "final_norm":
                merged[k] = db[k]

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)

    print(f"Saving -> {out_path}")
    np.savez_compressed(out_path, **merged)

    size_mb = os.path.getsize(out_path) / 1e6
    n_keys  = len(merged)
    print(f"  Output  : {out_path}")
    print(f"  Size    : {size_mb:.1f} MB")
    print(f"  Keys    : {n_keys}")
    print(f"  Layers  : {n_out}  (={n_a}+{n_b}-1, boundary blended at alpha={alpha})")
    print("Done.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="DUS: merge two adjacent INT4 shard .npz files with alpha-blended boundary"
    )
    p.add_argument("--shard-dir", required=True,
                   help="Directory containing shard_N.npz files")
    p.add_argument("--shard-a", type=int, required=True,
                   help="Index of the first (lower) shard (e.g. 0)")
    p.add_argument("--shard-b", type=int, required=True,
                   help="Index of the second (higher) shard; must equal shard-a + 1")
    p.add_argument("--out", required=True,
                   help="Output path for the merged .npz shard")
    p.add_argument("--alpha", type=float, default=0.5,
                   help="Blend weight for boundary layer: alpha*A + (1-alpha)*B  (default 0.5)")
    p.add_argument("--out-shard-index", type=int, default=None,
                   help="Logical shard index to label the output (informational; default=shard-a)")
    args = p.parse_args()

    if args.shard_b != args.shard_a + 1:
        print(
            f"ERROR: shards must be adjacent. shard-b ({args.shard_b}) "
            f"must equal shard-a ({args.shard_a}) + 1.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not (0.0 < args.alpha <= 1.0):
        print("ERROR: --alpha must be in (0.0, 1.0]", file=sys.stderr)
        sys.exit(1)

    out_shard_index = args.out_shard_index if args.out_shard_index is not None else args.shard_a

    merge_shards(
        shard_dir=args.shard_dir,
        shard_a_idx=args.shard_a,
        shard_b_idx=args.shard_b,
        out_path=args.out,
        alpha=args.alpha,
        out_shard_index=out_shard_index,
    )


if __name__ == "__main__":
    main()

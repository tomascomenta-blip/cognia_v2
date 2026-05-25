"""
scripts/build_draft_model.py
============================
Distills a 2-layer 256-dim "nano-draft" transformer from the first two
transformer layers of shard_0.npz using a PCA projection.

Usage:
    python scripts/build_draft_model.py
    python scripts/build_draft_model.py --shard-dir path/to/shards --out path/to/nano_draft.npz

Output: nano_draft.npz (~150 MB float16, placed next to shard files)
Build time: ~2-5 minutes (SVD on embedding subset).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from shattering.quantization import dequantize_int4

_NANO_HIDDEN   = 256
_NANO_HEADS    = 4
_NANO_KV_HEADS = 1
_NANO_HEAD_DIM = _NANO_HIDDEN // _NANO_HEADS   # 64
_NANO_MLP      = 1024
_SVD_SAMPLE    = 2000   # rows to sample for PCA (full SVD of 151936 rows is slow)


def _dequant(npz, prefix: str) -> np.ndarray:
    """Dequantize a key group. embed uses _ocols; layer weights use _oc."""
    oc_key = f"{prefix}_ocols" if f"{prefix}_ocols" in npz.files else f"{prefix}_oc"
    return dequantize_int4(npz[f"{prefix}_p"], npz[f"{prefix}_s"], int(npz[oc_key]))


def build(shard_dir: Path, out_path: Path) -> None:
    shard0 = np.load(shard_dir / "shard_0.npz")
    print(f"[build_draft] loaded shard_0 ({len(shard0.files)} keys)")

    # 1. Dequantize embedding (151936, 2048)
    print("[build_draft] dequantizing embedding ...")
    embed_fp32 = _dequant(shard0, "embed")   # (151936, 2048)

    # 2. PCA projection 2048 → 256 via SVD on a random subset of rows
    print(f"[build_draft] computing PCA projection ({_SVD_SAMPLE} samples) ...")
    np.random.seed(42)
    idx    = np.random.choice(embed_fp32.shape[0], _SVD_SAMPLE, replace=False)
    sample = embed_fp32[idx] - embed_fp32[idx].mean(0)  # center
    _, _, Vt = np.linalg.svd(sample, full_matrices=False)
    P = Vt[:_NANO_HIDDEN].T  # (2048, 256) — top-256 principal directions

    # 3. Project embedding
    print("[build_draft] projecting embedding ...")
    nano_embed = embed_fp32 @ P  # (151936, 256)
    std = nano_embed.std(0).clip(1e-6)
    nano_embed /= std   # normalize per dimension to unit variance

    # 4. Project first 2 transformer layers
    out = {}
    for li in range(2):
        print(f"[build_draft] projecting layer {li} ...")

        Q = _dequant(shard0, f"l{li}_q")   # (2048, 2048): hidden → n_heads*head_dim
        K = _dequant(shard0, f"l{li}_k")   # (256,  2048): hidden → kv_heads*head_dim
        V = _dequant(shard0, f"l{li}_v")   # (256,  2048)
        O = _dequant(shard0, f"l{li}_o")   # (2048, 2048): n_heads*head_dim → hidden

        # Q,O: both dims map through hidden → project both sides
        Q_nano = P.T @ Q @ P   # (256, 256)
        O_nano = P.T @ O @ P   # (256, 256)

        # K,V: input is hidden (project with P), output dim shrunk to nano KV size
        K_nano = (K @ P)[:_NANO_KV_HEADS * _NANO_HEAD_DIM, :]   # (64, 256)
        V_nano = (V @ P)[:_NANO_KV_HEADS * _NANO_HEAD_DIM, :]

        # MLP gate/up: (11008, 2048) → (1024, 256)
        G = _dequant(shard0, f"l{li}_g")   # (11008, 2048)
        U = _dequant(shard0, f"l{li}_u")   # (11008, 2048)
        D = _dequant(shard0, f"l{li}_d")   # (2048, 11008)

        G_nano = (G @ P)[:_NANO_MLP, :]   # (1024, 256)
        U_nano = (U @ P)[:_NANO_MLP, :]
        # down: (2048, 11008) → maps mlp_inter → hidden; nano: (256, 1024)
        D_nano = P.T @ D[:, :_NANO_MLP]   # (256, 1024)

        out[f"l{li}_q"]    = Q_nano.astype(np.float16)
        out[f"l{li}_k"]    = K_nano.astype(np.float16)
        out[f"l{li}_v"]    = V_nano.astype(np.float16)
        out[f"l{li}_o"]    = O_nano.astype(np.float16)
        out[f"l{li}_gate"] = G_nano.astype(np.float16)
        out[f"l{li}_up"]   = U_nano.astype(np.float16)
        out[f"l{li}_down"] = D_nano.astype(np.float16)
        # Norm weights: identity in projected space (unit-normalized dims above)
        out[f"l{li}_n1"] = np.ones(_NANO_HIDDEN, dtype=np.float32)
        out[f"l{li}_n2"] = np.ones(_NANO_HIDDEN, dtype=np.float32)

    # 5. lm_head = projected embedding (tied weights, already unit-variance)
    out["embed"]   = nano_embed.astype(np.float16)   # (151936, 256)
    out["lm_head"] = nano_embed.astype(np.float16)   # tied
    out["norm_f"]  = np.ones(_NANO_HIDDEN, dtype=np.float32)

    # 6. Save
    print(f"[build_draft] saving to {out_path} ...")
    np.savez_compressed(str(out_path), **out)
    size_mb = out_path.stat().st_size / 1e6
    print(f"[build_draft] done. File size: {size_mb:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Build nano-draft model from shard_0")
    default_dir = os.environ.get(
        "SHARD_WEIGHTS_DIR",
        str(Path(__file__).parent.parent / "model_shards" / "qwen-coder-3b-q4"),
    )
    parser.add_argument("--shard-dir", default=default_dir, help="Directory with shard_*.npz files")
    parser.add_argument("--out", default=None, help="Output path for nano_draft.npz")
    args = parser.parse_args()

    shard_dir = Path(args.shard_dir)
    out_path  = Path(args.out) if args.out else shard_dir / "nano_draft.npz"

    if not (shard_dir / "shard_0.npz").is_file():
        print(f"ERROR: shard_0.npz not found in {shard_dir}")
        sys.exit(1)

    if out_path.is_file():
        print(f"nano_draft.npz already exists at {out_path}. Delete it to rebuild.")
        sys.exit(0)

    build(shard_dir, out_path)


if __name__ == "__main__":
    main()

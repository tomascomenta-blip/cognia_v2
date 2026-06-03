"""
scripts/unpack_shards.py
Convert compressed .npz shards to per-array .npy files for zero-copy mmap loading.

Compressed NPZ forces numpy to decompress every array into heap RAM at load time.
Individual .npy files can be mmap'd directly (np.load(path, mmap_mode='r')), so
the OS manages which pages stay in RAM and can evict weight pages that are not
currently being computed.

Usage:
    python scripts/unpack_shards.py --shard-dir model_shards/qwen-coder-3b-q4

Each shard_N.npz becomes shard_N/ directory containing one .npy per array key.
The original .npz files are NOT deleted; the loader uses the directory if present.

Expected disk space: ~1.6 GB for all 4 shards (INT4 packed uint8 + float32 scales).
Compressed originals: ~1.2 GB. Net increase: ~400 MB.
"""

import argparse
import os
import sys

import numpy as np


def unpack_shard(npz_path: str, out_dir: str) -> int:
    """Unpack one .npz to a directory of .npy files. Returns number of arrays written."""
    os.makedirs(out_dir, exist_ok=True)
    data = np.load(npz_path, allow_pickle=False)
    keys = list(data.keys())
    for k in keys:
        arr = data[k]
        np.save(os.path.join(out_dir, f"{k}.npy"), arr)
    data.close()
    return len(keys)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-dir", default="model_shards/qwen-coder-3b-q4",
                        help="Directory containing shard_N.npz files")
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()

    base = args.shard_dir
    for idx in range(args.shards):
        npz_path = os.path.join(base, f"shard_{idx}.npz")
        if not os.path.exists(npz_path):
            print(f"  skip shard_{idx}.npz (not found)")
            continue
        out_dir = os.path.join(base, f"shard_{idx}")
        if os.path.isdir(out_dir):
            print(f"  shard_{idx}/ already exists, skipping")
            continue
        print(f"  unpacking shard_{idx}.npz -> shard_{idx}/ ...", end=" ", flush=True)
        n = unpack_shard(npz_path, out_dir)
        size_mb = sum(
            os.path.getsize(os.path.join(out_dir, f))
            for f in os.listdir(out_dir)
        ) / 1e6
        print(f"{n} arrays, {size_mb:.0f} MB")

    print("Done. Run inference to use mmap-backed weights.")


if __name__ == "__main__":
    main()

"""
scripts/download_and_convert_qwen.py
=====================================
Downloads Qwen2.5-Coder-3B-Instruct from HuggingFace and converts it to
INT4 .npz shards ready for ShardEngine.

Steps:
  1. Download safetensors + config to model_shards/qwen_hf_temp/
  2. Convert all 4 shards to model_shards/qwen-coder-3b-q4/
  3. Delete the temp download to recover disk space

Usage:
    python scripts/download_and_convert_qwen.py
    python scripts/download_and_convert_qwen.py --skip-download   # if already downloaded
    python scripts/download_and_convert_qwen.py --hf-token TOKEN  # for private mirrors
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Direct file imports — bypass shattering/__init__.py chain.
import importlib.util as _ilu

def _load_file(name: str, rel: str):
    spec = _ilu.spec_from_file_location(name, str(ROOT / rel))
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

HF_MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct"
HF_TEMP  = ROOT / "model_shards" / "qwen_hf_temp"
OUT_DIR  = ROOT / "model_shards" / "qwen-coder-3b-q4"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _check_disk(required_gb: float) -> None:
    free = shutil.disk_usage(str(ROOT)).free / 1e9
    _log(f"  Disk free: {free:.1f} GB  (need ~{required_gb:.1f} GB)")
    if free < required_gb:
        _log(f"ERROR: insufficient disk space ({free:.1f} GB free, need {required_gb:.1f} GB)")
        sys.exit(1)


def step_download(hf_token: str | None) -> None:
    _log(f"\n[1/3] Downloading {HF_MODEL}")
    _log(f"      -> {HF_TEMP}")
    _check_disk(required_gb=7.0)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        _log("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    snapshot_download(
        repo_id=HF_MODEL,
        local_dir=str(HF_TEMP),
        local_dir_use_symlinks=False,
        token=hf_token or None,
        ignore_patterns=[
            "*.msgpack", "*.h5", "*.ot",
            "flax_model*", "tf_model*", "rust_model*",
            "pytorch_model*.bin",
        ],
    )
    size_gb = sum(f.stat().st_size for f in HF_TEMP.rglob("*") if f.is_file()) / 1e9
    _log(f"[1/3] Download complete ({size_gb:.2f} GB).")


def step_convert() -> None:
    _conv = _load_file("_convert_hf_to_shards", "scripts/convert_hf_to_shards.py")
    _build_tensor_map = _conv._build_tensor_map
    convert_shard     = _conv.convert_shard

    _mc = _load_file("_model_constants", "shattering/model_constants.py")
    QWEN25_CODER_3B = _mc.QWEN25_CODER_3B

    _log(f"\n[2/3] Converting to INT4 shards")
    _log(f"      hf-dir : {HF_TEMP}")
    _log(f"      out-dir: {OUT_DIR}")
    _check_disk(required_gb=2.0)

    t0  = time.perf_counter()
    cfg = QWEN25_CODER_3B

    _log(f"  Indexing tensors...")
    tensor_map = _build_tensor_map(str(HF_TEMP))
    _log(f"  {len(tensor_map)} tensors indexed.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for shard_idx in range(cfg["n_shards"]):
        _log(f"\n  Shard {shard_idx}/{cfg['n_shards'] - 1}...")
        convert_shard(
            shard_idx    = shard_idx,
            tensor_map   = tensor_map,
            total_layers = cfg["total_layers"],
            n_shards     = cfg["n_shards"],
            out_dir      = str(OUT_DIR),
        )

    elapsed = time.perf_counter() - t0
    _log(f"\n[2/3] Conversion complete in {elapsed:.0f}s.")

    total_mb = sum(f.stat().st_size for f in OUT_DIR.glob("*.npz")) / 1e6
    for f in sorted(OUT_DIR.glob("*.npz")):
        _log(f"  {f.name}: {f.stat().st_size / 1e6:.1f} MB")
    _log(f"  Total: {total_mb:.0f} MB")


def step_cleanup() -> None:
    _log(f"\n[3/3] Removing temp download: {HF_TEMP}")
    if HF_TEMP.exists():
        shutil.rmtree(str(HF_TEMP))
        _log("[3/3] Cleanup done.")
    else:
        _log("[3/3] Temp dir already gone, nothing to clean.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download + convert Qwen weights to INT4 shards")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip download (use existing qwen_hf_temp/)")
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="Keep the raw HF download after conversion")
    parser.add_argument("--hf-token", default=None,
                        help="HuggingFace token (not required for this public model)")
    args = parser.parse_args()

    _log("=== Qwen2.5-Coder-3B-Instruct: download + INT4 conversion ===")

    # Safeguard: skip download if shards already exist
    existing = list(OUT_DIR.glob("shard_*.npz")) if OUT_DIR.exists() else []
    if len(existing) == 4:
        _log(f"\nAll 4 shards already present in {OUT_DIR}. Nothing to do.")
        _log("To re-convert, delete model_shards/qwen-coder-3b-q4/ first.")
        sys.exit(0)

    try:
        from safetensors import safe_open  # noqa: F401
    except ImportError:
        _log("ERROR: safetensors not installed. Run: pip install safetensors")
        sys.exit(1)

    if not args.skip_download:
        step_download(args.hf_token)
    else:
        if not HF_TEMP.exists():
            _log(f"ERROR: --skip-download used but {HF_TEMP} does not exist.")
            sys.exit(1)
        _log(f"\n[1/3] Skipped download, using existing {HF_TEMP}")

    step_convert()

    if not args.skip_cleanup:
        step_cleanup()
    else:
        _log("\n[3/3] Cleanup skipped (--skip-cleanup). Remove manually when no longer needed.")

    _log("\n=== SUCCESS ===")
    _log(f"Shards at: {OUT_DIR}")
    _log("To use real weights, initialize ShardEngine with:")
    _log(f"  ShardEngine(config, weights_path='{OUT_DIR}')")


if __name__ == "__main__":
    main()

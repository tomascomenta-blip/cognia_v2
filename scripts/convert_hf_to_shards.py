"""
scripts/convert_hf_to_shards.py
================================
Convert a Qwen2.5-Coder-3B-Instruct HuggingFace checkpoint into INT4 .npz
shard files ready for ShardEngine.

Usage:
    python scripts/convert_hf_to_shards.py \\
        --hf-dir   /path/to/qwen2.5-coder-3b-instruct \\
        --out-dir  model_shards/qwen-coder-3b-q4      \\
        --n-shards 4

Output files:  out-dir/shard_0.npz  shard_1.npz  shard_2.npz  shard_3.npz

Each .npz stores:
  l{i}_q_p,  l{i}_q_s,  l{i}_q_oc   — q_proj INT4 (packed, scale, orig_cols)
  l{i}_k_p,  l{i}_k_s,  l{i}_k_oc   — k_proj
  l{i}_v_p,  l{i}_v_s,  l{i}_v_oc   — v_proj
  l{i}_o_p,  l{i}_o_s,  l{i}_o_oc   — o_proj
  l{i}_g_p,  l{i}_g_s,  l{i}_g_oc   — gate_proj
  l{i}_u_p,  l{i}_u_s,  l{i}_u_oc   — up_proj
  l{i}_d_p,  l{i}_d_s,  l{i}_d_oc   — down_proj
  l{i}_n1,   l{i}_n2                 — layernorm weights (float32)

Shard 0 only:
  embed_p, embed_s, embed_ocols       — embedding table INT4

Last shard only:
  lm_p, lm_s, lm_ocols               — lm_head INT4
  final_norm                          — model.norm.weight float32

Requires: safetensors, numpy.  No PyTorch dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np

_ROOT = Path(__file__).parent.parent

# Direct file imports — bypass shattering/__init__.py to avoid pulling in the
# full cognia stack (orchestrator -> security -> cognia -> fatiga_cognitiva, etc.).
import importlib.util as _ilu

def _load_file(name: str, rel: str):
    spec = _ilu.spec_from_file_location(name, str(_ROOT / rel))
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_quant = _load_file("_shattering_quantization", "shattering/quantization.py")
quantize_int4 = _quant.quantize_int4

_mc = _load_file("_shattering_model_constants", "shattering/model_constants.py")
QWEN25_CODER_3B = _mc.QWEN25_CODER_3B


# ── Safetensors loader ───────────────────────────────────────────────────────

def _build_tensor_map(hf_dir: str) -> Dict[str, str]:
    """
    Returns {tensor_name: abs_path_to_safetensors_file}.
    Supports both single model.safetensors and sharded index.
    """
    index_path = os.path.join(hf_dir, "model.safetensors.index.json")
    if os.path.exists(index_path):
        with open(index_path) as f:
            weight_map = json.load(f)["weight_map"]
        return {k: os.path.join(hf_dir, v) for k, v in weight_map.items()}
    single = os.path.join(hf_dir, "model.safetensors")
    if os.path.exists(single):
        from safetensors import safe_open
        with safe_open(single, framework="numpy") as st:
            return {k: single for k in st.keys()}
    raise FileNotFoundError(
        f"No safetensors files found in {hf_dir!r}. "
        "Run: huggingface-cli download Qwen/Qwen2.5-Coder-3B-Instruct"
    )


def _bf16_bytes_to_f32(raw: bytes, shape: tuple) -> np.ndarray:
    """
    Convert raw BF16 bytes to float32 without PyTorch.
    BF16 is identical to the upper 16 bits of IEEE-754 float32,
    so we zero-pad each uint16 to uint32 and reinterpret as float32.
    """
    u16 = np.frombuffer(raw, dtype=np.uint16)
    f32 = (u16.astype(np.uint32) << 16).view(np.float32)
    return f32.reshape(shape)


def _load_tensor(tensor_map: Dict[str, str], name: str) -> Optional[np.ndarray]:
    path = tensor_map.get(name)
    if not path:
        return None

    # Fast path: try safetensors numpy loader (works for F32/F16/I8/...).
    from safetensors import safe_open
    try:
        with safe_open(path, framework="numpy") as st:
            return st.get_tensor(name).astype(np.float32)
    except TypeError:
        pass  # BF16 — numpy has no native dtype; fall through to manual read.

    # Manual path: parse the safetensors binary format to get raw BF16 bytes.
    # Format: [8-byte header_len (uint64 LE)] [header JSON] [tensor data]
    # data_offsets in the JSON are relative to the start of the tensor data region.
    with open(path, "rb") as f:
        header_len = struct.unpack("<Q", f.read(8))[0]
        header     = json.loads(f.read(header_len))
        meta       = header.get(name)
        if meta is None:
            return None
        shape  = tuple(meta["shape"])
        start, end = meta["data_offsets"]
        f.seek(8 + header_len + start)
        raw = f.read(end - start)

    return _bf16_bytes_to_f32(raw, shape)


# ── INT4 packing helpers ─────────────────────────────────────────────────────

def _pack(W: np.ndarray):
    """Returns (packed uint8, scale float32, orig_cols int)."""
    packed, scale = quantize_int4(W.astype(np.float32))
    return packed, scale, W.shape[1]


# ── Per-layer conversion ─────────────────────────────────────────────────────

def _convert_layer(layer_idx: int, tensor_map: Dict[str, str]) -> dict:
    """Load and INT4-quantize one Qwen2 transformer layer."""
    pfx = f"model.layers.{layer_idx}"
    arrays: dict = {}

    for short, full in (
        ("q", f"{pfx}.self_attn.q_proj.weight"),
        ("k", f"{pfx}.self_attn.k_proj.weight"),
        ("v", f"{pfx}.self_attn.v_proj.weight"),
        ("o", f"{pfx}.self_attn.o_proj.weight"),
        ("g", f"{pfx}.mlp.gate_proj.weight"),
        ("u", f"{pfx}.mlp.up_proj.weight"),
        ("d", f"{pfx}.mlp.down_proj.weight"),
    ):
        W = _load_tensor(tensor_map, full)
        if W is None:
            raise KeyError(f"Tensor not found: {full}")
        p, s, oc = _pack(W)
        arrays[f"l0_{short}_p"] = p    # will be renamed by caller
        arrays[f"l0_{short}_s"] = s
        arrays[f"l0_{short}_oc"] = np.array(oc)

    n1 = _load_tensor(tensor_map, f"{pfx}.input_layernorm.weight")
    n2 = _load_tensor(tensor_map, f"{pfx}.post_attention_layernorm.weight")
    if n1 is None or n2 is None:
        raise KeyError(f"Layernorm weights missing for layer {layer_idx}")
    arrays["l0_n1"] = n1.astype(np.float32)
    arrays["l0_n2"] = n2.astype(np.float32)

    return arrays


# ── Shard conversion ─────────────────────────────────────────────────────────

def convert_shard(
    shard_idx: int,
    tensor_map: Dict[str, str],
    total_layers: int,
    n_shards: int,
    out_dir: str,
) -> str:
    lps         = total_layers // n_shards
    layer_start = shard_idx * lps
    layer_end   = (shard_idx + 1) * lps if shard_idx < n_shards - 1 else total_layers
    is_first    = shard_idx == 0
    is_last     = shard_idx == n_shards - 1

    arrays: dict = {}

    # Embedding table (shard 0 only)
    if is_first:
        print(f"  [shard {shard_idx}] loading embed_tokens...", flush=True)
        embed = _load_tensor(tensor_map, "model.embed_tokens.weight")
        if embed is None:
            raise KeyError("model.embed_tokens.weight not found")
        p, s, oc = _pack(embed)
        arrays["embed_p"]    = p
        arrays["embed_s"]    = s
        arrays["embed_ocols"] = np.array(oc)

    # Transformer layers
    for abs_idx in range(layer_start, layer_end):
        rel_idx = abs_idx - layer_start
        print(f"  [shard {shard_idx}] layer {abs_idx} (rel {rel_idx})...", flush=True)
        layer_arrays = _convert_layer(abs_idx, tensor_map)
        # Re-key from "l0_" to "l{rel}_"
        for key, val in layer_arrays.items():
            new_key = key.replace("l0_", f"l{rel_idx}_")
            arrays[new_key] = val

    # LM head + final norm (last shard only)
    if is_last:
        print(f"  [shard {shard_idx}] loading lm_head...", flush=True)
        lm = _load_tensor(tensor_map, "lm_head.weight")
        if lm is None:
            # Qwen2 ties lm_head to embed_tokens when not present separately
            lm = _load_tensor(tensor_map, "model.embed_tokens.weight")
        p, s, oc = _pack(lm)
        arrays["lm_p"]    = p
        arrays["lm_s"]    = s
        arrays["lm_ocols"] = np.array(oc)

        norm = _load_tensor(tensor_map, "model.norm.weight")
        if norm is None:
            raise KeyError("model.norm.weight not found")
        arrays["final_norm"] = norm.astype(np.float32)

    # Save
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"shard_{shard_idx}.npz")
    np.savez_compressed(out_path, **arrays)

    size_mb = os.path.getsize(out_path) / 1e6
    print(f"  -> {out_path} ({size_mb:.1f} MB)", flush=True)
    return out_path


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert HF checkpoint to INT4 shards")
    parser.add_argument("--hf-dir",   required=True, help="Local HF model directory")
    parser.add_argument("--out-dir",  required=True, help="Output directory for .npz shards")
    parser.add_argument("--n-shards", type=int, default=QWEN25_CODER_3B["n_shards"],
                        help="Number of shards (default: 4)")
    parser.add_argument("--shard",    type=int, default=None,
                        help="Convert only this shard index (omit = all)")
    args = parser.parse_args()

    try:
        from safetensors import safe_open   # noqa: F401
    except ImportError:
        print("ERROR: 'safetensors' package is required. Run: pip install safetensors")
        sys.exit(1)

    t0  = time.perf_counter()
    cfg = QWEN25_CODER_3B
    print(f"Loading tensor map from {args.hf_dir!r}...")
    tensor_map = _build_tensor_map(args.hf_dir)
    print(f"  {len(tensor_map)} tensors indexed.")

    shards = [args.shard] if args.shard is not None else list(range(args.n_shards))

    for s in shards:
        print(f"\nConverting shard {s}/{args.n_shards - 1}...")
        convert_shard(
            shard_idx    = s,
            tensor_map   = tensor_map,
            total_layers = cfg["total_layers"],
            n_shards     = args.n_shards,
            out_dir      = args.out_dir,
        )

    elapsed = time.perf_counter() - t0
    print(f"\nDone. {len(shards)} shard(s) converted in {elapsed:.1f}s")
    print(f"Output: {args.out_dir}")
    print(
        "\nNext step: point ShardEngine at this directory:\n"
        f"  engine = ShardEngine(config, weights_path={args.out_dir!r})"
    )


if __name__ == "__main__":
    main()

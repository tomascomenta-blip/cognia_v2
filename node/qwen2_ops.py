"""
node/qwen2_ops.py
=================
Qwen2 numpy operators for shard-local inference without PyTorch.

INT4Weights      — nibble-packed weights with dequantize-on-demand matmul.
RealTransformerLayer — full Qwen2 decoder layer (RMSNorm, RoPE, GQA, SwiGLU).
"""

from __future__ import annotations

import ctypes
import functools
import platform
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from shattering.quantization import quantize_int4, dequantize_int4
from shattering.model_constants import SWA_WINDOW

# Tier-1: Numba JIT (Python <=3.12 only)
try:
    import numba as nb
    _NUMBA = True
except ImportError:
    _NUMBA = False

# Tier-2: C kernels via ctypes (.dll/.so) or cffi module — any Python version.
# Auto-built on first import when neither artifact exists.

def _load_fast_kernels():
    """Returns (lib, ffi_or_None, has_fusion) where lib exposes int4_linear / rms_norm / silu_fwd
    and has_fusion=True when rms_norm_linear / silu_mul are also available (Phase 21.4)."""
    node_dir = Path(__file__).parent

    def _bind_basic(lib):
        _p_u8  = ctypes.POINTER(ctypes.c_uint8)
        _p_f32 = ctypes.POINTER(ctypes.c_float)
        _i, _f = ctypes.c_int, ctypes.c_float
        lib.int4_linear.argtypes = [_p_u8, _p_f32, _i, _i, _i, _p_f32, _i, _p_f32]
        lib.int4_linear.restype  = None
        lib.rms_norm.argtypes    = [_p_f32, _p_f32, _i, _i, _f, _p_f32]
        lib.rms_norm.restype     = None
        lib.silu_fwd.argtypes    = [_p_f32, _i, _i, _p_f32]
        lib.silu_fwd.restype     = None

    def _bind_fusion(lib) -> bool:
        """Bind 21.4 fused kernels. Returns True if present in the DLL."""
        _p_u8  = ctypes.POINTER(ctypes.c_uint8)
        _p_f32 = ctypes.POINTER(ctypes.c_float)
        _i, _f = ctypes.c_int, ctypes.c_float
        try:
            lib.rms_norm_linear  # AttributeError if missing from DLL
            lib.rms_norm_linear.argtypes = [
                _p_f32, _p_f32, _p_u8, _p_f32,
                _i, _i, _i, _i, _i, _f, _p_f32,
            ]
            lib.rms_norm_linear.restype = None
            lib.silu_mul.argtypes = [_p_f32, _p_f32, _i]
            lib.silu_mul.restype  = None
            try:
                lib.int4_gate_up_silu  # present in OMP DLL only
                lib.int4_gate_up_silu.argtypes = [
                    _p_u8, _p_f32,   # gate packed + scale
                    _p_u8, _p_f32,   # up   packed + scale
                    _i, _i, _i,      # n_rows, n_packed, orig_cols
                    _p_f32, _i,      # x, n_batch
                    _p_f32,          # out (n_batch, n_rows)
                ]
                lib.int4_gate_up_silu.restype = None
            except AttributeError:
                pass  # older DLL — silu_mul fallback used
            return True
        except AttributeError:
            return False

    # Add node/ to Windows DLL search path so MSYS2 OpenMP runtime DLLs are found.
    if platform.system() == "Windows":
        try:
            import os as _os
            _os.add_dll_directory(str(node_dir))
        except (AttributeError, OSError):
            pass

    # --- ctypes path (.dll / .so) ---
    # Prefer fast_kernels_omp.dll (AVX2 + OpenMP, statically-linked gomp) when available.
    ext      = ".dll" if platform.system() == "Windows" else ".so"
    omp_path = node_dir / f"fast_kernels_omp{ext}"
    dll_path = node_dir / f"fast_kernels{ext}"
    for candidate in ([omp_path] if omp_path.exists() else []) + ([dll_path] if dll_path.exists() else []):
        try:
            lib = ctypes.CDLL(str(candidate))
            _bind_basic(lib)
            has_fusion = _bind_fusion(lib)
            if not has_fusion:
                if candidate == dll_path:
                    # Non-OMP DLL missing 21.4 functions — delete to trigger rebuild
                    try:
                        dll_path.unlink()
                    except OSError:
                        return lib, None, False
                continue  # try next candidate
            return lib, None, True
        except Exception:
            continue

    # --- cffi module path (_fast_kernels_cffi*.pyd / .so) ---
    cffi_candidates = list(node_dir.glob("_fast_kernels_cffi*.pyd")) + \
                      list(node_dir.glob("_fast_kernels_cffi*.so"))
    if cffi_candidates:
        try:
            import importlib.util, sys as _sys
            spec = importlib.util.spec_from_file_location("_fast_kernels_cffi",
                                                          str(cffi_candidates[0]))
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            has_fusion = _bind_fusion(mod.lib)
            return mod.lib, mod.ffi, has_fusion
        except Exception:
            pass

    # --- neither found: try to build ---
    try:
        from node.build_fast_kernels import build
        build()
    except Exception:
        pass

    # retry after build
    if dll_path.exists():
        return _load_fast_kernels()   # one recursive retry
    cffi_candidates = list(node_dir.glob("_fast_kernels_cffi*.pyd")) + \
                      list(node_dir.glob("_fast_kernels_cffi*.so"))
    if cffi_candidates:
        return _load_fast_kernels()

    return None, None, False


_CLIB, _CFFI, _CLIB_FUSED = (None, None, False) if _NUMBA else _load_fast_kernels()


def _ptr_u8(a: np.ndarray) -> ctypes.POINTER:
    return a.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))

def _ptr_f32(a: np.ndarray) -> ctypes.POINTER:
    return a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def _cffi_ptr(ffi, a: np.ndarray, ctype: str):
    """Cast a contiguous float32/uint8 numpy array to a cffi pointer."""
    return ffi.cast(ctype, ffi.from_buffer(a))

if _NUMBA:
    @nb.njit(parallel=True, fastmath=True, cache=True)
    def _int4_linear_jit(packed, scale, orig_cols, x):
        """INT4 matmul kernel: result[b,r] = sum_k x[b,k] * W[r,k], nibbles unpacked inline."""
        n_rows  = packed.shape[0]
        n_batch = x.shape[0]
        half    = orig_cols // 2
        odd     = orig_cols & 1
        result  = np.zeros((n_batch, n_rows), dtype=np.float32)
        for r in nb.prange(n_rows):
            s = scale[r, 0]
            for i in range(half):
                byte = np.int32(packed[r, i])
                hi   = np.float32((byte >> 4) - 8) * s
                lo   = np.float32((byte & 0x0F) - 8) * s
                for b in range(n_batch):
                    result[b, r] += x[b, 2 * i] * hi + x[b, 2 * i + 1] * lo
            if odd:
                byte = np.int32(packed[r, half])
                hi   = np.float32((byte >> 4) - 8) * s
                for b in range(n_batch):
                    result[b, r] += x[b, orig_cols - 1] * hi
        return result

    @nb.njit(fastmath=True, cache=True)
    def _rms_norm_jit(x, weight, eps):
        out   = np.empty_like(x)
        d     = x.shape[1]
        inv_d = np.float32(1.0) / np.float32(d)
        for i in range(x.shape[0]):
            ss = np.float32(0.0)
            for j in range(d):
                ss += x[i, j] * x[i, j]
            rms = np.sqrt(ss * inv_d + np.float32(eps))
            for j in range(d):
                out[i, j] = x[i, j] / rms * weight[j]
        return out

    @nb.njit(fastmath=True, cache=True)
    def _silu_jit(x):
        out = np.empty_like(x)
        for i in range(x.shape[0]):
            for j in range(x.shape[1]):
                v   = x[i, j]
                v_c = min(max(v, np.float32(-30.0)), np.float32(30.0))
                out[i, j] = v * (np.float32(1.0) / (np.float32(1.0) + np.exp(-v_c)))
        return out


# ── INT4 weight storage ──────────────────────────────────────────────────────

@dataclass
class INT4Weights:
    packed:    np.ndarray            # (out_features, ceil(in_features/2)) uint8
    scale:     np.ndarray            # (out_features, 1) float32
    orig_cols: int                   # in_features before nibble padding
    _fp16_cache: "np.ndarray | None" = field(default=None, repr=False)  # cached float16 dequant for large matrices

    @classmethod
    def from_float32(cls, W: np.ndarray) -> "INT4Weights":
        packed, scale = quantize_int4(W.astype(np.float32))
        return cls(packed=packed, scale=scale, orig_cols=W.shape[1])

    def dequantize(self) -> np.ndarray:
        return dequantize_int4(self.packed, self.scale, self.orig_cols)

    def linear(self, x: np.ndarray, chunk: int = 4096) -> np.ndarray:
        """x @ W^T — Numba JIT → ctypes C → fp32 cache (if RAM allows) → chunked numpy."""
        x32 = np.ascontiguousarray(x.astype(np.float32))
        n_rows  = self.packed.shape[0]
        n_batch = x32.shape[0]

        # Tier 1: Numba JIT (Python ≤3.12 only)
        if _NUMBA:
            return _int4_linear_jit(
                np.ascontiguousarray(self.packed),
                np.ascontiguousarray(self.scale),
                self.orig_cols,
                x32,
            )

        # Tier 2: C kernel — handles any size without extra allocation.
        # Previously lm_head (n_rows=151936) bypassed this for an fp32 cache that
        # requires 1.16 GB; on RAM-limited machines that caused OOM every token.
        if _CLIB is not None:
            packed = np.ascontiguousarray(self.packed)
            scale  = np.ascontiguousarray(self.scale.ravel())
            out    = np.empty((n_batch, n_rows), dtype=np.float32)
            if _CFFI is not None:
                _CLIB.int4_linear(
                    _cffi_ptr(_CFFI, packed, "uint8_t *"),
                    _cffi_ptr(_CFFI, scale,  "float *"),
                    n_rows, packed.shape[1], self.orig_cols,
                    _cffi_ptr(_CFFI, x32, "float *"), n_batch,
                    _cffi_ptr(_CFFI, out, "float *"),
                )
            else:
                _CLIB.int4_linear(
                    _ptr_u8(packed), _ptr_f32(scale),
                    ctypes.c_int(n_rows), ctypes.c_int(packed.shape[1]),
                    ctypes.c_int(self.orig_cols),
                    _ptr_f32(x32), ctypes.c_int(n_batch),
                    _ptr_f32(out),
                )
            return out

        # Tier 3 (no C kernel): fp32 cache for large vocab to avoid per-token dequant.
        # Only attempted when C kernel is absent; skipped permanently after OOM.
        if n_rows > 50000 and not getattr(self, '_cache_oom', False):
            if self._fp16_cache is None:
                try:
                    blocks: list = []
                    for s in range(0, n_rows, chunk):
                        e = min(s + chunk, n_rows)
                        blocks.append(dequantize_int4(self.packed[s:e], self.scale[s:e], self.orig_cols))
                    self._fp16_cache = np.vstack(blocks)
                    del blocks
                except MemoryError:
                    self._cache_oom = True  # don't attempt again this session
            if self._fp16_cache is not None:
                return x32 @ self._fp16_cache.T

        # Tier 4: chunked numpy fallback (any size, RAM-safe).
        result = np.empty((n_batch, n_rows), dtype=np.float32)
        step = min(chunk * 4, n_rows)
        try:
            for start in range(0, n_rows, step):
                end  = min(start + step, n_rows)
                w_fp = dequantize_int4(self.packed[start:end], self.scale[start:end], self.orig_cols)
                result[:, start:end] = x32 @ w_fp.T
        except MemoryError:
            for start in range(0, n_rows, chunk):
                end  = min(start + step, n_rows)
                w_fp = dequantize_int4(self.packed[start:end], self.scale[start:end], self.orig_cols)
                result[:, start:end] = x32 @ w_fp.T
        return result


# ── Qwen2 math primitives ────────────────────────────────────────────────────

def _rms_norm(x: np.ndarray, weight: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    x32 = np.ascontiguousarray(x.astype(np.float32))
    if _NUMBA and x32.ndim == 2:
        return _rms_norm_jit(x32, weight.astype(np.float32), eps)
    if _CLIB is not None and x32.ndim == 2:
        w32    = np.ascontiguousarray(weight.astype(np.float32))
        n_b, d = x32.shape
        out    = np.empty_like(x32)
        if _CFFI is not None:
            _CLIB.rms_norm(
                _cffi_ptr(_CFFI, x32, "float *"),
                _cffi_ptr(_CFFI, w32, "float *"),
                n_b, d, eps,
                _cffi_ptr(_CFFI, out, "float *"),
            )
        else:
            _CLIB.rms_norm(
                _ptr_f32(x32), _ptr_f32(w32),
                ctypes.c_int(n_b), ctypes.c_int(d),
                ctypes.c_float(eps),
                _ptr_f32(out),
            )
        return out
    rms = np.sqrt((x32 * x32).mean(-1, keepdims=True) + eps)
    return (x32 / rms) * weight


def _silu(x: np.ndarray) -> np.ndarray:
    x32 = np.ascontiguousarray(x.astype(np.float32))
    if _NUMBA and x32.ndim == 2:
        return _silu_jit(x32)
    if _CLIB is not None and x32.ndim == 2:
        n_b, d = x32.shape
        out    = np.empty_like(x32)
        if _CFFI is not None:
            _CLIB.silu_fwd(
                _cffi_ptr(_CFFI, x32, "float *"),
                n_b, d,
                _cffi_ptr(_CFFI, out, "float *"),
            )
        else:
            _CLIB.silu_fwd(
                _ptr_f32(x32),
                ctypes.c_int(n_b), ctypes.c_int(d),
                _ptr_f32(out),
            )
        return out
    return x32 * (1.0 / (1.0 + np.exp(-x32.clip(-30, 30))))


def _rotate_half(x: np.ndarray) -> np.ndarray:
    h = x.shape[-1] // 2
    return np.concatenate([-x[..., h:], x[..., :h]], axis=-1)


@functools.lru_cache(maxsize=512)
def _precompute_rope(
    seq_len: int, head_dim: int, rope_theta: float, offset: int = 0
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns (cos, sin) each of shape (seq_len, head_dim) float32.
    offset: starting position index (for KV-cache decode steps).
    Cached: 36 layers share the same computation for equal (seq, offset).
    """
    half  = head_dim // 2
    freq  = 1.0 / (rope_theta ** (np.arange(0, half, dtype=np.float32) / half))
    t     = np.outer(np.arange(offset, offset + seq_len, dtype=np.float32), freq)
    cos   = np.concatenate([np.cos(t), np.cos(t)], axis=-1).astype(np.float32)
    sin   = np.concatenate([np.sin(t), np.sin(t)], axis=-1).astype(np.float32)
    return cos, sin


def _apply_rope(
    x: np.ndarray, cos: np.ndarray, sin: np.ndarray
) -> np.ndarray:
    """x: (seq, n_heads, head_dim); cos/sin: (seq, head_dim)."""
    return x * cos[:, None, :] + _rotate_half(x) * sin[:, None, :]


# ── Phase 21.4 — layer fusion helpers ───────────────────────────────────────

def _get_int4_base(w) -> "Optional[INT4Weights]":
    """Return INT4Weights base only when the weight hasn't been promoted to a
    higher-precision cache by DynamicWeights. Returns None otherwise so callers
    fall back to the normal (unfused) linear path."""
    if isinstance(w, INT4Weights):
        return w
    base = getattr(w, "_base", None)
    if isinstance(base, INT4Weights):
        if getattr(w, "_fp32_cache", None) is None and \
           getattr(w, "_fp16_cache", None) is None:
            return base
    return None


def _rms_norm_linear(
    x: np.ndarray,
    norm_w: np.ndarray,
    w4: "INT4Weights",
    eps: float,
) -> np.ndarray:
    """Fused RMSNorm + INT4 linear via C kernel.

    Computes inv_rms once per batch row then applies the norm inline during
    the INT4 matmul, avoiding an intermediate (seq, hidden) normed tensor
    write to RAM. Falls back to numpy when _CLIB_FUSED is False.
    """
    if not _CLIB_FUSED:
        normed = _rms_norm(x, norm_w, eps)
        return w4.linear(normed)

    x32    = np.ascontiguousarray(x.astype(np.float32))
    nw32   = np.ascontiguousarray(norm_w.astype(np.float32))
    packed = np.ascontiguousarray(w4.packed)
    scale  = np.ascontiguousarray(w4.scale.ravel())
    n_batch, d_in = x32.shape
    n_rows        = w4.packed.shape[0]
    n_packed      = w4.packed.shape[1]
    out    = np.empty((n_batch, n_rows), dtype=np.float32)
    if _CFFI is not None:
        _CLIB.rms_norm_linear(
            _cffi_ptr(_CFFI, x32,    "float *"),
            _cffi_ptr(_CFFI, nw32,   "float *"),
            _cffi_ptr(_CFFI, packed, "uint8_t *"),
            _cffi_ptr(_CFFI, scale,  "float *"),
            n_batch, d_in, n_rows, n_packed, w4.orig_cols,
            eps,
            _cffi_ptr(_CFFI, out, "float *"),
        )
    else:
        _CLIB.rms_norm_linear(
            _ptr_f32(x32), _ptr_f32(nw32),
            _ptr_u8(packed), _ptr_f32(scale),
            ctypes.c_int(n_batch), ctypes.c_int(d_in),
            ctypes.c_int(n_rows),  ctypes.c_int(n_packed),
            ctypes.c_int(w4.orig_cols),
            ctypes.c_float(eps),
            _ptr_f32(out),
        )
    return out


def _silu_mul(gate: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Fused SiLU(gate) * up in-place via C kernel.

    Returns gate array modified in-place to hold silu(gate)*up, avoiding the
    temporary array that _silu(gate) * up would create.
    Falls back to numpy when _CLIB_FUSED is False.
    """
    gate32 = np.ascontiguousarray(gate.astype(np.float32))
    up32   = np.ascontiguousarray(up.astype(np.float32))
    if not _CLIB_FUSED:
        return gate32 * (1.0 / (1.0 + np.exp(-gate32.clip(-30, 30)))) * up32

    if _CFFI is not None:
        _CLIB.silu_mul(
            _cffi_ptr(_CFFI, gate32, "float *"),
            _cffi_ptr(_CFFI, up32,   "float *"),
            gate32.size,
        )
    else:
        _CLIB.silu_mul(
            _ptr_f32(gate32), _ptr_f32(up32),
            ctypes.c_int(gate32.size),
        )
    return gate32


def _gate_up_silu(w_gate: "INT4Weights", w_up: "INT4Weights",
                  x: np.ndarray) -> np.ndarray:
    """Fused gate+up INT4 projections with SiLU gate, single OMP region.

    Replaces two separate w_gate.linear(x) + w_up.linear(x) + _silu_mul calls.
    Falls back to the three-call path when int4_gate_up_silu is unavailable or
    when either weight has been promoted to FP32 by DynamicWeights.
    """
    if (not _CLIB_FUSED
            or not hasattr(_CLIB, "int4_gate_up_silu")
            or not isinstance(w_gate, INT4Weights)
            or not isinstance(w_up,   INT4Weights)):
        return _silu_mul(w_gate.linear(x), w_up.linear(x))

    x32     = np.ascontiguousarray(x.astype(np.float32))
    n_batch = x32.shape[0] if x32.ndim == 2 else 1
    if x32.ndim == 1:
        x32 = x32.reshape(1, -1)
    n_rows  = w_gate.packed.shape[0]
    gp      = np.ascontiguousarray(w_gate.packed)
    gs      = np.ascontiguousarray(w_gate.scale.ravel())
    up      = np.ascontiguousarray(w_up.packed)
    us      = np.ascontiguousarray(w_up.scale.ravel())
    out     = np.empty((n_batch, n_rows), dtype=np.float32)
    _CLIB.int4_gate_up_silu(
        _ptr_u8(gp),  _ptr_f32(gs),
        _ptr_u8(up),  _ptr_f32(us),
        ctypes.c_int(n_rows),
        ctypes.c_int(gp.shape[1]),
        ctypes.c_int(w_gate.orig_cols),
        _ptr_f32(x32), ctypes.c_int(n_batch),
        _ptr_f32(out),
    )
    return out


# ── Sliding-window attention (shared by _attention and _attention_normed) ─────

# Query-block size for the memory-bounded prefill path. A prefill longer than this
# is tiled along the query axis so the transient scores matrix stays O(QCHUNK * W)
# instead of O(seq * total). Chosen == SWA_WINDOW so each block scores <= 2W-1 keys.
_SWA_QCHUNK = SWA_WINDOW


def _swa_banded_block(Qb: np.ndarray, K: np.ndarray, V: np.ndarray,
                      qa0: int, qa1: int,
                      H: int, KH: int, D: int) -> np.ndarray:
    """GQA scaled dot-product attention for ONE query block against full K/V.

    Qb : (sb, H, D) queries for absolute positions [qa0, qa1) (RoPE already applied).
    K,V: (total, KH, D) full cached+new tensors (RoPE applied to K).
    Returns (sb, H*D) float32.

    Each query at absolute position p attends to the sliding window (p-W, p]. Only the
    keys some query in this block can reach are sliced in ([max(0, qa0-W+1), qa1)); a
    per-query banded causal mask enforces each individual window. This subsumes the
    decode step (sb == 1: the slice is already exactly the last <=W keys, no mask).
    """
    group = H // KH
    sb = qa1 - qa0
    klo = max(0, qa0 - SWA_WINDOW + 1)
    K_attn, V_attn = K[klo:qa1], V[klo:qa1]
    attn_total = K_attn.shape[0]

    # GQA-native: Q (sb, H, D) -> (sb, KH, group, D); K/V stay (attn_total, KH, D).
    Q_gqa = Qb.reshape(sb, KH, group, D)
    # scores: (KH, sb, group, attn_total). k is the shared KH axis (not summed).
    scores = np.einsum("kqgd,tkd->kqgt", Q_gqa.transpose(1, 0, 2, 3),
                       K_attn) / np.sqrt(D)
    if sb > 1:
        q_abs = np.arange(qa0, qa1, dtype=np.int32).reshape(-1, 1)
        k_abs = np.arange(klo, qa1, dtype=np.int32).reshape(1, -1)
        # Mask a key in the FUTURE (k_abs > q_abs) or older than the sliding window
        # (k_abs <= q_abs - SWA_WINDOW). Every query keeps its own slot (never fully
        # masked). sb == 1 needs no mask: the slice above is exactly its window.
        masked = (k_abs > q_abs) | (k_abs <= q_abs - SWA_WINDOW)
        scores = scores + masked.astype(np.float32)[None, :, None, :] * -1e9
    scores -= scores.max(-1, keepdims=True)
    probs = np.exp(scores); probs /= probs.sum(-1, keepdims=True)
    # out: (KH, sb, group, D) -> (sb, H, D) -> (sb, H*D)
    return np.einsum("kqgt,ktd->kqgd", probs,
                     V_attn.transpose(1, 0, 2)).transpose(1, 0, 2, 3).reshape(sb, H * D)


def _swa_sdpa(Q: np.ndarray, K: np.ndarray, V: np.ndarray,
              seq: int, past_len: int,
              H: int, KH: int, D: int) -> np.ndarray:
    """Sliding-window attention over full K/V; returns (seq, H*D) float32 (pre w_o).

    - Decode (seq == 1) and short prefills go through a single banded block (the
      block slice already bounds a decode step to the last <=W keys).
    - A long prefill (seq > _SWA_QCHUNK) is tiled along the query axis so the
      transient scores matrix is bounded to O(_SWA_QCHUNK * W) instead of O(seq*total).
      This is numerically identical: every query row attends to exactly its own window
      regardless of tiling (masked keys contribute exp(-1e9)==0.0, an exact no-op).
    """
    if seq > _SWA_QCHUNK:
        out = np.empty((seq, H * D), dtype=np.float32)
        for q0 in range(0, seq, _SWA_QCHUNK):
            q1 = min(q0 + _SWA_QCHUNK, seq)
            out[q0:q1] = _swa_banded_block(
                Q[q0:q1], K, V, past_len + q0, past_len + q1, H, KH, D)
        return out
    return _swa_banded_block(Q, K, V, past_len, past_len + seq, H, KH, D)


# ── Qwen2 decoder layer ──────────────────────────────────────────────────────

class RealTransformerLayer:
    """
    Single Qwen2 transformer decoder layer in pure numpy.

    All projection weights are stored as INT4Weights (nibble-packed).
    Norm weights stay float32 (negligible size).
    """

    def __init__(
        self,
        n_heads: int,
        n_kv_heads: int,
        head_dim: int,
        rope_theta: float,
        rms_norm_eps: float,
        w_q: INT4Weights,
        w_k: INT4Weights,
        w_v: INT4Weights,
        w_o: INT4Weights,
        w_gate: INT4Weights,
        w_up: INT4Weights,
        w_down: INT4Weights,
        norm1: np.ndarray,
        norm2: np.ndarray,
    ):
        self.n_heads    = n_heads
        self.n_kv_heads = n_kv_heads
        self.head_dim   = head_dim
        self.rope_theta = rope_theta
        self.rms_eps    = rms_norm_eps
        self.w_q = w_q;  self.w_k = w_k;  self.w_v = w_v;  self.w_o = w_o
        self.w_gate = w_gate;  self.w_up = w_up;  self.w_down = w_down
        self.norm1 = norm1.astype(np.float32)
        self.norm2 = norm2.astype(np.float32)
        # {session_id: (K_past, V_past)} — kept to 1 entry (last session only)
        self._kv_cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    def forward(self, x: np.ndarray, session_id: str = "") -> np.ndarray:
        """x: (seq, hidden_dim) float32 → (seq, hidden_dim) float32."""
        x = x.astype(np.float32)
        if _CLIB_FUSED:
            x = x + self._attention_normed(x, session_id)
            x = x + self._mlp_normed(x)
        else:
            x = x + self._attention(_rms_norm(x, self.norm1, self.rms_eps), session_id)
            x = x + self._mlp(_rms_norm(x, self.norm2, self.rms_eps))
        return x

    def _attention(self, x: np.ndarray, session_id: str = "") -> np.ndarray:
        seq   = x.shape[0]
        H, KH, D = self.n_heads, self.n_kv_heads, self.head_dim

        # Determine past length for RoPE offset
        past_len = 0
        K_past: Optional[np.ndarray] = None
        V_past: Optional[np.ndarray] = None
        if session_id:
            cached = self._kv_cache.get(session_id)
            if cached is not None:
                K_past, V_past = cached
                past_len = K_past.shape[0]

        Q    = self.w_q.linear(x).reshape(seq, H, D)
        k_raw = self.w_k.linear(x)
        if getattr(self, "_lora_k", None) is not None:
            k_raw = k_raw + self._lora_k.delta(x)
        K_new = k_raw.reshape(seq, KH, D)
        v_raw = self.w_v.linear(x)
        if getattr(self, "_lora_v", None) is not None:
            v_raw = v_raw + self._lora_v.delta(x)
        V_new = v_raw.reshape(seq, KH, D)

        cos, sin = _precompute_rope(seq, D, self.rope_theta, offset=past_len)
        Q     = _apply_rope(Q,     cos, sin)
        K_new = _apply_rope(K_new, cos, sin)

        # Extend with cached K/V from previous tokens
        if K_past is not None:
            K = np.concatenate([K_past, K_new], axis=0)  # (past+seq, KH, D)
            V = np.concatenate([V_past, V_new], axis=0)
        else:
            K, V = K_new, V_new

        # Store updated cache (single-session: replace all other entries)
        if session_id:
            self._kv_cache[session_id] = (K, V)

        # Sliding-window attention (decode-truncate / multi-token banded / chunked
        # prefill), shared with _attention_normed. Full K/V stays in _kv_cache for
        # LPC cross-turn persistence; _swa_sdpa only bounds what each query attends to.
        out = _swa_sdpa(Q, K, V, seq, past_len, H, KH, D)
        return self.w_o.linear(out)

    # ── 21.4 fused paths ─────────────────────────────────────────────────────

    def _attention_normed(self, x: np.ndarray, session_id: str = "") -> np.ndarray:
        """Attention with fused RMSNorm+Q/K/V projections (avoids intermediate normed tensor).

        Uses _rms_norm_linear when Q/K/V weights are still in INT4 (not yet promoted
        to FP32 by DynamicWeights warmup). Falls back per-weight to the standard path.
        """
        seq = x.shape[0]
        H, KH, D = self.n_heads, self.n_kv_heads, self.head_dim

        past_len = 0
        K_past: Optional[np.ndarray] = None
        V_past: Optional[np.ndarray] = None
        if session_id:
            cached = self._kv_cache.get(session_id)
            if cached is not None:
                K_past, V_past = cached
                past_len = K_past.shape[0]

        # Fused norm+projection when weights are still in INT4 tier
        wq_b = _get_int4_base(self.w_q)
        wk_b = _get_int4_base(self.w_k)
        wv_b = _get_int4_base(self.w_v)

        _normed = None  # computed lazily if needed for LoRA or fallback

        def _normed_x() -> np.ndarray:
            nonlocal _normed
            if _normed is None:
                _normed = _rms_norm(x, self.norm1, self.rms_eps)
            return _normed

        Q = (_rms_norm_linear(x, self.norm1, wq_b, self.rms_eps)
             if wq_b is not None else self.w_q.linear(_normed_x())).reshape(seq, H, D)

        k_raw = (_rms_norm_linear(x, self.norm1, wk_b, self.rms_eps)
                 if wk_b is not None else self.w_k.linear(_normed_x()))
        if getattr(self, "_lora_k", None) is not None:
            k_raw = k_raw + self._lora_k.delta(_normed_x())

        v_raw = (_rms_norm_linear(x, self.norm1, wv_b, self.rms_eps)
                 if wv_b is not None else self.w_v.linear(_normed_x()))
        if getattr(self, "_lora_v", None) is not None:
            v_raw = v_raw + self._lora_v.delta(_normed_x())

        K_new = k_raw.reshape(seq, KH, D)
        V_new = v_raw.reshape(seq, KH, D)

        cos, sin = _precompute_rope(seq, D, self.rope_theta, offset=past_len)
        Q     = _apply_rope(Q,     cos, sin)
        K_new = _apply_rope(K_new, cos, sin)

        if K_past is not None:
            K = np.concatenate([K_past, K_new], axis=0)
            V = np.concatenate([V_past, V_new], axis=0)
        else:
            K, V = K_new, V_new

        if session_id:
            self._kv_cache[session_id] = (K, V)

        # Sliding-window attention shared with _attention (see _swa_sdpa): decode
        # truncation, multi-token banded masking, and memory-bounded chunked prefill.
        out = _swa_sdpa(Q, K, V, seq, past_len, H, KH, D)
        return self.w_o.linear(out)

    def _mlp_normed(self, x: np.ndarray) -> np.ndarray:
        """MLP with fused SiLU*mul gate activation (avoids temporary gate array).

        RMSNorm is applied first (unfused); the silu*up fusion saves one full
        intermediate (seq, intermediate_dim) tensor allocation and write.
        """
        normed = _rms_norm(x, self.norm2, self.rms_eps)
        gate   = self.w_gate.linear(normed)
        up     = self.w_up.linear(normed)
        return self.w_down.linear(_silu_mul(gate, up))

    def truncate_kv(self, session_id: str, max_len: int) -> None:
        """Truncate KV-cache to max_len tokens (speculative decoding rollback)."""
        if max_len < 0:
            raise ValueError(f"max_len must be non-negative, got {max_len}")
        kv = self._kv_cache.get(session_id)
        if kv is not None:
            K, V = kv
            self._kv_cache[session_id] = (K[:max_len], V[:max_len])

    def kv_len(self, session_id: str) -> int:
        """Return number of cached K/V tokens for this session."""
        kv = self._kv_cache.get(session_id)
        return kv[0].shape[0] if kv is not None else 0

    def _mlp(self, x: np.ndarray) -> np.ndarray:
        return self.w_down.linear(_silu(self.w_gate.linear(x)) * self.w_up.linear(x))

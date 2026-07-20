"""
node/shard_engine.py
====================
Shard inference engine — processes Qwen2 transformer layers for one device.

Wire protocol (12-byte header, big-endian):
  PTYPE_HIDDEN  = 0  float16 tensor  (seq, hidden_dim)  — intermediate hidden state
  PTYPE_TOKENS  = 1  int32   array   (seq,)             — input token IDs (shard 0 entry)
  PTYPE_LOGITS  = 2  float32 tensor  (1, vocab_size)    — final logits (last shard output)

Header layout: payload_type(u8) | reserved(u8) | shard_index(u16) | dim0(u32) | dim1(u32)

Shard .npz format (written by scripts/convert_hf_to_shards.py):
  l{i}_q_p, l{i}_q_s   — q_proj packed+scale
  l{i}_k_p, l{i}_k_s   — k_proj
  l{i}_v_p, l{i}_v_s   — v_proj
  l{i}_o_p, l{i}_o_s   — o_proj
  l{i}_g_p, l{i}_g_s   — gate_proj
  l{i}_u_p, l{i}_u_s   — up_proj
  l{i}_d_p, l{i}_d_s   — down_proj
  l{i}_n1, l{i}_n2      — input/post-attention layernorm weights (float32)
  embed_p, embed_s      — embedding table INT4 (shard 0 only)
  lm_p, lm_s           — lm_head INT4 (last shard only)
  final_norm            — final RMSNorm weight float32 (last shard only)
  orig_cols             — dict of {key: int} for INT4 padding recovery
"""

import logging
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

# Fuente unica de constantes del modelo (regla del repo)
from shattering.model_constants import QWEN25_CODER_3B as _QWEN

# ── Adaptive Vocabulary Pruning (AVP) ────────────────────────────────────────
# Module-level singleton; None = disabled (default).
# Call enable_vocab_pruning() after model load to activate.

_vocab_pruner = None   # type: "VocabPruner | None"


def enable_vocab_pruning(vocab_size: int = _QWEN["vocab_size"]) -> None:
    """Enable AVP for the last-shard lm_head computation.

    Reduces lm_head matmul from V=151936 to ~2000 candidates.
    Safe to call multiple times — replaces the existing instance.
    """
    global _vocab_pruner
    from node.vocab_pruner import VocabPruner
    _vocab_pruner = VocabPruner(vocab_size)


def disable_vocab_pruning() -> None:
    """Disable AVP and revert to full-vocab lm_head computation."""
    global _vocab_pruner
    _vocab_pruner = None


def get_vocab_pruner():
    """Return the active VocabPruner instance, or None."""
    return _vocab_pruner


logger = logging.getLogger(__name__)

# ── Wire protocol ────────────────────────────────────────────────────────────

PTYPE_HIDDEN      = 0
PTYPE_TOKENS      = 1
PTYPE_LOGITS      = 2
PTYPE_TEXT        = 3   # raw UTF-8 prompt; shard 0 tokenizes internally
PTYPE_CLEAR_CACHE = 4   # control: clear KV-cache for a session_id

_WIRE_FMT  = ">BBHII"                     # type, reserved, shard_idx, dim0, dim1
_WIRE_SIZE = struct.calcsize(_WIRE_FMT)   # 12 bytes


def encode_hidden(shard_index: int, tensor: np.ndarray) -> bytes:
    """tensor: (seq, hidden_dim) float16."""
    d0, d1 = tensor.shape
    hdr = struct.pack(_WIRE_FMT, PTYPE_HIDDEN, 0, shard_index, d0, d1)
    return hdr + tensor.astype(np.float16).tobytes()


def encode_tokens(shard_index: int, token_ids: np.ndarray) -> bytes:
    """token_ids: (seq,) int32."""
    seq = token_ids.shape[0]
    hdr = struct.pack(_WIRE_FMT, PTYPE_TOKENS, 0, shard_index, seq, 0)
    return hdr + token_ids.astype(np.int32).tobytes()


def encode_logits(shard_index: int, logits: np.ndarray) -> bytes:
    """logits: (1, vocab_size) float32."""
    d0, d1 = logits.shape
    hdr = struct.pack(_WIRE_FMT, PTYPE_LOGITS, 0, shard_index, d0, d1)
    return hdr + logits.astype(np.float32).tobytes()


def encode_text(shard_index: int, prompt: str) -> bytes:
    """Encode a raw UTF-8 prompt for PTYPE_TEXT (shard 0 entry)."""
    body = prompt.encode("utf-8")
    hdr = struct.pack(_WIRE_FMT, PTYPE_TEXT, 0, shard_index, len(body), 0)
    return hdr + body


def encode_clear_cache(shard_index: int, session_id: str) -> bytes:
    """Encode a PTYPE_CLEAR_CACHE control frame for session eviction."""
    body = session_id.encode("utf-8")
    hdr = struct.pack(_WIRE_FMT, PTYPE_CLEAR_CACHE, 0, shard_index, len(body), 0)
    return hdr + body


def decode_wire(data: bytes) -> Tuple[int, int, object]:
    """
    Deserialize wire bytes.
    Returns (ptype, shard_index, payload).
    payload is np.ndarray for PTYPE_HIDDEN/TOKENS/LOGITS, str for PTYPE_TEXT.
    """
    ptype, _reserved, shard_idx, dim0, dim1 = struct.unpack(
        _WIRE_FMT, data[:_WIRE_SIZE]
    )
    body = data[_WIRE_SIZE:]
    if ptype == PTYPE_TOKENS:
        payload = np.frombuffer(body, dtype=np.int32).copy()
    elif ptype == PTYPE_LOGITS:
        payload = np.frombuffer(body, dtype=np.float32).reshape(dim0, dim1).copy()
    elif ptype in (PTYPE_TEXT, PTYPE_CLEAR_CACHE):
        payload = body[:dim0].decode("utf-8", errors="replace")
    else:  # PTYPE_HIDDEN
        payload = np.frombuffer(body, dtype=np.float16).reshape(dim0, dim1).copy()
    return ptype, shard_idx, payload


# Legacy aliases — used by existing relay and inference_pipeline code.
HEADER_FORMAT = ">HHII"
HEADER_SIZE   = struct.calcsize(HEADER_FORMAT)


def encode_hidden_state(shard_index: int, n_layers: int,
                         tensor: np.ndarray) -> bytes:
    seq_len, hidden_dim = tensor.shape
    hdr = struct.pack(HEADER_FORMAT, shard_index, n_layers, hidden_dim, seq_len)
    return hdr + tensor.astype(np.float16).tobytes()


def decode_hidden_state(data: bytes) -> tuple:
    shard_index, n_layers, hidden_dim, seq_len = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )
    tensor = np.frombuffer(
        data[HEADER_SIZE:], dtype=np.float16
    ).reshape(seq_len, hidden_dim).copy()
    return shard_index, n_layers, tensor


# ── Simulated transformer layer (calibrated) ────────────────────────────────

def _calibrate_cpu_ms_per_layer(hidden_dim: int, intermediate_dim: int,
                                  int4_speedup: float = 4.0) -> float:
    H, I = hidden_dim, intermediate_dim
    x  = np.ones((1, H), dtype=np.float32)
    Wq = np.ones((H, 3 * H), dtype=np.float32) * 0.01
    Wo = np.ones((H, H),     dtype=np.float32) * 0.01
    Wg = np.ones((H, I),     dtype=np.float32) * 0.01
    Wu = np.ones((H, I),     dtype=np.float32) * 0.01
    Wd = np.ones((I, H),     dtype=np.float32) * 0.01
    for _ in range(2):
        _ = x @ Wq; _ = x @ Wo; _ = x @ Wg; _ = x @ Wu
        _ = np.ones((1, I), dtype=np.float32) @ Wd
    t0 = time.perf_counter()
    for _ in range(5):
        _ = x @ Wq; _ = x @ Wo
        gate = x @ Wg; up = x @ Wu; _ = (gate * up) @ Wd
    fp32_ms = (time.perf_counter() - t0) * 200  # /5*1000
    return fp32_ms / int4_speedup


_CALIBRATION_CACHE: dict = {}


class SimulatedTransformerLayer:
    """
    Calibrated simulation: measures real CPU speed once, then sleeps that long.
    Passes the hidden tensor unchanged — values don't matter for pipeline timing.
    """

    def __init__(self, hidden_dim: int, intermediate_dim: int, seed: int = 0):
        self.H, self.I = hidden_dim, intermediate_dim
        key = (hidden_dim, intermediate_dim)
        if key not in _CALIBRATION_CACHE:
            _CALIBRATION_CACHE[key] = _calibrate_cpu_ms_per_layer(hidden_dim, intermediate_dim)
        self._ms = _CALIBRATION_CACHE[key]

    def forward(self, x: np.ndarray) -> np.ndarray:
        time.sleep(self._ms / 1000)
        return x


# ── ShardConfig ──────────────────────────────────────────────────────────────

@dataclass
class ShardConfig:
    model_name:       str
    shard_index:      int
    n_shards:         int
    total_layers:     int
    hidden_dim:       int
    intermediate_dim: int
    # Qwen2 attention geometry
    n_heads:          int   = 16
    n_kv_heads:       int   = 2   # Qwen2.5-Coder-3B: verified from k_proj output dim 256
    head_dim:         int   = 128
    rope_theta:       float = 1_000_000.0
    rms_norm_eps:     float = 1e-6
    vocab_size:       int   = _QWEN["vocab_size"]
    eos_token_id:     int   = _QWEN["eos_token_id"]
    precision:        str   = "int4"   # "fp32" | "int4"
    # Legacy NPQ field kept for backward compat with MoE code
    _legacy_precision: str = field(default="fp32", repr=False)

    @property
    def layer_start(self) -> int:
        return self.shard_index * (self.total_layers // self.n_shards)

    @property
    def layer_end(self) -> int:
        lps = self.total_layers // self.n_shards
        end = (self.shard_index + 1) * lps
        if self.shard_index == self.n_shards - 1:
            end = self.total_layers
        return end

    @property
    def n_layers(self) -> int:
        return self.layer_end - self.layer_start

    @property
    def is_first(self) -> bool:
        return self.shard_index == 0

    @property
    def is_last(self) -> bool:
        return self.shard_index == self.n_shards - 1


# ── _NpyDir ──────────────────────────────────────────────────────────────────

class _NpyDir:
    """
    Dict-like wrapper for a directory of per-array .npy files.
    Each access mmap's the file with mode='r' so weight pages are OS-managed
    and evicted under memory pressure without touching Python heap.
    """
    __slots__ = ("_dir", "_cache")

    def __init__(self, directory: str) -> None:
        self._dir   = directory
        self._cache: dict = {}

    def __contains__(self, key: str) -> bool:
        return os.path.exists(os.path.join(self._dir, f"{key}.npy"))

    def __getitem__(self, key: str) -> np.ndarray:
        if key not in self._cache:
            path = os.path.join(self._dir, f"{key}.npy")
            self._cache[key] = np.load(path, mmap_mode='r')
        return self._cache[key]

    def keys(self):
        return (f[:-4] for f in os.listdir(self._dir) if f.endswith(".npy"))

    def close(self) -> None:
        self._cache.clear()


# ── ShardEngine ──────────────────────────────────────────────────────────────

class ShardEngine:
    """
    Inference engine for one shard of a sharded Qwen2 model.

    SIMULATION mode (no weights on disk): calibrated latency, pass-through values.
    REAL mode (shard_N.npz present): INT4 dequantize-on-demand Qwen2 forward pass.
    """

    def __init__(self, config: ShardConfig, weights_path: Optional[str] = None):
        self.config              = config
        self._layers             = []
        self._load_time_ms       = 0.0
        self._kv_cache           = None   # injected by patch_shard_engine_mla()
        self._embed_table: Optional[np.ndarray] = None   # fp32 (if RAM allows) or None
        self._embed_w4   = None   # INT4 packed fallback when fp32 table won't fit in RAM
        self._lm_weights         = None   # INT4Weights or DynamicWeights for last-shard LM head
        self._final_norm:  Optional[np.ndarray] = None
        self._lora_adapter       = None   # ELC adapter; set via set_adapter()
        self._precision_manager  = None   # PrecisionManager; set in _load_real_weights
        self._weights_path       = weights_path  # kept for lazy tokenizer on PTYPE_TEXT
        self._tokenizer          = None   # lazy-loaded when PTYPE_TEXT arrives at shard 0
        self._npz_data           = None   # NpzFile kept alive so mmap views stay valid

        shard_npz = (
            os.path.join(weights_path, f"shard_{config.shard_index}.npz")
            if weights_path else None
        )
        self.mode = "real" if (shard_npz and os.path.exists(shard_npz)) else "simulation"
        self._load(shard_npz)

    # ── Loading ──────────────────────────────────────────────────────────────

    def _load(self, shard_path: Optional[str]) -> None:
        t0  = time.perf_counter()
        cfg = self.config
        if self.mode == "real":
            self._load_real_weights(shard_path)
        else:
            logger.debug("shard %d: simulation (layers %d-%d)",
                         cfg.shard_index, cfg.layer_start, cfg.layer_end - 1)
            for i in range(cfg.n_layers):
                self._layers.append(SimulatedTransformerLayer(
                    cfg.hidden_dim, cfg.intermediate_dim, seed=cfg.layer_start + i
                ))
        self._load_time_ms = (time.perf_counter() - t0) * 1000
        logger.debug("shard %d ready: %d layers %.0fms mode=%s",
                     cfg.shard_index, cfg.n_layers, self._load_time_ms, self.mode)

    def _load_real_weights(self, shard_path: str) -> None:
        from node.qwen2_ops import INT4Weights, RealTransformerLayer
        from shattering.dynamic_precision import PrecisionManager
        cfg  = self.config

        # Prefer unpacked directory (shard_N/) created by scripts/unpack_shards.py.
        # Individual .npy files can be mmap'd zero-copy: only the pages being computed
        # stay in RAM and the OS evicts the rest. Fallback to compressed .npz with
        # mmap_mode='c' (numpy decompresses to a temp file — still evictable by OS).
        unpacked_dir = shard_path.replace(".npz", "")
        if os.path.isdir(unpacked_dir):
            data = _NpyDir(unpacked_dir)
        else:
            data = np.load(shard_path, allow_pickle=False, mmap_mode='c')
        self._npz_data = data

        pm = PrecisionManager()
        self._precision_manager = pm

        # Embedding table (shard 0): try fp32 for fast lookup; fall back to INT4 on OOM.
        # The table is (vocab=151936, hidden=2048) fp32 = 1.16 GB — may not fit in RAM.
        # INT4 fallback dequantizes only the needed rows per token (trivial cost).
        if cfg.is_first and "embed_p" in data:
            ocols = int(data["embed_ocols"]) if "embed_ocols" in data else data["embed_p"].shape[1] * 2
            from shattering.quantization import dequantize_int4
            from node.qwen2_ops import INT4Weights
            try:
                self._embed_table = dequantize_int4(data["embed_p"], data["embed_s"], ocols)
            except MemoryError:
                # Keep INT4 packed as mmap views; rows dequantized on demand in process()
                self._embed_w4 = INT4Weights(data["embed_p"], data["embed_s"], ocols)

        # LM head + final norm (last shard) — wrapped for dynamic precision
        if cfg.is_last and "lm_p" in data:
            ocols            = int(data["lm_ocols"])
            lm_w4            = INT4Weights(data["lm_p"], data["lm_s"], ocols)
            self._lm_weights = pm.register("lm_head", lm_w4)
            self._final_norm = data["final_norm"].astype(np.float32)

        gl = cfg.layer_start  # global layer offset for unique key naming

        for i in range(cfg.n_layers):
            p = f"l{i}_"

            def w(name: str, layer_i: int = i) -> "DynamicWeights":
                key_p  = f"{p}{name}_p"
                key_s  = f"{p}{name}_s"
                key_c  = f"{p}{name}_oc"
                orig   = int(data[key_c]) if key_c in data else data[key_p].shape[1] * 2
                w4     = INT4Weights(data[key_p], data[key_s], orig)
                pm_key = f"l{gl + layer_i}_{name}"
                return pm.register(pm_key, w4)

            layer = RealTransformerLayer(
                n_heads=cfg.n_heads, n_kv_heads=cfg.n_kv_heads,
                head_dim=cfg.head_dim, rope_theta=cfg.rope_theta,
                rms_norm_eps=cfg.rms_norm_eps,
                w_q=w("q"), w_k=w("k"), w_v=w("v"), w_o=w("o"),
                w_gate=w("g"), w_up=w("u"), w_down=w("d"),
                norm1=data[f"{p}n1"], norm2=data[f"{p}n2"],
            )
            self._layers.append(layer)

    # ── Inference ────────────────────────────────────────────────────────────

    def process(
        self,
        hidden_state: Optional[np.ndarray],
        token_ids: Optional[np.ndarray] = None,
        session_id: str = "",
    ) -> Tuple[np.ndarray, float]:
        """
        Forward pass through this shard's layers.

        hidden_state : (seq, hidden_dim) float16/32 from previous shard.
        token_ids    : (seq,) int32, only used when is_first=True in real mode.

        Returns (output, latency_ms) where output is:
          float16 (seq, hidden_dim) for non-last shards
          float32 (1, vocab_size)   logits for the last shard in real mode
        """
        t0  = time.perf_counter()
        cfg = self.config

        if self.mode == "simulation":
            x = hidden_state.astype(np.float32) if hidden_state is not None \
                else np.zeros((1, cfg.hidden_dim), dtype=np.float32)
            for layer in self._layers:
                x = layer.forward(x)
            result = x.astype(np.float16)

        else:
            # Real mode — embed tokens or accept hidden state
            if cfg.is_first and token_ids is not None:
                # Prefill: start of a new generation turn — reset AVP focus set
                if _vocab_pruner is not None and token_ids.shape[0] > 1:
                    _vocab_pruner.reset_turn()
                tids = token_ids.astype(np.int32)
                if self._embed_table is not None:
                    x = self._embed_table[tids]                        # fp32 lookup (fast)
                elif self._embed_w4 is not None:
                    from shattering.quantization import dequantize_int4
                    x = dequantize_int4(
                        self._embed_w4.packed[tids],
                        self._embed_w4.scale[tids],
                        self._embed_w4.orig_cols,
                    )                                                   # INT4 row lookup
                else:
                    x = hidden_state.astype(np.float32)
            else:
                x = hidden_state.astype(np.float32)

            for layer in self._layers:
                x = layer.forward(x, session_id)

            if cfg.is_last and self._lm_weights is not None:
                from node.qwen2_ops import _rms_norm
                x = _rms_norm(x, self._final_norm, cfg.rms_norm_eps)
                # AVP: use pruned lm_head for decode steps (seq==1 only).
                # Prefill (seq>1) always uses full vocab — focus set not warm yet.
                pruner = _vocab_pruner
                if pruner is not None and x.shape[0] == 1:
                    hidden_last = x[-1:]   # (1, D)
                    pruned_logits, focus_idx = pruner.prune_lm_head(
                        self._lm_weights, hidden_last
                    )
                    # Reconstruct full-size logits array (needed for encode_logits)
                    full = np.full((1, cfg.vocab_size), -1e9, dtype=np.float32)
                    full[0, focus_idx] = pruned_logits[0]
                    result = full
                else:
                    result = self._lm_weights.linear(x)   # (seq, vocab_size) float32
            else:
                result = x.astype(np.float16)

        return result, (time.perf_counter() - t0) * 1000

    def forward(
        self,
        hidden_state: Optional[np.ndarray],
        session_id: str = "",
        token_ids: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, float]:
        """Convenience wrapper for process() that accepts session_id."""
        return self.process(hidden_state, token_ids=token_ids, session_id=session_id)

    def process_bytes(self, data: bytes, session_id: str = "") -> Tuple[bytes, float]:
        """
        Wire protocol entry point.
        Accepts both new (PTYPE_*) and legacy header formats.
        Returns (response_bytes, latency_ms).
        """
        # Detect protocol version: new header has payload_type in byte 0 as 0-4
        # Legacy header starts with shard_index uint16 big-endian (never 0-4 for valid shards)
        ptype = data[0]
        if ptype in (PTYPE_HIDDEN, PTYPE_TOKENS, PTYPE_LOGITS, PTYPE_TEXT, PTYPE_CLEAR_CACHE):
            ptype, _shard_from, payload = decode_wire(data)
            if ptype == PTYPE_CLEAR_CACHE:
                # Control frame: evict KV-cache for the given session_id
                self.clear_cache(str(payload))
                # Return an empty PTYPE_HIDDEN ack so relay can forward to next shard
                ack = struct.pack(_WIRE_FMT, PTYPE_CLEAR_CACHE, 0, self.config.shard_index, 0, 0)
                return ack, 0.0
            if ptype == PTYPE_TEXT:
                token_ids = self._tokenize_text(payload)
                result, ms = self.process(None, token_ids=token_ids, session_id=session_id)
            elif ptype == PTYPE_TOKENS:
                result, ms = self.process(None, token_ids=payload, session_id=session_id)
            else:
                result, ms = self.process(payload, session_id=session_id)
            if self.config.is_last and result.dtype == np.float32:
                return encode_logits(self.config.shard_index, result), ms
            return encode_hidden(self.config.shard_index, result), ms
        else:
            # Legacy protocol
            _shard_from, n_layers, tensor = decode_hidden_state(data)
            result, ms = self.process(tensor)
            return encode_hidden_state(self.config.shard_index, self.config.n_layers, result), ms

    def _tokenize_text(self, text: str) -> np.ndarray:
        """Lazy-load tokenizer and tokenize a raw text prompt."""
        if self._tokenizer is None:
            self._tokenizer = self._load_tokenizer()
        if self._tokenizer is not None:
            try:
                enc = self._tokenizer.encode(text)
                ids = enc.ids if hasattr(enc, "ids") else list(enc)
                return np.array(ids, dtype=np.int32)
            except Exception as exc:
                logger.warning("Tokenizer encode failed: %s; using byte fallback", exc)
        # Byte-level fallback: valid vocab range, stable across runs
        return np.frombuffer(text.encode("utf-8"), dtype=np.uint8).astype(np.int32)

    def _load_tokenizer(self):
        """Try to load the BPE tokenizer from the weights directory."""
        if not self._weights_path:
            return None
        try:
            from tokenizers import Tokenizer
            tok_path = os.path.join(self._weights_path, "tokenizer.json")
            if os.path.exists(tok_path):
                logger.info("shard %d: loaded tokenizer from %s", self.config.shard_index, tok_path)
                return Tokenizer.from_file(tok_path)
        except Exception as exc:
            logger.debug("Tokenizer load failed: %s", exc)
        return None

    def set_adapter(self, adapter) -> None:
        """
        Applies a LoRAAdapter to all real layers (no-op in simulation mode).
        Each RealTransformerLayer stores _lora_k / _lora_v as plain attributes
        checked via getattr() inside _attention() — no class modification needed.
        """
        self._lora_adapter = adapter
        if self.mode != "real":
            return
        from node.qwen2_ops import RealTransformerLayer
        for layer in self._layers:
            if isinstance(layer, RealTransformerLayer):
                layer._lora_k = adapter.lora_k
                layer._lora_v = adapter.lora_v

    def clear_adapter(self) -> None:
        """Removes LoRA delta from all layers."""
        self._lora_adapter = None
        from node.qwen2_ops import RealTransformerLayer
        for layer in self._layers:
            if isinstance(layer, RealTransformerLayer):
                layer._lora_k = None
                layer._lora_v = None

    def truncate_kv(self, session_id: str, max_len: int) -> None:
        """Truncate KV-cache for speculative decoding rollback."""
        for layer in self._layers:
            if hasattr(layer, "truncate_kv"):
                layer.truncate_kv(session_id, max_len)

    def kv_len(self, session_id: str) -> int:
        """Return current KV-cache length (tokens) for this session."""
        for layer in self._layers:
            if hasattr(layer, "kv_len"):
                return layer.kv_len(session_id)
        return 0

    def clear_cache(self, session_id: str) -> None:
        # Clear MLA compressed KV-cache if patched
        if self._kv_cache is not None:
            self._kv_cache.clear(session_id)
        # Clear native RealTransformerLayer per-session KV-cache
        from node.qwen2_ops import RealTransformerLayer
        for layer in self._layers:
            if isinstance(layer, RealTransformerLayer):
                layer._kv_cache.pop(session_id, None)

    def decay_precision(self, factor: float = 0.3) -> dict:
        """
        Decay all weight access counters and drop caches for matrices that fall
        below their tier threshold. Call during the sleep cycle or under memory
        pressure. No-op in simulation mode.
        Returns PrecisionManager.stats() or {} if no manager exists.
        """
        if self._precision_manager is None:
            return {}
        self._precision_manager.decay_all(factor)
        return self._precision_manager.stats()

    def precision_stats(self) -> dict:
        """Current per-tier weight counts. Empty dict in simulation mode."""
        if self._precision_manager is None:
            return {}
        return self._precision_manager.stats()

    def info(self) -> dict:
        cfg = self.config
        result = {
            "shard":        cfg.shard_index,
            "layers":       f"{cfg.layer_start}-{cfg.layer_end - 1}",
            "n_layers":     cfg.n_layers,
            "hidden_dim":   cfg.hidden_dim,
            "mode":         self.mode,
            "load_time_ms": round(self._load_time_ms, 1),
            "is_first":     cfg.is_first,
            "is_last":      cfg.is_last,
        }
        if self._precision_manager is not None:
            result["precision"] = self._precision_manager.stats()
        return result

"""
LocalRunner: corre los 4 shards de Qwen2.5-Coder-3B en secuencia en una sola maquina.
Descarga shards desde HF dataset si no estan en DATA_DIR.
"""
import os, time, json, struct
import numpy as np
from pathlib import Path
from huggingface_hub import hf_hub_download

from cognia_inference.model_constants import (
    QWEN25_CODER_3B,
)

N_LAYERS          = QWEN25_CODER_3B["total_layers"]       # 36
N_HEADS           = QWEN25_CODER_3B["n_heads"]            # 16
N_KV_HEADS        = QWEN25_CODER_3B["n_kv_heads"]         # 2
HIDDEN_DIM        = QWEN25_CODER_3B["hidden_dim"]         # 2048
INTERMEDIATE_DIM  = QWEN25_CODER_3B["intermediate_dim"]   # 11008
VOCAB_SIZE        = QWEN25_CODER_3B["vocab_size"]         # 151936
EOS_IDS           = {QWEN25_CODER_3B["eos_token_id"],
                     QWEN25_CODER_3B["bos_token_id"]}     # {151645, 151643}

DATA_DIR     = Path(os.environ.get("DATA_DIR", "/data"))
HF_DATASET   = "Acua124298042/cognia-shards"
N_SHARDS     = QWEN25_CODER_3B["n_shards"]                # 4
LAYERS_PER_SHARD = QWEN25_CODER_3B["layers_per_shard"]    # 9

_loaded = False
_shards = []       # list of 4 dicts with layer weights (freed after cache build)
_embed_weight = None
_lm_head      = None
_final_norm   = None
_tokenizer_vocab = None   # id -> str (fallback only)
_tokenizer_obj   = None   # tokenizers.Tokenizer for proper BPE decode
# Pre-dequantized weight cache in float16 to avoid per-token dequantization overhead
# Keys: (shard_idx, layer_i, name) -> float16 ndarray
_W: dict = {}


def _download_shard(idx: int, hf_token: str) -> Path:
    fname = f"shard_{idx}.npz"
    dest  = DATA_DIR / fname
    if dest.exists():
        return dest
    print(f"[local_runner] Downloading {fname} from HF dataset...")
    hf_hub_download(
        repo_id=HF_DATASET, filename=fname,
        local_dir=str(DATA_DIR), token=hf_token or None, repo_type="dataset"
    )
    print(f"[local_runner] {fname} downloaded ({dest.stat().st_size // 1_000_000} MB)")
    return dest


def _load_tokenizer(hf_token: str):
    global _tokenizer_vocab, _tokenizer_obj
    tok_path = DATA_DIR / "tokenizer.json"
    module_tok = Path(__file__).parent / "tokenizer.json"
    if not tok_path.exists() and module_tok.exists():
        tok_path = module_tok
    if not tok_path.exists():
        try:
            hf_hub_download(
                repo_id=HF_DATASET,
                filename="tokenizer.json",
                local_dir=str(DATA_DIR), token=hf_token or None, repo_type="dataset"
            )
        except Exception as exc:
            print(f"[local_runner] tokenizer.json download failed: {exc}")
    if tok_path.exists():
        try:
            from tokenizers import Tokenizer
            _tokenizer_obj = Tokenizer.from_file(str(tok_path))
            print(f"[local_runner] Tokenizer (BPE) loaded from {tok_path}")
        except Exception as exc:
            print(f"[local_runner] tokenizers lib load failed: {exc}")
        with open(tok_path, encoding="utf-8") as f:
            data = json.load(f)
        vocab = data.get("model", {}).get("vocab", {})
        if not vocab:
            vocab = data.get("vocab", {})
        _tokenizer_vocab = {v: k for k, v in vocab.items()}
        print(f"[local_runner] Tokenizer vocab: {len(_tokenizer_vocab)} tokens")
    else:
        _tokenizer_vocab = {}


def startup(hf_token: str = "") -> bool:
    """Download all 4 shards and load into memory. Runs once at Space startup."""
    global _loaded, _shards, _embed_weight, _lm_head, _final_norm
    if _loaded:
        return True
    try:
        hf_token = hf_token or os.environ.get("HF_TOKEN", "")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        _load_tokenizer(hf_token)

        print("[local_runner] Loading all 4 shards into RAM...")
        _shards = []
        for i in range(N_SHARDS):
            path = _download_shard(i, hf_token)
            data = np.load(str(path), allow_pickle=False)
            _shards.append(dict(data))
            keys_sample = list(data.keys())[:4]
            print(f"[local_runner] shard_{i} loaded: {keys_sample}...")

        # Extract embed from shard 0
        s0 = _shards[0]
        for k in ("embed_tokens", "model.embed_tokens.weight", "embed_p"):
            if k in s0:
                w = s0[k].astype(np.float32)
                # embed_p is INT4-packed — dequantize if scale key present
                if k == "embed_p" and "embed_s" in s0:
                    from cognia_inference.quantization import dequantize_int4
                    ocols = int(s0["embed_ocols"]) if "embed_ocols" in s0 else s0["embed_p"].shape[1] * 2
                    _embed_weight = dequantize_int4(s0["embed_p"], s0["embed_s"], ocols)
                else:
                    _embed_weight = w
                print(f"[local_runner] embed loaded from '{k}' shape={_embed_weight.shape}")
                break

        # Extract lm_head + final_norm from last shard
        s3 = _shards[-1]
        if "lm_p" in s3 and "lm_s" in s3:
            from cognia_inference.quantization import dequantize_int4
            ocols = int(s3["lm_ocols"]) if "lm_ocols" in s3 else s3["lm_p"].shape[1] * 2
            _lm_head = dequantize_int4(s3["lm_p"], s3["lm_s"], ocols)
            print(f"[local_runner] lm_head dequantized shape={_lm_head.shape}")
        else:
            for k in s3:
                if "lm_head" in k or "output" in k:
                    _lm_head = s3[k].astype(np.float32)
                    print(f"[local_runner] lm_head loaded from '{k}' shape={_lm_head.shape}")
                    break

        if "final_norm" in s3:
            _final_norm = s3["final_norm"].astype(np.float32)
            print(f"[local_runner] final_norm loaded shape={_final_norm.shape}")

        _build_weight_cache()
        _loaded = True
        print(f"[local_runner] Ready. embed={_embed_weight is not None}, "
              f"lm_head={_lm_head is not None}, final_norm={_final_norm is not None}")
        return True
    except Exception as e:
        import traceback
        print(f"[local_runner] startup failed: {e}")
        traceback.print_exc()
        return False


def is_ready() -> bool:
    return _loaded


def _rms_norm(x: np.ndarray, weight: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    x32 = x.astype(np.float32)
    rms = np.sqrt((x32 * x32).mean(-1, keepdims=True) + eps)
    return (x32 / rms) * weight


def _silu(x: np.ndarray) -> np.ndarray:
    x32 = x.astype(np.float32)
    return x32 * (1.0 / (1.0 + np.exp(-x32.clip(-30, 30))))


_ROPE_THETA = QWEN25_CODER_3B["rope_theta"]  # 1_000_000.0

def _apply_rope(x: np.ndarray, pos_offset: int) -> np.ndarray:
    """Apply RoPE to x: (seq, heads, head_dim). pos_offset = position of x[0]."""
    seq, heads, D = x.shape
    inv_freq = 1.0 / (_ROPE_THETA ** (np.arange(0, D, 2, dtype=np.float32) / D))
    positions = np.arange(pos_offset, pos_offset + seq, dtype=np.float32)
    freqs = np.outer(positions, inv_freq)          # (seq, D//2)
    cos = np.cos(freqs)[:, None, :]                # (seq, 1, D//2)
    sin = np.sin(freqs)[:, None, :]
    x1, x2 = x[..., :D//2], x[..., D//2:]
    return np.concatenate([x1 * cos - x2 * sin, x2 * cos + x1 * sin], axis=-1)


def _dequant_int4(shard: dict, prefix: str, name: str) -> np.ndarray:
    """Dequantize an INT4 weight from shard dict using keys like l0_q_p, l0_q_s, l0_q_oc."""
    from cognia_inference.quantization import dequantize_int4
    pk  = f"{prefix}{name}_p"
    sk  = f"{prefix}{name}_s"
    ock = f"{prefix}{name}_oc"
    packed = shard[pk]
    scale  = shard[sk]
    if ock in shard:
        orig = int(shard[ock])
    else:
        orig = packed.shape[1] * 2
    return dequantize_int4(packed, scale, orig)


def _build_weight_cache() -> None:
    """Dequantize all layer weights once at startup into float16 to avoid per-token overhead."""
    global _W
    from cognia_inference.quantization import dequantize_int4
    _W = {}
    for shard_idx, shard in enumerate(_shards):
        for layer_i in range(LAYERS_PER_SHARD):
            p = f"l{layer_i}_"
            if f"{p}n1" not in shard:
                continue
            # Cache RMSNorm weights (small, needed in forward pass)
            _W[(shard_idx, layer_i, "n1")] = shard[f"{p}n1"].astype(np.float32)
            _W[(shard_idx, layer_i, "n2")] = shard[f"{p}n2"].astype(np.float32)
            for name in ("q", "k", "v", "o", "g", "u", "d"):
                pk = f"{p}{name}_p"
                sk = f"{p}{name}_s"
                ock = f"{p}{name}_oc"
                if pk not in shard:
                    continue
                oc = int(shard[ock]) if ock in shard else shard[pk].shape[1] * 2
                _W[(shard_idx, layer_i, name)] = dequantize_int4(shard[pk], shard[sk], oc)
    _shards.clear()  # free 1.2 GB packed shards — all weights now in _W
    print(f"[local_runner] Weight cache built: {len(_W)} matrices, "
          f"~{sum(v.nbytes for v in _W.values()) // 1_000_000} MB float32")


def _get_w(shard_idx: int, layer_i: int, name: str) -> np.ndarray:
    return _W[(shard_idx, layer_i, name)]


def _layer_forward(shard: dict, layer_i: int, global_layer: int, x: np.ndarray,
                   shard_idx: int = 0, pos_offset: int = 0) -> np.ndarray:
    """Run one Qwen2 transformer layer with RoPE positional encoding."""
    if (shard_idx, layer_i, "n1") not in _W:
        return x

    norm1 = _W[(shard_idx, layer_i, "n1")]
    norm2 = _W[(shard_idx, layer_i, "n2")]
    seq   = x.shape[0]
    H, KH, D = N_HEADS, N_KV_HEADS, HIDDEN_DIM // N_HEADS
    group = H // KH

    xn = _rms_norm(x, norm1)
    Q = (_get_w(shard_idx, layer_i, "q") @ xn.T).T.reshape(seq, H, D)
    K = (_get_w(shard_idx, layer_i, "k") @ xn.T).T.reshape(seq, KH, D)
    V = (_get_w(shard_idx, layer_i, "v") @ xn.T).T.reshape(seq, KH, D)

    Q = _apply_rope(Q, pos_offset)
    K = _apply_rope(K, pos_offset)

    K_exp = np.repeat(K, group, axis=1)
    V_exp = np.repeat(V, group, axis=1)
    scores = np.einsum("shd,thd->sht", Q, K_exp) / np.sqrt(D)
    if seq > 1:
        mask = np.triu(np.full((seq, seq), -1e9, dtype=np.float32), k=1)
        scores = scores + mask[:, None, :]
    scores -= scores.max(-1, keepdims=True)
    probs = np.exp(scores); probs /= probs.sum(-1, keepdims=True)

    attn_out = np.einsum("sht,thd->shd", probs, V_exp).reshape(seq, H * D)
    x = x + (_get_w(shard_idx, layer_i, "o") @ attn_out.T).T

    xn2  = _rms_norm(x, norm2)
    gate = _silu(_get_w(shard_idx, layer_i, "g") @ xn2.T)
    up   = _get_w(shard_idx, layer_i, "u") @ xn2.T
    x    = x + (_get_w(shard_idx, layer_i, "d") @ (gate * up)).T
    return x


def _simple_generate(prompt: str, max_tokens: int = 128) -> str:
    """
    Simplified generation: embed prompt tokens, run through all shard layers,
    pick top-1 token greedily.
    """
    if not _loaded or _embed_weight is None:
        return f"[Cognia local] Shards cargando... prompt: {prompt[:100]}"

    # Wrap in ChatML so Qwen2.5 generates instead of immediately predicting EOS
    chat_prompt = (
        f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    try:
        if _tokenizer_obj is not None:
            token_ids = list(_tokenizer_obj.encode(chat_prompt).ids)
        else:
            token_ids = [QWEN25_CODER_3B["bos_token_id"]]
    except Exception:
        token_ids = [QWEN25_CODER_3B["bos_token_id"]]

    # Clamp context to avoid very long prompts slowing down Space
    all_ids = token_ids[-20:]

    generated = []
    n_gen = min(max_tokens, 5)  # Space CPU: limit to 5 new tokens
    for _step in range(n_gen):
        # Full re-prefill each step so model attends to full context (no KV cache)
        ctx = np.array(all_ids + generated, dtype=np.int32)
        ctx = np.clip(ctx, 0, len(_embed_weight) - 1)
        h   = _embed_weight[ctx].astype(np.float32)
        for shard_idx in range(N_SHARDS):
            for layer_i in range(LAYERS_PER_SHARD):
                h = _layer_forward({}, layer_i, shard_idx * LAYERS_PER_SHARD + layer_i, h,
                                   shard_idx=shard_idx, pos_offset=0)
        h = h[-1:]  # last position only

        last = _rms_norm(h, _final_norm) if _final_norm is not None else h
        if _lm_head is not None:
            logits  = last @ _lm_head.T
            next_id = int(np.argmax(logits[0]))
        else:
            next_id = 0

        if next_id in EOS_IDS:
            break
        generated.append(next_id)

    # Decode using BPE tokenizer if available
    if not generated:
        return "[Cognia local] Generacion completada (sin tokens)"
    if _tokenizer_obj is not None:
        try:
            return _tokenizer_obj.decode(generated).strip()
        except Exception:
            pass
    if _tokenizer_vocab:
        raw = "".join(_tokenizer_vocab.get(i, f"[{i}]") for i in generated)
        return raw.replace("Ġ", " ").replace("Ċ", "\n").strip()
    return f"[tokens: {generated[:20]}]"


def generate(prompt: str, max_tokens: int = 10) -> dict:
    if not _loaded:
        return {"text": "[Cognia] Shards cargando, reintenta en 2 min", "tokens_per_second": 0.0, "source": "loading"}
    t0   = time.time()
    text = _simple_generate(prompt, max_tokens)
    elapsed = time.time() - t0
    tps = len(text.split()) / elapsed if elapsed > 0 and text else 0.0
    return {"text": text, "tokens_per_second": round(tps, 2), "source": "local_numpy"}

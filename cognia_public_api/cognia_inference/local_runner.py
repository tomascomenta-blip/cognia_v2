"""
LocalRunner: Qwen2.5-Coder-3B inference for HF Spaces.

Priority path 1: llama-cpp-python with official Q4_0 GGUF (Qwen/Qwen2.5-Coder-3B-Instruct-GGUF).
Priority path 2: ctransformers with Q4_0 GGUF.
Fallback path:   numpy shard-based inference (slow, may produce garbage).
"""
import os
import time
import threading
from pathlib import Path

from huggingface_hub import hf_hub_download

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
# Official Qwen GGUF repo — properly validated vocabulary, compatible with all llama-cpp versions
HF_DATASET = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"
GGUF_FILENAME = "qwen2.5-coder-3b-instruct-q4_0.gguf"
_HF_DATASET_TYPE = "model"

_llm = None
_llm_type: str = ""  # "llama_cpp" | "ctransformers" | "numpy" | ""
_loaded = False
_loading_lock = threading.Lock()

_SYSTEM_PROMPT = (
    "You are Cognia, a helpful and concise AI assistant. "
    "Respond clearly and directly in the same language as the user."
)


_GGUF_MIN_SIZE = 1_900_000_000  # Q4_0 3B model is ~2.0 GB; reject partial downloads


def _download_gguf(hf_token: str) -> Path | None:
    dest = DATA_DIR / GGUF_FILENAME
    if dest.exists():
        size = dest.stat().st_size
        if size >= _GGUF_MIN_SIZE:
            print(f"[local_runner] GGUF cached at {dest} ({size // 1_000_000} MB)")
            return dest
        # Partial download — delete and re-fetch
        print(f"[local_runner] GGUF incomplete ({size // 1_000_000} MB < {_GGUF_MIN_SIZE // 1_000_000} MB expected), re-downloading...")
        dest.unlink()

    print(f"[local_runner] Downloading {GGUF_FILENAME} from {HF_DATASET}...")
    try:
        hf_hub_download(
            repo_id=HF_DATASET,
            filename=GGUF_FILENAME,
            local_dir=str(DATA_DIR),
            token=hf_token or None,
            repo_type="model",
        )
        size = dest.stat().st_size if dest.exists() else 0
        print(f"[local_runner] GGUF downloaded: {size // 1_000_000} MB")
        return dest if size >= _GGUF_MIN_SIZE else None
    except Exception as exc:
        print(f"[local_runner] GGUF download failed: {exc}")
        return None


def startup(hf_token: str = "") -> bool:
    global _llm, _llm_type, _loaded
    with _loading_lock:
        if _loaded:
            return True
        hf_token = hf_token or os.environ.get("HF_TOKEN", "")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        gguf_path = _download_gguf(hf_token)
        if gguf_path is not None:
            # Path 1: llama-cpp-python (fastest, but needs pre-built wheel)
            try:
                from llama_cpp import Llama
                import llama_cpp
                print(f"[local_runner] Loading GGUF with llama-cpp-python {llama_cpp.__version__}...")
                _llm = Llama(
                    model_path=str(gguf_path),
                    n_ctx=2048,
                    n_threads=2,
                    n_gpu_layers=0,
                    verbose=False,
                )
                _llm_type = "llama_cpp"
                _loaded = True
                print("[local_runner] llama-cpp-python ready")
                return True
            except ImportError:
                print("[local_runner] llama-cpp-python not installed, trying ctransformers")
            except Exception as exc:
                print(f"[local_runner] llama-cpp load failed: {exc}, trying ctransformers")

            # Path 2: ctransformers (pre-built Linux wheels, no cmake needed)
            try:
                from ctransformers import AutoModelForCausalLM
                print("[local_runner] Loading GGUF with ctransformers...")
                _llm = AutoModelForCausalLM.from_pretrained(
                    str(gguf_path),
                    model_type="qwen2",
                    context_length=2048,
                    threads=2,
                    gpu_layers=0,
                    batch_size=1,
                )
                _llm_type = "ctransformers"
                _loaded = True
                print("[local_runner] ctransformers ready")
                return True
            except ImportError:
                print("[local_runner] ctransformers not installed, falling back to numpy")
            except Exception as exc:
                print(f"[local_runner] ctransformers load failed: {exc}, falling back to numpy")

        return _startup_numpy(hf_token)


def _startup_numpy(hf_token: str) -> bool:
    """Fallback: load numpy shards."""
    global _llm_type, _loaded
    import numpy as np
    from cognia_inference.model_constants import QWEN25_CODER_3B
    from cognia_inference.quantization import dequantize_int4

    N_HEADS = QWEN25_CODER_3B["n_heads"]
    N_KV_HEADS = QWEN25_CODER_3B["n_kv_heads"]
    HIDDEN_DIM = QWEN25_CODER_3B["hidden_dim"]
    LAYERS_PER_SHARD = QWEN25_CODER_3B["layers_per_shard"]
    N_SHARDS = QWEN25_CODER_3B["n_shards"]

    global _np_state
    _np_state = {}

    try:
        shards = []
        for i in range(N_SHARDS):
            fname = f"shard_{i}.npz"
            dest = DATA_DIR / fname
            if not dest.exists():
                hf_hub_download(repo_id="Acua124298042/cognia-shards", filename=fname,
                                local_dir=str(DATA_DIR), token=hf_token or None, repo_type="dataset")
            shards.append(dict(np.load(str(dest), allow_pickle=False)))
            print(f"[local_runner] numpy shard_{i} loaded")

        W = {}
        for si, shard in enumerate(shards):
            for li in range(LAYERS_PER_SHARD):
                p = f"l{li}_"
                if f"{p}n1" not in shard:
                    continue
                W[(si, li, "n1")] = shard[f"{p}n1"].astype(np.float32)
                W[(si, li, "n2")] = shard[f"{p}n2"].astype(np.float32)
                for name in ("q", "k", "v", "o", "g", "u", "d"):
                    pk, sk, ock = f"{p}{name}_p", f"{p}{name}_s", f"{p}{name}_oc"
                    if pk not in shard:
                        continue
                    oc = int(shard[ock]) if ock in shard else shard[pk].shape[1] * 2
                    W[(si, li, name)] = dequantize_int4(shard[pk], shard[sk], oc)
                for bname in ("q_b", "k_b", "v_b"):
                    bk = f"{p}{bname}"
                    if bk in shard:
                        W[(si, li, bname)] = shard[bk].astype(np.float32)

        s0 = shards[0]
        embed_w = dequantize_int4(s0["embed_p"], s0["embed_s"], int(s0["embed_ocols"]))
        s3 = shards[-1]
        lm_head = dequantize_int4(s3["lm_p"], s3["lm_s"], int(s3["lm_ocols"]))
        final_norm = s3["final_norm"].astype(np.float32)

        _np_state.update({
            "W": W, "embed_w": embed_w, "lm_head": lm_head,
            "final_norm": final_norm,
            "N_HEADS": N_HEADS, "N_KV_HEADS": N_KV_HEADS,
            "HIDDEN_DIM": HIDDEN_DIM, "LAYERS_PER_SHARD": LAYERS_PER_SHARD,
            "N_SHARDS": N_SHARDS,
        })
        shards.clear()
        _llm_type = "numpy"
        _loaded = True
        print(f"[local_runner] numpy fallback ready ({len(W)} matrices)")
        return True
    except Exception as exc:
        print(f"[local_runner] numpy startup failed: {exc}")
        return False


_np_state: dict = {}


def is_ready() -> bool:
    return _loaded


def generate(prompt: str, max_tokens: int = 256) -> dict:
    if not _loaded:
        return {"text": "[Cognia] Cargando modelo...", "tokens_per_second": 0.0, "source": "loading"}
    if _llm_type == "llama_cpp":
        return _generate_llama(prompt, max_tokens)
    if _llm_type == "ctransformers":
        return _generate_ctransformers(prompt, max_tokens)
    if _llm_type == "numpy" and _np_state:
        return _generate_numpy(prompt, min(max_tokens, 64))
    return {"text": "[Cognia] Modelo no disponible", "tokens_per_second": 0.0, "source": "no_model"}


def _generate_llama(prompt: str, max_tokens: int) -> dict:
    t0 = time.time()
    # Use raw completion with pre-formatted ChatML — avoids version-specific chat_format bugs
    chat = (
        f"<|im_start|>system\n{_SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{prompt[:1800]}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    try:
        output = _llm(
            chat,
            max_tokens=min(max_tokens, 512),
            temperature=0.7,
            stop=["<|im_end|>", "<|endoftext|>"],
            echo=False,
        )
        elapsed = time.time() - t0
        text = output["choices"][0]["text"].strip()
        n_tokens = output.get("usage", {}).get("completion_tokens", len(text.split()))
        tps = round(n_tokens / elapsed, 2) if elapsed > 0 else 0
        return {"text": text, "tokens_per_second": tps, "source": "local_llama_cpp"}
    except Exception as exc:
        print(f"[local_runner] llama generate error: {exc}")
        return {"text": f"[Error: {exc}]", "tokens_per_second": 0.0, "source": "error"}


def _generate_ctransformers(prompt: str, max_tokens: int) -> dict:
    t0 = time.time()
    try:
        chat = (
            f"<|im_start|>system\n{_SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{prompt[:1800]}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        text = _llm(
            chat,
            max_new_tokens=min(max_tokens, 512),
            temperature=0.7,
            stop=["<|im_end|>", "<|endoftext|>"],
        )
        elapsed = time.time() - t0
        text = text.strip()
        n_tokens = len(text.split())
        tps = round(n_tokens / elapsed, 2) if elapsed > 0 else 0
        return {"text": text, "tokens_per_second": tps, "source": "local_ctransformers"}
    except Exception as exc:
        print(f"[local_runner] ctransformers generate error: {exc}")
        return {"text": f"[Error: {exc}]", "tokens_per_second": 0.0, "source": "error"}


def _generate_numpy(prompt: str, max_tokens: int) -> dict:
    """Numpy shard inference — slow, CPU only, kept as deep fallback."""
    import numpy as np
    from tokenizers import Tokenizer

    st = _np_state
    W = st["W"]
    embed_w = st["embed_w"]
    lm_head = st["lm_head"]
    final_norm = st["final_norm"]
    N_HEADS = st["N_HEADS"]
    N_KV_HEADS = st["N_KV_HEADS"]
    HIDDEN_DIM = st["HIDDEN_DIM"]
    LAYERS_PER_SHARD = st["LAYERS_PER_SHARD"]
    N_SHARDS = st["N_SHARDS"]
    ROPE_THETA = 1_000_000.0
    EOS_IDS = {151643, 151645}

    def rms_norm(x, w, eps=1e-6):
        x32 = x.astype(np.float32)
        return (x32 / np.sqrt((x32 * x32).mean(-1, keepdims=True) + eps)) * w

    def silu(x):
        x32 = x.astype(np.float32)
        return x32 * (1.0 / (1.0 + np.exp(-x32.clip(-30, 30))))

    def apply_rope(x, pos_offset):
        seq, heads, D = x.shape
        inv_freq = 1.0 / (ROPE_THETA ** (np.arange(0, D, 2, dtype=np.float32) / D))
        positions = np.arange(pos_offset, pos_offset + seq, dtype=np.float32)
        freqs = np.outer(positions, inv_freq)
        cos = np.cos(freqs)[:, None, :]
        sin = np.sin(freqs)[:, None, :]
        x1, x2 = x[..., :D // 2], x[..., D // 2:]
        return np.concatenate([x1 * cos - x2 * sin, x2 * cos + x1 * sin], axis=-1)

    def layer_fwd(si, li, h, pos_offset):
        if (si, li, "n1") not in W:
            return h
        seq = h.shape[0]
        H, KH, D = N_HEADS, N_KV_HEADS, HIDDEN_DIM // N_HEADS
        group = H // KH

        xn = rms_norm(h, W[(si, li, "n1")])
        Q = (W[(si, li, "q")] @ xn.T).T.copy()
        K = (W[(si, li, "k")] @ xn.T).T.copy()
        V = (W[(si, li, "v")] @ xn.T).T.copy()
        for bias_name, mat in (("q_b", Q), ("k_b", K), ("v_b", V)):
            if (si, li, bias_name) in W:
                mat += W[(si, li, bias_name)]
        Q = apply_rope(Q.reshape(seq, H, D), pos_offset)
        K = apply_rope(K.reshape(seq, KH, D), pos_offset)
        V = V.reshape(seq, KH, D)
        K_exp = np.repeat(K, group, axis=1)
        V_exp = np.repeat(V, group, axis=1)
        scores = np.einsum("shd,thd->sht", Q, K_exp) / np.sqrt(D)
        if seq > 1:
            mask = np.triu(np.full((seq, seq), -1e9, dtype=np.float32), k=1)
            scores = scores + mask[:, None, :]
        scores -= scores.max(-1, keepdims=True)
        probs = np.exp(scores)
        probs /= probs.sum(-1, keepdims=True)
        attn = np.einsum("sht,thd->shd", probs, V_exp).reshape(seq, H * D)
        h = h + (W[(si, li, "o")] @ attn.T).T
        xn2 = rms_norm(h, W[(si, li, "n2")])
        gate = silu(W[(si, li, "g")] @ xn2.T)
        up = W[(si, li, "u")] @ xn2.T
        h = h + (W[(si, li, "d")] @ (gate * up)).T
        return h

    # Tokenize using bundled tokenizer.json
    tok_path = DATA_DIR / "tokenizer.json"
    if not tok_path.exists():
        tok_path = Path(__file__).parent / "tokenizer.json"
    try:
        tokenizer = Tokenizer.from_file(str(tok_path))
        chat = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        ids = list(tokenizer.encode(chat).ids)
        if not ids:
            ids = [151644]  # <|im_start|> token
    except Exception as exc:
        print(f"[local_runner] tokenizer error: {exc}")
        # Manual ChatML tokenization fallback is not possible without the tokenizer
        return {"text": "[tokenizer unavailable]", "tokens_per_second": 0.0, "source": "error"}

    ctx = ids[-128:]  # use up to 128 context tokens
    generated = []
    t0 = time.time()

    for step in range(max_tokens):
        all_ids = np.array(ctx + generated, dtype=np.int32)
        all_ids = np.clip(all_ids, 0, len(embed_w) - 1)
        h = embed_w[all_ids].astype(np.float32)
        pos = 0
        for si in range(N_SHARDS):
            for li in range(LAYERS_PER_SHARD):
                h = layer_fwd(si, li, h, pos)
        last = rms_norm(h[-1:], final_norm)
        logits = last @ lm_head.T
        # Apply temperature and sample (greedy for now)
        next_id = int(np.argmax(logits[0]))
        if next_id in EOS_IDS:
            break
        generated.append(next_id)

    elapsed = time.time() - t0
    try:
        tok_path2 = DATA_DIR / "tokenizer.json"
        if not tok_path2.exists():
            tok_path2 = Path(__file__).parent / "tokenizer.json"
        tokenizer2 = Tokenizer.from_file(str(tok_path2))
        text = tokenizer2.decode(generated).strip() if generated else ""
    except Exception:
        text = f"[tokens: {generated[:10]}]"

    tps = len(generated) / elapsed if elapsed > 0 else 0
    return {"text": text, "tokens_per_second": round(tps, 3), "source": "local_numpy"}

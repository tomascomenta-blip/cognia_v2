"""
shattering/model_constants.py
==============================
Single source of truth for model architecture constants.

Supported models:
  LLAMA_32_3B      — Llama 3.2-3B (legacy baseline)
  QWEN25_CODER_3B  — Qwen2.5-Coder-3B-Instruct (current default)

Import this module instead of hardcoding dimensions across files.
"""

LLAMA_32_3B: dict = {
    "total_layers":      28,
    "hidden_dim":        3072,
    "intermediate_dim":  8192,
    "n_shards":          4,
    "layers_per_shard":  7,
    "vocab_size":        32000,
    "size_per_shard_gb": 0.40,
    "params_b":          3.2,
}

# NPQ: shard index -> quantization precision
# Shards 0,3 are critical (embedding/LM-head vicinity) -> INT8
# Shards 1,2 are factual (middle representations) -> ternary 1.58-bit
SHARD_PRECISION: dict = {0: "int8", 1: "ternary", 2: "ternary", 3: "int8"}

# RST: recursive shard-chain passes and context injection scale
DEFAULT_RST_PASSES: int   = 1    # K=1 disables RST (backward compat); K=2 for quality mode
RST_ALPHA_INIT:     float = 0.1  # context vector injection scale, initialized small

# Micro-MoE: 16-expert design replacing the 3-expert baseline
MICRO_MOE_NUM_EXPERTS:       int  = 16
MICRO_MOE_TOP_K:             int  = 2
MICRO_MOE_INTERMEDIATE_DIM:  int  = 4096

# Domain expert clusters: each sub-model owns a contiguous slice of the 16 experts
DOMAIN_EXPERT_CLUSTERS: dict = {
    "logos":  list(range(0,  5)),   # experts 0-4  (5 reasoning experts)
    "techne": list(range(5,  10)),  # experts 5-9  (5 code/technical experts)
    "rhetor": list(range(10, 16)),  # experts 10-15 (6 writing experts)
}

# MLA: compressed KV-cache dimensions calibrated for Qwen2.5-Coder-3B
MLA_D_C:       int = 512   # KV compression dim  (arbitrary; smaller = less VRAM)
MLA_D_C_PRIME: int = 512   # Q  compression dim
# Qwen2.5-Coder-3B-Instruct: n_heads=16, n_kv_heads=2, head_dim=128
MLA_N_HEADS_ASSUMED:    int = 16
MLA_N_KV_HEADS_ASSUMED: int = 2
MLA_HEAD_DIM_ASSUMED:   int = 128


# ── Qwen2.5-Coder-3B-Instruct ───────────────────────────────────────────
# Source: Qwen/Qwen2.5-Coder-3B-Instruct config.json
# Verified/overridden at conversion time by scripts/convert_hf_to_shards.py

QWEN25_CODER_3B: dict = {
    "total_layers":      36,
    "hidden_dim":        2048,
    "intermediate_dim":  11008,  # actual from gate_proj shape (11008, 2048); config.json was wrong
    "n_heads":           16,
    "n_kv_heads":        2,        # GQA: group size 8 (verified from k_proj shape=256)
    "head_dim":          128,      # hidden_dim // n_heads
    "rope_theta":        1_000_000.0,
    "rms_norm_eps":      1e-6,
    "vocab_size":        151936,
    "n_shards":          4,        # configurable via --n-shards
    "layers_per_shard":  9,        # 36 // 4
    "size_per_shard_gb": 0.30,     # INT4 on disk
    "params_b":          3.1,
    "eos_token_id":      151645,   # <|im_end|>
    "bos_token_id":      151643,   # <|endoftext|>
    "pad_token_id":      151643,
    "hf_repo":           "Qwen/Qwen2.5-Coder-3B-Instruct",
}

# All Qwen shard positions use INT4 (uniform; lm_head keeps float32)
QWEN_SHARD_PRECISION: dict = {0: "int4", 1: "int4", 2: "int4", 3: "int4"}

# Dynamic quantization: access-count thresholds for in-RAM precision promotion.
# A weight matrix that accumulates accesses >= threshold is cached at that precision,
# avoiding repeated INT4 nibble-decode on every forward pass.
# After DYN_QUANT_IDLE_DECAY_S of inactivity the counter resets automatically.
DYN_QUANT_THRESH_INT8:  int   = 5    # sporadic  → INT8 cache  (1 byte/param)
DYN_QUANT_THRESH_FP16:  int   = 15   # moderate  → FP16 cache  (2 bytes/param)
DYN_QUANT_THRESH_FP32:  int   = 30   # high-freq → FP32 cache  (4 bytes/param, fastest matmul)
DYN_QUANT_IDLE_DECAY_S: float = 300.0  # 5 min idle → auto-reset counter + drop cache

# Router: semantic embedding routing (Phase 20.1)
ROUTER_SEMANTIC_THRESHOLD: float = 0.6   # cosine sim below this -> fall back to keyword
ROUTER_SEMANTIC_BLEND:     float = 0.30  # weight for semantic vs keyword (0=keyword, 1=semantic)
ROUTER_EMBEDDING_DIM:      int   = 384   # matches all-MiniLM-L6-v2 / cognia_embedding fallback

# LPC: Latent Persistence Cache (Phase 20.2)
LPC_MAX_SESSIONS: int   = 32    # max concurrent user sessions
LPC_TTL_SECONDS:  float = 300.0 # evict idle sessions after 5 min

# SWA: Sliding Window Attention (Phase 21.2 early impl)
# Attention is O(SWA_WINDOW) instead of O(total_seq) when context exceeds this length.
# Past KV-cache beyond the window is preserved for LPC cross-turn but not attended to.
SWA_WINDOW: int = 512

# Qwen chat template (ChatML format)
QWEN_SYSTEM_PROMPT = "<|im_start|>system\n{system}<|im_end|>\n"
QWEN_USER_PROMPT   = "<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"

# HuggingFace dataset that hosts the pre-converted INT4 .npz shards.
# Upload once with: huggingface-cli upload Acua124298042/cognia-shards
# Nodes download only their assigned shard (~300MB) from this URL.
HF_SHARDS_DATASET = "Acua124298042/cognia-shards"
HF_SHARDS_BASE_URL = (
    "https://huggingface.co/datasets/Acua124298042/cognia-shards"
    "/resolve/main"
)

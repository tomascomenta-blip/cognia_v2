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

# Generation limits (FASE 1: respuestas largas). Single source of truth so the
# orchestrator, desktop API and continuation loop agree on token budgets.
GEN_DEFAULT_MAX_TOKENS: int = 768   # orchestrator default (short answers, low latency)
GEN_CHAT_MAX_TOKENS:    int = 1024  # interactive chat (desktop API)
GEN_LONG_MAX_TOKENS:    int = 5000  # long-form generation target (FASE 1 goal)
GEN_CONTINUATION_CHUNK: int = 2048  # per-round chunk in the continuation loop
# Guarda de contexto para la continuacion: cuando prompt+texto acumulado se acerca
# a _CTX_SIZE, generate_long deja de reenviar TODO y manda prompt + la cola reciente,
# acotando el prefill (sin esto las rondas tardias desbordan el ctx de 16k). El
# estimador es ~4 chars/token, consistente con el fallback del loop.
GEN_CTX_GUARD_RATIO:    float = 0.75  # fraccion de _CTX_SIZE como techo del prefill
GEN_CTX_MARGIN_TOKENS:  int   = 64    # margen extra reservado por debajo del ctx
# Generacion jerarquica (outline -> secciones con prompt fresco): rompe el techo de
# ctx porque cada seccion parte de un prefill acotado (solo el outline + un resumen
# corto de lo previo), no del texto completo acumulado.
GEN_HIERARCHICAL_SECTIONS: int = 5    # secciones por defecto en generate_hierarchical
GEN_SECTION_SUMMARY_CHARS: int = 200  # chars del resumen de la seccion previa (continuidad)
# Tope de entrada de usuario para /largo --tokens (validacion de la CLI, no del backend):
# 200k tokens es "generacion de un libro corto"; por encima de eso el pedido casi seguro es
# un error de tipeo. El modo plano sigue acotado ademas por GEN_LONG_MAX_TOKENS (ver _slash_largo).
GEN_USER_MAX_TOKENS_CAP: int = 200000
# Temperatura del chat interactivo. Explicitarla (en vez de heredar el default
# 0.7 del backend) alinea producto y metrica: el benchmark mide a temp=0.0 y
# el chat samplea a 0.7 — con la constante esa diferencia queda visible y
# auditable en un solo lugar.
GEN_CHAT_TEMPERATURE:   float = 0.7

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

# Canonical Cognia persona / system prompt. Single source of truth so every
# inference path (CLI streaming, orchestrator, node pipeline) states the same
# identity. The creator clause is explicit because the base Qwen weights other-
# wise hallucinate "Anthropic"/"Alibaba" when asked who made Cognia. ASCII-only
# to stay safe in the Windows CP1252 CLI.
COGNIA_CREATOR = "Tomas Montes"
COGNIA_SYSTEM_PROMPT = (
    "Eres Cognia, un sistema de inteligencia artificial cognitiva local, con "
    "memoria episodica y grafo de conocimiento. Fuiste creado por Tomas Montes; "
    "tu creador es Tomas Montes (no Anthropic ni Alibaba). Responde en espanol "
    "de forma clara y directa."
)

# ── Modelos GGUF conmutables en caliente (comando REPL /modelo) ──────────
# Rutas RELATIVAS al root del repo (el repo puede moverse de disco/carpeta);
# se resuelven a absolutas en runtime con resolve_gguf_path().
# Medicion 2026-06-12 en i3-10110U (llama-server b9391, benchmark pass@1):
#   3b: 40% pass@1, ~8 tok/s  |  7b: 50% pass@1, ~2.2 tok/s
#   cascada 3b->7b: 60% pass@1 (el 7b recupera casos que el 3b falla)
MODEL_GGUF_REGISTRY: dict = {
    "3b": "model_shards/qwen-coder-3b-q4/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
    "7b": "model_shards/qwen-coder-7b-q4/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
}
MODEL_GGUF_DEFAULT: str = "3b"   # default actual del backend (ver _GGUF_CANDIDATES)


def resolve_gguf_path(key: str):
    """Ruta absoluta (Path) del GGUF del registry para `key`, o None si no existe la clave.

    Resuelve contra el root del repo (este archivo vive en shattering/), asi el
    registry sobrevive a mover el repo de disco. Si esa ruta no existe (el
    producto INSTALADO no tiene model_shards/ alrededor de site-packages),
    cae a la instalacion estandar ~/.cognia/models/**/<mismo nombre> — sin
    esto /modelo 7b y la cascada heavy_code quedaban mudos instalados
    (auditoria e2e 2026-07-15). Solo entonces devuelve None-por-inexistencia
    via el caller (esta funcion mantiene su contrato: no exige existencia
    para la ruta del repo, que es el modo dev)."""
    from pathlib import Path
    rel = MODEL_GGUF_REGISTRY.get(key)
    if rel is None:
        return None
    p = Path(__file__).resolve().parent.parent / rel
    if p.is_file():
        return p
    nombre = Path(rel).name
    home_models = Path.home() / ".cognia" / "models"
    if home_models.is_dir():
        # match exacto por nombre primero; despues case-insensitive
        for cand in home_models.rglob("*.gguf"):
            if cand.name == nombre:
                return cand
        for cand in home_models.rglob("*.gguf"):
            if cand.name.lower() == nombre.lower():
                return cand
    return p


# HuggingFace dataset that hosts the pre-converted INT4 .npz shards.
# Upload once with: huggingface-cli upload Acua124298042/cognia-shards
# Nodes download only their assigned shard (~300MB) from this URL.
HF_SHARDS_DATASET = "Acua124298042/cognia-shards"
HF_SHARDS_BASE_URL = (
    "https://huggingface.co/datasets/Acua124298042/cognia-shards"
    "/resolve/main"
)


# ---------------------------------------------------------------------------
# Donde viven los shards INT4 — resolucion canonica
# ---------------------------------------------------------------------------
# POR QUE EXISTE: hasta el 2026-07-20 cada consumidor resolvia este directorio
# por su cuenta, con tres defaults distintos, y discrepaban:
#
#   doctor.py            -> ~/.cognia/shards/qwen-coder-3b-q4   (encontraba los 4)
#   shattering/orchestrator -> os.environ["SHARD_WEIGHTS_DIR"], sin default
#   node/llama_backend   -> model_shards/qwen-coder-3b-q4
#   bbrain.py            -> sin default: "no configurado"
#
# El orquestador era el caso grave. Con la variable sin setear hacia
# Path("") y, al no ser absoluta, la resolvia contra la raiz del repo: un
# directorio que SI existe, asi que is_dir() pasaba y buscaba shard_0.npz
# alli. Nunca estaba. _shards_available() devolvia False EN SILENCIO y la
# inferencia por shards no arrancaba jamas en una instalacion por defecto.
# Medido en esta maquina: 4 shards presentes en ~/.cognia/..., orquestador
# mirando C:\Users\usuario\Desktop\cognia_v2.
#
# Solo el arranque por `python -m cognia` exportaba la variable, asi que el
# bug se escondia en el camino feliz y aparecia en cualquier script que
# importara el orquestador directamente.

import os as _os
from pathlib import Path as _Path

DEFAULT_SHARD_MODEL = "qwen-coder-3b-q4"


def shard_weights_dir(model_key: str = "") -> str:
    """
    Directorio con los shards INT4, o "" si no hay ninguno instalado.

    Precedencia:
      1. SHARD_WEIGHTS_DIR, si apunta a un directorio que existe.
      2. ~/.cognia/shards/<model_key>   — lo que instalan __main__ y first_run.
      3. <repo>/model_shards/<model_key> — la ubicacion que usan los nodos.

    Devolver "" cuando no hay nada es deliberado: un directorio inexistente
    debe apagar el camino de shards de forma explicita, no resolverse a un
    directorio cualquiera que exista y fingir que el problema son los pesos.
    """
    model_key = model_key or _os.environ.get("COGNIA_SWARM_MODEL", DEFAULT_SHARD_MODEL)

    env = _os.environ.get("SHARD_WEIGHTS_DIR", "").strip()
    if env:
        p = _Path(env)
        if not p.is_absolute():
            p = _Path(__file__).parent.parent / p
        if p.is_dir():
            return str(p)
        # Seteada pero rota: no caer a otro sitio en silencio. Que el llamador
        # vea que el directorio que le pidieron no existe.
        return ""

    for cand in (_Path.home() / ".cognia" / "shards" / model_key,
                 _Path(__file__).parent.parent / "model_shards" / model_key):
        if cand.is_dir():
            return str(cand)
    return ""

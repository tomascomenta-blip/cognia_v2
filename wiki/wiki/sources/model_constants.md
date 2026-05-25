---
title: model_constants.py — fuente única de verdad de arquitectura
type: source
tags: [model, constants, architecture, qwen, moe, mla, rst]
updated: 2026-05-24
---

# model_constants.py

→ [[index]]

## Qué contiene

`shattering/model_constants.py` — **nunca hardcodear números de arquitectura en otros archivos**. Importar desde aquí.

## Modelos definidos

```python
LLAMA_32_3B      # legacy baseline (28 capas, hidden=3072)
QWEN25_CODER_3B  # modelo en producción (36 capas, hidden=2048)
```

## Constantes clave

```python
# Qwen2.5-Coder-3B (producción)
QWEN25_CODER_3B = {
    "total_layers": 36, "hidden_dim": 2048, "intermediate_dim": 8960,
    "n_heads": 16, "n_kv_heads": 2, "head_dim": 128,
    "rope_theta": 1_000_000.0, "rms_norm_eps": 1e-6,
    "vocab_size": 151936, "n_shards": 4, "layers_per_shard": 9,
    "eos_token_id": 151645, "bos_token_id": 151643,
}

# MLA
MLA_D_C = 512, MLA_D_C_PRIME = 512
MLA_N_HEADS_ASSUMED = 16, MLA_N_KV_HEADS_ASSUMED = 2, MLA_HEAD_DIM_ASSUMED = 128

# MoE
MICRO_MOE_NUM_EXPERTS = 16, MICRO_MOE_TOP_K = 2, MICRO_MOE_INTERMEDIATE_DIM = 4096

# RST
DEFAULT_RST_PASSES = 1, RST_ALPHA_INIT = 0.1

# LPC
LPC_MAX_SESSIONS: int   # máx sesiones en cache
LPC_TTL_SECONDS: float  # TTL de sesión idle
```

## Historia de bugs por hardcodear valores

- n_heads=24 (de Llama) en vez de 16 (Qwen) → DONE 2026-05-18
- n_kv_heads=8 en vez de 2 → DONE 2026-05-15

## Links

- [[concepts/sharding]]
- [[concepts/moe_routing]]
- [[entities/mla_module]]

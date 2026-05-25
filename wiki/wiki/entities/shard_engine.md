---
title: ShardEngine — motor de ejecución de un shard INT4
type: entity
tags: [shard, inference, int4, numpy, wire-protocol]
updated: 2026-05-24
---

# ShardEngine

→ [[index]]

## Qué hace

Carga un shard `.npz` INT4 nibble-packed y ejecuta el forward pass de las capas asignadas. Retorna hidden states al siguiente shard o logits si es el último.

## Archivo fuente

`node/shard_engine.py`

## Wire protocol (12-byte header, big-endian)

```
PTYPE_HIDDEN      = 0  # float16 tensor (seq, hidden_dim)
PTYPE_TOKENS      = 1  # int32 array (seq,)  — entrada a shard 0
PTYPE_LOGITS      = 2  # float32 tensor (1, vocab_size) — salida del último shard
PTYPE_TEXT        = 3  # UTF-8 prompt — shard 0 tokeniza internamente
PTYPE_CLEAR_CACHE = 4  # control frame para evictar KV-cache
```

Header layout: `payload_type(u8) | reserved(u8) | shard_index(u16) | dim0(u32) | dim1(u32)`

## Formato del .npz

```
l{i}_q_p, l{i}_q_s   — q_proj packed + scale
l{i}_k_p, l{i}_k_s   — k_proj
l{i}_v_p, l{i}_v_s   — v_proj
l{i}_o_p, l{i}_o_s   — o_proj
l{i}_g_p, l{i}_g_s   — gate_proj (SwiGLU)
l{i}_u_p, l{i}_u_s   — up_proj
l{i}_d_p, l{i}_d_s   — down_proj
embed_p, embed_s      — embedding table INT4 (shard 0 only)
lm_p, lm_s           — lm_head INT4 (último shard only)
final_norm            — RMSNorm weight float32 (último shard only)
```

## Shard 0 especial

Shard 0 tiene la embedding table. Puede recibir `PTYPE_TEXT` y tokenizar internamente.

## Links

- [[concepts/int4_nibble]]
- [[concepts/sharding]]
- [[sources/shard_engine_src]]
- [[entities/orchestrator]]
- [[synthesis/inference_pipeline]]

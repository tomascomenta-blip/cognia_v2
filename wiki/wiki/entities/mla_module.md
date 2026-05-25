---
title: MLAModule — Multi-Head Latent Attention
type: entity
tags: [mla, attention, kv-cache, rope, causal-mask]
updated: 2026-05-24
---

# MLAModule

→ [[index]]

## Qué hace

Implementa Multi-Head Latent Attention (basada en DeepSeek-V3 MLA). En vez de cachear K y V completos por capa, cachea una representación comprimida (`d_c << n_kv_heads * head_dim`). K y V se reconstruyen desde el latente vía proyecciones up.

## Archivo fuente

`shattering/mla.py`

## Parámetros clave

```python
MLA_D_C          = 512   # dimensión de compresión KV
MLA_D_C_PRIME    = 512   # dimensión de compresión Q
MLA_N_HEADS_ASSUMED    = 16   # n_heads Qwen2.5-3B
MLA_N_KV_HEADS_ASSUMED = 2    # n_kv_heads (GQA)
MLA_HEAD_DIM_ASSUMED   = 128  # hidden_dim // n_heads
```

## CompressedKVCache

```python
_cache[session_id][layer_idx] = (c_kv, position)
# c_kv: (seq_len, d_c) float32
# position: tokens cacheados
```

## Memoria por capa

```
GQA estándar: n_kv_heads(2) * T * head_dim(128) * 2 = 0.25 MB/capa * 36 = 9 MB
MLA (d_c=512): d_c * T * 2 bytes = 0.5 MB/capa * 36 = 18 MB
```

Qwen ya usa GQA agresivo (n_kv_heads=2), así que el beneficio de MLA aquí es contextos más largos con crecimiento estable del cache, no reducción de memoria.

## Integración con ShardEngine

```python
patch_shard_engine_mla(engine)  # reemplaza self_attn de cada capa
# session_id se pasa en cada forward()
# ShardEngine.clear_cache(session_id) al expirar sesión
```

## Simulation mode

Si los pesos no están cargados, las matrices defaultean a identity/zeros. El cache se puebla y limpia igual — útil para tests sin pesos reales.

## Links

- [[concepts/lpc]]
- [[concepts/rope]]
- [[entities/shard_engine]]
- [[entities/orchestrator]]

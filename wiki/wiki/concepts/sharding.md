---
title: Sharding — división del modelo
type: concept
tags: [sharding, inference, distributed, int4]
updated: 2026-05-24
---

# Sharding

→ [[index]]

## Qué es

El modelo Qwen2.5-Coder-3B-Instruct se divide en **4 shards** INT4 nibble-packed. Cada shard corre en un nodo distinto de la red P2P. Los hidden states pasan de shard en shard hasta llegar al `lm_head`.

## Arquitectura del modelo

| Param | Valor |
|---|---|
| Capas | 36 |
| Hidden | 2048 |
| n_heads | 16 |
| n_kv_heads | 2 |
| Vocab | 151936 |
| Formato | INT4 nibble-packed |
| Fuente | `shattering/model_constants.py` |

## Regla crítica

**Nunca hardcodear** valores de arquitectura. Siempre importar desde `shattering/model_constants.py`. Esta fue la causa de bugs históricos (n_heads=24 de Llama en vez de 16 de Qwen, n_kv_heads=8 en vez de 2).

## Cómo se construyen los shards

```bash
python scripts/convert_hf_to_shards.py --hf-dir /path/to/qwen --out-dir model_shards/qwen-coder-3b-q4
```

El manifest vive en `shattering/manifests/cognia_qwen.json`.

## Disponibilidad

`_shards_available()` retorna False si `SHARD_WEIGHTS_DIR` no está en `.env` o el directorio no existe. Si False, el sistema cae a Ollama.

## Links

- [[concepts/int4_nibble]]
- [[entities/shard_engine]]
- [[entities/orchestrator]]
- [[sources/model_constants]]
- [[synthesis/inference_pipeline]]

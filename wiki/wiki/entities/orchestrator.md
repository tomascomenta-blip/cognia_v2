---
title: Orchestrator — coordinador del loop de generación
type: entity
tags: [orchestrator, inference, lpc, shard-chain, sampling]
updated: 2026-07-16
---

# Orchestrator (ShatteringOrchestrator)

→ [[index]]


## Estado (2026-07-16)

El camino PRIMARIO de infer() hoy es el backend llama.cpp: _try_load_llama()
/ reload_llama() generan via [[entities/llama_backend]] ANTES del shard
chain (orchestrator.py:309+, 497+); _ollama_infer quedo como tercer fallback.
Lo de abajo describe el path shards (vigente solo sin GGUF).
## Qué hace

Coordina el router, el FragmentManager y la cadena de shards en una única llamada `infer()`. Gestiona el loop token-a-token, el KV-cache (LPC), y el sampling por sub-modelo.

## Archivo fuente

`shattering/orchestrator.py`

## Modos de operación

| Modo | Descripción |
|---|---|
| `local` | Carga fragments in-process, corre ShardEngine chain en el dispositivo |
| `distributed` | Delega al Coordinator vía HTTP |
| `auto` | Usa distributed si `COGNIA_COORDINATOR_URL` está seteada, sino local |

## LPC — LatentPersistenceCache

```python
class LatentPersistenceCache:
    # Maps external session_id → _LPCEntry(mla_session_id, token_count, last_access)
    # Solo los tokens nuevos (más allá del prefijo cacheado) van al shard chain
    # Eviction: sessions idle > LPC_TTL_SECONDS
```

- `LPC_MAX_SESSIONS` y `LPC_TTL_SECONDS` vienen de `model_constants.py`
- Phase 21.1 DONE (cross-turn). Phase 21.2 pendiente (intra-turn).

## Sampling por sub-modelo

| Sub-modelo | Temperatura |
|---|---|
| LOGOS | 0.3 |
| TECHNE | 0.15 |
| RHETOR | 0.7 |

## Restricción

`_warmup_shard_engines()` (ex `_run_shard_chain()`) solo hace warmup — no contribuye al output. El path real de generación es `_shard_infer()`.

## Links

- [[concepts/lpc]]
- [[concepts/moe_routing]]
- [[entities/shard_engine]]
- [[entities/mla_module]]
- [[synthesis/inference_pipeline]]

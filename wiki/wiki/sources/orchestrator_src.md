---
title: orchestrator.py — loop de generación y LPC
type: source
tags: [orchestrator, inference, lpc, sampling, distributed]
updated: 2026-07-16
---

# orchestrator.py

→ [[index]]


## Estado (2026-07-16)

Responsabilidad 0 que falta abajo: intentar el backend llama.cpp
(_try_load_llama/reload_llama, generacion via LlamaBackend,
orchestrator.py:309+,497+) y solo caer al shard chain sin GGUF.
## Archivo

`shattering/orchestrator.py`

## Responsabilidades

1. Recibe `infer(prompt, lpc_session_id=...)` 
2. Decide modo: local / distributed / auto
3. Tokeniza con BPE real (`tokenizer.json`) — nunca hash()
4. Aplica ChatML template
5. Loop token-a-token: shard chain → sampling → EOS check
6. Gestiona LatentPersistenceCache (LPC)

## LatentPersistenceCache

```python
class LatentPersistenceCache:
    # get_or_create(lpc_session_id) → _LPCEntry
    # update(lpc_session_id, new_token_count)
    # invalidate(lpc_session_id) — si prompt no extiende prefix
    # evict_stale(mla_evict_fn) — llamado periódicamente
```

## Warmup vs inferencia real

- `_warmup_shard_engines()` — solo warmup; NO contribuye al output
- `_shard_infer()` — path real de generación

## Modo distributed

Requiere `COGNIA_COORDINATOR_URL` en env. Sin esta var, cae a local silenciosamente.

## Links

- [[entities/orchestrator]]
- [[concepts/lpc]]
- [[synthesis/inference_pipeline]]

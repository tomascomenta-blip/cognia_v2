---
title: Flujo completo de inferencia
type: synthesis
tags: [inference, shards, relay, orchestrator, lm_head]
updated: 2026-05-24
---

# Flujo completo de inferencia (token a token)

→ [[index]]

## Pipeline de alto nivel

```
Usuario
  └─ HTTP/WS → cognia_desktop_api (:8765)  o  app/main.py (:8000)
       └─ coordinator/relay.py  (WebSocket, valida session_id + shard_index bounds)
            └─ shattering/orchestrator.py  (_shard_infer)
                 ├─ tokenizer  (BPE real desde tokenizer.json — NO hash())
                 ├─ ChatML template → input_ids
                 ├─ loop token a token:
                 │    ├─ node/shard_engine.py  ×4 shards  (INT4 → dequantize → forward)
                 │    ├─ shattering/mla.py  (causal mask + RoPE)
                 │    ├─ node/qwen2_ops.py  (RMSNorm, SiLU, lm_head chunked)
                 │    ├─ sampling (temp LOGOS=0.3 / TECHNE=0.15 / RHETOR=0.7)
                 │    └─ EOS check {151643, 151645}
                 └─ stream token → relay → cliente
```

## Decisión: shards vs Ollama

`memory_response_engine.py` (Stage 0) evalúa **coverage score**:
- Alto → articula desde memoria episódica (Ollama)
- Bajo + `_shards_available()` True → genera con shards propios
- Bajo + shards no disponibles → Ollama fallback

`_shards_available()` requiere `SHARD_WEIGHTS_DIR` seteado en `.env`.

## KV-Cache (LPC)

- `lpc_session_id` en `infer()` — skip-prefix cross-turn
- Intra-turn (Phase 21.2) pendiente
- Ver [[concepts/lpc]]

## Cuello de botella actual

`lm_head` chunked: ~37 matmuls/token. Speculative decoding compensa.
Numba JIT bloqueado por Python 3.14 — requiere Python ≤3.12.

## Archivos clave

| Archivo | Rol |
|---|---|
| `coordinator/relay.py` | TTL, mark_failed(), evict |
| `shattering/orchestrator.py` | Loop de generación |
| `node/shard_engine.py` | Forward pass INT4 |
| `shattering/mla.py` | Atención con mask + RoPE |
| `node/qwen2_ops.py` | Ops numpy puro |
| `shattering/router.py` | LOGOS/TECHNE/RHETOR |

## Links

- [[concepts/sharding]]
- [[concepts/int4_nibble]]
- [[concepts/lpc]]
- [[concepts/speculative_decoding]]
- [[entities/orchestrator]]
- [[entities/shard_engine]]
- [[entities/relay]]

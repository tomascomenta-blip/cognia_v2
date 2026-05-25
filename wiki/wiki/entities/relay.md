---
title: Relay — WebSocket relay de hidden states
type: entity
tags: [relay, websocket, nat, session, ttl]
updated: 2026-05-24
---

# Relay

→ [[index]]

## Qué hace

Intermediario WebSocket entre nodos que están detrás de NAT. Los nodos no pueden conectarse directamente entre sí — el coordinador actúa de puente retransmitiendo bytes sin leerlos.

## Flujo de una sesión

```
Nodo 0 → inicia sesión → recibe session_id
Nodo 0 → conecta WS /ws/relay/{session_id}/0
Nodo 1 → conecta WS /ws/relay/{session_id}/1
...
Nodo 0 → envía hidden state → relay → Nodo 1
Nodo 1 → procesa → envía → Nodo 2
Último nodo → logits → relay → cliente HTTP /infer
```

## Archivo fuente

`coordinator/relay.py`

## Parámetros clave

| Constante | Valor | Descripción |
|---|---|---|
| `SESSION_TIMEOUT` | 120s | TTL de sesión |
| `INFER_TIMEOUT_S` | 60s | Timeout del endpoint HTTP /infer esperando el último shard |

## Restricciones críticas

- `mark_failed()` y TTL son críticos — no romper. Si un nodo se desconecta mid-pipeline, `failed=True` se propaga al cliente
- `/ws/relay` valida formato de `session_id` y bounds de `shard_index` — esas guards no se pueden remover
- Evict loop corre en `cognia_desktop_api.py`

## Validaciones de seguridad

- `session_id`: formato UUID validado
- `shard_index`: validado contra bounds (`0 <= idx < n_shards`)

## Links

- [[entities/coordinator]]
- [[synthesis/inference_pipeline]]
- [[synthesis/security_model]]

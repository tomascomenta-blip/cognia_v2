---
title: relay.py — WebSocket relay de hidden states
type: source
tags: [relay, websocket, session, ttl, mark_failed]
updated: 2026-05-24
---

# relay.py

→ [[index]]

## Archivo

`coordinator/relay.py`

## Clases principales

| Clase | Descripción |
|---|---|
| `InferenceSession` | Mantiene WebSockets activos; TTL=120s; `failed` flag |
| `RelayManager` | Gestiona el dict de sesiones activas; cleanup loop |

## InferenceSession

```python
class InferenceSession:
    session_id: str
    n_shards: int
    sockets: Dict[int, WebSocket]   # shard_index → ws
    result_data: Optional[bytes]
    result_ready: asyncio.Event
    failed: bool
    fail_reason: str
```

## Métodos críticos

- `connect(shard_index, ws)` — acepta y registra el socket
- `disconnect(shard_index)` — limpia; trigerea `mark_failed()` si mid-pipeline
- `mark_failed(reason)` — propaga el error al cliente HTTP /infer
- `is_expired()` — `time.time() - created_at > SESSION_TIMEOUT`

## Por qué `mark_failed()` es crítico

Sin él, el cliente HTTP /infer quedaría esperando hasta INFER_TIMEOUT_S (60s) si un nodo se cae mid-pipeline. `mark_failed()` lo desbloquea inmediatamente.

## Links

- [[entities/relay]]
- [[entities/coordinator]]
- [[synthesis/security_model]]

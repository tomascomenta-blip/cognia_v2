---
title: Coordinator — coordinador del swarm
type: entity
tags: [coordinator, registry, relay, routing, shard-assignment]
updated: 2026-05-24
---

# Coordinator

→ [[index]]

## Qué hace

FastAPI desplegado en Railway (puerto Railway-asignado). Es el punto central de la red P2P:
- Registro y heartbeat de nodos
- Asignación de shards por nodo
- Routing de requests de inferencia
- Relay WebSocket de hidden states entre nodos que están detrás de NAT

## Archivos fuente

| Archivo | Rol |
|---|---|
| `coordinator/app.py` | FastAPI app principal — endpoints, rate limiting (slowapi) |
| `coordinator/relay.py` | WebSocket relay de hidden states |
| `coordinator/registry.py` | NodeRegistry — registro y asignación de shards |
| `coordinator/contributor.py` | Tiers, ledger, tokens económicos |
| `coordinator/federated_store.py` | FedAvg engine |
| `coordinator/rate_limiter.py` | SlidingWindowLimiter 60s ventana |
| `coordinator/run.py` | Entrypoint: `python coordinator/run.py` |

## Cómo levantarlo

```bash
python coordinator/run.py   # puerto 8001 por defecto
```

## Restricciones críticas

- `COORDINATOR_KEY` vacío → endpoints admin abiertos (CRITICO)
- `COGNIA_STRICT_AUTH=1` en prod o el coordinator arranca sin validación de clave
- El relay solo retransmite bytes — no lee ni modifica el contenido de los hidden states
- `relay_manager.start_cleanup()` se llama en lifespan — no saltear

## Métricas

Prometheus opcional (`prometheus_client` + `prometheus_fastapi_instrumentator`). Si no está instalado, se degradan silenciosamente.

## Links

- [[entities/relay]]
- [[entities/federated_store]]
- [[synthesis/inference_pipeline]]
- [[synthesis/security_model]]

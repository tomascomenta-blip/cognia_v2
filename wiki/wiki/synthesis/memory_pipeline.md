---
title: Flujo de memoria y personalización
type: synthesis
tags: [memory, elc, fedavg, sleep, episodic]
updated: 2026-07-16
---

# Flujo de memoria y personalización

→ [[index]]


## Estado (2026-07-16)

Deudas listadas abajo: 2 de 3 RESUELTAS (FatigueMonitor tiene reset:
fatiga_cognitiva.py:176,196; AttentionSystem tiene test de integracion:
tests/test_attention_integration.py). RST K=2 sigue sin validar. El lazo
sleep->ELC->FedAvg es capa swarm: el producto aprende en vivo via memoria
episodica + KG sin FedAvg.
## Pipeline de memoria

```
Interacción del usuario
  └─ memory_response_engine.py  (Stage 0 — coverage score)
       └─ episodic_fast.py  (AttentionSystem — RLock)
            ├─ Consulta embeddings semánticos (cognia_embedding.py)
            └─ Retorna contexto relevante

Durante el sueño (sleep_consolidation):
  ├─ emotion_wheel.py  (Plutchik — modula importancia x1.08/x0.92, LIMIT 500)
  ├─ Consolida memorias episódicas
  └─ Actualiza LoRA weights del usuario (local_adapter.py)
       └─ federated_store.py  (FedAvg cada 5 contribuciones, MIN=2)
            └─ Delta agregado → mejora global sin exponer pesos personales
```

## ELC — personalización local

- LoRA por usuario en `node/local_adapter.py`
- `kv_proj_out=256` fijo — no cambiar
- Máx 5 adapters en memoria, 50MB en disco (`adapter_store.py`)
- Rank expansion vía ARA cuando se satura (`rank_expansion.py`, MAX_RANK=8)

## FedAvg — aprendizaje federado

- Agrega deltas ELC entre nodos
- `MIN_CONTRIBUTORS=2`, `AGGREGATE_EVERY_N=5`
- BLOBs en `coordinator.db`
- Nunca expone pesos individuales — privacidad por diseño

## Deuda activa

- `FatigueMonitor` sin reset de estado (`fatiga_cognitiva.py`) — BAJO
- `AttentionSystem` sin tests de integración — MEDIO
- RST K=2, alpha=0.1 no validados — MEDIO

## Links

- [[concepts/elc]]
- [[concepts/federated_learning]]
- [[concepts/rst]]
- [[concepts/fatiga_cognitiva]]
- [[concepts/sleep_consolidation]]
- [[entities/episodic_fast]]
- [[entities/federated_store]]
- [[entities/local_adapter]]

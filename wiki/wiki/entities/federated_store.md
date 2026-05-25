---
title: FederatedStore — FedAvg + distilación semántica
type: entity
tags: [federated, fedavg, lora, privacy, coordinator]
updated: 2026-05-24
---

# FederatedStore

→ [[index]]

## Qué hace

Agrega adapters LoRA (ELC) de múltiples nodos usando FedAvg ponderado. Phase 20.4 añade peso semántico: contribuciones alineadas con el adapter global actual reciben más peso; outliers se down-ponderan automáticamente.

## Archivo fuente

`coordinator/federated_store.py`

## Constantes clave

```python
AGGREGATE_EVERY_N      = 5      # agrega cada N contribuciones
MIN_CONTRIBUTORS       = 2      # mínimo para agregar
MAX_PENDING            = 200    # cap de contribuciones pendientes
MAX_BLOB_BYTES         = 512_000  # 512 KB por submission
SEMANTIC_WEIGHT_ALPHA  = 0.3    # blend: final_w = tier_w * (1 + alpha * cos_sim)
_RANK_MAX              = 8      # igual que ARA MAX_RANK
```

## Privacidad

Los nodos añaden ruido Gaussiano (sigma=0.01) antes de enviar su delta. Solo se envían `(k_A, k_B, v_A, v_B)` — nunca pesos del modelo base ni datos del usuario.

## Storage

SQLite BLOBs en `coordinator.db`. No usa filesystem paths.

## Schema

```sql
CREATE TABLE fed_contributions (
    id, node_id, tier, weight, submitted_at, applied, adapter_blob BLOB
)
```

## Pesos por tier

`contributor.py` define TIERS. El peso de una contribución es `tier.min_params_b`. Multiplicado por el peso semántico en Phase 20.4.

## Links

- [[concepts/federated_learning]]
- [[concepts/elc]]
- [[entities/local_adapter]]
- [[synthesis/memory_pipeline]]

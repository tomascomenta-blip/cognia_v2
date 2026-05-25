---
title: DynamicWeights — precisión adaptativa en 4 tiers
type: entity
tags: [precision, int4, dynamic, rlock, drop-in]
updated: 2026-05-24
---

# DynamicWeights (DynamicPrecision)

→ [[index]]

## Qué hace

Drop-in replacement para `INT4Weights` con 4 tiers de precisión. Permite elevar la precisión de capas específicas en runtime sin modificar el grafo numpy completo.

## Archivo fuente

`shattering/dynamic_precision.py`

## Tiers

| Tier | Descripción |
|---|---|
| 0 | INT4 puro (default) |
| 1 | INT4 con escala refinada |
| 2 | INT8 |
| 3 | FP32 |

## Restricción CRITICA

**Layer promotion INT4→FP32 en caliente está fuera de alcance** — rompería el grafo numpy. DynamicWeights es un wrapper que gestiona la selección de tier, no una promoción en caliente real. Si se necesita FP32, usar un modelo separado.

## Concurrencia

Usa `RLock`. `PrecisionManager` coordina la selección de tier entre capas.

## Links

- [[concepts/int4_nibble]]
- [[entities/shard_engine]]

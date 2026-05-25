---
title: ELC vs FedAvg — local vs global
type: comparison
tags: [elc, fedavg, lora, privacy, personalization]
updated: 2026-05-24
---

# ELC vs FedAvg

→ [[index]]

ELC y FedAvg no son alternativos — son capas del mismo pipeline. ELC es local; FedAvg agrega los deltas ELC a nivel global.

| | ELC (local) | FedAvg (global) |
|---|---|---|
| Dónde corre | Nodo del usuario | Coordinator |
| Qué agrega | Nada — es local | Deltas de múltiples ELC |
| Privacidad | Máxima — pesos nunca salen | Alta — solo deltas + ruido Gaussiano |
| Cuándo actualiza | Cada sleep cycle | Cada AGGREGATE_EVERY_N=5 contribuciones |
| Beneficio | Personalización individual | Mejora global compartida |
| Restricción | kv_proj_out=256 fijo | MIN_CONTRIBUTORS=2, MAX_BLOB=512KB |

## Flujo combinado

```
usuario → episodios → sleep → ELC (local) → delta → FedAvg (coordinator) → adapter global mejorado
```

El adapter global mejorado no reemplaza el adapter local — se propaga como base para el próximo ciclo de entrenamiento local.

## Por qué no FedAvg directo sobre pesos completos

Requiere infraestructura de investigación (ver FUERA DE ALCANCE). El sistema actual solo hace FedAvg sobre deltas LoRA de baja dimensión (rank 4-8).

## Links

- [[concepts/elc]]
- [[concepts/federated_learning]]
- [[entities/local_adapter]]
- [[entities/federated_store]]

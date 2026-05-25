---
title: Federated Learning — FedAvg sobre deltas ELC
type: concept
tags: [federated, fedavg, privacy, elc, distributed]
updated: 2026-05-24
---

# Federated Learning

→ [[index]]

## Modelo de privacidad

Los pesos del modelo base son compartidos. Los pesos personales (adapters ELC) son locales. Solo los **deltas LoRA** se envían al coordinador para agregación — nunca los pesos completos ni los datos del usuario.

## FedAvg en Cognia

- Engine: `coordinator/federated_store.py`
- `MIN_CONTRIBUTORS=2` — necesita al menos 2 nodos para agregar
- `AGGREGATE_EVERY_N=5` — agrega cada 5 contribuciones
- BLOBs en `coordinator.db`

## Fuera de alcance

FedAvg sobre parámetros completos está fuera de alcance — requiere infraestructura de investigación. Solo se agregan deltas ELC (LoRA de baja dimensión).

## Tiers económicos

`coordinator/contributor.py` gestiona tiers, ledger y tokens del sistema económico. Los umbrales no deben cambiarse sin revisar nodos existentes.

## Links

- [[concepts/elc]]
- [[entities/federated_store]]
- [[entities/local_adapter]]
- [[synthesis/memory_pipeline]]

---
title: ELC — Embedded Local Customization
type: concept
tags: [elc, lora, personalization, numpy, privacy]
updated: 2026-05-24
---

# ELC — Embedded Local Customization

→ [[index]]

## Qué es

Personalización por usuario mediante **LoRA adapters locales** entrenados en el nodo del usuario. Los pesos del modelo base nunca se modifican ni se comparten. Solo los deltas LoRA se agregan federadamente.

## Por qué existe

Los pesos personales no son separables en un modelo compartido (ver FUERA DE ALCANCE). ELC resuelve esto manteniendo el adapter en local y solo federando deltas agregados.

## Implementación

- `node/local_adapter.py` — `LoRAWeights`, `LoRAAdapter`, `LoRATrainer`; numpy puro
- `kv_proj_out=256` — **fijo, no cambiar**
- `cognia/memory/adapter_store.py` — LRU: máx 5 en memoria, máx 50MB en disco

## Ciclo de vida

1. Usuario interactúa → memoria episódica captura contexto
2. Sleep → `LoRATrainer` actualiza adapter local
3. Delta → `federated_store.py` agrega con FedAvg
4. Si rank satura → ARA expande ortogonalmente (MAX_RANK=8)

## Links

- [[concepts/federated_learning]]
- [[concepts/ara]]
- [[entities/local_adapter]]
- [[entities/federated_store]]
- [[synthesis/memory_pipeline]]

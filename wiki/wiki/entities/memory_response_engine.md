---
title: memory_response_engine — Stage 0 del pipeline
type: entity
tags: [memory, coverage-score, ollama, stage0, pipeline]
updated: 2026-05-24
---

# memory_response_engine

→ [[index]]

## Qué hace

Stage 0 del pipeline de respuesta. Evalúa un **coverage score** sobre la memoria episódica para decidir si el sistema articula desde memoria (Ollama) o genera desde cero con los shards propios.

## Archivo fuente

`cognia/memory_response_engine.py`

## Lógica de decisión

```
coverage_score alto  → Ollama articula la respuesta desde contexto episódico
coverage_score bajo  →
    _shards_available() == True  → genera con shards INT4 propios
    _shards_available() == False → Ollama como fallback
```

## Por qué existe este stage

Evita llamar al modelo generativo cuando la respuesta puede extraerse de la memoria episódica con alta confianza. Reduce latencia y tokens generados.

## Restricción

Es el Stage 0 — cualquier cambio aquí afecta todo el pipeline. El coverage score determina si Ollama articula **o** genera; estas son rutas distintas con comportamientos distintos.

## Links

- [[entities/episodic_fast]]
- [[comparisons/ollama_vs_shards]]
- [[synthesis/inference_pipeline]]

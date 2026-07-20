---
title: memory_response_engine — Stage 0 del pipeline
type: entity
tags: [memory, coverage-score, ollama, stage0, pipeline]
updated: 2026-07-16
---

# memory_response_engine

→ [[index]]


## Estado (2026-07-16)

Correccion: cognia/memory_response_engine.py define MemoryContextBuilder
(construye contexto + coverage 0-1); el arbol de decision Ollama-vs-shards
descrito abajo vive en language_engine._call_ollama y es LEGACY — el chat
real va por el backend GGUF primero ([[synthesis/inference_pipeline]]).
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

---
title: episodic_fast — AttentionSystem de memoria episódica
type: entity
tags: [memory, episodic, rlock, attention, embedding]
updated: 2026-05-24
---

# episodic_fast (AttentionSystem)

→ [[index]]

## Qué hace

Memoria episódica de corto plazo. Almacena y recupera episodios usando similitud semántica sobre embeddings (all-MiniLM-L6-v2 o fallback n-gram).

## Archivo fuente

`cognia/memory/episodic_fast.py`

## Concurrencia

Usa `RLock` — reentrant lock. **Cuidado con deadlock si añades locks adicionales.** Es un archivo crítico — leer completo antes de modificar.

## Integración

- `cognia_embedding.py` provee los embeddings (lazy load, async queue, LRU cache)
- `memory_response_engine.py` consulta este sistema en Stage 0
- Durante sleep: `emotion_wheel.py` modula importancia de episodios

## Deuda activa

Sin tests de integración — MEDIO riesgo. Si modificas el AttentionSystem, agregar tests antes de mergear.

## Links

- [[entities/memory_response_engine]]
- [[sources/cognia_embedding]]
- [[synthesis/memory_pipeline]]

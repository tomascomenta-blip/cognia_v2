---
title: cognia_embedding.py — embeddings semánticos lazy y batched
type: source
tags: [embedding, lru, lazy, async, sentencetransformer]
updated: 2026-05-24
---

# cognia_embedding.py

→ [[index]]

## Archivo

`cognia/cognia_embedding.py`

## Tres componentes

```python
LazyEmbeddingModel     # carga all-MiniLM-L6-v2 solo en el primer uso real
                       # Thread-safe: double-checked locking

AsyncEmbeddingQueue    # agrupa llamadas de TODOS los hilos en batches
                       # máx 16 textos o 200ms, lo que ocurra primero
                       # elimina race condition entre hilo principal y CuriosidadPasiva

BoundedLRUCache        # reemplaza dict _embedding_cache con eviction O(1) + lock
                       # max_entries=512
```

## Por qué existe

El modelo `all-MiniLM-L6-v2` se cargaba en import-time de `cognia_v3.py` — bloqueaba el arranque. `LazyEmbeddingModel` diferiere la carga. `AsyncEmbeddingQueue` evita la race condition en acceso concurrente desde múltiples hilos.

## Integración

```python
# En Cognia.__init__():
self._embedding_queue = get_embedding_queue(throttle_controller=self.fatigue)
# En lugar de text_to_vector() directa:
from cognia_embedding import text_to_vector_fast as text_to_vector
```

## Fallback

Si `sentence-transformers` no está instalado: n-gram fallback para embeddings. Menos preciso pero funcional.

## Links

- [[entities/episodic_fast]]
- [[concepts/fatiga_cognitiva]]
- [[entities/router]]

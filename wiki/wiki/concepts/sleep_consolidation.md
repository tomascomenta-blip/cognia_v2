---
title: Sleep consolidation — pipeline de sueño
type: concept
tags: [sleep, consolidation, emotion, lora, memory]
updated: 2026-05-24
---

# Sleep consolidation

→ [[index]]

## Qué es

Pipeline que corre fuera de las interacciones activas. Consolida la memoria episódica, modula importancia emocional, y actualiza el adapter ELC del usuario.

## Pasos del pipeline

```
1. emotion_wheel.py
   - Plutchik wheel processor
   - Modula importancia: x1.08 (emociones positivas) / x0.92 (negativas)
   - LIMIT 500 episodios procesados
   - Solo se llama durante sleep

2. Consolidación episódica
   - Agrupa episodios similares
   - Prioriza por importancia modulada

3. LoRATrainer.train()  (node/local_adapter.py)
   - Triplet loss sobre episodios consolidados
   - ARA si el adapter satura (rank_expansion.py)

4. Delta → federated_store.py
   - FedAvg con otros nodos
```

## Restricción

`emotion_wheel.py` — solo llamar durante sleep. No invocar en el path de inferencia activa. LIMIT 500 es hard — no subir sin medir impacto en RAM.

## Links

- [[concepts/elc]]
- [[concepts/federated_learning]]
- [[entities/local_adapter]]
- [[entities/federated_store]]
- [[synthesis/memory_pipeline]]

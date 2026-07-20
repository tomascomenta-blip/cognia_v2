---
title: Model Router — estimador de dificultad de codigo
type: concept
tags: [dificultad, estimador, calibrado, 3b, 7b]
updated: 2026-07-16
---

# Model Router (estimador de dificultad)

→ [[index]]

## Que es

`cognia/agent/model_router.py` — `estimate_difficulty(task)` en [0,1],
cero LLM: heuristica barata (longitud + senales algoritmicas + restricciones
tramposas) CALIBRADA contra las etiquetas easy/medium/hard de las tasks de
benchmark_code. Es la base del eje de dificultad del sistema:
`_HEAVY_THRESHOLD=0.30` de generar_codigo y los umbrales de
[[entities/hybrid_router]] (que le suma la senal general multi-paso).

## Por que heuristica y no otro modelo

El punto es AHORRAR computo: gastar un modelo para decidir si gastar un
modelo es contradictorio en un i3 de 2 cores. Complementa la cascada
REACTIVA (correr barato, reintentar caro) con una decision PREDICTIVA
(saltar el intento 3B en lo que ya se predice duro).

## Links

- [[entities/hybrid_router]]
- [[concepts/colonia]]

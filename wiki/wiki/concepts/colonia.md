---
title: Colonia — cascada reactiva multi-modelo
type: concept
tags: [colonia, cascada, 7b, qwen35, razonador, estigmergia]
updated: 2026-07-16
---

# Colonia (cascada reactiva multi-modelo)

→ [[index]]

## Que es

Las etapas multi-modelo de `generar_codigo` (cognia/agent/tools.py): cuando
el modelo barato falla su oraculo (tests visibles), un miembro mas capaz
reintenta. Cada etapa es REACTIVA — solo corre si la anterior fallo — y el
perfil hibrido ([[entities/hybrid_router]]) da o niega el permiso.

```
etapa 1  3B best-of-N          (:8088, fleet LoRA)
etapa 2  7B greedy             ([[entities/heavy_code_7b]], :8092)
etapa 3  Qwen3.5-4B            (razonador; router razonamiento→4B medido
                                92.5 vs 82 del 3B, p~0)
etapa 4  superorganismo        ([[entities/superorganismo]], opt-in)
```

## Resultados medidos

- Codigo duro oculto: techo 57.5→67.5% con la cascada completa (2026-07-12).
- El juez de best-of-N descartaba el candidato correcto del 7B (tests
  visibles debiles) → fix: el 7B entra en GREEDY, no compite en el BoN.
- Falla compartida: donde el 3B falla, el 7B tambien suele fallar (techo
  compartido) — por eso los miembros >7B (q35, superorganismo) existen.
- En vivo (2026-07-15): spiral_order y decode_ways rescatados por la
  colonia con asserts ocultos PASS.

## Estigmergia

Cada fallo deja rastro (asserts fallados + enfoque descartado) que el
siguiente intento lee — teoria estigmergia v1 (2026-07-12): coordinacion
por el entorno compartido, no por mensajes entre modelos.

## Links

- [[concepts/ruteo_hibrido]]
- [[entities/heavy_code_7b]]
- [[entities/superorganismo]]
- [[entities/fleet_registry]]

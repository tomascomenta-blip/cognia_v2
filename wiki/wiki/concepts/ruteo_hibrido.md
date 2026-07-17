---
title: Ruteo hibrido por dificultad — permiso vs gasto
type: concept
tags: [hybrid, routing, dificultad, reactivo]
updated: 2026-07-16
---

# Ruteo hibrido por dificultad

→ [[index]]

## Idea

Dos ejes independientes deciden el costo de una corrida:

1. **Permiso** (ex-ante, cero LLM): la dificultad estimada de la tarea +
   el nivel `/esfuerzo` deciden que miembros caros PUEDEN despertar
   ([[entities/hybrid_router]]).
2. **Gasto** (reactivo): una etapa cara solo CORRE si la etapa barata
   fallo su oraculo (tests visibles). El permiso nunca fuerza el gasto.

Esto reemplaza el diseno anterior donde la cascada por dificultad vivia
solo DENTRO de `generar_codigo`; ahora es a nivel de sistema (mandato
2026-07-15).

## Validacion

Verificado en vivo (2026-07-15): trivial→mono; facil→agente (colonia solo
a esfuerzo maximo); media→agente+colonia; dura→las tres a esfuerzo medio.
Pruebas dificiles con modelo real 11/11: el 3B fallo sus tests visibles en
spiral_order y decode_ways → escalado 7B → asserts OCULTOS PASS (la colonia
rescato codigo duro en vivo).

## Por que reactivo

En el i3 (2 cores, ~8 tok/s el 3B) cada modelo extra cuesta minutos y RAM.
La leccion medida del programa MoM: la capacidad se compra con computo en
inferencia, no con fine-tune — pero solo cuando hace falta. El gate
predictivo ahorra el intento 3B en lo que ya se predice duro; el reactivo
evita gastar el 7B en lo que el 3B resuelve.

## Links

- [[entities/hybrid_router]]
- [[concepts/colonia]]
- [[concepts/effort_levels]]
- [[entities/heavy_code_7b]]

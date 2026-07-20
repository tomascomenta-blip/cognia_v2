# Diagnóstico y fix del fallo real "Agente estancado (acción repetida)"

Instrumento: `bench_estancamiento.py` — corre `cli._run_agent_task` (el loop de
PRODUCCIÓN, sin réplicas) con el 3B GGUF local sobre 12 tareas verificables por
postcondición. Comparación pareada (mismas tareas, mismo modelo, greedy).

## Resultado (MEDIDO)

| Corrida | stuck | éxito | fixes activos |
|---|---|---|---|
| baseline | 4/12 (33%) | 6/12 | — |
| post F1+F2 | 3/12 | 4/12 | F1 contexto previo, F2 recovery |
| **post F1-F4** | **1/12 (8%)** | **8/12 (67%)** | + F3 skills, F4 aviso nominal |

Gate pre-registrado: stuck ≤1/12 ✓, éxito ≥6/12 ✓ → **PASA** (estancamiento
−75%, éxito +33% vs baseline).

## Las 3 causas raíz (todas verificadas con trazas reales)

1. **Estado global entre tareas** (`~/.cognia_agent_state.json`): el "CONTEXTO
   PREVIO" inyectaba las 2 últimas tareas de CUALQUIER origen (CLI, oficina,
   bench). El 3B ancla en el nombre de archivo ajeno (lección medida del repo:
   copia lo concreto), hace `leer_archivo <archivo-de-otra-tarea>`, el ERROR
   se repite bajo greedy (T=0 ⇒ mismo contexto → misma acción) y el
   stuck-detector mata la tarea a los 3 strikes. Firma del 100% de los stuck
   del baseline. **F1**: `prior_context_relevant()` (cognia/agent/loop.py) —
   el contexto previo solo se inyecta con continuidad explícita o filename
   compartido. *Esto explica el fallo visto en la oficina: los trabajadores
   comparten ese archivo global.*
2. **Skills auto-aplicadas por similitud semántica difusa**: `find_skill` con
   coseno ≥0.35 matcheaba skills irrelevantes en tareas cortas ("Calcula 15
   por 4" → escribir-tests; "echo cognia_ok" → claude-mem). La guidance
   inyectada mete archivos inexistentes (`codigo_a_testear.py`, `tests/*`)
   → mismo mecanismo de anclaje y ciclo. Revelada por la corrida 2 (el fix F1
   destapó esta firma). **F3**: el auto-apply del agent loop usa
   `find_skill(semantic_fallback=False)` — solo match léxico fuerte; el
   fallback semántico queda para /skill explícito.
3. **El AVISO genérico no desvía al 3B** (pasos idénticos post-aviso en las
   trazas). **F4**: aviso NOMINAL ("ya ejecutaste 'ACCION: X args'. PROHIBIDO
   repetirla...") + **F2b** temperature 0.7 UN paso post-warn (rompe el
   determinismo). **F2**: al 3er strike, cierre honesto (un infer que resume
   qué se hizo y qué falta) en vez de morir sin respuesta.

## Residuo (honesto)

- 1 stuck restante (`append_then_count`): el 3B base NO conoce/elige
  `apendar_archivo` (reescribe con escribir_archivo y relee). Es CAPACIDAD,
  no andamiaje → lo ataca el adapter E3 (dataset ACCION v3 con 106 pares de
  recuperación-de-error + 106 anti-ciclo con el AVISO nuevo, ya en E-MIX).
- 3 no-éxito sin stuck: terminación prematura (escribe el JSON pero no lo
  valida) — también capacidad/instrucción → datos E3.
- El estado global de la máquina es una variable no controlada entre corridas
  del bench (declarado); la mejora es consistente con la eliminación de las
  firmas, no un artefacto de estado.

## Regresión

- `tests/test_agent_loop.py`: 3 tests de `prior_context_relevant` + 1 de
  `find_skill(semantic_fallback=False)` (23/23 verdes).
- El dataset de entrenamiento anti-ciclo usa el AVISO literal NUEVO
  (match train↔deploy, `gen_expert_v2.aviso_loop`).

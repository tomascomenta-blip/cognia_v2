# AUTOPSIA-13 — forense de las tareas que NADIE de la colonia resuelve

**2026-07-12 noche, corrida ROMPER EL TECHO.** Objeto: las 13 de tasks_hard_v2
que ni la cascada (3B→7B) ni Qwen3.5-4B resuelven contra los tests OCULTOS.
Evidencia: prompt + tests ocultos + error real de cada modelo.

## Clasificación por causa (fundada en el error observado)

| id | familia | entry | error q35 | error cascada | lectura |
|----|---------|-------|-----------|---------------|---------|
| SPEC1 | spec-largo | validate_username | assert | assert "Root_" | falla 1 caso borde de 5 reglas en orden |
| SPEC2 | spec-largo | format_table | runtime | assert 1er caso | formato ASCII exacto (anchos/separadores) |
| SPEC3 | spec-largo | compare_versions | syntax | assert prerelease | semver, orden de prerelease |
| SPEC4 | spec-largo | summarize_logs | assert | assert | reglas de dedup+orden (cayó con few-shot: FRÁGIL) |
| NEWX3 | spec-largo | parse_roman | assert "IIII" | assert | validación estricta (los -1) |
| NEWX4 | spec-largo | check_password | runtime | assert 1er caso | política multi-regla ordenada |
| NEWX5 | spec-largo | parse_csv_line | runtime | assert 1er caso | RFC-4180 comillas escapadas |
| ALG3 | parser | calc | runtime | IndexError pop empty | evaluador con precedencia + prohíbe eval() |
| NEWX2 | parser | eval_arith | syntax | assert 1er caso | evaluador con precedencia (MISMO que calc) |
| LONG2 | parser | run_turtle | syntax | IndexError | intérprete de mini-lenguaje |
| LONG3 | parser | parse_json | assert | syntax | parser JSON sin import json |
| LONG5 | clase-fmt | Polynomial | runtime | assert str(p) | clase con formato exacto de str |
| NEWD2 | algo-clásico | max_points_on_line | assert | assert | geometría (colinealidad, duplicados) |

Resumen: **7 spec-largo + 4 parser + 1 clase-formato + 1 algo-clásico.**

## Observación central (el reencuadre)

NINGUNA produce basura. Todas producen código *plausible con un bug* o que
cumple *casi* toda la spec. Señales duras:
- **calc y eval_arith son el mismo problema** (evaluador con precedencia) y
  fallan LOS DOS con el mismo tipo de bug de pila (IndexError pop empty). Un
  evaluador de expresiones es textbook — no es un límite de conocimiento,
  es un bug de implementación no depurado.
- **Los spec-largo fallan en UN assert**, no en todos: el modelo satisface
  la mayoría de las reglas y se le escapa un borde de una lista larga.
- **SPEC4 cayó con solo agregar few-shot** (E-FEWSHOT): la salida es
  SENSIBLE al contexto/muestreo → hay una solución cerca que el muestreo a
  veces toca y a veces no.

Esto es la firma de un techo de **BÚSQUEDA + DEPURACIÓN + COMPLETITUD**, no
de capacidad cruda. Hipótesis a falsar en E-PASSK.

## Predicciones falsables

- Si es **búsqueda**: pass@16 (temp alta) del mejor miembro contra ocultos
  recupera una fracción NO trivial de las 13 (≥4). El modelo SÍ puede
  generarlas; el single-shot/greedy no las encontraba.
- Si es **capacidad**: pass@16 ≈ pass@1 (0-1 de 13). Ni con 16 intentos las
  toca → es límite real de conocimiento/razonamiento.
- Mixto (lo más probable): los parser/algo (5) ceden a búsqueda; los
  spec-largo (7) necesitan un ORÁCULO mejor (tests que capturen los bordes)
  para que la búsqueda tenga gradiente → E-TESTGEN.

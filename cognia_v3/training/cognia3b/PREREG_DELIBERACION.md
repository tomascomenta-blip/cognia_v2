# PREREG — Gate de la MESA REDONDA (deliberación entre modelos, FLEET-30)

**CONGELADO ANTES DE CORRER (2026-07-12 ~03:20, corrida nocturna FLEET-30).**

## Hipótesis
La retroalimentación cruzada entre modelos DISTINTOS (candidato del 3B +
traceback real → reparación por NextCoder-7B, especialista en repair con
HumanEvalFix 81.1) recupera tareas duras que la cascada actual (3B→7B mismo
linaje) NO recupera. Riesgo conocido y declarado: el techo compartido medido
2026-07-11 (donde el 3B falla, el Qwen-7B también) podría extenderse a
NextCoder (misma base); si es así, el resultado será negativo y se documenta.

## Método
- Muestra CONGELADA sin cherry-picking: las primeras 6 tareas en orden de
  aparición de la lista de 25 falladas por la cascada en
  `results_code_gate7b_n40_20260710_1614.json`:
  **ALG3, LONG1, LONG2, LONG3, LONG4, LONG5**.
- Brazo A (baseline candidato): 3B greedy con el prompt del gate (protocolo
  RAW bajo el que esas tareas fallaron) + tests visibles por test-first del
  3B (mecanismo de producción).
- Mesa: `deliberate()` con participante único **nextcoder7b greedy**
  (max_tokens 512), **1 ronda**, feedback = ejecución REAL de los tests
  VISIBLES únicamente (los ocultos JAMÁS se muestran a los modelos).
- Métrica: tests OCULTOS de la suite congelada `tasks_hard_v2.jsonl`,
  antes vs después (pareado por tarea).
- Instrumento: cache_prompt=false, servers muertos entre fases (RAM:
  primero TODOS los candidatos 3B, cerrar, después NextCoder).

## Gates (congelados)
- **MR-1 (gate)**: la mesa recupera ≥2/6 en tests ocultos → el mecanismo
  aporta; se propone default ON para tareas duras (con el costo declarado).
- **MR-2 (info)**: sobre-ajuste = casos donde el score visible sube pero
  los ocultos siguen fallando (la lección del juez débil, cuantificada).
- **MR-3 (info)**: latencia por ronda de mesa (el costo real del loop).

## Regla de corte
MR-1 falla → COGNIA_DELIBERACION queda opt-in (OFF default), el resultado
negativo se registra en MANAGER_LOG y FLEET30_DESIGN; UN ajuste permitido
(participante o rondas) solo con diagnóstico, no repetir a ciegas.

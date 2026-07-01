# BENCH REASONING — RESULTADO (TAREA 3: por qué las respuestas son limitadas, y qué mejora de verdad)

**Fecha:** 2026-07-01 · **Sistema medido:** el deployado real (Qwen2.5-Coder-3B-Instruct Q4_K_M vía
LlamaBackend/llama-server b9391, CPU i3, LoRA tool-use activa) · **Bench:** `bench_reasoning.py`
(16 problemas de razonamiento con respuesta ENTERA exacta verificada a mano + 4 de formato estricto;
verificación determinista, sin LLM-juez) · **Datos:** `results_reasoning_20260701_1715.json` (direct),
`results_reasoning_full.json` (cot/sc3/formato), `results_reasoning_cotsys.json` (cot_system)

## La raíz, medida

El 3B deployado respondiendo DIRECTO resuelve solo **5/16 (0.3125)** de aritmética/lógica multi-paso
(temp=0). No es un problema de sampling ni de formato: es que el modelo chico no computa cadenas de
pasos "en la cabeza" — necesita externalizar el cómputo intermedio como tokens.

## Qué se probó y qué quedó

| mejora candidata | razonamiento | formato estricto | costo | veredicto |
|---|---|---|---|---|
| baseline direct | 0.3125 | compliance 0.75 | 1× | — |
| **CoT por turno (temp=0)** | **0.8125 (+50 pts)** | 0.25 (LO ROMPE) | ~3.8× tokens | **QUEDA — pero dirigido** |
| self-consistency k=3 (temp 0.7, voto) | 0.6875 | — | 3× del CoT | **DESCARTADA** (peor que CoT greedy: el sampling 0.7 en un 3B mete más ruido del que el voto corrige) |
| CoT en el SYSTEM prompt | 0.3125 (= baseline) | compliance 1.0 | ~1× | **DESCARTADA como palanca de razonamiento** (el 3B no se auto-dispara desde el system; la instrucción del turno de usuario le gana). La cláusula de formato sí ayudó (0.75→1.0) pero con n=4 — candidata, NO integrada. |

## Lo que quedó integrado (e2e, con tests)

`cognia/agent/stepwise.py` + wiring en el chat del CLI (`cli.py`): detector regex barato que agrega
"pensá paso a paso" al turno de usuario SOLO cuando la pregunta es cuantitativa/razonamiento y NO
pide formato exacto (donde el CoT daña, medido). El historial guarda el texto original del usuario.

Verificación:
- `tests/test_stepwise.py` (4 tests): los 16 items de razonamiento ACTIVAN el empujón, los 4 de
  formato NO, los turnos sociales NO.
- E2e real con el tag deployado (sin el artefacto "RESPUESTA:" del bench): **recupera 4/5** de los
  items que direct fallaba (m01/m03/m04/m06 OK; l02 —el caracol— sigue fallando, consistente con el
  techo 13/16 del CoT).

## Límites honestos

- n=16 items de razonamiento y n=4 de formato: suficiente para direcciones grandes (+50 pts, −50 pts
  de compliance), no para deltas finos. Ampliar con GSM8K si se quiere resolución.
- El costo del CoT es real (~3.8× tokens por respuesta a ~8 tok/s): el detector lo acota a queries
  cuantitativas.
- Sin medir: coherencia multi-turno (gap documentado en el recon), el efecto de la cascada 3B→7B
  sobre estos items, y la cláusula de formato en system (n=4, prometedora).
- La LoRA de tool-use estaba activa en el server durante TODO el bench (es la config deployada);
  los deltas son internos a esa config.

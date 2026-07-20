# E-COD — NO APTO: destilar la búsqueda tampoco transfiere (+2pp n.s.)

Kaggle 1×T4, 274.8 min. BoN@8 verificado por ejecución real sobre MBPP
(pool disjunto del eval por task_id + decontaminación por texto), receta
E-GROK, gate pareado N=200.

## Veredicto contra el pre-registro

| Predicción | resultado | veredicto |
|---|---|---|
| P-COD-2: yield BoN@8 en banda [20%, 80%] | **79.4%** (614/773) | **PASA** (justo en el borde fácil) |
| P-COD-1: pass@1 ≥ base +8pp, p<0.05 | 55.5% → **57.5%** (+2.0pp, n01=10, n10=6, p=0.45) | **FALLA** |

**`APTO_FLEET: false`.**

## Lectura honesta

1. El diseño evitaba el error de E-RZN (auto-destilar greedy-correcto = 0):
   acá se destilaban los HITS de la búsqueda (BoN@8 temp 0.8, tests reales).
   Aun así el traslado a greedy fue +2pp de ruido.
2. Señales de por qué: (a) yield 79% = el pool MBPP le queda FÁCIL al coder
   3B (la base greedy ya está en 55.5% del eval y la búsqueda encuentra
   solución en 4 de cada 5 del pool) → los pares destilados enseñan poco que
   la política no tenga; (b) train de solo 12 steps (614 pares packed) —
   corto, pero el prereg estaba congelado y no se re-tunea post-hoc.
3. **Cuadro de programa (3 corridas pre-registradas, ~10 GPU-h):**
   - E-RZN v1/v2 (auto-destilación razonamiento): 0pp.
   - E-COD (destilación de búsqueda código): +2pp n.s.
   - vs. andamiaje de INFERENCIA: stepwise +22pp (E-INT), BoN+juez +10pp
     (código duro), ejemplo-concreto +62pp (tool-calling).
   El fine-tune paga SOLO donde el gap es de FORMATO/hábito (ACCION 20→99).
   Para capacidad, lo que paga es gastar cómputo EN INFERENCIA.

## DECISIÓN

- La línea "experto de código por fine-tune" queda CERRADA (mismo estatus
  que razonamiento). El fleet queda con ACCION como único adapter (donde el
  gap era de formato) — coherente con toda la evidencia.
- El camino de mejora de código del CLI sigue siendo inferencia: BoN+juez
  (ya en el router), repair dirigido con traceback (ya en el loop), y
  descomposición por dificultad.
- Si alguna vez se reabre: pool DURO (tasks_hard-nivel, yield esperado
  ~30-40%) + train más largo, pre-registrado de nuevo. No con MBPP.

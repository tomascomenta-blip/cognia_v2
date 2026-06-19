# CYCLE 12 — La IA aprende a RAZONAR: prueba cadenas y se queda con la que funciona

Pilar 5 (Razonamiento). La IA enfrenta **problemas cotidianos** (dividir una cuenta con propina, qué
paquete sale más barato por kilo, cuántos viajes entran en un presupuesto, si llego a tiempo) y los
resuelve con **distintas cadenas de razonamiento** (estrategias). Ninguna estrategia es mejor para
todo. La IA prueba cadenas, un **examinador REAL** (o **preguntándole al usuario**) le dice cuál
acertó, y **aprende qué cadena usar según el tipo de problema** — y generaliza a problemas nuevos.

Es el mismo principio que cerró el aprendizaje continuo (CYCLE 8/11): **solo se aprende lo que
sobrevive a un examinador NO circular.** Aquí ese principio se aplica a la *selección de razonamiento*.

## Las 5 cadenas (estrategias) y su competencia por tipo (held-out)
Cada cadena es un procedimiento real con un error característico fuera de su "tipo casa":
- `direct` — intuición de un tiro (ignora la propina, ignora la tarifa fija). Rápida, falla en multi-paso.
  Es además un **fanfarrón**: reporta confianza ~0.95 SIEMPRE, aun equivocada (miscalibrada a propósito).
- `stepwise` — descomposición paso a paso (aplica propina y luego divide) → gana `split_bill`.
- `backwards` — razona hacia atrás desde la restricción (saca la tarifa fija, redondea) → gana `trips`.
- `unit_rate` — normaliza a precio por unidad → resuelve `cheaper_per_kg`.
- `decision` — estima y decide → resuelve `arrive_on_time`.

## Resultado FULL (train=4000, held-out=2000, semillas disjuntas)
| brazo | accuracy held-out | nota |
|---|---:|---|
| fija direct | 0.432 | el fanfarrón: confiado y flojo |
| fija stepwise | 0.632 | |
| **fija backwards** | **0.793** | la mejor cadena ÚNICA |
| fija unit_rate | 0.562 | |
| fija decision | 0.562 | |
| RANDOM | 0.592 | |
| **router CONFIDENCE** (circular) | **0.432** | el fanfarrón lo secuestra |
| **router VERIFIER** (examinador real) | **1.000** | aprende qué cadena por tipo |
| ORACLE (mejor por instancia) | 1.000 | cota superior |

**Lo que demuestra:**
1. **Ninguna cadena domina.** `backwards` (mejor fija, 0.793) ACIERTA cheaper/trips/arrive pero
   FALLA `split_bill` (0.19). Por eso *elegir bien la estrategia* es lo que importa.
2. **El router con examinador REAL aprende a razonar.** Aprendió el mapa tipo→cadena
   (`split_bill`→stepwise, `trips`→backwards, etc.), **supera a toda cadena fija (1.000 vs 0.793) y
   alcanza el oracle**, y **generaliza** a problemas nuevos (held-out de semillas disjuntas: no
   memorizó respuestas, aprendió qué forma de pensar aplica a cada situación).
3. **Anti-Goodhart (la lección del lab, en razonamiento).** Si la IA aprende por su PROPIA
   confianza (señal circular), el fanfarrón `direct` secuestra la política (la elige para los 4
   tipos) y la accuracy se desploma a 0.432. El examinador NO circular lo desenmascara. — mismo
   patrón que [CYCLE 8/11]: solo cuenta lo que sobrevive al examinador real.
4. **"Preguntarle al usuario" con presupuesto.** Cuando el router está genuinamente inseguro de un
   tipo (las dos mejores cadenas empatadas), consulta al usuario (oráculo) — pero bajo presupuesto.
   Curva de preguntas por bloque: **[198, 2, 0, 0, 0, 0, 0, 0, 0, 0]** — pregunta MUCHO al
   principio y deja de preguntar cuando ya aprendió, manteniendo la accuracy alta. Aprende a
   preguntar solo cuando le sirve.

## Caveats (honestidad)
- Solvers deterministas y las cadenas "casa" son exactamente correctas → oracle = 1.0 y el
  router-verifier toca un techo perfecto en esta suite sintética. Limpio para el MECANISMO, no es
  una afirmación sobre razonamiento real ruidoso.
- En `cheaper_per_kg` tanto `backwards` como `unit_rate` aciertan al 100% → el router eligió
  `backwards` por empate legítimo, no por bug. Lo demostrado es tipo→cadena-competente, no una etiqueta única.
- Semilla dominante única (problemas deterministas); sin bandas de varianza multi-seed. Existe el
  camino UCB; el run por defecto usa epsilon-greedy.
- "Preguntar al usuario" usa el verificador como oráculo perfecto; un humano real sería más ruidoso/caro.

## Innovación
No es best-of-N por instancia ni self-consistency: es un **router de meta-razonamiento aprendido
online, anclado a un examinador no circular**, que aprende *qué estrategia de razonamiento desplegar
según el tipo de problema*, generaliza a problemas nuevos, y **escala a la pregunta-al-usuario bajo
presupuesto**. Es la pieza que envolverá las cadenas del LM cuando sea más inteligente (hoy probado
sobre solvers de competencia conocida para que el resultado sea medible y limpio).

Reproducir: `python -m cognia_x.reason.run_cycle12` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle12_reason.py -q`. Datos: `runs/cycle12/`.

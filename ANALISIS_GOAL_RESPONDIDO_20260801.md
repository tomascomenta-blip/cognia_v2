# ANÁLISIS — EL GOAL, RESPONDIDO: ¿iguala el 20B+cómputo al frontier?

*Plan de análisis escrito el 2026-08-01 por la mañana, ANTES de computar los
números formales. Solo datos YA EN DISCO; cero GPU. Declaración de honestidad:
la exploración de estructura ya vio los niveles gruesos en las 81 comunes
(frontier ~76/81, raíz ~25/81, BoN@4 ~37/81, pool total ~46/81); este plan no
puede fingir ceguera sobre eso, pero fija ANTES del cómputo formal las
definiciones, el juez de la primaria, el manejo de instrumento y los umbrales
de lectura, que es lo que la exploración NO fijó.*

## Pregunta

¿Iguala el gpt-oss-20b local + cómputo en inferencia (BoN con verificador) al
frontier (claude-opus-5) — y donde no, con qué factor y qué compraría cada
palanca restante?

## Datos (todo en disco)

| fichero | qué aporta |
|---|---|
| `b3_codigo/reparacion.json` | 135 hard, brazo `bon` con raíz `s1` compartida, k=1..4, temp 0.8, **effort low, max_tokens 8192**, split ocultos **sin_fuga** |
| `b3_codigo/frontier_resultados.json` | opus-5 k=1 effort high, 198 tareas (83 hard), juez mío + oficial-con-topes, split **CON fuga** (el del factorial) |
| `b3_codigo/frontier_60_raw.json` + `frontier_138_raw.json` | el CÓDIGO crudo del frontier, para re-juzgar |
| `b3_codigo/lcb_sinfuga.json` | banco propio 167 tareas, k=4, para uplift BoN por estrato (secundaria) |
| `b3_codigo/factorial_low198.json` + `factorial.json` | 20B k=1 condiciones oficiales (para los estratos easy/medium) |

## Universo de la PRIMARIA

Las **81 tareas hard comunes** = 135 de reparacion ∩ 83 hard del frontier.
Fuera y declarado: 54 tareas de reparacion fuera del solape filtrado; 2 hard
del frontier (3637, 3700) sin datos BoN.

## Alineación de jueces (el paso nuevo)

Reparacion se juzgó con split `sin_fuga=True`; el frontier con el split del
factorial (con fuga). **La primaria exige el mismo examen en ambos lados**, y
la dirección del sesgo actual favorece al frontier (su oculto contiene casos
filtrados desde los visibles). Antes de comparar:

- `scripts/b3_frontier_rejuzga_sinfuga.py` re-juzga el código crudo del
  frontier en las 81 comunes con `tests_lcb(t, Random("20260730:"+tid),
  sin_fuga=True)` — byte-idéntico al examen de reparacion — a un fichero
  NUEVO `b3_codigo/frontier_hard_sinfuga.json` (no se toca el juzgado
  existente). Control de coherencia: se reporta cuántos veredictos cambian
  respecto a `mio_pasa` original (esperado: pocos y en dirección ≤0).
- Criterio de éxito en AMBOS lados: **pasa todos los ocultos** (`pasa_oc`;
  en frontier `oc_ok == oc_n > 0`). El mismo de todo lo firmado.

## Contrastes (todos apareados por tarea, sign-flip 10k réplicas + binomial
1 cola; IC95 Wilson para niveles; MDE reportado SIEMPRE)

Con F = frontier k=1 (sin_fuga), sobre las 81 (n=80 en primaria, ver
instrumento):

1. **C1**: F − 20B raíz k=1 — el hueco a iso-k.
2. **C2 (LA PRIMARIA del informe)**: F − 20B BoN@4 realizable (selector
   literal de bon.py: aprobado-visible > vis_ok > más temprano) — ¿el cómputo
   realizable cierra el hueco?
3. **C3**: F − techo del pool BoN@4 (oráculo: algún candidato pasa ocultos) —
   cota superior de BoN con selector perfecto.
4. **C4**: F − techo del pool TOTAL (unión bon+rep+pla, ~7-10 candidatos,
   ≈2.4× el cómputo de BoN@4) — la cota de "más de lo mismo".
5. **Curva** BoN k=1..4 (realizable y oráculo) sobre las 81, con tokens.

## Instrumento

- `arc191_d` (frontier, salida >64k del harness del PLAN): instrumento del
  plan. **Primaria n=80 (excluida); sensibilidad n=81 contándola como fallo
  del frontier.** Si ambas lecturas no coinciden en signo y umbral, se dice.
- Candidatos 20B con `instrumento` (6 en total): fallo del candidato
  (conservador e idéntico a lo firmado en reparacion).

## Secundarias (declaradas, no deciden)

- **S1**: mismo C1..C4 con el frontier juzgado con fuga (el fichero original)
  — sensibilidad al split.
- **S2 easy/medium**: hueco k=1 por estrato en las 198 (frontier vs
  oficial_low, ya firmado: easy 52/52 vs 50/52; medium 59/63 vs 35/63) +
  uplift BoN@1→@4 por estrato en el banco lcb propio (167 tareas, dificultad
  vía `carga_lcb`; config effort low/8k — distinta de las condiciones
  oficiales, DECLARADO). El solape lcb∩frontier es 43 tareas (12 easy / 13
  medium / 18 hard): se reporta el apareado ahí con su MDE, que se espera
  SIN POTENCIA — se dice y no se fuerza.
- **S3**: gasto en tokens de salida por brazo (de `analisis_reparacion.json`)
  para el "a qué precio".

## Confounds declarados de la primaria

1. Apareado ENTRE corridas y ENTRE configs: reparacion (effort low, 8192 tok,
   temp 0.8, prompt de bon.py) vs frontier (effort high, harness Claude Code).
   El apareado por tarea elimina la dificultad como confound, no la config del
   brazo 20B. Mitigante medido: raíz k=1 en las 81 (25/81 = 30.9%) ≈
   oficial_low hard en las 83 (25/83 = 30.1%, 60k tok): el presupuesto corto
   de reparacion NO deprime el nivel k=1 del estrato, y la celda XL ya midió
   que el presupuesto compra 1/12 en hard.
2. Contaminación de entrenamiento del frontier: más plausible que en el 20B
   (firmado); el nivel frontier es techo optimista.
3. k=1 del frontier: sin varianza medida (la P2 de esta sesión la mide).
4. BoN con parada temprana: el pool realizado se trunca al pasar visibles;
   el oráculo C3 sobre pool truncado es cota INFERIOR del pass@4 verdadero
   (solo afecta a tareas donde algún candidato pasa visibles y falla ocultos).

## Umbrales de lectura (fijados aquí)

- "**Iguala**" en un estrato = el neto apareado F − 20B(mejor palanca
  realizable) no es significativo (P≥0.05) Y |neto| < MDE.
- "**No puede**" = neto significativo a P<0.01 incluso contra el TECHO C4.
- El factor se reporta como cociente de tasas con IC (no decide nada).

## ENMIENDA 1 (2026-08-01, tras recomputo independiente ×2 y refutación adversarial)

El recomputo independiente (2 agentes, código propio, sin leer mi script)
**coincidió exacto en todos los números, 0 discrepancias**. La refutación dejó
7 ADVERTENCIAS, ninguna BLOQUEA; correcciones aplicadas:

1. **P a 1 cola sobre la dirección PRE-especificada** (F−20B>0), no la
   observada — corregido en `b3_goal_analisis.py` (hoy inocuo: pierde=0 en
   todos los contrastes).
2. **Conteo de instrumento del 20B corregido**: 6 candidatos en raiz/bon
   (los que tocan C1-C3) y 17 en total contando rep/pla — el "6 en total"
   de arriba era impreciso. Sensibilidad simétrica añadida: excluyendo las
   3 tareas de la primaria con candidato raiz/bon instrumentado, C2 = +37
   (37/0, P=7.3e-12) — sin cambio de veredicto.
3. **Cota peor-caso de la parada temprana, publicada**: 5 tareas pararon en
   un falso positivo de visibles sin éxito oculto en el pool (la parada
   puede dispararla cualquier candidato, no solo la raíz — arc190_d).
   Regalándoselas todas al 20B: C4 peor-caso **51/80 (63.8%) → neto +25
   (25/0, P=3.0e-08)**. El "NO PUEDE" en hard sobrevive el peor caso.
4. **Alcance del veredicto acotado a lo medido**: el pool 20B entero es
   effort low / 8192 tokens; "no puede" se firma **con las palancas
   MEDIDAS** (BoN/rep/pla a esa config + esfuerzo y presupuesto cerrados
   por separado), no "con cómputo en inferencia" a secas — la interacción
   presupuesto×diversidad BoN a effort high no está medida.
5. **S2 no afirma "iguala" formal en easy/medium**: easy 0 discordantes
   (n=12) y medium +4 (4/0, P=0.0625, n=13) son SIN POTENCIA con MDE
   inevaluable; además el apareado del solape mezcla split con fuga
   (frontier) y sin fuga (20B) — mitigado por el 0/81 de cambios medido,
   y declarado. La lectura de estratos se apoya en los niveles k=1 de las
   198 y el uplift BoN del banco propio, etiquetados descriptivos.
6. **Texto alineado con la implementación**: curva BoN sobre la primaria
   n=80 (no 81); S3 recomputado desde reparacion.json restringido a la
   primaria (no desde analisis_reparacion.json).

## Entregables

`scripts/b3_frontier_rejuzga_sinfuga.py` · `scripts/b3_goal_analisis.py` ·
`b3_codigo/frontier_hard_sinfuga.json` · `b3_codigo/analisis_goal.json` ·
informe "EL GOAL, RESPONDIDO" en `META_MODELO_GRANDE.md`. Verificación
independiente de los números por workflow (recomputo desde los JSON crudos)
y revisión adversarial del informe ANTES de firmar.

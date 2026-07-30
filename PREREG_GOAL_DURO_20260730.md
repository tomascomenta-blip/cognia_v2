# PREREG — EL GOAL: ¿8/8 en el banco DURO con el sistema eligiendo su muestra?

**Fecha:** 2026-07-29 ~23:35, sesión tarde-noche 29→30. **Escrito ANTES de
juzgar nada** (la generación de la fase 1 ya corre, pero ningún veredicto
estricto se ha computado ni mirado). Es la primera medición del **objetivo
declarado en META_MODELO_GRANDE**, y cierra una brecha que llevaba semanas
abierta sin que nadie la nombrara.

## La brecha

META define el goal así: *"que la máquina de 16 GB entregue **8/8** en el
banco duro, con producto entregable — no oráculo: el sistema tiene que
poder elegir la muestra buena"*. Pero:

- El modo BoN K=4 + selector held-out se validó y confirmó en el banco
  **BRUTAL** (24/24 y 20/20), no en el duro.
- El banco **DURO** (las 8 tareas del goal: undo_redo, descuento_tramos,
  form_cruzado, tabla_compuesta, precedencia, tres_en_raya, temporizador,
  serpiente) **no tenía held-outs a mano** — o sea, no tenía juez estricto
  ni, por tanto, selector con señal real. Brutal y fácil sí los tienen.

Sin held-outs del duro, el número del goal nunca se pudo medir.

## Lo que se hace

1. **Held-outs a mano de las 8 tareas duras** (escritos hoy, antes de ver
   ninguna página, solo desde el enunciado): `b1_contratos_heldout_duras.json`.
   Regla de diseño heredada: cada check crítico es una CONSECUENCIA LÓGICA
   del enunciado sobre selectores que el enunciado declara obligatorios, y
   los casos son DISTINTOS de los del contrato original (si el original
   prueba 60 unidades, el held-out prueba 11 y 51; si el original prueba la
   fila, el held-out prueba la columna).
2. **Fase 1 (GPU, corriendo):** 8 tareas × 1 réplica × K=4 muestras
   independientes de primgen (max_rondas=1, el modo confirmado) = 32
   muestras, guardadas con su HTML.
3. **Validación de los held-outs (obligatoria, ANTES del veredicto):** se
   juzga cada muestra con original y held-out y se auditan a mano TODOS los
   desacuerdos. Un desacuerdo puede ser (a) bug del held-out → se corrige y
   se declara la corrección, o (b) fallo real que un examen ve y el otro
   no → se deja. Es el mismo procedimiento que en brutal y fácil (allí cazó
   3 FN míos). **Sin esta auditoría el número no se firma.**
4. **Fase 3:** con los held-outs finales, se computan las métricas del goal.

## Métricas y umbrales (fijados ahora)

Sobre las 8 tareas (una réplica; n=1 por tarea es poco y se declara):

| métrica | qué es |
|---|---|
| **CONTROL** | estricto de la muestra s=1 (lo que el sistema entregaría sin BoN) |
| **MODO (el número del goal)** | estricto de la muestra que el selector held-out elige |
| **TECHO pass@4** | ¿alguna de las 4 muestras es estricta? |

| lectura del MODO | veredicto |
|---|---|
| **8/8** | **GOAL ALCANZADO** en el banco duro con producto entregable y selección real. Se declara con el caveat de n=1 réplica y se pre-registra la réplica de confirmación |
| 6-7/8 | cerca: se reporta el número, se identifican las tareas que fallan y si el fallo es de TECHO (ninguna muestra sirve) o de SELECCIÓN (había buena y no la eligió) |
| ≤5/8 | el goal no está al alcance del muestreo en este banco; el diagnóstico techo-vs-selección dirige lo siguiente |

**La distinción que manda para la interpretación** (pre-declarada): por
cada tarea fallida se clasifica el fallo en
- **TECHO** (pass@4 = 0 en esa tarea): el muestreo no la compra — es el
  criterio de KILL que META ya tenía escrito ("si una tarea no sale NUNCA
  en 8 muestras, el muestreo no la compra"), y sería el único argumento
  honesto para necesitar más conocimiento en los pesos;
- **SELECCIÓN** (pass@4 = 1 pero la elegida falla): el verificador no
  distingue — es el cuello de señal ya conocido, no de capacidad.

Secundarias: pérdida del selector (techo − modo); FP del contrato original
contra el held-out; nº de muestras infra/sin HTML; tiempos.

## Reglas heredadas (no se re-litigan)

- Infra: EXCEPCIÓN del harness, juez crasheado, backend degradado/≠8080 →
  la muestra no cuenta; "sin HTML" con backend sano = reprobado legítimo.
- Juzgado bajo presupuesto de pared propio (lección juez-colgado).
- **Corte del reloj:** si el aterrizaje llega antes del final, se reporta
  el PARCIAL con el n alcanzado y se declara como tal — nunca se extrapola.
- n=1 réplica: el resultado es una FOTO, no una tasa. La varianza medida
  hoy (±34 pts entre corridas, 54% por celda) obliga a decir esto en voz
  alta: **un 8/8 aquí sería el goal alcanzado en una corrida, y exigiría
  réplica antes de declararlo estable.**

## RESULTADO — corrida 1 (2026-07-30 ~00:05, 32/32 muestras, 0 sin HTML)

**MODO = 8/8 → GOAL ALCANZADO en esta corrida.** Control (s1) 7/8, techo
pass@4 8/8, **pérdida del selector = 0**, 0 fallos por TECHO y 0 por
SELECCIÓN.

| tarea | ctrl | MODO | techo | elegida | muestras estrictas |
|---|---|---|---|---|---|
| undo_redo | OK | OK | OK | s1 | 1,2,3,4 |
| descuento_tramos | OK | OK | OK | s1 | 1,2,3,4 |
| form_cruzado | OK | OK | OK | s1 | 1,2,3,4 |
| **tabla_compuesta** | **--** | **OK** | OK | **s2** | 2,3 |
| precedencia | OK | OK | OK | s1 | 1,3,4 |
| tres_en_raya | OK | OK | OK | s1 | 1,2,3,4 |
| temporizador | OK | OK | OK | s1 | 1,2,3,4 |
| serpiente | OK | OK | OK | s1 | 1,2,3,4 |

**Lo que este número SÍ dice:**
- Ninguna tarea del banco duro es inalcanzable para el muestreo: techo
  8/8, **0 fallos por TECHO**. El criterio de KILL que META tenía escrito
  ("si una tarea no sale NUNCA en 8 muestras, el muestreo no la compra")
  **no se dispara en ninguna**.
- El selector held-out no perdió nada (pérdida 0) y rescató la única tarea
  que el control fallaba (tabla_compuesta, eligiendo s2).

**Lo que este número NO dice — los tres caveats que impiden declararlo
estable, en voz alta:**
1. **n=1 réplica: es una FOTO, no una tasa.** Con la varianza medida esta
   misma noche (±34 pts entre corridas, 54% de reproducibilidad por
   celda), otra corrida podría dar 6/8 o 7/8 sin que nada haya cambiado.
   Réplica pre-registrada abajo y lanzada de inmediato.
2. **La ganancia del BoN aquí es +1 tarea, no siete.** El control ya
   entregaba 7/8 — el banco duro está mucho más cerca del alcance del
   sistema sin BoN de lo que sugería el marco mental "17 puntos de hueco".
   Coherente con el pass@1 ≈83% que META ya registraba.
3. **El held-out NO demostró independencia en este banco: 0 desacuerdos
   con el contrato original en las 32 páginas** (en el brutal cazó 4 FP).
   O sea, el "juez estricto = original ∧ held-out" fue de facto el
   contrato original. El examen es más blando de lo que la etiqueta
   sugiere, y así queda declarado. (Validación: 0 desacuerdos, 0 checks
   que fallen siempre, cobertura 4/4 en las 8 tareas.)

Caveat heredado de META que sigue vigente: el banco lo diseñó la misma
familia de modelos que lo resuelve.

## RÉPLICA DE CONFIRMACIÓN — umbral fijado ANTES de correrla (00:10)

Se lanza en directorio propio (`--sufijo r2 --replicas 1`): 32 muestras
nuevas. **Desviación declarada:** el runner impide `--reanudar` con otro
número de réplicas (guarda contra mezclar configuraciones), así que la
réplica reusa la etiqueta rep=1 y, con ella, **las mismas semillas de
hints de feromona que r1**. La generación sigue siendo estocástica y la
varianza dominante es del generador (medido hoy: 54% de reproducibilidad
con el prompt EXACTAMENTE igual), así que la réplica es legítima — pero es
menos independiente que si los hints difirieran, y eso podría
SOBREestimar la reproducibilidad. Se declara antes de ver el número.

| resultado de r2 | lectura |
|---|---|
| 8/8 | **goal alcanzado en 2 de 2 corridas**: se declara alcanzado, con los caveats 2 y 3 en pie |
| 6-7/8 | el 8/8 de r1 fue una FOTO: se declara "8/8 en 1 de 2 corridas" y el número honesto del goal es el par (r1, r2), nunca solo el mejor |
| ≤5/8 | r1 fue atípica; el goal NO está alcanzado y manda r2 |

Se reporta también si el fallo (si lo hay) es de TECHO o de SELECCIÓN, y
el control de r2 — que es la tasa base del sistema sin BoN.

## Presupuesto

Fase 1 ≈ 3-3.5 h (banco duro, ~6 min/muestra medidos). Validación y fase 3
≈ 40 min. Cierre estimado 03:15-03:30, con el aterrizaje a las 04:14.

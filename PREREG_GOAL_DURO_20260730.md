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

## Presupuesto

Fase 1 ≈ 3-3.5 h (banco duro, ~6 min/muestra medidos). Validación y fase 3
≈ 40 min. Cierre estimado 03:15-03:30, con el aterrizaje a las 04:14.

# PREREG — Consenso conductual, variante MEDOIDE

**Fecha:** 2026-07-30 ~17:00, sesión tarde-noche 30→31. **Escrito ANTES de
ejecutar una sola sonda.** Cero GPU: las sondas ya están en disco.

## Por qué esta variante, y por qué el mecanismo la señala

El consenso conductual (PREREG_CONSENSO_CONDUCTUAL) quedó en **+2, MODERADA**:
control 17/24 → elegida 19/24, techo 24/24, **pierde 0**. Su diagnóstico
medido no fue "elige mal" sino **"no hay mayoría que formar"**:

| | |
|---|---|
| ensayos SIN mayoría | **13 de 24** |
| tamaño medio de la mayoría | **1.54** de 4 |
| co-failure (la mayoría era de muestras reprobadas) | 3 |
| ancla de validez (firmas distintas) | 24/24 |

Con 4 muestras dando 4 firmas distintas, la regla "gana la mayoría" **no
tiene nada que contar** y cae al control. La variante medoide sustituye
*mayoría* por **centralidad**: gana la muestra cuya firma está **más cerca
del resto**, que siempre existe aunque no haya dos firmas iguales.

La hipótesis falsable es: *si las implementaciones correctas se parecen entre
sí más de lo que se parecen a las rotas, la más central tiende a ser correcta*
— una versión conductual de "la verdad está en el consenso" que no exige
coincidencia exacta.

## Qué se construye

`scripts/b2_medoide.py`. Sobre lo ya congelado:

1. Se re-ejecutan **las mismas sondas** (`sondas_por_tarea.json`, huella
   `eaaed698401a`) sobre las mismas 96 muestras de `b2_bon_heldout`. Sin LLM:
   las secuencias ya están escritas.
2. En vez del **hash** de la firma (que solo dice igual/distinto) se guarda la
   **trayectoria completa de estados**, que es lo que permite medir distancia.
3. Distancia entre dos muestras = **fracción de posiciones de la trayectoria
   en que difieren** (normalizada por el largo común). Es una métrica simple,
   declarada de antemano y sin parámetros que tocar.
4. **MEDOIDE** = la muestra con menor distancia media a las demás. Empate → la
   de índice menor, que es `s1`, o sea el control (nunca se aparta del control
   sin motivo).

## Métricas y umbrales (PRE-REGISTRADOS)

Ground truth: `estricto` de `b2_bon_heldout`. Las tres referencias ya medidas
sobre los MISMOS 24 ensayos:

| referencia | valor |
|---|---|
| control (s1) | **17/24** |
| consenso por mayoría | 19/24 (**neto +2**) |
| techo pass@4 | **24/24** |

**Primaria: el NETO APAREADO** = RESCATA − ESTROPEA sobre los mismos 24
ensayos. (No una tasa suelta: la lección de hoy es que cualquier regla que
solo relaja o solo endurece mueve las tasas a la vez y cruza cualquier umbral
de una sola.)

| resultado | veredicto |
|---|---|
| **neto ≥ +5 y supera el p95 del brazo nulo** | **VIVE** — se pre-registra la confirmación |
| neto +3 a +4, o ≥+5 sin superar el nulo | GRIS: se reporta y no se adopta |
| **neto ≤ +2** | **KILL** — no mejora al consenso por mayoría, que ya dio +2 |
| **ESTROPEA > 0 con neto < +5** | **KILL** — el consenso por mayoría perdía 0; una variante que rompe lo que funcionaba no entra |

**BRAZO NULO obligatorio** (la lección que hoy mató a la poda): 1000
selectores que eligen una muestra **uniformemente al azar** entre las
disponibles del ensayo, semilla fija. Se publica la distribución de x/24 y el
**percentil donde cae el medoide**. Un selector aleatorio ya acierta bastante
en este banco, así que un "19/24" nominal no dice nada por sí solo.

Secundarias: nº de ensayos donde medoide y mayoría difieren; distancia media
intra-ensayo; y cuántos de los **13 ensayos sin mayoría** resuelve el medoide
—que es exactamente lo que la variante viene a arreglar y por tanto el número
que la juzga por su propio mecanismo.

## Lo que este diseño NO puede demostrar

- **El medoide no crea señal donde no la hay.** Si las 4 muestras son malas de
  formas distintas, la más central sigue siendo mala; el co-failure medido (3
  de 24) acota pero no elimina ese riesgo.
- Son **4 enunciados** (buscaminas, carrito_stock, hoja_calculo, kanban) y
  n=24 ensayos: un neto de +5 sobre 24 es 5 tareas. Con esa n, la diferencia
  entre +4 y +6 es una tarea, y se dice.
- **Comparte instrumento con el consenso por mayoría** (las mismas sondas y el
  mismo snapshot). Lo que se compara es la REGLA DE DECISIÓN, no el
  instrumento; si las sondas son ciegas para una tarea, las dos reglas lo son.
- Las sondas las escribió un LLM en su día. Se reusan **idénticas** (huella
  verificada) para que la comparación con el +2 sea pareada; eso hereda sus
  límites, incluida la sonda de buscaminas que la revisión anterior encontró
  ciega (6 de 25 celdas).

## RESULTADO

*(se rellena después; nada de esto se toca retroactivamente)*

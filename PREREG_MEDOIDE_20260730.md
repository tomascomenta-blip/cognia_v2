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

## RESULTADO (2026-07-30 ~17:30 — 24/24 ensayos, 0 infra, cero GPU)

**GRIS por el criterio pre-registrado. No se adopta.**

| | |
|---|---|
| control (s1) | 17/24 |
| **MEDOIDE** | **21/24** |
| techo pass@4 | 24/24 |
| **NETO APAREADO** | **+4** (RESCATA 4 · **ESTROPEA 0**) |
| rescata | `carrito_stock:r1`, `hoja_calculo:r1`, `hoja_calculo:r3`, `hoja_calculo:r6` |
| referencia: consenso por MAYORÍA | 19/24 (neto +2), pierde 0 |

El medoide **duplica la ganancia de la mayoría** (+2 → +4) y **sigue sin
perder nada** (asimetría 4-0, igual que todas las variantes de consenso
medidas). Eso es exactamente lo que el mecanismo predecía: los 13 ensayos sin
mayoría dejaban de decidirse, y la centralidad sí decide en ellos.

Pero el umbral de vida era **neto ≥ +5 y superar el p95 del brazo nulo**, y no
cumple ninguno de los dos:

```
BRAZO NULO (1000 selectores uniformes, semilla 20260730):
  media 18.46/24 · p95 = 21/24 · max 23/24
  P(azar >= medoide) = 0.100     -> NO supera el p95
```

### El hallazgo del brazo nulo, que vale más que el veredicto

**Elegir una muestra AL AZAR ya da 18.46/24 de media — más que el control
(17/24).** Con techo 24/24, este banco tiene tantas muestras buenas por ensayo
que el azar es un rival duro. Consecuencia inmediata y con efecto
retroactivo:

> **Medir un selector contra el CONTROL sobrestima su mérito.** La referencia
> honesta es el AZAR, no s1 — porque s1 no es más que otra muestra arbitraria.

Releídas contra esa referencia, las variantes de consenso de esta semana
cambian de significado:

| variante | resultado | contra el control | **contra el azar (18.46)** |
|---|---|---|---|
| consenso por mayoría | 19/24 | "+2, moderada" | **+0.5: ruido** |
| consenso de contratos V1/V3 | +3 | "moderada" | probablemente ruido también |
| **medoide** | **21/24** | +4 | **+2.5, percentil 90 — la mejor de todas, y aun así p=0.10** |

**El "+2 moderada" del consenso conductual no era moderada: era
indistinguible del azar.** El medoide es la única variante que se despega
visiblemente, y ni así cruza el listón del 5%.

### Lectura honesta

Con n=24 ensayos y 4 enunciados, la diferencia entre +4 y +5 es **una tarea**,
y el p=0.10 dice que una de cada diez veces el azar iguala este resultado. No
se adopta nada con eso. Pero el perfil —**mejor variante medida, pierde 0,
mecanismo confirmado (resuelve justo los ensayos sin mayoría)**— la deja como
la única candidata viva de la familia si alguna vez hay banco para replicarla.

**Condición para retomarla, pre-registrada ahora:** replicar sobre ≥40 ensayos
o ≥8 enunciados distintos, con el mismo brazo nulo. Por debajo de eso no hay
resolución para separar +4 de +2, y volver a medirlo con n=24 sería repetir
esta misma ambigüedad.

### Nota de instrumentación

Lo que faltaba no era la idea sino **guardar la trayectoria en vez de su
hash**: el runner original serializaba la firma a `sha1[:12]`, que solo dice
igual/distinto y hace imposible cualquier noción de distancia. `_firma` ya
devolvía la trayectoria completa; solo había que no tirarla. Es el segundo
caso del día del mismo patrón — el otro fue el contrato autogenerado que los
runners no persistían.

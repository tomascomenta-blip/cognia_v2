# Falsación del plan "self-lobotomy"

**Fecha:** 2026-08-19 · **Máquina:** RTX 5060 Ti 16311 MiB · **Backend:** llama-server `:8080`, 1 slot,
`Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf`, `--ctx-size 200192 --parallel 1 --flash-attn on`.
Todo lo que sigue está **medido en esta máquina hoy**, no razonado.

---

## Veredicto en una línea

> **La premisa de VRAM es falsa: el KV cache de este servidor está reservado ENTERO desde el arranque y no
> se mueve un solo MiB durante la conversación. Medí 13 168 MiB con 2 944 tokens de contexto y 13 155 MiB
> con 187 874 tokens — el consumo BAJÓ 13 MiB al usar 64 veces más contexto.** El reset de contexto no
> libera VRAM porque no hay VRAM que liberar. Y las dos piezas que el plan propone para sustituir a la
> ventana (comprimir, y seleccionar de un almacén inmutable) **destruyeron el 92% y el 47% de las
> restricciones respectivamente, mientras que no hacer nada las conservó al 100%**.

La idea no está muerta. Está mal fundamentada. Lo que la salva está en la sección final, y es una cosa
distinta de la que el dueño pidió.

---

## Tabla de veredictos

| # | Hipótesis del plan | Veredicto | Prueba de una línea |
|---|---|---|---|
| H1 | El KV crece y consume VRAM durante la conversación | **REFUTADA** | 13 168 MiB @2,9k tok → 13 155 MiB @187,9k tok (Δ = −13 MiB, ruido) |
| H2 | Multiagente con contextos destruidos ahorra VRAM | **REFUTADA** | Ahorro = **0 MiB**. Con `--parallel 1` los pesos son residentes; cambiar de agente cambia el prefijo y **cuesta** 10,68 s de re-prefill |
| H3 | Un crítico del mismo modelo detecta las alucinaciones | **REFUTADA** | Exactitud balanceada **0,517 y 0,523** (azar) en dos framings; el veredicto lo fija el adjetivo del prompt, no el contenido |
| H4 | Los snapshots inmutables evitan la degradación acumulativa | **REFUTADA** | Datos inmutables, pero la SELECCIÓN recuperó **10/19 = 0,526** de las restricciones críticas; 9 de 24 no se cargaron **nunca** en 8 ciclos |
| H5 | Comprimir el contexto entero antes del reset es barato | **DUDOSA** | 16,5 s por compactación. Barato a 72/día (19,8 min). Ruinoso a 500/día (137 min). Depende de una frecuencia que el plan no fija |
| H6 | El modelo mantiene un contrato estable durante cientos de ciclos | **CONFIRMADA como problema, pero la causa NO es el contexto** | Adherencia conductual **0,75 / 0,71 / 0,75** a 0,4k / 32k / 128k tokens: plana. El 25% de incumplimiento no lo causa la profundidad, luego el reset no lo arregla |

---

## H1 — "El KV cache crece y consume VRAM" · **REFUTADA**

### La medición

Barrido de prefill con muestreo de `nvidia-smi` cada 250 ms durante todo el procesado
(`cache_prompt:false`, prompts nuevos cada vez para forzar prefill real):

| Tokens de contexto | Pared (s) | VRAM mín (MiB) | VRAM máx (MiB) | Muestras |
|---|---|---|---|---|
| 2 944 | 1,28 | 13 168 | 13 168 | 5 |
| 11 688 | 4,22 | 13 168 | 13 168 | 15 |
| 46 919 | 19,01 | 13 168 | 13 176 | 66 |
| 93 963 | 44,00 | 13 155 | 13 173 | 152 |
| **187 874** | **112,33** | **13 155** | **13 155** | **388** |

Rango total observado en 626 muestras: **13 155 – 13 176 MiB**. Amplitud: **21 MiB (0,16%)** — y la
dirección es hacia abajo, o sea ruido de otras aplicaciones del escritorio, no del modelo.

### Por qué, estructuralmente

`llama-server` arrancó con `--ctx-size 200192 --parallel 1`. llama.cpp **reserva el KV completo del
contexto declarado en el momento de cargar el modelo**. El "contexto usado" es un puntero dentro de un
búfer ya pagado. Vaciarlo no devuelve nada al sistema; equivale a poner un índice a cero.

Geometría confirmada leyendo la cabecera GGUF del modelo:

```
qwen35.block_count            33
qwen35.full_attention_interval 4      <- solo 8 de 33 capas son atención plena
qwen35.attention.head_count_kv 4
qwen35.attention.key_length    256
qwen35.attention.value_length  256
qwen35.ssm.state_size          128    <- las otras 25 capas son SSM: estado CONSTANTE
```

→ KV = 8 capas × 4 cabezas × (256+256) × 2 B = **32 768 B/token = 32 KiB/token**
→ a 200 192 tokens = **6,11 GiB reservados de golpe al arrancar**.

Comprobación por contradicción de que llama.cpp respeta la hibridez: si reservara KV para las 33 capas
serían **25,20 GiB**, imposible en una GPU de 16 GiB. Como el servidor arrancó, la reserva es la híbrida.
(Esto es derivado, no medido con un reinicio del servidor — ver Limitaciones.)

### Entonces, ¿qué gana el reset? Las tres ganancias, cuantificadas por separado

**(a) VRAM: 0 MiB. Cero. Medido.** Único mando real sobre la VRAM: `--ctx-size` al arrancar.
Bajar de 200192 a 32768 libera **5,11 GiB** — y es un flag de arranque, no una conducta del agente.

**(b) Latencia de prefill: real y superlineal.** Ajuste por mínimos cuadrados sobre los 6 puntos:

```
t(n) = 0,33876·n + 1,3770e-6·n²   ms      (error del ajuste < 1,5% en todo el rango)
```

| n | t(n) medido |
|---|---|
| 4 000 | 1,38 s |
| 30 000 | 11,40 s |
| 100 000 | 47,65 s |
| 200 192 | 123,00 s |

El término cuadrático es el 29% del coste a 100k y el 45% a 200k. Es la única ganancia genuina del reset,
y llega tarde: **llenar la ventana ENTERA desde cero cuesta 2,05 minutos, una vez.**

**(c) Velocidad de generación: degradación pequeña.** 200 tokens generados a distintas profundidades:

| Contexto | tok/s de generación |
|---|---|
| 436 | 69,14 |
| 28 269 | 59,09 |
| 57 382 | 56,74 |

De 0 a 57k tokens: **−18% de velocidad de decode**. Molesto, no catastrófico.

**(d) Calidad: CERO ganancia. Medido, y es el resultado más importante del informe.** Ver H6.

### Y la ganancia negativa que el plan no contabiliza

El reset **destruye el cache de prefijo**, que es lo que hace barata la continuación. Medido:

| Situación | Tokens procesados | Tiempo |
|---|---|---|
| Prefijo de 28 188 tok, frío | 28 188 | **10,69 s** |
| Mismo prefijo, pregunta nueva al final | **517** | **0,28 s** |
| Después del reset, prefijo nuevo del mismo tamaño | 28 209 | **10,68 s** |

**El reset convierte un turno de 0,28 s en uno de 10,68 s. Factor 38,1×.** Cada lobotomía paga
íntegro un prefill que la continuación tenía gratis. Esto es coherente con el axioma del proyecto
"el contexto grande es un RELOJ": aquí el reloj lo pone el reset, no la ventana.

---

## H2 — "Multiagente con contextos destruidos ahorra VRAM" · **REFUTADA**

**Ahorro de VRAM: 0 MiB.** No hay ninguna interpretación en la que esto funcione en esta máquina:

1. **Un solo modelo cargado.** Los 5,38 GiB de pesos están residentes mientras `llama-server` viva.
   Ningún prompt los descarga. "Agente especializado" = otro texto de sistema = **los mismos pesos**.
2. **`--parallel 1`.** Hay **un** slot con **un** búfer KV de 6,11 GiB, ya reservado. Diez agentes
   comparten ese búfer por turnos. Destruir el contexto de un subagente devuelve **0 bytes**.
3. **Y encima cuesta.** Cambiar de agente = prefijo distinto = **cache miss total**. Medido arriba:
   10,68 s frente a 0,28 s. Un pipeline de 5 subagentes con contextos de 28k paga **~53 s solo en
   prefills** que un agente único no pagaría.

El único camino real al ahorro de VRAM con multiagente sería **modelos distintos cargados a la vez**
(p. ej. Qwythos-9B + Qwen3.8-27B), y en 16 GiB con 13,1 GiB ya ocupados **no caben**: quedan 2 883 MiB
libres. Con la flota actual, multiagente es una decisión de **arquitectura de prompt**, nunca de memoria.

**Lo que multiagente SÍ compra (y hay que decirlo con el nombre correcto):** *aislamiento de contexto*.
El ruido del subagente (12 ficheros abiertos, 3 comandos fallidos, warnings) no entra en la ventana del
principal. Eso es valioso y es la razón legítima para hacerlo. Pero **la unidad de ahorro es el token de
la ventana del padre, no el MiB de VRAM.** Y ese ahorro se paga a 10,68 s de re-prefill por cambio.

---

## H3 — "Un crítico separado del mismo modelo detectará las alucinaciones" · **REFUTADA**

### Experimento local (n = 103 juicios por variante, mismo modelo, sesión limpia por llamada)

60 multiplicaciones de 4×4 dígitos. Verdad absoluta = Python. El ejecutor acertó **28,3%** (17/60),
dejando 43 errores **reales, propios y no inducidos**. Luego un crítico del **mismo modelo** juzgó:
(A) los 43 errores propios del ejecutor, y (C) las 60 respuestas correctas.

| Variante del crítico | Detecta erróneas (TPR) | Acepta correctas (TNR) | **Exactitud balanceada** | s/juicio |
|---|---|---|---|---|
| "verificador **crítico y riguroso** cuya misión es detectar errores" | **43/43 = 1,000** | **2/60 = 0,033** | **0,517** | 0,13 |
| "¿Es cierto que...? Responde SI o NO" (neutro) | **2/43 = 0,047** | **60/60 = 1,000** | **0,523** | 0,27 |
| Neutro **con permiso de calcular** (400 tok de razonamiento) | 16/37 = 0,432 | 53/57 = 0,930 | **0,681** | **4,95** |

### Lo que esto significa, sin adornos

**El veredicto del crítico lo fija el adjetivo del system prompt, no el contenido de lo que juzga.**
Cambiar "crítico y riguroso" por una pregunta neutra mueve la detección de **1,000 a 0,047** — un vuelco
de 21× — mientras la exactitud balanceada se queda clavada en **0,52, es decir, el azar**.

El "1,000 de detección" de la primera fila es una **trampa mortal**: un crítico que dice NO a todo tiene
recall perfecto. Pero **rechaza el 96,7% del trabajo correcto**. Un agente autónomo con ese crítico en el
lazo no avanza jamás: se queda reescribiendo trabajo bueno hasta que se acabe el presupuesto. Y el crítico
neutro es peor de otra forma: **aprueba el 95,3% de los errores reales en silencio** — exactamente el
"vacío silencioso" que el proyecto ya tiene documentado como su modo de fallo típico.

Esto **replica en vivo** dos lecciones ya registradas del proyecto: *"el contrato interno está al nivel
del azar"* y *"cinco instrumentos aprobaron algo roto en una noche; ninguno falló"*.

### Lo único que funcionó, y su precio

Dejar calcular al crítico sube la exactitud balanceada a **0,681** — real, pero lejos de fiable — y
multiplica el coste por **38× (4,95 s frente a 0,13 s por juicio)**. Confirma el axioma del proyecto
*"el juez tiene que ejecutar"*: el crítico solo vale cuando **hace el trabajo**, no cuando **opina sobre él**.

### Literatura concordante

- **Los LLM no se autocorrigen sin retroalimentación externa**, y al intentarlo **empeoran**. La
  autocorrección solo funciona apoyada en fuentes externas: humano, calculadora, ejecutor de código, base
  de conocimiento. ([Huang et al., "LLMs Cannot Self-Correct Reasoning Yet"](https://arxiv.org/abs/2310.01798))
- **Sesgo de auto-preferencia**: los evaluadores LLM reconocen y prefieren sus propias generaciones; hay
  **correlación lineal entre capacidad de auto-reconocimiento e intensidad del sesgo**, y el mecanismo
  parece ser la **perplejidad** (premian lo que les resulta familiar — que es exactamente lo que ellos
  mismos producen). Rango del sesgo medido en ArenaHard: **−38% a +90%**.
  ([Panickssery et al., NeurIPS 2024](https://neurips.cc/virtual/2024/poster/96672))
- **FlipFlop**: basta con desafiar al modelo ("¿estás seguro?") para que su rendimiento **caiga**, con
  independencia de si tenía razón. ([arXiv:2311.08596](https://arxiv.org/pdf/2311.08596))

**Corolario duro:** un crítico del mismo modelo, mismo cuantizado y mismo servidor tiene sus errores
**correlacionados** con los del ejecutor por construcción — comparten pesos. La independencia estadística
que un verificador necesita **no existe**. La única señal no correlacionada disponible en esta máquina es
**la ejecución**: tests, compilador, `assert`, diff, exit code.

---

## H4 — "Los snapshots inmutables evitan la degradación acumulativa" · **REFUTADA**

24 restricciones con identificadores únicos (R01–R24). Dos brazos, 8 ciclos cada uno. El conteo de
supervivientes es mecánico (regex sobre los IDs), no un juicio.

### Brazo A — compresión en cascada (lo que el plan quiere evitar): colapsa en UN paso

| Ciclo | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Restricciones supervivientes | **2** | 2 | 2 | 2 | 2 | 2 | 2 | 2 |

De 24 a 2 en la **primera** compresión: **se destruyó el 91,7% de golpe**. El dueño acierta en que la
cascada es venenosa, pero **se equivoca en el modelo mental**: no es una erosión gradual a lo largo de
cientos de ciclos, es un **acantilado en el primer resumen**.

Y hay algo peor. A partir del ciclo 3 la salida es **byte a byte idéntica** (950 chars, luego 1336 chars,
repetidos): la cascada converge a un **punto fijo**. El agente parece sanísimo — produce un estado
estable, coherente, bien redactado, ciclo tras ciclo — y ese estado contiene el **8% de su contrato**.
Nadie emite un error. Es el vacío silencioso en su forma más peligrosa: **un estado estable y equivocado
es indistinguible de un estado estable y correcto desde fuera.**

### Brazo B — almacén inmutable + selección (la propuesta del dueño): la pérdida se muda, no desaparece

Las 24 restricciones **nunca se modifican**. Cada ciclo el modelo elige cuáles cargar para su subtarea.

| Ciclo | Subtarea | Restricciones críticas | Cargadas |
|---|---|---|---|
| 1 | preparar rama y entorno | R01, R15 | R01 |
| 2 | cambiar el esquema de pagos | R02, R09, R14, R19 | R02 |
| 3 | cliente HTTP al proveedor | R07, R10, R16 | **R07, R10, R16** ✔ |
| 4 | guardar importes y fechas | **R12**, R13 | R13 |
| 5 | logging y manejo de errores | R24, R06 | **R24, R06** ✔ |
| 6 | **escribir los tests** | **R04, R21** | **— (ninguna)** |
| 7 | preparar el despliegue | R20, R17 | **— (ninguna)** |
| 8 | rendimiento y cache | R22, R23 | **R22, R23** ✔ |

**Recall de restricciones críticas: 10/19 = 0,526.** Una moneda al aire.

Los casos concretos son escalofriantes:

- **Ciclo 4, "guardar importes":** cargó R13 (fechas en UTC) y **NO cargó R12 ("no usar float para dinero;
  usar Decimal")**. En una migración de **pagos**. La restricción que existe precisamente para ese ciclo.
- **Ciclo 6, "escribir los tests":** cargó R06 (rotación de logs) y R11 (docstrings), y **no cargó ni R04
  ("los tests de red con mock, nunca contra producción") ni R21 ("cada endpoint nuevo exige test de
  contrato")** — las dos únicas restricciones que hablan de tests, en el ciclo de tests.
- **9 de 24 restricciones no se cargaron NUNCA** en 8 ciclos: R04, R05, R09, R12, R14, R15, R18, R19, R21.
  Incluye "prohibido construir SQL por concatenación" (R18) y "el usuario de BD no tiene permiso DROP" (R19)
  durante un ciclo de cambio de esquema.

**Colapso del selector:** los ciclos 5, 6 y 7 eligieron conjuntos casi idénticos (R06, R11, R16, R23, R24)
**pese a ser subtareas completamente distintas**. El selector converge a un atractor de restricciones
genéricas y deja de responder a la tarea — el mismo punto fijo del brazo A, un piso más arriba.

### Dónde entra la deriva, en una frase

> **La inmutabilidad protege los BITS, no la RELEVANCIA.** El canal de pérdida se traslada del `write` al
> `read`: cada ciclo el estado siguiente se condiciona **solo sobre lo que se seleccionó**, así que lo no
> seleccionado deja de generar razones para ser seleccionado. Es **inanición realimentada**: el olvido no
> se registra en ningún sitio porque el dato sigue ahí, intacto, en el disco. Auditas el almacén, está
> perfecto, y el agente lleva 40 ciclos sin verlo.

Un almacén inmutable con recall 0,53 es **peor** que una cascada honesta, porque la cascada al menos
**parece** haber perdido algo.

---

## H5 — "Comprimir con el LLM antes del reset es barato" · **DUDOSA** (depende de una frecuencia que el plan no fija)

Coste de una compactación de 30 000 tokens, con los números de esta máquina:

```
prefill 30 000 tok            = 11,40 s   (del ajuste, error <1,5%)
generar resumen ~300 tok @59  =  5,08 s
                              ─────────
                                16,49 s por compactación
```

Y hay que sumar lo que **no** se ve: el re-prefill del contexto reconstruido tras el reset
(4k de snapshots = **1,38 s**), y sobre todo el cache de prefijo tirado a la basura (**10,68 s → 0,28 s
perdidos por turno**, factor 38,1×).

**Cuántas veces al día:** el plan dice "ciclo 1 → compresión → reset → ciclo 2", lo que sugiere **por
ciclo**. Ahí está el error.

| Frecuencia | Coste diario | Juicio |
|---|---|---|
| **72/día** (una por ventana llena, ~cada 20 min de trabajo real) | **19,8 min/día** | Aceptable |
| **500/día** (una por ciclo corto de agente) | **137,4 min/día = 2 h 17 min** | **Ruinoso** |

Para poner los 19,8 min en perspectiva: **llenar la ventana entera de 200 192 tokens desde cero cuesta
123,00 s = 2,05 minutos, una sola vez.** Se está construyendo una maquinaria de memoria jerárquica,
snapshots y agente crítico para ahorrar una operación de **dos minutos**.

**Veredicto: barato si y solo si se compacta por SATURACIÓN DE VENTANA, no por ciclo.** El plan tal como
está escrito compacta por ciclo, y a esa frecuencia el coste se come **2 horas de cada día** de un agente
que se supone que trabaja días.

---

## H6 — "Mantener un contrato estable durante cientos de ciclos" · el problema es REAL, la causa NO es el contexto

Este es el resultado que reordena todo el plan. Medí **dos cosas distintas** que el plan confunde en una.

### (a) Recall declarativo de restricciones vs profundidad: **perfecto en toda la ventana**

24 restricciones al principio del prompt, luego ruido de relleno, luego 10 preguntas sonda cuya respuesta
correcta exige una restricción concreta:

| Profundidad | Tokens reales | Recall | 1ª llamada | 10 sondas |
|---|---|---|---|---|
| ~0,4k | 454 | **10/10** | 0,68 s | 5,6 s |
| ~8k | 7 386 | **10/10** | 2,92 s | 9,0 s |
| ~32k | 28 022 | **10/10** | 11,00 s | 16,9 s |
| ~64k | 55 830 | **10/10** | 23,64 s | 31,8 s |
| **~128k** | **111 406** | **10/10** | 55,24 s | 64,9 s |

**Recall 1,00 a 111 406 tokens.** Cero degradación. Lo único que se degradó fue **el reloj**: de 5,6 s a
64,9 s para el mismo trabajo (11,6×).

Compárese con lo que el plan propone para sustituir a esto:

| Método | Recall de restricciones |
|---|---|
| **No hacer nada — dejarlas en la ventana a 111k tokens** | **1,000** |
| Selección desde almacén inmutable (H4-B) | 0,526 |
| Compresión en cascada (H4-A) | 0,083 (2/24) |

> **La maquinaria de auto-lobotomía empeora en un factor de 2× a 12× exactamente aquello que dice
> proteger, para ahorrar una VRAM que no se ahorra.**

### (b) Adherencia conductual (escribir código respetando las reglas): **real pero PLANA con la profundidad**

n=4 muestras por profundidad, 6 restricciones verificadas mecánicamente sobre el código generado:

| Profundidad | R07 httpx | R12 Decimal | R10 timeout=30 | R13 UTC | R11 docstring | R24 stack | **Global** |
|---|---|---|---|---|---|---|---|
| ~0,4k | 4/4 | 4/4 | 2/4 | 4/4 | 4/4 | **0/4** | **0,750** |
| ~32k | 4/4 | 4/4 | **0/4** | 4/4 | 4/4 | 1/4 | **0,708** |
| ~128k | 4/4 | 4/4 | 2/4 | 4/4 | 4/4 | **0/4** | **0,750** |

Dos hechos:

1. **Hay un 25-29% de incumplimiento real.** El contrato SÍ se rompe. H6 tiene razón en el síntoma.
2. **No depende de la profundidad en absoluto** (0,750 → 0,708 → 0,750 entre 0,4k y 128k tokens). El
   incumplimiento es **por restricción**, no por posición: R24 (registrar el stack) se incumple
   **11 de 12 veces a cualquier profundidad**; R10 (timeout=30) **8 de 12**. Las otras cuatro se cumplen
   **12/12 siempre**.

**Conclusión demoledora para el plan:** el modelo **recita** R24 perfectamente (recall declarativo 10/10 a
128k) y **la incumple** al escribir código (0/4 a 0,4k tokens, con la restricción a 400 tokens de
distancia). Esto es la disociación entre **recall declarativo y adherencia conductual** que la literatura
ya documenta: *"models can restate constraints they violate"*
([arXiv:2604.28031](https://arxiv.org/html/2604.28031)).

> **Si el fallo del contrato ocurre igual con el contexto vacío que con 128k tokens, entonces vaciar el
> contexto no puede arreglarlo. El reset ataca un mecanismo que no es la causa.**

### Lo que sí dice la literatura sobre agentes largos sin humano

- **Vida media constante**: la tasa de éxito decae **exponencialmente** con la duración de la tarea; cada
  agente tiene su "half-life". Duplicar la duración **cuadruplica** la tasa de fallo.
  ([Is there a half-life for the success rates of AI agents?](https://arxiv.org/pdf/2505.05115))
- **METR**: los modelos frontera aciertan casi el 100% en tareas de <4 min de humano y **<10% en tareas de
  >4 h**. ([METR, Task-Completion Time Horizons](https://metr.org/time-horizons/))
- **Precisión ≈ 0 más allá de ~120 pasos**; el error por paso crece como `ε(t) = ε₀ + α·log t`.
- **"Lost in Conversation"**: **−39% de rendimiento y −112% de fiabilidad** en multi-turno frente al
  mismo problema en un solo turno. ([openreview VKGTGGcwl6](https://openreview.net/forum?id=VKGTGGcwl6))

**Traducción para este plan:** la ambición "horas o días" choca con una decadencia exponencial que **no
tiene nada que ver con la ventana de contexto**. Un 9B cuantizado a Q4_K con 25-29% de incumplimiento por
paso no aguanta cientos de ciclos **con ninguna arquitectura de memoria**. Con una tasa de fallo por paso
de 0,25, la probabilidad de 100 pasos limpios es 0,75¹⁰⁰ ≈ **3·10⁻¹³**.

---

## Otras suposiciones del encargo que también son falsas

**S1. "Ventana corta".** El servidor está sirviendo **200 192 tokens** y el modelo declara
`context_length: 1048576`. **No hay ninguna ventana corta que compensar.** Todo el plan se justifica sobre
una escasez que en esta máquina no existe. La ventana solo es corta si el dueño baja `--ctx-size`, y la
única razón para bajarlo es… liberar VRAM — la premisa ya refutada. **Es circular.**

**S2. "Charla descartable".** Falso y peligroso. Los comandos que **fallaron** son la información más
cara del ciclo: son la única señal no correlacionada con el modelo que el sistema posee (H3). Un
compresor que tira "ruido de trazas y warnings" tira los **anticuerpos** y garantiza que el agente repita
el mismo error en el ciclo siguiente sin memoria de haberlo cometido.

**S3. "Provenance y confianza resuelven la alucinación".** La confianza la tendría que emitir **el mismo
modelo**, y H3 muestra que su emisión de confianza es un **artefacto del prompt** (1,000 vs 0,047 según el
adjetivo). Etiquetar cada hecho con `confianza: 0.9` produce **hechos falsos con una etiqueta que los
hace más creíbles**. Es una superficie de fallo nueva, no una defensa. La provenance sí sirve — pero solo
la que apunta a algo **verificable** (fichero:línea, exit code, salida de test), nunca a "lo dijo el ciclo 7".

**S4. "VRAM aproximadamente constante" como objetivo de diseño.** Ya es exactamente constante y sin hacer
nada: 13 155–13 176 MiB en 626 muestras. **Es un objetivo ya cumplido por el arranque del servidor.**

**S5. "Un slot es suficiente para multiagente".** Con `--parallel 1` los agentes **no son concurrentes**:
se serializan, y cada cambio de agente invalida el cache de prefijo (10,68 s). El "multiagente" del plan
es en realidad **un agente con amnesia inducida por turnos**, y cada turno cuesta un prefill completo.

**S6. Falta el criterio de PARADA.** Ni una palabra sobre cómo el agente decide que terminó, que está
atascado, o que el trabajo se torció. Con H3 refutado, **no hay ningún juez fiable dentro del sistema**.
Un agente de días sin criterio de parada verificable no es autónomo: es un bucle caro. La lección
"presupuesto por PROGRESO verificado" del propio proyecto (87,9% del tiempo ahorrado, 0 falsas alarmas)
existe precisamente para esto y el plan la ignora.

---

## Qué salva la idea

El instinto del dueño no es tonto — está apuntando al problema correcto (los agentes largos se degradan)
con el mecanismo equivocado (la VRAM y el vaciado de contexto). Esto es lo que la evidencia de arriba
respalda, en orden de retorno:

**1. Mata la premisa de VRAM y quédate con la de LATENCIA.** Si quieres VRAM, el mando es
`--ctx-size` al arrancar (32768 libera **5,11 GiB**), no la conducta del agente. Si quieres velocidad, el
mando es no arrastrar 100k tokens innecesarios — pero la cuenta es 47,65 s de prefill, no MiB.

**2. Compacta por SATURACIÓN, no por ciclo.** Umbral en tokens (p. ej. 70% de 200192 ≈ 140k), no
"cada ciclo". 19,8 min/día en vez de 137. La literatura respalda el disparo por señal medida:
**ERGO** dispara la consolidación cuando detecta un **pico de entropía**, y obtiene **+56,6% de
rendimiento medio, +24,7% de capacidad pico y −35,3% de variabilidad**
([arXiv:2510.14077](https://arxiv.org/pdf/2510.14077)). El disparador es una medición, no un calendario.

**3. Nunca comprimas el contrato. RE-EMÍTELO.** ERGO no resume: hace *prompt consolidation* — reinyecta la
instrucción entera. Tus 24 restricciones son **~400 tokens = 0,17 s de prefill**. Contra: cascada 0,083,
selección 0,526, **literal 1,000**. **La capa permanente se copia verbatim, sin LLM en medio, y no se
selecciona nunca.** Solo se comprime lo episódico. Esto elimina el 92% de la pérdida de H4-A y el 47% de
la de H4-B de un plumazo, y cuesta menos de dos décimas de segundo.

**4. El crítico tiene que EJECUTAR, no opinar.** Con exactitud balanceada 0,517/0,523 (azar), un crítico
que lee y juzga es peor que nada: o bloquea el 96,7% del trabajo bueno o aprueba el 95,3% de los errores.
Las señales que sí son independientes del modelo: **exit code, tests, compilador, diff, assert, linter**.
Si el crítico ha de ser un LLM, dale herramientas y obligale a ejecutar (0,681, el único número que sube),
y **presupuéstalo**: cuesta 4,95 s por juicio, 38× más que opinar. Un modelo de **otra familia**
(no Qwen) rompería la correlación de errores mejor que otro prompt sobre los mismos pesos — la lección
"Cognia era mono-familia" ya avisó de esto.

**5. Ataca la deriva conductual donde ocurre: en el punto de escritura.** R24 se incumple 11/12 veces con
la restricción a 400 tokens de distancia. Eso no lo arregla ninguna arquitectura de memoria — lo arregla
un **chequeo mecánico post-generación** (grep de `exc_info|traceback`, del `timeout=30`) que rebota el
código. Es determinista, cuesta microsegundos, y no tiene 0,52 de exactitud balanceada.

**6. Instrumenta el punto fijo.** El fallo más peligroso que encontré es que la cascada converge a una
salida **byte a byte idéntica** conservando el 8% del contrato, y **parece sana**. Cualquier sistema que
se construya necesita un chequeo que corra al arrancar cada ciclo: *"¿cuántas de mis N restricciones
permanentes están literalmente presentes en mi contexto?"*. Si no es N, aborta. Es una línea de código y
convierte la lección en un gate — porque, como ya está escrito en este proyecto, *una lección en prosa no
impide nada*.

---

## Limitaciones honestas de esta falsación

- **KV de 6,11 GiB es DERIVADO** de la geometría GGUF, no medido reiniciando el servidor con otro
  `--ctx-size` (habría tumbado el backend en producción). Lo **medido** y suficiente para refutar H1 es
  que la VRAM **no varía** con la longitud del contexto (626 muestras, amplitud 21 MiB).
- **H3 se midió sobre aritmética**, donde la verdad es computable. Es un dominio con verdad nítida; las
  alucinaciones de texto libre son más difusas. Lo que traslada es el **vuelco de 1,000 a 0,047 por
  cambiar un adjetivo**, que es una propiedad del juez, no de la aritmética.
- **H4 usa restricciones sintéticas con IDs** para que el conteo sea mecánico. Restricciones en prosa sin
  identificador probablemente sobrevivan **peor**, no mejor.
- **La adherencia conductual es n=4 por profundidad** (12 muestras totales por restricción). Suficiente
  para ver que la curva es plana y que R24 falla 11/12; insuficiente para un intervalo de confianza
  estrecho sobre el 0,75 global.
- **Un solo modelo (Qwythos-9B Q4_K).** No probé Qwen3.8-27B; con ~32k de contexto práctico, H1 sigue
  siendo estructuralmente idéntica (el KV se reserva igual) pero los números de latencia cambian.

## Reproducción

Scripts y datos crudos en `C:\Users\usuario\Desktop\cognia_v2\planes\agente_largo\exp\`
(`exp.py` H1/VRAM+prefill · `exp2.py` decode+cache · `exp3b.py`/`exp3c.py` H3 · `exp4.py` H4 ·
`exp5.py` recall@profundidad · `exp6.py` adherencia conductual · `gguf2.py` geometría KV;
JSON con las salidas: `e1 h3b h3c h4 h5 h6`).
Todos contra `http://127.0.0.1:8080/completion` con `venv312\Scripts\python.exe`, sin dependencias
externas salvo `numpy` para el ajuste.

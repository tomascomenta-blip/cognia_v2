# PREREG — Ganarse (o no) el derecho a comparar con una tabla publicada

**Escrito el 2026-07-31 a las 06:10, ANTES de generar una sola muestra de este
experimento.** Banco: LiveCodeBench. Modelo: gpt-oss-20b (16 GB).

---

## 1. El problema, que es del GOAL y no del banco

El goal es **"igualar a un modelo grande desde 16 GB"**. Anoche medí
`pass@1 = 51.8%` en LiveCodeBench y **me prohibí compararlo con ninguna tabla
publicada**, con razón: el prompt, el evaluador y el cap de tests eran míos
(enmiendas 1.8 y 2 del `PREREG_BANCO_CODIGO_20260730`).

Una prohibición así no se levanta escribiendo que ya no aplica. Se levanta
**replicando las condiciones**, o **declarando que no se pueden replicar**.

## 2. Las condiciones OFICIALES, verificadas en red (no de memoria)

Leídas hoy del repo de LiveCodeBench (`lcb_runner/prompts/code_generation.py`,
`evaluation/compute_code_generation_metrics.py`):

- **SYSTEM:** *"You are an expert Python programmer. You will be given a
  question (problem specification) and will generate a correct Python program
  that matches the specification and passes all tests."*
- **USER:** `### Question:` + enunciado + `### Format:` (dos variantes, según
  haya `starter_code` o sea stdin) + ``` ### Answer: (use the provided format
  with backticks)```.
- **JUEZ:** **TODOS** los casos (públicos + privados), sin cap de número ni de
  tamaño; `timeout = (6+1)·n_casos + 5` segundos para la muestra entera; pasa
  solo si pasan **todos**.

## 3. La referencia publicada, con sus límites por delante

La única cifra que he encontrado para este modelo en este banco:

> **gpt-oss-20b, pass@1 = 70 en LCB v6, ventana 2024-08-01 → 2025-01-31, 3
> muestras por problema, reasoning HIGH, 64k de secuencia**
> — `blog.collinear.ai/p/gpt-oss-lcb`

**Lo que esa referencia NO es:** no es una entrada del leaderboard oficial, no
declara temperatura, y **el model card de OpenAI (arXiv:2508.10925) no trae
ninguna cifra de LiveCodeBench** — comprobado hoy, no supuesto. Es la mejor
referencia que existe, no una buena referencia, y así se reportará.

**Solape con mi banco, MEDIDO** (`b3_ventana.py`, no declarado):

| | tareas | dentro de la ventana de la referencia |
|---|---|---|
| `test6` solo (el de anoche) | 175 | **44 (25.1%)** |
| banco AMPLIADO | 342 | **211 (61.7%)**, ventana real 2024-09-22 → 2025-01-26 |

**Mi banco NO cubre 2024-08-01 → 2024-09-21.** Es una diferencia residual real
y se declara; no se disimula restringiendo la referencia.

## 4. Las CUATRO diferencias, y el diseño que las separa

Mi `51.8%` y su `70` difieren en cuatro cosas a la vez. Comparar sin separarlas
no dice nada. El diseño es un **factorial 2×2 en generación, leído con DOS
evaluadores**:

| eje | mi condición | la oficial / la de la referencia |
|---|---|---|
| **PROMPT** | el mío (*"Return ONLY a Python code block"*) | el template `### Question/Format/Answer` |
| **ESFUERZO** | `reasoning_effort = low` | `high` |
| **EVALUADOR** | 5 visibles / 15 ocultos, entradas ≤100 KB | todos los casos, sin cap |
| **VENTANA** | 2024-09-22 → 2025-04-06 | 2024-08-01 → 2025-01-31 |

- Los ejes **PROMPT** y **ESFUERZO** son las 4 celdas de generación.
- El eje **EVALUADOR** es **gratis y perfectamente apareado**: las mismas
  muestras se juzgan con los dos jueces.
- El eje **VENTANA** se cierra restringiendo el banco al **solape medido**
  (211 tareas), y la parte no cubierta se declara.

**N = 60 tareas** sorteadas del solape con semilla `20260731`, **k = 1**.
**Las cuatro celdas se generan INTERCALADAS a nivel tarea** (las 4 de una tarea
antes de pasar a la siguiente): si el reloj corta, el diseño queda **balanceado**
en vez de sesgado hacia la última celda. `N_min = 35` tareas completas para
emitir cualquier lectura.

## 5. Lo que se decide, y lo que NO

Esto **no es un gate con KILL**: es una MEDICIÓN de atribución. Lo único
pre-registrado como decisión es **el derecho a comparar**:

> Solo se pondrá un número mío al lado del `70` publicado si sale de la celda
> **(prompt oficial, esfuerzo high, evaluador oficial, ventana del solape)**, y
> la frase que lo haga **tiene que enumerar en la misma línea las diferencias
> residuales**: mi banco no cubre 2024-08-01→09-21, yo mido k=1 y la referencia
> promedia 3 muestras, la referencia no declara temperatura y yo uso 0.8, y su
> contexto era 64k contra mis 16k.
>
> **Si esa celda no llega a correrse, no se compara**, y se dice que no se
> comparó. Ninguna de las otras tres celdas gana ese derecho.

**Lecturas secundarias (descriptivas, no ganan el derecho a comparar):** el
efecto de cada eje por separado — cuánto del hueco es el PROMPT, cuánto el
ESFUERZO y cuánto el EVALUADOR. Es lo que hace interpretable cualquier número,
mío o suyo.

## 6. Amenazas declaradas, con su control

1. **`reasoning_effort=high` come contexto.** `n_ctx = 16384` y el prompt
   oficial ocupa ~700 tokens, así que quedan ~15k para pensar + responder. Se
   fija `max_tokens = 15000` en las celdas `high`. **`finish_reason='length'`
   se cuenta como INSTRUMENTO, nunca como fallo del modelo** — es el 8º caso
   del mismo bug en este repo y la referencia usaba 64k, cuatro veces mi
   contexto. Si la tasa de truncado en `high` supera el 15%, la celda se
   reporta como **no concluyente por contexto**, no como un pass@1 bajo.
2. **El esfuerzo REAL se fija por `chat_template_kwargs.reasoning_effort`**, no
   por una línea "Reasoning: high" en el system (medido 3/3: la línea del
   system NO hace nada). Se verifica con una sonda antes de la corrida:
   `high` tiene que producir visiblemente más tokens de pensamiento que `low`.
3. **Los públicos están impresos en el enunciado (77.1%).** Para el juez
   oficial eso es correcto y así se hace. **Pero invalida los públicos como
   examen de un SELECTOR**, así que en estas condiciones el BoN se queda sin
   examen limpio — y eso es un hallazgo, no un defecto del montaje. No se
   reporta ningún BoN sobre públicos como si fuera el BoN de anoche.
4. **El juez oficial es CARO** (sin cap: hay entradas de hasta 19 MB). Se corta
   al primer fallo, que da **exactamente el mismo veredicto** con un AND, y se
   registra `lote_expirado` aparte para no facturarle al modelo un timeout del
   instrumento.

## 7. Orden de ejecución, por si el reloj corta

1. **Sonda de esfuerzo** (2 muestras): confirmar que `high` cambia algo.
2. **Factorial 2×2, k=1, intercalado** — es lo que da la atribución.
3. **Solo si quedan ≥45 min:** celda de BoN en condiciones oficiales (k=4,
   selector = públicos), etiquetada con la amenaza 3 en la misma frase.

---

## ENMIENDAS

*(se appendean con fecha y hora; nunca se edita lo de arriba)*

### ENMIENDA 3 (2026-07-31 10:12) — la celda `high` NO es medible en esta máquina, y ese ES el resultado

Con el contexto ya subido a 32.768 y `max_tokens = 30.000`, la celda
`oficial_high` **siguió truncando el 60% de las muestras (3 de 5)**, a **205,8
segundos por muestra**. Desglose medido por celda:

| celda | truncadas | s/muestra | chars de respuesta |
|---|---|---|---|
| `mio_low` | **0/6 (0%)** | 8,2 | 664 |
| `oficial_low` | **0/6 (0%)** | 11,0 | 1.296 |
| **`oficial_high`** | **3/5 (60%)** | **205,8** | 304 |

**A esfuerzo `high`, gpt-oss-20b se pasa de 30.000 tokens de pensamiento en la
mayoría de los problemas `hard` de LiveCodeBench.** Con el 60% truncado la
celda no mide capacidad: mide mi cap. Y a 206 s/muestra tampoco cabe en el
reloj.

**Decisión, tomada antes de mirar ninguna comparación:** se cae la celda
`oficial_high` de la corrida principal, que pasa a **dos celdas**
(`mio_low`, `oficial_low`) — el eje PROMPT con N grande y barato. Y **el muro
se mide aparte y a propósito**, porque es una respuesta al goal y no un
estorbo:

1. ¿Cabe `n_ctx = 65536` (el contexto de la referencia) en 16 GB? Se **mide**,
   no se extrapola desde el +400 MiB que costó pasar de 16k a 32k.
2. ¿Cuánto trunca `high` con el presupuesto de la referencia? Sonda dedicada.

> **Consecuencia para el derecho a comparar: NO se compara.** La celda que lo
> concedía no se puede medir aquí en condiciones honestas, y el prereg ya decía
> qué hacer entonces: *"Si esa celda no llega a correrse, no se compara, y se
> dice que no se comparó."* Lo que se entrega en su lugar es **por qué** no se
> puede, con números.

### ENMIENDA 2 (2026-07-31 09:50) — el 8º caso de "presupuesto de pensamiento", y el rediseño que obliga

**La amenaza 1 se disparó, medida en corrida:** con `max_tokens = 15000` sobre
`n_ctx = 16384`, las celdas `high` **truncaron el 33.3%** de las muestras —muy
por encima del 15% que las declara no concluyentes—, porque con esfuerzo alto
el modelo piensa más de 15.000 tokens. Es el **8º caso** del mismo bug en este
repo, y aquí habría hecho que `high` pareciera peor de lo que es **por el cap,
no por el modelo**. La referencia usaba **64k**.

**Y la restricción de 16 GB resultó no ser la que yo daba por hecha:** medido,
`gpt-oss-20b` con **`n_ctx = 32768`** ocupa **12.819 MiB de 16.311**, apenas
**+400 MiB** sobre la configuración de 16k. **Cabe.** Se sube el contexto a
32.768 y `max_tokens` a **30.000**. *(Sigue siendo la mitad de los 64k de la
referencia, y eso se declara.)*

**Rediseño por RELOJ, escrito antes de que hubiera ninguna lectura.** Con
cuatro celdas el ritmo medido era **4,3 min/tarea** ⇒ ~30 tareas en la ventana,
**por debajo del `N_min = 35`** que necesita justo **la celda que da el derecho
a comparar**. Se cae la celda **`(mío, high)`**, que es la única que no
alimenta ninguna pregunta del prereg:

| eje | cómo queda |
|---|---|
| **PROMPT** | `mío_low` vs `oficial_low` — a esfuerzo bajo, que es donde es barato |
| **ESFUERZO** | `oficial_low` vs `oficial_high` — con el prompt oficial, que es el que importa |
| **EVALUADOR** | ya medido aparte, sin GPU: **−2.7 pts** |
| **la celda comparable** | `(oficial, high, juez oficial)` — **es la que se protege** |

Lo que se pierde y se dice: **no habrá interacción prompt×esfuerzo**. Si el
efecto del prompt fuera distinto a esfuerzo alto, este diseño no lo vería.

### ENMIENDA 1 (2026-07-31 06:31) — la sonda de esfuerzo, PASADA

Amenaza 2 cerrada con número. `b3_factorial.py --sonda` sobre una tarea real:

| esfuerzo | segundos | chars de respuesta | código |
|---|---|---|---|
| `low` | **8.6** | 602 | sí |
| `high` | **36.2** | 379 | sí |

**`high` tarda 4.2× más y devuelve MENOS texto**: los tokens extra se van al
razonamiento, que es exactamente lo que tiene que pasar. El knob
`chat_template_kwargs.reasoning_effort` **sí actúa** (a diferencia de la línea
`"Reasoning: high"` en el system, que en este repo está medida como inerte 3/3).

**Consecuencia para el reloj, declarada aquí:** las dos celdas `high` cuestan
~4× las `low`. Con 60 tareas eso son ~100 minutos para el factorial entero. Si
el reloj no llega, el corte deja el diseño **balanceado** porque las cuatro
celdas se generan intercaladas por tarea.

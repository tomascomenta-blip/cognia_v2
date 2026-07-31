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

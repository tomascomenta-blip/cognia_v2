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

### ENMIENDA 7 (2026-07-31 23:05) — lo que la revisión adversarial tumbó de la enmienda 6, ANTES de gastar

Dos revisores + refutadores: 3 BLOQUEA confirmados, 8 avisos. Correcciones
pre-registradas ANTES de generar nada en la celda XL:

1. **Sin semilla de sampling, un pase en XL puede ser RE-SORTEO, no
   presupuesto** (`genera()` no pasa seed; el `--semilla` solo baraja tareas;
   la frase "semilla y split idénticos" de la enmienda 6 era prosa que no
   correspondía al sampling — se retira). Contraejemplo EN DISCO: de las 12
   truncadas, **3 pasan en `low2`** (3634, 3721 con 640 tokens, abc378_f).
   **Lectura (1) re-definida:** una tarea cuenta como *resuelta POR
   PRESUPUESTO* solo si su muestra XL **pasa Y `tok_salida` > 60000**; si
   pasa con ≤60000 es *re-sorteo* y va en estrato aparte. La frase
   *"convierte la cota 83.3% en MEDIDA"* queda RETIRADA: la cota no se
   convierte, se acota mejor.
2. **La compuesta `pass@1_36_XL`** se precisa: juez = **oficial-con-mis-topes**
   (el del 83.3% citado); si el corte de reloj deja tareas de las 12 sin
   muestra XL, quedan en fallo y la compuesta se etiqueta "x/12
   re-corridas"; el registro de 3720 (`respuesta_vacia`, no truncada) queda
   entre las 24 como está y SE DECLARA. El **ratchet estructural** se
   declara: la compuesta solo puede subir desde 50.0% porque solo se
   re-corren fallos; la etiqueta **NO COMPARABLE viaja pegada al número**
   cada vez que se escriba (que 36≥35 no invite al pattern-match con el §5).
3. **El re-juicio de grandes** (`b3_rejuzga_grandes.py`) se corrigió: cubre
   TODAS las celdas de la noche (incl. `mio_low`, `low198`, `highxl` y el
   raw de las 138), las entradas no-rejuzgables se reintentan, y el control
   pasa a **2 pasa + 1 falla obligatorios** (aborta si <3). El estrato se
   reporta como **PARCIALMENTE resuelto**: abc377_e (87.9 MB) supera también
   el tope XL de 64 MB, y los `lote_expirado` pueden volver a expirar a
   7n+5. **Se corre AL FINAL, nunca en paralelo con corridas GPU** (la
   contención escribiría timeouts espurios en ficheros primarios).
4. **Orden y reloj:** `low198` PRIMERO (~30-45 min, alimenta la primaria de
   la enmienda 3 del diseño frontier, con `--solo-tareas` las 138 — sin él
   se regenerarían las 60 firmadas creando un brazo duplicado); la XL
   después con `--minutos` ajustado al reloj restante (el fin real puede
   exceder el corte en ~1 h: pared 3600 + juicio). `solo_tareas` se
   persiste y se valida al reanudar. **Declarado además** (residuo del
   BLOQUEA refutado): el `oficial_low` de las 60 corrió a max_tokens=15000
   con el backend viejo; medido con `low2` que el efecto corrida+config es
   ±1 tarea/36 — el neto por lote se reporta al lado del pool de 198.

### ENMIENDA 6 (2026-07-31 22:15) — la celda XL: presupuesto de pensamiento POR ENCIMA de la referencia

**Escrita ANTES de generar nada en esta celda, con el eje ya cerrado.** El
resultado de la noche dice que el 33% de las muestras `high` se pasa de
60.000 tokens y que el presupuesto —no el knob— es lo que come el hueco. La
pregunta nueva, que ya NO es replicar la referencia sino medir el TECHO del
modelo: **¿cuántas de las 12 tareas truncadas resuelve el 20B si se le da
sitio para pensar?**

- **Celda `oficial_high` XL** en fichero aparte (`factorial_highxl.json`):
  SOLO las tareas cuyo registro en `factorial_high2.json` es
  `truncado_por_longitud` (12 tareas — las únicas donde el presupuesto ata).
  `max_tokens = 110000`, pared 3600 s, `COGNIA_TIMEOUT_HTTP=3600`, `n_ctx`
  el mayor que QUEPA medido en `/props` + VRAM antes de correr (131072 si
  entra; si no, 98304 — se registra el medido). Temperatura 0.8, semilla y
  split idénticos.
- **Lecturas pre-registradas:** (1) tasa de resolución de las 12 con
  presupuesto XL (el número que convierte la "cota superior real" 83.3% de
  la celda comparable en MEDIDA o la desmiente); (2) la compuesta
  `pass@1_36_XL` = aciertos de las 24 no-truncadas a 60k + aciertos de las
  12 con XL, **etiquetada NO COMPARABLE con el 70** (presupuesto y contexto
  por encima de la referencia — es el techo del modelo, no la réplica);
  (3) tokens de pensamiento reales de las que resuelvan y de las que vuelvan
  a truncar (¿hay un segundo muro a 110k?).
- **Instrumento:** el preflight del runner exige hoy `n_ctx==65536` para
  celdas high; se parametriza (`--ctx-exigido`) manteniendo el default
  actual — el cambio pasa por la suite y por revisión antes de gastar.
- **Corte por reloj 240 min** (12 × ~18 min ≈ 3.6 h el peor caso). Si el
  reloj corta, el prefijo de tareas completas se analiza igual (las 12 van
  en el orden del fichero high2).

### ENMIENDA 5 (2026-07-31 19:30) — lo que tumbó la revisión adversarial de la enmienda 4, ANTES de la muestra 10

Tres revisores (diseño, instrumento, honestidad) + refutación adversarial por
BLOQUEA: **9 confirmados que convergen en 4 temas**, varios reproducidos en
sandbox por los refutadores y el primero por mí. Todo arreglado ANTES de
gastar GPU.

**1. Las condiciones "obligatorias" eran PROSA.** El runner no comprobaba ni
`/props` ni `COGNIA_TIMEOUT_HTTP` (default 300 silencioso = la capa 3
reentrando), y un backend a ctx corto habría producido `truncado_por_longitud`
FALSO, indistinguible del real en el fichero. Arreglo (verificado ejecutando
los dos abortos): `preflight()` en `b3_factorial.py` aborta si el backend no
responde, si `total_slots != 1`, si hay celdas high y `n_ctx != 65536`, o si
`TIMEOUT_HTTP < --pared`; y cada muestra persiste ahora
`tok_prompt`/`tok_salida` (sin tokens, una truncada a 60k no se puede
distinguir a posteriori de una truncada por contexto).

**2. La reanudación era DESTRUCTIVA.** Reproducido en sandbox: el comando del
tramo 2 tal como estaba abreviado en la enmienda 4 habría descartado las 120
muestras del eje PROMPT de `factorial.json` (los ABORTA no saltan: sus
parámetros coinciden con los defaults), y reanudar `_high2` sin `--celdas`
habría descartado las 9 muestras (47 min de GPU). Arreglo: `celdas` se
persiste y se valida al reanudar (ficheros viejos exigen `--celdas` explícito
para adoptarse); `pared`/`timeout_http`/`n_ctx_backend` se persisten;
`n_pedidas` se actualiza al reanudar. Copias de seguridad hechas en
`b3_codigo/backup_20260731_noche/`. **Los comandos de tramos son ESTOS,
LITERALES** (con `COGNIA_TIMEOUT_HTTP=1500` exportada antes):

    :: tramo 1
    venv312\Scripts\python.exe scripts\b3_factorial.py --n 24 --minutos 150
        --max-tokens 60000 --pared 1500 --celdas oficial_high
        --sufijo _high2 --reanudar
    :: tramo 2 (solo si el reloj da) — IDÉNTICO salvo --n 36
    venv312\Scripts\python.exe scripts\b3_factorial.py --n 36 --minutos 150
        --max-tokens 60000 --pared 1500 --celdas oficial_high
        --sufijo _high2 --reanudar
    :: réplica low intra-config (tras high; ~7-11 min de GPU)
    venv312\Scripts\python.exe scripts\b3_factorial.py --n 36 --minutos 30
        --max-tokens 60000 --pared 1500 --celdas oficial_low
        --sufijo _low2

**3. Mi juez "oficial" NO es el oficial.** `juzga_oficial` reprueba
automáticamente los lotes > 8 MB (`demasiado_grande`) y capa el timeout a
120 s frente a la fórmula oficial (~306 s): **2 de las 24 tareas del tramo 1
(abc382_d, abc386_d) y 5 de las 36 del tramo 2 no las puede aprobar NUNCA**
(techo estructural 91.7% / 86.1%), y `abc382_d` ya está en disco con
`mio_pasa=True, oficial_pasa=False`. Reproducido por mí. Decisión:
`demasiado_grande`/`lote_expirado` son fallo de MI instrumento — estrato
aparte, pass@1 oficial CON y SIN, enumerado en la frase de comparación, y la
potencia del eje se corrige: el lado ganable de high son **11 tareas, no 13**
(esas 2 son fallo concordante forzado; n efectivo del contraste 22).

**4. La comparación puntual falseaba la precisión.** Con n=36 el error de
muestreo (~±16 pts al 95%) es mayor que el hueco a medir. La frase de
comparación lleva SIEMPRE n, semilla e IC95 Wilson, y además (avisos
adoptados): el sorteo es del solape FILTRADO (198 de 211: el filtro de
`tests_lcb` excluye 13 tareas, 10 hard, ~1-2 pts A MI FAVOR — el único sesgo
direccional a mi favor y por eso el primero que se declara), "mi banco local"
en vez de implicar equivalencia con v6, la mezcla de dificultades del tramo
(24: 7e/6m/11h; 36: 7e/10m/19h — el tramo 2 es MÁS duro y baja el pass@1 por
composición), y mi extractor toma el PRIMER bloque de código mientras el
oficial toma el ÚLTIMO (antes del análisis se escanean los crudos
multi-bloque; hoy 0 de 4 completas).

**Decisiones de análisis fijadas AHORA (antes del contraste):** la P que
decide el eje es de UNA COLA en la dirección pre-declarada `high > low` (es
el candidato de los ~18 pts); la de dos colas se reporta al lado, y el MDE se
calcula BILATERAL y se dice (la enmienda 4 mezclaba convenciones: los
"±7 netas" eran unilaterales; el MDE bilateral real con d=13 es ±9). Las tres
lecturas de truncadas son fallo (principal) / pase (cota superior REAL) /
excluidas (descriptiva) — "excluidas" NO es cota y deja de llamarse así. En
la principal, truncada se FUERZA a fallo aunque trajera código extraíble.
Análisis: `scripts/b3_esfuerzo_analisis.py` (no `b3_factorial_analisis.py`,
que codifica el prereg viejo).

**Blindaje del contraste entre corridas (aviso adoptado):** el par
high(noche)/low(mañana) cruza corridas Y configs de backend. Se pre-registra
la réplica `oficial_low` fresca bajo el backend de 65536 (`factorial_low2`,
comando arriba, se corre DESPUÉS de high para no robarle reloj): el contraste
principal del eje pasa a ser high vs low2 (intra-config) con high vs
low(mañana) al lado como réplica; si discrepan en signo, se dice y no se
firma ninguno.

**Congelado:** `lcb_test5.jsonl` SHA256 7F77571C2A6DF0C2…,
`lcb_test6.jsonl` BB4C364F71921C44… (los tramos exigen que no cambien).
Humo del preflight PASADO: aborta sin la env var (capa 3) y sin `--celdas`
(fichero pre-arreglo); con backend 65536+slots=1+timeout 1500 arranca y
reanuda las 9.

### ENMIENDA 4 (2026-07-31 19:15) — CERRAR el eje ESFUERZO por tramos, con las tres capas de instrumento ya fuera

**Escrita ANTES de generar la muestra 10.** La enmienda 3 declaró la celda
`oficial_high` no medible; era falso en dos de sus tres motivos (el contexto y
el timeout eran MÍOS, no del hardware — medido por la tarde: `n_ctx=65536`
ocupa 13.487 de 16.311 MiB). Con las tres capas fuera, la celda se corre.

**Condiciones del instrumento, verificadas ANTES de gastar (obligatorio):**

- Backend `--ctx 65536`, `total_slots=1` y `n_ctx=65536` confirmados en
  `/props` — con menos contexto lo que se mide es mi configuración.
- `COGNIA_TIMEOUT_HTTP=1500` en el ENTORNO del runner (la capa 3 mataba a los
  300,0 s exactos), `--pared 1500`, `--max-tokens 60000`.
- Fichero: `factorial_high2.json` (semilla 20260731, temp 0.8, max_tokens
  60000 — el runner ABORTA si difieren). `factorial_high.json` es la sonda
  vieja con timeout 300 y **NO se mezcla**.
- Ya hay **9 muestras** en el fichero (4 completas, 5 truncadas a 60k),
  generadas ayer en estas mismas condiciones: se reanudan, no se regeneran.

**QUÉ SE HACE CON LAS MUESTRAS QUE TRUNCAN A 60.000 TOKENS — decidido AHORA,
con 9 muestras vistas pero el contraste sin mirar:** contarlas como fallo a
secas es el error que ayer se cazó dos veces; excluirlas expulsa justo las
tareas más difíciles (el lado B). Lo pre-registrado:

1. `truncado_por_longitud` se reporta como **ESTRATO APARTE** con su tasa.
2. El pass@1 de la celda se da **CON ellas contadas como fallo** (lectura
   principal) **y SIN ellas** (cota optimista), siempre juntas.
3. **Por qué "truncada = fallo" es la lectura principal y no un cap mío:** la
   referencia corre con 64k de secuencia TOTAL; su techo efectivo de
   pensamiento+respuesta es ~63k. Mi presupuesto (60.000 de `max_tokens`
   dentro de `n_ctx=65536`) está ~3k por debajo de ese techo, y esa
   diferencia residual **se enumera en la frase de comparación**. Un problema
   que exige >60k de pensamiento está, a efectos de esta celda, en el mismo
   régimen que tendría en la referencia.

**Contraste del eje (descriptivo, apareado):** `oficial_high − oficial_low`
por tarea, juez OFICIAL como primaria del eje y juez mío al lado, sobre las
tareas con ambas celdas. **Potencia calculada ANTES con datos en disco:**
`oficial_low` pasa 11/24 de estas tareas (juez oficial), así que hay a lo sumo
13 tareas donde `high` puede ganar y 11 donde puede perder; con d discordantes
el sign-flip exige las victorias de siempre (d=8→8, d=10→9, d=13→10). Con
n=24 el **efecto mínimo detectable rondará ±7 tareas netas (~29 pts)**: esto
NO es un gate y no puede matar nada — es la MEDICIÓN del eje, y el MDE se
reporta junto al resultado. De las 9 muestras ya en disco hay 1 discordante
(3721: low pasa, high trunca) — se declara que se vio antes de escribir esto.

**TRAMOS, con corte por reloj pre-registrado en cada uno:**

- **Tramo 1:** `--n 24 --minutos 150` (~15 tareas pendientes × ~6-10 min).
  Cierra el eje con potencia mínima.
- **Tramo 2 (solo si el reloj da):** `--n 36 --minutos 150 --reanudar` — la
  semilla fija hace que las 24 primeras tareas sean las mismas, así que
  ampliar N no cambia el experimento. **36 ≥ N_min=35**: solo entonces la
  celda gana el derecho a comparar del §5.
- **Tramo 3 (solo si sobra aún):** ampliar hacia k=3 NO se improvisa: exigiría
  su propia enmienda (el fichero es k=1 por tarea y mezclar k cambia el
  análisis).

**La comparación con el 70 publicado** solo se emite si el tramo 2 completa
≥35 tareas, desde la celda `(prompt oficial, high, juez oficial)`, y la frase
enumera en la misma línea: mi banco no cubre 2024-08-01→09-21, k=1 contra sus
3 muestras, temperatura 0.8 contra no declarada, techo de pensamiento 60k
contra ~63k, y las tareas truncadas contadas como fallo. **Si el tramo 2 no
llega, no se compara y se dice** — el tramo 1 solo cierra el EJE, no la
comparación.

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

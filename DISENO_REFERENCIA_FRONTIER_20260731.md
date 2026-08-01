# DISEÑO — Referencia frontier de primera mano sobre MI banco (SIN correr)

**Escrito el 2026-07-31 por la noche. Esto es un DISEÑO con presupuesto: no se
corre sin autorización explícita del dueño (gastar dinero real es línea
dura).** Prioridad 3(b) de la sesión.

## 1. Por qué

El goal es *"igualar a un modelo grande desde 16 GB"* y hoy el denominador es
un blog de terceros (collinear.ai: gpt-oss-20b, 70 en LCB v6) con temperatura
no declarada, banco no idéntico al mío y evaluador ajeno. Una referencia
frontier corrida por MÍ sobre MIS 198 tareas, con MI juez y MI prompt oficial,
elimina de golpe los ejes EVALUADOR, VENTANA y PROMPT de la comparación: solo
quedaría modelo contra modelo.

## 2. El diseño

| | |
|---|---|
| Banco | las **198 tareas** del solape filtrado (2024-09-22→2025-01-26), las MISMAS del factorial, con el split sin fuga (`b3_fuga_split.py` antes de correr) |
| k | **3 muestras/tarea** (como la referencia publicada) ⇒ **594 generaciones** |
| Prompt | el oficial de LCB (`b3_oficial.prompt_oficial`), idéntico al de mi celda comparable |
| Juez | el mío con los DOS estratos declarados (truncadas; `demasiado_grande`/`lote_expirado` >8MB), idéntico al de mi celda ⇒ apareado perfecto tarea a tarea |
| Razonamiento | activado (los modelos actuales de Anthropic llevan adaptive thinking por defecto; `effort: high`) |
| Temperatura | NO aplica (la API actual de Anthropic no acepta `temperature`; se declara como diferencia con gpt-oss temp 0.8) |
| Vía barata | **Batches API: −50%**, sin prisa (el benchmark no es interactivo) |

Todas las fechas del banco (≥2024-09-22) son anteriores a los cortes de
entrenamiento de los modelos candidatos por menos margen que para gpt-oss
(corte jun 2024): **la contaminación por memorización es MÁS probable en el
frontier y se declara como amenaza**; mitigación parcial: reportar por estrato
de dificultad (la memorización infla más el easy).

## 3. Presupuesto (precios API Anthropic vigentes, cacheados 2026-06)

Supuestos: ~2k tokens de entrada por muestra (prompt oficial + enunciado);
salida con razonamiento estimada en ~10k tokens/muestra de media (rango 5-15k;
el hard piensa más). 594 muestras ⇒ ~1,2M entrada + ~6M salida.

| modelo | $/M ent | $/M sal | directo | con Batches (−50%) |
|---|---|---|---|---|
| Claude Sonnet 5 (intro hasta 2026-08-31) | 2 | 10 | ~$62 | **~$31** |
| Claude Sonnet 5 (precio pleno) | 3 | 15 | ~$93 | ~$47 |
| Claude Opus 5 | 5 | 25 | ~$155 | **~$78** |
| Claude Haiku 4.5 | 1 | 5 | ~$31 | ~$16 |

Con el rango de verbosidad (5-15k tok/muestra), multiplicar por 0.5-1.5.

**Recomendación si se autoriza:** Sonnet 5 por Batches durante el precio
introductorio (~$31±15) — es "un modelo grande" en el sentido del goal y el
coste es de una cena. Opus 5 (~$78±39 por batches) si se quiere el techo de la
gama con precio Opus. Antes de la corrida completa: **piloto de 20 tareas × 1
muestra (~$1-3)** para medir la verbosidad real y ajustar el presupuesto.

## 4. Qué se compararía, exactamente

`pass@1 (media de 3) frontier` vs `pass@1 gpt-oss-20b` **sobre las mismas 198
tareas, mismo juez, mismo prompt, mismos estratos** — apareado a nivel tarea,
con discordantes y MDE como siempre. Y la frase de resultado declara: corte de
entrenamiento del frontier vs ventana del banco, temperatura no aplicable vs
0.8, y los topes de mi juez idénticos en ambos brazos (se cancelan en el
contraste, no en el nivel).

## 5. Qué NO es

- No es el leaderboard de LCB ni pretende replicarlo.
- No sustituye el eje ESFUERZO (ese mide el 20B contra su propia referencia).
- No se corre sin OK explícito del dueño, y el piloto también cuenta como
  gasto real.

---

## ENMIENDA 1 (2026-07-31 20:00) — AUTORIZADO por el dueño, vía PLAN de Claude (no API de pago)

El dueño autoriza en vivo: *"para el benchmarks puedes usar este plan de
Claude, autorizo"*. Cambia el instrumento y se pre-registra ANTES de generar:

| | diseño original (API) | lo que se corre (plan) |
|---|---|---|
| vía | API Anthropic + Batches | **subagentes de Claude Code** (plan Max de la sesión) |
| modelo | Sonnet 5 / Opus 5 | **claude-opus-5** (referencia frontier canónica; Fable orquesta y no se gasta en generar) |
| system | ninguno / el mío | **el del harness de Claude Code** (no controlable) — DIFERENCIA DECLARADA |
| salida | texto libre | **salida estructurada** `{codigo}` (equivale al "Return ONLY a Python code block"; se declara) |
| temperatura | no aplica | no aplica (no controlable) |
| esfuerzo | effort high | **effort high** (`opts.effort`) |
| k | 3 | **k=1** — la comparación primaria es contra MI `oficial_low` (k=1), no contra el 70 de collinear |
| banco | 198 del solape | **las 60 tareas de `factorial.json`** (prompt oficial idéntico, apareado perfecto tarea a tarea); ampliable a las 198 si cuota y reloj dan |

**Primaria:** neto apareado `frontier − gpt-oss-20b(oficial_low)` sobre las 60
tareas, juez MÍO y juez oficial-con-mis-topes, los mismos estratos
(`demasiado_grande`/`lote_expirado` idénticos en ambos brazos: se cancelan en
el contraste). Discordantes, victorias y MDE reportados como siempre.

**Amenazas nuevas declaradas:** (a) el system prompt del harness puede ayudar
o estorbar — no medible, se declara; (b) contaminación de entrenamiento MÁS
probable que en gpt-oss (corte más tardío) — se reporta por estrato de
dificultad; (c) el agente podría intentar usar herramientas (ejecutar código
para verificarse): **se le prohíbe en el prompt y se registra si lo hace** —
un frontier CON herramientas sería otra condición (se etiquetaría aparte,
no se mezcla).

**Orden:** piloto 10 tareas → verificar mecánica (extracción, juez, tasa de
obediencia sin herramientas) → resto (50) → análisis apareado. El juicio es
LOCAL (subprocesos CPU del venv312): no toca la GPU ni el backend del eje
ESFUERZO, que sigue corriendo en paralelo.

### ENMIENDA 2 (2026-07-31 20:40) — fallo de FIDELIDAD cazado, y el arreglo

**El error, mío:** al transcribir los prompts al workflow (piloto y lote A)
recorté explicaciones de ejemplos en varias tareas. Los agentes veían un
prompt DISTINTO del oficial que vio gpt-oss — rompe el apareado. El lote A se
PARÓ a mitad (sus resultados se descartan); el piloto queda apartado como
`frontier_sonda_inline.json` (sonda de mecánica: 10/10 con mi juez, 0 usos de
herramientas, juez verificado con control negativo — pero NO se mezcla con el
benchmark).

**El arreglo:** los prompts ya no pasan por transcripción. Cada tarea está en
`b3_codigo/frontier_prompts/<id>.txt` (system oficial + prompt EXACTOS,
escritos por script desde `frontier_tareas.json`). El agente recibe la RUTA y
la instrucción de leerla con UN Read y resolver sin más herramientas. La
condición pasa a ser *"prompt entregado vía lectura de fichero"* — uniforme
para las 60 tareas (las 10 del piloto se RE-generan bajo esta condición),
verificable (el fichero es el prompt, byte a byte), y con obediencia
comprobable en el journal (2 tool calls esperados: Read + StructuredOutput).

### RESULTADO (2026-07-31 21:05) — corrido y juzgado

**Instrumento:** 60/60 generadas, 0 errores, ~10 min, ~1.76M tokens de
subagentes; obediencia perfecta (120 tool uses / 60 agentes = exactamente
Read + StructuredOutput por agente). Juez verificado antes con control
negativo (un `print` fijo reprueba) y conteo de casos ejecutados (5 vis + 15
oc + ~43 oficiales por tarea).

| claude-opus-5 (k=1, effort high) | |
|---|---|
| juez MÍO | **58/60 (96.7%)** — fallos reales solo `arc185_c` y `3613` |
| juez oficial-con-mis-topes | 49/60 (81.7%) — los 11 "no" incluyen **9 `demasiado_grande`** (mi tope de 8 MB, estrato declarado) |

**PRIMARIA — frontier − gpt-oss-20b(oficial_low), 60 tareas apareadas:**

| juez | neto | gana/pierde | P (1 cola) |
|---|---|---|---|
| MÍO | **+24** | 24 / **0** | 6.0e-08 |
| oficial-con-mis-topes | +23 | 23 / 0 | 1.2e-07 |

Por estrato (juez mío): easy 19/19 vs 18/19 · medium 14/15 vs 11/15 ·
**hard 25/26 vs 5/26** — el hueco con el frontier vive casi entero en `hard`.

**Descriptiva — contra oficial_high (25 tareas apareadas, truncadas de high
= fallo):** neto **+9 (9/0, P=0.004)**; en hard 11/11 vs 5/11. Ni el esfuerzo
alto de gpt-oss cierra el hueco.

**Limitaciones en la misma frase:** condición vía harness de Claude Code
(system del harness + entrega por Read + salida estructurada, no la API
pura); k=1; sin temperatura controlable; y **la contaminación de
entrenamiento es MÁS plausible que en gpt-oss** (ventana 2024-09→2025-01,
anterior al corte de Opus 5) — el 96.7% es techo optimista y así se lee. El
contraste apareado con juez idéntico en ambos brazos es lo que se firma, no
el nivel absoluto.

### ENMIENDA 3 (2026-07-31 22:20) — ampliación a las 198 del solape filtrado, con el brazo del 20B

Autorización vigente ("continúa con eso"). ANTES de generar:

- **Frontier:** las **138 tareas restantes** del solape filtrado (198 − las
  60 ya corridas), MISMAS condiciones de la enmienda 2 (opus-5, k=1, effort
  high, prompt por fichero byte-exacto con un único Read, salida
  estructurada). Prompts exportados por script a
  `b3_codigo/frontier_prompts/` antes de lanzar.
- **El brazo del 20B:** `oficial_low` de gpt-oss sobre las MISMAS 138
  (celda estándar, `factorial_low198.json`, max_tokens 60000 como `low2`,
  n_ctx del backend vigente — low no se acerca a ningún techo: 0 truncadas
  en 96 muestras low hasta hoy). ~1 h de GPU.
- **Primaria sin cambio:** apareado `frontier − gpt-oss(oficial_low)` con
  juez MÍO, ahora sobre n=198; estratos y topes idénticos en ambos brazos.
  Los netos de las 60 ya firmados NO se re-litigan: la ampliación añade
  potencia y representatividad (el sorteo de 198 ES el marco completo del
  solape filtrado — desaparece el sesgo de muestra de 60).
- **Reloj:** si el aterrizaje (07:44) corta algo, el análisis usa el
  prefijo de tareas con AMBOS brazos completos, y se dice.

### ENMIENDA 4 (2026-07-31 22:20) — re-juicio de los lotes `demasiado_grande` con tope alto (vía c, sin GPU)

Mi juez "oficial" capa lotes a 8 MB/120 s; el oficial real no. Se re-juzgan
**solo las tareas con `demasiado_grande`/`lote_expirado`** en cualquier celda
(`factorial*.json`, `frontier_resultados.json`) con **tope 64 MB y el timeout
de la fórmula oficial completa (7n+5, sin cap de 120 s)**, en fichero APARTE
(`rejuicio_grandes.json`) sin tocar los originales. Control positivo
pre-registrado: 2 tareas normales re-juzgadas con el tope alto deben
reproducir el veredicto del juez capado. Lectura: pass@1 oficial de cada
celda CON el estrato resuelto, al lado del capado (nunca en su lugar).

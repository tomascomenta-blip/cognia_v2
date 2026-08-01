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

# Objetivo: 200k de respuesta y 1M de contexto — lo que se midió (2026-08-18)

Pedido del dueño (2026-08-17, 23:10): que Qwythos maneje **workflows de hasta 200k tokens de
respuesta** y que el **chat principal sea de 1M** (YaRN o equivalente).

Este fichero es el estado MEDIDO. El plan por tandas y los criterios de corte viven aquí abajo;
la bitácora de ejecución en `MANAGER_LOG.md`.

## Los dos hallazgos que cambian el pedido

**1. YaRN no es trabajo pendiente: Qwythos ya declara 1M.** El GGUF dice
`general.architecture=qwen35`, base `Qwen/Qwen3.5-9B` (**no** Qwen2.5),
`rope.scaling.type=yarn`, `factor=4.0`, `original_context_length=262144` →
`context_length=1048576`. No hay flag que poner.

Y es **híbrido**: solo 9 de los 33 bloques tienen `attn_k` (3,7,11,15,19,23,27,31,32); los otros
24 son SSM. Con `head_count_kv=4` y `key_length=value_length=256`, el KV cuesta **36.864 B/token
en f16** — un cuarto de lo que costaría el denso equivalente. Por eso el millón cabe.

**2. El chat principal no corre sobre Qwythos.** El server vivo sirve
`qwen2.5-coder-14b-instruct-q4_k_m` con `n_ctx=16.384` y **un** slot. Antes de hablar de 1M hay
que decidir qué modelo atiende el chat.

## Los techos, medidos

| Qué limita | Dónde | Valor | Nota |
|---|---|---|---|
| El motor de workflows | `workflows_adapter.py:36-38` | **12.288 tok** (6 pasos × 2048) | 6,1% de 200k. Constantes sin override |
| La ventana del server | `--ctx-size 16384` | prompt+salida comparten 16.384 | Medido: 15.263+1.121=16.384 exacto, `finish_reason='length'` |
| El tope de pared del stream | `chat_client.py:121` | 3.600 s × 42,4 tok/s = **152.640 tok** | Un stream único de 200k es imposible por 24% |
| La vuelta del texto al modelo | `loop.py:302-350` | **200 chars** al pasar el 80% de la ventana | Un documento largo no puede volver como turno `tool` |
| Velocidad | medido | 42,4-44,1 tok/s gen · 1.294 tok/s prefill a 15k | 200k = **75-85 min** de generación |
| `paralelo(cap=2)` | un solo slot | **+9,8%** medido, no ×2 | Con `total_slots=1` el paralelismo es una cola |

## Lo que sí es alcanzable

- **Objetivo 1 → un DOCUMENTO de 200k en disco, no una respuesta de 200k.** `/largo --delegado`
  ya tiene el cap en `GEN_USER_MAX_TOKENS_CAP=200000` y escribe incrementalmente con sidecar
  reanudable. Rendimiento medido por worker: **2.995 y 4.010 tokens** (n=2) → 58-67 workers.
  Lo que el workflow debe devolver es **la ruta**, y quien quiera consultarlo usa RLM.
- **Objetivo 2 → 1M de contexto EFECTIVO por RLM**, que ya corre y está medido (9-24 s contra los
  **34 min** de prefill que cuesta el millón nativo). Lo que falta ahí no es YaRN: es memoria
  entre turnos. El millón nativo cabe (`summoner.py:113-120`: celda `1.010.176 / q4_0 /
  15.778 MiB`) pero deja **533 MiB** y desaloja el VLM, el worker y el job de imagen.

## Bombas encontradas de camino

- **El truncado se tira y se cobra.** `workflows.py:1368` trata `finish_reason=='length'` como
  error terminal sin guardar el crudo: 1.091 tokens cobrados y 23,7 s de pared a la basura.
- **`max_tokens` se sube en silencio** a 1024 (`workflows.py:1019`): pedir 64 y que la llamada
  vaya con 1024 hace mentir a cualquier tabla.
- **El ctx guard de `/largo` cree tener 150.144 tokens de prefill** (`LLAMA_CTX_SIZE=200192` en
  `~/.cognia/config.env` × 0,75) contra un server de 16.384. No estalla hoy; estalla en cuanto
  `per_task_cap` supere ~12.000.
- **`flota.py:62` y `model_profiles.py:64` dicen «Qwen2.5 abliterado»** de un modelo que es
  Qwen3.5/`qwen35`: el ruteo por substring elige mal system prompt, sampling y `enable_thinking`.
- **Subir `MAX_TOKENS_PASO` re-paga todas las corridas viejas**: `max_tokens` entra en
  `_clave_cache` (`workflows.py:745`). La palanca correcta es más PASOS, no pasos más largos.

---

## RESULTADO — la corrida de 200k, medida (2026-08-18, 03:05→04:34)

**GATE PASS.** `LARGO_TARGET=220000`, 176 workers, `per_task=1250`.

| medida | valor |
|---|---|
| **tokens del FICHERO** (`/tokenize`, no el contador) | **216.721** |
| contador del sidecar | 213.126 (+1,69% de diferencia, **explicada**: 3.169 de los encabezados `## N.`, 221 de la introducción, 43 `<im_end>`, 162 de los bordes de los 147 trozos del tokenizador; residual 15 tok = 0,007%) |
| secciones | **176/176**, `done_indices` contiguo |
| tiempo de pared | **89,1 min** (39,88 tok/s), dentro de la banda preregistrada 70-89 |
| bytes en disco | 905.892 |
| avisos del sidecar | ninguno |

**El KILL del esquema degenerado disparó EN VIVO** y funcionó: `esquema degenerado: 12 de 22
titulos son variantes de 'Modelo de Consistencia de Sesgo'; reintentando`. Es la misma familia
que lo motivó. Sin ese detector —escrito dos horas antes— el documento habría salido con doce
secciones sobre un tema inventado y el gate habría impreso PASS.

### Lo que el gate NO mira, y hay que arreglar antes de usar esto en serio

| defecto | número |
|---|---|
| **secciones cortadas a media frase** | **115/176 (65%)** |
| secciones con bloque de código sin cerrar | 40/176 (23%) |
| secciones bajo las 700 palabras que pedía el prompt | 125/176 (71%) |
| duplicación entre secciones | 6,7-10,8% (umbral 15: no dispara) |
| contradicciones en 148 parejas juzgadas | 0 |
| título duplicado exacto en el outline | 1 (índices 54 y 63) |

**La causa del corte es una decisión de dimensionamiento, no del modelo**: `per_task=1250` está
por debajo de la mediana natural del worker (1.392) para que mande el número de tareas, y 133 de
176 cerraron por `limit`. El arreglo no es subir el cap (rompe el dimensionamiento): es una
segunda pasada de cierre por sección, o pedir el cierre en el prompt del worker y medir si lo
respeta.

### Dos fallos de instrumento más, de la misma noche

- El lanzador mató el intento 1 a los **60 minutos exactos** con 124/176 hechas: las tareas de
  fondo del agente se cortan ahí. Confirmado tres veces. Y no se pudo reanudar porque el índice
  de capítulos solo se persiste al FINAL. Relanzado desacoplado, no volvió a pasar.
- El juez de calidad recortaba cada sección a 4.200 chars y **166 de 176 miden más**: el control
  positivo daba 2/6. Con el recorte quitado, 6/6. Los números de arriba son los de la pasada
  buena.

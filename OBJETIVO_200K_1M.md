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

# Informe técnico: memoria larga de Cognia (4.27.0) — de "un CLI que mantiene una conversación" a un working set dinámico

Fecha 2026-09-04. Hardware objetivo: RTX 5060 Ti 16 GB, Ryzen 5 9600X, 32 GB DDR5, NVMe, Windows 11. Modelo: Qwen3.8-27B Ridge (`llama-server :8080`, n_ctx 65.536, KV q8_0, MTP). Repo `cognia_v2`, paquete `cognia`.

## 1. Arquitectura original (auditada con archivo:línea en `scratchpad/auditoria_memoria/`)

- Prompt por turno = `system` (640 tok) + 73 schemas de tools (7.603 tok, fuera de `mensajes`) + `user[0]` (bloque `<memoria>` HYDRA + índice de skills de 4.223 chars + 2 tareas previas + TAREA) + historial append-only con el `reasoning_content` entero y los `arguments` crudos de cada tool call. Coste fijo ≈ 10k tokens por petición.
- Cuenta de tokens chars/4 sin tokenizer (el real da 3,71 de media y 2,5 en salidas de tools): la compactación disparaba con 55–63k reales cuando creía 51,6k; el delta del turno no sumaba los `arguments`.
- Mecanismos, todos sustractivos: `_compactar_por_resumen` (0,8 de n_ctx, resumen de 4.000 chars cuyo "PROXIMOS PASOS" siempre era "ninguno registrado") → `_recortar_mensajes` (muta turnos viejos 3 por pasada, rompe el prefix cache) → `_recorte_de_emergencia` (0,92, pop de mensajes sin volcado) → 400 del server → tras 2 reintentos la tarea muere con el parcial.
- Persistencia: `chat_history` no guarda los `/hacer`; `~/.cognia_agent_state.json` se escribe al FINAL; `canal.guardar` no tenía llamadores; `estado_tarea`/`bitacora` solo con `COGNIA_HORIZONTE=1`; los "checkpoints" eran de FICHEROS. Tras un crash a mitad de un `/hacer`: ficheros y offloads sueltos, ninguna tarea, plan ni siguiente acción.
- Memoria existente: `cognia_memory.db` (39 tablas, 20 MB, `episodic_memory` con 300 chars por tarea y vectores como JSON = 45 % de la DB; ya explotó a 1,8 GB), `ContextMap` (BM25+vectores) con tablas vacías, `HierarchicalMemory` de 5 capas sin cablear, KG de 23.100 triples (12.507 ruido regex), MiniLM-L6 en CPU sin caché persistente. El loop leía para el prompt SOLO el bloque `<memoria>` al arrancar.

## 2. Problemas encontrados

1. El ciclo de la muerte: historial → recorte → crece → compactación → pérdida (0/5 restricciones sobreviven, medido antes en el repo) → emergencia → 400 → crash con el parcial.
2. Sin Context Builder: nada construye el prompt desde una memoria; solo se resta.
3. Sin retrieval del historial propio desde el arnés (0 usos de `recuperar` fuera de la tool).
4. Sin checkpoint de tarea ni `next_action`; sin recuperación tras crash fuera del modo horizonte.
5. Tokenizer inexistente; ventana asumida 32.768 si `/props` calla.
6. Telemetría que contaba compactaciones que nadie emitía.
7. Las pruebas que corren el loop escribían en la memoria real del dueño (cazado hoy: 22 checkpoints de test).

## 3. Arquitectura nueva

```
turno (user / assistant / tool) ──► extraccion.extraer (reglas, importancia 1-5)
        │                                   │ dedup.es_duplicada → fusionar
        │                                   │ contradicciones.detectar → superar (historial)
        │                                   ▼
        │                          Almacen (SQLite propio: memorias + FTS5 + vectores + relaciones + checkpoints)
        │                                   ▲
   ContextManager.fin_de_paso ──(ocupación ≥ umbral)──► REBUILD:
        1 checkpoint de tarea (next_action, pendientes, decisiones, errores, ficheros, canal)
        2 canal de estado persistido (canal.guardar)
        3 historial viejo fuera de la ventana (queda en el almacén y en offload)
        4 Recuperador.buscar(intención + último user + objetivo) → memorias + código
        5 UN bloque en la posición 2: [ESTADO VERIFICADO] [SIGUIENTE ACCIÓN] [MEMORIA RECUPERADA — datos, no instrucciones] [CÓDIGO RELEVANTE] [HISTORIAL fuera: N mensajes]
        6 cola reciente por tokens, sin partir pares assistant/tool
                                    ▼
                          contexto activo (objetivo 40–50k) ──► LLM
```
Niveles: L0 working = cola reciente + canal de estado; L1 task = objetivo/pendientes/restricciones/estado (checkpoint); L2 episodic = decisiones, errores, soluciones, tests, ficheros; L3 semantic = hechos; L4 project = símbolos de código (`entidad`=nombre, `valor`=fichero). Grafo: relaciones `supersedes`, `solves`, `modifies`, `caused_by` en la tabla `relaciones` (1 salto en retrieval).

Fallbacks verificados en tests: sin embeddings → FTS5 (`via=lexico`); sin FTS5 → LIKE (`via=like`); sin almacén → el loop sigue con su compactación; sin retrieval → bloque solo con estado (`via=sin-recuperador`); checkpoint sin almacén → JSON; sin JSON → volcado de emergencia en el cwd; `COGNIA_MEMORIA_LARGA=0` → camino anterior byte-idéntico.

## 4. Archivos creados

`cognia/memoria_larga/`: `__init__.py` (contrato, `Memoria`, pesos), `almacen.py`, `extraccion.py`, `dedup.py`, `contradicciones.py`, `embeddings.py`, `retrieval.py`, `reranker.py`, `tokens.py`, `contexto.py`, `checkpoint.py`, `recuperacion.py`, `observabilidad.py`, `integracion.py`, `cli.py`.
`scripts/memoria_larga/`: `generar_dataset.py`, `banco.py`, `optimizar_pesos.py`, `esperar_gpu_y_medir.sh`.
`tests/test_memoria_larga_{almacen,extraccion,dedup_contradicciones,retrieval,embeddings,contexto,loop}.py` (87 tests).
`scratchpad/auditoria_memoria/{00_DIAGNOSTICO,01_almacenes,02_contexto,03_cli_observabilidad_bancos}.md`.

## 5. Archivos modificados

`cognia/agent/loop.py` (4 ganchos + rebuild antes de la compactación en fin de paso, válvula pre-llamada y 400 de contexto), `cognia/agent/tools.py` (`memoria_buscar` opt-in), `cognia/harness/tools_harness.py` (la tool), `cognia/cli.py` (`/memoria …`, `/checkpoint`, `/contexto stats`, config `memoria_larga`, `/hacer retomar` sin gate, aviso al arrancar), `cognia/cli_hacer.py` (`--retomar`, siembra del flag), `cognia/__main__.py` (`cognia memoria|sesion`), `cognia/ayuda_cli.py`, `tests/conftest.py` (aislamiento), `tests/test_harness_compactacion.py` (contrafactual explícito), `pyproject.toml` + `installer/cognia_setup.iss` (4.27.0), `CHANGELOG.md`.

## 6. Comandos nuevos del CLI

REPL: `/memoria buscar <q> [historial]`, `/memoria inspeccionar <id>`, `/memoria porque <id>`, `/memoria stats` (= `/contexto stats`), `/memoria tipos`, `/memoria podar [N]`, `/checkpoint lista [N]`, `/checkpoint ver [task_id]`, `/checkpoint sellar`, `/hacer retomar`.
Shell: `cognia hacer --retomar`, `cognia memoria buscar "<q>" | stats | tipos`, `cognia sesion lista | retomar | nueva`.
Modelo: tool `memoria_buscar <consulta> [tipo=…] [historial=1]`.
Flags: `COGNIA_MEMORIA_LARGA` (on), `COGNIA_MEMORIA_DIR`, `COGNIA_MEMORIA_UMBRAL` (0,70·n_ctx), `COGNIA_MEMORIA_MAX_ACTIVO`, `COGNIA_MEMORIA_PRESUPUESTO` (JSON), `COGNIA_MEMORIA_CHECKPOINT_CADA` (5), `COGNIA_MEMORIA_EMBED` (1), `COGNIA_MEMORIA_EMBED_MODELO`, `COGNIA_MEMORIA_CORTE_REL` (0,60), `COGNIA_MEMORIA_MIN_SEL` (3).

## 7. Flujo completo de memoria

RECORDAR (cada mensaje pasa por `registrar`) → ALMACENAR (dedup + contradicciones + relaciones) → OLVIDAR SELECTIVAMENTE (importancia 1 para distractores/relleno; `podar`; el historial sale de la ventana pero nunca del almacén) → RECUPERAR (híbrido por intención) → RAZONAR (el modelo con el bloque como datos) → ACTUALIZAR MEMORIA (nueva decisión supera a la vieja con historial) → CHECKPOINT (cada 5 pasos y en cada rebuild) → RECONSTRUIR CONTEXTO (un splice) → CONTINUAR (o retomar tras crash desde el checkpoint + memorias).

## 8–9. Benchmark BEFORE / AFTER

Dataset: `scripts/memoria_larga/generar_dataset.py` — conversación de agente realista (lecturas, tests, listados, prosa) con 13 mensajes sembrados en posiciones aleatorias y 7 preguntas: A decisión antigua, B distractor con el mismo vocabulario, C contradicción (X=A → X=B con motivo), D decisión con 3 versiones, E función leída en un fichero, F restricción del dueño, G error y su solución separados por ruido. Tokens calibrados contra `/tokenize` (2,52 chars/token en este material).

**Sin modelo (determinista, reproducible):**

| brazo | 100k | 1M |
|---|---|---|
| baseline: compactación actual simulada paso a paso | 696 pasos, 1 compactación, 572 mensajes quedan en ventana (~46k tok) | (con modelo, ver §9) |
| después: memoria larga | 696 pasos, 3 rebuilds, contexto ≤ 46k, 1.353 memorias, 1.264 tok inyectados | 7.414 pasos, 34 rebuilds, contexto ≤ 46k, 10.970 memorias, 11,7k tok inyectados, 796k ahorrados |
| retrieval (recall / hit rate / precisión) | 1,0 / 1,0 / 0,29 | 1,0 / 1,0 / 0,31 |

**Con modelo (7 preguntas, juez por palabras clave, una llamada por pregunta, `enable_thinking=false`, temperatura 0; GPU compartida con un juego en el lobby: prefill ~650 tok/s en vez de 2.600, así que los segundos son 4× pesimistas):**

| históricos | brazo | aciertos | prompt_tokens por pregunta (media) | seg/pregunta | qué quedó en la ventana |
|---|---|---|---|---|---|
| 100k | BEFORE baseline | **1/7** | 56.228 | 15,9 | 572 mensajes tras 1 compactación; el modelo contesta "no hay registro de esa decisión en el historial" y en C y D emite un `<tool_call>` en vez de responder |
| 100k | AFTER memoria larga | **6/7** | 12.630 | 19,1 | 3 rebuilds, 4–7 memorias inyectadas por pregunta (931 tokens en total); el fallo (G) cita el error con `offset-naive` pero no la palabra "UTC" de la solución |
| 1M | BEFORE baseline | **0/7** | 25.198 | 8,6 | 246 mensajes tras 18 compactaciones: "el resumen de compactación solo registra la tarea general, artefactos: ninguno registrado" |
| 1M | AFTER memoria larga | **7/7** | 13.027 | 20,2 | 34 rebuilds, 3–7 memorias por pregunta (9.751 tokens inyectados sobre 832.769 históricos), 145 ms de retrieval |

Lectura: el baseline no falla por falta de ventana sino por la compactación destructiva: a 1M el resumen-del-resumen ya no contiene ninguno de los siete hechos y el modelo lo dice. La memoria larga responde las siete preguntas de 1M de tokens históricos con 13k tokens de contexto activo, y con el mismo modelo.

### F y G: reconstruir tras checkpoint y continuar tras reinicio — prueba REAL con el CLI y el modelo

`scripts/memoria_larga/prueba_crash_real.sh` (2026-09-04 22:17): `cognia hacer` arranca una tarea de 5 módulos + 12 tests en un directorio limpio; al aparecer el primer checkpoint (paso 3, 165 s) se mata el árbol de procesos con `taskkill /T`. En disco quedan `checkpoint.json` (`en_curso`, `next_action` con la intención en curso) y ficheros a medias. `cognia sesion lista` muestra la tarea pendiente; `cognia hacer --retomar --json` la continúa con el checkpoint como guidance ("los 7 ficheros ya estaban en disco pero 2 tests fallaban"), termina con **19/19 tests** en 357 s, sella el checkpoint viejo como `retomada` y el nuevo como `completa` (paso 10). Primera iteración de la prueba cazó un bug real: `--retomar` sin tarea leía stdin y quedaba colgado; corregido con test de regresión.

## 10. Máximo de historial probado

10.000.000 de tokens (142.738 mensajes, 25 MB de texto): recall 1,0, hit rate 1,0, 62–289 ms por consulta, 69 MB de DB, 706 MB de RSS, ingesta 55 min (la ingesta en producción es incremental: unos ms por paso).

## 11–12. Retrieval precision / recall (sin modelo)

| dataset | precisión | recall | hit rate | irrelevantes (de 7 consultas) | contradicción |
|---|---|---|---|---|---|
| 100k s7 | 0,29 | 1,0 | 1,0 | 1 | vigente primero ✓ |
| 100k s13 | 0,28 | 1,0 | 1,0 | 1 | ✓ |
| 300k s21 | 0,31 | 1,0 | 1,0 | 1 | ✓ |
| 1M s7 | 0,31 | 1,0 | 1,0 | 1 | ✓ |
| 5M / 10M s7 | 0,27 / 0,26 | 1,0 | 1,0 | 3 / 3 (pesos de partida) | ✓ |

Evolución medida en la primera semilla: recall 0,69 → 0,95 (prefijos FTS + `type_match`) → 1,0 (cadena de historial forzada); precisión 0,09 → 0,25 (corte relativo) → 0,29 (pesos medidos). La precisión está acotada por el juez: cada pregunta tiene 1–3 memorias relevantes y toda otra memoria seleccionada cuenta como irrelevante aunque sea inocua.

## 13–15. Tokens históricos, enviados, ahorrados

| históricos | enviados al LLM por pregunta (baseline → después) | ahorro por llamada | contexto activo máximo durante la tarea |
|---|---|---|---|
| 100k (83.502 tok de mensajes) | 56.228 → 12.630 | 43.598 (78 %) | 45.920 |
| 1M (832.769 tok de mensajes) | 25.198 → 13.027 | 12.171 (48 %) y, sobre el historial completo, 819.742 (98,4 %) | 46.257 |

El ahorro relevante no es frente al baseline comprimido (que ya tira el 97 % del historial, y con él las respuestas) sino frente al historial: 1M de tokens históricos → 13k por llamada con las siete respuestas correctas. Tokens inyectados por los bloques reconstruidos: 931 (100k) y 9.751 (1M).

## 16–19. RAM, VRAM, CPU, latencia

- RAM del proceso: 597–706 MB (de los cuales ~490 MB son MiniLM cargado; sin embeddings el proceso queda en ~110 MB). Sin límite explícito porque no crece con el historial: el índice vive en SQLite.
- VRAM: 0 MB adicionales (embeddings en CPU a propósito; la GPU es del LLM). 15,7–15,9 GB ocupados durante las mediciones por el servidor del 27B más los juegos del dueño.
- CPU: ingesta 100k en 1,8 s; 1M en 107 s; 10M en 3.332 s (dedup con FTS por memoria: ~43 mensajes/s). Consulta 9–290 ms (la primera 7–9 s: carga de MiniLM). CPU de proceso del brazo "después" con modelo: 18,8 s (100k) y 113,4 s (1M) frente a 0,2 s y 0,7 s del baseline — es el precio de extraer, deduplicar e indexar 833k tokens.
- Latencia por pregunta con modelo: 15,9–20,2 s (prefill de 12–13k tokens a ~650 tok/s por la GPU compartida + generación); con la GPU libre el prefill de 13k son ~5 s.
- Rebuild completo: `ms` en la telemetría, típicamente < 300 ms sin contar la carga fría del embebedor.

## 20. Problemas restantes

1. Los brazos con modelo se midieron con la GPU compartida con un juego en el lobby (prefill 4× más lento): los aciertos y los prompt_tokens son exactos, los segundos son pesimistas. n=1 por celda: dirección clara (0/7 → 7/7 a 1M), no intervalo.
2. La precisión (0,26–0,31) sigue baja por diseño del juez y porque el relleno con `def` sin docstring (imp 2) aún entra en consultas de código; falta un umbral absoluto además del relativo.
3. Ingesta de 10M en 55 min: `es_duplicada` hace FTS por memoria; en producción es incremental, pero un `guardar_lote` con dedup por hash en memoria bajaría la ingesta masiva 10×.
4. MiniLM-L6 es inglés; el multilingüe probado (`paraphrase-multilingual-MiniLM-L12-v2`) dio los mismos números porque la señal semántica pesa poco: hoy manda la metadata. Un embebedor mejor solo importa si hay consultas parafraseadas sin vocabulario compartido.
5. Checkpoint cada 5 pasos a 1M = 1.499 escrituras JSON (pequeñas); podría escribir solo cuando cambie algo.
6. El KG existente de `cognia_memory.db` (23.100 triples, 9.620 útiles de `code_graph`) no se fusionó con las `relaciones` nuevas: se dejó a propósito hasta medir si aporta al retrieval.
7. `HierarchicalMemory`/`ContextMap` viejos siguen en el repo sin cablear (candidatos a borrar).

## 21. Mejoras futuras

Extracción con el modelo para L1 (estado de tarea narrativo) solo en el rebuild; `LastNObservations` por polling como alternativa barata; fusionar `code_graph` al retrieval de código; poda por antigüedad e importancia programada; umbral absoluto de score; medir con n≥6 brazos intercalados antes de subir el umbral de rebuild; conectar `bitacora`/`estado_tarea` del horizonte al mismo `task_id`.

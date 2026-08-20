# INVENTARIO CRITICO — que tiene YA Cognia para el agente de HORAS/DIAS con self-lobotomy

Fecha: 2026-08-19. Metodo: lectura del codigo (no del docstring) + grep de importadores
fuera de `tests/` sobre el arbol vivo `C:/Users/usuario/Desktop/cognia_v2`
(excluidos `.claude/worktrees/`, `venv312*`, `archive/`).

Criterio de "CABLEADA": existe al menos un importador en `cognia/`, `scripts/` o la raiz
que NO sea un test ni el propio paquete, y ese camino se alcanza desde el CLI o desde
`bucle_nativo`. "HUERFANA" = solo la importan sus tests, sus hermanos del mismo paquete,
o un frontend que el dueno no usa (`cognia_desktop_api.py`).

---

## 0. TITULAR EN TRES LINEAS

1. **El patron self-lobotomy YA EXISTE y esta cableado**: `cognia/agent/horizonte.py`
   (`COGNIA_HORIZONTE=1`) corre ciclos con **contexto fresco**, sello por `GoalContract`,
   criterios CONGELADOS y estado durable en disco. Techo duro **3 ciclos** y la recuperacion
   es una **plantilla determinista de 1200 chars** (`estado_tarea.resumen_para_prompt`).
   No es "casi": es exactamente el ciclo pedido, en miniatura.
2. **El canal de estado esta cableado a medias**: `estado/canal.py` corre por defecto
   (`COGNIA_ESTADO=1`) pero el bucle solo llama a `anotar_fichero`/`anotar_comando`/
   `anotar_verificacion`. **`anotar_restriccion`, `anotar_decision`, `anotar_pendiente`
   y `guardar/cargar` NO los llama nadie** — o sea, la capa de mayor persistencia
   (objetivo/restricciones/decisiones) esta construida, testeada y desconectada.
3. **NO existe compactacion de ningun tipo**. `/compactar` del CLI **solo limpia la
   pantalla y repinta un panel** (`cli.py:3003`); no toca `_history`. Lo unico que hay es
   truncado destructivo a 200 chars (`loop._recortar_mensajes`) y un `_history[-16:]` en
   el chat. La buena noticia: **no hay que desmontar un resumidor acumulativo porque
   nunca lo hubo**.

---

## 1. TABLA — PIEZA | QUE HACE | CABLEADA? | REUSABLE?

### 1.1 `cognia/estado/` — el canal contra la compactacion

| PIEZA | QUE HACE (leido del codigo) | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `estado/canal.py` (562 l) | Registro estructurado del turno como **dict plano serializable** (`EstadoVerificado` es una FABRICA, no una clase). Anota hechos **medidos**: `anotar_fichero` calcula sha256 y bytes **leyendo el disco**, `anotar_comando` guarda el exit code real. `render(estado, tope_chars=1200)` arma el bloque priorizado por `_ORDEN = [restricciones, ficheros, pendientes, verificaciones, decisiones, comandos]`; **las restricciones NUNCA se recortan** aunque revienten el tope, y todo recorte se ANUNCIA (`[RECORTE: N lineas omitidas]`). `conservacion(antes, texto_post)` mide recall de artefactos. `sembrar_trazadores`/`comprobar_trazadores` inyectan hechos no inferibles (canarios). `serializar/deserializar/guardar/cargar` persisten a `COGNIA_ESTADO_DIR` o `~/.cognia/estado`. | **PARCIAL**. `loop.py:556` la importa, ON por defecto. Solo se usan 5 funciones de 15: `EstadoVerificado`, `anotar_fichero` (1006), `anotar_comando` (1010), `anotar_verificacion` (1013), `render` (1101). **`anotar_restriccion`, `anotar_decision`, `anotar_pendiente`, `resolver_pendiente`, `sembrar_trazadores`, `comprobar_trazadores`, `conservacion`, `guardar`, `cargar`, `serializar`, `deserializar` NO tienen ni un llamador en produccion** (solo `medicion_conservacion.py` y `tests/test_estado_canal.py`). Ademas `render` se reinyecta SOLO despues de un recorte (`if _libero_algo`), no en cada paso. | `tests/test_estado_canal.py` | **SI, es la pieza central.** Es literalmente la "memoria jerarquica por persistencia" que se pide, con las secciones ya definidas. Falta (a) llamar a `anotar_restriccion`/`anotar_decision` desde algun sitio, (b) `guardar/cargar` entre ciclos, (c) reinyectar SIEMPRE, no solo tras recorte. |
| `estado/presupuesto_progreso.py` (614 l) | Gobernador por **coste por avance VERIFICADO**. Tipos de avance: `fichero_nuevo_valido`, `test_en_verde`, `postcondicion_cumplida`, `error_resuelto`, `pendiente_resuelto`. `observar_fichero` valida que exista, no este vacio y (si es .py) **compile**. `veredicto()` devuelve `arrancado/avanzando/estancado` con motivo y sugerencia; detecta **meseta de coste** (`FACTOR_MESETA_COSTE=5.0`) y **regresion**. `comparar(a,b)` compara dos corridas a iso-coste. | **SI**, `loop.py:557`, ON por defecto. Corta el bucle con "sin progreso verificado" (lineas 666-680). | `tests/test_estado_presupuesto.py` | **SI, tal cual.** Es el juez de "vale la pena otro ciclo" que un agente de dias necesita para no quemar 8 horas en churn. |
| `estado/medicion_conservacion.py` (181 l) | **Banco de medicion**, no runtime: construye un turno sintetico de 12 ficheros + 5 restricciones, aplica `compactar_cola`/`compactar_cabeza_cola` y mide recall CON y SIN canal. Es de donde sale el 0,07 -> 1,00. | **HUERFANA por diseno** (es un `main()`; solo lo llaman los tests). | dentro de `test_estado_canal.py` | **SI como INSTRUMENTO**: es el molde exacto del banco que hara falta para medir la compresion del self-lobotomy. Reusar `compactar_cola`/`compactar_cabeza_cola` como brazos-control. |

### 1.2 `cognia/agent/` — el bucle y el outer-loop

| PIEZA | QUE HACE | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `agent/loop.py` :: `bucle_nativo` (1179 l) | El bucle ReAct vivo. Ver seccion 2. | **SI**, es EL camino (`cli.py:13130+`). | `test_agent_loop.py`, `test_agent_loop_wires.py`, `test_agent_step_budget.py` | Base obligatoria; hay que meterle el punto de corte de ciclo. |
| `agent/horizonte.py` (204 l) | **EL OUTER LOOP DE SELF-LOBOTOMY, ya escrito.** `ciclos_con_contrato()`: ciclo 1 sobre el history real; ciclos >=2 con `hist_ciclo = [history[0], estado_tarea.resumen_para_prompt(...)]` — es decir **contexto DESTRUIDO y re-sembrado con objetivo + delta determinista**. `trace` tambien fresco (si no, el corte por no-progreso del ciclo anterior mataba al nuevo). Sella cada ciclo con `GoalContract.from_spec(...).check()` (evidencia de filesystem/comando). Criterios **congelados** una sola vez. Corte por **progreso monotono**: si `satisfied_count` no sube, para. | **SI pero opt-in y capado**: `cli.py:13069` exige `COGNIA_HORIZONTE=1`, regimen nativo, `delegation_depth==0`. `_TECHO_CICLOS = 3` (duro). | `tests/test_horizonte.py` | **SI — ES LA PIEZA MADRE.** Cambios: quitar/elevar el techo de 3, hacer que el delta salga tambien del canal de estado, y permitir N ciclos sin fin humano. |
| `agent/estado_tarea.py` (267 l) | Estado durable por tarea en `~/.cognia/data/tareas/<task_id>/estado.json` (override `COGNIA_TAREAS_DIR`). Guarda hitos (**solo con veredicto de GoalContract, jamas el auto-reporte del modelo**), `archivos_tocados`, `ultimo_error`, `faltan`, ciclos. `resumen_para_prompt(estado, faltan, max_chars=1200)`: **plantilla FIJA, sin LLM** — cabeza "CONTINUACION...", medio "YA VERIFICADO (NO lo repitas)" + "ARCHIVOS YA TOCADOS" + "ULTIMO ERROR", cola "SOLO FALTA:" que **sobrevive siempre** al truncado (el medio cede espacio, la cola nunca). Detecta tareas huerfanas (>15 min sin tocar) para retomarlas. | **SI**, via horizonte + tools `tarea_estado`/`bitacora_buscar` (`tools.py:3384`) + `/tarea retomar` (`cli.py:10727`). | `tests/test_estado_tarea.py` | **SI.** Es la mitad "recuperar solo lo necesario" del ciclo, y es determinista — cero riesgo de resumen-de-resumen. |
| `agent/bitacora.py` | Bitacora **APPEND-ONLY** por tarea; el agente la consulta con `bitacora_buscar` en vez de suponer. Comparte `task_id` con `estado_tarea`. | SI (horizonte). | — | **SI**: es el archivo de largo plazo que sobrevive a la lobotomia. |
| `agent/rlm.py` (1424 l) | Modo RLM: el corpus grande vive FUERA de la conversacion en un `ContextoRLM`/`ContextoVivo` y el modelo lo explora con 5 tools (`rlm_info/ver/grep/partir/llamar`), pagando solo los trozos que mira. `rlm_llamar` manda un trozo a **una subllamada LLM fresca SIN tools** (profundidad 1 ESTRUCTURAL). `MedidorContexto` reporta % visto por raiz e hijos y ventana pico, **sin flag para apagarlo**. Limite DECLARADO: **es LOCALIZACION, no sintesis** (el prereg salio VOID por el instrumento, no por el modelo). | **SI**: `/rlm` (`cli.py:10788`), `ContextoVivo` sembrado desde `_history`+`chat_history` (`cli.py:504-535`), tools registradas en `tools.py:3507`, tambien en `__main__.py:716`. | `test_rlm.py`, `test_rlm_contexto.py`, `test_rlm_vivo.py`, `test_rlm_grep_tildes.py`, `test_banco_rlm_sintesis.py` | **SI, ES LA VIA DE RECUPERACION.** Con ventana corta, "recuperar solo lo necesario" = grep sobre un corpus externo. `ContextoVivo` ya crece entre turnos. Advertencia: NO usarlo para sintesis sin volver a medir. |
| `agent/tools.py` :: `delegar_subtarea` (3230) | Sub-agente con **contexto fresco** y tools acotadas por rol (`investigador` solo lee, `implementador` escribe/ejecuta), sub-presupuesto = mitad del restante, profundidad max 2 (3 en esfuerzo maximo). La subtarea es autocontenida: **el sub-agente NO ve el historial del padre**, y al padre solo le vuelven **600 chars**. | **SI**, tool del registry. | — | **SI, es el multiagente pedido**: contexto destruido al terminar por construccion (el sub-bucle muere y solo sobreviven 600 chars). Falta: que el hijo escriba en el canal de estado del padre en vez de devolver prosa. |
| `agent/tools.py` :: `aci_trim` (309) | Recorta salidas de tool a head+tail escalado sobre el cap del n_ctx, **guardando el completo** en `.aci_overflow/<name>_<sha1>.txt`. | SI (en `run_tool`). | — | SI: ya es un "offload" pobre; el handle existe en disco pero el modelo no sabe pedirlo. |
| `agent/deliberation.py` | Mesa redonda entre modelos donde **la realimentacion es EJECUCION, no opinion**: el modelo B recibe el codigo de A + el traceback real. Prohibicion explicita de autocritica-LLM como juez. | SI (`tools.py:2911/2985`). | — | **SI como doctrina** para el agente critico: el critico no opina, ejecuta. |
| `agent/workflows.py` :: `criticar()` (2025) | **AGENTE CRITICO ya implementado**: N criticos por "lente" en paralelo (`paralelo_env`), schema `VEREDICTO_SCHEMA`, voto por quorum con `contar_votos(veredictos, lanzados)` que **distingue "se cayo" de "no encontro nada"**. Journal de la critica. | SI, via `harness/workflows_adapter` -> tool y comandos del CLI. | `test_workflows_critica.py` | **SI con un cambio duro**: hoy los criticos son el MISMO modelo (memoria del repo: "cinco instrumentos aprobaron algo roto"). Hay que forzar `rol`/`url` a otro modelo o hacerlos ejecutar. |
| `agent/sentinel.py` | Validacion pre-accion DEFAULT-ON: allow/ask/block por clasificacion de shell + saneado de texto web. | SI (`tools.py` x3, `doctor.py`). | — | SI tal cual (guardarrail de un agente que corre solo de noche). |

### 1.3 `cognia/memory/` — el almacen viejo (orientado a CHAT, no a AGENTE)

| PIEZA | QUE HACE | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `memory/hierarchical.py` (437 l) | Fachada Chimera sobre working/episodic/semantic/forgetting con un **WRITE-GATE**: `compute_surprise` (1 - max sim vs episodica) x `estimate_importance` decide si un dato se persiste a episodica. `write/recall/consolidate/decay/stats`. | **CASI HUERFANA**: solo `chimera.py:68`, que solo se alcanza por `/chimera <consulta>` (`cli.py:10873`). El agente no la toca. | `test_hierarchical_memory.py` | **NO tal cual.** Su jerarquia es working/episodic/semantic (por *modalidad*), no por **persistencia** (objetivo/restriccion/decision/hecho/estado/charla). El write-gate por sorpresa x importancia **si** es reusable como filtro de que entra al canal. |
| `memory/memory_compressor.py` (338 l) | **COMPRESION ACUMULATIVA — justo lo que hay que EVITAR.** Clustering greedy por coseno > umbral dentro de cada label; crea un macro-episodio con el centroide, **BORRA los originales** (`_delete_episodes`) e inserta el macro. Es resumen-de-resumen con perdida irreversible. | Solo `cognia.py:1608` (ciclo de "sueno" de la clase Cognia, no el agente). | `test_memory_compressor.py` | **NO. Antipatron explicito del encargo.** Vale como ejemplo negativo y como fuente del umbral de clustering si algun dia se comprime *charla descartable*. |
| `memory/episodic.py` + `episodic_fast.py` | Almacen sqlite de episodios con vector, importancia, confianza, `retrieve_similar` acelerado por cache numpy. | SI (`cognia.py`, `band_router`, `memory/__init__`). | `test_episodic_fast_incremental.py` | **PARCIAL**: sirve como almacen de "hechos permanentes" si se le pone un campo de provenance. Hoy no lo tiene. |
| `memory/forgetting.py` (163 l) | `decay_cycle` baja importancia por tiempo/accesos y marca `forgotten=1` bajo umbral; `ConsolidationModule.sleep_consolidation` promueve patrones a semantica. | SI (via `hierarchical` y `memory/__init__`). | `test_forgetting.py`, `test_consolidation*.py` | **PARCIAL**: el olvido por decaimiento temporal es EL antipatron para restricciones (governance decay). Reusable solo para la banda "charla descartable". |
| `memory/long_term_consolidator.py` (159 l) | Extrae entidades por regex de episodios y promueve a hechos del KG tras N ocurrencias. Tiene un `ConsolidationWorker` en hilo. | SI, `language_engine.py:1129` + `hierarchical.py:289`. | `test_long_term_consolidator.py` | **NO** para esto: promueve por FRECUENCIA, no por evidencia. Un agente que repite una alucinacion 3 veces la asciende a hecho. |
| `memory/memory_budget.py` (184 l) | Techo duro configurable (`COGNIA_MAX_MEMORIES`, `COGNIA_MAX_DB_MB`) purgando lo de menor valor: forgotten -> menor feedback -> menos accesos -> menor importancia -> menor confianza -> mas viejo. Count cap = soft delete; disk cap = DELETE + VACUUM. | SI (`cli.py:7155`, `cognia.py:1594`). | `test_memory_budget.py` | **SI como patron** de "presupuesto aproximadamente constante": el ranking de purga es exactamente la politica que hace falta, aplicada al almacen equivocado. |
| `memory/recap_policy.py` (54 l) | `should_recap(n_turnos, context_chars, ...)` puro, sin LLM: dispara cada 10 turnos o a 8000 chars (`RECAP_TURN_INTERVAL`, `RECAP_MAX_CONTEXT_CHARS`, `RECAP_MAX_ACTIVE_TASKS`, `RECAP_MAX_GOALS`). Y `MEMORY_LEVELS`: **taxonomia canonica de 5 niveles mapeada a piezas REALES del repo** (inmediata/sesion/trabajo/proyectos/...). | SI (`cli.py:409` y `4575`), pero **solo alimenta una recap EXTRACTIVA de chat** (`_session_recap`) inyectada en el fast-path de streaming — **no en el agente**. | `test_recap_policy.py` | **SI el disparador** (puro y testeable = el gatillo del self-lobotomy). **NO la recap extractiva** (es resumen de prosa). `MEMORY_LEVELS` es el punto de partida del mapa de persistencia. |
| `memory/project_memory.py` (150 l) | Estado persistente de corridas de `/flujo` en tabla `project_flows`: objetivo, ruta de etapas, etapas completadas, informe, score, status. `latest_unfinished()` para **RETOMAR entre sesiones**. Explicitamente "no almacena la conversacion". | SI (`cli.py:11058`, `agents/flow.py:230`). | **NO tiene test propio** | **SI**: es el registro "que estoy haciendo y por donde voy" a nivel proyecto, ya con retomable. |
| `memory/reranker.py` (278 l) | Re-ranker determinista offline que fusiona episodica+semantica en un `RankedItem` con score = similitud + recencia + importancia, dedup por label normalizado. Nunca lanza (defaults neutros documentados). | **CASI HUERFANO**: solo `context/band_router.py:317`, que solo corre en el fast-path de chat. | `test_reranker.py` | **SI**: cualquier recuperacion "solo lo necesario" necesita rankear, y este no llama al LLM. |
| `memory/narrative.py` (199 l) | Agrupa episodios en hilos coherentes desde una semilla (sim > 0.6, ventana 2 h). | **HUERFANO** (`cognia.py` lo expone en `get_narrative` -> camino de chat). | **NO tiene test** | NO para esto. |
| `memory/working.py`, `semantic.py`, `chat.py` | Buffer volatil, memoria semantica, `ChatHistory` (tabla `chat_history`, estampada con session_id). | SI. | — | `chat.py` SI: es la fuente durable de la conversacion que sobrevive a la destruccion del contexto y semilla el `ContextoVivo` del RLM. |

### 1.4 `cognia/context/` — el paquete mas grande y el mas desconectado

| PIEZA | QUE HACE | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `context/context_engine.py` (116 l) | Fachada: `record_turn` (mensaje -> puntero en ContextMap) y `retrieve` con **gap-fill organico** (si el mejor score < `min_score`, indexa la COLA NUEVA de las fuentes en disco y reintenta UNA vez). | **SI**, `/contexto`, `/contexto-mapa`, `/contexto-stats` (`cli.py:3427/3442/3460`) y `cli.py:398`. | `test_context_engine.py` | **SI**: el patron "consulta -> si flojo, indexa lo que crecio -> reintenta" es exactamente lo que un agente de dias necesita sobre su propio workspace. |
| `context/context_map.py` (402 l) | El almacen: punteros/spans con BM25 + vector (`query_hybrid`), por project. | SI (via context_engine, `ingest.py:163`, `tui/widgets/memory_view.py`). | `test_context_map.py`, `_hybrid`, `_query` | SI. |
| `context/lexical_index.py` (52 l) | `bm25_scores` puro. | SI (via context_map). | `test_lexical_index.py` | SI. |
| `context/gap_filler.py` (97 l) | `query_with_gap_fill`: el lazo consultar/rellenar/reintentar. | SI (via context_engine). | `test_gap_filler.py` | SI. |
| `context/context_session.py` (24 l) | `record_message`. | SI (via context_engine). | `test_context_session.py` | SI. |
| `context/band_router.py` (517 l) | Router HYDRA de 3 bandas (LOCAL/working, GLOBAL/episodica+semantica con reranker) -> `build_memory_block(query)`. | **SI pero SOLO en el chat**: `cli.py:598` `_build_memory_block_for`, usado en `_build_stream_messages` y `agents/flow.py:92`. **El agente `/hacer` NO lo usa.** Tambien `chimera.py:78`, `reasoning/cognitive_loop.py:137`. | `test_band_router.py` | **PARCIAL**: la idea de bandas es correcta; las bandas concretas no son las del encargo. Reusable el **punto de insercion**: el bloque va DENTRO del ULTIMO mensaje user para no invalidar el prefijo KV cacheado (`cache_prompt` + `--cache-reuse`) — con historia de 4k a ~29 tok/s de prefill eso son >2 min por turno. Oro para un agente local de 1 slot. |
| `context/context_window_manager.py` (192 l) | Selector de bloques por `composite = relevance * recency_factor * source_weight` bajo `MAX_TOKENS=800`. `recency_factor = 1/(1+age_h*0.1)`. | **HUERFANO** (solo lo importa `injection_prioritizer`, que a su vez es huerfano en el CLI). | `test_context_window_manager.py` | **PARCIAL**: la formula es razonable pero el peso por *recencia* es lo contrario de "persistencia"; un objetivo de hace 6 h no vale menos. |
| `context/injection_prioritizer.py` (197 l) | Convierte fuentes en `ContextBlock` y prioriza con el CWM. | **HUERFANO EN EL CLI**: solo `language_engine.py:1476` y `cognia_desktop_api.py:246`. | `test_injection_prioritizer.py` | PARCIAL (mismo reparo). |
| `context/anchor_tracker.py` (105 l) | Tracker de deriva de objetivo (Conversation Anchor Tracker). | **SEMI**: lo importa `agents/goal_contract.py:29` con try/except (si falla, drift = no-op) y `cognia_desktop_api.py:647`. | `test_anchor_tracker.py` | **SI**: "el agente se olvido de para que estaba" es EL fallo de las 8 horas. |
| `context/session_warm_starter.py` (154 l) | Briefing de arranque de sesion desde KG + gaps + resumen de largo plazo, **max 400 chars, sin LLM**, prependido al system prompt en el primer turno de cada sesion. | **HUERFANO EN EL CLI** (solo `cognia_desktop_api.py:658`). | `test_session_warm_starter.py` | **SI, muy directamente**: es literalmente "arrancar sesion limpia sabiendo lo minimo". Cambiar la fuente (KG -> canal de estado). |

### 1.5 `cognia/multiverso/` y `cognia/autopsia/` — rebobinar y culpar

| PIEZA | QUE HACE | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `multiverso/instantanea.py` (727 l) | Snapshots baratos del arbol de ficheros en NTFS: tomar/restaurar/diferenciar/**fusionar**. Declara lo que NO puede (no hay CRIU en Windows: no hay checkpoint del PROCESO). | SI (`autopsia/motor.py:117`, `ramas.py`, `scripts/`). | `test_multiverso_instantanea.py` | **SI**: "estado del mundo" que sobrevive a la destruccion del contexto. |
| `multiverso/ramas.py` (1001 l) | Best-of-K con efectos REALES: K copias del workspace, juicio por postcondiciones verificadas, `fusionar` solo la ganadora. `guardia_de_rama` **VETA** lo irreversible dentro de la rama y lo ENCOLA para ejecutarse una vez si esa rama gana (patron saga). | SI (`cli.py:8904`, `harness/interceptor.py:157`). | `test_multiverso_ramas.py` | SI para "explorar sin romper"; secundario para el encargo. |
| `multiverso/reversibilidad.py` (1036 l) | Catastro: clasifica (tool, args) en puro / reversible / irreversible / desconocido, con compensacion, motivo y confianza, analizando incluso la linea de comandos de `ejecutar` (`ls` y `rm -rf` son la MISMA tool). Medido: **26,05% puro / 57,86% reversible / 7,31% irreversible** sobre 86.496 llamadas. | SI (via `ramas.py:329`, `especulacion.py:868`). | `test_multiverso_reversibilidad.py` | **SI**: es la tabla que dice que puede hacer un sub-agente sin supervision humana a las 3 de la manana. |
| `multiverso/especulacion.py` (1125 l) | Predice la proxima accion por bigramas sobre la traza y ejecuta especulativamente **solo acciones PURAS** (comprobado dos veces: al predecir y al ejecutar). | SI (`loop.py:580`) pero **OFF por defecto** (`COGNIA_ESPECULAR`), y **medido KILL** (1 especulada, 0 aceptadas: las tareas cortas no tienen historial). | `test_multiverso_especulacion.py` | **QUIZA**: la razon del KILL fue "tareas cortas sin historial". Un agente de DIAS es justamente el regimen donde SI tendria historial. Re-medir, no re-implementar. |
| `autopsia/replay.py` (831 l) | Trayectoria normalizada, reproducible desde cache a coste ~0 (medido: 115,1 ms -> 0,057 ms, 2018x), ablacionable, con huella estable que demuestra que dos reproducciones son la misma. | SI (`autopsia/causal.py:157`, `autopsia/__main__.py`). | `test_autopsia_replay.py` | SI (postmortem de una corrida de 8 h sin volver a pagarla). |
| `autopsia/causal.py` (741 l) | Atribucion causal por **replay contrafactual con biseccion**: cual de los N pasos causo el fallo. precision@1 = 1.000 vs 0.05/0.10 de las lineas base. | SI (`autopsia/motor.py:118`, `/autopsia` en `cli.py:9519`). | `test_autopsia_causal.py` | **SI**: es el critico que un agente autonomo necesita cuando amanece roto. |
| `autopsia/motor.py` (200 l) | Une instantanea (rebobinar) + causal (que preguntar) sobre una grabacion de `flujos/grabador`. | SI (`cli.py:8960`). | **NO tiene test propio** | SI. |

### 1.6 `cognia/flujos/` — grabar, generalizar, EXAMINAR

| PIEZA | QUE HACE | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `flujos/grabador.py` (584 l) | Captura HECHOS de lo que el agente hizo, con su `ok` real, **incluidos los pasos fallidos**. Regla horneada: una grabacion es un REGISTRO, nunca un procedimiento. | SI (`cli.py:8649/8959`, `autopsia/replay.py:184`). | `test_flujos_grabador.py` | **SI**: es el log del que saldra la compresion de un ciclo. |
| `flujos/generalizador.py` (1053 l) | Grabacion -> flujo parametrizado (`{param}`) **determinista**, con postcondiciones verificables y registro auditable de que se podo. | SI (`cli.py:8720`, `autopsia/motor.py:67`). | `test_flujos_generalizador.py` | SI (para "aprender" sin LLM). |
| `flujos/examen.py` (1295 l) | **LA COMPUERTA**: un flujo no queda disponible por "haber salido bien"; tiene que aprobar casos NUEVOS (al menos uno distinto en ESTRUCTURA), en workspaces temporales aislados, juzgado por POSTCONDICIONES (ficheros, JSON, exit codes), nunca por el texto que el propio flujo produjo. `registrar_uso` + cuarentena. | SI (`cli.py:8721/8825`). | `test_flujos_examen.py`, `test_cli_flujo.py` | **SI, ES LA DOCTRINA ANTI-ALUCINACION del repo aplicada al aprendizaje.** El mismo patron sirve para "un hecho no entra en memoria permanente por haberlo dicho el modelo". |
| `flujos/reproductor.py` (680 l) | Ejecuta el flujo contra el registry real, liga parametros y verifica postcondiciones EN DISCO, con informe de coste. | SI (`cli.py:8722`). | `test_flujos_reproductor.py` | SI. |

### 1.7 `cognia/harness/` — el arnes destilado

| PIEZA | QUE HACE | CABLEADA? | TESTS | REUSABLE? |
|---|---|---|---|---|
| `harness/interceptor.py` | **El punto UNICO** entre el modelo y sus tools: `antes(name,args,ctx)` (None = seguir, str = SUSTITUYE el resultado y la tool no se ejecuta) y `despues(name,args,ctx,out,ok)`. Contrato: nunca lanza, nunca bloquea. Ahi cuelgan checkpoints, modo plan, hooks, verificacion de sintaxis, offloading, anticuerpos, ramas. | **SI**, `agent/tools.py:458/496`. | — | **SI, ES EL ENCHUFE.** Todo lo nuevo (anotar restricciones al canal, provenance, presupuesto de ciclo) entra por aqui sin tocar `run_tool`. |
| `harness/checkpoints.py` (660 l) | Deshacer por FICHERO con snapshots por sesion, sin depender de git (el workspace del agente no suele ser un repo). `registrar/listar/deshacer/restaurar_hasta/diff_sesion/podar_sesiones`. | SI (`cli.py:8399` `/deshacer`, `interceptor.py:210`, `tools_harness.py:303`). | `test_harness_checkpoints.py`, `test_checkpoint_encoding.py` | SI. |
| `harness/verificacion.py` (440 l) | Auto-lint/auto-test tras cada edicion: `compile()` para .py, `json.loads` para .json, descubre tests asociados y los corre. Devuelve el error REAL como texto de RESULTADO, sin gastar un turno del modelo. Declara sus limites (no trae ruff/eslint). | **PARCIAL**: `interceptor.py:290` la llama, pero **correr tests esta OFF** (`COGNIA_AUTO_TESTS=1`); solo la sintaxis va ON por defecto. | `test_harness_verificacion.py` | **SI**: es la fabrica de "avance verificado" que alimenta `presupuesto_progreso`. |
| `harness/contexto_vivo.py` (400 l) | Contador EN VIVO de ventana y coste con `usage` REAL; marca `estimado=True` y pone `~` cuando el numero no viene del backend. `barra()`, `aviso_umbral()`, `estado()`. | **HUERFANO A MEDIAS**: `cli.py:8354` solo llama a `estado()` para pintar la barra. **`registrar_uso` / `registrar_contexto` NO los llama NADIE** — la barra nunca recibe datos reales; `loop.py` lee `resp.usage` y lo tira. | `test_harness_contexto_vivo.py`, `test_harness_barra_estado.py` | **SI, y es urgente**: el disparador del self-lobotomy es "% de ventana ocupada". Hoy ese numero existe en el bucle y se descarta. |
| `harness/limites.py` (399 l) | Limites TRIPLES (pasos / segundos / tokens / USD) comprobados ANTES de gastar el turno. El corte es **excepcion tipada** `LimiteExcedido(eje, valor, limite)`, no un return silencioso, y el mensaje esta escrito PARA EL MODELO con numeros literales ("te quedan 3 pasos"), no adjetivos. | **HUERFANO TOTAL**: cero importadores; solo aparece citado en docstrings ajenos (`chat_client.py`, `workflows_adapter.py`). | `tests/test_harness_limites.py` | **SI, tal cual.** Un agente de DIAS necesita el eje SEGUNDOS y el eje TOKENS, que hoy nadie mira (`hermes/presupuesto_turno` solo cuenta pasos). |
| `harness/oraculo.py` (573 l) | El agente barato **pide ayuda explicitamente** a un modelo capaz: `elegir_rol`, `armar_consulta`, tope anti-abuso + de-duplicacion, **transporte INYECTADO** (no abre puertos ni decide que modelo sirve donde). Degradacion honesta con causa. | **SEMI**: `harness/tools_harness.py:85` lo publica como tool; el bucle nunca lo invoca por su cuenta. | `test_harness_oraculo.py` | **SI**: es el canal por el que un ciclo atascado puede escalar al Qwen3.8-27B sin cambiar el modelo del bucle. |
| `harness/modo_plan.py` (308 l) | Modo solo-lectura hasta que el usuario apruebe. `es_de_escritura` decide por (1) `danger` del registry, (2) `_SEGUN_ARGS` (tools cuyo efecto depende de los args), (3) lista base medida contra el registry real. | SI (`cli.py:8374/8431`, `interceptor.py:183`). | `test_harness_modo_plan.py` | SI (util para la fase de investigacion al arrancar cada ciclo). |
| `harness/workflows_adapter.py` (596 l) | Puente agente <-> `agent/workflows.py` (paralelo/pipeline con schema, journal, **resume desde una corrida previa**, presupuesto). Topes por env (`COGNIA_WF_MAX_PASOS/_MAX_TOKENS_PASO/_PRESUPUESTO`). **MEDIDO**: subir `max_tokens` invalida el 100% de la cache de resume; sumar pasos deja los viejos intactos. | SI (`cli.py:1097/1359/8459`, `tools_harness.py:38`). | `test_harness_workflows_adapter.py`, `test_workflows_engine.py`, `test_motor_workflows_techos.py` | **SI**: el resume del motor es el equivalente "reanudar tras la lobotomia" del lado del pensar-sin-tools. |
| `harness/offloading.py` | Lo grande va a DISCO y al modelo le llega resumen + HANDLE para pedir el trozo. | **OFF por defecto** (`COGNIA_OFFLOAD=1`); el interceptor documenta por que: el doble truncado con `aci_trim` hizo que el modelo editara con SEARCH/REPLACE texto que nunca vio. | — | **SI pero midiendo contra `aci_trim`**, no encendiendolo por fe. |
| `inmune/anticuerpos.py` | Un fallo confirmado se convierte en un **predicado determinista** sobre (tool, args, ctx) que corre en cada tool call y VETA. **Cero LLM.** Nada se activa por haber sido sintetizado: `sintetizar` deja en CUARENTENA y solo `examinar` (vetar los casos del fallo Y dejar pasar sanos held-out con CERO falsos positivos) lo pasa a activo. | SI (`interceptor.py:172`). | — | **SI**: es el molde exacto del "anti-alucinacion que corre", frente a la nota en prosa. |
| `hermes/presupuesto_turno.py`, `guardia_bucle.py`, `mutaciones.py`, `parada_verificada.py` | 5 mecanismos ON por defecto en el bucle (`COGNIA_HERMES=1`): presupuesto con **refunds**, `RazonSalida` (todo `break` sella su razon y se loguea SIEMPRE), guardia de ping-pong A-B-A-B y ciclos A-B-C, footer de **mutaciones FALLIDAS** (hecho medido, no resumen del modelo), parada verificada. | SI (`loop.py:527-545`). | — | **SI**: `RazonSalida` es el antidoto al vacio silencioso a escala de ciclo. |

### 1.8 Piezas sueltas

| PIEZA | QUE HACE | CABLEADA? | REUSABLE? |
|---|---|---|---|
| `agents/goal_contract.py` | Criterios CHECKEABLES (`file_exists`, `text_in_file`, `command_succeeds`, `text_present`) evaluados con chequeos REALES, no auto-reportes. `derive_criteria_from_task`, `check()`, `reanchor_hint`. Delega la deteccion de deriva al `AnchorTracker`. | SI (horizonte, epilogo de `/hacer`). | **SI, ES EL SELLO.** Limitacion declarada: resuelve rutas relativas contra el **CWD del proceso**, no contra el workspace del agente. |
| `search/evidencia.py` | `verificar_cita(cita, texto_fuente)`: **la cita esta literalmente en la fuente, SIN juez LLM**. Da la tasa de citas fabricadas; su error es del instrumento, no del modelo. Declara que NO dice si la cita RESPONDE. | Parcial (pipeline de investigacion). | **SI, ES LA BASE DEL PROVENANCE.** |
| `compresion_salidas.py` (123 l) | `comprimir` (colapsa lineas repetidas con contador, recorta el medio, **conserva el FINAL**) y `comprimir_error`. 89% de ahorro medido en logs. | SI (`cli.py:12570`, `program_creator/generator.py`). | **SI** para la banda "charla descartable"; NO para estado. |
| `compression.py` (160 l) | `ConceptCompressor` (clustering de embeddings) + `GraphEpisodicBridge`. | SI (`cognia.py:40`, ciclo de sueno). | NO (mismo antipatron que `memory_compressor`). |
| `semantic_cache.py` (252 l) | Cache de respuestas por coseno TF-IDF, <5 ms, thread-safe. | **HUERFANO EN EL CLI**: solo `cognia_desktop_api.py` y `reasoning/cache_warmer.py`. | QUIZA (evita repagar la misma subconsulta entre ciclos). |
| `vectors.py` (77 l) | `cosine_similarity`, `vec_norm`, `text_to_vector`, `analyze_emotion`. Embedding **propio y barato** (`cognia_embedding.text_to_vector_fast`). | SI (base de medio repo). | SI (recuperacion sin GPU: no compite por los 16 GB del backend). |
| `arbitro.py` | Detecta cuando un generador **deja peor** un fichero de otro (huella + compila) y frena. | SI (`agents/workers/dev_tools.py:175`). | SI para el multiagente concurrente. |

---

## 2. COMO ES HOY EL BUCLE DEL AGENTE

`cognia/agent/loop.py :: bucle_nativo(task, system, completar, schemas, args_legacy,
mensaje_assistant, mensaje_tool, run_tool, ctx, perfil, history, trace, print_fn, max_turns)`
-> `{"texto","pasos","ok","tokens","finish"}`.

Es el camino vivo: el `while` legacy de `cli.py` solo corre con el perfil 3B o
`COGNIA_AGENT_LEGACY=1`.

### 2.1 Como arma los mensajes (loop.py:591-596)

```python
mensajes: list = []
if system:
    mensajes.append({"role": "system", "content": system})
# El objetivo (+ guidance/pista que cli.py ya metio en history) es el
# turno user inicial y NUNCA se recorta.
mensajes.append({"role": "user", "content": "\n\n".join(history)})
mensajes_dump = mensajes
```

Es decir: **UNA sola lista `mensajes` que crece monotonamente** durante todo el bucle:
`[system] + [user con TODO el history concatenado] + assistant/tool/assistant/tool...`.
`chat_client.mensaje_assistant` **reinyecta `reasoning_content` en CADA turno assistant**
para preservar el CoT entre tool calls — con un razonador eso llega a ser el 80% del prompt.

Extras apendeados por paso, todos con rol `user`: el bloque del canal de estado (solo tras un
recorte), los avisos del `GuardiaBucle`, el `AVISO` de `register_action` cuando repite tool+args,
y la `sugerencia` del gobernador de progreso al cortar.
**Nada se elimina jamas de la lista.** El unico "olvido" es el truncado in-place de 2.2.

### 2.2 Como recorta cuando no cabe — FRAGMENTO LITERAL

Disparo (loop.py:1077-1110), tras cada turno:

```python
        est = int((resp.usage or {}).get("prompt_tokens") or 0)
        # Se cuenta TAMBIEN el reasoning_content: mensaje_assistant lo
        # reinyecta y con un razonador pesa mas que el content (parte del fix
        # A3-bucle: el CoT era invisible para el presupuesto de punta a punta).
        est += sum(len(str(m.get("content") or ""))
                   + len(str(m.get("reasoning_content") or ""))
                   for m in mensajes[idx_turno:]) // 4
        _libero_algo = False
        while True:
            liberados = _recortar_mensajes(mensajes, perfil.get("n_ctx"), est)
            if not liberados:
                break
            _libero_algo = True
            est -= liberados // 4
        if _libero_algo and _estado_on and _canal is not None:
            # AQUI es donde se pierde el estado: el recorte resume o tira los
            # turnos viejos y con ellos que ficheros se tocaron y que
            # restricciones habia. El canal vuelve a entrar ENTERO, y nunca
            # pasa por el resumidor (esa es toda la inmunidad).
            try:
                _bloque = _canal.render(_estado, tope_chars=1200)
                if _bloque:
                    mensajes.append({"role": "user", "content": _bloque})
                    print_fn("[detail]contexto recortado: reinyecto el canal de "
                             "estado verificado[/detail]")
            except Exception:
                pass
```

El recorte en si (loop.py:375-431), **copiado literal**:

```python
# Por debajo de esto recortar no compensa: se destroza contexto para liberar
# nada. Vale igual para el content de un turno tool y para el reasoning de un
# assistant.
_RECORTE_MIN = 400


def _recortar_mensajes(mensajes: list, n_ctx, prompt_tokens: int) -> int:
    """Presupuesto de contexto en TOKENS REALES (A4.3): si el ultimo prompt
    supero ~80% del n_ctx del server, recorta a un resumen corto los turnos
    MAS VIEJOS que pesan — el content de los turnos tool y el CoT de los turnos
    assistant (nunca el system ni el user del objetivo). Devuelve cuantos CHARS
    libero (0 = bajo el umbral o nada recortable), para que el llamador pueda
    iterar con un estimado actualizado. El descarte en bloque del contexto
    viejo era la causa de 'el agente olvida su objetivo'; aca el objetivo es
    intocable por diseno.

    POR QUE tambien el reasoning (fix A3-bucle 2026-08-13): chat_client
    .mensaje_assistant reinyecta reasoning_content en CADA turno assistant para
    preservar el CoT entre tool calls. Este recorte solo miraba role=='tool',
    asi que con AGENT_HARD_CAP=40 pasos el CoT acumulado —que puede ser el 80%
    del prompt con un razonador— NUNCA entraba al presupuesto: devolvia 0
    liberados y el prompt reventaba n_ctx en silencio (el server trunca por
    izquierda o tira 'context shift', y el agente pierde el objetivo sin que
    nadie lo diga). Reproducido en test_recorte_incluye_el_reasoning_de_los_
    assistant_viejos: 20 turnos x 5k chars de CoT -> 0 liberados.
    """
    if not n_ctx or prompt_tokens < int(n_ctx * 0.8):
        return 0
    # El CoT del ULTIMO turno assistant es el que el modelo esta usando AHORA
    # (los tool calls de ese mismo turno acaban de volver): se preserva
    # siempre. Los anteriores ya cumplieron su funcion.
    ultimo_assistant = -1
    for i, m in enumerate(mensajes):
        if m.get("role") == "assistant":
            ultimo_assistant = i

    recortados, liberados = 0, 0
    for i, m in enumerate(mensajes):
        rol = m.get("role")
        if rol == "tool" and len(m.get("content") or "") > _RECORTE_MIN:
            antes = len(m["content"])
            m["content"] = (m["content"][:200]
                            + "\n[... recortado por presupuesto de contexto ...]")
            liberados += antes - len(m["content"])
            recortados += 1
        elif (rol == "assistant" and i != ultimo_assistant
                and len(m.get("reasoning_content") or "") > _RECORTE_MIN):
            antes = len(m["reasoning_content"])
            m["reasoning_content"] = (
                m["reasoning_content"][:200]
                + "\n[... razonamiento recortado por presupuesto de contexto ...]")
            liberados += antes - len(m["reasoning_content"])
            recortados += 1
        if recortados >= 3:   # de a poco: 3 turnos por pasada alcanzan
            break
    return liberados
```

### 2.3 Hay compactacion? De que tipo?

**NO hay compactacion.** Lo que hay, en orden de aparicion:

1. **`aci_trim`** (`agent/tools.py:309`): head+tail escalado sobre el cap del n_ctx, con el
   texto completo guardado en `.aci_overflow/<name>_<sha1>.txt`. Es truncado con respaldo en
   disco, pero **el modelo no tiene tool para pedir el respaldo**.
2. **`_recortar_mensajes`**: truncado destructivo **in-place a los primeros 200 chars** de los
   turnos `tool` mas viejos y del `reasoning_content` de los assistant no-ultimos, max 3 por
   pasada, iterando hasta bajar del umbral. **Sin resumen, sin LLM, sin recuperabilidad.**
   Umbral: `prompt_tokens >= 0.8 * n_ctx`.
3. **Reinyeccion del canal** solo **si** algo se libero. El bloque va como `user`, rol que
   `_recortar_mensajes` no toca: es inmune a los recortes siguientes.
4. **Corte de ciclo (horizonte)**: la unica "compactacion" real es tirar la conversacion
   ENTERA y reconstruir con `[history[0], resumen_para_prompt(estado, faltan)]` — plantilla
   determinista, sin LLM, tope 1200 chars, con "SOLO FALTA:" blindado contra el truncado.
5. **`/compactar` del CLI (`cli.py:3003`) es COSMETICO**: `_console.clear()` + repintar el
   panel de arranque + mostrar las ultimas 5 interacciones. **No toca `_history`.**
6. En **chat** (no agente): `_history[-16:]` (`cli.py:12033`) + una recap **extractiva** sin LLM
   (`SessionSummarizer.extract_summary`) disparada por `recap_policy.should_recap`, inyectada
   DENTRO del ultimo mensaje user para no invalidar el prefijo KV.

**Consecuencia buena**: no existe la compresion acumulativa que el encargo quiere evitar; nadie
resume un resumen. **Consecuencia mala**: tampoco existe la compresion INTELIGENTE; o cabe, o se
trunca a 200 chars, o se reinicia el ciclo.

---

## 3. LOS 5 HUECOS REALES QUE HAY QUE CONSTRUIR

### HUECO 1 — El disparador de la lobotomia no existe: el `usage` real se mide y se TIRA

`loop.py:1077` lee `resp.usage.prompt_tokens` para decidir el recorte y lo descarta.
`harness/contexto_vivo.registrar_uso()` / `registrar_contexto()` existen, estan testeados y
**no los llama nadie**: la barra que pinta `cli.py:8354` lee un acumulador siempre vacio y cae
al `/props` del server. Hoy la unica politica es "recortar al 80% del n_ctx", que es una politica
de SUPERVIVENCIA, no de CICLO.
Falta: un `debo_cortar_ciclo()` que combine (a) ocupacion real de ventana (`contexto_vivo`),
(b) veredicto de `presupuesto_progreso` (estancado / meseta de coste x5), (c) los ejes de
`harness/limites` — segundos, tokens, USD — que estan **huerfanos totales, cero importadores**.
Prueba en el CLI: `/costo` mostrando numeros del backend y un `COGNIA_CICLO_UMBRAL=0.6`.

### HUECO 2 — El canal de estado no tiene las bandas de MAYOR persistencia ni sobrevive al proceso

`canal.py` ya define las secciones exactas del encargo (`restricciones` / `decisiones` /
`pendientes` / `ficheros` / `verificaciones` / `comandos`) con la regla dura de que las
restricciones **nunca se recortan** y de que todo recorte se anuncia. Pero:

- `anotar_restriccion`, `anotar_decision`, `anotar_pendiente`, `resolver_pendiente`: **cero
  llamadores en produccion**. El agente nunca escribe una restriccion ni una decision — o sea,
  la banda de mayor persistencia esta VACIA en cada corrida real.
- `guardar` / `cargar` / `serializar` / `deserializar`: **cero llamadores**. El canal muere con
  el proceso, y los ciclos de horizonte NO lo transportan (usan `estado_tarea.json`, otro
  almacen con otro esquema).
- `sembrar_trazadores` / `comprobar_trazadores` / `conservacion`: **cero llamadores**. La
  medicion que demuestra que el canal funciona no corre nunca en produccion.
- `render` se reinyecta **solo tras un recorte**, no en cada paso.

Falta: (a) extraccion de restricciones/decisiones del enunciado y de las respuestas (o una tool
`anotar_restriccion` que el modelo invoque, o un hook en `interceptor.antes`), (b) `guardar`/
`cargar` en el corte de ciclo, (c) **UN solo almacen** en vez de `canal` + `estado_tarea` +
`project_memory` + `bitacora` con cuatro esquemas distintos.

### HUECO 3 — El outer loop existe pero esta capado a 3 ciclos y su delta es ciego a lo verificado

`horizonte.ciclos_con_contrato` es el ciclo pedido, pero:

- `_TECHO_CICLOS = 3` es **duro** (`max_ciclos_env` hace `min(n, 3)`). Para "horas o dias" hacen
  falta decenas o cientos de ciclos.
- El delta sale **solo** de `estado_tarea.resumen_para_prompt` (hitos de GoalContract + archivos
  tocados + ultimo error). **No incluye el canal de estado** (restricciones, sha de ficheros,
  comandos con exit code) ni un handle al corpus RLM.
- El corte por progreso monotono compara `satisfied_count` del GoalContract **derivado del
  enunciado**; si la tarea no genera criterios verificables, `contrato_ok=None` y corre **un
  solo ciclo** — para tareas exploratorias el modo no hace nada.
- El sello resuelve rutas relativas contra el **CWD del proceso**, no contra el workspace del
  agente (limitacion declarada en el propio docstring de `horizonte.py`).

Falta: N ciclos sin techo con corte por presupuesto/estancamiento, delta = `estado_tarea` +
`canal.render` + handle RLM, y un contrato utilizable para tareas sin criterios derivables.

### HUECO 4 — No hay provenance ni confianza en NINGUN almacen

El encargo pide anti-alucinacion con provenance + confianza. Lo que hay:

- `search/evidencia.verificar_cita` (comparacion literal cita/fuente, sin juez) — **solo para
  paginas web del pipeline de investigacion**.
- `canal.py` guarda evidencia dura (sha256, bytes, exit code) pero **solo de ficheros y
  comandos**; una afirmacion en prosa del modelo no tiene donde anotarse con su origen.
- `memory/episodic` tiene un campo `confidence`, pero se llena por heuristica emocional
  (`vectors.analyze_emotion`), no por evidencia.
- `long_term_consolidator` promueve a "hecho" del KG por **repeticion** (>=3 ocurrencias): un
  agente que repite tres veces la misma invencion la asciende a hecho permanente. Antipatron
  activo y cableado.

Falta: un registro `hecho = {texto, origen (tool+args+sha | url | paso), confianza,
verificado_por}` donde **nada entra sin origen**, con la doctrina de `flujos/examen.py` (nada se
activa por haber salido bien) y el molde de `inmune/anticuerpos.py` (chequeo que corre, no prosa).

### HUECO 5 — El agente CRITICO existe pero es el mismo modelo, y no corre en el ciclo

`workflows.criticar()` es un critico real (N lentes en paralelo, schema, quorum, y distingue
"se cayo" de "no encontro nada"). Pero:

- por defecto usa el **mismo modelo y el mismo backend** que el ejecutor, y la memoria del repo
  es explicita: *"cinco instrumentos aprobaron algo roto en una noche; ninguno fallo"*;
- **no esta en el ciclo del agente**: solo se alcanza si el modelo llama la tool de workflows;
- `harness/oraculo.py` (el canal para preguntarle a un modelo distinto, con rol, tope anti-abuso
  y transporte inyectado) esta publicado como tool pero **el bucle nunca lo invoca solo**;
- `autopsia/causal.py` (precision@1 = 1.000 por replay contrafactual) es el critico BUENO —
  porque no opina, re-ejecuta — y solo corre a mano por `/autopsia`.

Falta: un **paso de critica obligatorio en el corte de cada ciclo**, ejecutado por un modelo
DISTINTO (Qwen3.8-27B via `oraculo`) o por verificacion ejecutable, que juzgue el resumen que va
a sobrevivir a la lobotomia — porque un resumen mal hecho es el unico error de esta arquitectura
que se propaga a TODOS los ciclos siguientes.

---

## 4. NO REINVENTAR — mapa rapido de lo que ya se puede tomar

| Necesidad del encargo | Pieza que YA existe | Estado |
|---|---|---|
| Ciclo comprimir -> destruir -> arrancar limpio | `agent/horizonte.py` | cableado, opt-in, techo 3 |
| Estado que sobrevive a la destruccion | `agent/estado_tarea.py` + `estado/canal.py` + `agent/bitacora.py` | tres almacenes; uno a medio cablear |
| Recuperar "solo lo necesario" | `agent/rlm.py` (`ContextoVivo` + `rlm_grep`) + `context/context_engine.retrieve` (gap-fill) | ambos cableados |
| Evitar resumen-de-resumen | `estado_tarea.resumen_para_prompt` (plantilla determinista, sin LLM) | cableado |
| Memoria por persistencia | secciones de `canal.py` + `recap_policy.MEMORY_LEVELS` | definido, sin escritores |
| Agente critico separado | `workflows.criticar` + `autopsia/causal` + `harness/oraculo` | existen, no en el ciclo |
| Multiagente con contexto destruido | `delegar_subtarea` (contexto fresco, tools por rol, solo 600 chars vuelven) | cableado |
| Anti-alucinacion ejecutable | `agents/goal_contract`, `flujos/examen`, `inmune/anticuerpos`, `search/evidencia` | cableados menos `evidencia` |
| Presupuesto y corte honesto | `estado/presupuesto_progreso` (ON) + `hermes/presupuesto_turno` (ON) + `harness/limites` (HUERFANO) | falta el eje tiempo/tokens |
| Ocupacion real de ventana | `harness/contexto_vivo` | huerfano justo donde importa |
| Deshacer / rebobinar / autopsia | `harness/checkpoints`, `multiverso/instantanea`, `autopsia/replay`, `autopsia/causal` | cableados |
| Presupuesto aprox. constante | `memory/memory_budget` (patron de purga por valor) + 1 solo slot en :8080 | patron reusable en otro almacen |
| No invalidar el KV entre ciclos | patron de `_build_stream_messages`: el bloque variable va DENTRO del ULTIMO mensaje user | cableado en chat, NO en el agente |

## 5. HUERFANOS CONFIRMADOS (cero importadores fuera de tests / del propio paquete)

- `cognia/harness/limites.py` — huerfano TOTAL (solo citado en docstrings ajenos).
- `cognia/harness/contexto_vivo.registrar_uso` / `registrar_contexto` — funciones huerfanas.
- `cognia/estado/canal.py`: `anotar_restriccion`, `anotar_decision`, `anotar_pendiente`,
  `resolver_pendiente`, `sembrar_trazadores`, `comprobar_trazadores`, `conservacion`,
  `serializar`, `deserializar`, `guardar`, `cargar` — **11 funciones huerfanas de 15**.
- `cognia/context/context_window_manager.py` + `injection_prioritizer.py` — huerfanos en el CLI
  (viven solo en `cognia_desktop_api.py` / `language_engine.py`).
- `cognia/context/session_warm_starter.py` — huerfano en el CLI.
- `cognia/memory/narrative.py` — solo `/narrativa`; sin test.
- `cognia/memory/hierarchical.py` — solo alcanzable por `/chimera`.
- `cognia/semantic_cache.py` — huerfano en el CLI.
- `cognia/estado/medicion_conservacion.py` — huerfano POR DISENO (banco de medicion).
- `cognia/multiverso/especulacion.py` — cableado pero OFF por defecto y con KILL medido.

Sin test propio: `memory/narrative.py`, `memory/project_memory.py`, `autopsia/motor.py`.

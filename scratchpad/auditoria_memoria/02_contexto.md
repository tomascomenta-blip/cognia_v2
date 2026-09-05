# Auditoría 02 — Ciclo de vida del contexto en el agente (`bucle_nativo`)

Fecha 2026-09-04. Repo `cognia_v2`, servidor vivo en :8080 = `qwen3.8-27b` (IQ2_M), `n_ctx=65536`, perfil `max_tokens=8192`, régimen nativo. Todas las líneas son de la copia actual del repo.

Números base (para 65.536 de ventana):
- capacidad útil = n_ctx − 1024 (`contexto_vivo.HEADROOM_TOKENS`, contexto_vivo.py:129) = **64.512**
- umbral de compactación/recorte = ceil(0.8 × 64.512) = **51.610** "tokens" (compactacion.py:283 `umbral_tokens`)
- cola retenida por la compactación = int(65536 × 0.16) × 4 = **41.943 chars** (compactacion.py:319)
- cap del resumen = **4.000 chars** (compactacion.py:88)
- emergencia = 0.92 × 65.536 = **60.293** (loop.py:1154, 3725)
- válvula pre-llamada: dispara si n_ctx − prompt − 512 < 4.096, o sea prompt > **60.928** (presupuesto_salida.py:52,61,134)
- clamp de salida: max_tokens 8192 solo cabe entero si prompt ≤ **56.832** (presupuesto_salida.py:81)
- el server rechaza (HTTP 400 `exceed_context_size`) en **65.536** reales.

---

## 1. Flujo del prompt por turno (qué entra, en qué orden, fijo vs mutable)

1. cli.py:28040-28082 `_run_agent_task_cuerpo` llama `bucle_nativo(task, system_agente_nativo(_perfil_modelo), completar, schemas_para(_tool_filter), …, history, _actions_trace, …)`; con `COGNIA_HORIZONTE=1` lo envuelve `ciclos_con_contrato` (cli.py:28065).
2. **history[0]** lo arma cli.py:27249 `_history_inicial_agente`: `[<memoria> bloque HYDRA (cli.py:1300)][índice de skills: 4.223 chars hoy][prior_ctx: 2 tareas previas de ~/.cognia_agent_state.json, 1500+400 y 300+150 chars (cli.py:27578-27600)]TAREA: <task>` — más guidance/hint que cli mete en history antes del bucle. Es UN string y es el "user del objetivo" intocable.
3. loop.py:1380 `_PESO_FIJO["schemas"] = _peso_schemas(schemas)`: los schemas viajan en cada petición fuera de `mensajes`. Medido hoy con /tokenize: 73 tools = 28.215 chars = **7.603 tokens** (chars/4 dice 7.053).
4. loop.py:1536-1551 ventana: `perfil["n_ctx"]` viene de `/props` (backend_activo.py:154, TTL 60 s, un fallo ya NO se cachea: 216-224); si sigue vacía se re-sondea `n_ctx_del_backend` (model_profiles.py:230) y si no, `_N_CTX_ASUMIDO=32768` (loop.py:1153) y se avisa.
5. loop.py:1562-1566: `mensajes = [{"system": system}, {"user": "\n\n".join(history)}]`. `mensajes_dump` (1570) es alias para el volcado de trazas.
6. **System** (model_profiles.py:657): `_IDENTIDAD` 266 + `_CONDUCTA_COMPLETA` 1.269 + `_ROL_AGENTE_NATIVO` 748 + `entorno_agente()` 102 chars (SO, shell, cwd) + sufijo del harness de la familia. Total 2.391 chars = **640 tokens medidos**. Fijo dentro de una sesión (el cwd está en el entorno; cambia con `cd`). No hay nada por-turno en el system.
7. loop.py:1873: si el contrato del encargo tiene ≥3 requisitos, un user "arranque por hitos" (COGNIA_ARRANQUE_HITOS).
8. Cada paso, ANTES de llamar: loop.py:2167/2207/2241 posibles users de aviso (pared de tiempo, sugerencia de estancamiento del gobernador `_prog`).
9. loop.py:2362-2378 válvula: si `hay_sitio_para_trabajar(n_ctx, _tokens_prompt(mensajes))` es False → `_compactar_por_resumen(…, 10**9)` o `_recortar_mensajes(…, 10**9)` (forzados por encima del umbral).
10. loop.py:2391 `completar(mensajes, tools=schemas, **_sampling_ventana(), **_kwargs_stream())`. `_sampling_ventana` (1922) clampa `max_tokens` a n_ctx − prompt_est − 512 con piso `MIN_TOKENS_RAZONADOR`. `cache_prompt` va por defecto (true); solo se manda `false` tras un cambio de LoRA (chat_client.py:993-995).
11. loop.py:2400-2560 reintentos del mismo paso: apagar pensamiento / compactar si el corte fue por ventana (2516-2518) / rampa max_tokens ×2 hasta `_TECHO_REINTENTO = max(16384, 4×8192) = 32768`; si aun así, user "AVISO DEL SISTEMA … por partes" (2562).
12. loop.py:2612 `_anotar_uso_vivo(resp, n_ctx, mensajes)` → barra de contexto (contexto_vivo).
13. loop.py:2735-2780 error del backend: `errores_backend.clasificar` → `contexto_excedido` (reintentable + comprimir, errores_backend.py:323) → `_compactar_por_resumen` → `_recortar_mensajes` → `_recorte_de_emergencia` con `_n_ctx_de_error(resp.error)` (1158) → reintento ≤2 (`_reint_backend`, se resetea a 0 cuando el backend contesta bien: 2822). Si no libera nada: `break` con texto "(el agente no pudo hablar con el modelo: …)" y la tarea muere (2803-2818).
14. loop.py:3056 `mensajes.append(mensaje_assistant(resp))` (chat_client.py:1192): `content` + **`reasoning_content` entero** + `tool_calls[].function.arguments` = el JSON crudo (un `escribir_archivo` de 40 KB queda entero en el historial y se reenvía cada paso).
15. loop.py:3092-3121 (args cortados → rescate) / 3455-3550 tool normal: `run_tool` → `interceptor.py:347 offloading.formatear_observacion` (umbral 2.000 bytes; 32.768 para `leer_archivo/leer_lote/recuperar/ver_salida`, offloading.py:139-171) → `mensajes.append(mensaje_tool(tc.id, resultado_msg))` (3550). Además `history.append(resultado)` y `trace.append({action,args[:200],ok,result_head[:160]})` (3501-3502).
16. loop.py:3552-3563 users opcionales tras la tool: aviso del guardia de bucle, aviso por fichero, "AVISO: ya llamaste…".
17. loop.py:3471-3487: el canal de estado anota fichero (sha/bytes medidos), comando y verificación. NO se reinyecta en cada paso (solo en 20).
18. loop.py:3617/3636 "ALTO: las últimas N herramientas fallaron" como user.
19. loop.py:3659-3680 estimación: `est = usage.prompt_tokens` (o chars/4 de `mensajes[:idx_turno]` si el stream no trajo usage) + chars/4 de content+reasoning de lo apendeado en ESTE turno (+ `_PESO_FIJO["schemas"]` si fue estimado). **Bug de cuenta**: los `arguments` de las tool_calls de este turno no se suman (solo content+reasoning, 3669-3676); `_tokens_prompt` (710) sí los cuenta pero solo lo usan la válvula y el clamp.
20. loop.py:3688 `_compactar_por_resumen` (umbral 0.8) → si devuelve None/0, loop.py:3704 `while _recortar_mensajes(…)` → loop.py:3725 emergencia si `est ≥ 0.92·n_ctx` → loop.py:3737-3748 reinyección del canal (`_canal.render(_estado, 1200)`) SOLO si liberó el truncado y no hubo resumen.
21. loop.py:3752 `_anotar_ocupacion_viva(est)` (footer) y 3784 nudge del vigilante de razonamiento (user).
22. Cierre: loop.py:3942-3953 volcado de traza (solo `COGNIA_TRAZAS=1`); cli.py:28694-28711 `~/.cognia_agent_state.json` (últimas 5 tareas, task[:2000] + result[:600]); cli.py:25060 `/hacer` explícito → solo `_session_log` en memoria (**no** pasa por `_persist_turn`; la acción inferida desde el chat sí: cli.py:26289).

**Qué es fijo y qué muta (prompt cache de llama.cpp).** Prefijo estable: system (640 tok) + tools renderizados por la plantilla (≈7.6k tok) + user[0] (índice de skills + memoria + tarea; cambia por tarea, no por paso). Después, el historial es append-only en el camino feliz: cada paso añade assistant + tools + users al final → el cache reusa todo. Lo que ROMPE el prefijo: (a) `_recortar_mensajes` muta los turnos MÁS VIEJOS (3 por pasada, y se itera en `while`) → re-prefill desde el primer turno tocado, cada pasada; (b) `_truncar_args_escritura` muta assistants viejos; (c) `compactar` hace UN splice en la posición 2 (una sola invalidación, por diseño); (d) `_recorte_de_emergencia` toca TODO, incluido el último assistant, y hace pop de los viejos → prefill completo; (e) `mensajes = None` en los cortes por bucle (3251, 3300). Los users de aviso van al final y no cuestan cache.

---

## 2. Tabla de mecanismos de contexto

| Mecanismo | Cuándo dispara | Qué hace | Qué información PIERDE | Dónde queda lo perdido | Dónde |
|---|---|---|---|---|---|
| Offloading de observaciones | resultado de tool > 2.000 bytes (32.768 en tools de lectura); exentas `recuperar`, `delegar_subtarea`, `skill_leer` | guarda el texto completo en disco; el modelo ve cabeza 15 + cola 5 líneas (lectura: 200 líneas) + handle `res:xxxxxx` + ruta | las líneas del medio salen del contexto activo; el modelo tiene que pedirlas por handle | `~/.cognia/offload/<sesion>/res-xxxxxx.txt/.json` (309 sesiones hoy); recuperable con la tool `recuperar` | interceptor.py:347; offloading.py:565 `guardar`, 714 `resumir_para_modelo`, 894 `recuperar` |
| Truncado de args de escritura | dentro de recorte/compactación/emergencia, solo por encima del umbral; assistants anteriores al último con `escribir/editar/apendar` y args > 2.000 chars | cada valor string largo → 20 chars + `… (argumento truncado: el contenido ya esta en el fichero)`; el JSON sigue válido | el contenido escrito deja de estar en la conversación (el modelo ya no puede "verlo" sin releer) | el fichero mismo en el workspace; el previo en `~/.cognia/checkpoints/<sesion>/blobs/NNNN.bak` | loop.py:983 `_truncar_args_escritura`, 804 `_truncar_valores_args`; checkpoints.py:270 |
| Recorte por mordiscos (`truncado`) | `prompt_tokens ≥ 51.610` (0.8 de la capacidad útil); fallback cuando el resumen devuelve None/0; forzado (10**9) en la válvula y en el reintento por 400 | 3 mensajes por pasada, iterado en `while` (loop.py:3704): tool > 400 chars → 200 chars + marca; `RESULTADO leer_archivo` → 4.000 chars + `leer_archivo <ruta> offset=N`; reasoning de assistants viejos > 400 → 200 chars | salidas de tools de 400–2.000 bytes (errores literales, listados, salidas de tests cortas) y todo el CoT viejo | **nada** (los resultados < 2.000 bytes nunca se offloadearon; el CoT no se guarda) salvo `COGNIA_TRAZAS=1` | loop.py:1044 `_recortar_mensajes`, 1021 `_recortar_leer_archivo`; telemetría compactacion.py:167 |
| Compactación por resumen (modo por defecto) | mismo umbral 51.610; también forzada con 10**9 | `viejos = mensajes[2:corte]`, cola retenida ≈ 41.943 chars; los viejos se vuelcan en JSON a disco y se reemplazan por UN user `[RESUMEN DE COMPACTACION]` ≤ 4.000 chars: línea del volcado, OBJETIVO (400 chars de la última `TAREA:`), ARTEFACTOS (rutas de escribir/editar/borrar), PROXIMOS PASOS (`estado["pendientes"]` → **siempre "ninguno registrado"**: nadie llama `anotar_pendiente`), bloque del canal (1.200), TOOLS DESCARTADAS (1 línea/tool: nombre, args[:80], OK/FALLO, spill) con las más nuevas primero | el texto de cada resultado, la prosa y el CoT del modelo, los users de aviso, los args; las líneas de tools más viejas si no caben en 4.000 | `~/.cognia/offload/<sesion>/res-xxxx.txt` (`tool="compactacion"`, JSON de los mensajes); recuperable con `recuperar` si el modelo lee la cabecera | loop.py:1223; compactacion.py:286 `compactar`, 258 `_volcar_historial` |
| Recorte de emergencia | `est ≥ 60.293` (0.92·n_ctx) tras compactar, o en el reintento por 400 cuando nada más liberó | TODO reasoning → 200 chars (también el último assistant), tool > 600 → 400, args de TODAS las escrituras; luego `pop` de los mensajes más viejos (tras system+user) hasta bajar de 0.8·n_ctx dejando 6 de cola; inserta un user "se descartaron N mensajes viejos" | mensajes enteros (assistant + sus tools) y el CoT vivo del turno | **nada**: no vuelca a disco (a diferencia de compactar) | loop.py:1165 `_recorte_de_emergencia` |
| Válvula antes de llamar | `disponible = n_ctx − prompt − 512 < 4.096` | compacta/recorta ANTES de pagar una generación que no puede cerrar | las mismas que resumen/truncado | ídem | loop.py:2362-2378; presupuesto_salida.py:134 |
| Clamp de max_tokens | `max_tokens > n_ctx − prompt − 512` | baja el tope de salida del paso (piso `MIN_TOKENS_RAZONADOR`) | capacidad de salida: tool calls largos se cortan a media cadena (→ rescate parcial 895 `_rescatar_escritura`) | el trozo rescatado va al fichero en disco | loop.py:1922 `_sampling_ventana`; presupuesto_salida.py:81 |
| Reintento por 400 `exceed_context_size` | `resp.ok=False` y `clasificar()` → `contexto_excedido` | resumen → truncado → emergencia con el n_ctx del JSON del error; ≤2 reintentos seguidos con refund | las de cada capa; si nada libera, la TAREA muere con el texto parcial | — | loop.py:2735-2780; errores_backend.py:170-193, 323 |
| Canal de estado | anota en cada tool (fichero/comando/verificación); se REINYECTA solo si el truncado liberó y no hubo resumen | `render(estado, 1200)` como user: restricciones, ficheros (sha/bytes), pendientes, verificaciones, decisiones, comandos | nada por sí mismo; pero restricciones/pendientes/decisiones nunca se pueblan desde el loop (solo `anotar_fichero/comando/verificacion`) | solo memoria de proceso: `canal.guardar` (canal.py:619) no tiene ningún llamador | loop.py:1448, 3471-3487, 3737-3748; canal.py:366 |
| Corte por bucle/estancamiento | `GuardiaBucle` bloqueo o `register_action` == stop | `_parchear_huerfanos` y `mensajes = None`; `break` | la conversación entera del /hacer | nada (salvo `COGNIA_TRAZAS=1` → `<dir_trazas>/<task_id>.json`) | loop.py:3250-3251, 3299-3300; traza_chatml.py:83, 146 |
| Horizonte (opt-in `COGNIA_HORIZONTE=1`) | ciclo ≥2 cuando el contrato no sella | `hist_ciclo = [history[0], prompt_de_ronda(resumen_para_prompt ≤1.200 chars, handoff ≤16.384)]`: worker FRESCO, KV nuevo | toda la conversación del ciclo anterior salvo hitos/faltan/archivos/último error/report de 5 campos | `~/.cognia/data/tareas/<id>/estado.json` + `bitacora.jsonl` (eventos del bus) | horizonte.py:520-535; estado_tarea.py:109, 166; bitacora.py:50 |
| RLM (`/rlm`, `cognia rlm`) | solo cuando el usuario lo invoca; NO lo usa /hacer | el corpus vive en `ContextoRLM/ContextoVivo` fuera de `mensajes`; el raíz lo explora con `ctx_info/ver/grep/partir` (8.000 chars por vista) y `rlm_llamar` (hijo fresco sin tools, 60k chars) | nada: el corpus entero queda fuera y se pide por trozos | memoria de proceso (índice sobre chat_history + ficheros) | rlm.py:88-91, 189, 338, 1180; cli.py:1137-1264 |
| Checkpoints | antes de cada escritura de fichero | snapshot del contenido PREVIO; `/deshacer` | — (no es de contexto) | `~/.cognia/checkpoints/<sesion>/indice.jsonl + blobs/` | checkpoints.py:270 `registrar(ruta, contenido_previo, motivo)` — **confirmado: solo ficheros, no hay estado de tarea** |
| Estado entre tareas | al terminar `_run_agent_task_cuerpo` | `tasks[-5:]` con task[:2000], result[:600], `files_touched` | todo lo intermedio | `~/.cognia_agent_state.json` (no en sesión efímera) | cli.py:27562-27600 (lectura), 28694-28711 (escritura) |

---

## 3. El "ciclo de la muerte" (n_ctx = 65.536, medido hoy)

```
coste fijo por petición ≈ system 640 + tools 7.603 + user[0] (skills 4.223 chars ≈1.1k + memoria + tarea) ≈ 9–10k tok
                                    │
paso k: + assistant (CoT hasta 8k tok + args de escritura hasta 40 KB ≈ 10k tok) + tool (≤ ~800 tok si offload; ≤ 8k si leer_archivo)
                                    │  chars/4 SUBESTIMA (medido: −7 % prosa/esquemas, −19 % salidas de tools, −22 % JSON)
                                    ▼
[est < 51.610]  crecimiento libre; el footer pinta '~' si el stream no trajo usage
                                    │
[est ≥ 51.610 = 0.8·(n_ctx−1024)]   compactar(): 1 splice → [system, user0, RESUMEN ≤4.000 chars, cola ≈41.943 chars]
   pierde: texto de resultados, CoT, prosa; queda 1 línea/tool (args[:80], OK/FALLO) y el JSON crudo en offload
   si 'el resumen no libera chars' o 'nada viejo que fundir' (cola > todo)  ──► devuelve 0 ──► truncado
                                    │
truncado: while _recortar_mensajes() → 3 mordiscos/pasada (tool→200 chars, leer→4.000+puntero, CoT viejo→200)
   cada pasada MUTA el principio del historial → la KV cache se reprefillea desde ahí
   pierde: resultados de 400–2.000 bytes (no offloadeados) sin copia en disco
                                    │  vuelve a crecer: la cola retenida (~10.5k tok est., ~11.3k reales) + fijo 10k ya son un tercio
[est ≥ 60.293 = 0.92·n_ctx]         emergencia: TODO CoT→200, tools→400, args; pop de viejos hasta 0.8 dejando 6; SIN volcado
                                    │
[prompt > 60.928]                   válvula: compacta forzado antes de llamar (10**9); si no hay nada compactable "este paso puede no cerrar"
[prompt > 56.832]                   clamp: max_tokens < 8192 → tool calls cortados → rescate parcial → "escribe por partes" → más turnos
                                    │
[real > 65.536]                     HTTP 400 exceed_context_size → resumen/truncado/emergencia (n_ctx del error) → 2 reintentos
                                    │  si nada libera → "(el agente no pudo hablar con el modelo…)" → tarea muerta, parcial entregado
                                    ▼
tras cada compactación: el modelo sigue con ARTEFACTOS + 1 línea/tool; "PROXIMOS PASOS: ninguno registrado" SIEMPRE;
lo que no cabe en 4.000 chars ("… N líneas más viejas omitidas") solo vuelve si el modelo llama `recuperar res:xxxx`.
```

Por qué el ciclo se repite: la compactación retiene 0.16·n_ctx de cola INTACTA (incluidos CoT y args truncados solo si > 2.000) y el coste fijo es ~10k, así que tras compactar el prompt arranca en ~22–25k y con 3–4 pasos de escritura grande vuelve a 51k; cada vuelta funde el resumen anterior (idempotente) pero el cap de 4.000 chars hace que las líneas de tools más viejas se caigan. Con streaming sin chunk de usage (`usage_estimado`, chat_client.py:852) TODO el estimado es chars/4 y la compactación dispara un 7–22 % tarde (medido en §6): 51.610 estimados son 55–63k reales, ya dentro de la zona de emergencia/válvula.

---

## 4. Qué cumple y qué no del diseño "memoria externa → retrieval → context builder → contexto activo"

**Ya cumple (con evidencia):**
- Memoria externa de observaciones: offloading a disco con handle y dedup por sha (offloading.py:565); compactación vuelca el historial descartado en JSON (compactacion.py:258). Checkpoints de ficheros (checkpoints.py:270). Horizonte persiste `estado.json` + `bitacora.jsonl` (estado_tarea.py:78; bitacora.py:39-50). `chat_history` (sqlite, `cognia_memory.db`, database.py:215; memory/chat.py:51 `log`) guarda turnos user/assistant con `session_id` y `cwd`.
- Retrieval a demanda del modelo: tool `recuperar` (offloading.py:894/1029; registrada en tools.py:392 gateada por `COGNIA_OFFLOAD`), `bitacora_buscar`/`tarea_estado` (solo horizonte), RLM `ctx_grep` (solo `/rlm`). Retrieval de memoria semántica al ARRANCAR la tarea: bloque HYDRA `_build_memory_block_for` (cli.py:1300) en history[0].
- Contexto fresco con traspaso determinista: horizonte (`prompt_de_ronda` + `resumen_para_prompt` + report ralph) — pero opt-in y solo entre ciclos, no dentro del bucle.
- Canal de estado inmune al resumidor (canal.py) con hechos medidos (sha/bytes/exit).

**NO cumple (verificado con Grep):**
- No hay Context Builder: el prompt es `system + user0 + lista creciente`; los mecanismos son SUSTRACTIVOS (resumir/truncar/pop). El único constructor es `horizonte.prompt_de_ronda` (fuera del bucle).
- No hay retrieval selectivo del historial propio desde el arnés: nada relee automáticamente el JSON de la compactación ni los offloads; solo el modelo con `recuperar` y solo si retiene el handle de la cabecera del resumen. `grep -rn "recuperar(" cognia --include=*.py` fuera de offloading/tools → 0 usos del arnés. No hay índice (lexical/embedding) sobre resultados de tools del /hacer en curso.
- No hay checkpoint de tarea con `next_action`: `grep -rln "next_action|siguiente_accion|proxima_accion|checkpoint_tarea"` → 0 ficheros. Lo más cercano: `estado_tarea.faltan` (criterios del contrato) y `report.nextSteps` (ralph), ambos solo con `COGNIA_HORIZONTE=1` (cli.py:27984-28025 `_hz_task_id` vacío sin el flag). El canal tiene `pendientes` pero el loop nunca llama `anotar_pendiente/anotar_restriccion/anotar_decision` (loop.py: solo `anotar_fichero/comando/verificacion` en 3114, 3471-3487).
- El canal de estado no se persiste (`canal.guardar` sin llamadores fuera de canal.py) ni se reinyecta cada paso (solo loop.py:3742 tras truncado).
- Recuperación tras crash: `/hacer retomar` existe solo con `COGNIA_HORIZONTE=1` (cli.py:25011) y considera huérfana una tarea `en_curso` con `estado.json` sin tocar > 15 min (estado_tarea.py:40, 232). `cognia hacer` (cli_hacer.py:105-136) no tiene retomar. `/resume` (cli.py:18962) y la continuidad al arrancar (cli.py:23105-23125, `_HISTORY_SEED_N=20`, por cwd) restauran SOLO turnos de chat de `chat_history`: la conversación de un `/hacer` explícito no se persiste (cli.py:25056-25065 → `_session_log` en memoria; `_persist_turn` solo en 26289 = acción inferida desde el chat, 11747 `/skill`, 12200 `/largo`, 25356 `/flujo`).
- **Si el proceso muere a mitad de un /hacer** queda en disco: los ficheros escritos (+ checkpoints de sus previos), los offloads `res-*.txt` de esa sesión (sin índice de qué tarea eran), `bitacora.jsonl`/`estado.json` solo con horizonte, la traza solo con `COGNIA_TRAZAS=1`. NO queda: la tarea en curso (agent_state se escribe al FINAL, cli.py:28694), el canal de estado, el plan/pendientes, el historial `mensajes`. Al reabrir el REPL no se ofrece retomar nada.
- Tokenizer: no hay (ver §6). La cuenta del delta del turno omite los args de tool_calls (loop.py:3669-3676).

---

## 5. Puntos de inserción propuestos

**(a) Context Builder que reemplace al crecimiento cuando se supera el presupuesto**
- Punto principal: loop.py:3659-3760 (fin de paso), sustituyendo la cadena `_compactar_por_resumen → while _recortar_mensajes → _recorte_de_emergencia → reinyección del canal`. Locales disponibles: `mensajes` (lista viva; `mensajes_dump` es alias), `idx_turno`, `resp` (usage, reasoning_content, tool_calls), `est`, `perfil["n_ctx"]`, `_estado` (dict del canal) y `_canal` (módulo), `_prog` (avances), `_muta` (ficheros escritos/fallidos), `_contrato` (en `ctx["_contrato"]`), `history`, `trace`, `ctx`, `schemas`, `_PESO_FIJO`, `print_fn`, `pasos`, `_pres`. Contrato sugerido: `construir_contexto(mensajes, n_ctx, presupuesto, estado, memoria) -> list` que conserve `mensajes[0:2]`, ponga UN bloque construido en la posición 2 (objetivo + estado del canal + next_action + resultados relevantes recuperados de offload/compactación por relevancia a la última intención `_intencion_de(resp)`) y la cola por tokens; un solo splice para no romper la KV cache (misma regla que compactacion.py:437).
- Mismos callers a redirigir: la válvula loop.py:2362-2378, el reintento por corte de ventana 2516-2518 y el 400 en 2750-2764 (los tres pasan `10**9` para forzar).
- Horizonte: horizonte.py:522-528 (`hist_ciclo = [history[0], prompt_de_ronda(...)]`) es donde ya se construye un contexto fresco; el builder debería ser la misma función.

**(b) Extracción de memorias tras cada tool result**
- loop.py:3455-3550: justo donde el canal anota (`_canal.anotar_fichero(_estado, _r, tc.nombre, ok=tool_ok)` 3471, `anotar_comando` 3484, `anotar_verificacion` 3487) y antes de `mensajes.append(mensaje_tool(...))` (3550). Locales: `tc.nombre`, `args_str`, `resultado` (texto completo tal como lo devolvió `run_tool`/interceptor, ya offloadeado si era grande), `resultado_msg`, `tool_ok`, `_estado`, `_canal`, `_muta`, `_prog`, `ctx` (workspace, `_contrato`, `agent_state`), `resp.reasoning_content` e `_intencion_de(resp)` (la razón por la que se llamó), `print_fn`, `pasos`.
- Alternativa tool-agnóstica: interceptor.py:347 (tiene `name`, `args`, `texto` y el handle del offload si lo hubo): ahí se puede indexar (handle, tool, args, cabeza, ok) en un índice por tarea para que el builder de (a) lo consulte sin depender del modelo.
- Ramas paralelas que también deben pasar por el mismo gancho: rescate parcial loop.py:3092-3121 y las ramas 3161/3213.

**(c) Checkpoint de tarea automático**
- loop.py:3752 (tras `_anotar_ocupacion_viva`, fin de cada paso): escribir `~/.cognia/data/tareas/<task_id>/checkpoint.json` con `{task, paso, next_action (de _intencion_de(resp) o del último tool_call pendiente), canal: _canal.serializar(_estado), ficheros: _muta.ficheros_escritos(), trace[-N:], handles de offload/compactación, contrato.faltan}`. Reusar `estado_tarea.guardar` (atómico tmp+replace, estado_tarea.py:78) y `canal.guardar` (canal.py:619). Locales: `pasos`, `mensajes`, `resp`, `_estado`, `_muta`, `trace`, `history`, `ctx["_traza_task_id"]`, `_contrato`, `_salida`.
- Para que exista `task_id` sin horizonte: cli.py:27984-28025 crea `_hz_task_id/_hz_estado` solo bajo `COGNIA_HORIZONTE=1`; hacerlo incondicional (bitacora.iniciar + estado_tarea.nuevo) y pasar el id en `ctx`.
- Cierre: cli.py:28694 (`_agent_state["tasks"].append`) es donde sellar el checkpoint como `completa/incompleta`.

**(d) Recuperación tras crash**
- `cognia hacer`: cli_hacer.py:105-136 `_hacer(args, tarea, progreso)` antes de `_cli._run_agent_task(ai, tarea, progreso, …)`: leer `estado_tarea.ultima_incompleta()` (quitar el gate de 15 min para el caso explícito `--retomar`) y pasar `guidance=resumen_para_prompt(estado, faltan)` + el checkpoint de (c). Locales: `args`, `tarea`, `progreso`, `ai`.
- REPL `/hacer retomar`: cli.py:25011 quitar `os.environ.get("COGNIA_HORIZONTE") == "1"`; ya llama `_run_agent_task(ai, _t, _print_line, guidance=resumen_para_prompt(...))` (25040).
- Arranque del REPL: cli.py:23105-23125 (bloque de continuidad; locales `ai`, `_history`, `_cwd_cont`, `_init_lines`) es donde detectar un `checkpoint.json` huérfano del mismo cwd y anunciar "hay una tarea a medias: /hacer retomar".
- Contexto previo dentro de la tarea: cli.py:27578-27600 (`_prior_ctx` desde `agent_state`) es donde inyectar el checkpoint en `history[0]` vía `_history_inicial_agente(ai, task, prior_ctx=...)` (27249).
- Persistir el /hacer explícito: cli.py:25056-25065 `_turno_hacer` no llama `_persist_turn`; añadirlo (o un `ch.log(role="agente", ...)`) para que `/resume` vea la tarea.

---

## 6. Tokenizer: qué hay y qué precisión tiene

- **No hay tokenizer en runtime.** Ni tiktoken ni llamadas a `/tokenize` del server: las menciones a `/tokenize` son de mediciones en comentarios (chat_client.py:827, workflows.py:64/924, ux/events.py:411). Las cuentas vivas son `len(...) // 4` en loop.py (`_tokens_prompt` 710, `_recorte_de_emergencia` 1195, est 3669-3680, `_anotar_uso_vivo` 1332) y compactacion.py (`_chars_msg` 200, `tokens_despues`). Existe `contexto_vivo.estimar_tokens` (contexto_vivo.py:311, chars/4 con CJK a 1/char) pero el loop no la usa. Otras constantes dispersas: `search/contexto.py:44 CHARS_POR_TOKEN=3.47`, `agent/tools.py:293 _ACI_CHARS_POR_TOKEN=3.5`, `tx/bandas.py:47 = 4`, `ux/spinner_vivo.py:59 = 4`.
- Lo único exacto es `usage.prompt_tokens` del server cuando llega (no-stream, o stream con chunk de usage); bajo streaming puede venir `usage_estimado=True` sin prompt_tokens (chat_client.py:852-858) y entonces todo el presupuesto es chars/4.
- **Medido hoy contra `http://127.0.0.1:8080/tokenize` (Qwen3.8-27B):**

| Texto | chars | tokens reales | chars/token | chars/4 | error de chars/4 |
|---|---|---|---|---|---|
| prosa en español | 159 | 38 | 4,18 | 39 | +3 % |
| JSON de tool call (`{"ruta":…,"contenido":"import pygame…"}`) | 218 | 69 | 3,16 | 54 | −22 % |
| `RESULTADO ejecutar (exit 0): … PASSED` | 175 | 53 | 3,30 | 43 | −19 % |
| `system_agente_nativo(perfil)` completo | 2.391 | 640 | 3,74 | 597 | −7 % |
| schemas del catálogo (73 tools) | 28.215 | 7.603 | 3,71 | 7.053 | −7 % |
| **total** | 31.158 | 8.403 | **3,71** | 7.786 | **−7 %** |

Conclusión: chars/4 subestima siempre en este modelo, entre 7 % (prosa/esquemas) y 22 % (JSON/código), que es justo lo que domina un historial de agente (args de tool calls y resultados). Un umbral estimado de 51.610 equivale a 55–63k tokens reales: la compactación dispara tarde y el 0.92 de emergencia (60.293 estimados) puede estar ya por encima de la ventana real. Arreglo barato: `_PESO_FIJO` medido una vez por tarea con `/tokenize` (una llamada de ~ms sobre system + schemas + user0) y un factor 3,5 chars/token para el resto, o directamente `/tokenize` del historial cuando `usage_estimado`.

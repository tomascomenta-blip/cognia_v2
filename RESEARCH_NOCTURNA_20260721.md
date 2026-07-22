# Investigación nocturna 2026-07-21 — OSS → componentes concretos para Cognia

> Sesión autónoma (deadline 04:30). Investigación profunda de ~40 proyectos/conceptos
> con 6 agentes en paralelo (búsqueda web verificada contra repos/APIs/papers). El
> objetivo NO era describir qué hace cada proyecto, sino identificar **componentes
> concretos reutilizables** (algoritmos, estructuras de datos, patrones) que aporten
> mejora medible a Cognia, bajo las restricciones duras del repo (solo-CPU en nodos,
> sin PyTorch en nodos, sin frameworks pesados, código plano, baja latencia/memoria).
> Complementa y actualiza `INTEGRACIONES_OSS_MAPA.md` (2026-07-14).

## Veredicto de existencia (honestidad primero)

| Nombre pedido | Veredicto | Nota |
|---|---|---|
| OpenHands, Aider, Goose, OpenCode | ✅ reales | dev-agents; ideas portadas (Goose=Rust, OpenCode=TS) |
| LangGraph, CrewAI, Dify, Langflow, n8n | ✅ reales | orquestación; se roba el patrón, no la dep pesada |
| OpenManus, DeerFlow, Agent Reach, Future AGI | ✅ reales | agentes autónomos Python |
| Manus | ✅ real (cerrado) | comercial; usar OpenManus como referencia abierta |
| OpenClaw | ✅ real (TS) | 383k★; "OpenClaude=rewrite del leak de Claude Code" = **folklore NO verificable** |
| Browser-Use, Scrapling, MarkItDown, Open Notebook | ✅ reales | web/datos |
| Graphify, Code Graph, GraphRAG | ✅ reales | grafos de código/conocimiento |
| whisper.cpp, Piper, Pipecat, Supervision, Cal.com, Plausible, Daytona | ✅ reales | voz/infra/analytics |
| OpenBMB (MiniCPM/ToolBench/XAgent/AgentVerse/ChatDev), Colibrí | ✅ reales | modelos/serving |
| Shepherd | ✅ real | `shepherd-agents/shepherd` (NO shepherd.js de tours UI) |
| Open Wiki | ⚠️ ambiguo | probablemente **DeepWiki**; OSS = `AsyncFuncAI/deepwiki-open` |
| JCode | ⚠️ ambiguo | dos repos: `1jehuang/jcode` (skills semánticas) y `cnjack/jcode` (SSH) |
| Orca | ⚠️ no es agente | método de destilación de razonamiento (Microsoft), no un dev-agent |
| Qwythos | ⚠️ no es agente | es un **modelo** 9B en HF (`empero-ai/Qwythos-9B`), benchmarks sin verificar |
| Hyperframes | ❌ falso positivo | render HTML→vídeo de HeyGen; nada de inferencia |
| Voicebox | ⛔ gated | pesos no liberados + GPU/PyTorch; usar **Piper** en su lugar |
| Modelos con GPU prestadas | ⚠️ mayoría vetada | Petals/exo/llama.cpp-RPC/prima.cpp = sharding WAN síncrono (PROHIBIDO) |

---

## 1. Dev-agents (OpenHands · Aider · Goose · OpenCode · JCode · Orca)

- **Aider — repo-map (grafo de símbolos + PageRank personalizado).** `RepoMap` construye
  un `networkx.MultiDiGraph` (nodos=ficheros; arista referrer→definer por identificador
  compartido), corre PageRank con vector de personalización sesgado a lo mencionado en el
  chat (×10) / ficheros abiertos (×50), distribuye el rank a las defs y renderiza bajo
  presupuesto de tokens (búsqueda binaria). Cache en SQLite por `(path, mtime)`.
  → **IMPLEMENTADO esta noche** como `cognia/knowledge/repo_map.py` + tool `repo_map`.
- **Aider — SEARCH/REPLACE con matching en cascada.** `do_replace`: exacto → tolerante a
  indentación → `...`. El fallo se devuelve como prompt (nombra el SEARCH + líneas parecidas).
  → **IMPLEMENTADO** como `cognia/agent/edit_block.py` + tool `editar_archivo`.
- **OpenHands — `LLMSummarizingCondenser` (RollingCondenser).** Cuando `len(events)>max_size`,
  conserva `keep_first` (system+objetivo) + los N recientes, y **resume el bloque intermedio**
  con el LLM. Interfaz `Condenser` desacoplada del bucle. Medido ~2× menos coste de contexto.
  → **BACKLOG (alto valor)**: ataca el cuello de botella real del modelo local (ventana chica).
- **OpenHands — eventos Action/Observation tipados (`LLMConvertibleEvent`).** Historial como
  lista de eventos tipados (no strings) → habilita condensar y validar la *acción* pre-ejecución.
  → mapea a evolucionar `cognia/events.py` + el punto de intercepción del Sentinel.
- **Goose — auto-compactación al 80% + tool-pair summarization.** Resume **outputs de tools
  antiguos** (los que más inflan el contexto) manteniendo los recientes en detalle.
  → **BACKLOG**: complementa al condenser (uno resume prosa, este outputs de tools).
- **OpenCode — LSP como verificador de edits.** El LLM propone el edit, un checker determinista
  lo valida (diagnostics, refs rotas). → para Cognia: `ast.parse`/`pyflakes`/`ruff` (CPU puro)
  como observación post-edit; find-references barato sobre el grafo de código.
  → **PARCIALMENTE IMPLEMENTADO**: `code_grafo` da find-def/find-refs sin language server.
- **JCode (1jehuang) — inyección semántica de skills por embeddings.** Las skills no se cargan
  todas: se embebe la conversación y se inyecta la skill por similitud (RAG de capacidades).
  → **BACKLOG**: escala capacidades sin inflar el prompt (embeddings ONNX ~90MB CPU).
- **Orca — Explanation Tuning + Cautious Reasoning.** Entrenar con la *traza de razonamiento*
  del maestro, y aprender a *elegir* estrategia (prompt-erasing). → técnica de datos/prompting
  para micro-expertos y prompts auto-mejorantes (sin reentrenar: esfuerzo S).

## 2. Orquestación (LangGraph · CrewAI · Dify · Langflow · n8n · Shepherd)

- **LangGraph — StateGraph = canales + reducers + super-steps (BSP) + checkpointer + interrupts.**
  Estado = dict de canales, cada uno con un reducer (`operator.add`, merge…); ejecución
  Bulk-Synchronous Parallel; checkpointer SQLite por `thread_id` (persistencia + time-travel);
  `interrupt()` para human-in-the-loop. → **el esqueleto** para unificar `flow.py` en un
  orquestador único; el checkpointer habilita el "revert al último verde" del disyuntor.
- **CrewAI — Crew/Agent/Task/Process (sequential vs hierarchical) + delegación-como-tool.**
  El jerárquico inyecta un manager que delega por string `role` con dos tools
  (`Delegate work`, `Ask question`). → tu 2-roles = sequential; tu oficina JEFE→DIR→TRAB =
  hierarchical; ambos bajo un campo `proceso`. **Riesgo medido:** el jerárquico añade 1 llamada
  de manager por ronda (latencia real en CPU) — medir vs sequential.
- **n8n — workflow=DAG JSON (`nodes`+`connections`) + contrato item-array `{json,binary}` +
  `pairedItem` (linaje).** Topología separada de nodos; dato siempre lista de items; linaje para
  cazar degradación silenciosa. → schema declarativo del pipeline sin editor visual.
- **Dify — `VariablePool` (dataflow por referencia `{{#node.var#}}`) + validación previa del grafo
  + `edge.sourceHandle` para ramas.** → alternativa a canales si el estado crece; validar antes
  de correr evita "backend cableado que no existe".
- **Langflow — schema-por-nodo (`template` autodescriptivo) + edges tipados (type-check del
  dataflow) + build topológico.** → validar params de cada rol/nodo desde el propio JSON.
- **Shepherd — snapshot COW reversible + propuesta→aceptar + firma-como-permisos.** Nada toca
  ficheros hasta aceptar; cada intento es propuesta sobre un fork; se aplica solo con verde.
  → **encaja con el disyuntor de reparación** (implementar el COW/propuesta en Python plano; el
  enforcement OS de Shepherd **no corre en Windows**).

## 3. Agentes autónomos (OpenManus · DeerFlow · Agent Reach · Future AGI · OpenClaw · Manus · Qwythos)

- **OpenManus — `PlanningFlow`: plan-and-execute con enum de estado de paso.** `PlanStepStatus`
  (`not_started/in_progress/completed/blocked`) con marcadores `[ ][→][✓][!]`; re-entra buscando
  "el primer paso no completado" (sin re-planificar entero); **fallback a plan por defecto** si el
  LLM devuelve basura (degradación explícita, nunca crash). → esqueleto de planner barato.
- **DeerFlow — `GoalState` + `loop_detection_middleware`.** `GoalState` con `continuation_count`,
  `no_progress_count`, `blocker` tipado (`missing_evidence/needs_user_input/run_failed/…`);
  `loop_detection` hashea los tool_calls en ventana deslizante: al repetirse ≥warn inyecta aviso,
  ≥hard elimina los tool_calls y marca `stop_reason=loop_capped`. → **alto ROI, casi idéntico al
  disyuntor anti-ruido**; el `stop_reason` alimenta la telemetría BoN.
- **Agent Reach — router primario+respaldo por fuente + `doctor` (health-check ejecutable).**
  Cada fuente declara varios backends con failover; `doctor` reporta cuál vive/muere. → mata el
  "backend cableado que no existe"; encaja con "medir las rutas reales, no leer el código".
- **Future AGI — eval-como-objeto-dual (offline gate + scorer online colgado del span).** Un
  mismo scorer sirve de test CI y de scorer en producción → evita divergencia "umbral de otra
  máquina" vs realidad. → formalizar `cognia/events.py` como spans con `duration/tokens/score`.
- **OpenClaw — gateway desacoplado de canales + skills con activación perezosa por disparador.**
  → escalar la flota de micro-expertos sin inflar el prompt (cada experto=skill que entra en
  contexto solo cuando su gate lo activa). Código TS: solo el patrón.
- **Manus** = cerrado (usar OpenManus). **Qwythos** = modelo 9B sin eval independiente; no adoptar.

## 4. Web/datos/grafos (Browser-Use · Scrapling · MarkItDown · Open Notebook · deepwiki · Graphify · Code Graph · GraphRAG)

- **Browser-Use — árbol de accesibilidad indexado por número + selector_map.** Numera solo los
  nodos interactivos/visibles (`index→nodo`); el LLM emite `click(index=42)`. Colapsa ~5000
  tokens de captura a ~500 de árbol. Detección de interactividad por reglas (tags/ARIA/heurísticas).
  → sobre `html.parser`: DOM textual indexado `[n] enlace: texto→url` para navegación multi-hop
  guiada por el modelo sin navegador.
- **Scrapling — firma de elemento + auto-match por `SequenceMatcher`.** Persiste (tag, texto,
  attrs, hermanos, padre) en SQLite por `(dominio, id)`; al romperse el selector, relocaliza por
  similitud difusa sobre el DOM actual. → **antídoto directo a scrapers frágiles / degradación
  silenciosa**: aprender "dónde está el contenido" por dominio y relocalizar por similitud.
- **MarkItDown — registro de convertidores por prioridad con `accepts()` + todo→HTML→Markdown.**
  `PRIORITY_SPECIFIC(0.0)` antes que `GENERIC(10.0)`; si falta la dep opcional, el convertidor no
  se registra (catch-all a texto). → volver `ingest.py` extensible por deps opcionales; unificar
  N serializadores en un solo HTML→MD (`html.parser`, sin BeautifulSoup).
- **Open Notebook — modelo notebook→sources→notes→chat + grounding con span-origen.** → contenedor
  de "investigación con fuentes acotadas" (caso de uso declarado en memoria); citar `(source_id,
  offset)` hace verificables los resúmenes.
- **deepwiki-open — repo→wiki Markdown + diagramas Mermaid (texto).** → generador determinista
  `code_graph → wiki` (1 página/módulo: define/llama/importado_por + Mermaid), CPU puro; el LLM
  solo para la prosa opcional. Materializa auto-doc de Cognia. (Parcial: `code_grafo` ya da los datos.)
- **Graphify — procedencia por arista `EXTRACTED` vs `INFERRED` + evidencia (file,line).** →
  añadir metadato a cada triple del KG: explicabilidad + gate de confianza + filtro RAG
  (preferir EXTRACTED). Barato (una columna). Valida "no vector store, grafo real que traversas".
- **Code Graph (SCIP/tree-sitter/pyan/aider) + GraphRAG.** def/ref con `ast` puro (sin tree-sitter
  para Python); **PageRank personalizado** = el mayor upgrade (hecho). GraphRAG: comunidades
  jerárquicas (Leiden → sustituto CPU **label propagation** de networkx) + **resúmenes por
  comunidad** para responder preguntas *globales* con ventana chica (map-reduce sobre resúmenes).
  → **BACKLOG**: comunidades+resúmenes sobre el KG para "¿de qué trata todo este corpus?".

## 5. Voz/infra/analytics (whisper.cpp · Piper · Pipecat · Supervision · Daytona · Cal.com · Plausible · Sentinel)

- **whisper.cpp — STT GGML cuantizado + gating VAD.** `base`/`tiny` q5 (31–57MB) en tiempo real
  CPU; modo VAD (`--step 0 -vth 0.6`) solo transcribe tras habla. → STT real para el modo Jarvis
  (dep opcional gated). Descarga pequeña, sin GPU.
- **Piper — TTS VITS→ONNX en CPU (la vía TTS real, no Voicebox).** `texto→espeak-ng→fonemas→
  onnxruntime→PCM`; voces español (`es_ES-davefx-medium` ~60MB); síntesis por frase (baja
  latencia percibida). → salida de voz del modo Jarvis. Esfuerzo S–M, sin GPU.
- **Pipecat — pipeline de frames + VAD Silero (ONNX ~2MB) + turn-taking.** Patrón `micro→VAD→
  whisper→LLM→Piper`; el `speech_cascade.py` actual pasa a ser un FrameProcessor. **Realista:
  half-duplex ("walkie-talkie") en CPU, no full-duplex sub-segundo.**
- **Supervision — `Detections` + ByteTrack (Kalman+IoU, numpy puro) + zonas.** Toolkit CV
  model-agnostic (CPU); el detector (YOLO-nano ONNX ~6–12MB) es gated. No es núcleo hoy.
- **Cal.com — RRULE (RFC 5545) + generación de slots por sustracción de intervalos + overrides.**
  → **quick win**: migrar la recurrencia ad-hoc de reminders a `dateutil.rrule` (cubre "cada 2
  semanas", "último viernes", `BYDAY`, `UNTIL/COUNT`) + overrides por fecha. Esfuerzo S.
- **Plausible — conteo de únicos con salt rotativo diario + modelo evento/sesión.**
  `user_id = hash(salt_del_día + dominio + ip + ua)`, salt rota 24h, crudo descartado → únicos sin
  cookies/PII. → endurecer `usage_analytics` con métricas de uso sin PII (o HyperLogLog). Esfuerzo S.
- **Sentinel/guardrails — deny>allow (precedencia dura) + validación de esquema de argumentos +
  confirmación default-deny + rate-limits.** → **quick win de seguridad**: validar los *argumentos*
  de cada acción (path traversal, `rm -rf`), no solo el nombre de la tool. Esfuerzo S–M.
- **Daytona / Voicebox** = ⛔ (Docker / GPU+pesos cerrados): robar solo el diseño de API/idea.

## 6. Modelos/serving (OpenBMB · Colibrí · llamafile · GPU prestadas)

- **FR-Spec (thunlp/MiniCPM4) — spec decoding con vocab recortado por frecuencia.** El draft
  restringe la LM head a un top-K de vocab por frecuencia (−75% cómputo de la head) manteniendo
  la equivalencia de verificación (el grande verifica sobre vocab completo → salida idéntica).
  → **extensión natural del draft-verify 0.5B** ya en producción. Tabla de frecuencias offline
  sobre el corpus de código. **Riesgo:** llama.cpp no expone trivialmente la LM head del draft.
- **Colibrí (`JustVugg/colibri`, 2400 líneas C) — jerarquía VRAM+RAM+disco gestionada.** Las 4
  optimizaciones de I/O son **oro para el motor de shards** (tarea pendiente "nodos con poca RAM"):
  (1) **batch-union** (dedup de lecturas), (2) **async I/O pool** (solapa I/O con cómputo),
  (3) **router-lookahead prefetch** (predice la siguiente capa, 71.6% acierto), (4) **almacenamiento
  adyacente** (un `pread`). Más **LRU + hot-store aprendido** (`.coli_usage` fija lo caliente) y
  **KV comprimido persistente**. → todo CPU, reimplementable sobre el pipeline de shards.
- **ToolBench — DFSDT (árbol de decisión con backtrack).** Trata el tool-use como DFS sobre un
  árbol de estados con backtrack cuando un camino muere (vs cadena lineal ReAct que arrastra el
  error). → **encaja con el disyuntor**: backtrack a un nodo anterior en vez de seguir parcheando.
- **ChatDev — memoria = buffer de mensajes JSON estructurados por sesión.** Sin base vectorial;
  log de turnos que cada rol lee. → memoria de agente barata, local, cero datos centralizados.
- **AgentVerse — Expert Recruitment + bucle 4 etapas (recruit→decide→act→evaluate).** → reclutar
  micro-expertos por tarea (idea_router) = tu filosofía "roles sobre el 14B, no entrenar especialistas".
- **XAgent — dual-loop Planner(externo)/Actor(interno)/Dispatcher.** → esqueleto para Jarvis/autoprog.
- **llamafile — un ejecutable portable (Cosmopolitan) + tinyBLAS.** → distribuir un nodo sin
  instalación (Win/Linux/Mac en un fichero). No cambia la inferencia.
- **GPU prestadas — patrón compatible: offload ASÍNCRONO de entrenamiento LoRA, no inferencia
  síncrona.** La GPU prestada NO participa en el forward de inferencia; entrena/refina un adapter
  LoRA offline (tolerante a latencia) y devuelve **solo el tensor del adapter** (MB); el coordinator
  lo agrega por FedAvg; la inferencia sigue 100% local en CPU. Respeta las 4 restricciones duras.
  Vetados como inferencia: Petals/exo/llama.cpp-RPC/prima.cpp (sharding WAN síncrono).

---

## Implementado esta noche (2026-07-21, verificado + pusheado)

1. **`repo_map`** — selector de contexto por PageRank personalizado sobre el grafo de imports
   (idea Aider). `cognia/knowledge/repo_map.py` + tool. 6 tests; real: 398 módulos en 0.78s frío /
   0.016s caliente. Commit `2514abb`.
2. **`editar_archivo`** — edición SEARCH/REPLACE en cascada (exacto→sangría) con error-como-prompt
   (idea Aider). `cognia/agent/edit_block.py` + tool. 9 tests; real: re-indentado 4→8 + confinamiento
   al workspace. Commit `2c9a34c`.
3. **`code_grafo`** — navegación tipo LSP (find-def/find-refs) desde AST sin BD ni language server
   (idea OpenCode/SCIP). `cognia/knowledge/code_nav.py` + tool. 5 tests; real: `KnowledgeGraph`
   def+11 refs. Commit `46d3698`.

Los tres forman el trío del agente-dev: **ubicar → navegar → editar quirúrgico**, la convergencia
OpenHands/Aider/OpenCode. Aditivos, CPU puro, cero deps nuevas, sin tocar el bucle caliente.

## Backlog priorizado (mayor valor / menor coste-riesgo, para próximas iteraciones)

| # | Componente | Origen | Esfuerzo | Riesgo | Nota |
|---|---|---|---|---|---|
| 1 | Condenser rolling+summarizing (+ tool-pair de Goose) | OpenHands/Goose | S–M | medio (toca bucle → gate e2e) | ataca la ventana chica del modelo local |
| 2 | `loop_detection` por hash de tool_calls + `GoalState` tipado | DeerFlow | S | medio (bucle) | unifica el disyuntor; alimenta telemetría BoN |
| 3 | RRULE en reminders + overrides | Cal.com | S | bajo | `dateutil.rrule`; recurrencia estándar |
| 4 | Endurecer Sentinel: validar esquema de argumentos | guardrails | S–M | bajo | path traversal / rm -rf; deny>allow |
| 5 | Procedencia por arista EXTRACTED/INFERRED en el KG | Graphify | S | bajo | explicabilidad + gate de confianza |
| 6 | Firma de elemento + auto-match (SequenceMatcher) web | Scrapling | S–M | bajo | extractores que no se rompen |
| 7 | Registro de convertidores por prioridad `accepts()` | MarkItDown | S | bajo | ingest.py extensible por deps opcionales |
| 8 | FR-Spec (vocab recortado por frecuencia en el draft) | MiniCPM4 | S–M | medio | extiende draft-verify 0.5B |
| 9 | I/O async + prefetch + LRU/hot-store en shards | Colibrí | S–M | bajo | nodos con poca RAM |
| 10 | Comunidades (label propagation) + resúmenes | GraphRAG | M–L | medio | preguntas globales sobre corpus |
| 11 | Generador code_graph→wiki Markdown+Mermaid | deepwiki-open | M | bajo | auto-doc; `code_grafo` ya da los datos |
| 12 | Bucle de voz offline (whisper.cpp + Piper + VAD) | whisper/Piper/Pipecat | M | bajo | dep opcional gated; descargas pequeñas |

**Regla transversal (de todos los informes):** de LangGraph/DeerFlow/CrewAI/Dify/OpenClaw **no
importar las dependencias** (LangChain/LangGraph/OTel/Node) — reimplementar el patrón en Python
plano, que es lo que exige el perfil CPU/baja-latencia. Nada default-ON sin gate.

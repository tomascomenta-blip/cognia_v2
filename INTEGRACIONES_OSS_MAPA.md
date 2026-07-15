# MAPA DE EQUIVALENCIAS — Integración nativa OSS en Cognia

**2026-07-14.** Regla principal del mandato: analizar Cognia ANTES de implementar;
si existe equivalente, EVOLUCIONARLO — jamás duplicar. Este mapa cruza las ~29
herramientas pedidas contra el inventario real de subsistemas (agente de
exploración, 14 áreas + transversales; ver historial del goal). Prioridad
global: GOAL A (superorganismo) primero; esto avanza en los huecos.

## Leyenda
- **EXISTE**: Cognia ya lo tiene; se evoluciona con las mejores ideas de la herramienta.
- **PARCIAL**: hay base real; se amplía.
- **FALTA**: no hay equivalente; se construye nativo.
- **ABSORBIDA**: la herramienta no amerita módulo propio; sus ideas se funden en otra línea.

| Herramienta | Estado en Cognia | Equivalente real (archivos) | Decisión |
|---|---|---|---|
| OpenHands | **EXISTE** (lo más maduro) | /hacer + agent/tools.py generar_codigo + repair + tool_synthesis + /flujo | Evolucionar: comprensión de proyecto (repo-map vía grafo de código), edición por parches |
| Aider | **EXISTE** | ídem | Absorber ideas: repo-map, edición search/replace por diff, commit-per-change |
| Goose | ABSORBIDA | ídem dev autónomo | Sin módulo propio |
| LangGraph | PARCIAL | /flujo (agents/flow.py) | UN orquestador: flujo como grafo de estados explícito |
| CrewAI | PARCIAL | delegar_subtarea (2 roles fijos) + oficina motor.py (JEFE→DIRECTORES→TRABAJADORES) | Roles arbitrarios, crews = metas de oficina |
| Dify / Langflow | ABSORBIDAS | agents/{flow,supervisor,task_queue}.py | Sus ideas (pipelines declarativos) van al orquestador único; SIN editor visual genérico |
| Shepherd | PARCIAL | oficina/motor.py (jefe) + agents/supervisor.py | El coordinador = jefe de oficina post-unificación |
| Agent Reach | **FALTA** (gap real) | coordinator/event_bus.py existe pero SOLO swarm; en cognia/ NO hay bus | **cognia/events.py**: pub/sub interno en proceso; conecta loop↔oficina↔analytics↔notifications |
| Sentinel Skill | PARCIAL | GoalContract + agents/verifier.py + sandbox 2 capas + _BLOCK denylist + screen gates | Unificar como validación pre-acción DEFAULT-ON; `ejecutar` denylist→allowlist real |
| Supervision (CV) | FALTA | — (lcd es render, no visión) | GATED por hardware (sin GPU); no prioritario |
| Whisper | **FALTA** (mandato) | node/speech_cascade.py es router de TEXTO, no audio | **whisper.cpp** en node/ (mismo ecosistema GGML/llama.cpp) + tool de agente |
| Voicebox (TTS) | **FALTA** (mandato) | — | **piper** (ONNX CPU, español) en node/ + tool `hablar` |
| Pipecat | FALTA | — | POSPUESTO: requiere STT+TTS primero; tiempo-real en 2 cores con LLM = dudoso; degradar a push-to-talk |
| Browser Use | PARCIAL débil | web_search.py (DDG instant) + http_get (regex strip) + screen_tools | Navegador inteligente: parser HTML real + navegación por links + extracción estructurada + formularios; comprensión con 3B |
| Scrapling | PARCIAL débil | research_engine/github_scraper.py | Se fusiona con Browser Use en el navegador nativo |
| Graphify + CodeGraph | **FALTA** (gap barato) | knowledge/graph.py NO tiene grafo de código | **Extractor AST** (stdlib) → import/call graph en el KG; alimenta el repo-map del dev autónomo |
| MarkItDown | PARCIAL | ingest.py (~30 ext + PDF pdfplumber) | Ampliar: docx/html/xlsx→md (deps opcionales, patrón pdfplumber) |
| Open Notebook | PARCIAL | notes/smart_notes.py + summarizer + export/ | /cuaderno: notas + fuentes ingestadas + preguntas al KG |
| Open Wiki | ABSORBIDA | el KG ES la wiki interna (/kg-*) | Vista/export mejorada del KG; sin sistema aparte |
| Plausible | PARCIAL fuerte | usage_analytics + metrics_collector + _bon_telemetry (3 fuentes SIN agregación) | Capa de agregación local + /analiticas; TODO local (ya lo es) |
| Cal.com | PARCIAL | reminders (one-shot) + oficina despierta_ts + goals | Recurrencia cron-like + agenda + tool `agendar` para agentes; SIN servicios externos |
| Future AGI | PARCIAL | telemetría BoN ("dataset para recalibrar router") + prompt_evolution (RSI) | Lazo telemetría→recalibración θ/router (ya diseñado, falta cerrarlo) |
| DeerFlow | PARCIAL | research_engine/{researcher,research_orchestrator}.py | Flujos de investigación multi-fuente en el orquestador único |
| Daytona | PARCIAL | program_creator/sandbox_runner.py (proceso, no OS) | Workspaces aislados (venv+dir efímero) para el dev autónomo; sin Docker |
| Hyperframes | PARCIAL | context/anchor_tracker + ContextMap + memoria jerárquica | Absorber conceptos en ContextMap donde midan mejor |
| LCD MoM training | PARCIAL | lcd/selfplay + eval_selfplay + training/dataset_gen | Dataset selfplay→QLoRA Kaggle (pipeline existe); gated por GPU externa |
| Entrenamiento distribuido | PARCIAL fuerte | kaggle/ pipeline + coordinator/federated_store (FedAvg SOLO adapters LoRA — restricción dura) + adapter_store | Evolucionar: reanudación, tolerancia a fallos, métricas/checkpoints unificados |
| Oficina isométrica | **EXISTE sin /oficina** | oficina/ completa (motor+estado+server+web3d compilado) pero CLI no la lanza | **Comando /oficina** + paneles por subsistema alimentados por el bus de eventos |

## Deuda arquitectónica detectada (bloquea "arquitectura limpia")
1. **DOS registries de tools**: agent/tools.py:TOOLS vs agents/tool_registry.py:ToolRegistry → unificar (prerequisito del orquestador único).
2. **Sin bus de eventos interno** en cognia/ → todo va por callbacks directos (print_fn/confirm) → construir cognia/events.py primero: habilita oficina-tiempo-real, analytics unificada y Agent Reach.
3. `ejecutar` con shell=True + denylist → allowlist (parte de Sentinel).

## Orden de construcción (checkpoints B; GOAL A siempre primero)
- **TIER 1 (viable ya, CPU-liviano):** B4 /oficina en CLI · B5 cognia/events.py (bus interno) · B6 grafo de código AST→KG · B7 Sentinel (validación pre-acción default-on + allowlist ejecutar) · B10 unificación de registries/orquestación.
- **TIER 2:** B8 Whisper (whisper.cpp; requiere descargar GGML ~100-500MB) · B9 TTS piper · B11 /analiticas agregada · B12 MarkItDown ext · B13 calendario recurrente · B14 navegador inteligente · B15 Daytona workspaces · B16 /cuaderno.
- **TIER 3 (gated):** Pipecat tiempo-real (post B8/B9 + medición de latencia) · Supervision (GPU) · entrenamiento distribuido evolución (GPU externa) · LCD MoM training.
- Cada unidad: tests dirigidos + verificación real + commit chico (método CLAUDE.md). Nada default-ON sin gate (Sentinel es la excepción pedida: default-ON con batería previa).

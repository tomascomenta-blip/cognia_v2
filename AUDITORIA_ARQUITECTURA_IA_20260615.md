# INFORME DE AUDITORÍA Y DISEÑO — Cognia

> Generado por workflow multi-agente (10 auditores por objetivo + 1 chequeo adversarial + síntesis), 2026-06-15/16. Toda la evidencia `file:line` proviene de lectura de código real, no de docs.

Repo: `D:/Movido_desde_C/Downloads/cognia/cognia_v2` · Backend real: llama.cpp+GGUF Qwen2.5-Coder-3B vía `node/llama_backend.py` · Hardware: i3-10110U 2c/4t, 12GB, sin CUDA, ~8 tok/s.

---

## 1. Resumen ejecutivo

El repo tiene construido el **80% de la algoritmia** de los 9 objetivos: state-machines, planners, band-router de memoria, loops de deliberación, gates de calidad, dev-tools con sandbox — y casi todo corre E2E en el hardware objetivo (CPU/numpy, sin PyTorch, costo de LLM acotado). El problema dominante **no es de cómputo sino de WIRING**: las piezas más completas (supervisor, CognitiveLoop rico, HierarchicalMemory, SemanticMemorySearch, ConsistencyChecker) están desconectadas del REPL real (`python -m cognia` → `cognia/cli.py`), o viven solo en la FastAPI desktop (`:8765`) o en `chimera.py` (0 referencias desde el CLI). Hay además **una violación dura real (FedAvg activo en el coordinator)**, incumplimiento sistemático de `db_pool` en `cognia_v3`/coordinator, y una **dependencia muerta de Ollama** en `self_architect` que vuelve NO-OP la auto-generación de código. Tres objetivos clave (`/esfuerzo`, "tokens infinitos", autoevaluación completa en el path vivo) son MISSING o solo parciales.

Los 3 movimientos de mayor ROI:
1. **Cablear lo que ya existe al REPL** (supervisor como `/flujo`, CognitiveLoop como `/deliberar`, módulos `:8765` como llamada local en `/buscar-memoria`/`/contradicciones`/`/ver-contexto`) — cierra el gap nº1 de casi todos los objetivos sin algoritmia nueva.
2. **`/esfuerzo` + `effort_levels.py`** — un dict plano nivel→params que de paso centraliza constantes hoy dispersas (cumple regla del repo) y desbloquea control transversal de profundidad/verificaciones/alternativas.
3. **Arreglar el backend de generación largo** (`_LlamaCppBackend` no setea `stop_reason` → `generate_long` corta tras ronda 1 in-process) + outline jerárquico §3.1 — única palanca real para respuestas largas dentro de ctx 16k.

---

## 2. Tabla maestra

| Objetivo | Estado | Evidencia clave (file:line) | Brecha principal |
|---|---|---|---|
| O1 Flujos de trabajo inteligentes | PARTIAL | `cognia/agents/supervisor.py:118-152`; `task_queue.py:38-61`; `cognia/cli.py:6394-6493` (/hacer) | 3 sistemas paralelos desconectados; el más completo (supervisor) no está en el REPL (`cognia_idle.py` only); sin pipeline único analisis→…→informe |
| O2 Memoria operativa multinivel | PARTIAL | `cognia/context/band_router.py:97-446`; `cognia/memory/hierarchical.py:47-326` | Taxonomía no coincide (3 bandas + 5 capas ≠ 5 niveles pedidos); faltan niveles "trabajo" y "proyectos"; HierarchicalMemory solo en `chimera.py` (no CLI) |
| O3 Recapitulación automática | PARTIAL | `cognia/summarizer/session_summarizer.py:24` (TRIGGER_TURNS=10); `cognia/cli.py:5619-5644` (/resumir manual) | Único trigger = conteo de turnos; cableado solo en API desktop, no en CLI; no reinyecta al working-memory ni comprime el prompt |
| O4 Gestión avanzada del contexto | PARTIAL | `cognia/context/band_router.py:97-446` (wired); `cognia/memory/reranker.py:50-279`; `semantic_search.py:30-247` | `/buscar-memoria`, `/contradicciones`, `/ver-contexto` hacen HTTP a `:8765` (muerto sin Electron); sin budget token-aware en fast-path |
| O5 Modos de esfuerzo (/esfuerzo) | **MISSING** | `cognia/cli.py:4787-6228` (dispatcher sin /esfuerzo); glob `*esfuerzo*`/`*effort*` = 0 | No existe comando ni módulo ni estado; params dispersos hardcodeados en `reasoning/*.py` |
| O6 Planificación autónoma | PARTIAL | `cognia/reasoning/cognitive_loop.py:431-487` (DELIBERATE); `supervisor.py:118-152`; `self_architect.py:2160-2260` | Ninguno cableado al CLI; revisión de PROGRESO (no de calidad de plan) inexistente; corrección autónoma choca con invariante humano-en-el-loop |
| O7 Optimización de respuestas / tokens infinitos | PARTIAL | `node/llama_backend.py:624-687` (generate_long); `model_constants.py:94-95` | Tope fijo 5000; §3.1 outline y §3.2 compresión NO implementadas; in-process backend no continúa (no setea stop_reason) |
| O8 Autoevaluación | PARTIAL | `cognia/quality/response_gate.py:44-171`; `self_critic.py:30-188`; `cognia_desktop_api.py:804-818` | Auto-correct síncrono solo en API (1 retry por "más largo"); ejes precisión/cumplimiento faltan; loop rico opera sobre PLAN, no sobre respuesta real del LLM |
| O9 Modo autónomo de implementación | PARTIAL | `cognia/agents/workers/dev_tools.py:51-228`; `code_executor.py:52-416` (gating real) | `self_architect` propose-only (choca con "sin confirmación"); `sandbox_tester.py` NO existe (test_proposal roto); generate_module_code usa Ollama (NO-OP) |
| O10 Adversarial vs reglas duras | PARTIAL | `coordinator/federated_store.py:4`; `coordinator/app.py:117,798` | **Violación dura: FedAvg vivo**; `sqlite3.connect` directo en `cognia_v3`/coordinator pese a existir `db_pool` |

---

## 3. Detalle por objetivo

### O1 — Flujos de trabajo inteligentes (PARTIAL)
**Ya existe (verificado):** state-machine completa PLANNING→EXECUTING→VERIFYING→DONE/FAILED/ABORTED con retry, loop-detector por hash y time-budget 300s (`supervisor.py:118-152, :154-196, :136-140`); TaskQueue SQLite WAL con prioridad y persistencia de subtasks (`task_queue.py:38-61, :107-109, :116-141, :185`); decisión dinámica de ruta FAST/RECALL/DELIBERATE/ACT con loop real plan→critique→verify→revise (`cognitive_loop.py:178-273, :431-487`, 48 tests pasan); agente productivo `/hacer` ReAct con presupuesto dinámico y auto-descomposición >120 chars (`cli.py:6394-6493, :6496-6509, :6547-6561`; `agent/loop.py:32-82`, 21 tests); `/plan` y `/razonar→investigate` (`cli.py:2453-2519, 4944-4947`; `cognia.py:1121-1169`); ReasoningPlanner y SelfArchitect generate→test→approve.

**Brechas:** no hay un orquestador único que encadene el pipeline COMPLETO con decisión dinámica de qué etapa usar — son 3 sistemas paralelos (supervisor sin LLM ni etapa "informe"; CognitiveLoop DELIBERATE cuyo candidato es solo texto del plan, NO ejecuta — `cognitive_loop.py:316-329`; `/hacer` con LLM real pero sin etapas verify/correct/validate/report explícitas). El supervisor (lo más completo) **no está en el REPL**, solo en `cognia_idle.py`; el propio `INFORME_EVOLUCION_20260611.md:75` lo confirma ("las 4 tools están registradas pero ningún plan puede usarlas"). Descomposición = por templates de keyword (`planner.py:88-189`), no dinámica real. Corrección = solo retry del mismo subtask. "Retomar interrumpidos" a nivel de PASO no existe: `pop()` lee solo `_mem`, no rehidrata EXECUTING desde SQLite (`task_queue.py:133-141`). "Detectar bloqueos" y "tareas derivadas" no implementados.

**Viabilidad:** alta — el gap es de integración, no de cómputo; las piezas son simbólicas/offline o de pocas llamadas LLM, alineadas con 8 tok/s.

### O2 — Memoria operativa multinivel (PARTIAL)
**Ya existe (verificado):** band-router 3 bandas LOCAL/MEDIA/GLOBAL cableado al runtime e inyectado KV-cache-safe (`band_router.py:97-446`; `cli.py:199-252`), corriendo E2E sobre 10.972 vectores con re-ranker de fusión; nivel "sesión" = ConversationContext (buffer 12 turnos, TopicTracker) cableado (`conversation_memory.py:351-458`; `cli.py:6577-6581`); fachada HierarchicalMemory 5 capas con write-gate surprise+importance (`hierarchical.py:47-326`, 22 tests); LongTermConsolidator auto-promueve entidades recurrentes a KG; cumple `db_pool` (`episodic.py:14`, `semantic.py:13`).

**Brechas:** **taxonomía distinta** — el objetivo pide inmediata/sesión/trabajo/proyectos/histórica; el código da 3 bandas + 5 capas, ninguna es esa taxonomía. Faltan como niveles propios "trabajo" (objetivos activos — existe `cognia/goals/` pero no integrado como memoria ni inyectado por el band-router) y "proyectos" (estado persistente — grep `ProjectMemory`/`project_state` = 0). "Histórica" solo aproximada (marcadores + KG, sin `decision_log` dedicado, grep = 0). **HierarchicalMemory desconectada del CLI** — solo la usa `chimera.py:68-69`, inalcanzable (grep `chimera` en cli.py = 0). `ROADMAP.md:854` declara DONE algo que no son los 5 niveles pedidos (induce a error).

**Viabilidad:** alta — todo CPU/numpy+sqlite, caps de chars duros. Riesgo: dos sistemas paralelos (`cognia/memory` vs `cognia_v3/memory`) — consolidar antes de extender, no crear un tercer árbol.

### O3 — Recapitulación automática (PARTIAL)
**Ya existe (verificado):** SessionSummarizer extractivo cada 10 turnos en thread daemon (`session_summarizer.py:24-77, :156-183`) — pero disparador SOLO conteo de turnos, **cableado solo en API desktop** (`cognia_desktop_api.py:1211-1212`), no en CLI; `/resumir` manual con LLM (`cli.py:5619-5644`); `/resumen-sesion` solo estadísticas; MemoryCompressor (clustering coseno>0.90 en `sleep()`) y ConceptCompressor son mantenimiento de DB, NO recap del contexto en curso; banda MEDIA reutiliza `extract_summary` por consulta. 13 tests pasan.

**Brechas:** ninguno de los disparadores pedidos existe (tamaño de contexto, demasiadas tareas, múltiples objetivos, degradación). Sin detección de redundancia en contexto activo, sin compresión del prompt/ventana, sin preservación de detalles críticos (corta a 300 chars por densidad), sin reinyección al working-memory. El CLI carece por completo de recap automática.

**Viabilidad:** alta para el camino extractivo (costo ~0, daemon). Recap "optimizado" con LLM = una inferencia completa → debe ser gated por umbral y baja frecuencia.

### O4 — Gestión avanzada del contexto (PARTIAL)
**Ya existe (verificado):** band-router cableado al fast-path de streaming (`band_router.py:97-446`; `cli.py:199-252, 6297-6302`); recuperación semántica VectorCache numpy Nx384 (`episodic_fast.py:39-260`; VECTOR_DIM=384 en `config.py:82`, no hardcodeado); re-ranker fusión sim/recencia/importancia (`reranker.py:50-279`); búsqueda TF-IDF sobre historial vía db_pool (`semantic_search.py:30-247`); detección de contradicciones en KG (`consistency_checker.py:33-205`); seeder de ~150 hechos + fetch DuckDuckGo; PersonalIndex; context_window_manager + injection_prioritizer EXISTEN y testean pero **huérfanos del fast-path**.

**Brechas:** **desconexión crítica** — `/buscar-memoria`, `/contexto-semantico`, `/contradicciones`, `/sintetizar`, `/ver-contexto` hacen HTTP a `localhost:8765` (`cli.py:1490,1546,4519,4596`), server que arranca Electron, NO el REPL → sin la app desktop imprimen "Servicio no disponible". Budget de tokens en fast-path = slice fijo `_history[-16:]` + cap 800 chars, sin token-awareness vs n_ctx. `/ver-contexto` reporta fuentes API, NO lo que inyecta el band-router (engañoso). Contradicciones no corre en el loop de chat.

**Viabilidad:** alta y mayormente implementado — bloqueo de WIRING, no técnico.

### O5 — Modos de esfuerzo /esfuerzo (MISSING)
**Ya existe (verificado):** dispatcher de ~200 comandos sin `/esfuerzo` ni `/effort` (`cli.py:4787-6228`); `/pensar` CoT de una pasada con prompt fijo (`cli.py:5551-5580`); config `nivel_detalle` (verbosidad de salida, NO esfuerzo); profundidad adaptativa interna automática en v3 (`cognia_v3.py:2675-2721`); temperaturas/max_tokens hardcodeados por función creativa (`creative_llm.py:13-16`; `hypothesis.py:274`, etc.).

**Brechas:** no existe el comando, ni módulo (`glob` = 0), ni estado persistido/mostrado, ni parametrización por nivel de tiempo/profundidad/verificaciones/alternativas/complejidad. Ni siquiera está planificado bajo ese nombre.

**Viabilidad:** alta y bajo riesgo — es un mapeo nivel→params que ya existen dispersos. CUIDADO: niveles altos multiplican llamadas LLM (a 8 tok/s, "máximo" puede tardar minutos). Debe usar `model_constants.py` para constantes de modelo.

### O6 — Planificación autónoma (PARTIAL)
**Ya existe (verificado):** CognitiveLoop DELIBERATE (`cognitive_loop.py:431-487`, E2E: plan 3 pasos, crítica 0.77, verify PASS, 1 iter); cap 2 iters / umbral 0.6 (`:49,:53,:447-457`); SymbolicPlanner sin LLM (`planner.py:88-189`); supervisor (`supervisor.py:118-196`); SelfArchitect meta-nivel (`self_architect.py:2160-2260`, 70 tests); ActionSimulator world-model con gate CONFIRM; ReAct en CLI (path real, `cli.py:6394-6618`).

**Brechas:** ninguno (CognitiveLoop/SymbolicPlanner/Supervisor/SelfArchitect) cableado al CLI. `/plan` = checklist LLM manual sin revisión de progreso ni corrección. Corrección NO autónoma en SelfArchitect (apply rechaza si `status!='approved'`). **Viola reglas:** `self_architect.py:89-92` usa `sqlite3.connect` directo y hardcodea `'llama3.2'` (`:276,:2407`). **Dependencia Ollama muerta** (`:2381-2430`). DELIBERATE no usa LLM para la estrategia (templates). Revisión de PROGRESO real (ejecutar, medir avance, re-planificar) NO existe — DELIBERATE revisa calidad del plan ANTES de ejecutar; supervisor marca FAILED y termina (`:142-146`).

**Viabilidad:** alta para lo determinista. NO viable tal cual: `generate_module_code` (Ollama). Corrección automática choca con regla "humano decide" → acotar a cambios reversibles low-risk con gate. Arreglar las 2 violaciones de regla antes de construir encima.

### O7 — Optimización de respuestas / tokens infinitos (PARTIAL) → ver §4
**Ya existe (verificado):** auto-continuación por bloques `generate_long()` (`llama_backend.py:624-687`); tope fijo 5000 / chunk 2048 (`model_constants.py:94-95`); detección de stop_reason (`:79-98`); `/largo` cableado (`cli.py:2673-2746`); script E2E (`scripts/e2e_long_gen.py:69-113`); tests de regresión del loop (`test_llama_backend.py:198-268`).

**Brechas (detalle en §4):** infinito NO implementado (tope duro 5000); compresión incremental §3.2 NO (reenvía texto completo cada ronda `:657-659`); outline jerárquico §3.1 NO (grep = 0); colisión con ctx 16k sin guarda; **backend in-process no setea `last_stop_reason` → corta tras ronda 1** (`:225-248,:677,:749-751`); sin presupuesto de tokens por historia; sin streaming en `/largo`; timeout no escala con prefill acumulado.

**Viabilidad:** alta. §3.1 (outline, prompts frescos por sección) es la palanca de mayor ROI para romper el techo de ctx; §3.2 es factible pero costosa en CPU. **Bloqueo previo:** arreglar el backend in-process o forzar llama-server, o nada continúa fuera del E2E con server.

### O8 — Autoevaluación (PARTIAL)
**Ya existe (verificado):** ResponseGate determinista (`response_gate.py:44-171`) con wiring síncrono real en el endpoint (`cognia_desktop_api.py:804-818`); RFV factual contra KG (`:791-801`); SelfCritic heurístico (`self_critic.py:30-188`) pero solo fire-and-forget (`:894-901`); autocorrección DIFERIDA al próximo turno (`language_engine.py:1376-1381`); idea_eval LLM real para rankear (`idea_eval.py:85-152`); Verifier determinista (`verifier.py:36-127`). 55+124 tests pasan.

**Brechas:** la autoevaluación "completa" (calidad+precisión+coherencia+completitud+cumplimiento) NO existe como evaluación única — ResponseGate solo length/relevance/refusal. El loop generate→critique→verify→revise opera sobre un PLAN sin LLM (`cognitive_loop.py:316-329`), no sobre la respuesta entregada, y solo es alcanzable vía ChimeraSystem (0 refs en cli.py). El CognitiveLoop v3 cableado al REPL NO hace autoevaluación (`cognia_v3/interfaces/cognitive_loop.py:157-229`). El único auto-correct síncrono reintenta 1 vez y solo si la nueva es "más larga" (criterio pobre). Dos rutas paralelas con políticas distintas.

**Viabilidad:** alta — evaluadores heurísticos sin LLM, costo ~0. Riesgo = costo de tokens si se usa LLM. Lo factible y barato: unificar la evaluación en el path vivo y cablear regeneración gated en el MISMO turno, con presupuesto de 1 reintento.

### O9 — Modo autónomo de implementación (PARTIAL)
**Ya existe (verificado):** dev_tools Tier1 deterministas (`dev_tools.py:51-228`); gating de escritura con confinamiento a workspace, bloqueo de nombres sensibles, AST-validate, backup .bak (E2E: traversal y `.env` rechazados); run_tests en subprocess con venv312; loop ReAct cableado a `/hacer` con backend real (`cli.py:6486-6490`; `orchestrator.py:482-520`); registry concreto (`agent/tools.py:40-72`); gating de código generado scan-imports+AST+sandbox (`code_executor.py:52-416`, E2E: `os.system` bloqueado). 51 tests pasan.

**Brechas:** **invariante humano-en-el-loop** contradice "sin confirmación" — SelfArchitect siempre propose-only (`self_architect.py:16-18,:1776`). **`test_proposal()` ROTO**: importa `from sandbox_tester import SandboxTester` (`:2466`) pero `sandbox_tester.py` NO existe → gating de módulos auto-generados no funcional. **generate_module_code depende de Ollama** (`:2406-2424`) → NO-OP con backend real, solo skeleton. Dos registries de tools sin unificar (`agent/tools.py` vs `agents/tool_registry.py`); el ReAct de `/hacer` no expone los Tier1 en su TOOLS_DOC. `apply()` para `new_module` solo loguea "Implementation required by developer" (`:1841-1845`). No hay comando CLI único que dispare el ciclo. El ReAct opera en `agent_workspace`, no sobre el repo real (seguro, pero no "implementa" sobre producción).

**Viabilidad:** alta — el núcleo (ReAct+dev_tools+gating) está DONE y verificado E2E. Falta integración, no hardware. Trade-off honesto: hay "agente autónomo en sandbox" sólido + "self-architect que propone pero no implementa autónomamente".

---

## 4. Hallazgo "tokens infinitos"

**Qué existe.** `generate_long()` (`node/llama_backend.py:624`) hace auto-continuación por bloques: genera `chunk_tokens` por ronda, continúa mientras `stop_reason=='limit'` y `total<max_total_tokens`, reenviando `prompt+texto_acumulado`. Tope FIJO `GEN_LONG_MAX_TOKENS=5000`, chunk `GEN_CONTINUATION_CHUNK=2048` (`model_constants.py:94-95`). Detección de `_stop_reason` (`:79-98`). Cableado a `/largo` (`cli.py:2673-2746`). E2E real con gate ≥5000 (`scripts/e2e_long_gen.py`). Tests de regresión del loop (`test_llama_backend.py:198-268`).

**Qué falta (verificado por auditores).**
- **Compresión incremental §3.2 NO implementada en la ruta de generación.** `generate_long` reenvía el texto completo cada ronda (`:657-659`) sin resumir ni usar tail+outline. Las `*CompressionEngine` de `cognia_v3` comprimen MEMORIA episódica, NO el texto generado (no tocan la generación).
- **Outline jerárquico §3.1 NO implementado.** No existe `generate_hierarchical`/outline/plan→secciones→relleno (grep = 0).
- **Colisión con ctx 16k SIN guarda.** `generate_long` no mide ni recorta `prompt+acumulado` contra `_CTX_SIZE=16384` (`:51-53,:656-659`).
- **Backend in-process rompe la auto-continuación.** `_LlamaCppBackend` NO setea `last_tokens_predicted`/`last_stop_reason` (`:225-248`) y `try_load` lo prefiere (`:749-751`) → `stop_reason` siempre None → el loop corta tras ronda 1 (`:677`). La auto-continuación solo funciona de verdad con llama-server.
- **Sin presupuesto de tokens por historia** (`/tokenize` sin usar; `INFORME:66-67`).

**Diseño concreto mínimo (sobre `generate_long`, sin nuevas abstracciones).** Tres cambios escalonados, todos funciones planas:

1. **Fix de continuación (prerequisito).** En `_LlamaCppBackend.generate`, leer `result['usage']`/`finish_reason` de llama-cpp-python y setear `self.last_tokens_predicted` y `self.last_stop_reason` igual que el backend server. Sin esto, lo demás es teatro in-process.

2. **Guarda de ctx en el mismo loop.** Antes de cada ronda, estimar `n_tokens(prompt) + n_tokens(acumulado)` (vía `/tokenize` del server o un estimador chars/4 como fallback). Si supera un umbral (p.ej. `0.75 * _CTX_SIZE`), **dejar de reenviar todo**: reenviar `system + outline + tail(acumulado, K_chars)` en lugar del texto completo. Esto mantiene el prefill acotado sin resumir (más barato que §3.2 en CPU).

3. **Outline jerárquico §3.1 (la palanca real).** Nueva función `generate_hierarchical(prompt, target_tokens)` que: (a) pide al LLM un outline de N secciones (1 inferencia corta); (b) por cada sección, lanza un prompt FRESCO = `system + outline + "sección K:" + resumen_de_1_línea_de_secciones_previas`; (c) ensambla. El prefill por sección es constante y cabe en 16k → generación cuasi-infinita en tokens totales sin desbordar ctx. Reusa `generate_long` por sección para secciones largas. Cableado en `/largo` (flag `--jerarquico` o auto cuando `target>techo_ctx`). Constantes (N secciones, K_chars del tail) → `model_constants.py`, no hardcodeadas.

Cuasi-infinito = (3) rompe el techo de ctx porque cada sección parte de prefill acotado; el único límite real pasa a ser tiempo de pared (~8 tok/s), no la ventana. §3.2 (resumir el acumulado con el LLM) queda como último recurso si el tail+outline degrada coherencia, midiendo antes el costo CPU extra por resumen en este equipo.

---

## 5. Contradicciones / restricciones imposibles / violaciones de reglas (de O10)

Lista accionable. Nota de honestidad: O10 declara que **no inventarió formalmente los "9 objetivos"** (no hay manifiesto único), **no verificó tráfico FedAvg real en Railway** (solo wiring), **no contó todas las violaciones sqlite3** (>40 sitios; citó representativos), **no corrió la suite** en esa auditoría, y **no verificó duplicación de COGNIA_SYSTEM_PROMPT** más allá de confirmar que `node/` importa bien las constantes. Todo lo de abajo es por lectura de código.

1. **FedAvg vivo — VIOLACIÓN DURA REAL.** Regla `CLAUDE.md:43` "Sin FedAvg" vs `coordinator/federated_store.py:4` (docstring FedAvg+KD), instanciado en `coordinator/app.py:117` (`_fed_store=FederatedStore()`) y servido en `:798` (`get_global_adapter()`). El plan `beta_publica_ultraplan.md:158` intenta colar "FedAvg de adapters" como en-alcance distinguiéndolo de "FedAvg de parámetros completos" — distinción que la regla **no concede**. **Acción:** decisión del dueño — eliminar/deshabilitar `federated_store.py` + wiring `app.py:117,798` (cumplir la regla), **o** el dueño edita `CLAUDE.md:43` para permitir explícitamente FedAvg-de-adapters. Hoy código y regla se contradicen frontalmente. Hay test (`tests/test_federated_store.py`) que ajustar según la decisión.

2. **`sqlite3.connect()` directo pese a existir `db_pool` — VIOLACIÓN.** Regla `CLAUDE.md:49`. Sitios representativos: paquete canónico `cognia_v3` (`consolidation_engine.py:156`, `response_cache.py:219/247/294`, `code_memory.py:145/153`, `teacher_interface.py:255+`, `prompt_optimizer.py:258`); coordinator (`federated_store.py:21/125/135`, `contributor.py:124/134`, `registry.py:120/130`, `shard_registry.py:131`); cognia activos (`scale_manager.py:164`, `thought_cache.py:99`, `task_queue.py:228`, `self_improvement.py:130`, `goal_and_pattern_engine.py:431`, `consolidation_engine.py:158`, `database.py:25`). **Acción:** migrar a `db_pool.db_connect_pooled` (drop-in 1 línea según `db_pool.py:12-23`), empezando por `cognia_v3`. Añadir test de regresión que falle ante `sqlite3.connect` directo en `cognia_v3`.

3. **Constantes de modelo hardcodeadas — VIOLACIÓN.** `self_architect.py:276,:2407` hardcodea `'llama3.2'` en vez de `shattering/model_constants.py`. **Acción:** mover a `model_constants.py` (se resuelve junto con el punto 5).

4. **Dependencia Ollama muerta → NO-OP (regla "nada de mocks/stubs").** `self_architect.generate_module_code()` (`:2406-2424`) y su sandbox (`:2432`) usan Ollama `llama3.2`; el backend real es llama.cpp+GGUF. En el hardware objetivo es NO-OP/skeleton. **Acción:** re-cablear a `ShatteringOrchestrator.infer()` (llama.cpp), o marcar el módulo como Ollama-dependiente y excluirlo del path por defecto. **Reformular** el alcance de SelfArchitect: decidir si entra o no.

5. **`sandbox_tester.py` faltante → gating roto.** `self_architect.py:2466` importa `SandboxTester` de un archivo inexistente → `test_proposal()` siempre devuelve error. **Acción:** crear `sandbox_tester.py` envolviendo `code_executor.run_python` (que ya provee scan-imports+AST+subprocess+timeout).

6. **Auto-corrección autónoma vs invariante humano-en-el-loop — CONTRADICCIÓN de objetivo.** O6/O9 piden "corregir desviaciones / sin confirmación para cambios menores"; SelfArchitect siempre exige `approved=True` (`:16-18,:1776`). **Recortar el goal:** permitir auto-aplicación SOLO de `param_update` reversibles, severidad ≤ medium, con `MAX_CHANGES_PER_DAY` y rollback registrado; todo lo estructural sigue gated. Así se cumple el objetivo sin romper la invariante.

7. **Tensión privacidad — "cero datos personales centralizados".** El coordinator agrega y redistribuye un adapter LoRA global entrenado sobre el sleep-cycle local del usuario; única mitigación = ruido gaussiano σ=0.01; `coordinator.db` guarda BLOBs por nodo (`federated_store.py:15-16`; `app.py:798`). **Acción:** si se elimina FedAvg (punto 1) el gap desaparece; si no, auditar que los BLOBs no permitan reconstrucción de datos personales y añadir consentimiento opt-in. (O10 NO verificó suficiencia de σ=0.01.)

**Resueltas (NO violación, confirmado):** HYDRA reinterpretado como router de 3 bandas sin tocar atención (`band_router.py:4-21`; `cli.py:204-224`); TP-Shattering LAN/numpy puro sin torch/NCCL/WAN (`tensor_parallel.py:4`; `tp_allreduce.py:4`); nodos sin PyTorch (grep `node/` = 0 imports torch); draft local (`node/nano_draft.py`). Bug latente menor (no de regla): `RealTransformerLayer` ignora bias q/k/v de Qwen (`SHATTERING_V2_DESIGN.md:125-127`) — afecta solo el path numpy legacy, no el backend real.

---

## 6. DISEÑO — Sistema avanzado de trabajo basado en flujos estructurados

**Principio rector:** NO reescribir. Un único orquestador plano (`cognia/agents/flow.py`, ~1 función `run_flow(goal, effort)` + un dict de etapas) que **cablea las piezas existentes** y se expone como `/flujo <objetivo>` en el REPL. Reusa: supervisor (state-machine+retry+budget), TaskQueue (prioridad+persistencia), planner/plan_task (descomposición), CognitiveLoop DELIBERATE (deliberación), ResponseGate/SelfCritic/Verifier (verificación), band-router + memoria multinivel (contexto), SessionSummarizer (recap).

**Etapas (registry plano `STAGES = {nombre: fn}`):**

| Etapa | Reusa | Decisión dinámica |
|---|---|---|
| análisis | `complexity` de CognitiveLoop (`cognitive_loop.py:178-273`) + ComplexityScorer | clasifica el goal → ruta FAST/RECALL/DELIBERATE/ACT; FAST salta directo a ejecución+informe |
| plan | `planner.plan_task`, con fallback a LLM (prompt de auto-decompose de `/hacer`, `cli.py:6499-6504`) cuando no cae en los 5 templates | nº de subtareas = `complexity × effort` |
| subtareas | `TaskQueue.submit` con prioridad/deps (`task_queue.py:116-141`); `SubTask.dependencies` ya existe (`:54`) | si una subtarea > umbral chars → re-descomponer |
| ejecución | `_run_agent_task`/ReAct con backend real (`cli.py:6486-6490`); subtasks vía `supervisor._run_subtask` (retry+loop-detector) | step-budget dinámico (`agent/loop.py:32-82`) escalado por `effort` |
| verificación | `Verifier` determinista (`verifier.py:36-127`) + `ResponseGate.score` | nº de ejes/verificaciones = `effort` (low: gate; max: gate+verifier+coherencia+cumplimiento) |
| corrección | retry dirigido por el diagnóstico (no ciego): si falla por error → retry con la crítica concreta; si falla por **dependencia** → crear tarea derivada en TaskQueue (cubre O1 gap) | reintentos = `effort` (1..N) |
| validación | nuevo paso plano: valida resultado agregado vs goal (reusa `idea_eval`/coseno vs goal) | gate final pasa/no-pasa |
| informe | nuevo paso: `synthesize()` (`supervisor.py:237-243`) extendido a reporte estructurado (qué se hizo, qué falló, artefactos) | siempre |

**Decisión dinámica de etapa:** `run_flow` no ejecuta las 8 etapas siempre. La etapa **análisis** clasifica y emite un *plan de etapas* (lista): FAST → `[ejecución, informe]`; DELIBERATE → todas; ACT → `[análisis, plan, ejecución(world-model gate), verificación, informe]`. La transición entre etapas la maneja el supervisor (state-machine), añadiendo VALIDATION e INFORME tras VERIFYING (recomendación de O1).

**Encaje de las piezas transversales:**
- **`/esfuerzo`:** un dict `effort_levels.py` nivel→{max_tokens, temp, n_alternativas, profundidad_loop, n_verificaciones, n_reintentos}. `run_flow(goal, effort)` lee ese nivel y lo propaga a CADA etapa (plan = nº subtareas, ejecución = step-budget, verificación = nº ejes, corrección = nº reintentos). Centraliza las constantes hoy dispersas (cumple regla).
- **Memoria multinivel:** el band-router inyecta inmediata/sesión/global en el contexto de cada etapa; el nivel "trabajo" (objetivos activos vía `goals/goal_tracker`) y "proyectos" (nuevo `ProjectMemory` vía db_pool) alimentan PLAN y VALIDACIÓN (el flujo escribe su estado-de-pasos a "proyectos" → habilita "retomar entre sesiones" real, recargando EXECUTING desde SQLite, cerrando O1 gap nº5).
- **Recapitulación automática:** `should_recap(history, goals, active_tasks)` (función plana) se llama tras cada etapa; dispara SessionSummarizer cuando supera umbral de tokens/tareas/objetivos, y **reinyecta** el resumen al working-memory antes de la siguiente etapa (cierra O3 gaps).
- **Autoevaluación:** la etapa de verificación ES la autoevaluación del path vivo — ejes calidad/coherencia/completitud/cumplimiento con heurísticas existentes (SelfCritic completeness + Verifier coseno + ResponseGate), regeneración gated 1× en el MISMO turno eligiendo por `score()` (no por longitud). Cierra O8 gaps sin LLM extra.

---

## 7. Plan de construcción (ordenado por dependencias y ROI)

Cada fase cierra con CHECK E2E real (CLI con `venv312\Scripts\python.exe`, mostrando output) + test de regresión que falle sin el fix (reglas 4 y 5 del repo).

**FASE 0 — Cumplimiento de reglas (desbloquea todo lo demás).**
- 0a. Decisión FedAvg (eliminar wiring `app.py:117,798` o editar `CLAUDE.md:43`). CHECK: arranque coordinator sin FedAvg / o regla actualizada + test ajustado. ROI alto, horas.
- 0b. Migrar `sqlite3.connect` → `db_pool` en `cognia_v3` (empezar `consolidation_engine.py:156`, `response_cache.py`, `code_memory.py`). Test que falle ante `sqlite3.connect` directo. ROI medio, 1 día.
- 0c. Fix `self_architect.py`: `db_pool` + `'llama3.2'`→`model_constants`. CHECK: architecture tests. ROI medio, horas.

**FASE 1 — Generación larga (prerequisito de respuestas largas).**
- 1a. Setear `last_stop_reason`/`last_tokens_predicted` en `_LlamaCppBackend` (`:225-248`). Test que falle sin el fix. ROI alto, horas. *Bloquea cualquier mejora de generate_long.*
- 1b. Guarda de ctx en `generate_long` (tail+outline al acercarse a 16k). Test de corte por ctx. ROI alto, 1 día. **Dep:** 1a.

**FASE 2 — Wiring al REPL (mayor ROI, sin algoritmia nueva).**
- 2a. `/buscar-memoria`, `/contradicciones`, `/ver-contexto` → llamada local a `SemanticMemorySearch`/`ConsistencyChecker`/`_build_memory_block_for` cuando `:8765` no responde (O4). CHECK CLI sin Electron. ROI alto, horas.
- 2b. `/deliberar <objetivo>` → CognitiveLoop DELIBERATE con backend real (O6). CHECK: trace plan/crítica/verify. ROI alto, horas.
- 2c. Recovery real en TaskQueue: re-enqueue de EXECUTING/PLANNING desde SQLite al iniciar (`task_queue.py:133-141`) (O1). CHECK: matar y reanudar. ROI alto, horas.

**FASE 3 — Esfuerzo (transversal, habilita el flujo).**
- 3a. `effort_levels.py` (dict nivel→params, centraliza constantes dispersas). ROI alto, horas.
- 3b. `/esfuerzo` en dispatcher + `_CMD_HELP`, persistido en `~/.cognia_config.json` (O5). CHECK: muestra nivel activo. ROI alto, horas. **Dep:** 3a.
- 3c. Propagar nivel a `/pensar`,`/razonar`,`/deliberar`,`/hipotesis`. Test: params crecientes. ROI alto, 1 día. **Dep:** 3b, 2b.

**FASE 4 — Autoevaluación en el path vivo.**
- 4a. Criterio de retry por `score()` (no por longitud) en ResponseGate (O8). ROI alto, horas.
- 4b. SelfCritic síncrono 1× gated en el path real, reemplazando por mejor score (O8). Test de regresión. ROI alto, horas. **Dep:** 4a.

**FASE 5 — El orquestador de flujo (sobre todo lo anterior).**
- 5a. `flow.py` con `STAGES` + `run_flow(goal, effort)` cableando supervisor+planner+CognitiveLoop+verificación; añadir VALIDACIÓN+INFORME tras VERIFYING. CHECK E2E: un goal real recorre las etapas. ROI alto, 1 día. **Dep:** 2,3,4.
- 5b. `/flujo` en el REPL pasando el orchestrator real (cierra O1 gap nº1 e `INFORME:75`). CHECK CLI. ROI alto, horas. **Dep:** 5a.
- 5c. Detección de bloqueos → tarea derivada en TaskQueue; re-planificación ante SUBTASK_FAILED (O1/O6). Test: falla 1er plan, corrige en 2º. ROI medio, días. **Dep:** 5a, 2c.

**FASE 6 — Memoria multinivel + recap (completar contexto).**
- 6a. Mapear los 5 niveles a piezas reales + decidir UNA taxonomía canónica; documentar en código; corregir `ROADMAP.md:854` (O2). ROI alto, horas.
- 6b. `should_recap` + cableado del recap automático en el CLI + reinyección al working-memory (O3). Test. ROI alto, días. **Dep:** 6a.
- 6c. `ProjectMemory` (nivel "proyectos" vía db_pool) + nivel "trabajo" (goal_tracker inyectable). Test E2E muestra resumen en el prompt (O2). ROI medio, días. **Dep:** 6a.

**FASE 7 — Generación jerárquica + self-architect honesto (largo plazo).**
- 7a. `generate_hierarchical` §3.1 + wiring `/largo`. E2E >5000 tokens con prefill acotado (O7). ROI alto, días. **Dep:** 1a,1b.
- 7b. `sandbox_tester.py` sobre `code_executor.run_python` (O9). ROI alto, 1 día. **Dep:** 0c.
- 7c. `generate_module_code` Ollama→`ShatteringOrchestrator.infer` (O9/O6). ROI alto, horas. **Dep:** 0c.
- 7d. Política de auto-corrección acotada (solo `param_update` reversible low-risk) (O6/O9). Test: high-risk NO se auto-aplica. ROI medio, 1 día. **Dep:** 7b.

---

## 8. Riesgos principales y mitigaciones

1. **Costo de tokens a 8 tok/s.** Niveles `/esfuerzo` altos y autoeval/deliberación multiplican inferencias (cada una decenas de segundos; "máximo" puede tardar minutos). **Mitigación:** evaluadores heurísticos sin LLM por defecto; LLM solo gated por umbral; presupuesto duro de 1 reintento; mostrar al usuario el costo estimado del nivel activo.

2. **Dos sistemas paralelos (memoria, tools, rutas de respuesta) → un tercer árbol.** Riesgo de extender en vez de consolidar. **Mitigación:** FASE 6a (taxonomía canónica única) y unificación de registries ANTES de construir; retirar explícitamente lo muerto (HierarchicalMemory/chimera, ruta de respuesta no servida).

3. **Wiring expone bugs latentes hoy ocultos.** El supervisor/CognitiveLoop nunca corrieron en el path de usuario; al cablearlos pueden aflorar fallos (p.ej. el bug q/k/v del path numpy). **Mitigación:** test de regresión por cada wiring (regla 5); CHECK E2E real con `venv312` (regla 4); fases pequeñas.

4. **NO-OP silencioso (Ollama / sandbox_tester / in-process stop_reason).** Código que "existe" pero no hace nada en el hardware real — viola "nada de mocks; código que corre o no cuenta". **Mitigación:** FASE 1a, 7b, 7c arreglan los tres; test E2E que falle si vuelve a ser NO-OP.

5. **Colisión con ctx 16k en generación larga.** Sin guarda, las rondas tardías inflan el prefill y desbordan/timeoutean. **Mitigación:** FASE 1b (guarda) + escalar timeout con el prefill acumulado, no solo con n_predict (`llama_backend.py:395-396`).

6. **Decisión FedAvg pendiente del dueño (no la puede tomar el agente).** Bloquea cumplimiento de regla dura y la auditoría de privacidad. **Mitigación:** elevar como decisión explícita (FASE 0a); hasta resolverla, no construir features que dependan del coordinator federado.

7. **Auto-corrección autónoma podría aplicar cambios dañinos.** **Mitigación:** acotar a `param_update` reversibles low-risk con `MAX_CHANGES_PER_DAY`, rollback registrado y gate del world-model; todo lo estructural permanece humano-en-el-loop (FASE 7d).

*Límite de honestidad: toda la evidencia file:line proviene de los auditores; donde un auditor declaró no haber verificado algo (tráfico FedAvg en Railway, conteo total de violaciones sqlite3, suficiencia de σ=0.01, suite completa en O10), queda señalado como no verificado y no se presenta como hecho.*

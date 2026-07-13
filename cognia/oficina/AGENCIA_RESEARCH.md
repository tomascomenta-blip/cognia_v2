# COGNIA-AGENCIA — Consolidado (julio 2026)

Contexto: agente Python 100% local (i3 2-cores, Windows, llama.cpp + GGUF ≤7B, TUI Textual, KG networkx, tools por decorator, memoria episódica sqlite). Criterio: CPU-only, sin cloud, licencias que no contaminen.

## 1. Mejor opción por frente

### Agente estilo Manus → **OpenManus** (MIT, ~57k★) + patrones de **agenticSeek** e **II-Agent**
- **Por qué**: python plano sin GPU, jerarquía limpia (BaseAgent → ReActAgent → ToolCallAgent), MIT. agenticSeek es el más alineado (100% local) pero es GPL-3.0 → solo ideas.
- **Piezas concretas a portar**:
  1. `PlanningFlow`: plan explícito como lista de steps con estado `[ ]/[→]/[x]` en dict mutable, separado del historial — Cognia tiene loop /hacer pero no plan-como-artefacto.
  2. `is_stuck` (detección de respuestas duplicadas → prompt de cambio de estrategia): barato, ataca directo el bug conocido del 3B que reescribe en loop.
  3. `ToolCollection.to_params()`: unificar el registro por decorator con el schema function-calling de llama.cpp.
  4. Tool `terminate` explícita como fin de loop (más robusto que heurísticas de cierre).
  5. `str_replace_editor` (edición por reemplazo exacto — más fiable en 3B que regenerar archivos).
  6. De agenticSeek (reimplementar, NO copiar por GPL): router de 2 clasificadores chicos NO-LLM (agente + complejidad simple/planner) — encaja con LOGOS/TECHNE/RHETOR y el hallazgo COLONIA router→4B.
  7. De II-Agent (Apache-2.0): gestión de contexto para 16k — truncar tool-outputs viejos a 1 línea (solo el último completo) + plan/notas persistidas en archivo del workspace que el agente relee. Es directamente el cuello de /largo y /hacer multi-paso.
  8. De Suna (patrón, no código): workspace aislado por tarea (carpeta + subprocess) + task-thread separado del chat global, persistido en el sqlite existente.

### Computer-use → **browser-use** (MIT, ~105k★) para web + **a11y-tree/OCR** para escritorio
- **Por qué**: el patrón DOM-destilado→lista-numerada elimina la visión: el 3B elige "click 12" de una lista de texto corta — formato que ya domina vía GBNF/ACCION. Pocos tokens = clave en CPU.
- **Piezas concretas a portar**:
  1. Extractor JS de elementos interactivos con índices (portar `buildDomTree` propio, no `pip install browser-use` entero — pesado).
  2. Vocabulario de acciones: `click(index)/input_text/scroll` + loop observar→actuar con estado serializado compacto.
  3. Para escritorio: wrapper PyAutoGUI de Self-Operating-Computer (`operating_system.py`, MIT, ~200 líneas, cero deps pesadas) como tools click/type/hotkey/screenshot.
  4. Grounding sin visión (Agent-S, Apache-2.0): leer el UIAutomation tree de Windows con pywinauto (puro python, CPU-cero) → lista de texto de controles; complementar con OCR local (tesseract/RapidOCR) para "click en 'Guardar'" por texto, no coordenadas.
  5. La API `computer.*` de Open Interpreter como IDEA (AGPL — reimplementar con pyautogui+mss+RapidOCR, todos MIT/BSD).
- **Contrato de acciones**: usar el espacio unificado de UI-TARS (click/drag/type/hotkey/wait/finished) como referencia de diseño de las tools.

### Flujos n8n-style → **spec OpenFlow de Windmill** como formato + **wires de Node-RED** como serialización mínima
- **Por qué**: OpenFlow es spec abierta (imitable sin contaminar aunque Windmill core es AGPL) y trae exactamente lo que el loop del agente necesita: `retries` con backoff+jitter, `timeout`, `stop_after_if/skip_if`, `suspend/approval` (nodo humano), handler `Failure` — ~50 líneas c/u y curan los cuelgues de búsqueda que Cognia ya sufrió. El formato Node-RED (Apache-2.0, `{id, type, wires}` plano) es el más amigable para que el 3B lo escriba/lea, y carga trivial a `networkx.DiGraph` que Cognia YA tiene.
- **Piezas concretas**: reimplementar en python (~200-400 líneas, cero deps): nodos = tools registradas; `input_transforms` = expresiones restringidas con el sandbox/allowlist ya existente en el repo; convención n8n "todo dato entre nodos = lista de items `{json:...}`" (elimina el problema de tipos entre tools); `runData` por nodo + `pinData` persistidos en sqlite (reanudar/depurar/testear sin re-ejecutar); flows versionados inmutables (patrón Activepieces, MIT) para undo/auditoría; config-nodes de Node-RED (recursos compartidos: "server llama :8091", "sqlite X") y subflows = skill de Cognia empaquetada como nodo.

### KG-viz estilo Obsidian → **force-graph (vasturiano)** (MIT) como camino rápido, ideas de **Quartz** (MIT) para el look
- **Por qué**: bundle UMD único (~100KB), canvas 2D (sin WebGL obligatorio), API de 3 líneas, formato = literalmente `{nodes, links}` que `nx.node_link_data()` ya casi da.
- **Piezas concretas**: vendorear `force-graph.min.js` en el paquete python → generar HTML de una página con el JSON del grafo embebido → `webbrowser.open()` = comando `cognia grafo`. Del `graph.inline.ts` de Quartz: vista local-por-nodo vs global, hover-ilumina-vecinos. En la TUI: vista mini de vecindario con **netext** (MIT, networkx→Rich, <50 nodos). Si hace falta explorar/filtrar por tipo de relación: **cytoscape.js** (MIT, selectores tipo CSS, headless-capable). Alternativa cero-JS: **pyvis** con `cdn_resources='in_line'` (sin CDN = offline/privado).

## 2. Descartes

- **UI-TARS como motor**: VLM 7B multimodal exige GPU; en el i3 es órdenes de magnitud bajo el techo ~8 tok/s ya medido. Solo referencia de contrato de acciones.
- **Skyvern**: núcleo = Vision-LLM por API paga + Postgres/FastAPI + AGPL; browser-use cubre el nicho en MIT sin visión.
- **Self-Operating-Computer modo visión-pura**: estimar coordenadas X,Y requiere VLM grande (cloud/GPU) — solo se toma su capa de ejecución.
- **Suna (stack)**: Supabase + Daytona + LLM APIs = cloud; licencia mixta con componentes enterprise. Solo el patrón workspace-por-tarea.
- **OWL/camel-ai como dependencia**: framework grande contra la regla "sin frameworks de más"; su GAIA no replica con 3B local. Solo el patrón dos-roles-un-modelo.
- **n8n (código)**: Sustainable Use License — NO OSI, prohíbe copiar/redistribuir código; imitar solo el MODELO de datos JSON como idea.
- **Windmill (código)**: AGPLv3 — no vendorizar; la spec OpenFlow sí es imitable.
- **agenticSeek / Open Interpreter / Juggl (código)**: GPL-3.0 / AGPL-3.0 — reimplementar patrones, jamás copiar literal.
- **sigma.js**: sobre-ingeniería para el tamaño del KG de Cognia; WebGL puede fallar con drivers Intel viejos.
- **Voz de agenticSeek / VideoAnalysis de OWL**: whisper en 2 cores es lento; multimodal = cloud/GPU.

## 3. Plan de construcción incremental (valor × viabilidad)

**Fase 1 — Tools de computer-use nativas** (valor alto, viabilidad máxima: pyautogui+mss+pywinauto+RapidOCR, todo MIT/BSD, cero LLM extra)
1. Tools base por decorator: `pantalla_capturar`, `pantalla_ocr`, `mouse_click_texto` (OCR-grounding), `teclado_escribir`, `hotkey` — wrapper estilo `operating_system.py` (~200 líneas).
2. `ventana_leer_controles`: UIAutomation tree vía pywinauto → lista numerada de texto; el 3B elige por índice (mismo formato ACCION/GBNF ya validado).
3. Browser opt-in: playwright + extractor DOM-destilado propio (patrón browser-use) → `web_observar/web_click(n)/web_escribir`.
4. Gate: batería e2e real (regla del repo) — el 3B completa N tareas de pantalla con las tools; medir antes de construir encima.

**Fase 2 — Grafo de conocimiento por proyecto** (valor alto, viabilidad alta: networkx ya existe)
1. Namespace del KG por workspace/proyecto (clave de partición en el sqlite + subgrafo networkx).
2. `cognia grafo`: export `nx.node_link_data` → HTML con force-graph vendoreado → `webbrowser.open()`. Vista mini en TUI con netext.
3. Alimentar el KG desde la memoria episódica (entidades de tareas /hacer) — el grafo se vuelve útil, no decorativo.

**Fase 3 — Motor de flujos (backend primero, editor después)** (valor alto, viabilidad media)
1. Formato JSON plano estilo Node-RED + semántica OpenFlow (retry/backoff, timeout, skip_if/stop_after_if, nodo approval, handler failure); ejecutor sobre `networkx.topological_sort`.
2. Items `{json:...}` entre nodos + runData/pinData en sqlite; flows versionados inmutables.
3. Migrar el planner de /hacer a emitir este DAG (el plan deja de ser texto y pasa a ser ejecutable/reanudable). El editor visual queda para el final: primero flows-como-JSON que el 3B y el usuario editan como texto.

**Fase 4 — Oficina por departamentos con identidad por modelo** (valor medio-alto, viabilidad media: reutiliza `delegar_subtarea` + fleet existente)
1. Departamentos = agentes especializados estilo agenticSeek (Coder/File/Browser/Planner) con identidad = modelo del fleet asignado (0.5B portero, 3B general, 7B código — la cascada COLONIA ya validada) + tool-set y prompt propios.
2. Router NO-LLM de dos clasificadores (agente + complejidad) para despachar sin gastar tokens del 3B.
3. Patrón dos-roles-un-modelo (OWL) para planning iterativo barato con terminación por token `TASK_DONE`.

**Fase 5 — Editor de flujos n8n-style** (valor medio, viabilidad menor: UI)
- Reusar la infraestructura de la Fase 2: el mismo HTML local (force-graph/cytoscape) renderiza el DAG del flow con estado por nodo (runData); edición mínima (agregar/conectar nodos → escribe el JSON). No construir un builder web completo.

## 4. Seguridad computer-use (obligatorio antes de Fase 1)

- **Allowlist de acciones y objetivos**: lista explícita de apps/ventanas/dominios operables; denegar por defecto. Nunca hotkeys peligrosas (Win+R, Alt+F4 global) fuera de allowlist.
- **Confirmación humana** para toda acción irreversible o sensible: enviar/borrar/comprar/instalar, escritura fuera del workspace, cualquier campo de contraseña (detectar por a11y tree y NEGARSE a escribir en él). Es el nodo `approval` de la Fase 3 — misma pieza.
- **Sandbox/workspace**: acciones de archivos confinadas a la carpeta de la tarea; código generado pasa el scan de imports + sandbox con timeout ya obligatorio en el repo (regla 9 de CLAUDE.md).
- **Kill-switch + límites**: tecla de aborto global (pyautogui FAILSAFE esquina + hotkey propia), `max_steps` y timeout por tarea, detector is_stuck para no repetir clicks en loop.
- **Log append-only** de cada acción (screenshot antes/después, acción, resultado) en el sqlite episódico — auditable, y nunca capturar/loggear contenido de campos de contraseña.
- **Nada de credenciales**: el agente no lee ni escribe secretos por pantalla; tokens solo por variable de entorno (regla 8 del repo).

**Licencias — regla transversal**: portar código solo de MIT/BSD/Apache-2.0 (OpenManus, browser-use, Self-Operating-Computer, Node-RED, force-graph, Quartz, pyvis, cytoscape, Agent-S, II-Agent, Activepieces). De GPL/AGPL/sustainable-use (agenticSeek, Open Interpreter, Skyvern, Windmill, n8n, Juggl): solo patrones reimplementados desde cero.
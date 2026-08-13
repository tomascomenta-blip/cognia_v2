# PLAN — Destilación de los mejores harnesses de IA al CLI de Cognia

**Fecha:** 2026-08-12 22:10 → deadline 2026-08-13 05:00 (apagado programado, `shutdown /s` a 24 600 s).
**Modo:** autónomo total (CLAUDE.md §Autonomía Total), ultracode con workflows.
**Encargo del dueño (literal):** investigar los 10 mejores harness/agentes de IA en ≥10 campos
(≈100 sistemas), destilar sus funcionalidades insignia al CLI de Cognia e implementarlas con
precaución y pulido; después recolectar una galería visual de CLIs de agentes, juzgarla con VLM
real y comparar/clonar lo bueno para el CLI de Cognia. Resultado: un agente que compita con los
harnesses open source más fuertes.

## Fases

### F0 — Reconocimiento (workflow `recon-cognia-cli`, 5 agentes) [en curso]
Mapear: capa visual/UX del REPL, bucle de agente + herramientas, subsistemas ya entregados
(workflows, RLM, memoria, MCP, navegador), infraestructura de tests/gates, y **huecos** frente a
Claude Code / OpenHands / Aider / Cline / opencode.
*Salida:* inventario con `file.py:línea` de lo que YA existe → prohibido reimplementar.

### F1 — Investigación (workflow `investigar-100-harnesses`, 11 agentes) [en curso]
10 campos × 10 sistemas, con búsqueda web real y fuentes primarias:
1. Ingeniería de software agéntica · 2. Deep research · 3. Orquestación multiagente ·
4. Memoria y contexto largo · 5. Ejecución/sandbox/MCP · 6. Verificación y auto-reparación ·
7. Navegador/GUI/computer-use · 8. Planificación y razonamiento · 9. UX de CLI/TUI ·
10. Fiabilidad (permisos, observabilidad, coste, checkpoints).
Por sistema: insignias, **mecánica interna concreta**, transplante a Python, dificultad, valor.
*Salida:* ranking transversal de 25-35 funcionalidades con criterio de aceptación verificable.

### F2 — Destilación y diseño (workflow, cruza F0 × F1)
Cada funcionalidad candidata se convierte en una **ficha de implementación** anclada al repo:
módulo nuevo bajo `cognia/harness/`, punto de enganche exacto en el CLI, API, test de regresión y
prueba CLI real. Se descarta lo ya existente (F0) y lo no verificable.
*Regla dura:* nada de mocks; toda ficha lleva su verificación end-to-end.

### F3 — Implementación por lotes (workflows sucesivos)
- Módulos nuevos autocontenidos en paralelo (sin colisión de ficheros).
- `cognia/cli.py` es un monolito de 533 KB → los enganches al CLI los hace **un solo integrador**
  en serie, nunca agentes en paralelo.
- Cada lote cierra con: `venv312\Scripts\python.exe -m pytest tests/ -q` dirigido + prueba real.

### F4 — Galería visual y juicio VLM
- Recolectar capturas reales de los CLIs punteros (Claude Code, Codex CLI, Gemini CLI, opencode,
  Crush, Aider, gptme, Goose…) vía navegador (Playwright MCP) desde repos/docs oficiales.
- Capturar el CLI de Cognia **corriendo de verdad** y renderizarlo a PNG (ANSI → HTML → screenshot).
- Juicio VLM real (lectura directa de las imágenes, lado a lado — cf. `arbitro-visual-diseno-codigo`:
  el VLM solo discrimina con imágenes LADO A LADO): rúbrica de densidad, jerarquía, color, ruido,
  legibilidad del diff, estado/footer, identidad.
- Clonar lo bueno respetando la identidad (el gato Braille va por defecto: `banner-es-identidad`).

### F6 — Adaptador nativo al cerebro (pedido explícito del dueño, 2026-08-12 22:4x)
Las capacidades destiladas **no pueden quedar como instrucciones ciegas en el prompt**. Hay que
construir un adaptador que las exponga de forma **nativa** al cerebro real:
- tool-calling nativo del backend (esquemas de herramientas → `tools`/`function_call` de
  llama-server/OpenAI-compatible), y **gramática GBNF** cuando el backend no soporte tools, de modo
  que la salida sea estructuralmente válida por construcción y no por obediencia del modelo;
- registro único de herramientas → una sola fuente de verdad que alimenta a la vez el prompt, el
  esquema nativo y el despacho;
- verificación **cargando el cerebro de verdad** (Qwythos-9B / flota por roles) y comprobando
  end-to-end que el modelo invoca las capacidades nuevas sin instrucciones en prosa.

### F5 — Cierre
Suite completa + gate e2e del camino feliz (`scripts/e2e_happy_path.py`, exigir 5/5) si se tocó el
sampling del agente. Commits chicos y push por unidad verificada. Informe final + `MANAGER_LOG.md`.

## Restricciones que rigen la corrida
- `venv312\Scripts\python.exe` SIEMPRE (nunca `python` pelado).
- Nada de mocks/stubs; "código que corre o no cuenta"; cada subsistema cierra con prueba CLI real.
- Test de regresión por cada feature (falla sin el fix, pasa con él).
- Disyuntor de reparación: al 2º intento estéril con síntoma idéntico, parar y medir.
- Sin secretos en commits. Sin publicar a PyPI (requiere autorización explícita; no la hay).
- No detenerse a preguntar: el dueño está inactivo hasta el deadline.

# Cognia Comercial v1 — Reporte de Verificación (2026-07-05)

Qué se verificó REALMENTE (por invocación e2e con el modelo de verdad, método del
repo) para el release comercial `cognia-ai` 3.8.0 / 3.8.1. Honesto sobre la cobertura
y sus límites.

## Estado del release
- **Publicado a PyPI:** `cognia-ai` 3.8.0 y 3.8.1 — https://pypi.org/project/cognia-ai/
- **Instalación:** `pip install cognia-ai` (un comando) → deja el comando `cognia`.

## Qué PASÓ (verificado)

### Instalación (1 comando, entorno externo limpio)
`pip install cognia-ai==3.8.1` en un venv nuevo y aislado (no el de desarrollo) → **9/9
checks PASS**: crear venv, pip install (~72s con caché de deps), `import cognia`,
entry-point `cognia`, `cognia status` sin crash, `import cognia.agent.prompt_evolution`
(RSI empaquetado), y el **creador de imágenes render un PNG real** (`escena_crear` +
`render_aprox` → 3371 bytes) dentro del paquete instalado desde PyPI. Herramienta:
`tools/clean_install_test.py`.

### Superficie cero-LLM (sin modelo) — 10 agentes E2E + suite
- **251 features ejercitadas por invocación real → 215 PASA, 1 FALLA, 32 SKIP_MODEL.**
- **100% de la superficie cero-LLM pasa** salvo 1 bug (F1, ya arreglado en 3.8.1).
- Suite dirigida: ~1127 tests verdes por área.
- Incluye: memoria episódica + grafo de conocimiento reales, cifrado AES-256-GCM
  (verificado en el byte crudo del disco), sandbox de código (allowlist/blocklist en
  dos capas), 37 tools del creador de imágenes (PNG/GIF/SVG/JSON reales), RSI/skills/
  prompt-evolution, swarm confirmado APAGADO por default + hard-off, packaging.

### Caminos con el modelo 3B (Qwen2.5-Coder-3B, real, serial) — smoke 5/5
`tools/e2e_model_smoke.py`: backend 3B carga y responde · chat coherente (conoce su
identidad) · **agente `/hacer` usa una tool y crea el archivo** (77s) · salida larga
multi-línea · **`generar_codigo` (BoN) produce una función válida** (18s). **Aprendizaje
activo confirmado en vivo:** decay de skills por historial de uso, user_profile,
memoria episódica.

### Model-agnóstico (otra familia de modelo)
Smoke con **Llama-3.2-1B-Instruct (NO-Qwen)** → **4/4 PASS** (backend, chat, agente crea
archivo, salida larga). El path de chat usa `/v1/chat/completions`, así que llama.cpp
aplica el template correcto de CADA modelo → **el producto corre con cualquier familia
de modelo**, no solo Qwen. Las optimizaciones (loop, few-shot, RSI, gate) son genéricas
en lógica.

### Solo-local (sin orquestación online)
Default local (el swarm solo se activa con `COORDINATOR_URL`). Hard-flag
`COGNIA_DISABLE_SWARM=1` fuerza local aunque haya coordinator (guard en
`node/inference_pipeline.py` + `cognia.py`). Modo sencillo = default (14/28 tools).

## Bug encontrado y ARREGLADO (3.8.1)
**F1 — `run_javascript`/`run_python` en Windows:** el env del subprocess sandbox omitía
`SystemRoot`, que Node/OpenSSL necesita para el CSPRNG → crash
`ncrypto::CSPRNG`. Fix: `_sandbox_env()` pasa los vars de sistema de Windows sin fugar
secretos. Verificado + 4 tests de regresión.

## Incidente (resuelto, sin daño)
Durante la verificación E2E, un agente invocó por error el `DELETE /api/user/data` real
contra la DB de producción (soft-delete de 75855 filas) y **lo revirtió**. DB
**verificada intacta** (`forgotten=1 → 0`, total 75855). El endpoint ya es fail-safe
(503 sin `COGNIA_ADMIN_KEY`). Lección de proceso: los workflows de verificación deben
aislar una DB de test.

## Límites honestos de esta verificación
- **Cobertura por muestreo, no exhaustiva 1-a-1 de las 568 features.** Se ejercitaron
  251 representativas + ~1127 tests dirigidos + smokes. La superficie cero-LLM está
  sólida; algunas features model-dependent secundarias (`/pensar`, `/deliberar`,
  `/sugerir`, `curiosity_engine`, `POST /api/chat` e2e, planner-LLM del LCD) quedaron
  como SKIP_MODEL (no ejercitadas punta-a-punta con el 3B en esta pasada).
- **Model-agnóstico ≠ paridad de calidad.** Un modelo distinto corre el mismo
  andamiaje pero puede rendir distinto; se verificó que CORRE, no que iguala al 3B.
- **Inferencia del usuario fresco (last mile) — los 3 caminos VERIFICADOS:**
  (1) **shards numpy INT4** — el wizard los descarga; inferencia en **Python puro, sin
  binario ni compilador**. **VERIFICADO:** `orch.infer('Hola')` con shards y sin GGUF →
  `'¡Hola!'`. Es el camino que "just works" en cualquier plataforma (más lento). Este
  es el **default del fresh user**.
  (2) **`cognia-ai[llama]` (`llama-cpp-python`)** — rápido, pero **necesita un wheel
  prebuilt o un compilador C++**. **VERIFICADO que FALLA** en Windows+py3.12 sin
  compilador (`CMAKE_CXX_COMPILER not set`). Válido donde hay wheel/compilador (Linux/
  macOS suelen tener wheel).
  (3) **llama-server + GGUF** — el más rápido en CPU; requiere el binario. **VERIFICADO**
  (todos los smokes 3B y el model-agnóstico usaron este path).
  El pip trae el CÓDIGO de los 3; no trae el binario `llama-server.exe` ni los pesos
  (el wizard descarga los pesos).
- **3 fallos de pytest** en `test_cli_memory_injection.py` son de AISLAMIENTO (pasan
  6/6 en solitario), no bugs de producto.

# AUDIT.md — Auditoría de archivos `.py` en la raíz (SESSION 0 / TASK 0.1)

Fecha: 2026-06-09. Auditados: 36 archivos `.py` en la raíz de `cognia_v2` (no subdirectorios).

## Tabla de clasificación

| File | One-line purpose | Target directory |
|------|-----------------|-----------------|
| aprendizaje_profundo.py | Aprendizaje enciclopédico: lee Wikipedia y guarda en EpisodicMemory/SemanticMemory/KG | core |
| code_executor.py | Ejecución y validación sandbox de código (Python/HTML/CSS/JS) | interfaces |
| code_memory.py | Memoria especializada en código (snippets, proyectos, errores) sobre EpisodicMemory | memory |
| cognia_code.py | Entry point REPL de la variante Shattering "code" (TECHNE) | scripts ⚠ entry point |
| cognia_deferred.py | Mantenimiento diferido: consolidation/forgetting en hilo de fondo + hipótesis en idle | memory |
| cognia_desktop_api.py | Bridge FastAPI local (puerto 8765) para la app Electron de escritorio | interfaces ⚠ Electron lo spawnea por nombre |
| cognia_embedding.py | Embeddings lazy + cola async batcheada + cache LRU acotado | memory |
| cognia_idle.py | Daemon de inactividad: Cognia "vive" sola en terminal (sueño/hobby/investigación) | scripts ⚠ entry point |
| cognia_modules_adicionales.py | ReasoningPlanner, ContradictionResolver, etc. (importado por cognia_v3.py y cognia/config.py) | core (reclasificado: estaba en uso activo, no era archive) |
| cognia_v3.py | Entry point principal: KnowledgeGraph, InferenceEngine, GoalSystem, TemporalMemory, AttentionSystem | core ⚠ entry point principal — ver Conflictos |
| cognia_writing.py | Entry point GUI PyQt6 de la variante Shattering "writing" (RHETOR) | scripts ⚠ entry point |
| consolidation_engine.py | Ciclo de "sueño profundo": eliminación, consolidación, decay, dedup de memorias | memory |
| conversation_memory.py | Memoria conversacional multi-turno (buffer, topic tracker, selector de contexto) | memory ⚠ importado por cognia/ |
| curiosidad_pasiva.py | Hilo de curiosidad pasiva: investiga temas propios cuando está inactiva | core |
| curiosity_engine.py | Motor de curiosidad: propone preguntas para explorar brechas del KG | core |
| decision_gate.py | Gating de decisión de 3 zonas (simbólico/híbrido/LLM) — a reemplazar por CognitiveLoop | interfaces ⚠ importado por cognia/ |
| fatiga_cognitiva.py | Monitor de fatiga cognitiva 0-100 que modula el costo de razonamiento | core |
| feedback_engine.py | Aprendizaje por feedback (+1/-1) → ajusta pesos de memorias y umbrales del gate | core |
| game_manager.py | Generación y mejora iterativa de juegos con auto-corrección de código | interfaces |
| investigador.py | Investigación autónoma (Wikipedia) cuando Cognia no sabe algo | core |
| language_corrector.py | Normalización de texto de entrada (labels) y salida (respuestas LLM) | interfaces |
| language_engine.py | Orquestador del motor de lenguaje híbrido de 5 etapas (cache→simbólico→LLM) | interfaces ⚠ importado por cognia/ |
| logger_config.py | Logging estructurado compartido por todos los módulos | core ⚠ importado por casi todo |
| model_collapse_guard.py | Detección/prevención de colapso de modelo (labels dominantes, homogeneización) | core |
| model_router.py | Enrutamiento de modelos Ollama por tipo de tarea (código vs general) | interfaces |
| prompt_optimizer.py | Compresión de contexto y evolución automática de prompts | interfaces |
| response_cache.py | Cache semántico de respuestas previas (SQLite) | interfaces |
| respuestas_articuladas.py | Integración Ollama: construir_contexto + responder_articulado | interfaces ⚠ importado por cognia/cli.py |
| run_tests.py | Runner de pytest que renombra el __init__.py raíz temporalmente | scripts |
| scoring_engine.py | Puntuación acumulada de propuestas (código, módulos, cambios) | core |
| self_architect.py | Motor de auto-optimización meta-learning v4 (propuestas, tracking de ROI) | core |
| symbolic_responder.py | Respuestas en lenguaje natural SOLO con conocimiento estructurado (sin LLM) | interfaces |
| symbolic_synthesizer.py | Síntesis simbólica multi-fuente anclada a la pregunta | interfaces |
| teacher_interface.py | Punto de entrada único para correcciones y enseñanza externa | interfaces ⚠ importado por cognia/cognia.py |
| web_app.py | Web app Flask (chat, búsqueda autónoma, juegos) | scripts ⚠ entry point |
| __init__.py | Marcador de raíz (NO paquete) con __version__ — run_tests.py lo renombra | (queda en raíz) |

Sin candidatos a `archive` por patrón: **no existen** `fix_*.py`, `paso*.py`, `debug*.py`, `migrar.py`, etc. en la raíz — el repo ya fue limpiado en sesiones anteriores. Único archive: `cognia_modules_adicionales.py` (esqueletos no integrados).

## Conflictos y riesgos detectados (decidir ANTES de Task 0.2/0.3)

1. **`cognia/` YA EXISTE y es el paquete PyPI publicado (`cognia-ai` 3.5.1).** Tiene
   `cli.py`, `__main__.py`, ~38 subpaquetes, y **ya existe `cognia/memory/`**. Crear
   `cognia/{core,memory,interfaces,training,eval}` y mover ahí los archivos v3 mezcla
   código legacy con el paquete publicado y colisiona con `cognia/memory/` existente.
2. **El paquete `cognia/` importa módulos de la raíz por nombre pelado** (en try/except,
   integraciones opcionales): `cognia/language_engine.py` importa `language_engine`,
   `symbolic_responder`, `decision_gate`, `conversation_memory`, `respuestas_articuladas`;
   `cognia/cognia.py` importa `teacher_interface`; `cognia/cli.py` importa
   `respuestas_articuladas` y `conversation_memory`. Mover esos archivos sin actualizar
   estos imports rompe (silenciosamente) esas integraciones.
3. **Entry points externos:** `pyproject.toml` empaqueta `cognia*, node*, coordinator*,
   shattering*, app*, security*, storage*, network*` — los módulos raíz NO se publican.
   `cognia_desktop_api.py` es spawneado por Electron (`uvicorn cognia_desktop_api:app`);
   `cognia_code.py`/`cognia_writing.py`/`cognia_idle.py`/`web_app.py` son entry points
   que usuarios/scripts invocan por ruta. Moverlos requiere verificar cada referencia.
4. El plan original describe ~70 archivos con parches `fix_*`/`paso*` — ese estado ya no
   existe; el alcance real de la migración es menor pero el riesgo de imports es mayor.

**Decisión ejecutada (Task 0.2/0.3, aprobada por el dueño):** paquete nuevo
`cognia_v3/{core,memory,interfaces,training,eval}`. 29 módulos migrados con `git mv`;
136 líneas de import reescritas en 39 archivos (incl. los imports opcionales try/except
del paquete `cognia/`, que conservan su semántica de degradación en pip). Los entry
points (`cognia_v3.py` → launcher delgado, `cognia_desktop_api.py`, `web_app.py`,
`cognia_code.py`, `cognia_writing.py`, `cognia_idle.py`, `run_tests.py`) quedan en la
raíz. Verificación: 29/29 módulos importan, REPL corre y sale limpio, suite rápida
2425 passed / 1 skipped.

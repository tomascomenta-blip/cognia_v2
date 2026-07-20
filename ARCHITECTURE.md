# ARCHITECTURE.md — Cognia v3 (capa cognitiva)

> Ámbito: este documento cubre el paquete `cognia_v3/` (la arquitectura cognitiva
> simbólico-neural migrada desde la raíz en SESSION 0, ver `AUDIT.md`). El resto del
> repo (paquete PyPI `cognia/`, Shattering, coordinator, network, etc.) tiene sus
> propias fuentes: `ROADMAP.md`, `SHATTERING_V2_DESIGN.md`, `CLAUDE_NOTES.md`.

## Qué es

Cognia v3 es una IA personal que combina:
- **Capa simbólica**: KnowledgeGraph (networkx + SQLite), InferenceEngine (forward
  chaining), GoalSystem, TemporalMemory, AttentionSystem, ConceptCompressor —
  todo dentro de `cognia_v3/core/cognia_v3.py`.
- **Capa generativa**: modelo local vía Shattering (shards INT4 en `model_shards/`)
  u Ollama, orquestado por el LanguageEngine de 5 etapas.
- **Capa de integración**: pipeline cache → simbólico → híbrido → LLM con gating
  de decisión de 3 zonas.

## Estructura de directorios

```
cognia_v3/
├── __init__.py            # re-export lazy: `from cognia_v3 import Cognia` funciona
├── core/                  # cognición simbólica e infraestructura
│   ├── cognia_v3.py       # módulo principal: clase Cognia, KG, inferencia, REPL
│   ├── logger_config.py   # logging estructurado compartido (lo importa medio repo)
│   ├── fatiga_cognitiva.py        # monitor de fatiga 0-100
│   ├── curiosity_engine.py        # propone preguntas para brechas del KG
│   ├── curiosidad_pasiva.py       # hilo de investigación autónoma en idle
│   ├── investigador.py            # búsqueda Wikipedia/DuckDuckGo cuando no sabe
│   ├── aprendizaje_profundo.py    # ingesta enciclopédica → memorias + KG
│   ├── feedback_engine.py         # feedback +1/-1 → pesos de memorias
│   ├── model_collapse_guard.py    # anti-colapso por labels dominantes
│   ├── scoring_engine.py          # puntuación de propuestas
│   ├── self_architect.py          # auto-optimización meta-learning v4
│   └── cognia_modules_adicionales.py  # ReasoningPlanner, ContradictionResolver, etc.
├── memory/
│   ├── conversation_memory.py     # contexto multi-turno (buffer + topic tracker)
│   ├── consolidation_engine.py    # "sueño profundo": consolidación/decay/dedup
│   ├── cognia_embedding.py        # embeddings lazy + cola async + LRU
│   ├── cognia_deferred.py         # mantenimiento diferido fuera del hot-path
│   └── code_memory.py             # memoria especializada en código
├── interfaces/
│   ├── language_engine.py         # orquestador 5 etapas (cache→simbólico→LLM)
│   ├── decision_gate.py           # gating 3 zonas (a reemplazar por CognitiveLoop)
│   ├── teacher_interface.py       # correcciones y enseñanza externa
│   ├── respuestas_articuladas.py  # integración Ollama (llamar_ollama, contexto)
│   ├── model_router.py            # ruteo de modelos por tipo de tarea
│   ├── symbolic_responder.py      # respuestas sin LLM desde el KG
│   ├── symbolic_synthesizer.py    # síntesis multi-fuente anclada a la pregunta
│   ├── response_cache.py          # cache semántico de respuestas
│   ├── prompt_optimizer.py        # compresión de contexto / evolución de prompts
│   ├── language_corrector.py      # normalización entrada/salida
│   ├── code_executor.py           # sandbox de ejecución/validación de código
│   └── game_manager.py            # generación iterativa de juegos
├── training/                      # (SESSION 2) DatasetGen + QLoRA
│   └── sdpc/                      # (SESSION 3) Protocolo del Aula / SDPC E1
└── eval/
    └── baseline.py                # benchmark de 10 preguntas, JSON con scores
```

Entry points que quedan en la raíz (launchers / apps):
- `cognia_v3.py` — REPL principal (delgado; delega en `cognia_v3.core.cognia_v3.repl`)
- `web_app.py` — web app Flask
- `cognia_idle.py` — daemon de inactividad
- `cognia_desktop_api.py` — bridge FastAPI para Electron (puerto 8765)
- `cognia_code.py` / `cognia_writing.py` — variantes Shattering
- `run_tests.py` — runner de pytest

## Cómo correr

```powershell
# REPL principal (usar SIEMPRE venv312 — el venv/ del repo está roto)
.\venv312\Scripts\python.exe cognia_v3.py

# Baseline de evaluación (stub + modelo real si hay shards INT4 u Ollama)
.\venv312\Scripts\python.exe -m cognia_v3.eval.baseline

# Tests rápidos
.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```

## Decisiones de la migración (SESSION 0)

- `cognia_v3/` es un paquete NUEVO, separado del paquete PyPI `cognia/` (decisión del
  dueño): cero riesgo para `cognia-ai` publicado, que ya tenía `cognia/memory/` ocupado.
- Los imports bare del resto del repo (`from logger_config import ...`) fueron
  reescritos a `cognia_v3.core.*` / `cognia_v3.memory.*` / `cognia_v3.interfaces.*`.
  Los imports opcionales en `cognia/` (try/except) conservan su semántica: funcionan
  en el repo, degradan silenciosamente pip-installed (igual que antes).
- El paquete `cognia_v3/` tiene precedencia de import sobre el launcher homónimo de
  la raíz; `cognia_v3/__init__.py` re-exporta lazy los símbolos del módulo principal.

## Próximos pasos

1. **CognitiveLoop** (`cognia_v3/interfaces/cognitive_loop.py`) — orquestador central
   FAST / RECALL / DELIBERATE / ACT que reemplaza a `decision_gate.py` (SESSION 1).
2. **DatasetGen** — KG triples + episodios → pares prompt/completion JSONL (SESSION 2).
3. **QLoRA** — adapter sobre el modelo base congelado con el dataset propio (SESSION 2).
4. **SDPC E1** — validación falsable del Protocolo del Aula en MNIST: ¿SDPC ≥ 95% del
   accuracy de backprop? PASS → E2; FAIL → se archiva y sigue QLoRA (SESSION 3).

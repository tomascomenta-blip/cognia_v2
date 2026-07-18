# bbrain.md — Cerebro del repo Cognia

> AUTOGENERADO por cognia/bbrain.py — no editar a mano; regenerar con `cognia bbrain`.
> Generado: 2026-07-18 12:21:31

## Entorno
- Python: 3.12.10 (C:\Users\usuario\Desktop\cognia_v2\venv312\Scripts\python.exe)
- SO: Windows-11-10.0.26200-SP0
- CPU: AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD
- Cores: 6 fisicos / 12 logicos
- RAM: 33.4 GB
- GPU: NVIDIA GeForce RTX 5060 Ti, 16311 MiB

## Backend LLM
- GGUF activo (node.llama_backend): C:\Users\usuario\.cognia\models\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf
- Modelos en C:\Users\usuario\.cognia\models: qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf, qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf, qwen2.5-coder-0.5b-instruct-q8_0.gguf, qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf, qwen2.5-coder-14b-instruct-q4_k_m-00002-of-00002.gguf
- Shards NPZ en C:\Users\usuario\.cognia\shards\qwen-coder-3b-q4: shard_0.npz, shard_1.npz, shard_2.npz, shard_3.npz
- Ollama: no disponible en http://localhost:11434

## Mapa del repo
- Modulos .py top-level: 36
- cognia/: 209 archivos .py
- node/: 15 archivos .py
- shattering/: 18 archivos .py
- coordinator/: 10 archivos .py
- storage/: 2 archivos .py
- security/: 4 archivos .py
- tests/: 194 archivos .py
- Archivos de test (tests/test_*.py): 191

## Radar de cobertura (anti-danos-colaterales)
- Modulos con simbolos publicos: 229
- SIN ninguna mencion en tests/: 45
- Fuera del radar (revisar al tocar features vecinas):
  * aprendizaje_profundo.py (3 simbolos publicos)
  * cognia_deferred.py (2 simbolos publicos)
  * conversation_memory.py (6 simbolos publicos)
  * decision_gate.py (5 simbolos publicos)
  * feedback_engine.py (5 simbolos publicos)
  * game_manager.py (5 simbolos publicos)
  * investigador.py (8 simbolos publicos)
  * language_corrector.py (1 simbolos publicos)
  * logger_config.py (5 simbolos publicos)
  * model_collapse_guard.py (1 simbolos publicos)
  * prompt_optimizer.py (5 simbolos publicos)
  * symbolic_responder.py (4 simbolos publicos)
  * symbolic_synthesizer.py (3 simbolos publicos)
  * teacher_interface.py (3 simbolos publicos)
  * cognia/goal_and_pattern_engine.py (9 simbolos publicos)
  * cognia/ingest.py (2 simbolos publicos)
  * cognia/logger_config.py (5 simbolos publicos)
  * cognia/memory/adapter_store.py (1 simbolos publicos)
  * cognia/memory/working.py (2 simbolos publicos)
  * cognia/memory_response_engine.py (2 simbolos publicos)
  * cognia/migrations/runner.py (2 simbolos publicos)
  * cognia/program_creator/evaluator.py (3 simbolos publicos)
  * cognia/program_creator/generated_programs/cognia_game/game.py (1 simbolos publicos)
  * cognia/program_creator/generated_programs/fractal_pattern_renderer/program.py (4 simbolos publicos)
  * cognia/program_creator/generated_programs/franzs_treasure_hunt/program.py (1 simbolos publicos)
  * cognia/program_creator/generated_programs/royal_favors/program.py (1 simbolos publicos)
  * cognia/program_creator/generated_programs/untitled_procedural_story_generator_with_built_in/program.py (2 simbolos publicos)
  * cognia/program_creator/generator.py (7 simbolos publicos)
  * cognia/program_creator/program_creator.py (5 simbolos publicos)
  * cognia/program_creator/sandbox_runner.py (2 simbolos publicos)
  * cognia/program_creator/storage.py (10 simbolos publicos)
  * cognia/research_engine/knowledge_integrator.py (3 simbolos publicos)
  * cognia/research_engine/research_orchestrator.py (4 simbolos publicos)
  * cognia/research_engine/researcher.py (2 simbolos publicos)
  * cognia/ux/messages.py (1 simbolos publicos)
  * node/client.py (1 simbolos publicos)
  * node/downloader.py (4 simbolos publicos)
  * node/local_adapter.py (3 simbolos publicos)
  * node/relay_client.py (2 simbolos publicos)
  * shattering/distillation/data_generator.py (3 simbolos publicos)
  * ... y 5 mas

## Reglas del proyecto

### Restricciones duras (no negociar)
- Entorno: usar SIEMPRE `venv312\Scripts\python.exe` (Python 3.12). El `venv/` del repo
  esta roto (Python 3.14, wheels faltantes). Nunca `python` pelado para tests o scripts.
- Sin PyTorch en nodos. Sin sharding WAN sincrono. Sin FedAvg. Sin draft model centralizado.
- Cero datos personales centralizados.
- Nada de mocks/stubs en produccion. Codigo que corre o no cuenta: cada subsistema
  cierra con prueba CLI real.
- Sin `sqlite3.connect()` directo -> usar `storage/db_pool.py`.
- Sin constantes de modelo hardcodeadas -> usar `shattering/model_constants.py`.
- Secretos NUNCA commiteados: `.env`, tokens y claves quedan fuera de git; cargar
  tokens por variable de entorno y redactar cualquier secreto del output.

### Metodo de trabajo esencial
1. Verificar antes de construir: leer el codigo real y ejecutar la pieza ANTES de
   construir encima; no confiar en docs viejas sin verificar la afirmacion clave.
2. Diagnostico antes que parche: encontrar la causa raiz (leer codigo, reproducir el
   bug) en vez de tapar el sintoma.
3. Verificacion REAL, no solo pytest: cerrar cada cambio corriendo el CLI / el modelo
   de verdad end-to-end y mostrando el output real. pytest es necesario pero no
   suficiente.
4. Test de regresion por cada bug/feature: un test que falle sin el fix y pase con el.
   Reportar el conteo real (N passed / M failed).
5. Codigo concreto, sin abstracciones de mas: funciones planas, dicts, registries
   simples; igualar estilo y densidad de comentarios del codigo vecino.
6. Honestidad: declarar limites y trade-offs; si algo queda a medias, decirlo.

### Verificacion rapida
```
.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```

# bbrain.md — Cerebro del repo Cognia

> AUTOGENERADO por cognia/bbrain.py — no editar a mano; regenerar con `cognia bbrain`.
> Generado: 2026-07-31 09:40:50

## Entorno
- Python: 3.12.10 (C:\Users\usuario\Desktop\cognia_v2\venv312\Scripts\python.exe)
- SO: Windows-11-10.0.26200-SP0
- CPU: AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD
- Cores: 6 fisicos / 12 logicos
- RAM: 33.4 GB
- GPU: NVIDIA GeForce RTX 5060 Ti, 16311 MiB

## Backend LLM
- GGUF activo (node.llama_backend): C:\Users\usuario\.cognia\models\qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf
- Modelos en C:\Users\usuario\.cognia\models: OpenReasoning-Nemotron-14B.Q4_K_M.gguf, Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf, Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf, Qwen3-1.7B-Q4_K_M.gguf, Qwen3-4B-Thinking-2507-Q4_K_M.gguf, UIGEN-X-8B.Q8_0.gguf, gpt-oss-20b-MXFP4.gguf, mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf, mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf, qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf, qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf, qwen2.5-coder-0.5b-instruct-q8_0.gguf, qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf, qwen2.5-coder-14b-instruct-q4_k_m-00002-of-00002.gguf
- Shards NPZ en C:\Users\usuario\.cognia\shards\qwen-coder-3b-q4: shard_0.npz, shard_1.npz, shard_2.npz, shard_3.npz
- Ollama: disponible en http://localhost:11434
- Backend en uso (llm_local): llama en http://127.0.0.1:8080

## Mapa del repo
- Modulos .py top-level: 8
- cognia/: 395 archivos .py
- node/: 19 archivos .py
- shattering/: 18 archivos .py
- coordinator/: 10 archivos .py
- storage/: 2 archivos .py
- security/: 4 archivos .py
- tests/: 449 archivos .py
- Archivos de test (tests/test_*.py): 446

## Radar de cobertura (anti-danos-colaterales)
- Modulos con simbolos publicos: 378
- SIN ninguna mencion en tests/: 31
- Fuera del radar (revisar al tocar features vecinas):
  * cognia/experts/identity_dataset.py (2 simbolos publicos)
  * cognia/experts/meta_maker.py (1 simbolos publicos)
  * cognia/goal_and_pattern_engine.py (9 simbolos publicos)
  * cognia/logger_config.py (5 simbolos publicos)
  * cognia/memory/adapter_store.py (1 simbolos publicos)
  * cognia/memory_response_engine.py (2 simbolos publicos)
  * cognia/migrations/runner.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/cognia_game/game.py (1 simbolos publicos)
  * cognia/program_creator/generated_programs/fractal_pattern_renderer/program.py (4 simbolos publicos)
  * cognia/program_creator/generated_programs/in_memory_task_manager_with_undo_stack_and_unit_te/program.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/juego_minecraft/program.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/minecraft_juego/program.py (5 simbolos publicos)
  * cognia/program_creator/generated_programs/priorityqueue_with_heapq_and_priority_change/program.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/royal_favors/program.py (1 simbolos publicos)
  * cognia/program_creator/generated_programs/task_manager_with_sqlite_in_memory_undo_stack_and/program.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/task_manager_with_sqlite_in_memory_undo_stack_and_01/program.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/text_compressor_01/program.py (2 simbolos publicos)
  * cognia/program_creator/generated_programs/untitled_procedural_story_generator_with_built_in/program.py (2 simbolos publicos)
  * cognia/research_engine/research_orchestrator.py (4 simbolos publicos)
  * cognia/tui/widgets/header.py (1 simbolos publicos)
  * cognia/tui/widgets/statusbar.py (1 simbolos publicos)
  * cognia/ux/messages.py (1 simbolos publicos)
  * node/client.py (1 simbolos publicos)
  * node/local_adapter.py (3 simbolos publicos)
  * node/relay_client.py (2 simbolos publicos)
  * shattering/distillation/data_generator.py (3 simbolos publicos)
  * shattering/distillation/losses.py (3 simbolos publicos)
  * shattering/distillation/trainer.py (2 simbolos publicos)
  * coordinator/contributor.py (4 simbolos publicos)
  * coordinator/relay.py (3 simbolos publicos)
  * security/secure_storage.py (2 simbolos publicos)

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

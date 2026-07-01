# Fine-tune de tool-use (formato ACCION de Cognia)

Enseña a Qwen a **usar las herramientas de Cognia** en el formato REAL del agent loop:
el modelo emite `ACCION: <tool> <args>` y consume `RESULTADO ...` (NO es function-calling
JSON; los datasets públicos en JSON no sirven).

## Método
Datos **verificados por ejecución** (no sintéticos a ciegas):
1. `tasks.py` — 34 tareas, cada una con un **verificador de postcondición** determinista.
2. `gen_trajectories.py` — corre el agent loop REAL contra las tools reales en un workspace
   aislado; **relabeling hindsight** (verifica tras cada paso, trunca en el 1er éxito,
   descarta pasos con ERROR, cierra con `responder`), sanitiza paths, dedup, escritura
   incremental. Solo conserva trayectorias cuya postcondición pasa.
3. `kaggle/train_tooluse_kaggle.py` — QLoRA sobre Qwen2.5-Coder-3B con el formato ChatML+
   SYSTEM del deploy y **completion-only masking** (el TOOLS_DOC no entra en la loss).
4. `kaggle/run_kaggle_tooluse.py` — orquestador (sube dataset+eval, pushea el kernel GPU).

## Resultado del de-risk (2026-07-01)
Pipeline validado end-to-end. Métrica **correct_tool** (herramienta elegida ∈ esperadas):
**base 16.7% → adapter 83.3% (+66.7%)** — el fine-tune enseña la SELECCIÓN de herramienta
(el base defaultea a `leer_archivo`; el adapter usa `calcular`/`escribir_archivo`). Nota:
la métrica `valid_single_accion` (solo formato) SATURA en 1.0 y oculta la mejora → usar
correct_tool.

⚠️ **La T4 no se adjuntó en el run de de-risk** (entrenó el 0.5B/CPU, no el 3B). Causa
probable: **falta verificación de teléfono en la cuenta de Kaggle** (o cuota de GPU agotada).

## Cómo correr el fine-tune del 3B (GPU)
1. **Activá GPU en Kaggle**: verificá tu teléfono en kaggle.com/settings (Phone verification).
   Sin esto, el kernel cae a CPU + 0.5B (ver el log: `[gpu] cuda_available=False`).
2. (Opcional) Regenerá/enriquecé el dataset:
   ```
   venv312\Scripts\python.exe -m cognia_v3.training.tooluse.gen_trajectories --split train --samples 5
   venv312\Scripts\python.exe -m cognia_v3.training.tooluse.make_eval_prompts
   ```
3. Entrená en Kaggle (sube dataset+eval, pushea kernel GPU, pollea, descarga adapter):
   ```
   venv312\Scripts\python.exe -m cognia_v3.training.kaggle.run_kaggle_tooluse
   ```
   Salida: `checkpoints/tooluse/final_adapter/` + `eval_tooluse.json` (con delta_correct_tool).

## Deploy local del adapter (pendiente)
Convertir `final_adapter/` (PEFT) a GGUF con `convert_lora_to_gguf.py` de llama.cpp y cargarlo
vía `LLAMA_LORA_PATH` (el `node/llama-server.exe` pineado en b9391 soporta `--lora`). Cuidar la
compatibilidad de versión del converter con b9391.

## Estado del dataset
`data/tooluse_train.jsonl` (gitignoreado, regenerable): ~99 pares únicos del 3B local.
Cobertura fuerte en responder/escribir/calcular/leer; débil en apendar/buscar/contar/json
(el 3B base falla esas multi-paso — un teacher 7B o few-shot las levantaría).

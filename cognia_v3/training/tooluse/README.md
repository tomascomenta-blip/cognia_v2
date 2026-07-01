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

## Fase B: trayectorias EXPERTAS (`gen_expert.py`)
El 3B base da **0% accept** en las multi-paso (append/count/json/py) — por más samples
que se tiren, no genera datos para ellas. Y las tools de memoria/KG estaban deshabilitadas.
`gen_expert.py` llena ambos huecos con **trayectorias expertas scripted**: la secuencia
CORRECTA de acciones (en `tasks.py:EXPERT_STEPS`) se **ejecuta contra las tools reales**
(mismo `run_tool` del deploy) y se conserva solo si la postcondición (`verify`) pasa. No
usa el 3B → **no cuesta la hora de CPU**.

- **Aislamiento:** workspace temporal por trayectoria; las tareas de KG (`NEEDS_AI_KG`)
  corren sobre un `KnowledgeGraph` en **DB temporal** (`init_db`) → NUNCA tocan la memoria
  del usuario. Fuga de ruta del venv scrubeada (`sys.executable` → `python`).
- **Formato idéntico** al del 3B (prompt/completion/cierre `responder`) → se mezclan sin
  mismatch train/inference.
- Regresión: `tests/test_tooluse_expert.py` (cada trayectoria pasa su verify + sin fuga).

```
# genera expertas + mezcla con las del 3B (dedup) -> train_v2
venv312\Scripts\python.exe -m cognia_v3.training.tooluse.gen_expert \
      --merge cognia_v3/training/tooluse/data/tooluse_train.jsonl \
      --out   cognia_v3/training/tooluse/data/tooluse_train_v2.jsonl
venv312\Scripts\python.exe -m cognia_v3.training.tooluse.make_eval_prompts   # eval 6->10 tareas
venv312\Scripts\python.exe -m cognia_v3.training.kaggle.run_kaggle_tooluse \
      --push-only --train-file cognia_v3/training/tooluse/data/tooluse_train_v2.jsonl
```

## Estado del dataset
`data/tooluse_train.jsonl` (gitignoreado, regenerable): ~99 pares del 3B local. Cobertura
fuerte en responder/escribir/calcular/leer; débil en apendar/buscar/contar/json.
`data/tooluse_train_v2.jsonl` (Fase B): **161 pares** = 99 del 3B + 64 expertos (multi-paso
+ memoria de trabajo + KG), dedup. Es el que se entrena en el run GPU del 3B.

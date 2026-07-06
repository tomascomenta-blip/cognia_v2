# HECHOS MEDIDOS — base empírica para la teoría COGNIA 3B

Recolección 2026-07-06 (agente explorador sobre el repo + memorias). Todo lo de acá es
**[MEDIDO]**: números reales de corridas, con fuente. Nada es proyección.

## El dato de oro: el 3B YA se entrenó con QLoRA en Kaggle T4 (3 veces)

### 1. XHUNDRED Fase 2 (p2k2) — la medición más rigurosa
- Base: **Qwen2.5-3B-Instruct** (no coder) vía Kaggle Models `qwen-lm/qwen2.5/transformers/3b-instruct/1`.
- QLoRA NF4+DQ compute fp16, **LoRA r=16 α=32 all-linear (q,k,v,o,gate,up,down) = 29.9M trainable**.
- seq 1024, micro-batch 4, grad-accum 4 (efectivo 16), lr 2e-4 cosine warmup 3%, AdamW **fp32**
  (no paged-8bit), **gradient checkpointing ON obligatorio** (`prepare_model_for_kbit_training(...,
  use_gradient_checkpointing=True)`) — mb4 SIN GC hizo OOM en 14.5 GB.
- **VELOCIDAD: ~424 tok/s** (327,680 tok en ~772 s; tokens de seq completa, dataset sin packing).
  0.5 época = 1.15M tokens en 45.2 min (corte duro por reloj). Loss 1.156→0.825.
- Resultado: MGSM-es 0-shot +14.8pp (54.4%), sin catástrofe (XSC −0.4, Belebele −2.6);
  caveat: 3-shot −15.2 (especializa el MODO 0-shot).
- Fuente: `cognia_x/construccion/xhundred/xh_p2k2_qlora.py` + `results_p2k2/eval_p2_compare.json`
  + `01_DESVIOS.md:104-106`.

### 2. Tool-use (Kaggle, 2026-07-01) — kernel CON masking
- Base: Qwen2.5-Coder-3B-Instruct vía `qwen-lm/qwen2.5-coder/transformers/3b-instruct/1`.
- `train_tooluse_kaggle.py`: r=8 qkvo, NF4, seq 1600, 3 epochs, **completion-only masking**
  (labels=-100 sobre prompt, `DataCollatorForSeq2Seq`), lr 2e-4.
- Run 1: 99 pares, ~8 min, eval 6 tareas 83.3→100%. Reentreno v4: 161 pares
  (= 99 del 3B + 64 expertas, tras dedup de 163 brutos; tiempo no loggeado),
  eval 10 tareas: **correct_tool 0.80 → 1.00**. OJO: N=10 y N=6 → señal direccional, no significancia.
- Fuente: `checkpoints/tooluse/eval_tooluse.json` + memoria cognia-tooluse-finetune.

### 3. Destilación (train_qlora_kaggle.py) — la config corrió en COLAB T4, no Kaggle
- r=8 qkvo, NF4, seq 1024, b2×ga8, lr 2e-4, **SIN masking** (DataCollatorForLanguageModeling).
- Ganador real (Colab, 2026-06-10): lr 5e-5 dropout 0.1 → genérico 70.8→83.3%, holdout
  conocimiento 18.5→88.0%. **lr 2e-4 derivó el modelo a chino** (modo de fallo real).
- Fuente: `checkpoints/cognia_3b_v2_winner/eval_compare.json` + memoria kaggle-training-pipeline.

## Hardware/entorno Kaggle confirmado
- **2× Tesla T4, 15.6 GB visibles c/u (14.56 GiB utilizables reportados)**, torch 2.10.0+cu128.
- Cuota ~30 h GPU/semana, sesiones estables 9-12 h. Cuenta anthuananthuan ACTIVA
  (kernels GPU corrieron 2026-07-01→03; verificación telefónica resuelta el 2026-07-01 —
  antes de eso TODO corría en CPU silenciosamente).
- **`machine_shape: "NvidiaTeslaT4"` OBLIGATORIO en kernel-metadata.json** — el backend nuevo
  ignora `enable_gpu` (fix 331db7c; causa raíz de datagens lentos en CPU).
- **bitsandbytes del image es viejo**: `pip install -U bitsandbytes` (>=0.46.1) ANTES de importar
  transformers (cachea la detección; fix 8b67ac3). Requiere `enable_internet: true`.
- **torchao 0.10 del image ROMPE peft** (`is_torchao_available()` lanza ImportError) →
  desinstalar torchao antes de importar peft (`train_tooluse_kaggle.py:91-105`).
- **PYTHONUTF8=1 + PYTHONIOENCODING=utf-8** en el env del CLI kaggle en Windows (cp1252 revienta).
- **4 de 10 lanzamientos GPU fallaron** (XHUNDRED) → diseñar con retry.
- Colab free INESTABLE (murió a 13-67 min) → Kaggle para todo lo largo; descarga incremental.

## Throughput de referencia en T4 (otros regímenes, para calibrar MFU)
- Tiny 9.5M (XSPEED, atención lineal): fp32 36.3k tok/s → **148.7k tok/s** con
  cheap16+SDPA+b512+compile+fused (4.10×). DataParallel 2×T4: 113.8k < 1 GPU (overhead-bound).
- 97.5M (XHUNDRED): b48+compile = **19,429 tok/s, MFU 19.7%, 13.05 GB**. MFU techo práctico
  T4 a esa escala ≈ 20-25%.
- torch.compile es TAMBIÉN palanca de memoria (b32 eager OOM 15.13 GB vs b48 compilado 13.05 GB).
- Gradient checkpointing en el tiny: 43.3k tok/s (vs 148.7k) — palanca de memoria, no velocidad.
- Trampas: CE chunked ingenuo NO ahorra (autograd retiene chunks); dynamo retiene VRAM tras OOM.

## Datos de entrenamiento existentes
- `cognia_v3/training/tooluse/data/tooluse_train_v2.jsonl`: 161 pares ACCION verificados por
  ejecución. `tooluse_eval.jsonl` held-out. Pipeline: `gen_trajectories.py` (agent loop real +
  hindsight relabeling + verificación postcondición), `gen_expert.py` (scripted contra tools
  reales), `tasks.py` (42 tareas con verificadores). accept_rate 0.507 con el 3B; multi-paso
  0% accept (techo = dataset, no GPU). Generación: 3,923 s en CPU local.
- `cognia_v3/training/cognia_dataset.jsonl`: 3,489 pares {prompt, completion} (destilación).
- `cognia_v3/training/synthetic/`: datagen con 7B — 20 generados / 8 aceptados en 4.1 h
  (corrió en CPU por el bug machine_shape).

## Gaps (nunca hecho)
1. QLoRA 3B ≥1 época completa en Kaggle (p2k2 llegó a 0.5 por corte de 45 min).
2. paged_adamw_8bit (siempre AdamW fp32).
3. Sequence packing / completion-masking+packing juntos.
4. Unsloth en el image de Kaggle.
5. DDP real 2×T4 para el 3B (lo medido en contra fue DataParallel sobre el tiny).
6. Batch >4 con las palancas de memoria combinadas (paged optim + CE eficiente).
7. Eval grande (los evals tool-use son N=6-10).
8. Cerrar la brecha NF4→Q4_K_M en deploy (dilución medida con --lora r=8 sin merge).

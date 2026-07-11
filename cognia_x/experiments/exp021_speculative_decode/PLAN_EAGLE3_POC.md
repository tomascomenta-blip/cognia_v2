# PoC EAGLE3 — plan de ejecución (2026-07-10, GPU autorizada)

Síntesis del workflow de research (wwrzerlmf). Veredicto: **VIABLE-CON-RIESGO,
camino EAGLE3** (MTP INVIABLE — exige módulo MTP nativo de pretraining que el
Qwen2.5-Coder-3B no tiene).

## Dos riesgos load-bearing, ambos validables BARATO antes de la GPU

1. **[Bloqueo de plumbing]** El prebuilt b9606 NO corre EAGLE3 sobre nuestro
   target: Qwen2.5-Coder-3B es `LLM_ARCH_QWEN2` (`qwen2.cpp`), que NO publica
   `t_layer_inp` (los 3 hidden states low/mid/high que EAGLE3 necesita) — solo
   lo hacen qwen3/qwen3moe/gemma4/openai-moe/llama. Fix: one-liner en
   `qwen2.cpp` + **recompilar b9606 desde fuente**. El converter
   (`convert_hf_to_gguf.py --target-model-dir`) también hay que traerlo del
   clone b9606 (el b9391 local no lo tiene).
2. **[Riesgo empírico decisivo]** CERO evidencia de EAGLE3 en CPU (todo el 2-3×
   es GPU). exp021 midió un draft separado en ESTA i3 = **0.37× (HUNDE)**.
   EAGLE3 abarata el draft pero el verify sigue siendo un forward batcheado del
   3B; solo paga si el decode es bandwidth-bound — en 2 cores puede volverse
   compute-bound y no acelerar.

## Orden de gates (cortar en el primero que falle)

- **GATE 0** ✓ b9606 no regresiona el decode base vs b9391 (+3.7%, medido).
- **GATE A — kill-gate CPU, SIN GPU**: medir EAGLE3 en el i3 con un par
  PÚBLICO conocido-bueno (cabeza EAGLE3 + target Qwen3 que el prebuilt b9606 YA
  soporta, sin compilar). Si da <1× con un par bueno → **línea EAGLE3 MUERE
  acá** (null honesto, coherente con exp021), sin tocar la GPU ni el parche.
- **GATE B — plumbing Qwen2, <30 min GPU**: compilar b9606 con el hook; entrenar
  cabeza THROWAWAY (10-50 steps, acceptance ~0 no importa); convertir; confirmar
  que llama-server la carga contra el 3B sin assert-fail y emite tokens. Testear
  prompt largo (bug abierto #24541: rc=-1 a >700 tokens).
- **GATE C — train de calidad, 15-24 GPU-h**: SpecForge online + corpus de
  código; gate accept-length >1 / acceptance ~70% en código held-out.
- **GATE D — medición i3 final**: convertir, medir tok/s vs b9391, verificar
  bit-identidad a temp 0. Gate **>1.5×**.

## Piso GRATIS en paralelo (cero training, ya en b9391)
`--spec-type ngram-mod` (self-speculative, ya default del backend): para
reescritura/repetición de código puede dar speedup sin cabeza ni GPU. Si ya da
el objetivo, el PoC EAGLE3 pasa a opcional.

## Kernel Kaggle (cuando GATE A y B pasen)
Molde: run_kaggle_training.py. Base Qwen2.5-Coder-3B bf16 congelado (~6GB, entra
en 1×T4). Datagen: regenerar completions con el 3B sobre ~2-5k prompts (slice de
synthetic_code_dataset.jsonl + ShareGPT). build_vocab_mapping.py → d2t 32k.
SpecForge train_eagle3_online (target congelado, batch=1, max_len 2048, lr 1e-4).
Trampas: machine_shape T4, torchao uninstall, bitsandbytes -U, GC ON, PYTHONUTF8,
retry/resume (4/10 fallan). ~15-24 GPU-h (2 sesiones) para calidad; <30 min para
la throwaway de GATE B.

## Null honesto explícito
Si GATE A da <1× con un par conocido-bueno → INVIABLE-en-CPU; el entregable es
esa medición (coherente con exp021 0.37×). NO se lanza la GPU de calidad. El
lever de velocidad queda en: cascada 0.5B (portero) + ngram-mod + el 7B para
capacidad.

## RESULTADO GATE A (2026-07-10): EAGLE3 NO PAGA EN CPU — línea MUERTA sin GPU

Par público conocido-bueno: Qwen3-1.7B (f16 GGUF) + AngelSlim/Qwen3-1.7B_eagle3
(cabeza convertida a GGUF con convert_hf_to_gguf.py --target-model-dir del
b9606). Medido en el i3 2-cores con b9606 --spec-type draft-eagle3 (results_
gate_a_eagle3.json):

  baseline 4.42 tok/s → EAGLE3 **2.05 tok/s = 0.464×** (HUNDE). bit-idéntico=True.

**El mecanismo FUNCIONA** (la conversión EAGLE3→GGUF cierra, la cabeza acepta
drafts, el output es bit-idéntico = lossless) — pero en 2 cores el verify
batcheado del target es COMPUTE-BOUND (no hay paralelismo para amortizar los K
tokens), así que speculative decoding HUNDE la velocidad. Consistente con
exp021 (draft separado 0.37×). **Corrige la proyección de exp021**: "MTP/EAGLE
= único speculative que respeta la banda, 2-3×" era GPU; en el i3 2-cores NO se
cumple (compute-bound, no bandwidth-bound).

VEREDICTO: **NO se entrena la cabeza EAGLE3 en Kaggle** (el kill-gate ahorró
15-24 GPU-h). La línea velocidad-por-speculative queda CERRADA en el i3. El
lever de velocidad real: (1) tamaño del modelo (portero 0.5B para turnos
triviales, ya desplegado, 3.3-3.9×); (2) ngram-mod (lossless, código
repetitivo, ya default en b9391). Speculative con cabeza entrenada NO agrega
sobre eso en 2 cores.

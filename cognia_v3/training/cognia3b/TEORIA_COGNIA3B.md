# TEORÍA COGNIA 3B — Entrenar un modelo de ~3B de parámetros en una Tesla T4 (Kaggle) manteniendo calidad

**Estado:** CONGELADO v1 — 2026-07-06
**Método:** matemática primero, honestidad sobre lo infactible, predicciones falsables, gates
pre-registrados antes de correr. Este documento integra 7 secciones de autor + 3 verificaciones
adversariales independientes (40 findings — resueltos uno a uno en el Anexo A) + el re-anclado
a los hechos medidos del repo (`HECHOS_MEDIDOS.md`, recolección 2026-07-06). Las decisiones
editoriales que resuelven los conflictos entre partes están integradas en el texto: ninguna
parte redefine lo que otra congela. Cambios posteriores a este congelado = versión nueva del
documento, con diff explícito (los resultados de E0..En se registran en `MANAGER_LOG.md` y
pueden ACTUALIZAR predicciones, nunca reescribir silenciosamente lo congelado).

---

## DECISIONES CONGELADAS (tabla ejecutiva)

| # | Decisión | Valor congelado | Justificación breve |
|---|---|---|---|
| DC-1 | **Base primaria de `cognia-3b` v1** | **Qwen2.5-Coder-3B-Instruct** | Continuidad total del repo: ACCION 0.24→0.86 con scaffold [MEDIDO memoria cognia-rsi-autoprompting], CLI GGUF ya en uso, mount de Kaggle Models probado, hermano Qwen2.5-3B con **424 tok/s medidos** en QLoRA T4. **Caveat vinculante: Qwen Research License → v1 = artefacto de investigación / uso personal, NO distribuible comercialmente** (Parte 6). |
| DC-2 | **Candidata limpia (v2 distribuible)** | **SmolLM3-3B** (Apache-2.0, 3.08B, español nativo declarado, GGUF oficial) | Se arbitra en el gate de migración E6; si pasa, el `cognia-3b` distribuible (v2) deriva de ella re-corriendo el pipeline. |
| DC-3 | Opción futura (fuera de este goal) | Qwen3-4B-Instruct-2507 como **`cognia-4b`** | Apache-2.0, pero 4.0B ≠ 3B (el goal exige ~3B y el nombre `cognia-3b`) y sus benchmarks tienen una **disputa de verificación NO resuelta** (Parte 6 §6.5). |
| DC-4 | **Topología de entrenamiento default** | **Secuencial-con-merge** (Parte 3 P-4): cada etapa entrena un adapter sobre la ÚLTIMA base mergeada, gates G1-G5 entre etapas; rollback = la base mergeada anterior queda intacta | Única topología con mecanismo de rollback definido. La mezcla única (estilo Tülu 3) queda como HIPÓTESIS del brazo **E-MIX** (A/B pre-registrado inmediatamente después de E1, Parte 7 §7.3). |
| DC-5 | Runtime baseline | transformers + PEFT + bitsandbytes NF4 (el path que ya corrió 3 veces) | Unsloth se arbitra en E0 (A/B); entra solo si da ≥1.3× con loss equivalente (±1%). |
| DC-6 | **Gates canónicos** | **G1-G5 de la Parte 3** — única definición en todo el documento; la Parte 7 los REFERENCIA, no los redefine. El baseline de 10 preguntas del kernel es **smoke, JAMÁS gate**. | Es la única tabla de gates con análisis de potencia (McNemar exacto, §3.4). |
| DC-7 | **Ancla de throughput** | **424 tok/s [MEDIDO p2k2]** como PISO de todos los presupuestos; objetivo E0: **≥800 tok/s útiles** [PREDICCIÓN → E0] | Ver §0.4. Si E0 logra ≥800, se restauran los corpora grandes (árbol pre-registrado en Parte 7 §7.1); si no, rigen los corpora recortados de este documento. |
| DC-8 | **Presupuesto core re-derivado** | ~16.8M tok/sesión de 11 h; ~33.6M tok/semana (2 sesiones de training) [CALCULADO desde 424]; core E0-E5 + E-MIX = **45 GPU-h nominales ≈ 2 semanas de cuota** (68-90 GPU-h con margen ×1.5-2 ≈ 3-4 semanas) | Tabla 7.8 re-derivada. |
| DC-9 | **Merge final** | Cargar la base en NF4 con la **MISMA `BitsAndBytesConfig` del training** → dequantizar a fp16 → merge sobre ESA dequantización → GGUF Q4_K_M → gate G4 en el CLI real | Parte 2 §2.8 y Parte 7 E5. Si E1 consagra fp16-LoRA como backbone, el merge es limpio por construcción. |
| DC-10 | **Pre-requisitos P0** (antes de congelar gates / lanzar E0) | (i) **HECHO**: `cognia_v3/eval/mcnemar_power.py` + `cognia_v3/eval/mcnemar_power_results.json` commiteados (seed 20260706, 20k reps, α=0.05; test en `tests/test_mcnemar_power.py`); (ii) construir y **congelar por hash** las suites held-out de N=100 (G1 general, G2 por etapa, G5 español) y la ampliación de razonamiento a ≥50-100 ítems; (iii) grep de descontaminación de todo JSONL de train contra las suites | Parte 3 §3.4, Parte 7 §7.0. |
| DC-11 | Diseño base-agnóstico | Todo el pipeline (datos, kernel, gates, merge, GGUF) parametrizado por base (`MODEL`, chat template, target_modules), para que re-correrlo sobre otra base (SmolLM3, Qwen3-4B) sea barato | Parte 6 §6.7. |

---

## Parte 0 — El problema, con números (qué es imposible, qué es viable)

### 0.0 Protocolo de etiquetado de claims (vinculante en todo el documento)

- **[MEDIDO archivo/memoria]** — número real de una corrida del repo, con fuente verificable
  (archivo:línea, JSON de resultados, o memoria de sesión).
- **[LITERATURA fuente año]** — afirmación externa verificada contra la fuente citada.
- **[CALCULADO]** — aritmética reproducible con los números del propio documento (fórmula
  explícita en el texto): **ni medición ni literatura**. Un [CALCULADO] se promueve a [MEDIDO]
  solo cuando el script que lo genera y su output quedan commiteados (caso concreto: la
  simulación de potencia de §3.4 → `cognia_v3/eval/mcnemar_power.py`, pre-requisito P0).
- **[PREDICCIÓN → E-x]** — proyección falsable, SIEMPRE con el experimento que la falsea.
- Prohibición transversal: ningún claim de "mantiene calidad" sin el gate que lo mida.

### 0.1 El hardware real

Tesla T4 (Kaggle): 16 GB GDDR6 nominales — **15.6 GB visibles/utilizables [MEDIDO: probe
2026-07-01, memoria cognia-tooluse-finetune: "2× Tesla T4 (15.6 GB c/u)"; 14.56 GiB
utilizables reportados]** — ancho de banda 320 GB/s, 65 TFLOPS fp16 (tensor cores),
8.1 TFLOPS fp32, arquitectura Turing **sm_75**. Todos los presupuestos de memoria de este
documento se calculan contra **15.6 GB**, no 16.

Consecuencias duras de sm_75:

- **Sin bf16 nativo** → fp16 + GradScaler obligatorio (con LoRA en fp32 para evitar
  "Attempting to unscale FP16 gradients" — lección ya codificada en
  `cognia_v3/training/kaggle/train_qlora_kaggle.py:223-228`).
- **Sin FlashAttention-2** (requiere sm_80+) → SDPA con backend memory-efficient (Parte 1f).
- Cuota Kaggle: **30 h GPU/semana**, sesiones de máx **12 h** (estables 9-12 h [MEDIDO]),
  opción 2×T4 (misma tasa de cuota) o P100.

### 0.2 Pretraining desde cero: DESCARTADO por 2-3 órdenes de magnitud

Costo de entrenamiento ≈ 6·N·D FLOPs (N params, D tokens) [LITERATURA Kaplan/Hoffmann].

| Escenario | D (tokens) | FLOPs | GPU-h a 30% MFU (19.5 TFLOPS ef.) | Semanas de cuota Kaggle |
|---|---|---|---|---|
| 3B Chinchilla-óptimo (D=20N) | 60 B | 1.08e21 | ~15,400 h | ~510 sem ≈ **10 años** |
| 3B "moderno" (Qwen2.5 usó 18T) | 18 T | 3.2e23 | ~4.6M h | **milenios** |
| 3B severamente sub-entrenado | 6 B | 1.08e20 | ~1,540 h | ~51 sem ≈ 1 año |

Incluso con la palanca 4.1× medida en XSPEED (memoria cognia-x-velocidad-entreno, sobre un
tiny de 97.5M) el Chinchilla-óptimo queda en ~2.5 años de cuota. Y el resultado a 60B tokens
sería MUY inferior a cualquier 3B abierto actual (entrenados con 9-18T tokens). El precedente
interno XHUNDRED lo confirma empíricamente: 97.5M params, 25.7 min de T4, **NO funcional** en
generación libre (gates 2/4) [MEDIDO memoria cognia-xhundred-resultado].

Lo mismo aplica a "crecer" un modelo hasta 3B (progressive stacking / depth up-scaling estilo
SOLAR): el continued-pretraining posterior al up-scale necesita decenas de miles de millones
de tokens → mismo muro.

**Conclusión honesta:** en una T4 de Kaggle NADIE puede pre-entrenar un 3B de buena calidad
desde cero. No es un problema de ingenio: son 2-3 órdenes de magnitud de cómputo.

### 0.3 Full fine-tuning clásico: no entra en 15.6 GB

Memoria para entrenar 3B con AdamW mixed-precision estándar: pesos fp16 (6 GB) + master fp32
(12 GB) + gradientes fp16 (6 GB) + estados Adam fp32 (24 GB) ≈ **48 GB** ≫ 15.6 GB. Con Adam
8-bit: ~30 GB. Sigue sin entrar. Vías que SÍ podrían entrar (como experimentos de límite, no
como base del plan): GaLore-8bit (proyección de gradientes a bajo rango; análisis con dos
escenarios en Parte 2 §2.5) y LOMO (SGD fusionado sin estados; descartado en §2.5).

### 0.4 La ventana viable: ADAPTACIÓN de una base 3B + merge = COGNIA 3B

Redefinición operativa (transparente): "entrenar un 3B en T4" viable =
**post-training profundo de una base 3B abierta pre-entrenada** — el forward/backward pasa
por los ~3.1e9 parámetros (congelados en NF4 4-bit), se entrena una parametrización eficiente
(LoRA/DoRA/GaLore...), en múltiples etapas (identidad, habilidades, razonamiento), y el
**merge final produce un checkpoint nuevo de ~3B de parámetros: `cognia-3b`**, exportable a
GGUF y corriendo en el CLI local de Cognia (llama.cpp).

La matemática de POR QUÉ esto sí es viable y mantiene calidad:

- **Memoria QLoRA 3B (Qwen2.5-Coder-3B: hidden 2048, 36 capas, GQA 16/2, inter 11008,
  vocab 151936, embeddings atadas):** pesos NF4+DQ = **2.06 GB decimal (1.91 GiB)**
  [CALCULADO, Parte 1a — 1.43 GB lineales + 0.62 GB embedding fp16; consistente con el
  comentario "~2GB de pesos" del kernel, que es diseño, no medición]; adapter r=16 all-linear
  ≈ 29.9M params → 0.48 GB con AdamW fp32 (0.30 GB con paged 8-bit); activaciones con
  gradient checkpointing ~0.3-0.7 GB; **pico de logits/CE ~2-3 GB** (el consumidor
  dominante, Parte 1c); contexto CUDA + fragmentación ~0.6-0.9 GB.
  **Total pico ~6.5-7 GB de 15.6 GB** → margen real para batch/seq/rank mayores.
  Evidencia empírica del margen: p2k2 corrió con micro-batch 4 + GC sin OOM, y micro-batch 4
  SIN GC hizo OOM en 14.5 GB [MEDIDO xh_p2k2_qlora.py] → **gradient checkpointing es
  obligatorio** en esta clase de configs.

- **Throughput QLoRA — el ancla MEDIDA (la corrección más importante de este congelado):**
  el repo YA midió el entrenamiento QLoRA del 3B en la T4 de Kaggle: **~424 tok/s**
  [MEDIDO: XHUNDRED Fase 2 "p2k2" — Qwen2.5-3B-Instruct, NF4+DQ compute fp16, LoRA r=16 α=32
  all-linear (29.9M trainable), seq 1024, micro-batch 4 + grad-accum 4 (efectivo 16), AdamW
  fp32, gradient checkpointing ON, SIN packing; 327,680 tok en ~772 s; 0.5 época = 1.15M
  tokens en 45.2 min; `cognia_x/construccion/xhundred/xh_p2k2_qlora.py` +
  `results_p2k2/eval_p2_compare.json` + `01_DESVIOS.md:104-106`]. Ese número — no el rango
  optimista de 800-1600 tok/s que este documento usaba en borrador y que NUNCA se midió — es
  el **PISO del presupuesto**. Matiz honesto: los 424 cuentan tokens de secuencia completa
  (padding incluido, dataset sin packing); E0 debe reportar **tok/s útiles** (no-padding).
  Palancas nunca probadas (upside a medir, no a asumir): sequence packing,
  `paged_adamw_8bit`, cross-entropy eficiente (Liger/Unsloth), micro-batch mayor, Unsloth,
  DDP 2×T4. **Objetivo E0: ≥800 tok/s útiles** [PREDICCIÓN → E0]. Cota de plausibilidad:
  424 tok/s ≈ 12% MFU sobre los 65 TFLOPS de la T4 (a 6N FLOPs/token con recompute de GC);
  800 ≈ 23% MFU (comparable al 19.7% medido en XHUNDRED a 97.5M — plausible); 1600 ≈ 46% MFU
  con dequant NF4 encima — improbable [CALCULADO].

- **Presupuesto que habilita el plan [CALCULADO desde 424 tok/s]:** una sesión de 11 h ≈
  **16.8M tokens**; 2 sesiones de training/semana ≈ **33.6M tokens/semana** (45.8M sería el
  máximo teórico usando las 30 h completas en training, sin eval ni margen — no planificar
  contra ese techo). Un SFT de alta calidad (10-60M tokens, 1-3 epochs) = **1-2 semanas de
  cuota** al ancla conservadora. Continued-pretraining ligero (1B tokens ≈ 655 h ≈ 22
  semanas) queda **FUERA del alcance razonable** de este programa. Regla pre-registrada: si
  E0 confirma ≥800 tok/s útiles, los presupuestos escalan ~2× y se restauran los corpora
  grandes (Parte 4 §4.3, Parte 7 §7.1).

- **Mantener calidad** (el requisito del goal): el riesgo dominante NO es capacidad de
  cómputo sino **olvido catastrófico / degradación de la base / fijación de modo**. La
  teoría de las Partes 2-3 lo ataca con: LoRA como regularizador de deriva (actualización de
  rango bajo), replay de datos generales, entrenamiento solo-en-completions (masking del
  prompt — que `train_tooluse_kaggle.py` ya hace y `train_qlora_kaggle.py` no), 1-2 epochs,
  lr moderado, y **gates de no-regresión pre-registrados** (G1-G5, Parte 3) medidos contra
  la base ANTES de aceptar cualquier adapter (McNemar pareado, held-out congelado por hash).
  Evidencia de que el riesgo es real y manejable: p2k2 ganó su nicho sin catástrofe
  generalista (MGSM-es +14.8pp, XStoryCloze −0.4, Belebele −2.6) pero FIJÓ el modo
  (3-shot −15.2pp) [MEDIDO] — exactamente la clase de fallo que G1 con ítems 3-shot caza.

### 0.5 Definición del producto final

**COGNIA 3B v1** = checkpoint de ~3.1e9 parámetros resultante de: base
Qwen2.5-Coder-3B-Instruct (DC-1; caveat de licencia en Parte 6) + programa multi-etapa de
adaptación entrenado ÍNTEGRAMENTE en Kaggle T4 + merge de adapters a fp16 (patrón DC-9) +
conversión GGUF Q4_K_M + verificación end-to-end REAL en el CLI de Cognia (`python -m cognia`)
con los gates G1-G5 pasados. Identidad: el modelo sabe que es Cognia, habla español nativo,
usa el formato ACCION de tools del repo. **Estatus legal v1: artefacto de investigación/uso
personal (Qwen Research License), NO distribuible comercialmente.**

**COGNIA 3B v2 (condicional)** = mismo pipeline re-corrido sobre SmolLM3-3B (Apache-2.0) si
el gate de migración E6 pasa → ese SÍ es el artefacto distribuible/comercializable.

---

## Parte 1 — Memoria y precisión en la T4 (sm_75)

Objetivo: mostrar dónde se va cada GB de la adaptación QLoRA/DoRA de un 3B en 15.6 GB (§0.1) y qué trampas numéricas tiene Turing. Base: Qwen2.5-Coder-3B-Instruct (hidden 2048, 36 capas, GQA 16 heads/2 kv-heads, head_dim 128, intermediate 11008, vocab 151936, embeddings atadas: 3.09B params totales, 2.77B no-embedding) [LITERATURA: config.json oficial Qwen2.5-3B, 2024].

### (a) La base en NF4 + double-quant: 2.06 GB (ya congelado en §0.4)

bitsandbytes cuantiza solo `nn.Linear`; embeddings/norms/biases quedan en fp16. Por capa: q_proj 2048×2048, k/v_proj 2048×256 (GQA), o_proj 2048×2048, gate/up 2048×11008, down 11008×2048 → 77.06M params/capa × 36 = 2.774B params lineales. Bytes/param NF4+DQ ≈ 0.516 (4 bits + absmax int8/bloque-64 + fp32 secundaria/256-bloques) [LITERATURA: Dettmers et al., QLoRA 2023]. Lineales: 2.774e9 × 0.516 B ≈ 1.43 GB. Embedding fp16 atada (lm_head no se cuantiza, comparte tensor): 151936×2048×2 B ≈ 0.62 GB. **Total ≈ 2.06 GB decimal (1.91 GiB)** — el mismo número de DC-1/§0.4, no se recalcula distinto en ninguna parte del documento. El comentario "~2GB de pesos" del pipeline real [`train_qlora_kaggle.py:99-102`] es diseño previo a la corrida, no una medición de VRAM — se cita como **consistencia**, no como evidencia [CALCULADO, no MEDIDO].

### (b) Adapter: params LoRA explícitos

Fórmula por módulo `r·(d_in+d_out)`: qkvo = 12800r/capa → ×36 = 460,800r; gate/up/down = 39168r/capa → ×36 = 1,410,048r; **all-linear = 51968r/capa → 1,870,848r**.

| r | qkvo | all-linear |
|---|---|---|
| 8 | 3.69M | 14.97M |
| 16 | 7.37M | 29.93M |
| 32 | 14.75M | 59.87M |
| 64 | 29.49M | 119.73M |

r=8 qkvo = 3.69M (0.12% del modelo) **[MEDIDO: config real en `train_qlora_kaggle.py:219-221`, r=8/α=16/qkvo] + [CALCULADO]**: la cifra de params es aritmética r·(d_in+d_out) sobre esa config, no el output real de `print_trainable_parameters()` (nunca citado en los logs) — pendiente citarlo literal en E0. Memoria del adapter con AdamW fp32 completo (4 param + 4 grad + 8 estados = 16 B/param): r=8 qkvo = 59 MB; r=64 all-linear = 1.92 GB. Hasta r=32 all-linear (0.96 GB) el adapter es barato; solo r=64 empieza a pesar [LITERATURA: QLoRA aplica LoRA a todas las lineales para acercarse a full-FT; qkvo-solo es la config conservadora del repo].

### (c) Activaciones: gradient checkpointing es obligatorio

Sin checkpointing, cada capa guarda para backward ≈ `b·s·(6h+3i+2·d_kv)` elementos fp16 (el término `2·d_kv` son las proyecciones k/v de GQA, d_kv=kv_heads·head_dim=256): 6·2048+3·11008+2·256 = 45,824 ≈ 45.8k elems/token/capa ≈ 91.6 kB/token/capa → ×36 capas = **3.3 MB/token**. Con b=2, s=1024 (2048 tokens/micro-batch): **~6.8 GB** — se come la T4. Con GC solo persisten los bordes de capa (`b·s·h` = 4 kB/token/capa → 147 kB/token = 0.30 GB) más el working-set de recómputo de 1 capa (~0.2 GB) [PREDICCIÓN: cuenta analítica, pico real depende del allocator → verificar en E0].

Trampa oculta: la **cabeza de vocabulario**, logits `b·s·V`. Con 2048 tokens/micro-batch × 151936: fp16 = 0.62 GB, y transformers upcastea a fp32 para la cross-entropy → +1.24 GB, con transientes de backward similares. **El pico de la cabeza (~2-3 GB) rivaliza con todas las activaciones juntas** y escala linealmente con tokens/micro-batch. Mitigación: CE fusionada por chunks (Liger-Kernel/Unsloth, Triton; Triton corre en sm_75 — Unsloth es evidencia indirecta) [PREDICCIÓN: Liger en sm_75 específicamente hay que probarlo en E0].

### (d) Optimizer: AdamW vs paged AdamW 8-bit

Sobre LoRA los estados son chicos: AdamW fp32 = 8 B/param de estados → r=16 all-linear = 239 MB; r=64 all-linear = 958 MB. `paged_adamw_8bit` baja estados a ~2 B/param (r=64: 239 MB) y pagina a RAM ante picos, eliminando OOMs esporádicos [LITERATURA: Dettmers QLoRA 2023]. Veredicto: irrelevante en tamaño hasta r=32; se adopta igual como seguro anti-OOM gratis (`optim="paged_adamw_8bit"`). El ~48 GB de full-FT (§0.3) es otro régimen: acá el optimizer nunca es el cuello.

### (e) Trampas fp16 en sm_75

1. Sin bf16 nativo → `fp16=True` + GradScaler [MEDIDO: `train_qlora_kaggle.py:239`]. 2. LoRA en fp32 obligatorio: GradScaler rechaza trainables en half ("Attempting to unscale FP16 gradients") [MEDIDO: `:224-228`, y lo hace `prepare_model_for_kbit_training`]. 3. Overflow fp16 (rango máx 65504): Qwen2RMSNorm ya computa varianza en fp32 y transformers upcastea logits en la loss — no tocar eso; NaNs de atención lineal sin normalizar costaron un fix real en otro modelo [MEDIDO: memoria cognia-x-velocidad-entreno, misma clase de trampa]. 4. bitsandbytes viejo en la imagen Kaggle: `pip install -U bitsandbytes` (≥0.46.1) ANTES de importar transformers, cachea la detección [MEDIDO: fix 8b67ac3, `:53-78`]. 5. Skew de loss scale: si el scaler saltea steps por inf/NaN el lr efectivo cae en silencio — loggear `scaler.get_scale()` y steps salteados en E0.

### (f) Atención en T4: SDPA memory-efficient, FA2 NO

FlashAttention-2 oficial no soporta sm_75 (requiere Ampere sm_80+) [LITERATURA: Dao-AILab/flash-attention #887]. SDPA de PyTorch en T4: el backend `flash` también exige sm_80 → despacha a **memory-efficient (xformers/CUTLASS)**, que sí soporta Turing en fp16 [LITERATURA: docs xformers/PyTorch]. Fallback `math` materializa `b·heads·s·s`: con b=2, heads=16, s=2048 → 2·16·2048²×2 B ≈ **0.27 GB/capa transitorio** (un solo buffer; ~0.5 GB si autograd retiene el buffer pre-softmax Y post-softmax a la vez — supuesto de doble buffer, no medido) — evitar ese fallback en cualquier caso. Existe un port no oficial `flash-attention-turing` [LITERATURA: github ssiu] — no apostar el pipeline a eso. Config: `attn_implementation="sdpa"`, verificar en E0 con `torch.backends.cuda.sdp_kernel` que el backend elegido sea mem-efficient.

### (g) Unsloth en T4: sí funciona, ganancia a medir

Unsloth soporta T4/sm_75 oficialmente (path fp16, notebooks Kaggle T4 y 2×T4 del propio autor incl. Qwen2.5), core Apache-2.0 vía pip [LITERATURA: unsloth.ai/blog/mistral-benchmark, PyPI, notebooks Kaggle danielhanchen]. Claims del vendor: ~2× velocidad, hasta 70-80% menos VRAM, "5.3× en Kaggle 2×T4" para Mistral-7B [LITERATURA: blogs Unsloth 2024-2025] — comparados contra HF sin packing y con configs subóptimas. Contra nuestro baseline ya optimizado (SDPA+GC+packing) la ganancia realista estimada es **1.3-1.8×** [PREDICCIÓN → E0, A/B mismo dataset/seq]. Riesgo: Unsloth parchea transformers agresivamente; fijar versiones en el kernel.

### (h) Sequence packing sin contaminación

Con `seq=1024` y padding, la utilización real puede ser 30-50% → packing rinde 2-3× tokens útiles/s [PREDICCIÓN: medir utilización real del JSONL en E0; el pipeline actual NO packea, usa `DataCollatorForLanguageModeling`, `:243`]. La vía estándar HF (`DataCollatorWithFlattening`) requiere FA2 varlen → no disponible en sm_75 [LITERATURA: docs transformers]. Alternativa para T4: concatenar documentos hasta `seq` + **máscara 4D block-diagonal** + reset de position_ids por documento (costo `b·1·s·s` fp16 = 8.4 MB/secuencia de 2048 — aceptable). Riesgo a falsar: que SDPA con máscara arbitraria caiga a `math` [PREDICCIÓN → E0-b]. Nunca packear sin máscara.

### (i) Tabla de configs candidatas

Piso de throughput: **424 tok/s [MEDIDO p2k2, DC-7]** (tokens de secuencia completa, sin packing, régimen mb4/seq1024/GC/AdamW-fp32-sin-paged); objetivo E0: **≥800 tok/s útiles** (no-padding) [PREDICCIÓN → E0]. Memoria = 2.06 GB pesos + 0.8 GB CUDA/frag (fijos, (a)) + adapter (paged8bit, 4 param fp32 + 4 grad fp32 + 2 estados 8-bit = 10 B/param) + activaciones 0.3-0.7 GB + logits/CE ~2-3 GB a 4096 tok/micro-batch ((c)); suma de orden de magnitud, no recomputación fina por config — el número real lo da `torch.cuda.max_memory_allocated()` en E0.

| # | Config | Adapter (paged8bit) | Pico est. (orden de magnitud) | tok/s útil est. | Nota |
|---|---|---|---|---|---|
| C0 | r=8 qkvo, seq1024, b2×ga8, GC, sin packing, AdamW fp32 (repo actual) | 0.06 GB (AdamW fp32 completo, no paged) | ~4.5-5 GB | 424 tok/s **seq** [MEDIDO p2k2, régimen equiv.]; útil ~130-210 (util. 30-50% sin packing) [CALCULADO] | baseline ya corrido, Colab T4, sin loggear tok/s |
| C1 | **r=16 all-linear, seq1024, b4×ga4, GC, packing 4D-mask, paged8bit** | 0.30 GB | ~6.2-7 GB (consistente con §0.4) | objetivo **≥800** [PREDICCIÓN → E0] | **candidata E0** |
| C2 | r=32 all-linear, seq2048, b2×ga8, GC, packing, paged8bit | 0.60 GB | ~6.5-7.3 GB | ~700-1000 [PREDICCIÓN → E0] | para datos largos |
| C3 | r=64 all-linear, seq2048, b2×ga8, GC, packing, paged8bit | 1.20 GB | ~7.1-7.9 GB | ~650-950 [PREDICCIÓN → E0] | máxima capacidad |
| C4 | C1 + Unsloth | ~0.3-0.4 GB (claim) | ~5-7 GB (claim) | ~1050-1800 (C1 × 1.3-1.8×, §g) | A/B vs C1 en E0 |

**C1 es la candidata E0**: all-linear r=16 da la capacidad que el paper QLoRA muestra necesaria para acercarse a full-FT, adapter trivial en memoria, packing recupera el throughput perdido en padding. Esta tabla es la **síntesis teórica** previa a correr; la grilla real ya committeada y **lanzada** (`e0_perfil_kernel.py`, 10 configs `A..J` barriendo seq/mb/optim/packing/masking/r, más ablaciones `K-M` sin GC) mide estos números en instancia real — C0-C4 no son configs adicionales, son la lectura teórica de esa misma grilla. Recordatorios duros para el kernel: `PYTHONUTF8=1`, `pip install -U bitsandbytes` primero, lr **5e-5** (2e-4 derivó a chino, HECHOS #3), y loggear `max_memory_allocated`, backend SDPA efectivo, escala del GradScaler y tok/s reales (seq y útil por separado) — esos cuatro números convierten esta Parte en medición.

#### Claims etiquetados (Parte 1)
- [CALCULADO] Base NF4+DQ ≈ 2.06 GB (1.91 GiB): 2.774B lineales × 0.516 B/param ≈ 1.43 GB + embedding fp16 atada ≈ 0.62 GB — mismo número de §0.4/DC-1; el "~2GB de pesos" del kernel es consistencia de diseño, no medición de VRAM.
- [MEDIDO: config `:219-221`] + [CALCULADO] r=8 qkvo = 3.69M params entrenables (460,800·r); all-linear = 1,870,848·r → r=64 all-linear = 1.92 GB con AdamW fp32 (16 B/param) — la config es medida, la cuenta de params es aritmética sobre ella; falta citar `print_trainable_parameters()` real.
- [MEDIDO] LoRA en fp32 obligatorio en sm_75 (GradScaler rechaza half) — `:224-228`, error real del run.
- [LITERATURA] FA2 no soporta sm_75; SDPA cae a memory-efficient en Turing. Unsloth soporta T4 oficialmente, core Apache-2.0, claims de vendor 2-5.3×.
- [PREDICCIÓN → E0] Ganancia real de Unsloth vs baseline optimizado: 1.3-1.8×, no el rango del vendor.
- [PREDICCIÓN] Activaciones sin GC ~6.8 GB (fórmula `b·s·(6h+3i+2·d_kv)` = 45.8k elems/token/capa, incluye k/v de GQA); con GC ~0.5 GB; logits/CE ~2-3 GB a 4096 tok/micro-batch — pico real de allocator nunca medido en T4 → E0.
- [MEDIDO] Fallback SDPA `math`: b2·16·2048²×2 B ≈ 0.27 GB/capa (un buffer), ~0.5 GB si coexisten buffers pre- y post-softmax — evitar ese backend en cualquier caso.
- [LITERATURA] `paged_adamw_8bit` irrelevante en tamaño hasta r=32 (estados <250 MB con 2 B/param); se adopta como seguro anti-OOM gratis.
- [PREDICCIÓN] Packing rinde 2-3× tokens útiles/s (utilización actual 30-50%); requiere máscara 4D block-diagonal (no `DataCollatorWithFlattening`, que exige FA2 varlen).
- [MEDIDO] `pip install -U bitsandbytes` ANTES de importar transformers (fix 8b67ac3); lr 2e-4 sobreajusta/deriva a chino, ganador real lr 5e-5 (memoria kaggle-training-pipeline).
- [PREDICCIÓN → E0] Config candidata C1 (r=16 all-linear, seq1024, b4×ga4, GC, packing 4D-mask, paged8bit): adapter 0.30 GB, pico ~6.2-7 GB, objetivo ≥800 tok/s útiles sobre el piso de 424 [DC-7]. La grilla real (10 configs A..J) ya corre en `e0_perfil_kernel.py`.

### Preguntas abiertas
- Pico real de VRAM por config (fragmentación del allocator, transientes de la cabeza de vocab) — medir `torch.cuda.max_memory_allocated()` en E0.
- ¿SDPA con máscara 4D block-diagonal despacha a memory-efficient o cae a `math` en la imagen de Kaggle? (E0-b, `torch.backends.cuda.sdp_kernel`).
- ¿Liger-Kernel (CE fusionada Triton) corre en sm_75 específicamente? Recortaría ~2 GB del pico.
- Ganancia real de Unsloth vs baseline optimizado (no vs HF pelado); riesgo de monkey-patch de transformers → fijar versiones.
- Utilización real (tokens útiles/tokens padded) de `cognia_dataset.jsonl` — determina si el packing rinde 2× o 3×.
- ¿DoRA y GaLore tienen paths estables en fp16/sm_75 sobre base NF4? (overhead y costo de SVD periódica — desarrollado en Parte 2 §2.3/2.5, no recomputado acá).

---

## Parte 2 — El espacio de métodos de entrenamiento en una T4

La Parte 0 fijó la ventana (§0.4): adaptar una base 3B abierta con forward barato y update de
bajo costo en 15.6 GB/sm_75. Esta parte mapea los métodos candidatos —costo, calidad, veredicto—
heredando sin redefinir: DC-4 (topología), DC-5 (runtime), DC-7/DC-8 (ancla 424 tok/s), DC-9
(merge).

### 2.1 El presupuesto de memoria (importado de Parte 1, no recalculado)

Qwen2.5-Coder-3B: ~3.1e9 params, hidden 2048, 36 capas, GQA 16/2, inter 11008, vocab 151936.
Tabla importada de Parte 1 + la fila que el borrador original omitía (el consumidor real mayor):

| Componente | fp16 | NF4+DQ |
|---|---|---|
| Pesos base (frozen) | ~6.2 GB | **2.06 GB decimal (1.91 GiB)** [CALCULADO, Parte 1a — unificado en todo el documento; no "~1.8 GB", que omite la embedding fp16 de 0.62 GB sin cuantizar] |
| LoRA r=16 all-linear (~29.9M) + AdamW | ~0.48 GB (0.30 paged 8-bit) | igual |
| Activaciones seq 1024, grad ckpt | ~0.3–0.7 GB | igual |
| **Logits/CE (vocab 151936)** | **~2–3 GB** (consumidor dominante, Parte 1c) | igual |
| Contexto CUDA + fragmentación | ~0.6–0.9 GB | igual |
| **Total pico** | **~10–11 GB** | **~6.5–7 GB** |

Conclusión revisada: en 3B, 15.6 GB **no obliga** a cuantizar —ambos caminos entran— pero con
menos margen del que el borrador estimaba (no "4–5 GB" NF4 / "8–9 GB" fp16). QLoRA es opción para
3B (compra batch/seq/2-modelos a cambio de ruido de cuantización, §2.4/§2.8), no obligación. El
número real lo fija E0/E1 (`max_memory_allocated`). Full FT AdamW (~48 GB) sigue descartado
(Parte 0 §0.3).

### 2.2 LoRA clásico y la lección ALL-LINEAR

**Teoría.** LoRA (Hu et al. 2021) congela W, aprende ΔW=(α/r)·BA, r≪d: costo de optimizador de
A,B cae de 12 bytes/param a ~0. [LITERATURA — QLoRA, Dettmers 2023, NeurIPS]: LoRA en TODAS las
capas lineales es crítico para igualar full FT 16-bit; subir r (8→256) mueve poco — palanca #1
gratis que el pipeline actual no usa.

**Estado del repo [MEDIDO] — atribución corregida (dos kernels distintos):** el run GPU real en
**Kaggle** (2026-07-01) fue `train_tooluse_kaggle.py`: r=8 α=16 qkvo, NF4+DQ fp16, seq 1600, 3
epochs, lr 2e-4, **completion-only masking** (`DataCollatorForSeq2Seq`). Run 1: 99 pares, ~8 min,
eval **6** tareas 83.3%→100%; v4: 161 pares (=99+64 tras dedup de 163, tiempo no loggeado), eval
**10** tareas 0.80→1.00. N=6/N=10: señal direccional, no significancia. Kernel distinto,
`train_qlora_kaggle.py` (r=8 qkvo, seq 1024, b2×ga8, **sin masking**), corrió en **Colab**
(2026-06-10): lr 2e-4 derivó a chino; ganador lr 5e-5 + dropout 0.1 (+69.5% holdout conocimiento).
"lr 2e-4 sobreajusta" es del régimen Colab/destilación, no universal.

**Veredicto: BASE DEL PLAN**, con dos upgrades: targets `q,k,v,o,gate_proj,up_proj,down_proj`
(all-linear) y lr 5e-5–1e-4, más completion-only masking (ya validado en
`train_tooluse_kaggle.py`, ausente en `train_qlora_kaggle.py`).

### 2.3 Variantes de LoRA: rsLoRA, LoRA+, DoRA, PiSSA

- **rsLoRA** [Kalajdzievski 2023, arXiv 2312.03732]: escala α/√r, destraba r≥64 (α/r clásico
  colapsa el gradiente efectivo). Costo 0 (`use_rslora=True`). **E-r**, solo si r=16 all-linear
  muestra techo. [PREDICCIÓN: en datasets chicos r=16 no satura; r=64 no gana medible.]
- **LoRA+** [Hayou et al. 2024, ICML]: lr_B≈16×lr_A, +1–2% y ~2× convergencia. Costo 0
  (`loraplus_lr_ratio=16`). **E-lrp**, entra al backbone si el gate no-regresión pasa.
- **DoRA** [Liu et al. 2024, ICML]: magnitud×dirección, gana a LoRA en rank bajo, pero
  materializar BA en el forward reporta **overhead sustancial (orden +50-80% según la evaluación
  unificada de variantes LoRA, arXiv 2601.22708, ene-2026; cifra exacta no confirmable en el
  abstract accesible)**, no amortiguado sin kernels fused en sm_75. **E-dora**, solo si hay techo
  de calidad Y sobra cuota. [PREDICCIÓN: DoRA r=8 ≈ LoRA r=16 en calidad pero ~1.5× más lento.]
- **PiSSA** [Meng et al. 2024, NeurIPS]: init A,B con SVD de W, congela el residuo; converge
  más rápido y en QLoRA reduce error de cuantización (cuantiza el residuo, no W). Costo: SVD
  one-shot. **E-pissa**, relevante si NF4 gana en §2.4.

### 2.4 QLoRA NF4 vs fp16-LoRA: cuándo cada uno en 15.6 GB

- **QLoRA NF4+DQ** [Dettmers 2023]: NormalFloat-4 + double quant (~0.4 bits/param), compute
  fp16. Recupera 16-bit si LoRA es all-linear. Costo oculto: dequant on-the-fly (overhead de
  benchmarks públicos, no medido en esta T4 → E1). Obliga al merge de dos pasos (§2.8). Gotcha
  [MEDIDO]: `pip install -U bitsandbytes` (≥0.46.1) ANTES de importar transformers (image viejo,
  fix 8b67ac3); torchao 0.10 rompe peft, desinstalar antes.
- **fp16-LoRA**: base fp16 (~6.2 GB), sin dequant, merge limpio. Rama codificada
  (`GPU/fp16-fallback/3B` en `train_qlora_kaggle.py`, con GC) sin corrida registrada.

**Regla de decisión** (no contradice DC-5 — fija el runtime/librería, transformers+PEFT+
bitsandbytes, frente a Unsloth; NF4-vs-fp16 es capa independiente, abierta por DC-9: *"si E1
consagra fp16-LoRA, el merge es limpio por construcción"*): con el margen de §2.1 (~10–11 GB
fp16 vs ~6.5–7 GB NF4, ambos <15.6 GB), fp16-LoRA es candidato racional a default; NF4 se
justifica si (a) seq/batch mayor, (b) 2 modelos en memoria (juez), o (c) rama 2×T4. [PREDICCIÓN
E1: fp16-LoRA 1.2–1.4× más rápido que NF4, calidad ≥ igual; si se confirma, sube el ancla 424
tok/s (DC-7).]

### 2.5 Full-parameter con truco: GaLore, LOMO/AdaLOMO

- **GaLore** [Zhao et al. 2024, arXiv 2403.03507]: proyecta el GRADIENTE a rank bajo, Adam en el
  subespacio (SVD cada T pasos). Titular: LLaMA-7B/RTX4090 24GB, 8-bit + per-layer updates = 22.0
  GB, token-batch≤500. Trasladado a 3B/15.6GB, **dos escenarios**: (i) per-layer updates
  funcionando (gradiente liberado capa por capa): fp16 6.2 + estados 8-bit ~0.7 + activaciones
  1–2 ≈ **8–9.5 GB** — pero incompatible con grad-accum estándar; (ii) si el gradiente completo
  fp16 (6.2 GB) queda vivo: **~14–15 GB**, al borde del OOM. Evidencia de superioridad sobre LoRA
  en fine-tuning (no pretraining) es débil (GLUE/RoBERTa). **E-galore, reserva, NO backbone**.
  [PREDICCIÓN: en ≤33.6M tok/sem (DC-8) GaLore no supera a LoRA y cuesta ≥2× tiempo.]
- **LOMO/AdaLOMO** [Lv et al. 2023]: fusiona gradiente+update por capa, cero estados de
  optimizador; 3B fp16 entraría holgado. Pero SGD sin momentum es frágil para SFT y el update
  toca la base directo (forgetting sin cota de rank, §2.7). **DESCARTADO** — resuelve una
  memoria que el 3B no necesita, sin aislamiento de adapter ni integración PEFT/TRL/GGUF.

### 2.6 NEFTune: ruido en embeddings

[Jain et al. 2023, arXiv 2310.05914]: ruido uniforme α=5 en embeddings sube AlpacaEval de
LLaMA-2-7B 29.8%→64.7%, pero OpenLLM Leaderboard (razonamiento/conocimiento) ~cero — ganancia
conversacional/estilo, no capacidad (mismo paper). Costo 0 (`neftune_noise_alpha=5`, TRL).
**Encender en SFT conversacional; apagar en tool-calling ACCION.** [PREDICCIÓN: puede degradar
la emisión exacta de `ACCION: <tool> <args>` — medir con `correct_tool` antes de fijarlo ahí.]

### 2.7 Multi-etapa: topología (hereda DC-4, no la redefine)

DC-4 congeló la topología default: **secuencial-con-merge** (adapter sobre la última base
mergeada, gates entre etapas, rollback = base anterior intacta). Razón: LoRA acota el olvido
porque ΔW vive en rank≤r [Biderman et al. 2024, "LoRA Learns Less and Forgets Less", arXiv
2405.09673]. Evidencia local [MEDIDO]: lr 2e-4 en una sola etapa (Colab, §2.2) ya derivó a chino.

**Distinto** es el experimento **E-merge** de esta parte: N adapters **independientes en
paralelo desde la MISMA base**, fusionados por interferencia de pesos — no confundir con
**E-MIX** (DC-4/P4/P7: mezcla única de datos vs. etapas separadas, brazo A/B distinto). E-merge
ataca signos entre task vectors: **TIES** [Yadav et al. 2023, NeurIPS] con trim+voto de
signo+merge disjunto; **DARE** [Yu et al. 2024] dropea 90%+ de deltas re-escalando. Los adapters
comparten init (misma cuenca de los *model soups*, [Wortsman et al. 2022]). mergekit/PEFT
(`add_weighted_adapter`, `ties`/`dare_ties`) corren en CPU local, cuota Kaggle = $0.

**Veredicto:** backbone = secuencial-con-merge (DC-4), menor→mayor especificidad
(conocimiento→chat→ACCION último, formato más frágil). **E-merge** puede reemplazar la topología
si gana; **E-MIX** es eje ortogonal (Parte 7 §7.3) — ambos comparten los gates G1-G5 (Parte 3)
como árbitro, ninguno los redefine.

### 2.8 El merge final QLoRA correcto (si NF4 gana en E1)

Patrón DC-9: el adapter QLoRA se entrenó contra `dequant(quant(W))`, no contra W. **Nunca**
`merge_and_unload()` sobre 4-bit (peft #2321, "rounding errors"; Kaitchup mide la degradación).
Mergear sobre fp16 original (sin dequant) introduce mismatch ΔW-vs-base-equivocada. Correcto
(gist ChrisHayduk, Kaitchup): base NF4 con la MISMA `BitsAndBytesConfig` → dequant a fp16 →
merge sobre ESA. Costo real de saltarse esto [MEDIDO]: el adapter v4 corregía `anotar_eval` en
NF4 pero el deploy Q4_K_M diluyó parte del delta r=8. Mitigantes: r/targets mayores, PiSSA
(§2.3), o fp16-LoRA (§2.4), que elimina el mismatch por construcción. Conversión ya verificada
e2e (`convert_lora_to_gguf.py` b9391, `LLAMA_LORA_PATH`) [MEDIDO].

### 2.9 Árbol de decisión

```
COLUMNA VERTEBRAL:
  LoRA all-linear (q,k,v,o,gate,up,down), r=16 α=32, lr 5e-5-1e-4 cosine,
  completion-only masking, dropout 0.05-0.1, fp16+GradScaler (LoRA fp32),
  NEFTune α=5 solo en chat/SFT (apagado en ACCION).
  Batch/seq/micro-batch: HEREDA la config ganadora de E0 (grilla
  e0_perfil_kernel.py, 10 configs A..J, ya committeada/lanzada) — no se fija
  b2×ga8 acá para no competir con esa arbitración (Parte 1, Parte 7 E0).
  Precisión: fp16-LoRA si E1 lo confirma; NF4+DQ si se necesita
  seq/batch mayor o 2 modelos (DC-5/DC-9, §2.4).
  Topología: secuencial-con-merge (DC-4). Merge: (dequant si NF4) → fp16
  → GGUF Q4_K_M → verificación CLI real (DC-9).

EXPERIMENTOS (cada uno con gate no-regresión, Parte 3):
  E1      fp16-LoRA vs QLoRA NF4 (tok/s + calidad + fidelidad post-Q4_K_M) ← 1º
  E-lrp   LoRA+ ratio 16 (costo 0)
  E-merge TIES/DARE multi-adapter vs secuencial (CPU, $0) — ORTOGONAL a E-MIX
  E-r     r=64 + rsLoRA (solo si r=16 muestra techo)
  E-pissa PiSSA init (solo si gana NF4)
  E-dora  DoRA r bajo (solo si hay techo Y sobra cuota)

DESCARTADOS:
  Full FT AdamW      — ~48 GB > 15.6 GB (Parte 0 §0.3)
  Pretraining 0      — 2-3 órdenes de magnitud (Parte 0 §0.2)
  LOMO/AdaLOMO       — memoria que el 3B no necesita; SGD+sin-adapter = riesgo
  GaLore backbone    — caso probado es pretraining 7B/24GB; sin evidencia en
                       fine-tuning 3B (reserva E-galore)
  Merge sobre 4-bit / fp16-sin-dequant — degradación documentada (§2.8)
```

Fuentes: [QLoRA](https://proceedings.neurips.cc/paper_files/paper/2023/file/1feb87871436031bdc0f2beaa62a049b-Paper-Conference.pdf) · [GaLore](https://arxiv.org/abs/2403.03507) · [NEFTune](https://arxiv.org/pdf/2310.05914) · [DoRA](https://arxiv.org/abs/2402.09353) · [Estudio unificado variantes LoRA](https://arxiv.org/pdf/2601.22708) · [Kaitchup merge QLoRA](https://kaitchup.substack.com/p/dont-merge-your-lora-adapter-into) · [peft #2321](https://github.com/huggingface/peft/issues/2321) · [gist ChrisHayduk](https://gist.github.com/ChrisHayduk/1a53463331f52dca205e55982baf9930) · [LoRA Learns Less and Forgets Less](https://arxiv.org/abs/2405.09673)

#### Claims etiquetados (Parte 2)
- [MEDIDO] `train_tooluse_kaggle.py` corrió en Kaggle T4 (2026-07-01): run1 99 pares ~8min eval 6 tareas 83.3→100%; v4 161 pares (=99+64 tras dedup 163, tiempo no loggeado) eval 10 tareas 0.80→1.00 — `checkpoints/tooluse/eval_tooluse.json` + memoria cognia-tooluse-finetune.md. N=6/N=10: direccional, no significancia.
- [MEDIDO] `train_qlora_kaggle.py` (r=8 qkvo, sin masking) corrió en **Colab** (2026-06-10, no Kaggle): lr 2e-4 derivó a chino; ganador lr 5e-5+dropout 0.1, +69.5% holdout conocimiento — `checkpoints/cognia_3b_v2_winner/eval_compare.json` + memoria kaggle-training-pipeline.md.
- [MEDIDO] bitsandbytes viejo en el image de Kaggle + torchao 0.10 rompe peft: requieren `pip install -U bitsandbytes` y desinstalar torchao antes de importar — fix 8b67ac3.
- [MEDIDO] Q4_K_M diluye parte del delta de un adapter r=8 NF4 (`anotar_eval` vuelve a fallar en el CLI) — memoria cognia-tooluse-finetune.md, `verify_lora.py`.
- [CALCULADO] Pesos base NF4+DQ = 2.06 GB decimal (1.91 GiB), unificado con Parte 1.
- [CALCULADO] Total pico ~6.5–7 GB NF4 / ~10–11 GB fp16, sumando logits/CE (~2–3 GB) y contexto CUDA (~0.6–0.9 GB) — Parte 1c.
- [LITERATURA] LoRA all-linear crítico para igualar full FT 16-bit; subir r mueve poco — Dettmers et al. 2023.
- [LITERATURA] rsLoRA destraba ranks altos — Kalajdzievski 2023. LoRA+ (lr_B≈16×lr_A) +1-2%, ~2× convergencia — Hayou et al. 2024.
- [LITERATURA] DoRA: overhead sustancial (orden +50-80%, cifra exacta no confirmable) — arXiv 2601.22708 (2026); DoRA = Liu et al. 2024.
- [LITERATURA] GaLore 8-bit pretraining 7B/24GB=22.0GB/batch≤500 (no fine-tuning); trasladado a 3B/15.6GB: 8-9.5 GB o 14-15 GB según escenario — Zhao et al. 2024 (traslación propia, a falsar).
- [LITERATURA] NEFTune +AlpacaEval sin mover OpenLLM Leaderboard — Jain et al. 2023.
- [LITERATURA] Merge QLoRA sobre base dequantizada, nunca 4-bit ni fp16-sin-dequant — peft #2321, Kaitchup, gist ChrisHayduk.
- [LITERATURA] LoRA acota forgetting vs full FT — Biderman et al. 2024. TIES/DARE resuelven interferencia de signos; model soups exige cuenca compartida — Yadav 2023, Yu 2024, Wortsman 2022.
- [PREDICCIÓN → E1] fp16-LoRA 1.2-1.4× más rápido que NF4, calidad ≥ igual, merge limpio.
- [PREDICCIÓN → E-merge] TIES/DARE ≥ secuencial en promedio multi-eval, mismo presupuesto.
- [PREDICCIÓN → etapa ACCION] NEFTune degrada el formato ACCION; medir `correct_tool` antes de fijar el default.

---

## Parte 3 — Teoría de calidad: gates canónicos G1-G5 (LA definición única)

**Premisa.** El goal no es "entrenar algo": es que `cognia-3b` sea **estrictamente mejor que la base en las habilidades objetivo sin ser peor en lo demás**, medido con el rigor que este repo ya practica (gates congelados ANTES de correr, McNemar pareado, held-out nunca visto — memorias `cognia-xhundred-resultado` y `cognia-rsi-autoprompting`). Esta parte define la taxonomía de fallos, los mecanismos preventivos y **la única tabla de gates G1-G5 del documento (DC-6)**: la Parte 7 la referencia, no la redefine; el baseline de 10 preguntas del kernel es smoke, nunca gate.

### 3.1 Taxonomía de degradación (qué puede salir mal, con evidencia)

**D-1. Olvido de capacidades generales.** Fine-tuning en un dominio degrada dominios no vistos. [LITERATURA] Luo et al. 2023 (arXiv:2308.08747) lo midieron en 1B-7B durante fine-tuning continuo; [LITERATURA] Biderman et al. 2024 "LoRA Learns Less and Forgets Less" (arXiv:2405.09673) muestran que LoRA olvida *menos* que full-FT a igual dato — argumento de calidad, no solo de memoria, a favor de la ventana QLoRA de la Parte 0. [MEDIDO] La corrida XHUNDRED Fase 2 (QLoRA 45 min sobre Qwen2.5-3B en T4) ganó su nicho **sin catástrofe**: MGSM-es +14.8, XStoryCloze −0.4, Belebele −2.6 — el olvido generalista fue chico pero **no cero**.

**D-2. Fijación de modo / colapso de formato.** El caso más traicionero porque las suites "de ganancia" no lo ven. [MEDIDO] En esa misma corrida, el adapter que ganaba +14.8 en 0-shot **cayó −15.2 en 3-shot**: el fine-tune fijó el modo de respuesta y rompió el uso con exemplars (memoria `cognia-xhundred-resultado`). Para Cognia esto es letal: el CLI mete few-shot y system-prompts (scaffold v1 de tool-use: 0.24→0.86 [MEDIDO, `cognia-rsi-autoprompting`]); un adapter que solo funciona 0-shot degradaría el producto real.

**D-3. Pérdida de español.** La base Qwen2.5-Coder-3B (DC-1) es mayormente en/zh/código; si el dataset de adaptación es sesgado a inglés (o a código), la salida en español se erosiona. [PREDICCIÓN] a falsar con G5; no hay medición previa en el repo específica de "responde en español cuando le hablan en español" post-QLoRA.

**D-4. Sobreajuste a estilo del dataset.** Respuestas que imitan la longitud/plantilla de las completions sintéticas (p.ej. todo termina en clase de 40-80 líneas porque `syn_long` domina). [MEDIDO como riesgo estructural] el kernel actual entrena con **todos** los pares sin filtro por `source` (`train_qlora_kaggle.py:204-209`).

**D-5. Degradación por merge.** El adapter se entrena contra la base **NF4** (los residuos LoRA compensan el error de cuantización NF4); al mergear hay que decidir contra qué pesos. Mergear contra la base fp16 original introduce un mismatch adapter↔base distinto al de entrenamiento; la práctica correcta es dequantizar la base NF4 y mergear sobre ESA dequantización ([LITERATURA] docs de peft `merge_and_unload` sobre modelos k-bit, 2023-2024) — **este es exactamente el procedimiento congelado en DC-9**, no una opción abierta. Magnitud del daño en nuestro caso: [PREDICCIÓN], se mide en G4 comparando adapter-vivo vs mergeado.

**D-6. Degradación por cuantización GGUF post-merge.** El checkpoint mergeado fp16 se convierte a GGUF Q4_K_M para el CLI. [LITERATURA] llama.cpp (PR k-quants #1684, 2023) reporta ΔPPL ≈ +0.05 en LLaMA-7B para Q4_K_M; en un 3B el impacto relativo es mayor (menos redundancia) y **no hay número publicado para un 3B recién adaptado**: [PREDICCIÓN]. Peor: la doble transformación NF4-entreno → fp16-merge → Q4_K_M puede componer errores de forma no aditiva. Por eso G4 **re-mide la calidad en llama.cpp**, no la asume.

### 3.2 Mecanismos preventivos (con evidencia y configs)

**P-1. Replay de datos generales.** [LITERATURA] Scialom et al. 2022 ("Fine-tuned Language Models are Continual Learners", EMNLP) muestran que ~1% de rehearsal evita la mayor parte del olvido en continual instruction-tuning; InstructGPT (Ouyang et al. 2022) mezcló gradientes de pretraining (PPO-ptx) con el mismo fin. La práctica 2024-2025 en adaptación de dominio usa 10-30% de mezcla general. **Config propuesta:** 15% del token-budget de cada etapa = mezcla general es+en (instrucciones variadas + QA factual + chat multi-turno), 85% dominio objetivo. Con **~16.8M tokens/sesión al piso 424 tok/s [CALCULADO desde DC-7/DC-8]** (no los ~59M optimistas de un borrador anterior nunca medidos), 15% ≈ **2.5M tokens** de replay por sesión — sigue siendo barato incluso al piso; si E0 confirma ≥800 tok/s el presupuesto de replay escala junto con el resto (Parte 0 §0.4). [PREDICCIÓN E-replay]: ablación 0% vs 15% debería mover G1 en ≥3pp; si no, bajar a 5%.

**P-2. Completions-only masking (fix obligatorio al kernel).** [MEDIDO] El kernel actual **no** enmascara el prompt: usa `DataCollatorForLanguageModeling(mlm=False)` sobre `prompt+completion` concatenados (`train_qlora_kaggle.py:204-245`), o sea que ~40-70% del gradiente (según la fracción de tokens de prompt) va a *modelar el turno del usuario*. Por qué importa: (i) desperdicia señal en el régimen de pocos tokens; (ii) es un vector directo de D-4; (iii) en datasets con prompts largos y completions cortas (tool-use ACCION: la completion es una línea) la loss queda dominada por el prompt. [LITERATURA — matiz honesto] la evidencia no es unánime: Shi et al. 2024 (arXiv:2405.14394) y Huerta-Enochian & Ko 2024 (arXiv:2401.13586) encuentran que *algo* de prompt-loss puede ayudar con datos escasos y completions cortas. **Config:** labels=-100 en tokens de prompt (equivalente a `DataCollatorForCompletionOnlyLM` de TRL), experimento pre-registrado E-mask (masked vs sin-masked vs prompt-loss-weight 0.1) sobre la misma semilla y dataset, gate = G2.

**P-3. Presupuesto de épocas y lr×rank.** [MEDIDO] La receta que corrió en Kaggle (1 epoch, lr 2e-4 cosine, r=8 α=16, warmup 5%) entrenó sin divergencia y ganó su nicho. [LITERATURA] Al subir rank (r=16-32 para etapas de conocimiento), el scaling clásico α/r encoge el update efectivo; rsLoRA (Kalajdzievski 2023, arXiv:2312.03732) propone α/√r; LoRA+ (Hayou et al. 2024, arXiv:2402.12354) sugiere lr de B ≫ lr de A. **Regla concreta:** al duplicar r, mantener α/√r constante o re-tunear lr en {1e-4, 2e-4} con corrida corta; máximo 2 epochs por etapa; >2 epochs solo si un eval intermedio lo justifica — el kernel actual tiene `eval_strategy="no"` [MEDIDO, línea 241]: activar eval por pasos (cada ~200 steps, sobre el split test que el kernel ya crea y hoy no usa) con early-stop por loss de eval creciente durante 2 evals consecutivos.

**P-4. LoRA como seguro estructural + merge disciplinado (DC-4, DC-9).** Los 3B params base quedan congelados: el "olvido" está acotado al subespacio de rango bajo [LITERATURA, Biderman 2024]. Topología: **secuencial-con-merge** (DC-4) — cada etapa entrena adapter sobre la ÚLTIMA base mergeada, con G1-G5 entre etapas; si una etapa rompe un gate, se descarta el adapter (rollback barato: la base mergeada anterior queda intacta). Merge (DC-9): NF4 con la misma `BitsAndBytesConfig` del training → dequantizar a fp16 → `merge_and_unload` sobre esa dequantización → guardar fp16; **nunca** re-cuantizar y volver a entrenar encima del mergeado dentro de la misma etapa (el error se compone). La mezcla única (estilo Tülu 3) es un brazo alternativo, no el default: se arbitra en **E-MIX** (Parte 7 §7.3), no acá.

### 3.3 Gates G1-G5 pre-registrados (canónicos — estilo repo: congelados ANTES, McNemar, held-out)

**Protocolo común.** Suite held-out de **100 ítems por gate** redactada y **congelada por hash en git ANTES de la primera corrida** (pre-requisito P0-ii, DC-10), nunca usada para tuning ni para seleccionar checkpoints (el split dev/test disjunto de `bfcl_split.py` es el patrón [MEDIDO]). Scoring por **oráculo determinista** (keywords normalizados con `fold()`, AST-check + sandbox para código, `parse_model_response` para ACCION, langid para español) — nunca LLM-juez ([MEDIDO como práctica: el árbitro AG-ARB por oráculo dio 100% vs 31% del LLM-juez, memoria `cognia-herramientas-ai-nativas`]). Decodificación **greedy/temp 0**. Test: **McNemar exacto pareado** (binomial sobre pares discordantes), dos colas, α=0.05 — el mismo gate que ya mató un +1/50 espurio en prompt_evolution [MEDIDO]. Dónde corre: G1/G2/G3/G5 dentro del kernel de Kaggle post-training (base vs base+adapter, mismo proceso — el kernel ya hace eval pareado base/adapter [MEDIDO]); G4 re-corre G1+G2 (200 ítems totales) en el CLI local con llama.cpp — a ~8 tok/s y ≤200 tokens/ítem eso son **~90-180 min solo de decode**, más la corrida de perplexity aparte (un GGUF fp16 de referencia decodifica ~2-3 tok/s en esta CPU): **2-4 h en total, factible overnight** [MEDIDO el techo de tok/s, memoria `llama-server-speed-findings`; corrección de estimación previa 45-90 min, que solo contaba decode de 100 ítems].

- **G1 — No-regresión general (100 ítems: 25 razonamiento es/en, 25 factual es/en, 25 código, 25 seguir-instrucciones/formato).** PASA si: (a) McNemar NO detecta regresión significativa (p≥0.05 en la dirección mala), **y** (b) delta puntual ≥ −4pp, **y** (c) ningún sub-dominio cae >10pp puntual. Incluir 20 de los 100 ítems en modo **3-shot** para cazar D-2 (la lección MGSM −15.2 [MEDIDO]).
- **G2 — Ganancia objetivo (por etapa; suites de 100 ítems c/u).** Tool-use ACCION (checker `parse_model_response`), código (AST + ejecución sandbox), razonamiento (respuesta exacta). PASA si delta ≥ +10pp **y** McNemar p<0.05. A ese umbral y N=100, la potencia real es **73.3%** (§3.4) — un fallo de G2 con delta puntual 8-12pp exige **re-test**, no descarte automático. Ancla direccional (no estadística): el fine-tune de tool-use de-risk dio +66.7pp en correct_tool sobre el **0.5B con N≈6** [MEDIDO, memoria `cognia-tooluse-finetune`] — 4 pares discordantes de 6 dan McNemar p=0.125, **no significativo**; el número vale como señal de que el efecto existe y es grande, no como prueba de detectabilidad al N=100 de este gate.
- **G3 — Identidad Cognia sin regresión.** 20 prompts de identidad ("¿quién sos?", "¿quién te creó?", es y en). Oráculo: regex — contiene "Cognia" ∧ no contiene "Qwen|Alibaba". PASA si ≥18/20 **y** G1 sigue pasando (la identidad no puede costar capacidades). [PREDICCIÓN] 20 ítems bastan porque el efecto esperado es enorme (base: ~0/20 dice Cognia).
- **G4 — Integridad merge+GGUF (el gate que nadie corre y acá es obligatorio).** Tras merge fp16 → GGUF Q4_K_M (patrón DC-9), re-correr G1+G2 (200 ítems) **en llama.cpp en el CLI local**, comparando contra el adapter-vivo medido en Kaggle. PASA si: delta agregado (GGUF vs adapter-en-kernel) ≥ −4pp, McNemar sin regresión significativa, y perplexity en un corpus fijo es/código dentro de +5% vs el merge fp16 (medida con `llama-perplexity`, corrida aparte del decode de los 200 ítems — ver protocolo común). Si falla: probar Q5_K_M o imatrix antes de culpar al training. [PREDICCIÓN] el costo de Q4_K_M en el 3B adaptado será ≤3pp; no hay dato previo — por eso es gate y no supuesto.
- **G5 — Español.** 25 ítems solo-español (instrucciones, cloze estilo XStoryCloze-es [el repo ya usó cloze-es como gate, MEDIDO], QA). Doble criterio: (a) accuracy ≥ base −1 ítem; (b) **responde en español** ≥ 24/25 (langid sobre la respuesta). El criterio (b) caza D-3 aunque el contenido sea correcto.

### 3.4 Anti-Goodhart y potencia estadística (qué NO se puede concluir)

**Por qué se congela el held-out.** Si los ítems se ven durante el desarrollo, el pipeline optimiza el test (Goodhart) — el bug-class que la verificación adversarial de XHUNDRED corrigió cuando un "PARCIAL" estaba inflado [MEDIDO como práctica]. El hash del archivo de suite se commitea antes del primer run (P0-ii, DC-10); cualquier cambio posterior = suite nueva, resultados no comparables.

**Por qué greedy/temp 0.** Elimina la varianza de sampling del par (base, adaptado): McNemar asume que la discordancia refleja al modelo, no al RNG. (Matiz honesto: llama.cpp con batching/threads puede tener no-determinismo numérico residual; fijar seed, threads y correr la suite 2× — si >2 ítems flipean entre corridas idénticas, la suite tiene ítems inestables que hay que reescribir.)

**Potencia [MEDIDO: `cognia_v3/eval/mcnemar_power.py` + `mcnemar_power_results.json`, seed 20260706, 20k reps, α=0.05 dos colas, binomial exacto sobre discordantes; test en `tests/test_mcnemar_power.py`, commit 5cb84c4 — pre-requisito P0(i) cumplido].** Con p10=0.02 fijo: **N=50** → +8pp: 20.0%, +12pp: 44.5%, +18pp: 76.2%. **N=100** → +8pp: 56.5%, +10pp: 73.3%, +12pp: 85.6%, +18pp: 98.4%. Sensibilidad al churn en el umbral del gate (+10pp, N=100): p10=0.06 → 49.5%, p10=0.12 → 33.4% — **regla de re-test pre-registrada**: si un delta puntual de 8-12pp falla el test, repetir con N mayor antes de descartar el adapter. **N=200** (G4, 100+100 combinados) → +10pp: 97.5%. Casos extremos: **N=10** detecta un delta verdadero de +30pp solo el **5.5%** de las veces; **N=16** detecta +20pp solo el **9.1%**. Umbrales exactos de pares discordantes-para-significancia: 10→9, 15→12, 20→15, 30→21, 50→33.

Conclusiones vinculantes: (1) **N≤16-50 solo sirve para efectos enormes y aun así con potencia baja-media**; (2) G2 (+10pp, N=100) opera al 73.3% de potencia nominal — no es un gate infalible, de ahí la regla de re-test; (3) para no-regresión, "McNemar no significativo" con N=50 **jamás** demuestra equivalencia — un olvido real de −6pp pasaría desapercibido la mayoría de las veces; por eso G1 combina test estadístico + banda puntual (−4pp) + sub-dominios, y se declara "sin regresión *detectable* a esta potencia", no "sin regresión"; (4) el baseline de 10 preguntas keyword del kernel [MEDIDO, `BASELINE_QUESTIONS`] es **smoke, jamás gate** (DC-6): con N=10 ni un delta de 30pp es concluyente (5.5% de potencia) — se conserva solo como humo dentro del kernel, nunca como sustituto de G1-G5.

**Límite declarado.** Suites de 100 ítems por dominio detectan regresiones groseras y ganancias medianas-grandes; no certifican calidad fina (estilo, coherencia larga, multi-turno profundo). Eso queda para la verificación E2E del CLI ("código que corre o no cuenta") y para las preguntas abiertas.

#### Claims etiquetados (Parte 3)
- [MEDIDO] El kernel QLoRA actual entrena sobre prompt+completion SIN masking del prompt y con `eval_strategy="no"` — evidencia: `train_qlora_kaggle.py:204-245`.
- [MEDIDO] QLoRA en T4 sobre el 3B gana su nicho sin catástrofe generalista pero FIJA el modo: MGSM-es +14.8 en 0-shot, −15.2 en 3-shot; XSC −0.4, Belebele −2.6 — evidencia: memoria `cognia-xhundred-resultado` (corrida real Kaggle T4 2026-07-02, gates pre-registrados).
- [MEDIDO] El gate McNemar pareado sobre held-out congelado ya funcionó en este repo: mató un +1/50 espurio (p=1.0) en prompt_evolution — evidencia: memoria `cognia-rsi-autoprompting`.
- [LITERATURA] ~1% de rehearsal mitiga la mayor parte del olvido; la práctica de dominio usa 10-30% — Scialom et al. 2022; Ouyang et al. 2022 (PPO-ptx).
- [LITERATURA] LoRA olvida menos que full fine-tuning a igual dato — Biderman et al. 2024 (arXiv:2405.09673).
- [LITERATURA] Evidencia mixta sobre completions-only masking: estándar, pero algo de prompt-loss puede ayudar con datos escasos — Shi et al. 2024 (arXiv:2405.14394); Huerta-Enochian & Ko 2024 (arXiv:2401.13586).
- [LITERATURA] Q4_K_M cuesta ~+0.05 PPL en LLaMA-7B; en un 3B recién adaptado el costo es desconocido y se re-mide en G4, no se asume — llama.cpp k-quants (PR #1684, 2023).
- [MEDIDO] Potencia exacta de McNemar (script+JSON+test commiteados, commit 5cb84c4): N=50 +8pp→20.0%/+12pp→44.5%/+18pp→76.2%; N=100 +8pp→56.5%/+10pp→73.3%/+12pp→85.6%/+18pp→98.4%; N=200 +10pp→97.5%; N=10 +30pp→5.5%; N=16 +20pp→9.1% — evidencia: `cognia_v3/eval/mcnemar_power.py` + `mcnemar_power_results.json`.
- [MEDIDO] El baseline de 10 preguntas keyword del kernel es smoke-test sin poder estadístico, no gate (DC-6) — con N=10 ni un delta de 30pp es concluyente (potencia 5.5%).
- [MEDIDO] El ancla de tool-use +66.7pp en correct_tool proviene del **0.5B con N≈6** (memoria `cognia-tooluse-finetune`); bajo McNemar exacto, 4-vs-0 discordantes da p=0.125 — no significativo; vale como señal direccional del tamaño del efecto, no como evidencia de detectabilidad al N=100 de G2.
- [CALCULADO] Los 200 ítems de G4 (G1+G2 combinados) en llama.cpp toman ~90-180 min de decode (~8 tok/s, ≤200 tok/ítem) más la corrida de perplexity aparte (~2-3 tok/s sobre el GGUF fp16 de referencia): 2-4 h totales, factible overnight.
- [PREDICCIÓN] Entrenar el adapter contra la base NF4 y mergear contra fp16 dequantizado (DC-9) introduce un mismatch cuantificable pero de magnitud desconocida — a medir en G4 (adapter-vivo vs mergeado).
- [PREDICCIÓN] 15% de replay (~2.5M tokens/sesión al piso 424 tok/s, DC-7/DC-8) evitará regresión en G1; ablación E-replay 0% vs 15% debería mover ≥3pp.
- [PREDICCIÓN] Completions-only masking mejorará G2 en tool-use sin dañar G1 — experimento pre-registrado E-mask, gate=G2 con N=100.

### Preguntas abiertas
- ¿Cuánto cuesta Q4_K_M en un 3B recién adaptado (vs +0.05 PPL publicado para 7B base)? ¿Q5_K_M/imatrix recuperan si G4 falla? — primera corrida de G4 lo responde.
- ¿El mismatch NF4-entreno → fp16-merge (DC-9) es medible en la suite? ¿Conviene entrenar la última etapa directamente contra la base fp16 mergeada?
- ¿Prompt-loss-weight 0.1 le gana al masking total en completions cortas de ACCION? — E-mask lo decide.
- ¿15% de replay alcanza en un multi-stage de 3-4 etapas donde el olvido se acumula entre merges? ¿Hace falta replay de etapas anteriores además del general?
- ¿Cuántos ítems de la suite flipean entre dos corridas greedy idénticas en llama.cpp (threads=3)? Si >2/100, hay que reescribir ítems inestables antes de confiar en McNemar.
- ¿La sub-suite de 20 ítems 3-shot detecta D-2, o hace falta una suite few-shot dedicada de 50 ítems dado que ese fue el fallo real medido (−15.2)?
- ¿Cómo gatear coherencia multi-turno larga (fuera del alcance de suites de 1 turno)? Candidato: gate e2e de 100k con oráculo de estructura, costo (~horas) limita frecuencia.

---

## Parte 4 — Teoría de datos

Esta parte no redefine gates (DC-6, Parte 3) ni la topología de entrenamiento (DC-4): asume secuencial-con-merge como default y reencuadra la mezcla única propuesta en el borrador como la hipótesis del brazo **E-MIX**.

### 4.0 Estado real del repo (lo que YA existe, medido)

1. **Tool-use ACCION** (`cognia_v3/training/tooluse/`): dos corridas de Kaggle distintas, que hay que citar por separado (no fusionarlas en un solo hecho). **Run 1**: 99 pares generados por el 3B local, ~8 min, eval **N=6**, correct_tool 83.3%→100% (+16.7pp) [MEDIDO]. **v4** (reentreno): 161 pares = 99 + 64 trayectorias expertas scripted **tras dedup de 163 brutos**, tiempo no loggeado, eval **N=10**, correct_tool 0.80→1.00 (+20pp) [MEDIDO: `checkpoints/tooluse/eval_tooluse.json`, memoria `cognia-tooluse-finetune`]. Ancla direccional adicional (no gate): de-risk del 0.5B 16.7%→83.3% (+66.7pp, **N≈6**, 4 pares discordantes → McNemar exacto p=0.125, **no significativo** — señal de tamaño de efecto, no de detectabilidad; ver Parte 3 §3.3 G2). Lección paga con las tres corridas: el 3B base da **0% accept en tareas multi-paso** (accept_rate global 0.507 con el 3B, `tasks.py`, 42 tareas) — el self-instruct puro no genera los datos difíciles; las trayectorias expertas ejecutadas contra las tools reales sí.
2. **Código sintético** (`cognia_v3/training/synthetic/`): `datagen_report.json` [MEDIDO]: generador Qwen2.5-Coder-**7B** en Kaggle, 20 generados / 8 aceptados (acceptance 0.4) tras scan estático + asserts + ejecución sandbox, en **14,813 s (~4.1 h)**, corrido en CPU por el bug `machine_shape` (ya fixeado, commit 331db7c). El merged actual tiene 22 ejemplos. El throughput de generación es el cuello (~2 aceptados/hora), no la validación.
3. **`cognia_dataset.jsonl`** (dataset_gen.py, KG+episodios): 3,489 pares [MEDIDO], baja calidad: plantillas en inglés sobre contenido en español, triples vacuos, ruido U+200B. No usar tal cual: materia prima para D5 solo tras filtrado agresivo. [PREDICCIÓN → **E-D5**: el pipeline de filtrado de D5 loggea la tasa real de supervivencia (aceptados/3,489) como métrica registrada — predicción puntual: <30% sobrevive].

También [MEDIDO]: el CLI parsea `ACCION: <tool> <args>` por regex (`cli.py`), NO JSON → los datasets públicos de function-calling (Glaive, ToolACE, xLAM) no sirven sin reformateo; y CoT-por-turno lleva al 3B de 0.3125→0.8125 en razonamiento (16 ítems, `bench_reasoning.py`) pero rompe compliance de formato (0.75→0.25).

### 4.1 Calidad > cantidad: cuánto N por etapa

[LITERATURA] Para SFT de estilo/identidad el N útil es chico si la calidad es alta: **LIMA** (Zhou et al., 2023) alinea un 65B con 1,000 ejemplos curados; **AlpaGasus** (Chen et al., 2023): 9k filtrados > 52k de Alpaca; **Deita** (Liu et al., 2024): paridad con ~6k por complejidad×calidad×diversidad; **Tülu 3** (Lambert et al., 2024) confirma que la mezcla curada domina sobre el volumen. Para **habilidades verificables** (código, tool-use, matemática) el N útil es mayor y la señal correcta es la verificación por ejecución, no el gusto humano (Self-Instruct, Wang et al. 2023; STaR, Zelikman et al. 2022).

N objetivo por etapa **si E0 confirma ≥800 tok/s útiles** (plan restaurado, DC-7): D1 ~1,500 / D2 ~4,000 / D3 ~6,000 / D4 ~5,000 / D5 ~15,000 (31,500 total, ~17.6M tok/epoch). **Al piso 424 tok/s** (regla 1) este plan no entra en el presupuesto de una sesión a costo razonable — §4.3 da el plan redimensionado que sí rige mientras no haya medición de E0. [PREDICCIÓN → **E-D2**]: 4,000 pares con cobertura completa de tools × multi-paso × memoria/KG satura la selección de herramienta; se falsea con la curva 161→500→2k→4k sobre el eval ampliado.

### 4.2 Las cinco etapas de datos

**D1 — Identidad + estilo Cognia (español).** ~1,500 ejemplos multi-turno (régimen restaurado) / ~1,250 al piso (§4.3): quién es Cognia, tono rioplatense neutro, rechazos honestos, manejo de los system prompts reales del CLI. Fuente: escritura experta + generación GLM/Claude, curado manual al 100%. Régimen LIMA: acá calidad manda absolutamente.

**D2 — Tool-use ACCION.** Escalar el pipeline que ya demostró la ganancia medida en 4.0: (i) ampliar `tasks.py` de **42 → ~150 tareas** (composiciones multi-paso, errores y recuperación — conservar trayectorias `RESULTADO ... ERROR` + corrección siguiente, hoy descartadas por el hindsight relabeling [PREDICCIÓN → **E-D2b**]); (ii) trayectorias expertas para lo que el 3B no genera (0% accept multi-paso, medido); (iii) paráfrasis de la tarea para inyectar diversidad léxica (el generador es determinista). Cobertura pendiente: `recordar`/`memorizar` (episódica) no se cubre hoy.

**D3 — Código con verificación por ejecución.** Pipeline funciona pero rinde ~2 aceptados/h. Fix: generar con el 7B **batched** en Kaggle (o vLLM si entra en T4) y validar (sandbox+asserts, barato) en paralelo. Alternativa que evita el cuello: partir de datasets públicos verificables (MBPP/CodeContests-style con tests) y solo reformatear al estilo Cognia, reservando la generación sintética para el nicho (APIs internas de Cognia). Acceptance 0.4 medido → para 6,000 aceptados hacen falta ~15,000 generados.

**D4 — Razonamiento CoT-por-turno.** El dato medido (0.31→0.81 solo si la instrucción CoT vive en el turno de usuario) fija el formato: disparador CoT en el turno de usuario (como `stepwise.py` en deploy), respuesta = razonamiento paso a paso + respuesta final delimitada — match train↔inference exacto (entrenar CoT "espontáneo" con system prompt sería una distribución que el deploy nunca ve). Fuente: GSM8K/matemática traducida + problemas propios, validación por respuesta exacta (oráculo aritmético, estilo STaR). Incluir ~20% de contraste "formato exacto sin CoT" para no romper compliance (el trade-off 0.75→0.25 es el riesgo #1; [PREDICCIÓN → **E-D4**]: medir compliance y razonamiento juntos post-SFT, en la suite de razonamiento ampliada a N≥50-100 que exige DC-10/Parte 3 antes de que el gate tenga potencia).

**D5 — Español general + replay anti-olvido.** (i) instrucciones generales en español (subset filtrado de Aya, Üstün et al. 2024 [LITERATURA]); (ii) `cognia_dataset.jsonl` filtrado (quality ≥0.8, sin plantillas vacuas — E-D5); (iii) replay: muestras de la distribución de la base (prompts generales → respuestas del propio base aceptadas por un juez barato). [LITERATURA] Biderman et al. 2024 muestran que LoRA olvida menos que full-FT — el replay es seguro barato, no la defensa principal; Parte 3 P-1 fija el presupuesto operativo de replay (~15% del token-budget, ~2.5M tokens/sesión al piso 424, DC-7/DC-8) — esta parte no lo redefine.

### 4.3 Mezcla: default secuencial, E-MIX como hipótesis, redimensionada al piso

La topología default es **secuencial-con-merge** (DC-4): cada etapa D1→D5 entrena un adapter sobre la última base mergeada, con G1-G5 entre etapas (Parte 3); rollback = la base mergeada anterior. La propuesta de "una sola mezcla" (estilo Tülu 3, Lambert et al. 2024) **no es el plan default** — es la hipótesis que arbitra el brazo **E-MIX** (Parte 7 §7.3, DC-4): A/B secuencial-con-merge vs mezcla única tras E1, mismo presupuesto de tokens, gates G1-G5 unificados como árbitro (si la mezcla única empata o gana en el promedio multi-gate, las etapas posteriores colapsan en una sola corrida).

[PREDICCIÓN, falsable en E-MIX] Corpus para la primera pasada de mezcla, **redimensionado al piso 424 tok/s** (regla 1: ~8-12M tokens × 1-2 epochs, no los ~17.6M tok/epoch × 3 del plan restaurado):

| Etapa | Ejemplos (piso) | % | tok/ej (medio) | Tokens/epoch |
|---|---|---|---|---|
| D1 identidad | 1,250 | 5% | 400 | 0.50M |
| D2 ACCION | 1,450 | 13% | 900 | 1.30M |
| D3 código | 3,150 | 19% | 600 | 1.89M |
| D4 CoT | 3,550 | 16% | 450 | 1.60M |
| D5 español+replay | 9,400 | 47% | 500 | 4.70M |
| **Total** | **~18,800** | | | **~10.0M** |

Al piso 424 tok/s: 1 epoch (10.0M tok) ≈ 6.6 h; 2 epochs (20.0M tok) ≈ 13.1 h (~1.2 sesiones de 11h, DC-8). Si E0 confirma el objetivo ≥800 tok/s [PREDICCIÓN → E0], 2 epochs bajan a ~6.9 h (1 sesión) y se restauran los N objetivo de §4.1 (31,500 ejemplos, ~17.6M tok/epoch) — árbol pre-registrado en Parte 7 §7.1. Las proporciones (%) se conservan en ambos regímenes: D5 domina por ser la banda de menor riesgo y la que protege la base; D2/D3 pesan por ser el diferencial de producto (agente CLI); D1 chico porque el estilo se aprende con poco (LIMA) y sobre-representarlo produce muletillas. El costo computacional cuenta el prompt aunque esté maskeado (el forward pasa por toda la secuencia).

### 4.4 Deduplicación y descontaminación vs los gates

Los gates canónicos son G1-G5 (Parte 3 §3.3, DC-6) — esta sección no los redefine. Los instrumentos que alimentan sus suites incluyen `bench_reasoning.py` (16 ítems + 4 de formato, no 32), `benchmark_code.py`, `bench_bfcl_slice.py` (slice BFCL held-out 50 ítems, umbral 0.80 — regla global 6), `bench_design.py`, y el eval de tool-use (10 tareas hoy → ~150 con `tasks.py` ampliado, held-out N≥100 por P0-ii antes de congelar). El baseline de 10 preguntas embebido en `train_qlora_kaggle.py` es **smoke del kernel, jamás gate** (DC-6). Reglas duras de higiene de datos:

1. **Dedup interno**: hash exacto de `completion` normalizada + near-dup MinHash/Jaccard >0.8 sobre prompt+completion. [LITERATURA] Lee et al. 2021 ("Deduplicating Training Data Makes LMs Better"): los duplicados degradan y sobre-memorizan.
2. **Descontaminación**: overlap de 13-gramas entre cada ejemplo de train y cada ítem de las suites held-out congeladas (estándar GPT-3, Brown et al. 2020 [LITERATURA]); cualquier hit → el ejemplo sale de train.
3. **Riesgo específico del repo** [MEDIDO]: train y eval de tool-use salen del MISMO `tasks.py` — el eval es held-out por `task_id`, pero comparte plantillas y verbos con train (mide "aprendió la habilidad", infla vs. generalización real). Fix: eval-v2 con tareas escritas desde cero, sin plantillas compartidas, congelado ANTES de generar el train ampliado ([PREDICCIÓN → **E-DECON**]: comparar delta en eval-plantilla vs eval-fresco; si divergen mucho, hubo contaminación blanda).
4. Los ítems de `bench_reasoning` y toda suite held-out se greppean literalmente contra cada JSONL de train antes de cada corrida (script corto, corre en el runner de Kaggle antes de subir).

### 4.5 Quién genera lo sintético

Regla vigente del repo: nada auto-generado se entrena sin verificación por ejecución/oráculo. El generador se elige por costo, no por confianza:

- **Trayectorias expertas scripted** (cero LLM): D2 multi-paso y memoria/KG — gratis, determinista. Primera opción si la secuencia correcta es escribible a mano.
- **7B local/Kaggle** (Qwen2.5-Coder-7B): D3 y paráfrasis de D2. Acceptance 0.4 medido; el cuello es throughput → batchear.
- **El propio 3B (self-instruct/rejection sampling estilo STaR)**: solo donde ya acierta — D4 (CoT-por-turno resuelve 0.81; sus cadenas correctas son datos on-distribution legítimos). NO para multi-paso de D2 (0% accept medido).
- **GLM/Claude (LLM externo)**: D1 (identidad, curable a mano) y semillas de diversidad para D3/D4. Costo por API — usar solo donde el 7B no llega en calidad de español.

### 4.6 Formato

- **Chat template de la base** (Qwen2.5: ChatML), vía `tokenizer.apply_chat_template` — nunca concatenación manual (lección MoM: el bug de prompt-templado que metía la instrucción en el turno del asistente producía salida VACÍA con el modelo real).
- **Completion-only masking SIEMPRE**: `train_tooluse_kaggle.py` ya lo hace; `train_qlora_kaggle.py` entrena sin masking [MEDIDO] — Parte 3 P-2 lo fija como fix obligatorio del kernel antes del run principal (con TOOLS_DOC ~700 tok, sin masking la loss queda dominada por el prompt).
- **Multi-turno real**: trayectorias ACCION como turnos alternados assistant(`ACCION:`)/user(`RESULTADO ...`), loss solo en turnos del asistente.
- **System prompts variados**: muestrear los system prompts reales del CLI (agente, chat, /hacer) + variaciones. [PREDICCIÓN → **E-SYS**]: entrenar con 1 solo system prompt degrada al cambiar el prompt en deploy.
- seq_len 1024 cubre D1/D4/D5; D2/D3 multi-paso necesitan **2048** (trayectoria de 5 pasos con TOOLS_DOC no entra en 1024) — costo de VRAM a verificar en T4 ([PREDICCIÓN → **E-SEQ**]).

### 4.7 Preguntas abiertas → experimentos

**E-D2** curva N para tool-use; **E-D2b** ¿recuperación-de-error mejora robustez del agente?; **E-D4** CoT vs compliance simultáneos sobre suite ampliada; **E-MIX** mezcla única vs secuencial-con-merge (árbitro de DC-4, Parte 7 §7.3); **E-DECON** eval-fresco vs eval-plantilla; **E-D5** tasa de supervivencia del filtrado de `cognia_dataset.jsonl`; **E-SEQ** 2048 en T4; **E-SYS** robustez a system prompt variado; throughput de generación sintética batched (¿sube los ~2 aceptados/hora?); y el fantasma transversal: la dilución NF4→Q4_K_M medida en deploy (Parte 3 D-6/G4) — todo delta de datos debe re-medirse sobre el GGUF Q4_K_M final, no solo en el kernel NF4.

#### Claims etiquetados (Parte 4)
- [MEDIDO] Run 1 de tool-use: 99 pares generados por el 3B, ~8 min, eval N=6, correct_tool 83.3%→100% — `checkpoints/tooluse/eval_tooluse.json`, memoria `cognia-tooluse-finetune`.
- [MEDIDO] v4 de tool-use: 161 pares = 99 + 64 trayectorias expertas scripted tras dedup de 163 brutos, tiempo no loggeado, eval N=10, correct_tool 0.80→1.00 — mismo origen; `gen_expert.py`.
- [MEDIDO] Ancla direccional del de-risk 0.5B: correct_tool 16.7%→83.3% (+66.7pp) con N≈6 (4 discordantes → McNemar p=0.125, no significativo) — no es evidencia de detectabilidad al N=100 de G2 (Parte 3).
- [MEDIDO] El 3B base da 0% accept en tareas multi-paso (accept_rate global 0.507); las trayectorias expertas scripted contra tools reales sí generan esos datos — `tasks.py` (42 tareas), `gen_expert.py`.
- [MEDIDO] El datagen de código sintético con el 7B en Kaggle: 20 generados / 8 aceptados (acceptance 0.4) en 14,813 s (~4.1h) → ~2 aceptados/hora, cuello de throughput no de validación — `datagen_report.json`; `synthetic_code_dataset_merged.jsonl` (22 líneas).
- [MEDIDO] `cognia_dataset.jsonl` (3,489 pares) es de baja calidad estructural (plantillas en inglés, triples vacuos, ruido U+200B) — usable en D5 solo tras filtrado agresivo (E-D5).
- [MEDIDO] CoT-por-turno en el 3B: 0.3125→0.8125 en razonamiento (16 ítems + 4 de formato) si el disparador vive en el turno de usuario, pero rompe compliance (0.75→0.25) — `bench_reasoning.py`, memoria `cognia-reasoning-cot-dirigido`.
- [MEDIDO] `train_qlora_kaggle.py` entrena sin completion-only masking; `train_tooluse_kaggle.py` sí maskea — fix obligatorio antes del run principal, fijado en Parte 3 P-2.
- [LITERATURA] Para SFT de estilo/identidad, ~1k-9k ejemplos curados bastan y superan corpus grandes sin curar — LIMA, AlpaGasus, Deita, Tülu 3.
- [LITERATURA] La deduplicación de train mejora calidad y reduce memorización; la descontaminación estándar es overlap de 13-gramas contra eval — Lee et al. 2021; Brown et al. 2020.
- [LITERATURA] LoRA olvida menos que full fine-tuning; el replay anti-olvido es un seguro barato (~15% del budget, fijado en Parte 3), no la defensa principal — Biderman et al. 2024; Scialom et al. 2022.
- [PREDICCIÓN → E-MIX] La mezcla única redimensionada al piso (~18,800 ejemplos, ~10.0M tok/epoch) toma ~6.6h/epoch a 424 tok/s (~13.1h para 2 epochs, ~1.2 sesiones); si E0 confirma ≥800 tok/s, se restauran los N de §4.1 y el tiempo baja a la mitad — aritmética en §4.3, a falsar con el run real.
- [PREDICCIÓN → E-D2] 4,000 pares con cobertura completa (multi-paso + memoria/KG + recuperación de errores) saturan la selección de herramienta en el eval ampliado — extrapolación del +20pp con 161 pares (N=10).
- [PREDICCIÓN → E-DECON] El eval de tool-use actual comparte plantillas con train (mismo `tasks.py`) → el delta medido puede estar inflado vs generalización real; se necesita eval-v2 escrito desde cero y congelado antes de generar train.

### Preguntas abiertas
- E-D2: ¿curva de aprendizaje de correct_tool con 161→500→2,000→4,000 pares? ¿Dónde satura?
- E-D2b: ¿trayectorias con RESULTADO...ERROR + corrección mejoran la robustez del agente en deploy?
- E-D4: ¿se puede entrenar CoT-por-turno sin degradar compliance (trade-off medido 0.75→0.25)? Medir ambos ejes en el mismo checkpoint, sobre suite ampliada.
- E-MIX: mezcla única vs secuencial-con-merge — ¿cuál gana en el promedio multi-gate al mismo presupuesto de tokens? (Parte 7 §7.3 tiene la regla de decisión).
- E-DECON: ¿cuánto diverge el delta en eval-plantilla vs eval-fresco?
- E-D5: ¿qué % de `cognia_dataset.jsonl` sobrevive el filtrado de calidad ≥0.8?
- E-SEQ: ¿entra seq_len 2048 en la T4 con NF4 + batch efectivo 16?
- E-SYS: ¿system prompts variados en train mejoran la robustez al cambiar el prompt del CLI en deploy?
- Throughput de generación sintética: ¿batchear el 7B sube los ~2 aceptados/hora a un ritmo que haga viable D3 a 6k? ¿O conviene reformatear datasets públicos verificables y reservar lo sintético para APIs internas?
- Dilución NF4→Q4_K_M: ¿el delta del adapter medido en el kernel se pierde en el GGUF final? Todo gate debe correr sobre el Q4_K_M, no solo en el kernel (Parte 3 G4).

---

## Parte 5 — Operaciones Kaggle: entrenar de verdad, sesión tras sesión

Esta parte convierte la teoría de adaptación (Partes 1-4) en un protocolo operable con lo que ya existe en el repo. No partimos de cero: hay tres orquestadores CLI que ya corrieron kernels GPU reales (`cognia_v3/training/kaggle/run_kaggle_training.py`, `run_kaggle_tooluse.py`, `cognia_x/construccion/run_kaggle_xspeed.py`) y un kernel QLoRA que entrenó el 3B en T4 (`train_qlora_kaggle.py`, corrido en Colab; ver Parte 2 §2.2 para la atribución exacta de cada run). El patrón probado es: **staging local → `kernel-metadata.json` → `kaggle kernels push` → poll cada 60 s → `kaggle kernels output`** [MEDIDO: los 3 runners]. Todo presupuesto de tokens de esta parte hereda el ancla DC-7/DC-8 (424 tok/s piso, ≥800 objetivo de E0): no se repiten los números, se referencian.

### 5.1 Lo que el repo ya sabe (lecciones pagadas, no repetirlas)

- **`machine_shape` es el campo efectivo, `enable_gpu` se ignora.** El backend nuevo de Kaggle corrió 2 runs de 4 h en CPU con `enable_gpu: true` hasta que se agregó `"machine_shape": "NvidiaTeslaT4"` [MEDIDO: `run_kaggle_training.py:99-102`, fix 331db7c].
- **`PYTHONUTF8=1` en el entorno del CLI local** o `kaggle kernels push` revienta leyendo el `code_file` en cp1252 (`'charmap' codec can't decode byte 0x81`) [MEDIDO: `run_kaggle_xspeed.py:30-34`].
- **bitsandbytes del image es viejo**: el load 4-bit muere; el kernel hace `pip install -U bitsandbytes` (>=0.46.1), con fallback a fp16 si falla. Crítico: **importar transformers/peft DESPUÉS del upgrade** — transformers cachea la detección de bnb al primer import [MEDIDO: `train_qlora_kaggle.py:53-78`, fix 8b67ac3].
- **torchao 0.10 del image ROMPE peft** (`is_torchao_available()` lanza `ImportError`) → desinstalar torchao antes de importar peft [MEDIDO: `train_tooluse_kaggle.py:91-105`].
- **4 de 10 lanzamientos GPU fallaron** en XHUNDRED (cola, timeouts de push) [MEDIDO: memoria cognia-xhundred-resultado] → diseñar con retry, no asumir éxito al primer intento.
- **La verificación de teléfono gatea GPU e internet a nivel de cuenta** (no de kernel). Ya resuelta en `anthuananthuan`: kernels GPU corrieron 2026-07-01→03 [MEDIDO: HECHOS_MEDIDOS.md].
- **Formato de `model_sources`**: `{owner}/{slug}/{framework}/{instance}/{version}` → montado bajo `/kaggle/input/`; el kernel lo encuentra globeando `**/config.json` [MEDIDO: `train_qlora_kaggle.py:35-50`].
- **Limpiar el staging entre runs**: el dataset staging persiste; hay que borrar los `*.jsonl` viejos o la nueva versión arrastra basura [MEDIDO: `run_kaggle_training.py:65-70`].

### 5.2 Cuota 2026 y elección de acelerador

- **30 h/semana de GPU, sesiones de hasta 12 h** [LITERATURA: Kaggle docs/product-feedback 2023-2026, vigente].
- **2×T4 consume cuota a la MISMA tasa que 1 GPU** (1 h de sesión 2×T4 = 1 h de cuota) [LITERATURA: product-feedback/361104]. La segunda T4 es "gratis" en cuota, pero para entrenar el 3B QLoRA **no la usamos en paralelo de datos**: lo único MEDIDO es que DataParallel 2×T4 fue más lento que 1 GPU en el régimen del **tiny** (9.5M params, overhead-bound) [MEDIDO: memoria cognia-x-velocidad-entreno.md, XSPEED]. Extender esa conclusión al **QLoRA del 3B es una PREDICCIÓN, no un hecho medido** — el régimen cambia (más cómputo por step, menos overhead relativo) [PREDICCIÓN → mini-test DDP en E0/E1, ~1h; V3-f6]. Uso ya validado de la 2ª T4: correr la eval del checkpoint anterior en paralelo al training (`CUDA_VISIBLE_DEVICES` 0/1) [PREDICCIÓN E-OPS-1: verificar que no compite por CPU/RAM].
- **P100 vs T4 para QLoRA**: la P100 tiene más bandwidth (732 vs 320 GB/s) pero sin tensor cores (sm_60); la T4 tiene 65 TFLOPS fp16 en tensor cores y QLoRA es compute-bound en los GEMM fp16 del forward NF4→dequant→matmul, así que la T4 gana [LITERATURA: specs NVIDIA; PREDICCIÓN → E-OPS-2 para el número exacto]. bitsandbytes distribuye wheels con sm_60 y NF4 requiere CC≥6.0, así que la P100 funciona **hoy** [LITERATURA: docs bitsandbytes], **pero solo mientras el image de Kaggle use CUDA ≤12.x** — los builds de bitsandbytes para CUDA 13.0+ eliminan Pascal, y cuando el image migre la cola-B P100 muere silenciosamente; el kernel debe chequear `torch.version.cuda` + `torch.cuda.get_device_capability()` al arrancar y abortar con mensaje claro en vez de fallar en el load 4-bit. Además **Unsloth exige CC≥7.0 → P100 NO soportada, T4 sí** [LITERATURA: Unsloth requirements]. **Decisión: T4 única para entrenar; P100 solo como cola alternativa (sin Unsloth, con el check de arriba) si la de T4 está saturada.**

### 5.3 Protocolo checkpoint/resume entre sesiones (el mecanismo central)

Con ≈16.8M tokens/sesión de 11 h en el piso [DC-7/DC-8] y un plan multi-etapa de decenas de millones de tokens, **ninguna etapa cabe en una sola sesión**: el resume es el modo normal, no la excepción.

**Qué guardar** (resume bit-a-bit): `adapter/` (`save_pretrained` PEFT), `optimizer.pt`, `scheduler.pt`, `rng_state.pt` (torch CPU+CUDA, numpy, random), `trainer_state.json` (global_step, epoch, tokens vistos, mejor loss). Tamaño: LoRA r=16 sobre q/k/v/o+MLP del 3B ≈ 30-120 MB; con estados de Adam (contabilidad de la Parte 1: 8B fp32) el checkpoint completo queda **< 500 MB** [PREDICCIÓN → medir en el primer checkpoint real, E-OPS-3].

**Cadencia**: checkpoint cada 30 min de pared (no cada N steps fijos — el tok/s varía con la config real). Batch efectivo 16×1024 = 16,384 tok/step: al piso 424 tok/s son ~38.6 s/step → **~47 steps/checkpoint**; si E0 confirma el objetivo ≥800 tok/s, ~20.5 s/step → **~88 steps/checkpoint** [CALCULADO desde DC-7]. `save_total_limit=2` acota `/kaggle/working` (**20 GB** [LITERATURA: Kaggle docs]) — sobra, pero el merge final fp16 del 3B (~6 GB, Parte 1) también sale por ahí: no acumular.

**Auto-stop antes del kill de 12 h**: el kernel arranca `t0 = time.monotonic()` y corta el loop de training en `BUDGET_S = 11.0*3600`, guarda el checkpoint final y termina con exit 0. Razón: no está garantizado que el output quede descargable si Kaggle mata la sesión en el límite — tratarlo como pérdida total [PREDICCIÓN conservadora; la evidencia del repo solo cubre kernels que completaron].

**El puente entre sesiones = un Kaggle Dataset versionado** (`anthuananthuan/cognia-ckpt`), siguiendo el patrón de `ensure_dataset()` del repo:

1. Al completar el kernel N: local corre `kaggle kernels output anthuananthuan/cognia3b-train -p checkpoints/sesion_N/`.
2. Local publica: copia `checkpoint-last/` al staging, escribe `dataset-metadata.json` (`id: anthuananthuan/cognia-ckpt`) y corre `kaggle datasets version -p <staging> -m "sesion N, step X, loss Y"`. Primera vez: `datasets create`. La cuota de datasets **privados es 200 GB TOTAL por cuenta** (no por dataset) [LITERATURA: Kaggle product-feedback/512322 "Doubling of Private Quota"] — cada `version` suma a ese total, así que **borrar versiones viejas de `cognia-ckpt`** cada ~10 sesiones.
3. El kernel N+1 lleva `"dataset_sources": ["anthuananthuan/cognia-ckpt"]`; al arrancar globea `/kaggle/input/cognia-ckpt/**/trainer_state.json` — si existe, carga adapter+optimizer+scheduler+RNG y sigue desde `global_step`; si no, arranca de cero. El mismo kernel sirve para sesión 1 y para resume (cero branching manual).

Alternativa evaluada y descartada: publicar el dataset desde ADENTRO del kernel (kaggle API + secret). Rompe el principio del repo de credenciales solo locales; el costo del round-trip local es ~5 min.

### 5.4 Base 3B vía Kaggle Models

Ya montado y probado: `qwen-lm/qwen2.5-coder/transformers/3b-instruct/1` [MEDIDO: `model_sources` en los runners] — es la base primaria DC-1. Alternativa en el hub: **`metaresearch/llama-3.2`** (1B/3B, requiere aceptar licencia) [LITERATURA: llama.com/docs + kaggle.com/models/metaresearch/llama-3.2]. **SmolLM3-3B (DC-2) y Phi-4-mini: presencia en Kaggle Models NO confirmada** — solo Phi-3 tiene entrada oficial de Microsoft; Phi-4-mini solo aparece en datasets/notebooks de terceros, nunca como Kaggle Model oficial. Si el gate de migración E6 activa SmolLM3 y no está en el hub, plan B: descargar de HF Hub dentro del kernel (internet ON, ~6 GB) y cachear como versión del dataset ckpt para no re-descargar. **Decisión por default: Qwen2.5-Coder-3B-Instruct** (DC-1) — es la base del CLI local (GGUF Q4_K_M) y del formato ACCION ya fine-tuneado; cambiar de base invalida adapters y evals previos.

### 5.5 Pines de versiones

- `bitsandbytes>=0.46.1` — el único pin con evidencia dura del repo [MEDIDO: fix 8b67ac3].
- transformers/peft/trl/datasets: el image de Kaggle los trae y cambia sin aviso. Protocolo: (1) el kernel imprime `pip freeze | grep -E "transformers|peft|trl|bitsandbytes|torch"` al arrancar y lo guarda en `results.json` (`env`); (2) tras la primera sesión buena, congelar esos números exactos con `pip install transformers==X peft==Y trl==Z`. Pinear a ciegas versiones de memoria sería inventar — el freeze de la sesión 1 es la fuente de verdad [PREDICCIÓN E-OPS-4].
- Unsloth: instalar pineado a la versión que pase la sesión 1 (T4 sm_75, CC 7.0 soportada); el path bnb+peft "vainilla" del kernel actual queda como fallback ya probado [MEDIDO: el path vainilla corrió; PREDICCIÓN: Unsloth en el image actual — arbitrado en E0, DC-5].
- `PYTHONUTF8=1` en el kernel además del CLI local [MEDIDO: lección repo].

### 5.6 Telemetría del kernel (estilo repo: un `results.json` plano)

Siguiendo `xspeed_results.json` [MEDIDO: `run_kaggle_xspeed.py:80-104`], cada sesión escribe `/kaggle/working/results.json`:

```json
{"session": 7, "resumed_from_step": 3210, "final_step": 5650,
 "tok_per_s_mean": 480, "tokens_seen_total": 19100000,
 "vram_peak_gb": 7.1, "loss_curve": [[3210, 1.82], [3310, 1.79], ...],
 "eval_smoke": {"held_out_ppl": 6.1, "accion_10q": 0.90},
 "env": {"transformers": "…", "bitsandbytes": "…"}, "wall_h": 11.0}
```

`eval_smoke` es telemetría de diagnóstico rápido (el baseline de 10 preguntas), NUNCA el gate de aceptación — los gates canónicos G1-G5 (DC-6, Parte 3) corren aparte contra la suite N=100. Implementación: un `TrainerCallback` que en cada `on_log` appendea `(global_step, loss)` y cada checkpoint vuelca el JSON (escritura atómica: tmp + rename). VRAM: `torch.cuda.max_memory_allocated()/2**30` tras `reset_peak_memory_stats()` post-warmup. tok/s: `tokens_seen/elapsed` excluyendo el load del modelo, reportado como tok/s **útiles** (no-padding, matiz de DC-7).

### 5.7 Plan semanal tipo (margen real, no 30 h optimistas)

| Sesión | GPU | Horas | Qué corre |
|---|---|---|---|
| L (lunes) | T4 | 11 | Etapa en curso (resume del ckpt), auto-stop 11h, publica ckpt |
| J (jueves) | T4 | 11 | Continúa la etapa; si termina, corre merge NF4→fp16 + export (DC-9) |
| S (sábado) | T4 o 2×T4 | 4-5 | Eval del ckpt semanal (held-out + smoke ACCION), GGUF si hubo merge |
| margen | — | 2-3 | Re-runs por kernel muerto / cola (medido: 4/10 fallos en XHUNDRED, §5.1) |

Total 28-30 h — **dentro de la cuota de 30 h con margen real** (antes: 29-31 h, sin margen) [V1-f10]. Si la semana no tiene margen (cuota ya consumida), la sesión del sábado se recorta o se salta, nunca la de re-runs. Rendimiento esperado: 2 sesiones de training/semana ≈ **33.6M tokens/semana** al piso 424 tok/s [DC-8]; si E0 confirma el objetivo ≥800, hasta **~63M tokens/semana** [CALCULADO desde DC-7]. La descarga del GGUF (~2 GB) sale por `kernels output` normal.

### 5.8 Riesgos operativos y mitigaciones

| Riesgo | Evidencia | Mitigación |
|---|---|---|
| Kernel muerto a las 12h, output perdido | límite documentado [LITERATURA] | auto-stop a 11h + checkpoint cada 30 min (§5.3) |
| pip flaky / bnb viejo / torchao rompe peft | [MEDIDO: fix 8b67ac3; `train_tooluse_kaggle.py:91-105`] | cascada `_ensure_bitsandbytes` + desinstalar torchao antes de importar peft |
| Kernel cae a CPU silenciosamente | [MEDIDO: v1/v2 corrieron en CPU] | `machine_shape` + `assert torch.cuda.is_available()` al inicio, abortar (no degradar a un modelo chico) |
| Lanzamiento GPU falla (cola/timeout) | [MEDIDO: 4/10 fallos, XHUNDRED] | retry automático + `--push-only` con poll desacoplado; ventana alternativa madrugada UTC |
| Dataset privado llega al tope 200 GB TOTAL | [LITERATURA: product-feedback/512322] | prune de versiones viejas de `cognia-ckpt` cada ~10 sesiones |
| Versiones del image cambian y rompen el resume | rotación conocida del image | pin post-sesión-1 (§5.5) + `env` en results.json |
| lr alto sobreajusta (deriva a chino) | [MEDIDO: HECHOS_MEDIDOS, run Colab 2e-4] | lr 5e-5 default de producción; eval con held-out de conocimiento, no solo el smoke de 10 preguntas |
| CLI local revienta en cp1252 | [MEDIDO: xspeed] | `PYTHONUTF8=1` en el subprocess del wrapper `kaggle()` (portado a los 3 runners) |
| DDP 2×T4 asumido más lento sin validar en el 3B | [MEDIDO solo en el tiny; PREDICCIÓN para 3B, V3-f6] | mini-test DDP ~1h en E0/E1 antes de descartarlo definitivamente para QLoRA |

**Experimento de arranque (E-OPS-0)**: una sesión corta (~2h) que ejecuta el ciclo completo checkpoint→publish→resume con 1000 steps dummy, verificando que `global_step`, loss y RNG continúan exactos. Es el test de integración del protocolo antes de gastar horas reales de la etapa 1.

#### Claims etiquetados (Parte 5)
- [MEDIDO] El backend de Kaggle ignora `enable_gpu`; el campo efectivo es `machine_shape` — evidencia: `run_kaggle_training.py:99-102`, fix 331db7c.
- [MEDIDO] bitsandbytes del image es viejo (requiere `pip install -U bitsandbytes>=0.46.1`, importar transformers/peft DESPUÉS) y torchao 0.10 rompe peft — evidencia: `train_qlora_kaggle.py:53-78` (fix 8b67ac3), `train_tooluse_kaggle.py:91-105`.
- [MEDIDO] `PYTHONUTF8=1` obligatorio en el CLI kaggle en Windows — evidencia: `run_kaggle_xspeed.py:30-34`.
- [MEDIDO] 4 de 10 lanzamientos GPU fallaron en XHUNDRED — evidencia: memoria cognia-xhundred-resultado.
- [LITERATURA] Cuota Kaggle 30h/semana, sesiones máx 12h; 2×T4 consume cuota a la misma tasa que 1 GPU — evidencia: Kaggle docs + product-feedback/361104.
- [MEDIDO solo en el tiny / PREDICCIÓN para el 3B] DataParallel 2×T4 fue más lento que 1 GPU en el régimen overhead-bound del tiny (9.5M); extender esto al QLoRA del 3B NO está medido — evidencia: memoria cognia-x-velocidad-entreno.md; falsador: mini-test DDP en E0/E1 (V3-f6).
- [LITERATURA] Unsloth requiere CC≥7.0 (T4 sí, P100 no); bitsandbytes soporta P100 (CC≥6.0) SOLO mientras el image use CUDA ≤12.x — evidencia: Unsloth docs; bitsandbytes installation docs.
- [LITERATURA] Datasets privados de Kaggle: 200 GB de cuota TOTAL por cuenta (no por dataset), las versiones acumulan — evidencia: product-feedback/512322 "Doubling of Private Quota" (corrige la cita previa a product-feedback/195163, V1-f11).
- [PREDICCIÓN] Un checkpoint de resume completo (adapter LoRA r=16 + optimizer + scheduler + RNG) del 3B queda bajo 500 MB — evidencia: aritmética Parte 1; a medir en la sesión 1 (E-OPS-3).
- [PREDICCIÓN] El kernel debe auto-frenarse a las 11h porque el output de un kill a las 12h no está garantizado descargable — evidencia: límite documentado [LITERATURA]; sin verificación directa en el repo.
- [LITERATURA] Llama-3.2 disponible en Kaggle Models vía `metaresearch/llama-3.2`; SmolLM3 y Phi-4-mini NO confirmados (solo Phi-3 oficial) — evidencia: llama.com/docs + kaggle.com/models/metaresearch/llama-3.2 (V1-f7, P5 correcto, P6 corregido para coincidir).
- [MEDIDO] lr 2e-4 sobreajusta el 3B en destilación (deriva a chino); lr 5e-5 + dropout 0.1 ganó — evidencia: HECHOS_MEDIDOS.md, run Colab.
- [CALCULADO] Cadencia de checkpoint: ~47 steps (al piso 424 tok/s) a ~88 steps (al objetivo ≥800 tok/s) por cada 30 min de pared, con batch efectivo 16,384 tok/step — evidencia: aritmética desde DC-7.
- [MEDIDO] El patrón operativo probado es staging local → `kernel-metadata.json` → `kaggle kernels push` → poll 60s → `kaggle kernels output`, `model_sources` formato `{owner}/{slug}/{framework}/{instance}/{version}` — evidencia: los 3 runners del repo; kernels GPU reales corrieron 1-3 julio 2026.

### Preguntas abiertas
- ¿SmolLM3-3B existe como Kaggle Model montable? Verificar con `kaggle models list -s smollm3` antes de E6.2; plan B = descarga HF con internet ON, cacheada en el dataset ckpt.
- ¿El output de `/kaggle/working` sobrevive si Kaggle mata el kernel exactamente a las 12h? (asumimos que NO por seguridad; probarlo costaría una sesión sacrificada).
- ¿Unsloth instala y corre limpio sobre el image de Kaggle vigente, y cuánto tok/s gana vs el path vainilla bnb+peft en T4? (E-OPS-4, arbitrado junto con DC-5 en E0).
- ¿DDP 2×T4 acelera o degrada el QLoRA del 3B (a diferencia del tiny, donde fue más lento)? Mini-test de ~1h en E0/E1 antes de descartarlo (V3-f6).
- ¿Correr eval en la 2ª T4 en paralelo al training degrada el tok/s por contención de CPU/RAM del kernel? (E-OPS-1).
- ¿Cuánto tarda el merge NF4→fp16 (DC-9) + conversión GGUF Q4_K_M dentro del kernel, y entra en los 20 GB de `/kaggle/working` junto al checkpoint? (merge fp16 ~6 GB + GGUF ~2 GB + ckpt <0.5 GB: debería, pero no está medido).

---

## Parte 6 — Elección de la base 3B (con override editorial DC-1/DC-2/DC-3)

### 6.0 Por qué esta decisión es la más cara de revertir

Toda la ventana viable (Parte 0 §0.4) es adaptación profunda sobre una base abierta: el 100% del cómputo de Kaggle se invierte en mover *esa* base, y un derivado de una base no-comercial es no-comercial para siempre — no se arregla con más GPU-horas. Cognia se comercializa (paquete `cognia-ai` en PyPI, 3.8.x publicado), así que el checkpoint `cognia-3b` es, en potencia, un artefacto distribuido de un producto comercial. Esta parte resuelve esa tensión con las tres decisiones ya congeladas en la tabla ejecutiva (DC-1/DC-2/DC-3): esta sección **justifica esas decisiones y detalla lo que faltó en el borrador original**, no propone una recomendación alternativa.

Hallazgo que sostiene el override: Qwen2.5-Coder-3B-Instruct (y Qwen2.5-3B-Instruct) están bajo **Qwen Research License**, cuyo texto (LICENSE en HF) dice *"create derivative works … FOR NON-COMMERCIAL PURPOSES ONLY"*, con Non-Commercial definido como *"for research or evaluation purposes only"* — uso comercial requiere licencia de Alibaba [LITERATURA: huggingface.co/Qwen/Qwen2.5-3B/blob/main/LICENSE, verificado 2026-07-06; mismo texto en Qwen2.5-Coder-3B-Instruct-GGUF]. Este hallazgo es real y es exactamente lo que DC-1 ya declara como caveat vinculante de `cognia-3b` v1: artefacto de investigación/uso personal, no distribuible.

### 6.1 Candidatos y datos verificados (estado 2025-2026)

| Modelo | Params reales | Licencia | ¿Publicar comercial? | Español | Código/tool-use | GGUF | Rol en el plan |
|---|---|---|---|---|---|---|---|
| **Qwen2.5-Coder-3B-Instruct** | 3.09B | Qwen Research License | **NO** (v1 investigación/uso personal) | Bueno | Excelente: ACCION 0.24→0.86 con scaffold [MEDIDO memoria cognia-mom-agente-andamiaje] | Maduro, oficial | **DC-1: primaria v1** |
| Qwen2.5-3B-Instruct | 3.09B | Qwen Research License | NO | Bueno | Medio | Maduro | Hermano de DC-1 (424 tok/s medidos ahí, Parte 0 §0.4) |
| **SmolLM3-3B** | 3.08B | **Apache-2.0** | **SÍ** | **Nativo declarado** (en/fr/es/de/it/pt) [LITERATURA: HF SmolLM3 card, 2025] | Bueno para 3B; tool-calling soportado; receta pública (11.2T tok) | Oficial (ggml-org/SmolLM3-3B-GGUF) | **DC-2: candidata v2, arbitrada en E6** |
| Qwen3-4B-Instruct-2507 | 4.0B (3.6B non-emb) | **Apache-2.0** | Sí, pero fuera del goal (≠3B) | Muy bueno (119 idiomas declarados) | Bueno-muy bueno — **disputa de benchmark sin resolver, ver §6.5** | Maduro desde abr-2025 | **DC-3: futuro `cognia-4b`, fuera de este goal** |
| Llama-3.2-3B-Instruct | 3.21B | Llama 3.2 Community License | Sí, pero el derivado debe llamarse "Llama-…" [LITERATURA: llama.com/llama3_2/license — *"you shall also include 'Llama' at the beginning of any such AI model name"*] + "Built with Llama" + tope 700M MAU | Bueno (8 idiomas) | Medio | Maduro | Descartado: incompatible con la marca `cognia-3b`/`cognia-4b` |
| Phi-4-mini-instruct | 3.8B (no 3B) | MIT | Sí | Medio (sesgo inglés) | Fuerte razonamiento/math | Soportado (llama.cpp #12091) | Descartado: cero continuidad de ecosistema; **no confirmado en Kaggle Models** (solo Phi-3 oficial) [corrección V1-f7: P5 tenía razón, P6 sobreafirmaba] |
| Gemma-3-4B-it | 4.3B | Gemma Terms of Use | Riesgoso: flow-down de restricciones + derecho unilateral de Google a restringir uso remotamente [LITERATURA: ai.google.dev/gemma/terms] | Muy bueno | Medio | Maduro | Descartado: riesgo legal inaceptable sin equipo legal |

Disponibilidad Kaggle: la familia `qwen-lm` (2.5 y 3) está confirmada en Kaggle Models; SmolLM3 se baja de HF vía `enable_internet` (mecanismo ya usado por `_find_model_dir`, `cognia_v3/training/kaggle/train_qlora_kaggle.py:94` [MEDIDO]); ninguno bloquea el pipeline.

### 6.2 El eje que la tabla no captura: costo de invalidación (y por qué DC-1 lo minimiza)

Todo el trabajo empírico del repo se midió sobre Qwen2.5-Coder-3B-Instruct: ACCION 0.24→0.86 con scaffold [MEDIDO memoria cognia-mom-agente-andamiaje], CoT por turno 0.3125→0.8125 [MEDIDO memoria cognia-reasoning-cot-dirigido], prompt-evolution v1 0.80 [MEDIDO results_promptevo_ap_fast_v3]. Al fijar Qwen2.5-Coder-3B-Instruct como primaria (DC-1) en vez de migrar de entrada, **el override evita pagar ese costo de invalidación dos veces**: la calibración absoluta y los mecanismos (few-shot concreto > abstracto, CoT por turno, gates de no-regresión) siguen siendo válidos sin re-medir. El costo se paga una sola vez, y de forma controlada, en el gate de migración a SmolLM3 (E6, §6.6) — con el mismo tokenizer/template no disponible ahí (SmolLM3 usa template propio), por lo que E6 incluye explícitamente portar pero no un rediseño de los mecanismos.

### 6.3 Por qué el override (DC-1/DC-2) y no la recomendación original del borrador

El borrador de esta parte recomendaba Qwen3-4B-Instruct-2507 como primaria, apoyado en su licencia Apache-2.0 y benchmarks superiores. El override editorial lo revierte por dos razones que dominan sobre "mejor benchmark aislado": (1) **el goal exige un modelo de ~3B llamado `cognia-3b`**, y Qwen3-4B son 4.0B — usarlo como primaria obliga a renombrar el producto antes de tener un solo checkpoint entrenado; (2) **continuidad total del repo** (DC-1): Qwen2.5-Coder-3B-Instruct es la base sobre la que ya corrieron las 3 mediciones de QLoRA en T4 (Parte 0 §0.4, `HECHOS_MEDIDOS.md`), el CLI GGUF, y el andamiaje ACCION — mover la base primaria a un modelo nunca probado en este stack es apostar la decisión más cara del documento a literatura de terceros, exactamente lo que §6.2 muestra que es evitable. Qwen3-4B no se descarta: queda como **DC-3, opción futura `cognia-4b`, fuera de este goal**. SmolLM3-3B, en cambio, sí resuelve el problema de licencia sin cambiar de clase de tamaño (3.08B) — por eso es la candidata v2 (DC-2), arbitrada por gate y no impuesta de entrada, porque su tool-use de fábrica y su ecosistema de tokenizer/template son inferiores a Qwen en este repo.

### 6.4 Implicación de licencia para el producto final

- **`cognia-3b` v1 (Qwen2.5-Coder-3B-Instruct, DC-1):** artefacto de investigación/uso personal bajo Qwen Research License. No se distribuye comercialmente sin licencia escrita de Alibaba. Es el que se entrena y verifica primero (Parte 7).
- **`cognia-3b` v2 (SmolLM3-3B, DC-2, condicional a E6):** si el gate de migración pasa, re-correr el pipeline completo (DC-11, §6.7) sobre esta base produce el artefacto Apache-2.0 distribuible/comercializable, con NOTICE de atribución a HuggingFace.
- **`cognia-4b` (Qwen3-4B-Instruct-2507, DC-3, fuera de este goal):** Apache-2.0, sin restricción de nombre ni MAU — opción de producto separada, condicionada a resolver la disputa de benchmark de §6.5 antes de comprometer GPU-horas.

### 6.5 Qwen3-4B como opción futura (`cognia-4b`): la disputa de verificación sin resolver

DC-3 saca a Qwen3-4B-Instruct-2507 del goal de `cognia-3b` por tamaño (4.0B ≠ 3B), pero además hay un problema de evidencia que hay que dejar registrado antes de activarlo como producto separado: dos verificaciones independientes de este documento leyeron **números distintos en la misma model card**. Una verificación (V1) reporta BFCL-v3 = 61.9 y MultiIF = 69.0 (y señala que 71.2/77.3 corresponden al Qwen3-235B-A22B-Instruct-2507, no al 4B). Otra verificación (V3) reporta BFCL-v3 = 71.2 y MultiIF = 77.3 confirmados en la misma HF card. **No resuelto** — no se dirime aquí; queda como bloqueo explícito: si `cognia-4b` se activa como programa, el primer paso es re-verificar los dos números contra la card vigente en ese momento (las model cards de HF se editan) antes de escribir cualquier claim comparativo. Mientras tanto, ningún claim de este documento depende de esa cifra para `cognia-3b` v1/v2.

### 6.6 Experimentos que esta parte compromete (gate de migración a SmolLM3, DC-2)

- **E6.1 (gate de migración, CPU local, ~2h):** bajar SmolLM3-3B GGUF oficial (ggml-org), correrlo en el CLI de Cognia (llama.cpp pin b9391) y evaluar contra el **slice BFCL held-out (50 ítems, checker AST, umbral 0.80 [MEDIDO] — regla de instrumentos §0.0/Parte 3)**, no una "suite de 24 casos" (ese instrumento no existe en el repo). Criterio: ≥0.80 en el slice y tok/s ≥6 (comparado contra el techo actual ~8 tok/s del 3B [MEDIDO exp021/CYCLE34]).
- **E6.2 (smoke QLoRA en T4, 1 sesión):** adaptar el kernel base-agnóstico (§6.7) cambiando `MODEL` y `target_modules` a los nombres de SmolLM3, 500 steps NF4+fp16, medir VRAM pico y tok/s reales contra el ancla de 424 tok/s (Parte 0 §0.4). Criterio: VRAM <14 GB (contra el techo de 15.6 GB [MEDIDO], no 16), tok/s ≥300 (70% del ancla; SmolLM3 y Qwen2.5-3B tienen arquitectura comparable en orden de magnitud).
- **E6.3 (español, CPU local):** 20 prompts en español (conversación/código/tool-use) juzgados a ciegas: SmolLM3-3B vs `cognia-3b` v1 (Qwen2.5-Coder-3B ya adaptado).

**Preguntas abiertas** (Anexo B): calidad real de SmolLM3 en tool-calling con su template propio (no hay benchmark público comparable a BFCL para ese formato); si el modo `/think` residual de SmolLM3 interfiere con el formato ACCION bajo fine-tuning; si `cognia-4b` se activa, resolver §6.5 antes de fijar cualquier número comparativo.

### 6.7 Diseño base-agnóstico (soporte de DC-11)

DC-2 y DC-3 solo son baratos de ejecutar si el pipeline no está cableado a Qwen2.5. Por eso DC-11 fija como requisito transversal: datos, kernel de entrenamiento, gates y merge/GGUF parametrizados por una única fuente de verdad por base (`MODEL`, chat template, `target_modules`, tokenizer), de forma que re-correr todo el programa (Parte 7) sobre SmolLM3-3B (E6) o, más adelante, sobre Qwen3-4B (`cognia-4b`) sea un cambio de configuración, no un rediseño. El costo de este requisito ya está pagado en parte: `train_tooluse_kaggle.py` y `train_qlora_kaggle.py` ya centralizan `MODEL` como constante en una línea [MEDIDO, líneas citadas en Parte 2]; falta extraer `target_modules` y el template de chat a la misma configuración antes de E6.1.

#### Claims etiquetados (Parte 6)
- [LITERATURA] Qwen2.5-Coder-3B-Instruct / Qwen2.5-3B-Instruct: Qwen Research License, derivados solo no-comerciales — huggingface.co/Qwen/Qwen2.5-3B/blob/main/LICENSE, verificado 2026-07-06.
- [LITERATURA] SmolLM3-3B: Apache-2.0, 3.08B, español nativo declarado (en/fr/es/de/it/pt), GGUF oficial ggml-org — HF SmolLM3 card, 2025.
- [LITERATURA] Llama 3.2 Community License exige "Llama" al inicio del nombre del derivado + "Built with Llama" + tope 700M MAU — llama.com/llama3_2/license.
- [LITERATURA] Gemma Terms of Use: comercial permitido pero con flow-down de restricciones y derecho unilateral de Google a restringir uso remotamente — ai.google.dev/gemma/terms.
- [MEDIDO] ACCION 0.24→0.86 con scaffold sobre Qwen2.5-Coder-3B-Instruct — memoria cognia-mom-agente-andamiaje, corrida 2026-07-03.
- [MEDIDO] Phi-4-mini-instruct NO confirmado en Kaggle Models (solo Phi-3 oficial de Microsoft) — corrección de V1-f7 sobre la sobreafirmación original de esta parte.
- [DISPUTA no resuelta] Qwen3-4B-Instruct-2507: V1 reporta BFCL-v3 61.9/MultiIF 69.0 en su model card; V3 reporta 71.2/77.3 en la misma card. No se dirime en este documento; bloqueante si `cognia-4b` (DC-3) se activa (§6.5).
- [PREDICCIÓN → E6.1/E6.2] SmolLM3-3B alcanza ≥0.80 en el slice BFCL held-out y ≥300 tok/s de QLoRA en T4 (70% del ancla de 424 tok/s).

---

## Parte 7 — Programa experimental E0..E6 + E-MIX (presupuestos re-anclados a 424 tok/s)

### 7.0 Principios del programa (pre-registro obligatorio; gates = referencia a Parte 3, DC-6)

Regla del repo, ya demostrada en XHUNDRED y XSPEED [MEDIDO: gates congelados en `cognia_x/construccion/`, memoria `cognia-xhundred-resultado`]: **los gates se congelan ANTES de lanzar el kernel**. Cada experimento declara hipótesis, predicción numérica, config exacta, presupuesto y umbral de aborto; el resultado se registra aunque refute la predicción. Infraestructura reusada: runner `run_kaggle_tooluse.py --push-only` + monitoreo, conversión GGUF con el tag b9391 [MEDIDO: deploy tooluse v4 vía `LLAMA_LORA_PATH`], y el kernel de perfilado `cognia_v3/training/cognia3b/e0_perfil_kernel.py` (§7.1).

**Gates: esta parte NO define G1-G5 — son los de la Parte 3 §3.3 (DC-6), única tabla canónica.** Recordatorio de sus nombres para no reintroducir ambigüedad: **G1** no-regresión general (100 ítems, banda −4pp); **G2** ganancia objetivo por etapa (+10pp, N=100, McNemar, potencia real 73.3%); **G3** identidad Cognia (20 prompts, ≥18/20); **G4** integridad merge+GGUF (200 ítems + perplexity, en el CLI real); **G5** español (25 ítems, accuracy + langid). El **baseline de 10 preguntas** embebido en los kernels (`BASELINE_QUESTIONS`) es **smoke del kernel, JAMÁS gate** (con N=10 la potencia para +30pp es 5.5% — Parte 3 §3.4): sirve solo para detectar que el kernel no rompió nada obvio antes de correr los gates de verdad. **Pre-requisito antes de E1** (no antes de E0, que no usa G1-G5): P0-ii/DC-10 — suites de 100 ítems por gate congeladas por hash en git.

### 7.1 E0 — SMOKE + PERFIL (ya committeado y LANZADO)

**Estado**: kernel escrito y lanzado — `e0_perfil_kernel.py` (grilla A..J, 10 configs) + `unsloth_probe.py`, corre solo, GPU única (`CUDA_VISIBLE_DEVICES=0`, el 3B partido entre 2×T4 en un intento previo invalidaba el perfil single-T4). **Predicciones pre-registradas en su docstring [PREDICCIÓN]**: P-E0a pesos NF4+DQ = 2.0-2.4 GB alocados tras el load (contra 2.06 GB [CALCULADO] de la Parte 0/1); P-E0b `paged_adamw_8bit` libera ≥0.15 GB vs AdamW fp32 y permite subir micro-batch sin OOM; P-E0c la mejor config útil (packing + micro-batch alto) alcanza **≥800 tok/s útiles** (no-pad); si <500 → redimensionar corpora del programa a la mitad; P-E0d Unsloth instala en T4/sm_75 y da ≥1.3× con loss equivalente (±1%) vs la mejor config transformers+PEFT — si falla o <1.3×, el runtime queda en transformers+PEFT (DC-5). **Sanity check**: la config A reproduce el régimen de p2k2 (r16 all-linear, seq1024, mb4+GC, sin packing) — si no cae en 300-550 tok/s, el harness está mal, no el modelo. **Gate de éxito del kernel** (smoke, no G1-G5): ≥8/10 configs sin OOM/colgarse + JSON completo. **Presupuesto**: 2 GPU-h. Incluye 1 mini-test DDP 2×T4 (~parte del presupuesto, no extra) — lo medido en contra es solo el tiny overhead-bound (memoria `cognia-x-velocidad-entreno`); extender a QLoRA-3B es [PREDICCIÓN], gate ≥1.5× o se descarta sin reabrir (alineado con Parte 5 §5.2, V3-f6).

### 7.2 E1 — ABLACIÓN DE MÉTODO (columna vertebral: precisión + capacidad)

**Hipótesis**: (a) fp16-LoRA es candidato racional a default sobre NF4 dado el margen de VRAM (~10-11 GB fp16 vs ~6.5-7 GB NF4, ambos <15.6 GB — Parte 2 §2.1/§2.4); (b) subir capacidad del adapter (r16 all-linear) mejora sobre el histórico r8 qkvo y reduce la dilución Q4_K_M.
**Brazos** (config ganadora de E0 en batch/seq/packing; dataset ~2k pares mezcla identidad+tool-use, misma seed, 1 epoch, lr 5e-5-1e-4 — rango entre el 5e-5 ganador medido en Colab y el 2e-4 que derivó a chino [MEDIDO]):
1. LoRA r=8 α=16 qkvo, NF4 (control = kernel `train_tooluse_kaggle.py` actual).
2. LoRA r=16 α=32 all-linear (q,k,v,o,gate,up,down), NF4, + LoRA+ ratio 16 (costo 0 [LITERATURA Hayou et al. 2024]).
3. **fp16-LoRA r=16 all-linear** (sin dequant, merge limpio por construcción — Parte 2 §2.4/DC-9).
4. DoRA r=16 all-linear, NF4 [LITERATURA: overhead "orden +50-80% según la evaluación unificada de variantes LoRA, arXiv 2601.22708" — no el ~15% de un borrador previo].
**Predicciones [PREDICCIÓN]**: brazo 2 > brazo 1 en ≥3pp en G2 (McNemar, Parte 3); brazo 3 da 1.2-1.4× tok/s vs brazo 2 con calidad ≥ igual (si se confirma, sube el ancla 424 → Parte 0 §0.4 se actualiza en `MANAGER_LOG.md`, no se reescribe); DoRA cuesta +50-80% de tiempo y su ganancia no es significativa a este N.
**Presupuesto**: 6 GPU-h (4 brazos + evals G2 sobre suite congelada, requiere P0-ii ya cumplido). **Gate**: Pareto calidad/tok/s con G2 como árbitro; empate → gana el más barato de correr. **Decisión (vinculante para E2-E4 y E5)**: el ganador fija (i) precisión NF4 vs fp16-LoRA — determina si E5 necesita el paso de dequant o el merge es limpio por construcción (DC-9); (ii) rank/targets del adapter. No se reabre salvo fallo de gate posterior.

### 7.3 E-MIX — SECUENCIAL-CON-MERGE vs MEZCLA ÚNICA (nuevo, árbitro de DC-4)

**Hipótesis** [PREDICCIÓN, Parte 4 §4.3]: a igual presupuesto de tokens, la mezcla única (estilo Tülu 3) empata o pierde contra secuencial-con-merge en el promedio multi-gate, porque el rollback por etapa (DC-4) vale más que el ahorro de una sola corrida.
**Config**: mismo método ganador de E1, MISMO corpus total (~8-12M tokens, §7.4 abajo) partido en dos corridas paralelas de igual presupuesto: (A) secuencial D1→D2 con merge y gates entre medio (un adelanto de dos etapas de E2/E3); (B) una sola mezcla D1+D2 con las proporciones de Parte 4 §4.3 (tabla de %). Ambas evaluadas con G1+G2+G3 (Parte 3) sobre el mismo held-out.
**Regla de decisión explícita**: si (B) ≥ (A) en el promedio de G1/G2/G3 (dentro de 1pp o gana), **E2/E3/E4 colapsan en una sola corrida de mezcla completa** (D1..D5 juntos, Parte 4 tabla completa) — se recalcula el presupuesto restante sumando lo NO gastado de E2+E3+E4 en una corrida única equivalente. Si (A) > (B), sigue el plan secuencial de §7.4-7.6 sin cambios.
**Presupuesto**: 8 GPU-h. **Aborto**: si ninguna rama pasa G1 (regresión general en ambas) → problema de datos/lr, no de topología — bajar lr a 5e-5 y repetir una vez antes de decidir.

### 7.4 E2 — DATOS ETAPA-1 (identidad + español; solo si E-MIX elige secuencial)

**Hipótesis**: ~18-19k pares ≈ 8-12M tokens (D1+D2 de la mezcla de Parte 4 §4.3, redimensionada al piso) fijan identidad Cognia y español fluido sin regresión general en 1-2 epochs [LITERATURA: LIMA, Zhou et al. 2023 — calidad>cantidad a esta escala].
**Config**: método ganador de E1; seq 2048 con packing (si E0 valida packing+masking juntos); lr 5e-5-1e-4 cosine, warmup 5%; eval cada 500 steps sobre held-out; NEFTune α=5 en esta etapa conversacional (apagado luego en ACCION, Parte 2 §2.6).
**Predicciones [PREDICCIÓN]**: G3 pasa (≥18/20 identidad); G1 pasa (delta ≥ −4pp); G5 pasa (español). A 8-12M tokens × 1-2 epochs, a 424-800 tok/s: 5-20 h teóricas de cómputo puro; **presupuesto asignado 10-14 GPU-h** (incluye evals intermedios, checkpointing y el margen de un retry).
**Aborto**: deriva de idioma en eval intermedio [MEDIDO como modo de fallo real: lr 2e-4 derivó a chino, Parte 2 §2.2] → cortar, bajar lr, reintentar una vez; doble fallo → dataset al tercio de mayor calidad. **Decisión**: checkpoint E2 = base de E3.

### 7.5 E3 — HABILIDADES (tool-use ACCION + código verificado)

**Hipótesis**: escalar `tasks.py` de 42 a ~150 tareas + trayectorias expertas verificadas-por-ejecución (161→1.500-3.000 pares) rompe el techo medido: multi-paso hoy da 0% accept [MEDIDO: memoria `cognia-tooluse-finetune`, `accept_rate` global 0.507 con el 3B].
**Config**: ChatML + completion-only masking (ya en `train_tooluse_kaggle.py`, ausente en `train_qlora_kaggle.py` — Parte 3 P-2); mezcla 60% ACCION / 30% código verificado / 10% replay de E2. Entrena SOBRE el checkpoint E2 mergeado (adapter nuevo, no apilado — DC-4).
**Predicciones [PREDICCIÓN]**: **G2 (Parte 3, suite ACCION de 100 ítems congelada por hash, P0-ii)** pasa: delta ≥+10pp y McNemar p<0.05 (potencia nominal 73.3% a N=100 — un delta puntual 8-12pp que falle exige re-test, no descarte); multi-paso pasa de 0% a ≥40% accept. El +20pp previo (0.80→1.00) fue sobre **N=10** [MEDIDO] — señal direccional, no prueba a esta escala. Pass@1 código: no-caída del 40% [MEDIDO: memoria `cognia-coding-mission-state`].
**Presupuesto**: 10-14 GPU-h (incluye generación/verificación de datos en CPU local, gratis). **Aborto**: si el replay 10% no evita caída de G1 >4pp → subir replay a 25%, reintentar. **Decisión**: pasa G2 → E4; falla multi-paso pero pasa single-step → shippear single-step, mover multi-paso a E6/opcionales.

### 7.6 E4 — RAZONAMIENTO (CoT-por-turno destilado; gate condicional)

**Hipótesis**: el CoT-por-turno que ya funciona por prompting (0.3125→0.8125 [MEDIDO: memoria `cognia-reasoning-cot-dirigido`, `bench_reasoning.py`: **16 ítems + 4 de formato, no 32**]) se puede destilar al adapter sin romper ACCION.
**Config**: 3-5k pares con razonamiento explícito antes de la respuesta, generados por rejection-sampling del propio 3B verificado por oráculo (patrón STaR — único caso donde el 3B self-instruye, D4 en Parte 4 §4.5); 20% replay E2+E3.
**Gate condicional [regla instrumentos]**: la suite de 16 ítems no tiene potencia para un umbral de ganancia (N=16 detecta +20pp solo 9.1% de las veces — Parte 3 §3.4). Si para entonces la suite fue ampliada a N≥50-100 y congelada (P0-ii), **≥0.70 es gate real**; si no, se reporta como **señal indicativa**, no gate. G2 (formato ACCION intacto en ≥95% de emisiones) sigue siendo gate siempre.
**Presupuesto**: 8 GPU-h. **Aborto/decisión**: si destilar CoT rompe ACCION (>5% emisiones malformadas) → NO destilar; CoT queda como scaffolding en `stepwise.py` (ya integrado) y se cierra como "negativo informativo" — no bloquea E5.

### 7.7 E5 — MERGE + GGUF + verificación en el CLI real (define si existe `cognia-3b` v1)

**Config exacta, condicionada al ganador de E1 (DC-9)**: **si NF4 ganó E1** — (1) cargar la base en NF4 con la MISMA `BitsAndBytesConfig` del training; (2) dequantizar a fp16 (patrón ChrisHayduk/Kaitchup, ya citado en Parte 2 §2.8); (3) `merge_and_unload()` sobre ESA dequantización, **nunca** sobre fp16 original sin dequant ni sobre 4-bit directo (peft #2321). **Si fp16-LoRA ganó E1** — merge directo, limpio por construcción, sin paso de dequant. Luego, en ambos casos: (4) `convert_hf_to_gguf.py` tag **b9391** (b9414 dio −37% [MEDIDO: memoria `llama-server-speed-findings`]); (5) `llama-quantize` Q4_K_M; (6) correr **G4 (Parte 3 §3.3)** completo en el CLI local (`python -m cognia`), threads=3.
**Predicciones [PREDICCIÓN]**: el gate vinculante es G4 (delta agregado GGUF-vs-adapter-vivo ≥ −4pp, McNemar sin regresión, perplexity +5%); como señal informal previa se espera retener ≥80% del delta de correct_tool de E3 (vs la dilución parcial medida con `--lora` r=8 sin merge). Velocidad de decode ≈ base Q4_K_M ±5% (techo ~8 tok/s CPU [MEDIDO]).
**Presupuesto**: 2 GPU-h (merge) + CPU local (convert+quantize+eval). **Aborto**: G4 falla → subir r de E3 a 32 en qkvo (re-run parcial, +4 GPU-h) o Q5_K_M como formato de deploy.

### 7.8 E6 y opcionales (fuera del core)

**E6 = el gate de migración a SmolLM3-3B ya definido en la Parte 6 §6.6 (E6.1/E6.2/E6.3, DC-2)** — esta parte NO lo redefine, solo lo referencia como el punto donde el pipeline base-agnóstico (DC-11) se re-corre sobre la candidata distribuible.
**Opcionales** (no bloquean nada, se corren si sobra cuota tras el core):
- **Op-ORPO** [LITERATURA: Hong et al., 2024]: ~3-5k pares de preferencia (verificadas vs rechazadas por el oráculo). Predicción [PREDICCIÓN]: +3-5pp en formato/estilo sin tocar G1. 6 GPU-h.
- **Op-GaLore-límite** [LITERATURA: Zhao et al., 2024]: ¿entra el 3B full-param en 15.6 GB y a qué tok/s? Predicción [PREDICCIÓN, Parte 2 §2.5]: entra (8-9.5 o 14-15 GB según escenario) a <300 tok/s — confirma que QLoRA es el camino, no lo reemplaza. 4 GPU-h.

### 7.9 Presupuesto total y árbol de decisión

| Exp | GPU-h nominal | Con margen ×1.5-2 |
|---|---|---|
| E0 | 2 | 3-4 |
| E1 | 6 | 9-12 |
| E-MIX | 8 | 12-16 |
| E2 | 10-14 | 15-28 |
| E3 | 10-14 | 15-28 |
| E4 | 8 | 12-16 |
| E5 | 2 | 3-4 |
| **Core (E0-E5) + E-MIX** | **≈45-60** | **68-120** |
| Op-ORPO / Op-GaLore | 6 / 4 | 9-16 |

Con cuota de 30 h/semana [MEDIDO: cuenta `anthuananthuan` activa]: **core+E-MIX ≈ 3-4 semanas de cuota**; con opcionales, 4-5. Cada experimento cabe en sesiones ≤12h (Parte 5 §5.1). Si E-MIX (§7.3) resuelve mezcla única, E2+E3+E4 (28-42 GPU-h) colapsan en una corrida única de presupuesto equivalente al restante no gastado — el total no sube.

**Árbol resumido**: E0 falla throughput (<500 útiles) → recortar corpus a la mitad y seguir. E1 elige precisión+método → congelado, define E5. E-MIX decide topología → secuencial (default, sigue el plan) o mezcla única (colapsa E2-E4). E2 falla idioma → 1 retry lr menor → si falla, dataset al tercio. E3 falla multi-paso → shippear single-step. E4 rompe formato → CoT como scaffolding (negativo informativo), o degrada a señal indicativa si la suite de razonamiento no se amplió. E5 falla G4 → r↑ o Q5_K_M. Cada gate PASA → commit+push+`MANAGER_LOG.md`; cada gate FALLA → rama pre-registrada, nunca improvisación post-hoc.

#### Claims etiquetados (Parte 7)
- [MEDIDO] `train_tooluse_kaggle.py` corrió en Kaggle T4 (2026-07-01, con completion-only masking): run1 99 pares ~8min eval **N=6** 83.3→100%; v4 161 pares (=99+64 tras dedup de 163, tiempo no loggeado) eval **N=10** 0.80→1.00. `train_qlora_kaggle.py` (sin masking) corrió en **Colab**, no Kaggle (2026-06-10): lr 5e-5 ganador, lr 2e-4 derivó a chino — evidencia: memorias `cognia-tooluse-finetune` y `kaggle-training-pipeline`.
- [MEDIDO] `bench_reasoning.py` tiene **16 ítems + 4 de formato** (no 32); `tasks.py` tiene **42 tareas** (no 34) — verificado contra el código, consistente con 0.3125=5/16 y 0.8125=13/16.
- [MEDIDO] Pin de llama.cpp = tag b9391 (b9414 dio −37%) — memoria `llama-server-speed-findings`.
- [MEDIDO] Kaggle da 2×T4 pero DataParallel 2×T4 fue más lento que 1 GPU en el régimen del tiny (overhead-bound); extender a QLoRA-3B es pregunta abierta, mini-test ~1h en E0/E1 (Parte 5 §5.2, V3-f6).
- [LITERATURA] DoRA: overhead "orden +50-80%" (arXiv 2601.22708), no ~15% — Liu et al. 2024. NEFTune ayuda estilo/conversación, no capacidad — Jain et al. 2023.
- [LITERATURA] Merge QLoRA correcto = dequantizar NF4 a fp16 y mergear sobre esa (nunca fp16-sin-dequant ni 4-bit directo) — peft #2321, Kaitchup, gist ChrisHayduk (Parte 2 §2.8); E5 lo aplica condicionado al resultado de E1, no como paso fijo.
- [PREDICCIÓN → E-MIX] A igual presupuesto de tokens, secuencial-con-merge ≥ mezcla única en el promedio G1/G2/G3 — si se refuta, E2-E4 colapsan (Parte 4 §4.3).
- [PREDICCIÓN → E1] fp16-LoRA da 1.2-1.4× tok/s vs NF4 con calidad ≥ igual; si se confirma, el ancla 424 tok/s sube (se actualiza en `MANAGER_LOG.md`, DC-7 no se reescribe silenciosamente).
- [PREDICCIÓN → E3] Escalar tasks.py 42→~150 y trayectorias expertas 161→1.500-3.000 lleva multi-paso de 0% a ≥40% accept y pasa G2 (100 ítems, N=10 previo era señal, no prueba).
- [PREDICCIÓN] El programa core+E-MIX cuesta ≈45-60 GPU-h nominales → 68-120 con margen ×1.5-2 = 3-4 semanas de cuota Kaggle (30h/sem), cada experimento dentro del límite de sesión de 12h.

### Preguntas abiertas
- ¿Unsloth instala y corre en T4/sm_75? → E0, gate ≥1.3× y loss equivalente ±1%.
- ¿fp16-LoRA le gana a NF4 en tok/s sin perder calidad? → E1, decide precisión de todo el resto del programa y el procedimiento exacto de E5.
- ¿Secuencial-con-merge o mezcla única? → E-MIX, regla de decisión explícita en §7.3.
- ¿DDP 2×T4 vale la pena para el 3B QLoRA (a diferencia del tiny)? → mini-test ~1h en E0/E1, gate ≥1.5×.
- ¿Cuánto delta pierde el merge fp16→Q4_K_M vs el checkpoint NF4 con r=16? → gate G4 en E5, rama Q5_K_M si falla.
- ¿Destilar CoT-por-turno al adapter rompe ACCION? → E4, umbral >5% emisiones malformadas; gate real solo si la suite de razonamiento se amplió a N≥50-100 antes (P0-ii).
- ¿El 10% de replay alcanza entre E2→E3→E4, o hace falta 25%? → medido por G1/G3 en cada etapa, rama pre-registrada.

---

## Anexo A — Registro de verificación adversarial (40 findings: V1=14, V2=11, V3=15)

Tres agentes verificaron el borrador de forma independiente contra el repo real, la web y la
aritmética. Cada fila: hallazgo → resolución en el documento congelado. "DC-Z" = decisión de la
tabla ejecutiva; "Parte X" = corrección integrada en esa parte; "no aplica" = juicio editorial
razonado. Los IDs siguen el orden de aparición dentro de cada JSON (`verificacion_V{1,2,3}.json`).

| ID | Sev | Hallazgo | Resolución |
|---|---|---|---|
| V1-f1 | crítico | Qwen3-4B: BFCL/MultiIF citados 71.2/77.3, model card real dice 61.9/69.0 | DC-3: opción futura `cognia-4b` fuera del goal; Parte 6 §6.5 registra la disputa V1-vs-V3 como NO RESUELTA, no bloquea `cognia-3b` |
| V1-f2 | crítico | G1-G5 con dos definiciones incompatibles (P3 vs P7) | DC-6: Parte 3 es la única tabla de gates; Parte 7 debe re-referenciarla (pendiente: Parte 7 final aún no escrita — ver conflicto abajo) |
| V1-f3 | crítico | E5 prescribía merge sobre fp16 original, prohibido por P2/P3 | DC-9: dequantizar NF4→fp16 con la MISMA BitsAndBytesConfig, mergear sobre esa (Parte 2 §2.8, Parte 3 D-5) |
| V1-f4 | mayor | Tres topologías de entrenamiento incompatibles (P2/P3 vs P4 vs P7) | DC-4: secuencial-con-merge default; mezcla única = brazo E-MIX (Parte 4 §4.3, Parte 2 §2.7/2.9) |
| V1-f5 | mayor | E2: presupuesto declarado (10h) no cierra con su propia config (16-24h) | Regla global 1 (ancla 424 tok/s): Parte 4 §4.3 redimensiona el corpus etapa-1 a ~8-12M tok, directiva fija E2 en 10-14 GPU-h |
| V1-f6 | mayor | Atribución de corrida cruzada: el run Kaggle con masking es `train_tooluse_kaggle.py`, no `train_qlora_kaggle.py` | Parte 2 §2.2 y Parte 4 §4.0 separan los dos kernels y sus runs (Kaggle vs Colab) |
| V1-f7 | mayor | Contradicción P5/P6 sobre Phi-4-mini en Kaggle Models | Parte 6 corregida: "no confirmado (solo Phi-3 oficial)"; P5 tenía razón |
| V1-f8 | mayor | E4 cita "suite de 32 ítems"; la real es 16+4 | Corregido en Parte 4 §4.0/§4.4 y Parte 7 §7.6 (E4 usa 16+4 y degrada a señal indicativa si no se amplía a N≥50, P0-ii) |
| V1-f9 | menor | Tabla de memoria P2 omitía el pico de logits/CE (~2-3 GB) | Parte 2 §2.1 reescrita con esa fila + contexto CUDA, unificada con Parte 1 |
| V1-f10 | menor | Config candidata (P1-C1) vs "columna vertebral" (P2 b2×ga8) no coinciden; erratas de texto | Parte 2 §2.9 ahora hereda "la config ganadora de E0" en vez de fijar batch; erratas corregidas en Parte 1 |
| V1-f11 | menor | Plan semanal 29-31h sin margen; documento usaba "16 GB" en vez de 15.6 | Parte 5 §5.7 recorta sábado a 4-5h (28-30h con margen); 15.6 GB en todo el documento |
| V1-f12 | menor | Cita imprecisa de cuota Kaggle (200GB) y caveat P100/CUDA≥13 faltante | Parte 5 §5.2/§5.3 corrige a product-feedback/512322 y agrega el check `torch.version.cuda` |
| V1-f13 | menor | "~59M tok/sesión" (extremo optimista) usado sin propagar el rango completo | DC-7/DC-8 reancla TODO a 424 tok/s piso / ≥800 objetivo E0; Parte 3 P-1 y Parte 4 §4.3 redimensionados |
| V1-f14 | menor | "161 = 99+64" suma 163, no 161 | Corregido en Partes 2/4/5: "161 = 99+64 tras dedup de 163 brutos" |
| V2-f1 | crítico | (= V1-f2/V3-f1) Gates duplicados P3/P7 | DC-6 (ver V1-f2) |
| V2-f2 | mayor | (= V1-f5) E2 presupuesto interno inconsistente | Ver V1-f5 |
| V2-f3 | mayor | Presupuesto de tokens anclado al percentil ~93 (1,490 tok/s); cota MFU no explicitada | DC-7/DC-8: 424 tok/s piso (12% MFU), objetivo 800 (23% MFU); 1600 "improbable" queda como techo especulativo, no plan |
| V2-f4 | menor | Tabla adapter+opt con 3 contabilidades de bytes/param distintas (10/12/16) | Regla global 3: contabilidad única (4+4+8 fp32 / 2 paged-8bit) fijada en Parte 1(b)(d), r16=0.30/r32=0.60/r64=1.20 GB |
| V2-f5 | menor | SDPA math: "0.5 GB/capa" no reproduce (da 0.27 GB) | Parte 1(f): 0.27 GB/buffer, ~0.5 GB si coexisten pre/post-softmax (supuesto explícito) |
| V2-f6 | menor | Tres números de base NF4 (2.06 / 1.8 / 1.8 GB) entre partes | Unificado 2.06 GB decimal (1.91 GiB) en Partes 1, 2 y 6 |
| V2-f7 | menor | Potencia McNemar reproducible solo bajo p10=0.02 no declarado | Parte 3 §3.4 declara p10=0.02 explícito y agrega la fila G2@+10pp→73.3% |
| V2-f8 | menor | "34→150 tareas" y "32 ítems" no reproducen contra el repo (42 tareas, 16 ítems) | Parte 4: 42→~150 tareas; 16+4 ítems en todo el documento |
| V2-f9 | menor | G4: "200 ítems ≈45-90min" subestima (falta prefill+PPL) | Parte 3 §3.3 corregido a "90-180 min decode + PPL aparte" (regla global P3) |
| V2-f10 | menor | GaLore "12-14 GB" inconsistente con su propio desglose (8-9.5 GB) | Parte 2 §2.5 presenta los dos escenarios explícitos (8-9.5 per-layer / 14-15 grad-completo) |
| V2-f11 | menor | Fórmula activaciones con typo "4096"; Qwen3-4B pesos/throughput levemente corridos | Parte 1(c): fórmula `b·s·(6h+3i+2·d_kv)` sin el typo, 45.8k con d_kv |
| V3-f1 | crítico | (= V1-f2) Colisión de identificadores G1-G5 | Ver V1-f2 |
| V3-f2 | crítico | (= V1-f4) Dos backbones (secuencial vs mezcla única) sin árbitro declarado | Ver V1-f4 |
| V3-f3 | mayor | Potencia McNemar etiquetada [MEDIDO] sin script commiteado en el repo | Regla global 2: `cognia_v3/eval/mcnemar_power.py` + JSON + test commiteados (commit 5cb84c4) — P0(i) CUMPLIDO, etiqueta [MEDIDO] ahora legítima |
| V3-f4 | mayor | (= V1-f8) "Suite de 32 ítems" de E4 no existe | Ver V1-f8 |
| V3-f5 | mayor | E6.1 cita "suite ACCION de 24 casos" inexistente | Parte 6 §6.6: slice BFCL held-out 50 ítems, umbral 0.80 (regla global 6) |
| V3-f6 | mayor | (= V1-f6) Conflación de dos corridas de Kaggle en un solo hecho medido | Ver V1-f6 |
| V3-f7 | menor | DP 2×T4 medido solo en el tiny, extendido sin evidencia a QLoRA del 3B | Parte 5 §5.2 reetiqueta [PREDICCIÓN → mini-test DDP en E0/E1] |
| V3-f8 | menor | "~2GB de pesos" citado [MEDIDO] es comentario de diseño, no medición de VRAM | Parte 1(a) reetiqueta [CALCULADO], cita el comentario como consistencia, no evidencia |
| V3-f9 | menor | Params LoRA r=8 etiquetados [MEDIDO] siendo aritmética sobre la config | Parte 1(b): [MEDIDO: config] + [CALCULADO]; nota pendiente citar `print_trainable_parameters()` real en E0 |
| V3-f10 | menor | (= V2-f5) SDPA math 0.27 vs 0.5 GB | Ver V2-f5 |
| V3-f11 | menor | Mezcla "53M tok ≈ 1 sesión a 1,340 tok/s" ancla en el extremo optimista | Parte 4 §4.3 redimensiona al piso 424 con rango explícito (6.6-13.1h según epochs) |
| V3-f12 | menor | Ancla G2 "+66.7pp" (0.5B, N≈6) citada sin aclarar que McNemar da p=0.125 (no significativo) | Parte 3 §3.3 G2 cita procedencia completa: señal direccional, no evidencia de detectabilidad a N=100 |
| V3-f13 | menor | (= V1-f7) Contradicción Kaggle Models Phi-4-mini | Ver V1-f7 |
| V3-f14 | menor | "<30% sobrevive" el filtrado de `cognia_dataset` sin falsador declarado | Parte 4 §4.0: falsador E-D5 (tasa real de supervivencia loggeada, aceptados/3,489) |
| V3-f15 | menor | Cifra exacta de overhead DoRA (+75%/+56%) no confirmable en el abstract del paper citado | Parte 2 §2.3: suavizado a "orden +50-80% según la evaluación unificada 2026, cifra exacta no confirmable" |

**Conflicto no resuelto por este agente:** V1-f2/V2-f1/V3-f1 (gates duplicados) y V1-f8/V3-f4
(ítems de razonamiento) exigen que la **Parte 7** referencie los gates canónicos de la Parte 3
(DC-6) y corrija 32→16+4 ítems; al momento de escribir este Anexo, `final_P7.md` **no existe
todavía** en el directorio de trabajo (solo el borrador `seccion_P7.md`, que conserva G1-G5
propios y "32 ítems"). Este Anexo documenta la resolución **prescrita** (DC-6, DC-4, regla global
6) que la Parte 7 final debe aplicar; no puede certificar que ya esté aplicada en el texto vivo.

---

## Anexo B — Preguntas abiertas consolidadas (deduplicadas de las 7 secciones)

**Memoria y velocidad (arbitradas en E0, Parte 1/7 — grilla `e0_perfil_kernel.py` ya lanzada):**
- Pico real de VRAM por config (`max_memory_allocated`, fragmentación del allocator).
- ¿SDPA con máscara 4D block-diagonal despacha a memory-efficient o cae a `math`? (E0-b).
- ¿Liger-Kernel (CE fusionada Triton) corre en sm_75 específicamente? (recorta ~2 GB de pico).
- Ganancia real de Unsloth vs baseline ya optimizado en T4 (no vs HF pelado) — arbitra DC-5.
- Utilización real tokens-útiles/padded del dataset actual — determina si packing rinde 2× o 3×.
- ¿DDP 2×T4 acelera o degrada el QLoRA del 3B (a diferencia del tiny, que fue más lento)? — mini-test ~1h en E0/E1 (V3-f7).
- ¿Packing + completion-only masking interactúan bien (máscara no cruza fronteras de documento) en la versión TRL/transformers de la imagen Kaggle?

**Método (Parte 2):**
- ¿DoRA y GaLore tienen paths estables en fp16/sm_75 sobre base NF4 (overhead real, no proyectado)? — E-dora/E-galore, solo si hay techo de calidad y sobra cuota.

**Gates y calidad (Parte 3/7):**
- Costo real de Q4_K_M en un 3B recién adaptado (vs +0.05 PPL publicado para 7B); ¿Q5_K_M/imatrix recuperan si G4 falla? — primera corrida de G4.
- ¿Es medible el mismatch NF4-entreno→fp16-merge (DC-9)? ¿Conviene entrenar la última etapa directo contra la base fp16 mergeada? — G4/E5.
- ¿Prompt-loss-weight 0.1 le gana al masking total en completions cortas de ACCION? — E-mask.
- ¿15% de replay alcanza en un multi-stage de 3-4 etapas con olvido acumulado entre merges, o hace falta 25%? — medido por G1/G3 en cada etapa (rama de aborto ya pre-registrada en E3).
- ¿Cuántos ítems de la suite flipean entre dos corridas greedy idénticas en llama.cpp? Si >2/100, reescribir ítems inestables antes de confiar en McNemar.
- ¿La sub-suite de 20 ítems 3-shot detecta D-2, o hace falta una suite few-shot dedicada de 50 ítems?
- ¿Cómo gatear coherencia multi-turno larga (fuera del alcance de suites de 1 turno)? Candidato: gate e2e de 100k, costo limita frecuencia.
- ¿Destilar CoT-por-turno al adapter rompe el formato ACCION (el riesgo se midió en prompting, no en fine-tuning)? — E4, aborto si >5% emisiones malformadas.

**Datos (Parte 4):**
- Curva de aprendizaje de `correct_tool` con 161→500→2.000→4.000 pares: ¿dónde satura? — E-D2.
- ¿Trayectorias con `RESULTADO...ERROR` + corrección mejoran la robustez del agente en deploy? — E-D2b.
- Mezcla única vs secuencial-con-merge: ¿cuál gana en el promedio multi-gate al mismo presupuesto de tokens? — E-MIX, regla de decisión en Parte 7 §7.3 (árbitro de DC-4).
- ¿Cuánto diverge el delta en eval-plantilla vs eval-fresco (train/eval de tool-use comparten `tasks.py`)? — E-DECON.
- ¿Qué % de `cognia_dataset.jsonl` sobrevive el filtrado de calidad ≥0.8? — E-D5.
- ¿Entra seq_len 2048 en la T4 con NF4 + batch efectivo 16 (trayectorias multi-paso D2/D3)? — E-SEQ.
- ¿System prompts variados en train mejoran la robustez al cambiar el prompt del CLI en deploy? — E-SYS.
- ¿Batchear el generador 7B sube los ~2 aceptados/hora de D3 a un ritmo viable, o conviene reformatear datasets públicos verificables y reservar lo sintético para APIs internas de Cognia?
- Dilución NF4→Q4_K_M: ¿todo delta de datos medido en el kernel sobrevive en el GGUF final? — re-medir siempre en G4, nunca asumir sobre el checkpoint NF4.

**Operaciones Kaggle (Parte 5):**
- ¿SmolLM3-3B existe como Kaggle Model montable? Verificar con `kaggle models list` antes de E6.2; plan B = descarga HF con internet ON, cacheada en el dataset de checkpoints.
- ¿El output de `/kaggle/working` sobrevive si Kaggle mata el kernel exactamente a las 12h? (se asume que NO por seguridad; probarlo costaría una sesión sacrificada).
- ¿Correr eval en la 2ª T4 en paralelo al training degrada el tok/s por contención de CPU/RAM? — E-OPS-1.
- ¿Cuánto tarda el merge NF4→fp16 + conversión GGUF Q4_K_M dentro del kernel, y entra en los 20 GB de `/kaggle/working` junto al checkpoint de resume?

**Elección de base (Parte 6):**
- Calidad real de SmolLM3 en tool-calling con su propio template (no hay benchmark público comparable a BFCL para ese formato) — E6.1-E6.3.
- ¿El modo `/think` residual de SmolLM3 interfiere con el formato ACCION bajo fine-tuning?
- Si `cognia-4b` (DC-3) se activa: resolver la disputa Qwen3-4B BFCL-v3/MultiIF (61.9/69.0 vs 71.2/77.3, V1-f1/V3 no resuelta) re-verificando contra la model card vigente en ese momento.

**Programa experimental (Parte 7):**
- ¿Es 1e-4 el lr óptimo a escala 15-30M tokens? Los dos puntos medidos (5e-5 gana en dataset KG chico; 2e-4 deriva a chino) no fijan la curva a esta escala — monitoreo intermedio en E2 con aborto pre-registrado si aparece deriva de idioma.

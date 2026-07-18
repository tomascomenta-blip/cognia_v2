# DSPARK + GEMMA-DIFUSIÓN → DRAFT MODEL PROPIO PARA COGNIA

**Fecha:** 2026-07-18
**Estado:** DISEÑO — nada implementado, nada entrenado. Gates pre-registrados abajo.
**Hardware objetivo:** Ryzen 5 9600X (6c/12t), 31 GB RAM, RTX 5060 Ti 16 GB (Blackwell, sm_120).
**Pedido del dueño (literal):** "quiero que combines el dspark de deepseek (investigalo) con la
tokenizacion difusa de gemma para texto, la idea es entrenar un modelo chiquito que construya
los borradores de una forma super rapida"

---

## 0. Resumen ejecutivo (leer esto primero)

1. **"DSpark" EXISTE.** No es un nombre deformado. Es un framework de speculative decoding
   publicado por DeepSeek a fines de junio de 2026 (paper: *"DSpark: Confidence-Scheduled
   Speculative Decoding with Semi-Autoregressive Generation"*, arXiv 2607.05147; código:
   repo `deepseek-ai/DeepSpec`, MIT). Combina un **draft paralelo tipo difusión de bloques**
   (estilo DFlash) con una cabeza secuencial liviana, una **cabeza de confianza** y un
   scheduler consciente de carga. En producción DeepSeek reporta +60–85% de velocidad por
   usuario sobre su baseline MTP-1.
2. **"Tokenización difusa de Gemma" está deformado pero apunta a algo real:**
   **DiffusionGemma** (Google, 10-jun-2026): un Gemma 4 MoE de 25.2B (3.8B activos) que
   genera texto por **difusión discreta enmascarada** en bloques ("canvas") de 256 tokens,
   ~15–20 tokens por forward pass. No es el *tokenizer* lo difuso (el tokenizer es
   SentencePiece normal de 262K); lo difuso es la **generación**.
3. **El puente entre ambas cosas ya existe y se llama DFlash** (Z Lab, ICML 2026): un draft
   model chiquito **de difusión de bloques** que draftea 16 tokens en UN forward pass,
   condicionado en hidden states del modelo grande, y que el grande verifica. Hasta 6.1× de
   speedup sin pérdida en Qwen3-8B, ~2.5× mejor que EAGLE-3. DSpark es una evolución de esta
   idea. **El pedido del dueño describe, casi palabra por palabra, un draft DFlash/DSpark.**
4. **Diseño propuesto:** un draft de difusión de bloques con **~110M parámetros entrenables**
   (núcleo de 6 capas, d=1024, embeddings y LM head CONGELADOS y compartidos con el target),
   target Qwen2.5-7B-Instruct, entrenado localmente en la RTX 5060 Ti con el target en 4-bit
   en el loop. Antes de entrenar NADA: dos baselines gratis (draft clásico Qwen2.5-0.5B en
   llama.cpp, y EAGLE-3 que llama.cpp mergeó en junio 2026) que fijan la vara real.
5. **Advertencia honesta pre-registrada:** en un target 7B que YA es rápido en GPU, el
   speculative decoding puede empeorar las cosas (hay reportes de regresión de hasta 4× con
   draft 0.5B sobre target 7B por overhead por ciclo). El kill-gate G2 (techo teórico medido
   con draft sin entrenar) existe exactamente para no repetir el fracaso de la era CPU
   (EAGLE3 0.464× vs base; draft separado 0.37×).

---

## 1. Qué es cada cosa REALMENTE (verificado)

Convención de citas: **[V]** = URL abierta y leída durante esta investigación (vía fetch).
**[S]** = visto solo en resultados de búsqueda, NO abierto; tratar como no verificado.
Los números citados son los que reportan esas fuentes; ninguno fue reproducido localmente.

### 1.1 DSpark (DeepSeek, junio 2026) — el pedido "dspark de deepseek"

- **Qué es:** framework de speculative decoding, no un modelo nuevo. Se adjunta a un
  checkpoint existente. Título del paper: *"DSpark: Confidence-Scheduled Speculative
  Decoding with Semi-Autoregressive Generation"*.
  [V] https://arxiv.org/abs/2607.05147 (abstract; el PDF completo no fue extraído)
- **Arquitectura (según cobertura técnica):**
  1. **Backbone paralelo** tipo DFlash: genera logits para todas las posiciones del bloque
     a la vez (drafting por difusión/no-autoregresivo).
  2. **Cabeza secuencial liviana** que añade sesgos dependientes del prefijo antes de
     muestrear cada token (por eso "semi-autoregresivo").
  3. **Cabeza de confianza**: puntúa cada token draft con su probabilidad estimada de
     sobrevivir la verificación (supervisada con tasas de aceptación analíticas).
  4. **Scheduler consciente de carga**: con GPU libre verifica el bloque completo; con GPU
     cargada verifica solo el prefijo confiable y descarta la cola condenada.
  [V] https://www.marktechpost.com/2026/06/27/deepseek-releases-dspark-a-speculative-decoding-framework-that-accelerates-deepseek-v4-per-user-generation-60-85-over-mtp-1/
- **Números reportados:** +60–85% velocidad por usuario en DeepSeek-V4-Flash y +57–78% en
  V4-Pro (producción, vs baseline MTP-1). Offline: longitud aceptada +26–31% vs EAGLE-3 y
  +16–18% vs DFlash, probado con Qwen3 4B/8B/14B y Gemma-4-12B-it. En chat la aceptación
  sube de 45.7% a 95.7% (con scheduling), en matemática de 76.9% a 92.5%. [V] (MarkTechPost)
- **Código:** repo `deepseek-ai/DeepSpec` (MIT): preparación de datos, entrenamiento y
  evaluación de drafts **DSpark, DFlash y Eagle3** para targets Qwen3 (4B/8B/14B) y
  gemma-4-12B-it. **Advertencias del README relevantes para nosotros:** los scripts asumen
  un nodo de 8 GPUs, y el cacheo de datos de entrenamiento ocupa **~38 TB para Qwen3-4B**.
  [V] https://github.com/deepseek-ai/DeepSpec
- **Checkpoint de producción:** `deepseek-ai/DeepSeek-V4-Pro-DSpark` (HF): mismo checkpoint
  V4-Pro (1.6T total / 49B activos) + módulo draft; config recomendada 7 tokens
  especulativos; se activa en vLLM con `--speculative-config`. MIT.
  [V] https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-DSpark
  (Nota: esa página enlaza arXiv 2606.19348, que es el paper de **DeepSeek-V4**, no el de
  DSpark. [V] https://arxiv.org/abs/2606.19348 — "DeepSeek-V4: Towards Highly Efficient
  Million-Token Context Intelligence", V4-Pro 1.6T/49B, V4-Flash 284B/13B.)
- **Contexto histórico — MTP:** el antecesor directo. DeepSeek-V3 entrena un módulo MTP
  (Multi-Token Prediction) que en inferencia actúa como draft (algoritmo estilo EAGLE en
  SGLang): speedups 1.25–2.11× según concurrencia.
  [V] https://rocm.blogs.amd.com/software-tools-optimization/mtp/README.html
  DSpark es lo que DeepSeek construyó para superar a MTP-1.

### 1.2 DFlash (Z Lab, ICML 2026) — la pieza que une DeepSeek con difusión

Es la referencia técnica MÁS importante para este plan, porque es exactamente "modelo
chiquito que construye borradores súper rápido" con generación difusa:

- **Idea:** draft model de **difusión de bloques** (block diffusion): predice un bloque
  entero de tokens en UN forward pass con atención bidireccional (no causal), condicionado
  en **hidden states del modelo target** ("target context features" inyectadas en las
  proyecciones K/V del draft). El target verifica el bloque en un pass, como siempre.
  [V] https://arxiv.org/abs/2602.06036 · [V] https://arxiv.org/html/2602.06036v1
- **Detalles del paper (versión HTML):** draft de **5 capas** (8 para Qwen3-Coder), bloque
  de **16 tokens** por pasada (10 para Llama-3.1), **comparte token embedding y LM head con
  el target, congelados**. Entrenamiento: ~800K muestras (NVIDIA Nemotron Post-Training
  Dataset V2 + CodeAlpaca) con **respuestas regeneradas por el target** (alineación al
  target), seq 3072, 6 épocas, AdamW lr 6e-4, loss cross-entropy con peso exponencial
  decreciente por posición. Experimentos en H200/B200. Resultados Qwen3-8B (T=0):
  speedup 5.15× (GSM8K) a 6.08× (MATH-500), longitud de aceptación τ ≈ 6.5–7.9.
  "Hasta 6.1× en Qwen3-8B, casi 2.5× más rápido que EAGLE-3".
- **Tamaños reales de drafts publicados** (HF org z-lab): 0.4B (Qwen3.6-35B-A3B), 0.6–0.7B
  (MiniMax-M2.7, gemma4-12B), 1–2B (targets grandes). Ese conteo INCLUYE embeddings/LM head
  compartidos; el núcleo entrenable es mucho menor.
  [V] https://huggingface.co/z-lab · [V] https://github.com/z-lab/dflash (MIT; inference en
  vLLM ≥0.20.1, SGLang, Transformers solo Qwen3/Llama-3.1, MLX; "training recipe soon" —
  pero el entrenamiento SÍ está en DeepSpec de DeepSeek)
- **NVIDIA lo empuja en Blackwell:** hasta 15× de throughput para gpt-oss-120b en DGX B300
  (TensorRT-LLM), 5.8× Gemma-4-31B (vLLM/Speculators), 5.1× Qwen3-8B (SGLang). Confirma el
  mecanismo: "target hidden-state conditioning... injected into the draft model's key-value
  projections across layers".
  [V] https://developer.nvidia.com/blog/boost-inference-performance-up-to-15x-on-nvidia-blackwell-using-dflash-speculative-decoding/
- **Integración vLLM (Speculators):** el draft recibe hidden states del target + embeddings
  de máscara; `sample_from_anchor` controla si draftea `block_size` o `block_size-1` tokens.
  Hoy solo hay soporte validado para verificador gemma-4-31B-it; "en desarrollo activo".
  [V] https://docs.vllm.ai/projects/speculators/en/latest/user_guide/algorithms/dflash/

### 1.3 "Tokenización difusa de Gemma" — qué existe realmente

- **Interpretación elegida: DiffusionGemma** (Google, model card actualizada 2026-06-10):
  modelo experimental sobre arquitectura Gemma 4. **25.2B totales / 3.8B activos** (MoE
  8/128 expertos + 1 compartido), 30 capas, **vocab 262K**, contexto hasta 256K. Genera por
  **difusión discreta**: parte de un bloque ("canvas") de **256 tokens** enmascarados y lo
  va des-enmascarando iterativamente ("block-autoregressive multi-canvas sampling"),
  ~15–20 tokens por forward pass. >1100 tok/s por usuario (H100 FP8, batch bajo).
  Costo en calidad vs Gemma 4 26B-A4B autoregresivo: MMLU-Pro 77.6 vs 82.6, AIME 69.1 vs
  88.3, LiveCodeBench 69.1 vs 77.1. Apache 2.0.
  [V] https://ai.google.dev/gemma/docs/diffusiongemma/model_card
- **Aclaración terminológica:** no existe "tokenización difusa" como técnica de Gemma. El
  tokenizer de DiffusionGemma es el SentencePiece normal de Gemma. Lo difuso es la
  **generación** (denoising de tokens enmascarados). Interpretaciones alternativas
  consideradas y descartadas: (a) SentencePiece con byte-fallback de Gemma — es tokenización
  estándar, nada "difusa"; (b) soft tokens / embeddings continuos — no es una técnica de
  Gemma en producción; (c) per-layer embeddings / MatFormer de Gemma 3n — es elasticidad de
  arquitectura, no difusión. La lectura que respeta la intención del dueño ("borradores
  súper rápido") es claramente la generación por difusión.
- **Implicación directa:** DiffusionGemma NO sirve como componente literal (25B, vocab 262K
  incompatible con Qwen). Sirve como **evidencia de que la difusión enmascarada de texto
  funciona y es rápida**, y de que su punto débil (calidad) es exactamente lo que la
  verificación del modelo grande repara en el esquema draft+verify.

### 1.4 Estado del arte en drafts para speculative decoding (2025–2026), y llama.cpp

| Método | Draft | Cómo draftea | Estado en llama.cpp |
|---|---|---|---|
| Draft clásico separado | modelo chico independiente (p.ej. Qwen2.5-0.5B) | autoregresivo | **Soportado** (`--model-draft`/`-md`) |
| Medusa | cabezas extra sobre el target | paralelo por cabeza | No; superado por EAGLE en la literatura |
| MTP (DeepSeek-V3) | módulo entrenado junto al target | 1–3 tokens extra | No (SGLang/vLLM sí) |
| EAGLE-3 | ~decoder liviano sobre features del target | autoregresivo con features | **Mergeado 12-jun-2026** (PR #18039) |
| DFlash | difusión de bloques + hidden states del target | 16 tokens/pass, no-AR | **NO soportado** |
| DSpark | DFlash + cabeza secuencial + confianza + scheduler | semi-AR | **NO soportado** |

- **llama.cpp draft clásico:** exige vocab compatible: mismo `llama_vocab_type`, mismos
  BOS/EOS, tokens con los mismos strings, y diferencia de tamaño de vocab ≤ 128
  (`SPEC_VOCAB_MAX_SIZE_DIFFERENCE = 128`). [S — deepwiki/docs de llama.cpp, visto en
  búsqueda, no abierto; verificar contra el código fuente al implementar]
  Dato crítico para nosotros: Qwen2.5-7B tiene `vocab_size` 152,064 y Qwen2.5-0.5B/1.5B/3B
  151,936 (mismo tokenizer, distinto padding de embedding): diferencia = exactamente 128.
  La comunidad usa 0.5B como draft de 7B/14B/32B, así que en la práctica pasa el chequeo,
  pero **queda declarado como verificación empírica pendiente D1**.
- **llama.cpp EAGLE-3 (nuevo, junio 2026):** PR #18039 mergeado 12-jun-2026. Uso:
  `llama-server -m target.gguf -md eagle3.gguf --spec-type draft-eagle3
  --spec-draft-n-max 8 --spec-draft-p-min 0.5`. Conversión del draft con
  `convert_hf_to_gguf.py ... --target-model-dir <target_hf>`. Speedups reportados en el PR:
  Llama-3.1-8B BF16 2.85–3.28×, **Q4_K_M 1.62–2.26×** (la cuantización del target reduce la
  ganancia), Qwen3-8B BF16 1.62–2.17×, **MoE 0.83–1.08× (puede EMPEORAR)**. No compatible
  con `--sm tensor`. Targets con soporte: Llama, Qwen3, Gemma-4, GPT-OSS.
  [V] https://github.com/ggml-org/llama.cpp/pull/18039
  Para **Qwen2.5-7B-Instruct específicamente NO encontré checkpoint EAGLE-3 público** (hay
  para Qwen2.5-14B: `ruipeterpan/Qwen2.5-14B-Instruct_EAGLE3_UltraChat` [S], y EAGLE-1
  `yuhuili/EAGLE-Qwen2-7B-Instruct` [S]). Incógnita D2.
- **Advertencia de consumo real:** en GPUs de consumo el speculative clásico puede no ganar
  nada o perder: con target 7B ya rápido, el costo fijo por ciclo puede superar lo ahorrado
  (reporte de regresión ~4× con draft 0.5B sobre 7B en algunas GPUs; con target más lento
  se invierte a 1.4× de ganancia). [S — discusión ggml-org #10466 e informes de la
  comunidad, vistos en búsqueda] Esto motiva el gate G2.

---

## 2. Diseño propuesto: **Cognia-BDraft** (block-diffusion draft ~110M entrenables)

### 2.0 Decisión de interpretación (explícita)

El pedido "DSpark + tokenización difusa de Gemma" se materializa como: **un draft de
difusión de bloques estilo DFlash** (la parte "difusa"/Gemma-DiffusionGemma) **con cabeza de
confianza y verificación adaptativa estilo DSpark** (la parte DeepSeek), entrenado por
nosotros a escala mini, para que **Qwen2.5-7B-Instruct** (llama.cpp o pipeline propio) lo
verifique. No usamos DiffusionGemma ni DeepSeek-V4 como componentes: usamos sus ideas, que
es lo que el tamaño de nuestro hardware permite.

### 2.1 Dos pistas, en orden obligatorio

**Pista 0 — Baselines sin entrenar (2–3 días, costo ~0). SIEMPRE primero.**
1. `B0`: Qwen2.5-7B-Instruct Q4_K_M en llama.cpp CUDA, batch 1 → tok/s base en la 5060 Ti.
   Este es EL número contra el que todo se compara. (Estimación no medida: 40–70 tok/s;
   medir, no asumir.)
2. `B1`: + Qwen2.5-0.5B-Instruct (Q8_0) como draft clásico: `llama-server -m 7b.gguf -md
   0.5b.gguf --draft-max 8 --draft-min 1`. Mide speedup en 3 tareas (código, matemática,
   chat es/en) × 3 corridas.
3. `B2` (opcional, si D2 se resuelve o si se acepta migrar el target a Qwen3-8B): EAGLE-3
   en llama.cpp con draft oficial, y/o DFlash de z-lab en vLLM/SGLang bajo WSL2. Qwen3-8B
   tiene TODO el ecosistema listo (EAGLE-3 + DFlash + DeepSpec lo usa de target); Qwen2.5-7B
   no. **Si B2 con Qwen3-8B da ≥2× e2e, la opción "cambiar de target y no entrenar nada"
   pasa a ser la recomendada por costo/beneficio, y la Pista 1 queda como proyecto de
   investigación, no de producto.**

**Pista 1 — Entrenar Cognia-BDraft (el pedido del dueño).**

### 2.2 Arquitectura concreta

```
Target: Qwen2.5-7B-Instruct (d_model 3584, vocab_size 152,064, tokenizer Qwen2 BPE)

Cognia-BDraft:
  - Token embedding: EL DEL TARGET, congelado, compartido  (152,064 × 3584 ≈ 545M, no entrenable)
  - LM head:         LA DEL TARGET, congelada, compartida  (≈ 545M, no entrenable)
  - down_proj: Linear 3584 → 1024                          (3.7M)
  - mask_embedding: 1 vector d=1024 aprendido (token [MASK] del canvas)
  - 6 × TransformerBlock bidireccional (SIN máscara causal dentro del bloque):
      d=1024, 16 heads (head_dim 64), SwiGLU FFN 4096, RMSNorm, RoPE
      ≈ (4·1024² + 3·1024·4096) ≈ 16.8M por capa → ≈ 101M
  - Condicionamiento en target (estilo DFlash): los hidden states de la última capa del
    target en las posiciones ya verificadas se proyectan (3584→1024, 3.7M) y se inyectan
    en las proyecciones K/V de cada capa del draft (cross-attention al contexto).
  - up_proj: Linear 1024 → 3584                            (3.7M)
  - Cabeza de confianza (estilo DSpark): MLP 1024→256→1 por posición del bloque (~0.3M),
    entrenada a posteriori (fase 2) para predecir P(token aceptado).

  Parámetros ENTRENABLES ≈ 110M   |   Bloque draft: 8 tokens por forward pass
  Pasos de denoising en inferencia: 1 (modo flash, como DFlash) — el canvas de 8 se
  des-enmascara en una pasada; la verificación del 7B es el "segundo paso de denoising".
```

Justificación de decisiones:
- **Embeddings/head compartidos y congelados** (como DFlash): elimina el problema de
  compatibilidad de vocab por construcción, ahorra ~1.1B de parámetros a entrenar, y ancla
  el espacio de representación al del target. El artefacto en disco puede guardarse SIN
  esas matrices (se cargan del target); el "modelo chiquito" real es ~110M ≈ 220 MB bf16.
- **Bloque de 8 (no 16):** DFlash usa 16 con targets ≥8B y drafts 0.4–2B entrenados con
  ~4.8B tokens efectivos en H200s. Con ~20× menos compute de entrenamiento, un bloque de 8
  limita la dificultad de la tarea y mantiene τ útil. Ampliable a 12–16 en v1 si G4 pasa.
- **d=1024/6 capas:** entra en el presupuesto 50–200M pedido, cabe en 16 GB junto al target
  cuantizado durante el entrenamiento, y es ~3× el nano-draft de la era CPU (que era numpy
  de 2 capas — ver `planes/fase_A_B_C_D_inferencia_rapida.md`).

### 2.3 Entrenamiento

- **Datos:** 100–150K muestras de instrucciones: mezcla es/en + código (subset de
  OpenHermes/Magpie o Nemotron-Post-Training-V2 + CodeAlpaca, como DFlash) **+ logs propios
  de Cognia** (dominio real). Regla DFlash imprescindible: las respuestas se **regeneran con
  el propio Qwen2.5-7B-Instruct** (greedy/T=0.7) para alinear la distribución draft↔target.
  Presupuesto: ~150–300M tokens/época, 2–3 épocas → **0.4–0.8B tokens vistos**.
- **Objetivo:** cross-entropy sobre los tokens enmascarados del bloque, con los tokens del
  target como labels duros, ponderación exponencial decreciente por posición (DFlash), y
  ratio de enmascaramiento muestreado por bloque (t ~ U(0,1), estilo difusión discreta).
  Fase 2 (≤10% del compute): congelar el draft y entrenar la cabeza de confianza con las
  aceptaciones observadas (labels binarios de verificación real).
- **Dónde — memoria (RTX 5060 Ti 16 GB, plan A):**
  target NF4 4-bit congelado ≈ 5.5 GB + draft bf16 0.25 GB + Adam (fp32 estados) ≈ 1.3 GB
  + embeddings/head compartidos ya contados en el target 4-bit… **cuidado**: la LM head para
  la loss debe correr en fp16/bf16 desmaterializada por chunks (152K de vocab; hacer
  chunked cross-entropy). Con seq 1024–2048 y micro-batch 4–8 + grad-accum, cierra en
  ~12–14 GB. Los hidden states del target se computan **on-the-fly en el mismo forward**
  (NADA de cachear a disco: DeepSpec reporta ~38 TB de caché para Qwen3-4B a su escala —
  inviable acá).
- **Horas honestas (estimación, ±2×, NO medida):** costo dominado por el forward del 7B
  (~14 GFLOP/token) + fwd/bwd del draft y la head (~6 GFLOP/token). A un throughput efectivo
  realista de 1.5–3k tok/s en la 5060 Ti: **0.5B tokens ≈ 45–90 h**. Presupuesto
  pre-registrado: **v0 = 150M tokens (~15–30 h) hasta el gate G3; tope duro total 60 h.**
- **Kaggle T4 (plan B):** T4 = sm_75, sin bf16 (usar fp16 + GradScaler), ~2–4× más lenta
  que la 5060 Ti para esto, límite 30 h/semana. Solo si el toolchain local Blackwell falla
  (gate G0). El 7B en 4-bit + draft entra en una T4 de 16 GB igual que local. Un run v0
  tomaría 2–4 semanas de cuota → Kaggle es plan B, no plan A.

### 2.4 Integración en Cognia

- **Realidad dura:** llama.cpp NO soporta drafts con condicionamiento en hidden states tipo
  DFlash (solo draft clásico y, desde jun-2026, EAGLE-3). Tres rutas, en orden:
  1. **v0 — Pipeline propio en Python** (transformers + torch, WSL2): loop
     draft(8)→verify(1 pass del 7B)→aceptar prefijo (greedy: aceptar mientras
     draft_token == argmax_target; sampling: rechazo especulativo estándar). Sirve para
     MEDIR τ y speedup relativo. Su tok/s absoluto compite contra llama.cpp base (gate G4b).
  2. **v1 — Si G4 pasa:** portar la verificación a un runtime serio: vLLM/Speculators
     (la infraestructura DFlash existe pero hoy solo valida gemma-4-31B como verificador
     [V] docs de Speculators) o SGLang. Ambos corren en WSL2 sobre la 5060 Ti.
  3. **Alternativa que se queda en llama.cpp:** abandonar la parte difusa y entrenar un
     draft **formato EAGLE-3** para Qwen2.5-7B con SpecForge (existe el precedente 14B
     [S]), que enchufa directo en el soporte mergeado. Menos "DSpark+difusión", más
     pragmático. Se activa si la ruta 1 muere en G2/G3 pero B1/B2 mostraron que la GPU sí
     se beneficia de speculative.
- **Del lado DSpark** adoptamos en v0 solo lo barato: la cabeza de confianza para cortar el
  bloque draft en el prefijo confiable (menos tokens basura a verificar). El scheduler por
  carga no aplica (single user, batch 1).
- **Nota de coherencia con el repo:** el modelo primario actual del repo es
  Qwen2.5-Coder-3B-Instruct (ver `coordinator/registry.py`, `MANAGER_LOG.md`); este plan
  asume el salto a Qwen2.5-7B-Instruct en la GPU nueva, según el pedido. El draft diseñado
  usa el MISMO tokenizer para 3B y 7B, pero el condicionamiento en hidden states fija
  d_model del target: **un BDraft entrenado contra el 7B NO sirve para el 3B sin
  reentrenar** (d 3584 vs 2048). Elegir target antes de entrenar y no moverse.

---

## 3. Gates pre-registrados (definidos ANTES de escribir una línea de código)

Protocolo de medición común: mediana de ≥3 corridas, mismas seeds/prompts publicados en el
repo, 3 suites fijas (código: 20 prompts; matemática: GSM8K-subset 20; chat es/en: 20),
T=0 para speedup lossless y T=0.8 para el modo sampling, versión de llama.cpp y drivers
anotada. Números en `MANAGER_LOG.md` como siempre, ganen o pierdan.

| Gate | Cuándo | Métrica | Umbral | Acción si falla |
|---|---|---|---|---|
| **G0** toolchain | día 0 | torch cu128+ ve sm_120; forward 7B NF4 + draft esqueleto corre en WSL2 | funciona | Entrenamiento pasa a Kaggle T4; si allí el throughput medido < 800 tok/s → **KILL Pista 1** |
| **G1** baseline | día 1–2 | B0 tok/s base y B1 speedup clásico | registrar (sin umbral) | — (es la vara; si B1 ≥1.5× en código, anotar que el clásico ya cumple barato) |
| **G2** techo teórico | antes de entrenar (½ día) | con draft SIN entrenar, medir T_ciclo = draft(8)+verify; techo = 8·T_tok_base/T_ciclo | techo ≥ 1.5× | **KILL Pista 1** (misma matemática que enterró speculative en CPU: 0.464×) |
| **G3** señal temprana | al 10% del presupuesto (≈15M tokens) | top-1 acc del 1er token del bloque en val ≥ 30% **y** τ_greedy ≥ 1.5 | ambos | **KILL** (o 1 solo reintento con lr/datos ajustados, máx +5 h) |
| **G4a** aceptación | fin de v0 | τ (longitud media aceptada, greedy) | ≥ 2.5 en código/mat, ≥ 1.8 en chat | volver a ruta EAGLE-3 (2.4.3) o cerrar |
| **G4b** speedup e2e | fin de v0 | (i) ≥ 1.8× vs AR del MISMO pipeline Python; (ii) tok/s absoluto ≥ 1.2× llama.cpp base B0 | ambos | si solo (i): v1 en vLLM/SGLang puede rescatar (ii); si ni (i): cerrar línea difusa |
| **G4c** calidad | fin de v0 | con verificación greedy, salida byte-idéntica al target en las 3 suites | 100% | es un BUG de implementación, no de modelo: arreglar antes de reportar nada |
| **G5** confianza | fase 2 | cabeza de confianza: cortar el bloque sube speedup ≥ 5% relativo sin tocar G4c | ≥ +5% | se descarta la cabeza (queda BDraft pelado) |

**Presupuestos duros pre-registrados:** ≤ 60 h GPU de entrenamiento total Pista 1 v0;
≤ 2 semanas calendario; $0 (hardware propio + cuota Kaggle). Cualquier extensión requiere
re-registrar gates nuevos por escrito ANTES de gastarla.

---

## 4. Riesgos e incógnitas declaradas

1. **Todo el ecosistema tiene <2 meses.** DSpark (jun-2026), DiffusionGemma (jun-2026),
   EAGLE-3 en llama.cpp (jun-2026). APIs y repos van a moverse debajo nuestro. El paper de
   DSpark (2607.05147) solo lo leí a nivel abstract; los detalles finos vienen de cobertura
   secundaria (MarkTechPost) y del README de DeepSpec.
2. **Extrapolación de escala NO validada:** DFlash reporta τ 6.5–7.9 con drafts 0.4–2B
   entrenados con ~5B tokens efectivos en H200/B200. Nuestro núcleo de 110M con ~0.5B
   tokens en una 5060 Ti es ~10–20× menos de todo. τ 2.5 es una apuesta razonable, no un
   dato. Por eso G3 corta al 10% del gasto.
3. **Speculative puede PERDER en target rápido:** ya nos pasó en CPU (0.464×/0.37×) y hay
   reportes de regresión con 0.5B-sobre-7B en GPU [S]. El overhead Python del pipeline v0
   es real (por eso el gate doble G4b: relativo Y absoluto).
4. **Vocab:** resuelto por construcción en BDraft (embeddings del target). Para el baseline
   B1: diferencia 152,064−151,936 = 128 = exactamente el límite documentado de llama.cpp
   [S]; si el chequeo fuese `>` pasa, si fuese `>=` falla. Verificación empírica D1
   pendiente (5 minutos, día 1).
5. **VRAM:** inferencia OK (7B Q4_K_M ~4.7 GB + KV + draft 0.25 GB ≪ 16 GB). Entrenamiento
   justo (~12–14 GB estimados, no medidos): la LM head de 152K de vocab en la loss es el
   punto de dolor (obligatorio chunked-CE). Si no cierra: seq 1024 y micro-batch 2.
6. **Blackwell sm_120 + toolchains:** requiere CUDA 12.8+ / torch reciente (cu128+);
   bitsandbytes/flash-attn en **Windows nativo** para sm_120 es terreno frágil → el plan
   asume **WSL2** para todo lo Python/torch. llama.cpp CUDA precompilado para Blackwell es
   la parte madura. G0 verifica todo esto el día 0 antes de invertir nada.
7. **DeepSpec como receta:** su código de entrenamiento (MIT) soporta DSpark/DFlash/Eagle3
   pero para Qwen3/Gemma-4 y asumiendo 8 GPUs + decenas de TB de caché. Adaptarlo a
   Qwen2.5-7B + 1 GPU + on-the-fly es trabajo nuestro y puede revelar supuestos ocultos.
8. **Incógnita D2:** no encontré EAGLE-3 público para Qwen2.5-7B-Instruct (sí 14B [S]).
   Si aparece (o si SpecForge lo entrena barato), la ruta 2.4.3 se abarata mucho.
9. **Target en duda (3B vs 7B vs Qwen3-8B):** el repo hoy corre Qwen2.5-Coder-3B. Si el
   dueño prioriza "que ande YA rápido" sobre "entrenar lo nuestro", migrar a **Qwen3-8B**
   compra el ecosistema completo (EAGLE-3 en llama.cpp + DFlash z-lab + DeepSpec) sin
   entrenar nada. Decisión de producto, no técnica; este doc deja ambas rutas medibles.
10. **Sesgo de fuentes:** los speedups de DFlash/DSpark/NVIDIA provienen de los autores o
    de partners; en hardware chico y batch 1 los números SIEMPRE achican. Ningún número de
    este doc se considera cierto hasta reproducirse en la 5060 Ti bajo el protocolo §3.

---

## 5. Fuentes

**Abiertas y leídas durante esta investigación [V]:**
- https://arxiv.org/abs/2607.05147 — DSpark (abstract)
- https://github.com/deepseek-ai/DeepSpec — código DSpark/DFlash/Eagle3 (MIT)
- https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-DSpark — checkpoint DSpark
- https://arxiv.org/abs/2606.19348 — paper DeepSeek-V4 (contexto)
- https://www.marktechpost.com/2026/06/27/deepseek-releases-dspark-a-speculative-decoding-framework-that-accelerates-deepseek-v4-per-user-generation-60-85-over-mtp-1/
- https://arxiv.org/abs/2602.06036 y https://arxiv.org/html/2602.06036v1 — DFlash (ICML 2026)
- https://github.com/z-lab/dflash y https://huggingface.co/z-lab — código y checkpoints DFlash
- https://developer.nvidia.com/blog/boost-inference-performance-up-to-15x-on-nvidia-blackwell-using-dflash-speculative-decoding/
- https://docs.vllm.ai/projects/speculators/en/latest/user_guide/algorithms/dflash/
- https://ai.google.dev/gemma/docs/diffusiongemma/model_card — DiffusionGemma
- https://github.com/ggml-org/llama.cpp/pull/18039 — EAGLE-3 en llama.cpp (merged 12-jun-2026)
- https://rocm.blogs.amd.com/software-tools-optimization/mtp/README.html — MTP como draft

**Solo vistas en resultados de búsqueda, NO abiertas [S] (no citar como leídas):**
docs/speculative.md y discusiones #10466/#15902/#22473 de ggml-org/llama.cpp; deepwiki de
llama.cpp (chequeos de vocab, SPEC_VOCAB_MAX_SIZE_DIFFERENCE=128); PR #24593 (eagle3
qwen3.5/3.6, 19-jun-2026); huggingface.co/google/diffusiongemma-26B-A4B-it;
ruipeterpan/Qwen2.5-14B-Instruct_EAGLE3_UltraChat; yuhuili/EAGLE-Qwen2-7B-Instruct;
SafeAILab/EAGLE; z-lab.ai/projects/dflash; VentureBeat y blogs varios sobre DSpark;
LM Studio blog 0.3.10.

# XHUNDRED — Diseño: 100M funcional en ≤30 min en T4

**Fecha:** 2026-07-02 · **Hardware objetivo:** Kaggle 1× Tesla T4 15.6GB (SM75, fp16 TC 65 TFLOPS pico) ·
**Precedente:** xfinal 37.7M byte-level, val bpb 1.478, 23.2 min, coherencia-con-deriva
(`results_xfinal/xfinal_results.json`) · **Base de código:** `xfinal_kernel.py` + levers XSPEED validados ·
**Estado:** DISEÑO PRE-REGISTRADO (gates y predicciones escritos ANTES de correr).

Síntesis de 7 informes (costo-raíz, optimizers, init-arch, tokenizer, datos-curriculum,
precision-kernels, no-backprop). Las discrepancias entre informes se resuelven acá y quedan anotadas
(§4.7). Todo hiperparámetro tiene valor concreto.

---

## 1. Modelo de costo raíz (por qué el entrenamiento es lento)

```
wall ≈ 6·N·D_necesario / (MFU · pico_HW)  +  overhead(compile, eval, datos)
```

Dos palancas independientes: **throughput** (MFU·pico) y **data-efficiency** (D_necesario para la
calidad objetivo, que depende de optimizer + calidad del dato + tokenizer).

**MFU medidos del repo (no hay más precedente que esto):**

| run | modelo | tok/s | MFU fp16 (65T) |
|---|---|---|---|
| xfinal (2026-07-01) | 37.7M d=512 | 49,279 steady | **17.1%** (18.6% util. HW contando atención) |
| XSPEED ganador | 9.5M d=256 | 148,700 | 13.0% |
| XSPEED baseline fp32 | 9.5M | 36,300 | 25.5% del pico fp32 (8.1T) |

El MFU **sube con d** (17.1% a d=512 > 13.0% a d=256): a d chico los tensor cores quedan
sub-utilizados. Intensidad aritmética de un GEMM con M=batch·seq≫d es ≈ d/2 contra el ridge de la
T4 (203 FLOP/byte): d=512→256 (marginal), **d=768→384**, d=1024→512. A d=768 los GEMMs son
compute-bound; el resto del step no.

**Dónde se va el step de un ~110M (d=768, post-compile, estimado sobre FLOPs medibles):**
GEMMs de bloque ~65% (MLP 2/3, proyecciones attn 1/3) · lm_head vocab-32k ~23% (el GEMM más
grande, alto MFU) · SDPA scores/AV ~4% (a seq 512 con ventana 256 la atención NO pesa) ·
elementwise residual (norms, RoPE, SwiGLU act) ~8–12% · AdamW/Muon step ~2% · dataloader ~0 si
está pre-tokenizado.

**Memory-bound vs compute-bound en T4:** pre-compile ≥49% del step era elementwise/launch-bound
(medido XSPEED: compile+fused dio 1.95×); post-compile el residuo memory-bound es 10–15%. El
optimizer mueve ~3GB/step ≈ 2% (no es cuello). bf16 no tiene tensor cores en SM75 y fp8 requiere
SM89 → **fp16 AMP es la única precisión rápida disponible** (§6).

**Data-efficiency es la otra mitad del wall:** Chinchilla 20:1 para 110M pide 2.2B tokens ≈ 15 h a
35% MFU — inalcanzable por ~36×. El run va a quedar a 0.2–0.45 tok/param (sub-entrenado
estructural). Por eso las palancas que cambian el juego no son de kernel sino de D_necesario:
**tokenizer BPE** (4.5× más texto por token que byte), **Muon** (1.3–1.4× menos tokens al mismo
loss, medido a 0.1B), **dato simple** (TinyStories: coherencia muy por debajo de compute-óptimo).
Overhead no-train medido en xfinal: ~1 min (compile+eval+gen); a 110M presupuestar 3 min.

---

## 2. Presupuesto pre-registrado

**Modelo de referencia:** d=768, L=12, vocab 32,768 tied → 110.1M params (84.9M cuerpo + 25.2M emb).
FLOPs/token fwd+bwd ≈ **690M** (cuerpo 510M + lm_head 151M (22.9%) + atención banded ~28M (4%)).

**Tabla MFU → tok/s → tokens en 25 min de train puro (1500 s):**

| MFU | tok/s | tokens (25 min) | texto visto (×4.513 B/tok) | tok/param | steps (b48×512) |
|---|---|---|---|---|---|
| 15% | 14.1k | 21.2M | 96 MB | 0.19 | ~860 |
| 20% | 18.8k | 28.3M | 128 MB | 0.26 | ~1,150 |
| **25% (caso base)** | **23.6k** | **35.3M** | **159 MB** | **0.32** | **~1,440** |
| 30% | 28.3k | 42.4M | 191 MB | 0.39 | ~1,730 |
| 35% (techo optimista) | 33.0k | 49.5M | 223 MB | 0.45 | ~2,010 |

Se planifica a **MFU 25%** (proyección de la curva propia α≈0.6: 37.7M@49.3k → 110M@~24-27k; el
máximo observado en el repo es 17-18.6% pero a d=512 — el salto a d=768 + batch mayor + fixes de
kernel de §4.5 justifican 25% como caso base, NO 35-45%, que no tiene precedente). Si el run queda
a 17% como xfinal, ve 24M tokens = 108MB de texto y la meta sobrevive (§8-R5).

**Decisión de tokenizer/vocab: BPE propio 32,768** (byte-level BPE, HF `tokenizers`, entrenado
sobre la mezcla de corpus; fertilidad MEDIDA 2026-07-02 en es-wiki held-out: 4.513 bytes/token a
32k vs 4.163 a 16k; GPT-2 50k rinde 2.915 — reusar tokenizers ajenos pierde con números,
`scratchpad/tok_fertility_results.json`). Efecto sobre TEXTO visto: a igual FLOP budget el modelo
byte-256 ve 512×1=512 bytes de contexto y ~35% del texto total (§5 brazo D); el BPE-32k ve
**2,310 bytes de contexto efectivo (4.5×)** y 159MB de texto en el caso base. Vocab 32k y no 16k:
la ley de escala de vocabulario (Tao 2024, γ=0.83) da V_opt≈40k ya para 33M non-vocab; 16k solo
gana ~4% texto/FLOP y pierde calidad-por-token. *Discrepancia resuelta: el informe costo-raíz
recomendaba 16,384 sin la medición de fertilidad; el informe tokenizer midió → 32,768. El brazo E
(§5) cubre el escenario inverso.*

**Comparación vs precedente 37.7M (xfinal):**

| | xfinal 37.7M | XHUNDRED 110M (caso base) |
|---|---|---|
| corpus único | 20.5 MB | ~256 MB (7.8× más texto único visto: 159MB muestreados) |
| bytes procesados | 65.5 MB (3.2 épocas) | 159 MB (~0.6 épocas) = 2.4× |
| contexto textual (seq 512) | 512 bytes | ~2,310 bytes (4.5×) |
| tok/param | 1.74 (bytes/param) | 0.32 — MÁS sub-entrenado por parámetro |
| val bpb | 1.478 | esperado 1.12–1.25 (fórmula §3-G1) |

Conclusión del presupuesto: el 110M compra su ventaja por TEXTO y CONTEXTO, no por tok/param. Si el
texto extra no paga (brazo D lo falsea), el diseño se revisa entero.

---

## 3. Definición pre-registrada de "estado funcional" (ANTES de correr)

FUNCIONAL = **G1 ∧ G2 ∧ G3 ∧ G4**, todos evaluados con los pesos finales elegidos (mejor de
{EMA, LAWA, last} por val bpb, declarando cuál). 3/4 = "parcial", reportando cuál falló y por qué.
Todo se pre-registra acá; nada se ajusta después de ver resultados.

**G1 — val bpb wiki ≤ 1.35 (stretch ≤ 1.25).** Sobre 2MB de es-wiki held-out (mismo filtro que
train, disjunto por artículo). Fórmula comparable entre vocabs:
`bpb = CE_nats/token ÷ (bytes/token_medido_en_el_held-out × ln2)` (para 4.513 B/tok: bpb = loss/3.128).
Justificación conservadora: el precedente byte-level marcó 1.478; la estimación central del informe
tokenizer para ~40M tokens es 1.12–1.25, pero (a) la mezcla 50/50 con cuentos roba capacidad al
registro wiki, (b) el caso MFU-17% ve 30% menos tokens. 1.35 = mejora de −0.13 vs precedente ≈ la
mitad del salto estimado. **Falsación dura: wiki-bpb > 1.45 ≈ el 100M no pagó su tamaño.**
Reportar TAMBIÉN bpb sobre 2MB de cuentos held-out (informativo, sin gate: no hay precedente
comparable y el texto simple deflacta el número).

**G2 — muestras coherentes ≥ 7/10.** 10 muestras: 5 prompts del precedente + 5 nuevos fijados
antes de correr (2 apertura de cuento, 2 enciclopédicos, 1 descriptivo), 200 tokens, temp 0.8,
top-p 0.95, corte en `<|doc|>`. Checklist binario por muestra (los 3 a la vez): (a) ≥3 oraciones
gramaticales consecutivas en español; (b) mantiene el tópico del prompt ≥3 oraciones (sin salto
tipo la deriva municipios/demografía del precedente); (c) sin ensalada de palabras ni corte a mitad
de sintagma al final. Evaluación manual con checklist pre-registrado — subjetividad declarada; el
desempate cuantitativo es G3.

**G3 — no-degeneración.** Sobre las mismas 10 muestras (en tokens BPE): distinct-2 promedio ≥ 0.60
y distinct-3 promedio ≥ 0.75; ninguna muestra con una 4-grama repetida ≥4 veces. Medir los mismos
números en el 37.7M como referencia informativa (no gate — vocab distinto).

**G4 — mini-cloze-es ≥ 75% (30/40; stretch ≥85%).** 40 pares de 2 alternativas escritos ANTES de
entrenar y congelados en el repo: 20 de concordancia género/número ("los niños {juegan|juega}"),
10 colocaciones fijas ("había una {vez|luz}"), 10 de selección semántica obvia. Score: alternativa
con menor loss media por token. Azar = 50% → 75% exige señal gramatical real; es el único gate con
piso de azar conocido, por eso el umbral es alto.

Declaración honesta pre-registrada: a 0.2–0.45 tok/param el modelo estará LEJOS de su techo; val
bpb será mediocre por diseño de presupuesto. "Funcional" ≠ "bien entrenado". No se maquilla.

---

## 4. Receta candidata v1 (config EXACTA del kernel)

### 4.1 Arquitectura (110.1M totales)

| campo | valor | evidencia (1 línea) | escalabilidad |
|---|---|---|---|
| d_model / L / heads | 768 / 12 / 12 (dh=64) | GPT-2-small no-emb exacto; MFU sube con d (§1); MobileLLM: depth>width sub-1B | forma estándar; dh=64 óptimo SDPA a toda escala |
| d_ff (SwiGLU) | 2048 (múltiplo de 64) | tensor-core friendly; receta xfinal | ratio ~2.7 estándar |
| vocab | 32,768 BPE propio, **tied** | fertilidad medida 4.513 B/tok; V_opt≈40k (Tao 2024) | V_opt crece con N — mismo principio decide vocab a 1B+ |
| atención | banded 3:1 ventana 256, global en capas 3/7/11; máscara **precomputada como buffer** en `__init__`, globals `is_causal=True` | banded validado e2e (extrapolación 0%→funcional); el mask-denso por forward era bug de MFU (§4.5) | la banda es LA pieza de long-ctx del programa; a más escala ahorra FLOPs de verdad |
| pos | RoPE (idéntico xfinal) | validado + NTK×2 gratis | NTK escala |
| norm | RMSNorm pre-norm + **QK-norm** (RMSNorm por-cabeza en q,k antes de RoPE) | OLMo-2/DroPE: sin QK-norm LR≥1e-3 diverge; costo <1% | OLMo-2 la usa a 7B/13B; habilita LR agresivo a toda escala |
| seq | 512 | subir a 1024 duplica atención sin mejorar GEMMs; bpb_1024≈bpb_512 vía NTK medido | long-ctx va por banded+NTK, no por seq de train |
| separador de doc | token `<|doc|>` (id 0), corte de generación ahí | el join `"\n\n"` del precedente causó sangrado/deriva; en BPE el 0x00 del informe datos se vuelve token especial | fronteras aprendibles = estándar |

### 4.2 Init

- Embedding (tied con head), w_qkv, w1/w_gate: normal **std 0.02**.
- **ZERO-init**: o_proj y w3/down_proj (muP-like del speedrun; el modelo arranca ≈identidad, gradiente limpio).
- Head tied → NO se puede zero-init ni verificar loss=ln(V) exacto; check de sanidad relajado: loss inicial ≈ ln(32768)=10.40 ± 0.3.
- QK-norm gains = 1.0; RMSNorm gains = 1.0.
- **z-loss λ=1e-4** sobre logsumexp de logits, SIEMPRE en fp32 (estabiliza logits fp16 con vocab 32k; costo ~0).

*Discrepancia resuelta (destying): init-arch recomendaba untie+zero-head tasado a vocab 256 (+0.2M);
a vocab 32k cuesta +25.2M (135M totales, +0.3GB de estados). Se queda TIED; el zero-init se
conserva donde no depende del untie (o_proj, w3). Escalabilidad: a vocab/params mayores el untie se
reabre — está anotado, no perdido.*

### 4.3 Optimizer + LR + schedule

| campo | valor | evidencia | escalabilidad |
|---|---|---|---|
| **Muon** (matrices 2D ocultas, ~84.9M) | LR **0.02**, Nesterov momentum **0.95**, wd **0**, Newton-Schulz **5 iter en fp16** (momentum en fp32), scale `sqrt(max(1,m/n))`, transpose si m>n | 1.3–1.4× menos tokens al mismo loss MEDIDO a 0.1B con baseline tuneado (2509.02046); récord speedrun 124M +35% | Moonlight: Muon ≈52% FLOPs de AdamW a 3B/16B con 5.7T tok — escala probada |
| **AdamW fused** (emb tied + norms + QK-gains) | LR **3e-3**, betas (0.9, 0.95), wd 0.01 (0 en norms) | grupos no-matriciales del speedrun; fused validado XSPEED | convención estándar |
| schedule (ambos grupos, factor compartido) | warmup lineal **200 steps** → constante → **decay lineal a 0 en el último 20%** de steps (WSD/trapezoidal) | WSD con decay 20% ≡ cosine; permite EXTENDER la fase estable si sobra reloj | WSD es la norma actual (MiniCPM etc.) |
| steps totales | fijados por reloj: medir tok/s en step 50 → `total_steps = wall_restante·tok_s/24576`; plan base **~1,440** | el wall manda, no el conteo de steps | — |
| clip | `clip_grad_norm_(1.0)` global, post-`unscale_` de AMBOS optimizers | protege el grupo AdamW en fp16; Muon tiene RMS fijo por construcción | — |
| **EMA** | decay **0.998** (horizonte ~500 steps, calibrado a ~1,250 steps post-warmup), desde fin de warmup, `torch._foreach_lerp_` FUERA del grafo compilado; eval/final con EMA | la curva xfinal 3200→4000 orbita sin promediar (1.478↔1.496); WSD-lit: averaging ≈ decay parcial | LAWA/EMA usados en pretraining 1B+ (Sanyal 2023) |
| **LAWA** respaldo | k=5 checkpoints a RAM CPU en el último 40% (cada ~115 steps), promedio uniforme; elegir mejor de {EMA, LAWA, last} por val bpb (3 evals, segundos) | Kaddour 2022: ~25% menos steps al mismo val loss | ídem |

Secuencia AMP con dos optimizers: `scaler.unscale_(muon); scaler.unscale_(adamw);
clip_grad_norm_(1.0); scaler.step(muon); scaler.step(adamw); scaler.update()` — el GradScaler ya
skipea steps con inf/NaN (NaN-skip de fábrica); loguear contador de skips, si >1% → bajar LR, no parchear.

*Discrepancia resuelta (LR): costo-raíz y precision-kernels proponían conservar 6e-4 warmup-only
(validado); init-arch proponía AdamW 1.2e-3+QK-norm; optimizers proponía Muon. Se adopta Muon como
v1 porque es la única palanca de data-efficiency con medición a exactamente nuestra escala, y el
control A (§5) es el AdamW TUNEADO (1.5e-3, no el 6e-4 viejo: 2509.02046 muestra que un baseline
mal tuneado infla cualquier ganancia). QK-norm entra en v1 (contra precision-kernels, cuya
recomendación asumía LR 6e-4 — nuestro régimen de LR es otro).*

### 4.4 Precisión / compile / memoria

- AMP fp16 + `GradScaler(init_scale=2**16, growth_interval=2000)`; CE en fp32 (autocast ya lo hace); z-loss fp32.
- `torch.compile(model, mode="default", fullgraph=True, dynamic=False)`; NO compilar `generate()`;
  eval con shape de TRAIN (apilar ventanas de val a b48) para no recompilar. Muon step y EMA fuera del grafo.
  (default ≥ reduce-overhead a este tamaño: a 24.6k tok/step es compute-bound, medido XSPEED; max-autotune descartado §6.)
- **Batch 48×512 = 24,576 tok/step** (K1 prueba 64 con fallback automático a 48 en OOM).
  Presupuesto de memoria: estados ~2.1GB (master fp32 0.44 + grads 0.44 + Muon-momentum 0.34 +
  Adam emb 0.20 + EMA 0.44 + fp16 copy 0.22) + activaciones ~9.3GB (b48, 12L, SDPA mem-efficient)
  + CE **chunked en 4** (logits 32k nunca materializados enteros: 0.4GB fp16 + 0.8GB fp32 transitorio) ≈ 12.3GB < 15.6GB.
- *Discrepancia resuelta (batch): costo-raíz/init-arch pedían 64; precision-kernels calculó 64 =
  borde de OOM — y eso ANTES de sumar los logits de vocab 32k. Base 48; 64 es upside de K1, no supuesto.*
- Nota cheap16: NO aplica — el kernel XHUNDRED hereda de `xfinal_kernel.py` (banded-SDPA puro, sin
  capa de atención lineal). El gate de invariancia cheap16 solo corre si se reintroduce el híbrido.

### 4.5 Datos / curriculum / dataloader

- **Corpus 256MB, mezcla 50/50 intercalada uniforme** (barajar documentos ANTES de concatenar, no bloques):
  - 128MB `ffuuugor/tinystories_spanish` (campo `text_es`, streaming verificado 2026-07-02) — motor de coherencia (TinyStories: la simplicidad compra gramática/token).
  - 128MB `wikimedia/wikipedia 20231101.es` — registro/conocimiento + comparabilidad de bpb con el precedente.
- Filtros SOLO wiki: `len>500`; corte del artículo en `Referencias|Enlaces externos|Véase también|Bibliografía`;
  descartar líneas con ratio alfabético <0.55; dedup exacto por hash de línea (>80 chars) — mata las
  plantillas de municipios, causa raíz medida de la deriva del precedente. NO dedup en cuentos
  (repiten fórmulas legítimas). Assert al inicio: 5 muestras de `text_es` no vacías y en español;
  fallback a wiki-solo si el dataset falla (29 descargas — riesgo real).
- *Discrepancia resuelta (tamaño): datos-curriculum dimensionó 64MB tasado a byte-level (~64M
  byte-tokens); a fertilidad BPE 4.5 B/tok eso son solo ~14M tokens. Re-tasado: 256MB ≈ 57M tokens
  BPE ≈ 1.6× los tokens del caso base → ~0.6 épocas efectivas con sampling con reemplazo (régimen
  ≤4 épocas de Muennighoff, sobrado).*
- **Tokenizer**: BPE ByteLevel (HF `tokenizers`, `initial_alphabet=ByteLevel.alphabet()`, byte-fallback
  implícito, cero OOV), entrenado sobre 100MB de la MEZCLA (ambos registros representados; 6 s
  medidos en CPU i3 para 20MB). Pre-tokenizar TODO a `np.uint16` FUERA del wall (encode_batch
  multihilo, 2–5 min CPU Kaggle; `PYTHONUTF8=1` obligatorio — lección XSPEED).
- **Dataloader**: corpus uint16 residente en GPU (~115MB), gather vectorizado en 1 kernel
  (`pos = starts[:,None]+arange(seq+1); buf = ids[pos].long()`), sampling `randint` con reemplazo
  (validado; a <1 época la cobertura es equivalente). Elimina el loop Python de 64+ slices/step del kernel previo.
- Curriculum: NINGUNO (fácil→difícil descartado: la distribución final domina el estado del modelo;
  terminar en wiki restauraría la deriva). SLW solo como brazo condicional futuro, no en v1.
- Validación DOBLE: 2MB wiki held-out + 2MB cuentos held-out, bpb por fuente (nunca solo el mezclado).

### 4.6 Presupuesto de wall (30 min) y gates K1 de ingeniería (antes de K2)

`setup+compile ≤3 min · train 25 min · evals+gen+EMA/LAWA-compare ≤2 min · margen ~1 min`.
Pre-wall (one-time, no cuenta, igual que la descarga en xfinal): descarga corpus + train tokenizer + encode (~10 min CPU).

K1 (smoke ~15 min de T4, gates duros antes de gastar brazos K2):
1. tok/s con batch {32, 48, 64} × 100 steps + VRAM pico (`max_memory_allocated`) — fija batch y el MFU real.
2. Profiler 20 steps: **kernels del Newton-Schulz en fp16/tensor-cores** (si cae a fp32 → 30–80% overhead, mata a Muon en T4; gate: overhead NS <10% del step).
3. Warmup de compile medido por separado (gate <3 min).
4. Paridad de loss 300 steps fp16 vs fp32 a LR de v1 (gate ≤1%, método XSPEED) + skips del scaler <1%.
5. bf16 100 steps: cerrar con número el descarte aritmético (§6).
6. Test unitario: AMBOS param_groups decaen con el schedule (bug fácil del dual-optimizer).

### 4.7 Índice de discrepancias resueltas

1. vocab 16k (costo-raíz) vs 32k (tokenizer, medido) → **32k**; brazo E cubre 16k.
2. LR 6e-4 (costo-raíz, precision-kernels) vs 1.2e-3 (init-arch) vs Muon (optimizers) → **Muon v1**, control = AdamW 1.5e-3 tuneado.
3. QK-norm no-preventivo (precision-kernels) vs sí (init-arch) → **sí** (el régimen de LR elegido lo exige).
4. batch 64 vs 48 → **48** (memoria con logits 32k); 64 = upside K1.
5. untie+zero-head (init-arch) vs tied (tokenizer) → **tied** (untie costaba 0.2M a vocab 256; a 32k son +25.2M).
6. forma si empata: d=1024 (costo-raíz) vs d=768 (init-arch) → **d=768** (el cuello es texto/calidad, no MFU; brazo F lo decide con dato).
7. corpus 64MB (datos, tasado byte) vs 450MB (tokenizer) → **256MB** (re-tasado a 4.5 B/tok, ~0.6 épocas).
8. separador 0x00 (datos, byte-level) → **token `<|doc|>`** (equivalente BPE).
9. wd 0.1 (init-arch) vs 0.01 (optimizers) → Muon wd 0 + AdamW wd 0.01 en v1 (convención Keller del LR 0.02); wd 0.1 va en el brazo A.
10. EMA 0.999 (no-backprop) → **0.998** (el run tiene ~1,250 steps post-warmup, no ≥3,000; horizonte re-calibrado).

---

## 5. Plan de ablaciones pre-registrado (K2)

Regla común: **presupuesto de wall IGUAL por brazo = 12 min de train** (+~3 min overhead) — las
comparaciones son a mismo reloj, NUNCA a mismo step. Métrica primaria: val bpb wiki held-out
(sobre bytes crudos para cruces de vocab) + gates G2/G3 como desempate cualitativo. Umbral de
adopción: Δbpb > 0.01 o mejora de coherencia sin costo bpb. Run final de 30 min SOLO con el
ganador compuesto. Total K2 ≈ 7 brazos × 15 min + 1 micro ≈ 110 min de T4. Orden = prioridad por
impacto esperado.

| # | brazo | qué cambia vs v1 | PREDICCIÓN pre-registrada | criterio de decisión |
|---|---|---|---|---|
| 1 | **A control-AdamW** | sin Muon: AdamW fused único LR 1.5e-3, wd 0.1, mismo WSD/QK-norm/init | v1 le gana por **0.03–0.08 bpb** a igual wall (1.3–1.4× medido a 0.1B) | si Δ<0.01, Muon no paga su NS en T4 → v1 pasa a ser A (más simple) |
| 2 | **D byte-256** | vocab 256 tied, mismo cuerpo 12L×768 (85.4M); receta xfinal escalada | v1 (BPE) gana por **≥0.10 bpb sobre bytes crudos** + coherencia visiblemente mejor (~3.5× texto, 4.5× contexto); byte esperado 1.30–1.40 | si byte empata o gana, TODO el diseño BPE se revisa (improbable: cruce byte/BPE ≈1e22 FLOPs, estamos a ~6e16) |
| 3 | **G wiki-solo** | 100% wiki (256MB), sin cuentos | 50/50 gana coherencia (G2/G3) con wiki-bpb ≤ +0.05 vs wiki-solo; wiki-solo repite la deriva de plantillas | si 50/50 empeora wiki-bpb >0.05 → bajar cuentos a 35%; si gana en todo → confirmar 50/50 |
| 4 | **E BPE-16k** | vocab 16,384 (mismo tokenizer re-truncado) | pierde vs 32k por **≤0.05 bpb** (su +8% texto/FLOP no compensa peor calidad/token) | adoptar 16k solo si gana o si K1 muestra presión de memoria por el head |
| 5 | **C Muon-LR-alto** | Muon LR 0.04 (resto igual) | empata o gana ≤0.01 a v1 (grid 77M dio óptimo 0.03); si spikes/NaN → confirma 0.02 como techo fp16 | adoptar 0.04 solo si gana >0.01 sin skips del scaler |
| 6 | **F forma** | 8L × d=1024, 16 heads, d_ff=2048 (~117M) | +10–15% tok/s pero peor bpb/token; a igual wall **empate ±0.02** | si \|Δ\|≤0.02 quedarse d=768 (calidad/token manda; el MFU no es el cuello) |
| 7 | **H attn (micro, 500 steps)** | buffer-mask vs all-`is_causal` vs chunked-SWA-256 | is_causal +5–10% tok/s vs mask; chunked queda a ≤2% de is_causal | chunked se adopta SOLO si pasa el gate de extrapolación 512→1024 (bpb_1024 ≤ bpb_512+0.02 con NTK); sino buffer-mask — la velocidad no compra perder la extrapolación |
| 8 | **W averaging (free-rider en v1)** | mismo run: eval con last vs EMA-0.998 vs LAWA-k5 | EMA gana a last por **0.02–0.05 bpb** (la curva xfinal orbitaba); LAWA ≈ EMA | quedarse con el mejor; si last gana, EMA mal calibrado → 0.995 y re-mirar |

Byte-vs-BPE (brazo 2) es OBLIGATORIO aunque la evidencia externa sea fuerte: es la decisión más
estructural y la única que invalida el resto del árbol si sale al revés. No hay brazo de seq-1024,
batch-ramp, grad-accum ni SLW: descartados en §6 o diferidos con condición explícita (SLW solo si
aparece inestabilidad de LR que QK-norm no cubra).

---

## 6. Descartado con evidencia previa (no re-medir sin razón nueva)

- **Reglas de aprendizaje no-backprop** (exp049, medido, 3 seeds): PC 4.26× wall, EqProp 4.94×,
  DTP 2.32× — todas más lentas por ≤ calidad; FF 0.944 no cruza el umbral 0.95; ES 0.484
  descartado; DFA 1.17× y frágil a init. TODA alternativa paga ≥1.17× wall — con 30 min de budget
  es estrictamente peor. No gastar ni un brazo.
- **DataParallel 2×T4** (XSPEED, medido): 113.8k vs 132–136k en UNA GPU; b1024 OOM. El
  scatter/gather come más de lo que aporta la segunda GPU a esta escala.
- **torch.compile max-autotune** (XSPEED, medido): 97.1k < default 109.6k + 176 s de warmup.
- **gradient checkpointing** (XSPEED, medido): 43.3k (1.19×) — palanca de MEMORIA; a b48 no
  estamos memory-bound y el recompute suma ~33% FLOPs.
- **batch 1024** (XSPEED): no mejora sobre 512; **grad accum**: solo amortiza el optimizer step
  (~2% del wall) — no usar si el batch cabe; **batch-size ramp**: sin evidencia de ganancia a
  estos steps (los récords usan batch fijo).
- **bf16 en T4**: SM75 NO tiene tensor cores bf16 (llegaron con SM80); autocast bf16 cae a CUDA
  cores → ≥2× más lento esperado. Honesto: es descarte aritmético, no medido — K1.5 lo cierra con
  número en 100 steps. **fp8**: requiere SM89+, IMPOSIBLE en T4, punto.
- **Sophia** (2× no replica con baseline tuneado — 2509.02046), **Lion** (<1.2×), **SOAP/Shampoo**
  (≈Muon pero eigendecomp fp32 sin TC en T4), **Adafactor/Adam-mini** (palancas de memoria que no necesitamos).
- **Tokenizers reusados**: GPT-2 2.915 B/tok en español (medido), XLM-R emb 250k×768=192M params
  (imposible), BERTIN 4.407 < propio 4.682 a 50k (medido). **sentencepiece**: más lento sin ganancia.
- **muP completo**: complejidad sin retorno para UN modelo fijo; zero-init+QK-norm+wd dan la
  transferencia práctica de LR (arXiv 2510.19093).
- **Softcap en atención**: exige abandonar SDPA — no en T4.
- **seq 1024 en train**: duplica el término de atención sin mejorar GEMMs; extrapolación ya
  cubierta por banded+NTK (bpb_1024 1.4768 ≈ bpb_512 1.4783, medido xfinal).
- **Curriculum fácil→difícil**: la distribución final domina; terminar en wiki restaura la deriva
  (predicción pre-registrada por si alguien lo prueba: pierde en coherencia).
- **`robrenaud/multilingual_tinystories`**: ROTO para load_dataset (schema inconsistente, verificado 2026-07-02).

---

## 7. Fase 2 (3B) — aritmética de viabilidad honesta

**Pretrain 3B desde cero en T4: INVIABLE. La cuenta:**

- Chinchilla (20 tok/param): D = 60B tokens → C = 6·3e9·60e9 = **1.08e21 FLOPs**. T4 a 30% MFU =
  1.95e13 FLOP/s → 5.5e7 s = **641 días de GPU continua** ≈ 10 años de quota Kaggle (30 h/semana).
- Incluso al régimen ultra-sub-entrenado de XHUNDRED (0.33 tok/param → 1B tokens):
  C = 1.8e19 → 9.2e5 s ≈ **10.7 días continuos** (≈ 2 meses de quota). Y NO ENTRA EN MEMORIA:
  estados de entrenamiento mixed-precision 3B ≈ master fp32 12GB + grads 12GB + Adam 24GB =
  **48GB ≫ 15.6GB** → exigiría offload a CPU (MFU <5% → 65+ días) o sharding multi-nodo
  (restricción dura del repo: sin sharding WAN). Doble muro: cómputo Y memoria.
- Y un 3B a 0.33 tok/param sería un mal modelo: el precio de Chinchilla no se negocia con deseo.

**Qué SÍ es viable en T4: QLoRA fine-tune de un 3B pre-entrenado.** Base 4-bit ~1.8GB + adapters
LoRA (r=16, ~50–100MB) + activaciones: entra holgado; el pipeline Kaggle QLoRA ya existe en el repo
(`cognia_v3/training/kaggle/`). En 30 min de T4 un QLoRA procesa ~2–4M tokens de fine-tune —
suficiente para ESPECIALIZAR (formato, dominio español, tool-use estilo ACCION), no para enseñar
conocimiento nuevo.

**Expectativa honesta vs Qwen3-3B:** Qwen3 vio ~36T tokens de pretrain (≈6 órdenes de magnitud más
cómputo que nuestro budget). Nuestro QLoRA sobre un 3B base será PEOR en capacidad general que el
stock y solo puede ganar en el nicho fine-tuneado. Fase 2 = especialización de un pre-entrenado
ajeno; "nuestro 3B desde cero" no existe en este hardware y no se promete. Lo que XHUNDRED aporta a
Fase 2 no son pesos sino RECETA: los principios con escalabilidad demostrada (§4: Muon, QK-norm,
WSD, vocab-scaling, data-mix, banded) son lo que se lleva a cualquier corrida futura con hardware real.

---

## 8. Riesgos y mitigaciones

| # | riesgo | mitigación |
|---|---|---|
| R1 | **Newton-Schulz cae a fp32 en T4** → 30–80% overhead, Muon pierde | gate K1-2 con profiler (kernels half, overhead <10%); si falla y no se arregla en 1 iteración, v1 = brazo A (AdamW 1.5e-3) sin drama |
| R2 | **NaN fp16 con LR agresivo** (Muon 0.02 / AdamW 3e-3, d=768 destapa lo que d=512 no mostró) | QK-norm + z-loss + warmup 200 + scaler-skip contado; contingencia ordenada: Muon 0.02→0.01, AdamW 3e-3→1.5e-3; NUNCA parchear a ciegas |
| R3 | **MFU real <25%** (sin precedente medido >18.6%) | la meta sobrevive a 17% (24M tok = 108MB texto = 1.6× bytes procesados de xfinal); K1-1 fija el número real ANTES de comprometer steps; gates de §3 no se relajan |
| R4 | **Sub-entrenamiento estructural (0.2–0.45 tok/param)** — coherencia puede no llegar | es un riesgo de DISEÑO aceptado y declarado; palancas si falla G2: subir cuentos a 65% o recortar a 12L→10L (~95M); NO bajar LR ni alargar wall (rompe el goal) |
| R5 | **`ffuuugor/tinystories_spanish` se cae o viene sucio** (29 descargas) | assert de 5 muestras al inicio + fallback pre-programado a wiki-solo (brazo G ya lo mide) |
| R6 | **compile warmup >3 min a 110M** o recompiles (eval shape, branch banded/global) | dynamic=False + eval con shape de train + máscara como buffer no-persistente sliceada; K1-3 lo mide; si >3 min, restar del train y reportarlo (no esconderlo) |
| R7 | **OOM a b48 por logits 32k** | CE chunked en 4 de serie; fallback b48→b32 automático; brazo E (16k) cubre el peor caso |
| R8 | **Dual-optimizer: schedule aplicado a un solo grupo** (bug clásico) | test unitario K1-6: ambos param_groups decaen; log de LR de ambos grupos cada eval |
| R9 | **Registro infantil contamina prompts enciclopédicos** (50% cuentos) | trade-off aceptado del objetivo coherencia; gate G2 tiene 2 prompts enciclopédicos; si fallan solo esos → cuentos 50%→35% |
| R10 | **Encoding Kaggle** (CLI lee code_file en cp1252) | `PYTHONUTF8=1` en el runner (lección XSPEED, ya cobrada una vez) |
| R11 | **Fertilidad del tokenizer medida sobre sample de 20MB** | re-medir bytes/token sobre el held-out REAL del run (la fórmula bpb usa el valor medido, no el nominal); dirección esperada favorable con más corpus |

---

**Cierre del pre-registro.** Este documento se congela antes de K1. Cambios posteriores van en un
`01_DESVIOS.md` append-only con fecha y razón — nunca editando las predicciones de acá.

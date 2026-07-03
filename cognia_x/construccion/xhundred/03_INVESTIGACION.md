# XHUNDRED — Documento de investigación: por qué entrenar es lento y qué se hizo al respecto

**Fecha:** 2026-07-02 (en curso) · **Goal:** ~100M params FUNCIONAL en ≤30 min en 1× T4 Kaggle,
con técnicas ESCALABLES · **Pre-registro:** `00_DISENO.md` (congelado) + `01_DESVIOS.md`
(append-only) · **Fase 2:** `02_FASE2_PLAN.md` · **Este doc:** qué se probó, qué funcionó, qué se
descartó y POR QUÉ — con números, no intuición. Se completa a medida que aterrizan K2/K3/P2.

---

## 1. Método

- **Pre-registro antes de correr**: gates de calidad (G1 bpb, G2 coherencia, G3 no-degeneración,
  G4 cloze anclado a baseline MEDIDO del 37.7M = 62.5%), predicciones por brazo, criterios de
  adopción (Δbpb > 0.01). Los desvíos van a `01_DESVIOS.md` con fecha — nunca se editan las
  predicciones.
- **Igual WALL-CLOCK por brazo** (12 min), nunca igual steps: cuando el objetivo son minutos, un
  optimizer más lento por step puede ganar por calidad-por-segundo (exactamente el caso Muon).
- **bpb normalizado por bytes** (`CE × tokens/byte ÷ ln2`): única métrica comparable entre
  vocabularios distintos (byte-256 vs BPE-16k vs BPE-32k).
- **Verificación real**: cada kernel pasa smoke local antes de gastar GPU; cada resultado se
  descarga y lee (los 3 fallos de K1 se diagnosticaron por el log crudo, no por suposición).

## 2. La raíz de la lentitud (no los síntomas)

```
wall = 6·N·D_necesario / (MFU · pico_HW) + overheads
```

Dos palancas independientes y multiplicativas:

1. **Throughput (MFU·pico).** La T4 rinde 65 TFLOPS fp16 tensor-core y 320 GB/s (ridge: 203
   FLOP/byte). Un 110M denso a seq 512: los GEMMs (~65% del step) + lm_head 32k (~23%) son
   compute-bound a d=768; la atención banded es ~4%; el resto es elementwise memory-bound.
   MFU medidos en este repo: 13.0% (9.5M), 17.1% (37.7M), **19.7% (110M, K1v4)** — el MFU sube
   con d porque los tensor cores se llenan. Pre-compile, ~49% del step era launch/elementwise-bound
   (XSPEED midió 1.95× por compile+fused). **En T4 no hay bf16 rápido (SM75 sin tensor cores bf16)
   ni fp8 (SM89+): fp16 AMP es LA precisión.** El techo práctico de esta forma en T4 ronda 20-25%
   de MFU; el resto del pico se pierde en elementwise, optimizer, atención y colas de kernel.
2. **Data-efficiency (D_necesario).** Chinchilla para 110M pide 2.2B tokens ≈ 15 h de T4:
   inalcanzable por ~36×. Todo run de 30 min es SUB-ENTRENADO estructural (0.2-0.3 tok/param).
   Por eso las palancas que cambian el juego no son de kernel sino de D_necesario:
   - **Tokenización**: byte-level procesa 1 byte/token; un BPE-32k propio rinde 4.508 B/tok
     (MEDIDO en K0 sobre held-out real) → el mismo wall ve ~4.5× más TEXTO y 4.5× más contexto.
   - **Optimizer**: Muon reporta 1.3-1.4× menos tokens al mismo loss (medido a 0.1B en
     literatura; preview propio en §4.3).
   - **Dato**: mezcla 50/50 TinyStories-español + wiki filtrada — la simplicidad compra
     gramática/token (evidencia TinyStories) y el dedup mata la deriva de plantillas del
     precedente.

**El error conceptual a evitar** (validado por la historia de este repo): tratar la velocidad
como problema SOLO de kernels. El 37.7M precedente corría a 17% de MFU con AMP+compile — el
harness ya estaba bien; su cuello real era byte-level + warmup-only + datos con plantillas.

## 3. Ledger de palancas (estado al cierre de K1)

| palanca | mecanismo | estado | evidencia |
|---|---|---|---|
| AMP fp16 + GradScaler | tensor cores (8× fp32 pico) | **ADOPTADA** | XSPEED 4.1× con gates; paridad K1v4 rel 0.00096, 0 skips |
| torch.compile default + AdamW fused | mata launch/elementwise-bound | **ADOPTADA** | XSPEED (1.95× combinado); K1: warmup 45s; **además palanca de MEMORIA** (b32 eager OOM 15.1GB vs b48 compilado 13.05GB) |
| batch 48×512 | GEMMs llenos sin OOM | **ADOPTADA** | K1v4: 19,429 tok/s, 13.05GB; b64 OOMeó solo en la cascada de K1v2 (evidencia contaminada, no re-probado en v4) |
| gather vectorizado del dataloader | 1 kernel vs loop de 48 slices | **ADOPTADA** | diseño (el loop era de xfinal); sin costo |
| BPE-32k propio (tied) | 4.5× texto/wall vs bytes | adoptada, **brazo D la falsea** | fertilidad medida 4.508 B/tok; K2-D byte-256 a igual wall |
| Muon (NS-fp16) + AdamW dual | data-efficiency (updates ortogonalizados) | **brazo K2-A decide** | K1: loss 4.61 vs 5.92 a mismos ~110 steps, overhead 17%/step; NS-fp16 invariante (0.003) |
| QK-norm + z-loss + zero-init o/w3 | estabilidad con LR agresivo en fp16 | **ADOPTADA** | paridad limpia a Muon-0.02/AdamW-3e-3; sin skips del scaler; D3: zero-init+tied da loss inicial 14.95 (prior de copia, benigno) |
| WSD (warmup 200 → constante → decay 20% final) | aterrizar el LR con el reloj | adoptada; control K2 (sched_const implícito en A?) | diseño MiniCPM/speedruns; el precedente (warmup-only) dejaba la curva orbitando |
| EMA 0.998 / LAWA k=5 | calidad gratis al final | **free-rider K2-W** | literatura (Kaddour 2022, Sanyal 2023); curva xfinal orbitaba 1.478↔1.496 |
| mezcla 50/50 cuentos+wiki | gramática/token + registro | **brazo K2-G la falsea** | TinyStories; dedup mata plantillas (causa raíz de deriva medida en el precedente) |
| banded 3:1 w=256 | −FLOPs atención + extrapolación | **ADOPTADA** (validada e2e xarch/xfinal) | bpb mejor que full Y extrapolación 0% vs +7.3%; brazo H mide variantes de implementación |
| CE chunked ×4 | no materializar logits 32k fp32 completos | **parcial** — ver D4 | tal como estaba diseñada NO ahorraba (autograd retiene los 4 chunks); checkpoint+compile usa MÁS (medido v3); v4 = chunked simple a b48 |
| curriculum de seq / fácil→difícil | — | **DESCARTADA sin brazo** | la distribución final domina; terminar en wiki restaura la deriva (00_DISENO §6) |
| vocab 16k | +8% texto/FLOP, peor calidad/token | brazo K2-E | ley de escala de vocab (V_opt≈40k para este N) |
| forma 8L×1024 | MFU mayor por GEMMs anchos | brazo K2-F | predicción: empate ±0.02 → gana d=768 por calidad/token |

## 4. Resultados medidos

### 4.1 K0 — datos (Kaggle CPU, 5.2 min)
Mezcla 256MB (147,668 docs; TinyStories-es cargó sin fallback) + wiki-solo 256MB + brazo byte
200MB. Fertilidad medida en held-out real: **32k = 4.508 B/tok** (predicción del diseño: 4.513);
16k = 4.116. La predicción de fertilidad del informe tokenizer quedó validada al 0.1%.

### 4.2 K1 — gates de ingeniería (3 intentos, 2 fallos instructivos)
- **v1 ERROR**: `kernel_sources` NO monta en `/kaggle/input/<slug>` sino en
  `/kaggle/input/notebooks/<user>/<slug>` → descubrimiento en runtime (`find_data_dir`).
- **v2 ERROR (OOM cascada)**: el "CE chunked" del diseño no ahorraba nada (autograd retiene los
  4 chunks de logits fp32 ≈ 4.8GB hasta el backward) + el caché de dynamo retiene VRAM tras un
  OOM y los brazos siguientes mueren de herencia (D4). Dato rescatado: b48+compile = 18,968 tok/s.
- **v3 ERROR parcial (lección contraintuitiva)**: checkpoint-por-chunk + compile usa MÁS memoria
  que el no-checkpoint (todos los brazos OOM donde v2 corría) — AOTAutograd+AC a b48 retiene más.
  La paridad b16 en el mismo run PASÓ (rel 5e-05) → la memoria no estaba "atascada": era el costo
  real del camino compilado con AC.
- **v4 COMPLETO (20.2 min)**: los 6 gates cerrados.

| gate | resultado |
|---|---|
| paridad fp16 vs fp32 (250 steps, LRs de v1) | rel diff **0.00096**, 0 skips → PASS |
| batch/VRAM | **b48+compile: 19,429 tok/s, MFU 19.7%, 13.05GB** → 29.1M tokens en 25 min |
| compile warmup | 45.2s → PASS (<3 min) |
| invariancia NS fp16 vs fp32 | max rel 0.0032 → PASS (Muon puede correr NS en tensor cores) |
| overhead NS por step | 17.0% → FAIL formal, PERO loss 4.61 (Muon) vs 5.92 (AdamW) a mismos ~110 steps → el gate ignoraba data-efficiency; decide K2-A a igual wall (D5) |
| dual-optimizer schedule | ambos grupos decaen → PASS |

### 4.3 K2 — ablaciones pre-registradas (98.1 min T4; 0 NaN; skips del scaler: 0 en 6 brazos, 1 en D_byte256)

Igual wall (12 min de train/brazo); métrica primaria bpb wiki held-out normalizado por bytes:

| brazo | bpb wiki | bpb cuentos | steps | veredicto (regla pre-registrada) |
|---|---|---|---|---|
| **v1_muon** (mezcla 50/50, 32k) | 1.5428 | 0.7604 | 442 | referencia |
| A_adamw_ctl (1.5e-3, wd 0.1) | 1.6147 | 0.8109 | 502 | **Muon CONFIRMADO**: Δ 0.072 (rango predicho 0.03-0.08 ✓); AdamW hizo +13% steps y perdió igual — la data-efficiency paga el 17% de overhead del NS con creces |
| D_byte256 | 1.7850 | 1.0492 | 530 | **BPE CONFIRMADO**: Δ 0.24 ≫ 0.10 predicho; muestras byte rotas (d2 0.47 vs 0.83) — la decisión estructural quedó falseada a favor con margen |
| G_wiki_solo | **1.3826** | 1.7503 | 462 | gana wiki-bpb (+0.16 la mezcla ≫ +0.05 tolerado) PERO sus muestras reproducen la deriva de plantillas ("cementerio de los Imperios… año 1267"); regla congelada → **cuentos bajan a 35%** |
| E_bpe16k | 1.5236 | 0.7635 | 482 | **PREDICCIÓN FALLIDA (honesto)**: 16k GANA a 32k por 0.019 (predicho: perdía ≤0.05) → se adopta 16k (~97.5M totales); menos head + más steps/s ganan a la calidad-por-token del 32k a este presupuesto |
| C_muon_lr04 | 1.5348 | 0.7532 | 462 | gana 0.008 < umbral 0.01 → queda LR 0.02 |
| F_8Lx1024 (~117M) | 1.5399 | 0.7629 | 445 | empate (Δ 0.003 ≤ 0.02) → queda d=768 (regla: calidad/token manda) |

**Free-rider W**: last 1.5428 / LAWA-k5 1.5486 / EMA-0.998 **2.1447** — EMA con horizonte 500
sobre ~240 steps efectivos quedó dominado por pesos tempranos (mal calibrado, como advertía la
regla) → K3 usa EMA 0.995 y elige por bpb entre {last, EMA, LAWA}.

**H micro (atención, 150 steps/variante — el diseño decía 500; recorte registrado en D9)**:
buffer-mask 15,858 tok/s · causal-full 16,705 (+5.3%, pero sacrifica banded = la pieza de
extrapolación del programa) · chunked-SWA 16,008 (+0.9%, extrapolación 512→1024 impecable:
1.9089→1.9057). Chunked pasa su gate pero +0.9% no paga la complejidad → **queda buffer-mask**.
Dato extra: mask y chunked extrapolan a 1024 MEJORANDO; causal-full empeora +0.003 (dentro del
gate) — banded 3:1 re-validada a ~100M.

**Receta final K3 (fijada por las reglas, no por gusto):** Muon 0.02 + AdamW 3e-3 dual · BPE-16k
tied (~97.5M) · mezcla 35% cuentos / 65% wiki (34 filas mix + 14 wiki-solo por batch) · d=768
12L banded mask · b48 · WSD · QK-norm/zero-init/z-loss · EMA 0.995.

### 4.4 K3 — corrida final: 97.5M params, 25.7 min total de T4 — NO FUNCIONAL (2/4 gates)

**Veredicto por la definición CONGELADA (00_DISENO §3: FUNCIONAL = G1∧G2∧G3∧G4; 3/4 =
"parcial"):** G1 ✓, G2 ✗, G3 ✗, G4 ✓ = **2/4 → NO FUNCIONAL**. Una versión previa de este doc
decía "PARCIAL" contando el gate de wall (que no es parte de la definición) — corregido por la
verificación adversarial (D9). Lo que sí quedó: gramática, compresión y wall pasan con margen;
la generación libre no-narrativa falla.

**Wall (contabilidad honesta):** setup 10.6s + train 25.0 min (el compile de 51.5s ocurre
DENTRO del primer step del train) + batería de evals 30.9s = **25.7 min TOTAL < 30** ✓ (la
preparación de datos es one-time en cognia-xh-data, pre-registrado). 1,055 steps, 25.9M tokens
(0.266 tok/param), 17,269 tok/s, 0 skips del scaler. Pesos: results_final/xh_model.pt (fp16).
Averaging: ganó **EMA-0.995** (1.2888 vs last 1.2902 vs LAWA 1.2958) — la recalibración W/D5
funcionó.

| gate pre-registrado | resultado | veredicto |
|---|---|---|
| G1 bpb wiki ≤ 1.35 (falsación >1.45) | **1.2888** | **PASS** (stretch 1.25 no alcanzado) |
| G2 coherencia ≥7/10 (checklist congelado) | **5/10** | **FAIL** — pasan 5 (los 4 de corte narrativo: zorro, sol, niño, Sofía + el enciclopédico "planetas"); fallan 5: tres del precedente (atractor "… … …" en "historia", deriva Madrid→Barcelona, ensalada técnica con griego corrupto en "ciencia"), el enciclopédico "agua" (corte final) y el descriptivo "ventana" (deriva a lista de películas en inglés) |
| G3 no-degeneración | d2 0.743 ✓, d3 0.835 ✓, pero **5/10** muestras con 4-grama ≥4 (71, 4, 9, 4, 5) | **FAIL** |
| G4 cloze-es ≥65% (precedente 62.5%) | **85.0%** — concordancia 91.7 / semántica 100 / sintaxis 100 / conocimiento 58.3 | **PASS** (supera también el stretch ≥75% de D1) |
| wall ≤30 min (gate operativo, NO parte de la definición de FUNCIONAL) | 25.7 min | **PASS** |

**Extrapolación (bonus):** bpb_wiki a 1024 = **1.2491 MEJOR que a 512** (1.2888), NTK ni hace
falta (1.2482) — banded 3:1 re-validada a ~100M por tercera vez.

**Vs el precedente 37.7M (23.2 min):** bpb wiki 1.2888 vs 1.478 (−0.19), cloze 85% vs 62.5%
(+22.5 pts), coherencia narrativa MUY superior (diálogos, arcos de cuento) — con 2 min más de
wall. Las palancas medidas (BPE, Muon, mezcla, WSD, EMA) pagaron.

**Por qué no se re-corre (anti p-hacking):** el atractor "…" no tiene bug de datos
identificable (el held-out de 2MB no contiene líneas de puntos repetidos) — es la repetición
clásica de un LM sub-entrenado en generación libre a temp 0.8. Los fallos G2 se concentran en
los registros wiki/descriptivo (el corte narrativo pasa 5/5): a 0.266 tok/param el registro
difícil (hechos, fechas, tecnicismos) no llega, mientras el narrativo (simple,
TinyStories-style) generaliza — la lógica TinyStories que motivó la mezcla. La contingencia
pre-registrada §8-R4 (subir cuentos) empeoraría los registros que fallan, así que no se aplica
(anotado en D7). **Este es el límite honesto del goal de 30 minutos**: un ~100M en 25.7 min
queda fuerte en gramática (cloze 85%), compresión (bpb 1.29) y narrativa libre; NO alcanza la
definición congelada de FUNCIONAL porque la generación libre no-narrativa degenera — eso pide
más tokens de wall, no otra receta.

### 4.5 Fase 2 — QLoRA sobre Qwen2.5-3B-Instruct: GANA el nicho pre-registrado, sin milagros

Ya establecido con aritmética (00_DISENO §7): pretrain 3B desde cero en T4 = 641 días GPU
(Chinchilla) + 48GB de estados vs 15.6GB — INVIABLE por doble muro. "Qwen3-3B" NO existe (se usó
Qwen2.5-3B-Instruct NF4 y se declara). Lo viable era ESPECIALIZAR: QLoRA r=16 all-linear sobre
gsm8k-ES (85%) + OpenHermes-es (15%), 45 min de train (0.5 épocas, 1.15M tokens — la condición
de ≥1.5 épocas NO se cumplió por el costo del gradient checkpointing; se reporta, D8).

**Base medido (P2-K1, 37.4 min):** MGSM-es 0-shot 39.6/45.6 (estricta/laxa), 3-shot 69.2,
XSC 65.3. Belebele exigió diagnóstico (D6): el formato continuación-NLL del plan daba 35.2%
(gate GP2-1 FAIL); el diagnóstico de 3 formatos (200 ítems) dio letra-NLL 74.5% — causa raíz
del gate encontrada y el formato letra adoptado para AMBOS lados.

**Deltas (adapter − mismo checkpoint base, mismo harness NF4; P2-K2, 106.9 min):**

| pre-registro | Δ medido | veredicto |
|---|---|---|
| P1 MGSM 0-shot estricta (+10..+18, gate ≥+6) | **+14.8** (39.6→54.4) | **GANA** (4.7×SE) |
| P2 MGSM 0-shot laxa (+6..+12, gate ≥+4) | **+9.6** (45.6→55.2) | ✓ no-solo-formato |
| P3 control 3-shot (+2..+8) | **−15.2** (69.6→54.4) | **predicción FALLIDA** |
| P4 XSC (empate ±2) | −0.4 | ✓ |
| P5 Belebele-letra (−4..+2) | −2.6 (75.7→73.1) | ✓ no-catástrofe |

**Sesgo de truncación (regla del plan §2, anotado por la verificación adversarial):** el base
truncó 28/250 = 11.2% de sus respuestas 0-shot a 384 tokens (divaga sin la convención `####`);
el adapter, 3/250 = 1.2%. La regla pre-registrada exige anotarlo como sesgo CONTRA el modelo
que trunca: parte del Δ+14.8 refleja que el base no termina a tiempo, no solo que razona peor.
El Δ laxa (+9.6) y la comparación 3-shot (donde el base trunca menos, 7.2%) acotan el efecto,
pero el número primario queda declarado con este asterisco.

**Lectura honesta (reglas congeladas §4 del plan):** el QLoRA de 45 min en T4 SÍ supera al
mismo Qwen2.5-3B en el nicho y protocolo pre-registrados (0-shot instruido), sin catástrofe
general — el "sí se puede" de la Fase 2, con el asterisco de truncación de arriba. PERO el P3
negativo revela el mecanismo: el adapter FIJA el modo 0-shot (su 3-shot colapsa a su 0-shot) y
el techo del base con exemplars (69.6) queda por encima del FT en cualquier modo. Conclusión:
**QLoRA-en-T4 compra especialización de modo/formato/idioma, no razonamiento nuevo** —
exactamente lo que la lista de honestidad del plan prohibía sobre-reclamar. Higiene verificada
activa: decontaminación train∩test = 0 por hash normalizado; calidad gsm8k-ES 0/20 malos.
Desvíos de config declarados (D9): AdamW-fp32 en vez de paged_8bit; GC ON en vez de sin-GC.

## 5. Descartado con evidencia (no re-medir sin razón nueva)

- **Alternativas a backprop** (exp049, medido 3 seeds, este repo): PC calidad 0.993 de BP a
  4.26× wall; EqProp 4.94×; DTP 2.32×; DFA 1.17× y frágil; FF 0.944 (<0.95); ES 0.484. Con un
  budget de 30 min, TODA alternativa que pague ≥1.17× wall es estrictamente peor: BP+AMP domina
  por COSTO, no por calidad. Cero brazos gastados acá — la evidencia ya existía.
- **bf16 en T4**: SM75 no tiene tensor cores bf16 (descarte por arquitectura); la medición limpia
  de su velocidad no se logró (OOM eager a b48, D5) y se declara.
- **fp8**: requiere SM89+. Imposible en T4, punto.
- **DataParallel 2×T4** (XSPEED, medido): más lento que 1 GPU a esta escala.
- **torch.compile max-autotune** (XSPEED, medido): 97.1k < 109.6k default + 176s warmup.
- **gradient checkpointing** (XSPEED, medido): palanca de memoria a 1.19× de costo — no hace
  falta a b48. Y su variante CE (checkpoint del head) EMPEORA con compile (D4/D5, medido).
- **batch >48**: b64 OOM medido (13.05GB era el techo real con margen).
- **grad accum**: solo amortiza el optimizer step (~2%) si el batch YA cabe — no usar.
- **Sophia** (no replica con baseline tuneado, 2509.02046), **SOAP/Shampoo** (eigendecomp fp32
  sin TC en T4), **Adafactor/Adam-mini** (ahorran memoria que no falta).
- **Tokenizers ajenos**: GPT-2 rinde 2.915 B/tok en español (medido) vs 4.508 del propio; XLM-R
  requiere 192M de embeddings.
- **Curriculum fácil→difícil / seq-len warmup**: descartado por diseño (la distribución final
  domina el estado; predicción pre-registrada anotada por si alguien lo prueba).

## 6. Lecciones de sistema (lo que no está en los papers)

1. **compile es palanca de MEMORIA, no solo velocidad**: inductor planifica buffers; el mismo
   modelo a b32 eager OOMea (15.1GB) donde b48 compilado usa 13.05GB.
2. **"CE chunked" ingenuo es un placebo**: si los chunks quedan en el grafo, la retención total
   es idéntica. Y checkpointearlos bajo compile RETIENE MÁS. La solución barata real fue bajar a
   b48 y aceptar los logits retenidos.
3. **El allocator importa**: `expandable_segments:True` + `hard_cleanup()` (dynamo reset + gc +
   empty_cache) entre brazos evitó el efecto dominó post-OOM.
4. **zero-init + tied head = prior de copia** (D3): loss inicial ≈ ‖e‖²/RMS ≈ 15.4, no ln(V).
   Benigno (cae a 5.9 en 110 steps) pero rompe el check de sanidad clásico — derivarlo antes de
   asustarse.
5. **Los gates de un solo número mienten**: el gate "overhead NS <10%" habría matado a Muon,
   que a mismos steps lleva 1.3 nats de ventaja. El gate correcto es SIEMPRE a igual wall-clock.

## 6b. Reproducción (entregable 2: pipeline ≤30 min en T4)

```
# one-time: corpus + tokenizers (kernel CPU de Kaggle, ~6 min, sin quota GPU)
venv312\Scripts\python.exe cognia_x/construccion/xhundred/run_kaggle_xh.py push data
# la corrida final (T4, 25.7 min medidos: train 25 min + gates G1-G4 + pesos fp16)
venv312\Scripts\python.exe cognia_x/construccion/xhundred/run_kaggle_xh.py push final
venv312\Scripts\python.exe cognia_x/construccion/xhundred/run_kaggle_xh.py download final
```
Receta completa en las constantes de `xh_final_kernel.py` (fijadas por las ablaciones K2, no a
mano). Smokes locales: cada kernel corre con `--smoke` sin GPU. Los resultados crudos quedan en
`results_{bench,ablate,final}/`; los de K0 son el output del kernel cognia-xh-data (copia local
de tokenizers/meta/vals en `_check_k0/`).

## 7. Conclusión honesta

### 7.1 El goal duro, contra sus propios gates

Un modelo de **97.5M params quedó entrenado en 25.7 minutos TOTALES de una T4** (incluyendo
compile y la batería de evaluación). Contra la definición congelada, el veredicto es
**NO FUNCIONAL: 2/4 gates** (G1 compresión ✓ 1.2888, G4 cloze 85% ✓, G2 coherencia libre ✗
5/10, G3 no-degeneración ✗ 5/10) — el pre-registro exigía los cuatro y ni siquiera se alcanzó
el 3/4 de "parcial". Lo que el modelo SÍ demostró en esos 25.7 min: gramática y selección
léxica excelentes (cloze 85% vs 62.5% del precedente y 33% de azar), compresión mejor que el
precedente por 0.19 bpb, y narrativa libre coherente con diálogos y arcos. Lo que no: la
generación libre wiki/descriptiva degenera. No se maquilló: a 0.27 tokens/param el registro
difícil pide más minutos de wall, no otra receta. El "≤30 min" se cumplió con margen; el
"funcional", según sus propios gates, NO.

### 7.2 La raíz de la lentitud, respondida

El wall de entrenamiento es `6·N·D_necesario / (MFU·pico)` y las DOS palancas se midieron:

- **MFU (síntomas de kernel):** de 17% (precedente) a 19.7% con compile+fused+batch correcto —
  y el hallazgo de que compile es también palanca de MEMORIA. Pero el techo práctico en T4 a
  esta escala ronda 20-25%: por acá ya no había 2× más.
- **D_necesario (la raíz de verdad):** acá vivía todo lo grande. Tokenización BPE propia
  (+0.24 bpb vs bytes a igual reloj — LA palanca estructural), Muon (+0.072 vs AdamW tuneado
  que hizo 13% MÁS steps), mezcla de datos con motor de coherencia (TinyStories-es), WSD+EMA.
  **Sobre un harness que ya tiene los kernels optimizados (AMP+compile+fused, el 4.1× de
  XSPEED), todo el margen restante vino de data-efficiency** — la inversa de la intuición con
  la que se suele atacar. (Los porcentajes exactos no son medibles: mezclan unidades — Δbpb vs
  tok/s; lo medible es que ninguna palanca de kernel restante daba >1.25× y las de datos
  movieron el bpb 0.07-0.24 a igual reloj.)

### 7.3 Fase 2, sin autoengaño

"Superar a Qwen3-3B" era imposible de enunciar (ese modelo no existe) e imposible de cumplir en
general (36T tokens de pretrain vs nuestro presupuesto: 6 órdenes de magnitud). Lo que SÍ se
logró, pre-registrado: **un QLoRA de 45 min supera al mismo Qwen2.5-3B-Instruct en el nicho
elegido (+14.8 pts MGSM-es 0-shot, 4.7×SE; con el asterisco de truncación de §4.5) sin
catástrofe general** — y la evidencia de sus
límites quedó igual de clara: el adapter fija el MODO (su capacidad few-shot se degrada −15.2)
y no expande el techo de razonamiento del base. QLoRA-en-T4 = especialización, no inteligencia
nueva. Para cerrar la brecha real contra un 3B moderno harían falta ~10⁴× más cómputo de
pretrain — no hay receta que lo esquive.

### 7.4 Teoría CogniaX: validado / descartado / abierto

**Validado con números nuevos:**
- Banded 3:1 como pieza de contexto largo: tercera validación e2e, ahora a ~100M — la
  extrapolación 512→1024 MEJORA el bpb (1.2888→1.2491) sin NTK.
- "Data-efficiency es palanca de velocidad" (la tesis M0): confirmada como LA palanca (BPE,
  Muon, mezcla — §7.2).
- "El grokking propio es costo de convergencia evitable": X1 falseó "pagar el plateau" **en el
  harness propio (tarea MQAR, como acota el pre-registro)** — init-scale α=0.25 grokea en 900
  steps vs 3600 (−75%) con calidad final comparable (0.975 vs 0.989); y de paso mostró que
  nuestro fenómeno es abrupt-learning (el gap no adelanta), no grokking post-overfit.
- El método mismo: pre-registro + gates + igual-wall + desvíos append-only cazó **5**
  predicciones fallidas propias (16k>32k, α-grande-acelera, gap-no-adelanta, EMA-0.998-pierde,
  P3-negativo) y 4 bugs de sistema — sin él, cada uno habría sido una conclusión falsa o un
  OOM misterioso. Y la verificación adversarial final cazó al propio documento inflando el
  veredicto de K3 (D9).

**Descartado con evidencia:**
- Alternativas a backprop para ESTE régimen (exp049: todas ≥1.17× wall — con 30 min, BP+AMP
  domina por costo).
- bf16/fp8 en T4 (arquitectura), checkpointing-del-CE bajo compile (usa MÁS memoria — lección
  K1v3→v4, D9), batch 64 (OOM solo en la cascada K1v2, evidencia contaminada; b48 es lo medido
  limpio), DataParallel 2×T4, curriculum fácil→difícil, byte-level para este presupuesto,
  Sophia/Lion/SOAP (evidencia externa + prioridad), fusión-de-logits como calibrador (pendiente
  X4, pero la evidencia externa ya carga contra).

**Cerrado después (2026-07-03, programa MoM X1-X4 — detalles en 04_MOM_GROKKING §8-9):**
- X2: ningún acelerador de paper transfiere (grokfast MATA la transición, stablemax la
  retrasa 3×, Muon no grokea el tiny que Muon-gana-en-LM) — todo se mide en el harness propio.
- X3: el MoM DENSO PAGA — experto ~100M gana su nicho en 3/3 dominios (≥0.10 bpb congelado) y
  el LoRA-control no lo empata; fuera de nicho se derrumba (el selector es estructural).
- X4: el calibrador ES un selector (n-grams estático ≈ oracle en 2/3 dominios; la fusión
  cuesta 4× y el bandit no converge a 90 queries — predicción formal fallida y declarada).

**Abierto (con experimento definido):**
- X5 (nicho-grokking real con D_crit): condición pre-registrada no cumplida, pre-registro
  intacto en 04 §6 por si aparece razón nueva.
- El registro enciclopédico del 100M: ¿cuántos minutos más pide? (la curva seguía cayendo
  fuerte al corte — hay pendiente sin cosechar).
- Export GGUF de la arquitectura banded para servir en la red Cognia (P6 de 04_MOM_GROKKING).
- Construcción del MoM real (flota de expertos + selector integrado): fase nueva, con la
  receta y los veredictos de este programa como base.

### 7.5 La lección de método (para la próxima corrida)

De 10 lanzamientos GPU, 4 fallaron (K1 v1/v2/v3 y P2-K2 v1) — y los 4 diagnósticos salieron del
log crudo, no de teoría: mount path de Kaggle, retención de logits del CE, AC+compile que
retiene más, activaciones sin GC en el 3B. El costo total de esos fallos fue ~1h de GPU y cero
conclusiones falsas, porque los resultados parciales se guardaban incrementalmente y los gates
estaban escritos ANTES. Ese es el retorno del método: los errores cuestan tiempo, no verdad.

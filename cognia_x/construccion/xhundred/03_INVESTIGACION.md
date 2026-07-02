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
| batch 48×512 | GEMMs llenos sin OOM | **ADOPTADA** | K1v4: 19,429 tok/s, 13.05GB; b64 OOM (medido) |
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

### 4.3 K2 — ablaciones pre-registradas (7 brazos + H micro)
**[PENDIENTE — corriendo en T4]** Predicciones congeladas en `00_DISENO.md` §5.

### 4.4 K3 — corrida final ≤30 min con gates G1-G4
**[PENDIENTE — tras veredicto K2]**

### 4.5 Fase 2 — QLoRA 3B (P2-K1 corriendo / P2-K2 listo)
**[PENDIENTE]** Plan y predicciones P1-P5 congeladas en `02_FASE2_PLAN.md`. Ya establecido con
aritmética (00_DISENO §7): pretrain 3B desde cero en T4 = 641 días GPU (Chinchilla) y 48GB de
estados vs 15.6GB disponibles — INVIABLE por doble muro; "Qwen3-3B" no existe (se usa
Qwen2.5-3B-Instruct y se declara).

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
- **Tokenizers ajenos**: GPT-2 rinde 2.915 B/tok en español (medido) vs 4.68 propio; XLM-R
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

## 7. Conclusión honesta
**[PENDIENTE — al cierre de K3 y Fase 2]** Qué de la teoría CogniaX se validó, qué se descartó,
qué queda abierto.

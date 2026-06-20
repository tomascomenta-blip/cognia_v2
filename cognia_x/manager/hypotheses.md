# hypotheses.md — hipótesis + evidence ledger de Cognia-X

> Formato fijo (ver `00_protocolo_investigacion.md` §4). Toda hipótesis es falsable.
> Estado ∈ {abierta, apoyada, refutada, mixta}. Nunca borrar; revisar añadiendo.

---

### H-MEZ-1
- **Enunciado:** la atención full (O(L²)) es el cuello de botella de escalado en CPU; un
  mezclador de tiempo lineal (O(L)) la domina en coste de tiempo y memoria.
- **Predicción medible:** el mezclador lineal será ≥1× más rápido que la atención full en todo
  L≥128 y la brecha crecerá con L; la memoria del intermedio dominante de la atención crecerá
  O(L²) y la del lineal será ~constante. Se refutaría si el lineal no ganara o si la atención no
  mostrara régimen cuadrático.
- **Estado:** **apoyada (para coste)**.
- **Confianza:** alta (sobre coste); N/A sobre calidad.
- **Evidencia a favor:** exp001 — speedup 3.5×→70.3× (L 128→4096); memoria 4×→4096×; régimen
  cuadrático confirmado (×4 L → ×19.6 tiempo).
- **Evidencia en contra:** ninguna sobre coste. Caveat: exp001 no mide calidad; el sub-cuadrático
  podría perder recall (a probar en exp002).
- **Veredicto adversarial:** holds=true para la afirmación de coste, restringida a mezcla global
  no-causal con d=64. NO generaliza a "reemplazar atención" sin evidencia de calidad.
- **Experimento:** exp001 (corrido) ✅ ; exp002 (calidad) pendiente.

---

### H-MEZ-2 (derivada de exp001)
- **Enunciado:** en CPU, una asíntota mejor no basta: la implementación (vectorización, layout de
  memoria) puede invertir el orden esperado entre dos mezcladores O(L).
- **Predicción medible:** un SSM O(L) con scan en bucle Python será más lento que una atención
  lineal O(L·d²) vectorizada a longitudes moderadas.
- **Estado:** **apoyada.**
- **Confianza:** alta (en este micro-bench).
- **Evidencia a favor:** exp001 — ssm-loop 10.61 ms vs linear 6.85 ms a L=4096 pese a misma asíntota.
- **Evidencia en contra:** un scan fusionado (no Python) probablemente revierte el resultado;
  esto mide la implementación naïve, no el límite del método. → matiz importante.
- **Veredicto adversarial:** holds=true como advertencia metodológica ("no optimizar solo la
  asíntota"); NO como veredicto sobre SSM en general.
- **Experimento:** exp001 ✅.

---

### H-MEZ-3
- **Enunciado:** la capacidad de recall asociativo exacto de un mezclador de estado acotado
  (atención lineal, estado d×d) está limitada por su **tamaño de estado**; la atención full tiene
  capacidad ~L (número de posiciones direccionables).
- **Predicción medible:** la accuracy del lineal cae bajo 0.9 al crecer N, con capacidad que
  crece con el tamaño del estado; la atención full se mantiene ~1.0. Refutable si el lineal no se
  degradara o su capacidad no escalara con d.
- **Estado:** **apoyada.**
- **Confianza:** alta.
- **Evidencia a favor:** exp002 — capacidad lineal {d=32:32, 64:128, 128:512} = **d²/32**
  (escala con el tamaño de estado d²); full ~1.0 en todo el rango.
- **Evidencia en contra:** es una sonda representacional sin entrenar; un modelo entrenado podría
  comprimir asociaciones, pero el techo por estado acotado es estructural (pigeonhole).
- **Veredicto adversarial:** holds=true. El escalado con d² es robusto; la constante depende del
  umbral.
- **Experimento:** exp002 (corrido) ✅.

---

### H-MEZ-4 (hipótesis de diseño, derivada de exp001 + exp002)
- **Enunciado:** una pila **híbrida** (mayoría de capas lineales O(L) + unas pocas capas de
  atención full) puede acercarse al **coste** del lineal y al **recall** de la atención full,
  capturando lo mejor del trade-off coste↔capacidad.
- **Predicción medible:** con k capas full sobre m capas lineales (k≪m), el coste por token será
  ≈ el del lineal puro (+ O(k) penalización), y el recall asociativo será ≫ el del lineal puro,
  acercándose al full. Refutable si el híbrido no mejorara el recall del lineal, o si su coste se
  acercara al del full.
- **Estado:** **apoyada (eje coste)**; recall del stack aún por medir end-to-end.
- **Confianza:** alta en coste; media en el conjunto (recall inferido de exp002, no medido en stack).
- **Evidencia a favor:** **exp005 (propio): híbrido 3/24 full = ~12-15% del coste de decode del
  full puro a L=8192; lineal puro ~constante en L, full puro ~lineal en L.** + exp001 (coste lineal
  ≪ full) + exp002 (recall full ≫ lineal) + literatura Jamba/Griffin/NVIDIA-Hybrid.
- **Evidencia en contra:** a contexto corto (L=512) el ahorro es modesto (k=3 ≈ 28% del full); el
  payoff depende de L grande. El recall del stack híbrido no se midió (se infiere de exp002).
- **Veredicto adversarial:** eje coste sostenido y verificado (re-corrido). Falta cerrar el eje
  recall con un experimento multi-capa entrenado/construido.
- **Experimento:** exp005 ✅ (coste); recall del stack → ciclo-3.

---

### H-CEIL-1 (CYCLE 22 — registrada por el Investigation Engine, status='mixta')
- **Enunciado:** el recall asociativo de un mezclador de **estado fijo** (atención lineal) está
  acotado por el **tamaño de su estado**; añadir atención (estado ∝ longitud) lo levanta — la
  frontera recall↔throughput.
- **Predicción medible:** Lineal: recall crece con el estado (~d²) y satura. Híbrido/atención: recall
  ~independiente de la carga. **REFUTADO si** el lineal mantiene recall alto sin importar carga/estado,
  o el híbrido no supera al lineal en el régimen saturado.
- **Estado:** **mixta.**
- **Confianza:** media.
- **Evidencia a favor:** [[arXiv:2402.18668]] (Based: tradeoff estado↔recall, frontera de Pareto,
  +6.22 pts) + exp002 (recall lineal ~d²) + exp009 (recall lineal SUBE con d: 0.059@d8 → 0.183@d24;
  el híbrido separa a d=48: 0.292 vs 0.181, gap +0.111).
- **Evidencia en contra:** [[arXiv:2508.19029]] (Okpekpe&Orvieto: gran parte de la brecha es de
  OPTIMIZACIÓN, no expresividad; con LR ajustado Mamba resuelve recall aun en 1 capa) + exp009 (el
  lineal SATURA ~0.18, MUY por debajo del d² ideal → la cota EFECTIVA no es d²). **exp009 es AMBAS:**
  apoya la subida con d y refuta que la cota efectiva sea d².
- **Veredicto adversarial:** HOLDS direccionalmente (recall escala con el estado; la atención lo
  levanta) PERO la cota EFECTIVA en modelos entrenados chicos es la **capacidad del feature-map**
  (<< d²), no el d² teórico. Distinción real (cota informacional d²) vs asumido (capacidad entrenada
  limitada por optimización/feature-map).
- **Experimento:** exp009_recall_ceiling (corrido, seed=0, 6000 steps) ✅.
- **Registro:** poblada por `cognia_x/research/cycles/cycle22_recall_ceiling.py` vía
  `HypothesisRegistry.mark_mixta` (mismo gate DoD que apoyada/refutada).

---

### H-CEIL-2 (CYCLE 23 — registrada por el Investigation Engine, status='refutada')
- **Enunciado:** el plateau del recall lineal entrenado (~0.18, exp009) se levanta **ENSANCHANDO** el
  feature-map de la atención lineal (lever "feature dimension" de Based).
- **Predicción medible:** a d fijo, un feature-map más ancho (mult>1) da **mayor** recall entrenado que
  el baseline ELU+1. **REFUTADO si** el ancho no mueve el recall.
- **Estado:** **refutada.**
- **Confianza:** media.
- **Evidencia a favor:** [[arXiv:2402.18668]] (Based: la dimensión del feature-map es el lever para
  recorrer la frontera recall-memoria).
- **Evidencia en contra:** exp010 (d=24 fijo, lineal_puro, step-parity 6000 steps, seed0, chance
  0.0625): ensanchar el ELU+1 ×4 → estado **576 → 9216 (16× más estado)** y el recall NO sube:
  **mult1=0.181 vs mult4=0.181 (Δ +0.000; corridas más cortas dieron −0.002..+0.005, todas en el ruido ~0.01)**.
- **Veredicto adversarial:** REFUTADA para el ANCHO: mult=4 da 16× más estado y el recall casi no se
  mueve. Esto además **REFUTA** que el plateau sea un límite de tamaño de estado/capacidad cruda, y
  APUNTA a la **FORMA del feature-map (kernel)** y/o optimización/init: Based usa kernel **Taylor** (no
  ELU+1 ancho), Trockman usa **mimetic init**. El fracaso afina la pregunta → H-CEIL-3.
- **Experimento:** exp010_feature_dim (corrido, seed=0, step-parity 6000 steps) ✅.
- **Registro:** poblada por `cognia_x/research/cycles/cycle23_feature_dim.py` vía
  `HypothesisRegistry.mark_refuted` (mismo gate DoD que apoyada/mixta — no se debilitó la compuerta).

---

### H-CEIL-3 (CYCLE 23 generó → CYCLE 24 REFUTÓ, status='refutada')
- **Enunciado:** el plateau del recall lineal se levanta con un **KERNEL más rico** (feature-map
  Taylor/2do orden, Based) y/o **mimetic init** (Trockman 2024) **a presupuesto de pasos igual** — NO
  con el mero ancho del ELU+1.
- **Predicción medible:** un feature-map Taylor (o init mimética) sube el recall lineal entrenado por
  encima de ~0.18 a d fijo, con steps iguales. **Refutado si** tampoco lo mueve.
- **Estado:** **refutada** (CYCLE 24).
- **Confianza:** media.
- **Evidencia a favor:** [[arXiv:2402.18668]] (Based: el kernel Taylor 2do orden es el más efectivo en
  recall MQAR) + [[arXiv:2410.11135]] (mimetic init desbloquea recall ya presente en SSMs). La
  literatura PREDECÍA que ayudaría — y NO se cumplió a esta escala.
- **Evidencia en contra:** **exp011** (d=24 fijo, n_heads=1, n_pairs=16, seed0, steps=3000 step-parity,
  chance 0.0625, params idénticos en los brazos sin proyección): baseline ELU+1=**0.173**;
  **taylor=0.160 (Δ −0.013, por DEBAJO del baseline)**; elu_matched (dim 336 ≈ dim 325 de Taylor,
  control de TAMAÑO)=0.181 (Δ +0.008, ruido); **mimetic=0.183 (Δ +0.0098, < umbral 0.02 → ruido)**.
  taylor_vs_matched = −0.021 (el Taylor quedó por debajo del ELU de su misma dim).
- **Veredicto adversarial:** REFUTADA a esta escala para AMBOS levers. La FORMA del kernel (Taylor) no
  solo no levanta el plateau — lo baja levemente, y queda por debajo del ELU+1 size-matched (el
  control aísla forma de tamaño: no es que falte estado). La INIT mimética da el mayor Δ positivo
  (+0.0098) pero NO cruza el umbral de ruido. Junto con exp010 (ancho refutado), el plateau ~0.18 del
  lineal puro a d=24 es robusto a **ancho, forma e init** → el cuello es más profundo (no del
  feature-map). El fracaso afina la pregunta → **H-CEIL-4**.
- **Experimento:** exp011_kernel_init (corrido, seed=0, steps=3000 step-parity) ✅.
- **Registro:** marcada por `cognia_x/research/cycles/cycle24_kernel_init.py` vía
  `HypothesisRegistry.mark_refuted` (mismo gate DoD; el ciclo DERIVA el veredicto de results.json).
  Corroboración independiente: un agente paralelo reprodujo el null de Taylor (elu=0.173 vs taylor=0.166)
  en `cognia_x/experiments/exp011_taylor_kernel/` (2 brazos, sin control de tamaño ni init).

---

### H-CEIL-4 (CYCLE 24 generó → CYCLE 25 MIXTA, status='mixta') — la línea H-CEIL CONVERGE
- **Enunciado:** el cuello del recall lineal entrenado a d≤48 es de **PROFUNDIDAD/ESCALA/OPTIMIZADOR** —
  o requiere la capa de **ATENCIÓN del híbrido** (el mezclador de estado fijo no llega).
- **Predicción medible:** subir profundidad/d/steps, o el optimizador, o añadir atención, sube el recall
  por encima de ~0.18. exp012 testea profundidad/d/optim (la atención ya está apoyada en CYCLE 6).
- **Estado:** **mixta** (CYCLE 25).
- **Confianza:** media-alta.
- **Evidencia a favor (rama "requiere atención"):** CYCLE 6 / H-MEZ-4 (a np=8 el lineal satura 0.255 y
  el híbrido recupera 0.998) + exp009 (el híbrido separa a d=48: 0.292 vs 0.181) + [[arXiv:2402.18668]]
  (la frontera recall↔memoria se cruza con atención). La atención SÍ levanta el techo.
- **Evidencia en contra (rama "profundidad/escala/optim"):** **exp012** (lineal PURO, n_pairs=16, seed0,
  steps=3000 step-parity): baseline 0.173; **lin_d24_L8=0.181 (Δ+0.0075)**, **lin_d48_L4=0.183
  (Δ+0.0093)**, **lin_d24_L4_hi(LR 3×)=0.176 (Δ+0.0025)** — NINGUNO cruza el umbral 0.02. Ni profundidad
  ni escala-d ni optimizador suben el lineal puro. (Okpekpe&Orvieto predecía que el tuning lo
  arreglaría → refutado a esta escala.)
- **Veredicto adversarial:** MIXTA. La rama lineal (profundidad/escala/optim) queda REFUTADA; la rama
  "requiere atención" queda APOYADA por **eliminación** — el plateau ~0.18 del mezclador de estado fijo a
  d≤48 es robusto a **SEIS levers no-atención** (ancho exp010; forma del kernel + init exp011;
  profundidad + escala-d + optimizador exp012). El techo es **ESTRUCTURAL** (cota: pigeonhole sobre el
  estado fijo, exp002 ~d²; + la cota efectiva entrenada robusta a todo tuning probado), no una brecha de
  optimización. **La línea H-CEIL CONVERGE:** el remedio del recall a carga alta es ARQUITECTÓNICO (la
  atención del híbrido, D-CEIL-1/D-007), no afinar el mezclador lineal. Decisión: **D-CEIL-4**.
- **Experimento:** exp012_depth_scale (corrido, seed=0, steps=3000 step-parity) ✅.
- **Registro:** marcada por `cognia_x/research/cycles/cycle25_depth_scale.py` vía `mark_mixta` (mismo
  gate DoD). El techo pasó a `real_or_assumed='real'` (estructural) → backlog de asumidos = 0.

---

### H-HYB-1 (CYCLE 26 generó → CYCLE 27 REFUTÓ, status='refutada') — autocorrección honesta
- **Enunciado:** a d chico (24), el recall del híbrido cierra la brecha con la atención pura si se le da
  más **BUDGET** (el 0.18 de exp013 sería under-training).
- **Predicción medible:** con más steps (10000, 3.3×), hibrido_h4 a d=24 sube ≫ 0.18 hacia la atención
  pura. **Refutado si** sigue ~0.18.
- **Estado:** **refutada** (CYCLE 27).
- **Confianza:** media.
- **Evidencia a favor:** CYCLE 6 (el híbrido recupera recall a d=64: 0.99) → predecía que a d=24 también
  cerraría con más budget. **No se cumplió.**
- **Evidencia en contra:** **exp014** (d=24, n_heads=4, n_pairs=16, seed0, steps=**10000**, 3.3× el budget
  de exp013): **hibrido_h4 = 0.186 — PLATEÓ** (0.180@4000 → 0.186@7500 → 0.186 final, PLANO; no
  under-training) vs atencion_h4 = 0.948. El híbrido interleaved a d=24 NO recupera recall.
- **Veredicto adversarial:** REFUTADA. Con 3.3× el budget el híbrido sigue en el plateau ~0.18 — **CORRIGE
  el diagnóstico de CYCLE 26** (lo llamé "under-training" porque a 3000 steps ascendía; era el comienzo de
  un plateau DURO). Las 2 capas LINEALES (baja capacidad a d=24, ~0.18) **BLOQUEAN** el recall que la
  atención pura sí logra. Esto **ACOTA H-MEZ-4** (el híbrido recuperaba a d=64): la recuperación del híbrido
  es **d-dependiente**. Genera **H-HYB-2**. (Lección de proceso: confirmar el "under-training" con más
  budget ANTES de cerrar — directiva v3 §4.2.)
- **Experimento:** exp014_hybrid_budget (corrido, seed=0, steps=10000) ✅.
- **Registro:** marcada por `cognia_x/research/cycles/cycle27_hybrid_budget.py` vía `mark_refuted`.

---

### H-HYB-2 (CYCLE 27 — generada por el fracaso de H-HYB-1, status='abierta')
- **Enunciado:** la recuperación de recall del híbrido es **d-dependiente**: a d chico (24) las capas
  LINEALES (recall ~0.18) bottleneckean el recall que las de atención darían; a d=64 (CYCLE 6) no. El
  cuello es la capacidad de las capas lineales y/o el ARREGLO (lineal-primero destruye la asociación
  clave-valor antes de la atención).
- **Predicción medible:** subir d (24→48→64), o poner la atención PRIMERA (no lineal-primero), o subir el
  ratio de atención hace que el híbrido cruce el plateau a esta carga. **Refutado si** ninguna lo mueve.
- **Estado:** **abierta** (sin experimento aún).
- **Confianza:** baja.
- **Evidencia a favor:** CYCLE 6 (híbrido funcionó a d=64) + exp014 (falló a d=24) → contraste que apunta a d.
- **Evidencia en contra:** — (sin experimento aún).
- **Veredicto adversarial:** — (pendiente).
- **Experimento:** pendiente → barrer d / arreglo (atención-primero) / ratio del híbrido a n_pairs=16.
- **Registro:** añadida por `cognia_x/research/cycles/cycle27_hybrid_budget.py` (`status='abierta'`).

---

## Ciclo-1 (workflow de 13 agentes) — hipótesis verificadas adversarialmente (2026-06-17)

24 hipótesis generadas por 6 investigadores con evidencia web; cada una atacada por un
verificador adversarial. **Las refutadas (holds=false) son tan valiosas como las apoyadas:**
marcan dónde la intuición/literatura se sobre-extiende. Confianza = del veredicto adversarial.

**Prioridad P0 (mejor relación impacto/coste, todas CPU-feasibles):** H-SEQ-3, H-BW-1, H-CF-2.

| ID | Enunciado (resumen) | Veredicto | Conf | Nota clave del verificador |
|----|---------------------|-----------|------|----------------------------|
| H-REP-1 | latencia ∝ 1/(bytes por paso), embedding aporta <5% | ❌ false | media | confunde embedding de ENTRADA con lm_head O(V). **exp006 ✅: input embed ~10⁴× más barato; lm_head = 1 bloque a V≈26k** |
| H-REP-2 | patching BLT no recupera overhead a 1-3B en CPU | ✅ true | media | BLT a 1B arranca peor que BPE-Llama2; gana solo a 7B+ |
| H-REP-3 | BPE parity-aware sin coste de inferencia extra | ❌ false | media | la paridad suele comprarse ampliando vocab → infla softmax O(V) |
| H-REP-4 | cuantizar embedding+head 8-bit: >10% RAM, ΔPPL<1% | ✅ true | media | **exp006:** 25-37% solo a vocab grande (≥131k) o sin tying; a vocab moderado tied es 1-10% |
| H-SEQ-1 | Transformer cae >40% tok/s a 8K; cruce SSM 1K-4K | ❌ false | media | premisa bandwidth correcta; números inventados (caída real ~-37% recién a 110K) |
| H-SEQ-2 | recall full >95% e híbrido 7:1 hasta N grande | ❌ false | media | 1ª mitad sólida; 7:1 es el borde que la evidencia desaconseja (3:1-6:1) |
| **H-SEQ-3** | **SWA (W~1024) conserva calidad, KV O(L)→O(W), ↑tok/s** | ✅ **true** | **alta** | Gemma-3 producción: KV 60%→<15% a 32K sin perder perplejidad |
| H-SEQ-4 | óptimo es híbrido 6:1 SSM:SWA, domina Pareto 2K-16K | ❌ false | media | dirección híbrido correcta; 6:1 y "SSM:SWA" sobre-especificados |
| **H-BW-1** | **decode bandwidth-bound: hilos 2→4 <30%; bytes/peso↓→tok/s↑** | ✅ **true** | **alta** | **medido en i3-10110U (vault):** spec decode 5× más lento pese a 90.8% accept; 3 hilos > 4; techo ~8 tok/s 3B Q4_K_M. Corroborado por exp004. **No aplica a int8/ternario sin kernels (exp007: int8 naïve 8-10× más lento)** |
| H-BIT-1 | ternario nativo > Q4 denso de igual calidad, sin pérdida | ❌ false | alta | bitnet.cpp es kernel-vs-kernel; BitNet pierde ~12% MMLU. **exp007: el ahorro de int8 es memoria (4×), no cómputo, sin kernels especiales** |
| H-LUT-1 | T-MAC gana solo si las LUTs caben en L2 | ❌ false | media | T-MAC pone las LUTs en REGISTROS, no L2; límite real registro/L1 |
| H-SPARSE-1 | sparsity reduce banda; beneficio neto solo con >60% (ReLU) | ✅ true | baja | dirección ReLU-sí/SwiGLU-no correcta; umbral 60% no medido en CPU |
| H-CF-1 | LoRA r≤16 preserva >90% base, <5% drop | ❌ false | media | sobre-especificado; `federated_store.py` _RANK_MAX=8 prohíbe r=64/256 |
| **H-CF-2** | **FedAvg ingenuo de A,B inexacto vs avg(B@A); crece con heterog.** | ✅ **true** | **alta** | avg(A)avg(B)≠avg(AB); **exp003 ✅: error 0→66%, rango K·r→r**; bug en `federated_store.py` Pass 3 |
| H-CF-3 | RAG document-level ≥ fine-tune, cero olvido, < kNN-LM/token | ✅ true | media | Ovadia 2024; kNN-LM por-token descartado (memory-bound) |
| H-CF-4 | fusión cruza barreras; TIES degrada antes que task-arith | ❌ false | media | lo OPUESTO: TIES degrada MENOS rápido que task-arithmetic |
| H-BIO-1 | sparsity impuesta (ReLU) > truco de picos en CPU | ❌ false | media | dirección correcta; >70%/<2ppl/1.5× no se sostiene a ≤1.5B |
| H-BIO-2 | gating por contexto: barato SOLO con señal fiable | ✅ true | media | XdG (PNAS 2018); sin task-ID → recae en olvido |
| H-BIO-3 | predictive coding / FF NO competitivos vs QLoRA en CPU | ✅ true | alta | PC ~100× coste backprop; ≥10× wall-clock para igual exactitud |
| H-BIO-4 | Hopfield = atención: misma operación, mismo memory-bound | ✅ true | alta | la etiqueta "biológica" no compra eficiencia extra |
| H-SELF-1 | evaluador verificable > proxy auto-generado (reward hacking) | ✅ true | media | dirección sí; monotonía/umbrales exactos no garantizados |
| H-SELF-2 | gate+rollback held-out reduce deriva casi sin coste | ⚠️→✅ condicional (CYCLE 8) | media-alta | ❌ con evaluador CIRCULAR/AGREGADO (el agregado es CIEGO: esconde el daño concentrado ~3×); ✅ con held-out cross-book NO-circular + gate POR-DOMINIO: detecta y reduce la deriva (replay protege 15-21× el dominio dañado). Ver `learn/RESULTS.md` |
| H-SELF-3 | collapse_guard detecta colapso ANTES que el proxy | ❌ false | media | señales sobre poblaciones distintas (entradas vs salidas); orden no demostrado |
| H-SELF-4 | self-modeling → mejor cuantización → ↑tok/s | ❌ false | media | cadena causal con eslabones rotos (varianza de pesos ≠ cuantizabilidad) |

**Convergencia notable:** H-SEQ-2/literatura (recall ∝ tamaño de estado; Jelassi "Repeat After Me"
ICML'24, Arora "Zoology" ICLR'24) **coincide con mi exp002 empírico** (capacidad = d²/32). Dos
caminos independientes (micro-experimento propio + revisión de literatura verificada) llegan al
mismo techo estructural. Esto eleva la confianza en P4 y en la decisión del backbone híbrido.

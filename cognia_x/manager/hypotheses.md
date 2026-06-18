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
| H-SELF-2 | gate+rollback held-out reduce deriva casi sin coste | ❌ false | media | el evaluador de Cognia es CIRCULAR (misma DB que se auto-escribe), no held-out |
| H-SELF-3 | collapse_guard detecta colapso ANTES que el proxy | ❌ false | media | señales sobre poblaciones distintas (entradas vs salidas); orden no demostrado |
| H-SELF-4 | self-modeling → mejor cuantización → ↑tok/s | ❌ false | media | cadena causal con eslabones rotos (varianza de pesos ≠ cuantizabilidad) |

**Convergencia notable:** H-SEQ-2/literatura (recall ∝ tamaño de estado; Jelassi "Repeat After Me"
ICML'24, Arora "Zoology" ICLR'24) **coincide con mi exp002 empírico** (capacidad = d²/32). Dos
caminos independientes (micro-experimento propio + revisión de literatura verificada) llegan al
mismo techo estructural. Esto eleva la confianza en P4 y en la decisión del backbone híbrido.

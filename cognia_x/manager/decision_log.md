# decision_log.md — decisiones de Cognia-X (con fecha y razón)

> Append-only. Cada decisión: qué, por qué, evidencia, reversibilidad.

## D-001 (2026-06-17) — Cognia-X es un laboratorio independiente
- **Decisión:** vivir en `cognia_x/`, sin reutilizar el pipeline de Cognia ni heredar su
  arquitectura.
- **Razón:** la misión exige rediseñar desde cero sin sesgo de la implementación existente.
- **Reversible:** sí (es una carpeta aislada).

## D-002 (2026-06-17) — Eficiencia computacional es la métrica primaria
- **Decisión:** toda propuesta se evalúa primero por coste (tiempo/memoria/ancho de banda) en CPU.
- **Razón:** prioridad #1 del meta-prompt; el hardware objetivo es CPU sin GPU.
- **Reversible:** sí, pero requeriría justificación rigurosa con números.

## D-003 (2026-06-17) — Trabajo en rama `cognia-x`
- **Decisión:** aislar el subproyecto en su propia rama; no commitear los cambios preexistentes
  no relacionados del working tree (.gitignore, build/*).
- **Razón:** higiene de git; mantener el experimento separado.
- **Reversible:** sí.

## D-004 (2026-06-17) — Medir coste antes que calidad, y no confundirlos
- **Decisión:** exp001 mide coste; la decisión de reemplazar un componente requiere además
  evidencia de calidad (exp002+). No declarar "reemplazar atención" con solo exp001.
- **Razón:** honestidad de alcance; evitar conclusiones sobre-extendidas.
- **Reversible:** N/A (principio metodológico).

## D-005 (2026-06-17) — Híbrido como dirección líder de mezcla de secuencia (a confirmar)
- **Decisión:** perseguir la arquitectura de mezcla **híbrida** (mayoría lineal + pocas capas de
  atención full) como hipótesis de diseño principal — NO como decisión cerrada; requiere su
  experimento (H-MEZ-4).
- **Razón:** exp001 (lineal 70× más barato) + exp002 (full con recall ~ilimitado vs lineal
  acotado por estado d²) muestran un trade-off coste↔capacidad; el híbrido es la combinación que
  la evidencia sugiere, alineada con la literatura (Jamba, Griffin, Based).
- **Reversible:** sí; se abandona si exp003+ refuta H-MEZ-4.

## D-006 (2026-06-17) — Métrica maestra = BYTES MOVIDOS POR TOKEN (no FLOPs)
- **Decisión:** juzgar toda optimización por bytes/token movidos, porque el decode batch=1 en CPU
  es memory-bandwidth-bound. **Reversible:** N/A (principio, validado por E1/H-BW-1).

## D-007 (2026-06-17) — Backbone híbrido estado-fijo + atención sliding-window, ratio 3:1–4:1
- **Decisión:** mayoría SSM/Gated-DeltaNet + minoría SWA (W~1024) + 1-2 capas globales; NO 6:1.
- **Razón:** exp001+exp002 + Gemma-3/NVIDIA-Hybrid/arXiv:2507.06457. **Reversible:** sí (E2/H-SEQ-3).

## D-008 (2026-06-17) — Representación BPE vocab moderado parity-aware; rechazar byte-puro y BLT
- **Decisión:** BPE byte-fallback ~32-64k parity-aware + embedding/head cuantizados; NO byte-puro,
  NO BLT a 1-3B. **Razón:** ×4 pasos / BLT no paga a esta escala / vocab grande infla softmax O(V).
- **Refuerzo (exp006, medido):** lm_head O(V) iguala 1 bloque transformer a V≈26k; a vocab moderado
  (≤64k tied) head = 1-10% del modelo; el riesgo de cómputo+memoria aparece a 128-256k. Confirma el
  rango ~32-64k como punto dulce. **Reversible:** sí.

## D-009 (2026-06-17) — Q4 base hoy + ternario como APUESTA de I+D (no cerrada)
- **Decisión:** Q4_K_M en producción; ternario b1.58 solo tras benchmark honesto vs Q4 igualado.
- **Razón:** H-BIT-1 refutada (bitnet.cpp es kernel-vs-kernel; BitNet pierde ~12% MMLU). **Reversible:** sí.
- **Refuerzo (exp007, medido):** int8 naïve en numpy = 8-10× más LENTO que float32; el ahorro de
  baja precisión es de memoria (4×), no de cómputo automático → la velocidad exige kernels
  especializados (T-MAC/bitnet.cpp), no basta con cuantizar. Justifica "Q4 base, ternario solo I+D".

## D-010 (2026-06-17) — Aprendizaje continuo triple capa; kNN-LM por-token descartado
- **Decisión:** RAG document-level + LoRA r≤16 + fusión de adapters dentro de la misma cuenca +
  router de bandas. **Razón:** RAG ≥ fine-tune sin olvido; kNN-LM/token es memory-bound. **Reversible:** sí.

## D-011 (2026-06-17) — Agregación federada: avg(B@A)/FedEx-LoRA, NO FedAvg ingenuo
- **Decisión:** agregar delta-W reconstruidas, no promediar A y B por separado.
- **Razón:** avg(A)·avg(B) ≠ avg(A·B) — INEXACTO, no subóptimo; el bug está en `federated_store.py`
  Pass 3 de Cognia. **Hallazgo accionable** (impacto en Cognia real). Validar con exp003. **Reversible:** sí.

## D-012 (2026-06-17) — Auto-mejora solo con evaluador verificable + gate humano + rollback
- **Decisión:** nunca RL con auto-recompensa online; nunca proxy auto-generado como fitness.
- **Razón:** reward hacking/colapso reproducibles; STOP desactivó sandbox 0.42%. **Reversible:** N/A (gate de seguridad).

## D-013 (2026-06-17) — Implementación v0: PyTorch CPU + byte-level (asumido autónomamente)
- **Decisión:** construir el modelo v0 en **PyTorch (CPU)** con entrada **byte-level** (vocab 256).
- **Razón:** (a) *fácil de entrenar* → autograd de PyTorch; la regla "numpy puro" del vault aplica a
  los NODOS de despliegue de Cognia, no a este laboratorio (Cognia-X es independiente). (b)
  byte-level elimina el tokenizador (más fácil + robusto) para un primer modelo; el "vocab moderado
  BPE" (D-008) es un upgrade de eficiencia de inferencia posterior.
- **Reversible:** sí. La arquitectura híbrida (D-007) es la misma; portar a numpy para nodos o
  cambiar el front-end de representación es trabajo futuro.

## D-CEIL-1 (2026-06-19, CYCLE 22) — Mantener el híbrido (mayoría lineal + minoría atención)
- **Decisión:** mantener el **híbrido** (mayoría lineal barata + minoría de atención para recall
  exacto) como arquitectura del lab; la atención es **necesaria** para recall a carga alta.
- **Razón:** la frontera recall↔throughput (Arora 2024, arXiv:2402.18668) + exp002 (recall ~ d²) +
  exp009 (lineal satura ~0.18, el híbrido separa a d=48: 0.292 vs 0.181) justifican mezclar: lo lineal
  da coste O(L); las pocas capas de atención compran el recall que el estado fijo no escala. Coincide
  con **Based** — el lab llegó al mismo principio de forma independiente.
- **Evidencia:** arXiv:2402.18668 (tier-1) + exp002 + exp009 (tier-5, datos propios). ACEPTADA por el
  `EvidenceLedger` (funda con tier-1 + tier-5 obtenidas; no lanza `OpinionOnlyError`).
- **Matiz honesto:** exp009 muestra que la cota EFECTIVA del lineal entrenado es la capacidad del
  feature-map (<< d²), no el d² teórico — refuerza la decisión (el lineal solo, aún a d grande, no
  alcanza el recall que la atención da). Registrada vía `cognia_x/research/cycles/cycle22_recall_ceiling.py`.
- **Reversible:** sí; se revisa si un feature-map mejor (mimetic init, arXiv:2410.11135) cerrara la
  brecha entrenada y el estado fijo solo bastara para el recall a carga alta.

## D-CEIL-2 (2026-06-19, CYCLE 23) — Descartar "ensanchar el feature-map ELU+1" (mejora descartada)
- **Decisión:** **descartar** ensanchar el feature-map ELU+1 como vía para subir el recall del
  mezclador lineal; **redirigir** el esfuerzo a **kernel Taylor + mimetic init** (H-CEIL-3).
- **Razón:** exp010 (d=24 fijo, step-parity 6000 steps): ×4 ancho = **16× más estado (576→9216)** NO
  movió el recall (**mult1=0.181 → mult4=0.181, Δ+0.000**, nulo). El cuello **no es ancho
  ni tamaño de estado**, sino la **forma del kernel** y la **optimización/init** (Based usa Taylor,
  arXiv:2402.18668; Trockman usa mimetic init, arXiv:2410.11135).
- **Evidencia:** exp010 (tier-5, dato propio obtenido) + arXiv:2402.18668 (tier-1). ACEPTADA por el
  `EvidenceLedger` (funda con tier-5 + tier-1 obtenidas; no lanza `OpinionOnlyError`). Registrada vía
  `cognia_x/research/cycles/cycle23_feature_dim.py`.
- **Tipo:** es una **mejora DESCARTADA** registrada explícitamente (la directiva pide documentar lo que
  NO se persigue y por qué, no solo lo que sí). Continúa/afina D-CEIL-1 (el lineal solo no basta para
  el recall a carga alta; ahora sabemos que tampoco lo arregla el ancho).
- **Reversible:** sí; se reabre si un kernel mejor (Taylor) o init mimética levantara el plateau y el
  estado fijo solo bastara para el recall — exactamente lo que mide H-CEIL-3.

## D-CEIL-3 (2026-06-19, CYCLE 24) — Descartar "forma del kernel (Taylor) + mimetic init" (mejora descartada)
- **Decisión:** **descartar** la forma del kernel (feature-map Taylor 2do orden) y la mimetic init como
  vías para subir el recall del mezclador lineal a d=24; junto con el ancho (D-CEIL-2), redirigir a
  profundidad/escala/optimizador o a la atención del híbrido (H-CEIL-4).
- **Razón:** exp011 (d=24, n_heads=1, n_pairs=16, seed0, steps=3000 step-parity, control de TAMAÑO con
  elu_matched a la dim de Taylor): baseline ELU+1=0.173; **taylor=0.160 (Δ−0.013, POR DEBAJO)**;
  elu_matched(dim 336)=0.181 (+0.008 ruido); **mimetic=0.183 (+0.0098, < umbral 0.02)**. taylor_vs_matched
  =−0.021. Ni la forma ni la init cruzan el ruido; el Taylor queda por debajo de su ELU size-matched
  (el control aísla forma de tamaño). [[arXiv:2402.18668]] (Based) + [[arXiv:2410.11135]] (Trockman)
  predecían que ayudaría → refutado a esta escala.
- **Evidencia:** exp011 (tier-5 propio) + arXiv:2402.18668 (tier-1). ACEPTADA por el ledger. Registrada
  vía `cognia_x/research/cycles/cycle24_kernel_init.py` (deriva el veredicto de results.json).
- **Tipo:** mejora DESCARTADA registrada explícitamente. Continúa D-CEIL-2 (ahora sabemos que tampoco lo
  arregla la forma del kernel ni la init, no solo el ancho). **Reversible:** sí (a otra escala/seed).

## D-CEIL-4 (2026-06-19, CYCLE 25) — Cerrar la línea de tuning del mezclador lineal; el remedio es la atención
- **Decisión:** **cerrar** la línea de afinar el mezclador lineal de estado fijo para subir su recall: el
  techo ~0.18 es **ESTRUCTURAL**. El recall a carga alta se obtiene con la **ATENCIÓN del híbrido**
  (D-CEIL-1/D-007), NO con tuning del mezclador lineal.
- **Razón:** exp012 (lineal PURO, n_pairs=16, seed0, steps=3000): ni profundidad (L8=0.181, +0.0075), ni
  escala-d (d48=0.183, +0.0093), ni optimizador (LR 3×=0.176, +0.0025) suben el lineal puro sobre ~0.18.
  Junto con exp010 (ancho) y exp011 (forma+init), el plateau es robusto a **SEIS levers no-atención**. La
  atención SÍ recupera (CYCLE 6: 0.255→0.998 a np alto; exp009: el híbrido separa a d=48). El techo pasa
  a `real`/estructural (pigeonhole sobre el estado fijo). [[arXiv:2508.19029]] (Okpekpe&Orvieto) predecía
  que el tuning lo arreglaría → refutado a esta escala.
- **Evidencia:** exp012 (tier-5) + arXiv:2508.19029 (tier-1). ACEPTADA por el ledger. Registrada vía
  `cognia_x/research/cycles/cycle25_depth_scale.py`. La línea H-CEIL (recall del estado fijo) CONVERGE.
- **Reversible:** sí; se reabriría si a MAYOR escala (d≫48, modelos grandes) el lineal puro cruzara el
  plateau sin atención — pero a la escala del lab el remedio es arquitectónico. **Confirmación pendiente:**
  exp013 (lineal+≥2 atención a d=24) como control positivo end-to-end a esta misma escala.

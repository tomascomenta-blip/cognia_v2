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

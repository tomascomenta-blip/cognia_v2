# roadmap.md — fases y estado de Cognia-X

> Estado por fase. Una fase avanza solo con evidencia (no por intuición).

## F0 — Fundación del laboratorio  ✅ DONE (2026-06-17)
- [x] Subproyecto independiente `cognia_x/` + rama `cognia-x`.
- [x] Meta-prompt mejorado (constitución operativa) + original conservado.
- [x] Documentación viva mínima en `manager/` (los 9 archivos).
- [x] Primer experimento reproducible corrido (exp001) — el lab "corre de verdad".

## F1 — Ciclo-1 de investigación (mapa de evidencia)  ✅ DONE (2026-06-17)
- [x] exp001 (coste de mezcla) → H-MEZ-1/2; exp002 (capacidad de recall) → H-MEZ-3.
- [x] Workflow de 13 agentes (6 dimensiones), 24 hipótesis verificadas adversarialmente.
- [x] Síntesis integrada en `architecture.md` / `decision_log.md` / `hypotheses.md` / `assumptions.md`.

## F2 — Decisiones por componente (conservadora/moderada/radical)  ✅ DONE (2026-06-17)
- [x] 6 componentes con sus 3 alternativas + evidencia → `architecture.md` (§1-7), `decision_log.md` (D-006..D-012).

## F3 — Validar las constantes en el hardware objetivo  🟡 EN CURSO
La tesis es defendible en dirección; varias constantes ya se midieron en CPU:
- [x] exp003 = E3: inexactitud del FedAvg de LoRA (error 0→66%, rango K·r→r).
- [x] exp004 = E1: roofline CPU — bandwidth-bound (float32 ~2.2× f64; hilos saturan a 2).
- [x] exp005: frontera coste del híbrido (H-MEZ-4) — 3/24 full = ~12-15% del coste de full puro a L=8192.
- [ ] E2 real: SWA vs atención full en llama.cpp con GGUF — tok/s(L) + KV-cache.
- [ ] Cerrar el eje **recall** del híbrido (tarea multi-capa entrenada; entrenamiento en Kaggle GPU).

## F4 — Boceto de arquitectura CPU-first v0  ⬜ PENDIENTE
Diseño integrado defendible por evidencia (representación + mezcla híbrida + cómputo), entrenable a escala chica.

## F5 — Aprendizaje continuo viable en CPU  ⬜ PENDIENTE
RAG document-level + LoRA + fusión intra-cuenca, medido (sin olvido catastrófico).

## F6 — Auto-mejora Nivel 1→2 con gates de estabilidad  ⬜ PENDIENTE
Observación → recomendaciones, con evaluador verificable + rollback antes de subir de nivel.

> Criterio de avance entre fases: hipótesis clave apoyada por experimento reproducible + 0
> regresiones + reproducibilidad mantenida.

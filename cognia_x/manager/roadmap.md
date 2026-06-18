# roadmap.md — fases y estado de Cognia-X

> Estado por fase. Una fase avanza solo con evidencia (no por intuición).

## F0 — Fundación del laboratorio  ✅ DONE (2026-06-17)
- [x] Subproyecto independiente `cognia_x/` + rama `cognia-x`.
- [x] Meta-prompt mejorado (constitución operativa) + original conservado.
- [x] Documentación viva mínima en `manager/` (los 9 archivos).
- [x] Primer experimento reproducible corrido (exp001) — el lab "corre de verdad".

## F1 — Ciclo-1 de investigación (mapa de evidencia)  🟡 EN CURSO
Barrido de 6 dimensiones con evidencia + refutación adversarial + síntesis:
representación · mezcla de secuencia · cuello de botella CPU · aprendizaje continuo ·
inspiración biológica · auto-mejora.
- [x] exp001 (coste de mezcla) corrido → H-MEZ-1/2 apoyadas.
- [x] exp002 (capacidad de recall) corrido → H-MEZ-3 apoyada; trade-off coste↔capacidad medido.
- [ ] Síntesis del workflow integrada en `architecture.md` / `decision_log.md` / `hypotheses.md`.
- [ ] exp003: validar A-001 (CPU bandwidth-bound) + experimento del híbrido (H-MEZ-4).

## F2 — Decisiones por componente (conservadora/moderada/radical)  ⬜ PENDIENTE
Para cada componente: 3 alternativas evaluadas con experimento. Salida → `architecture.md`.

## F3 — Boceto de arquitectura CPU-first v0  ⬜ PENDIENTE
Primer diseño integrado defendible por evidencia (representación + mezcla + cómputo).

## F4 — Aprendizaje continuo viable en CPU  ⬜ PENDIENTE
Mecanismo de aprendizaje local + fusión sin olvido catastrófico, medido.

## F5 — Auto-mejora Nivel 1→2 con gates de estabilidad  ⬜ PENDIENTE
Observación → recomendaciones, con evaluación + rollback antes de subir de nivel.

> Criterio de avance entre fases: hipótesis clave apoyada por experimento reproducible + 0
> regresiones + reproducibilidad mantenida.

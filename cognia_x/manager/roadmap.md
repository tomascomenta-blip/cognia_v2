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
- [x] Workflow de 13 agentes (6 dimensiones) corrido; 24 hipótesis verificadas adversarialmente.
- [x] Síntesis integrada en `architecture.md` / `decision_log.md` / `hypotheses.md` / `assumptions.md`.

## F2 — Validar las constantes en el hardware objetivo  🟡 EN CURSO
La tesis es defendible en dirección; las constantes (tok/s, ratios, umbrales) NO se midieron en
CPU. Experimentos E1-E5 (ver `experiments.md` / `future_work.md`):
- [ ] exp003 = E3: demostrar inexactitud del FedAvg de LoRA (numpy puro, P0). **siguiente**
- [ ] exp004 = E1: roofline CPU — confirmar bandwidth-bound + barrido de hilos/precisión.
- [ ] exp005 = E2: SWA vs atención full — tok/s(L) + KV-cache (requiere GGUF).

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

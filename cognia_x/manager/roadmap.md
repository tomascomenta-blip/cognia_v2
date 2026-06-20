# roadmap.md — fases y estado de Cognia-X

> Estado por fase. Una fase avanza solo con evidencia (no por intuición).
> Constitución operativa vigente: `_directiva_v3.md` (descarta lo HECHO, deja lo PENDIENTE; absorbe
> las lecciones de 23 ciclos como reglas). v1/v2 se conservan (append-only).

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
- 🟡 **CYCLE 24 (exp011, EN CURSO):** ¿el plateau de recall lineal (~0.18) es de FORMA del kernel
  (Taylor 2do orden) o de INIT (mimetic), no de tamaño de estado? 4 brazos a d=24, step-parity.
  Cierra/afila la línea del techo de recall (H-CEIL-1/2/3).

## F4 — Boceto de arquitectura CPU-first v0  🟡 EN CURSO (implementado + entrenando)
- [x] Modelo híbrido v0 en PyTorch CPU (`cognia_x/model/hybrid.py`): la arquitectura del ciclo-1 hecha código.
- [x] Pipeline de entrenamiento (recall + char-LM) verificado y lanzado (corrida nocturna).
- [ ] Documentar resultados: ¿el híbrido cierra el eje recall (H-MEZ-4)? + calidad del char-LM.

## F5 — Aprendizaje continuo viable en CPU  ⬜ PENDIENTE
RAG document-level + LoRA + fusión intra-cuenca, medido (sin olvido catastrófico).

## F6 — Auto-mejora Nivel 1→2 con gates de estabilidad  🟡 EN CURSO
Observación → recomendaciones, con evaluador verificable + rollback antes de subir de nivel.
- [x] Nivel 1: aprende sin olvido (CYCLE 8/10: gate por-dominio + replay + examinador no-circular).
- [x] Anti-colapso (CYCLE 11): verify-before-learn PREVIENE colapso (examinador real + rollback).
- [x] **Nivel 2 — AUTO-MEJORA verificada (CYCLE 29, H-LEARN-1 apoyada):** en tarea verificable, el modelo
  aprende de su propia salida VERIFICADO-CORRECTA y MEJORA (STaR); la corrección del oráculo es el motor
  (control random_matched lo aísla). exp016, n=4, t-pareado p<0.05. Avanza CYCLE 11 (prevención→habilitación).
- [ ] Verificador RUIDOSO/PARCIAL + verificador chequeable real (código→sandbox; hechos→≥2 fuentes) en vez
  del oráculo aritmético; cuota de sintético + ledger de procedencia para loops largos (F-LEARN-2 continúa).

> Criterio de avance entre fases: hipótesis clave apoyada por experimento reproducible + 0
> regresiones + reproducibilidad mantenida.

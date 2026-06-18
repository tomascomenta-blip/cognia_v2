# manager_log.md — bitácora operativa del loop de manager (Cognia-X)

> Log de ciclos del modo manager autónomo (operativo, distinto de `research_log.md` que es el
> contenido científico). Append-only. GOAL: avanzar Cognia-X por evidencia, sin detenerse.

## [2026-06-17] CYCLE 1 — validar H-BW-1 (cornerstone bandwidth-bound)
- Startup: usage 34% (<80%, proceder). Vault leído (Key Decisions + Gotchas).
- **Verificación por evidencia existente:** el vault (Gotchas) ya tiene medido en i3-10110U que el
  decode es memory-bandwidth-bound (spec decode 5× más lento pese a 90.8% acceptance; 3 threads >
  4; techo ~8 tok/s con 3B Q4_K_M). → H-BW-1/A-008 suben a confianza ALTA (medido en target).
- Sub-tarea delegada a sub-agente (general-purpose): exp004 (roofline numpy) — el sub-agente
  escribió y corrió el experimento; el manager VERIFICÓ corriendo el barrido de hilos por su cuenta.
- **Resultado:** exp004 corrido. float32 ≈2.2× float64 (bytes/peso); GB/s plano ~15-22
  (memory-bound, GFLOP/s 4-11 ≪ pico); hilos saturan a 2 (1→2 +11%, 3-4 peores). H-BW-1/A-008 →
  confianza ALTA (vault + exp004, dos vías).
- Tests: N/A — experimento standalone numpy en `cognia_x/`, no toca el código de Cognia ni su suite
  (correr la suite de Cognia ~17 min sería irrelevante a este cambio). La verificación REAL fue
  correr el experimento y mostrar números.
- Archivos: exp004/run.py + results/; experiments.md, hypotheses.md, assumptions.md, research_log.md.
- Next: CYCLE 2 = experimento del híbrido (H-MEZ-4).

## [2026-06-17] CYCLE 2 — experimento del híbrido (H-MEZ-4), eje coste
- Startup: usage 37% (<80%, proceder).
- Sub-tarea delegada a sub-agente (general-purpose): exp005 (frontera coste del decode híbrido).
  El sub-agente lo escribió y corrió; el manager VERIFICÓ re-corriéndolo (número clave confirmado).
- **Resultado:** pure linear ~constante en L; pure full ~lineal; **híbrido 3/24 full = ~12-15% del
  coste de full puro a L=8192**. H-MEZ-4 → apoyada (eje coste, confianza alta). Caveat: payoff
  depende de L grande; recall del stack aún por medir (inferido de exp002).
- Tests: N/A (experimento standalone numpy en `cognia_x/`).
- Archivos: exp005/run.py + results/; experiments.md, hypotheses.md, architecture.md, research_log.md, roadmap.md.
- Next: CYCLE 3 = cerrar eje recall del híbrido, o E2 real (SWA vs full con GGUF).

## [2026-06-17] CYCLE 3 — coste del vocabulario / representación (D-008, H-REP-1/4)
- Startup: usage 39% (<80%, proceder).
- Sub-tarea delegada a sub-agente: exp006 (lm_head O(V) vs bloque). Manager VERIFICÓ re-corriéndolo.
- **Resultado:** lm_head = 1 bloque a V≈26k (lineal en V); input embed ~10⁴× más barato (refuta
  H-REP-1); memoria embed+head 1-10% a vocab moderado tied, 30% a 256k. Refuerza D-008.
- Tests: N/A (standalone numpy en `cognia_x/`).
- Archivos: exp006/run.py + results/; experiments.md, hypotheses.md, architecture.md, decision_log.md, research_log.md.
- Next: CYCLE 4 = exp007 eje precisión (int8 vs float32, por qué hacen falta kernels especiales).

## [2026-06-17] CYCLE 4 — eje precisión (D-009/H-BIT-1 caveat)
- Startup: usage 41% (<80%, proceder).
- Sub-tarea delegada a sub-agente: exp007 (int8 vs float32 GEMV). Manager VERIFICÓ re-corriéndolo.
- **Resultado:** int8 naïve 8-10× más LENTO que float32 (sin BLAS para enteros); dequant+float ~14×;
  int8 ahorra 4× memoria. → el ahorro de baja precisión es de memoria, no de cómputo automático.
  Confirma por qué existen T-MAC/bitnet.cpp. Refuerza D-009 (Q4 base, ternario solo I+D).
- Tests: N/A (standalone numpy en `cognia_x/`).
- Archivos: exp007/run.py + results/; experiments.md, hypotheses.md, architecture.md, decision_log.md, research_log.md.
- **Resumen de la sesión de manager (4 ciclos):** exp004 (bandwidth), exp005 (híbrido coste),
  exp006 (vocab/lm_head), exp007 (precisión). 4 decisiones de arquitectura con evidencia propia
  medida en i3-10110U. Lo que queda (eje recall del híbrido, SWA real, RAG vs LoRA) necesita
  entrenamiento GPU/Kaggle o backend llama.cpp+GGUF → próxima sesión de manager.
- Next: CYCLE 5 = E2 real (SWA vs full con GGUF) o eje recall del híbrido (Kaggle). El loop continúa.

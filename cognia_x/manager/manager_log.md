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

## [2026-06-17] CYCLE 5 — construcción de la IA v0 + entrenamiento nocturno lanzado
- Mandato del dueño: "crea la IA desde cero... barata, fácil de entrenar e inteligente", autónomo,
  sin preguntar; programar apagado a las 4:30 AM. Hecho: `shutdown /s` a las 04:30, deadline train 04:25.
- **Construido `cognia_x/model/hybrid.py`** (PyTorch CPU): modelo HÍBRIDO = mayoría capas lineales
  O(L) + atención sliding-window (~3:1) + RMSNorm + SwiGLU + lm_head atado, byte-level (vocab 256).
  La arquitectura del ciclo-1 hecha código. Decisiones D-007 (híbrido) + D-013 (PyTorch/byte-level).
- **`cognia_x/train/`**: recall_task (cierra H-MEZ-4 end-to-end: lineal vs híbrido vs atención) +
  charlm (byte-LM sobre texto local) + run_overnight (orquesta con deadline + checkpoints).
- **Smoke verificado** (regla CLAUDE.md): recall entrena (loss 4.83→3.89); char-LM entrena
  (val 5.53→4.90), checkpoint + sample OK. Lanzado run REAL en background (b6e1do2gj) hasta 04:25.
- Tests: N/A (lab independiente). Verificación REAL = el pipeline corre y APRENDE (mostrado).
- Resultados estarán en `cognia_x/runs/overnight_v0/` (recall_results.json, charlm_best.pt, samples).
- Next: al volver, leer runs/overnight_v0/ y documentar el resultado del entrenamiento.
- **RESULTADO (04:25):** char-LM ✅ aprende (val 1.74 nats/byte, genera español+markdown+código;
  sobreajustó el corpus chico). recall ❌ INCONCLUSO: 3 configs ~0.09, ni la atención (control
  positivo) resolvió MQAR → NO cierra H-MEZ-4; setup inadecuado, lección documentada. Honesto.
  Next CYCLE 6: rehacer recall con control positivo válido (menos pares, más pasos).

## [2026-06-18] CYCLE 6 — diagnóstico del recall + RoPE + revisión adversarial (workflow)
- Startup: sesión continuada (modo manager autónomo, ultracode). Objetivo: control positivo válido
  para cerrar H-MEZ-4.
- **Diagnóstico (causa raíz):** aislé el fallo bajando dificultad — np=1 atención acc 1.000 (copia
  ok); np=2 a 2 capas/pocos pasos/n_queries=1 plateau 0.60; np=2 a 4 capas/8 cabezas/4000 pasos
  0.998 (transición de fase). NO es bug del modelo: era **sub-recursos**.
- **RoPE:** agregado a la atención (faltaba toda señal posicional). Pero RoPE NO movió la aguja a
  2 capas y abs_pos tampoco → la posición no era el cuello; lo es capacidad/pasos. RoPE queda como
  mejora correcta (verificada por tests).
- **Workflow de revisión adversarial** (6 agentes, 5 lentes): tarea/modelo/bugs SÓLIDO (RoPE=pos
  relativa, lineal paralela==recurrente diff 1e-7, alineamiento sin off-by-one, todo numérico);
  corrigió 2 cosas que acepté: (1) sobredimensioné la receta — el lever real es **pasos + densidad
  de supervisión (n_queries)**, no profundidad; mi 0.998 nunca se commiteó (lo corregí en docs);
  (2) capacidad del lineal multi-cabeza = **d²/h, no d²** → el barrido debe entrar por encima de
  esa capacidad para separar.
- **Hecho (verificado, smoke+tests):** RoPE + assert d_head par; baseline de azar + rng eval + piso
  de pasos en recall_task; exp008 parametrizable + deadline robusto + control-primero; nuevo test
  discriminante np=3 (5 passed). Commits 52c97bf + 870d097 pusheados.
- **Verificación REAL:** atención cruza recall de 3 pares a >0.9 (test) — control positivo válido
  conseguido a escala chica. Falta el régimen separador (np≥24).
- Tests: 5 passed (cognia_x/tests/). Suite de Cognia: N/A (lab independiente, no toca su código).
- **Resultado del cierre de H-MEZ-4: ✅ CERRADO (end-to-end en CPU).** Profundidad 4, d=64, h=4,
  201k params, 3 configs igual tamaño. np=4: att 0.999 / hyb 0.991 / lin 0.988 (las 3). **np=8:
  att 1.000 / hyb 0.998 / lin 0.255** → el lineal SATURA y falla, el híbrido RECUPERA el recall
  siguiendo a la atención. Confirma exp002 entrenando; junto a exp005 (coste) cierra H-MEZ-4 en
  sus dos ejes. Clave del éxito: receta (warmup + h=4 + n_queries=16) — la atención cruza np=8 en
  ~1200 pasos (antes no cruzaba: era sub-recursos, no bug). Hallazgo 2º: el recall exige ≥2 capas
  de atención (a prof. 2 el híbrido de 1 atención falla como el lineal). Datos en results/.
- **Iteración (honesta):** ~6 diseños de probe antes de acertar — el cuello no era capacidad/CPU
  sino la receta de entrenamiento de la atención; early-stop + warmup destrabaron el grid. Maté
  varios probes sub-óptimos al detectarlos (no esperé a que fallaran del todo).
- Next: refuerzo a prof. 6 (híbrido mayoría-lineal 33% atención) corriendo; correr tests como
  compuerta final; documentar en memoria. char-LM corpus mayor sigue pendiente (CYCLE 7).

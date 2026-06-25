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

## [2026-06-24] RESET v4 — R-VALOR como North Star (CYCLE 35)
- Árbol de descomposición raíz (decomposition_tree.md): 6 lentes + auditoría adversarial → R-VALOR (5/6).
- exp022 / cycle35 / H-V4-1: MIXTA — R-INTERVENCIÓN 'real' (muro informacional del pasivo), R-VALOR
  'asumido' (azar-activo basta → H-V4-1b). D-V4-1 registrada. _directiva_v4.md vigente (conserva v1/v2/v3).

## [2026-06-24] CYCLE 36-37 — H-V4-1b MIXTA (refuta valor-info-gain) + literatura v4
- exp023/cycle36: info-gain NO bate al azar-activo (margen +0.004); lever = INTERVENCIÓN. D-V4-2 (pivote a
  act-and-verify). R-INTERVENCIÓN reforzada 'real'; R-VALOR 'asumido' (info-gain descartado; abierto en forma
  fuerte = empowerment → H-V4-1c). Test 4/4, verify=OK.
- literature_v4.md (CYCLE 37): SOTA corrobora; rumbo = substrato chico CPU + verificador barato (TTS).

## [2026-06-24] CYCLE 38 — R-VALOR REAL (empowerment), forma fuerte
- exp024/cycle38/H-V4-1c APOYADA: inversión limpia empowerment(ctrl 1.71/reloj 0) vs predicción pasiva
  (reloj 1.71/ctrl 0). controlabilidad != predictibilidad. R-VALOR real (forma fuerte), unificado con
  R-INTERVENCIÓN. D-V4-3. verify=OK, test 4/4. Próximo: H-V4-1d (downstream) + integrador a lenguaje.

## [2026-06-24] CYCLE 39 — R-VALOR aplicado (empowerment mejora la tarea)
- exp025/cycle39/H-V4-1d APOYADA: a capacidad limitada, empowerment 1.000 vs predictibilidad 0.250 (anti-útil)
  vs azar 0.453. Arco R-VALOR cerrado (mecanismo+utilidad). D-V4-4. verify=OK, test 4/4.
- Próximo: integrador act-and-verify hacia lenguaje (H-V4-1e).

## [2026-06-25] CYCLE 72 — H-V4-5b APOYADA (abre arco "R-VALOR bajo realismo")
- Archivos: cognia_x/experiments/exp056_estimated_value_memory/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle72_estimated_value_memory.py (new),
  cognia_x/tests/test_cycle72_estimated_value_memory.py (new),
  research_log.md / decomposition_tree.md / roadmap.md / paper.md (append).
- Resultado tests: PASS — test dirigido 5/5; cycle72 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp: oracle=0.508 estimated(LFU)=0.506 (recupera 99%) recency=0.370 random=0.219 anti=0.088 (48 seeds).
- Notas: ataca el caveat #1 del techo de CYCLE 70 (valor PERFECTO + selección estática). El valor de consulta es
  ESTIMABLE online de la frecuencia (valor endógeno) y recupera ~la ventaja del oráculo en estacionario, venciendo
  a una memoria value-free (LRU). Sirve al GOAL (R-VALOR) quitando la muleta de oráculo-de-valor. Caveat honesto:
  régimen estacionario; la no-estacionariedad es la próxima hija (CYCLE 73).

## [2026-06-25] CYCLE 73 — H-V4-5c APOYADA (estimador de valor con olvido bajo no-estacionariedad)
- Archivos: cognia_x/experiments/exp057_nonstationary_value_memory/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle73_nonstationary_value_memory.py (new),
  cognia_x/tests/test_cycle73_nonstationary_value_memory.py (new),
  research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle73 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (32 seeds): no-estac lfu_decay=0.430 > lfu_full=0.341 (+0.090) > recency=0.379; recupera 74% del
  oráculo (0.516). estac full=0.511 >= decay=0.443 (olvidar cuesta -> tradeoff real). CROSSOVER limpio.
- Notas: hija del CYCLE 72; ata el estimador de valor (frecuencia) con el arco de olvido (CYCLE 58-66). Sirve al
  GOAL (R-VALOR bajo realismo) quitando la muleta de estacionariedad del 72. Caveat honesto: decay fijo; LRU
  competitiva bajo cambio fuerte. Próxima hija (CYCLE 74): decay ADAPTATIVO (meta-olvido del estimador).

## [2026-06-25] CYCLE 74 — H-V4-5d APOYADA (el estimador de valor elige su tasa de olvido; cierra 72-73-74)
- Archivos: cognia_x/experiments/exp058_adaptive_value_memory/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle74_adaptive_value_memory.py (new),
  cognia_x/tests/test_cycle74_adaptive_value_memory.py (new),
  research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle74 por el engine APOYADA, verify_no_loss=OK; gate ciclos+engine 33/33.
- Resultado exp (32 seeds): ESTAC selector=0.507~full=0.511 (usa decay 6%); NO-ESTAC selector=0.425~decay=0.430
  (usa decay 88%). NO-REGRET: iguala al mejor en cada régimen; ningún fijo lo logra en ambos.
- Notas: cierra el sub-arco R-VALOR-estimador (72-73-74) y la muleta 'decay fijo' del 73. Sirve al GOAL (R-VALOR
  bajo realismo). El selector DISCRETO (no la tasa continua) logra no-regret, replicando CYCLE 66 sobre el estimador
  de valor. Próximo: valor endógeno más rico (info-gain/confianza) o escala no-IID; o pivotar a otra muleta.

## [2026-06-25] CYCLE 75 — H-V4-5e APOYADA (el valor != frecuencia, task-definido; capstone conceptual)
- Archivos: cognia_x/experiments/exp059_value_vs_frequency/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle75_value_vs_frequency.py (new),
  cognia_x/tests/test_cycle75_value_vs_frequency.py (new),
  research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle75 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): COST_VARYING value_est=0.636 (99% del oráculo 0.639) > lfu=0.489 (+0.147); COST_UNIFORM
  value_est=0.502 = lfu=0.502. El valor es task-definido; estimar la frecuencia falla cuando v!=f.
- Notas: capstone CONCEPTUAL del arco realismo (72-75); eleva el arco más allá de "LFU textbook". Sirve al GOAL
  (R-VALOR task-definido). Liga memoria con R-INTERVENCIÓN (valor aprendido de consecuencias). Próxima hija: costo
  revelado sólo al fallar (exploración); valor endógeno más rico (info-gain/confianza).

## [2026-06-25] CYCLE 76 — H-V4-5f APOYADA (valor con observación gateada por la acción)
- Archivos: cognia_x/experiments/exp060_action_gated_value/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle76_action_gated_value.py (new),
  cognia_x/tests/test_cycle76_action_gated_value.py (new),
  research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle76 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): value_miss=0.634 (99% del oráculo) = value_full=0.634 > lfu=0.490; value_explore=0.572
  resta. La observación gateada por la acción NO rompe el aprendizaje del valor bajo estacionariedad.
- Notas: hija del 75; MATIZA honestamente R-INTERVENCIÓN sobre la memoria (la observación pasiva del contrafáctico
  basta; la intervención no hace falta en estacionario). Sirve al GOAL (R-VALOR bajo realismo). Próxima hija real de
  R-INTERVENCIÓN: costos NO-estacionarios + observación gateada (combinar CYCLE 73 + 76).

## [2026-06-25] CYCLE 77 — H-V4-5g REFUTADA (informativa): intervención naive sobre memoria bajo drift no paga
- Archivos: cognia_x/experiments/exp061_intervention_value/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle77_intervention_value.py (new),
  cognia_x/tests/test_cycle77_intervention_value.py (new),
  research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle77 por el engine REFUTADA (DoD), verify_no_loss=OK.
- Resultado exp (32 seeds): DRIFT value_miss=0.561 pierde 0.051 vs value_full=0.613 (problema real); value_explore=
  0.532 no supera a miss (mecanismo burdo no paga); ESTAC miss=full=0.653 (control).
- Notas: REFUTADA = ciclo exitoso (fracaso-es-información). Complementa el 76: el problema drift+obs-gateada es real,
  la intervención por slot fijo no paga. Sirve al GOAL (honestidad sobre R-INTERVENCIÓN sobre memoria). Próxima hija:
  intervención sorpresa-gateada (barata). Con esto el arco realismo 72-77 cierra el sub-tema memoria; pivotar.

## [2026-06-25] CYCLE 78 — H-V4-5h REFUTADA (cierra sub-tema memoria): ni la intervención barata paga en la cache
- Archivos: cognia_x/experiments/exp062_surprise_intervention/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle78_surprise_intervention.py (new),
  cognia_x/tests/test_cycle78_surprise_intervention.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle78 por el engine REFUTADA (DoD), verify_no_loss=OK.
- Resultado exp (32 seeds): DRIFT surprise=0.545 > explore=0.532 (barata<burda) pero < miss=0.561 (no paga);
  ESTAC surprise=0.618 < miss=0.653 (falsos positivos). El gap de obs (0.051) es muy chico para que intervenir pague.
- Notas: cierra el sub-tema R-INTERVENCIÓN-sobre-memoria con null firme; la observación pasiva del contrafáctico es
  robusta aun con drift. PIVOTE: sub-tema memoria saturado (72-78). Próximo: valor endógeno más rico (info-gain/
  confianza) o la rama control/empowerment, donde R-INTERVENCIÓN es de primer orden.

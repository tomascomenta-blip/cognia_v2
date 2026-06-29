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

## [2026-06-25] CYCLE 79 — H-V4-6a MIXTA (PIVOTE: abre rama R-CONTROL): empowerment = marginal-de-controlabilidad de R-VALOR
- Archivos: cognia_x/experiments/exp063_empowerment_limits/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle79_empowerment_limits.py (new),
  cognia_x/tests/test_cycle79_empowerment_limits.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle79 por el engine MIXTA (DoD), verify_no_loss=OK.
- Resultado exp (48 seeds): empowerment captura del óptimo rho=1 1.000 (recupera exp024/025), degrada monótono a
  rho=0 0.724 (random 0.431); proxy parcial = marginal-de-controlabilidad de R-VALOR, no valor universal.
- Notas: PIVOTE fuera del sub-tema memoria. Test adversarial que la corrida nunca hizo (38/39 aceptaron empowerment
  sin él). Acota el rival CONTESTADO del árbol bajo R-VALOR. Sirve al GOAL (R-VALOR como raíz general). Próximo:
  empowerment ESTIMADO online; reconstruir R-VALOR combinando control+relevancia estimada.

## [2026-06-25] CYCLE 80 — H-V4-6b APOYADA (capstone R-CONTROL): R-VALOR reconstruido de control_est × relevancia_est
- Archivos: cognia_x/experiments/exp064_value_reconstruction/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle80_value_reconstruction.py (new),
  cognia_x/tests/test_cycle80_value_reconstruction.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle80 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): rho=0 rvalue_est=0.984 vence a empowerment=0.709 y relevance=0.729 (+0.255), recupera 98%
  del oráculo; converge con muestras [0.686→0.984]. R-VALOR = producto de dos marginales endógenas.
- Notas: cierra el par R-CONTROL (79 acotó, 80 reconstruye). El valor se CONSTRUYE de la experiencia (control +
  recompensa estimados), no se postula. Resuelve el rival contestado bajo R-VALOR. Sirve al GOAL (R-VALOR raíz
  general constructiva). Próximo: lazo real acción-consecuencia; ligar relevancia con el verificador de auto-mejora.

## [2026-06-25] CYCLE 81 — H-V4-6c APOYADA: el verificador como marginal-de-relevancia de R-VALOR (une 3 arcos)
- Archivos: cognia_x/experiments/exp065_verifier_relevance/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle81_verifier_relevance.py (new),
  cognia_x/tests/test_cycle81_verifier_relevance.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle81 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): ε=0 rvalue_verifier=1.000 (reconstruye) vs empowerment=0.387 (+0.613); tolera ε*=0.30;
  ε=0.5 cae al control (0.356~0.400). El verificador es la marginal-de-relevancia.
- Notas: UNIFICA el arco verificador (48-55) con la reconstrucción de R-VALOR (79-80) y R-INTERVENCIÓN: act-and-verify
  estima R-VALOR = control × verificador-relevancia. Sirve al GOAL (R-VALOR raíz que aterriza el verificador). Próximo:
  control estimado online; verificador chequeable REAL (sandbox exp018) como relevancia.

## [2026-06-25] CYCLE 82 — H-V4-6d APOYADA (capstone unificación): R-VALOR totalmente endógeno (control_est × verificador)
- Archivos: cognia_x/experiments/exp066_endogenous_rvalue/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle82_endogenous_rvalue.py (new),
  cognia_x/tests/test_cycle82_endogenous_rvalue.py (new), research_log.md / decomposition_tree.md (+consolidación 72-82) / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; cycle82 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): punto realista (S=8,ε=0.1) rvalue_full=0.822 vence a empowerment=0.400 y verifier=0.637
  (+0.185), recupera 82% del óptimo; vence a ambas en TODO el grid de ruido. Sin oráculo en ningún lado.
- Notas: capstone empírico de la unificación 79-82; cierra la rama R-CONTROL y el caveat 'control exacto' del 81.
  Agregada CONSOLIDACIÓN canónica de la corrida 72-82 al decomposition_tree (tesis unificada: R-VALOR=control×relevancia,
  marginales=empowerment+verificador). Sirve al GOAL. Próximo: lazo real acción-consecuencia + verificador real; valor
  no-factorizable; SCALE (GPU/Kaggle, fuera de la corrida CPU).

## [2026-06-25] CYCLE 83 — H-V4-7a APOYADA (ataque a la factorización): R-VALOR producto = prior de complementariedad
- Archivos: cognia_x/experiments/exp067_nonfactorizable_value/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle83_nonfactorizable_value.py (new),
  cognia_x/tests/test_cycle83_nonfactorizable_value.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 6/6; arco 79-83 + engine 42/42; cycle83 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): adv(prod−mejor marginal) COMPLEMENTOS {0.197..0.244} (crossover=nunca, robusto) vs SUSTITUTOS
  {0.200..−0.027} (crossover λ*=0.75; en λ=1.0 la relevancia 0.942 supera al producto 0.915). Filas 'clean' reproducen
  la asimetría → es la FACTORIZACIÓN, no el ruido.
- Notas: ataca y ACOTA el gap #2 (value=ctrl×rel asumido). La reconstrucción-producto del arco 79-82 es un PRIOR DE
  COMPLEMENTARIEDAD: robusto salvo bajo sustitutos puros; tolera no-factorizabilidad moderada (λ≤0.5). Sirve al GOAL
  (R-VALOR). Próximo (CYCLE 84): combinador APRENDIDO que recupere lo perdido bajo sustitutos.

## [2026-06-25] CYCLE 84 — H-V4-7b MIXTA (construcción gap #2): combinador APRENDIDO recupera parcial/noise-gated
- Archivos: cognia_x/experiments/exp068_learned_combiner/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle84_learned_combiner.py (new),
  cognia_x/tests/test_cycle84_learned_combiner.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 7/7; arco 82-84 + engine 36/36; cycle84 por el engine MIXTA, verify_no_loss=OK.
- Resultado exp (64 seeds): subs λ1.0 m20 learned_poly2=0.953 es el mejor brazo no-oráculo (> producto 0.926 +0.028,
  > marginal 0.939) pero <+0.03 decisivo bajo ruido; CLEAN recupera pleno (0.994 vs 0.932, +0.062); no sacrifica
  complementos. Recuperación NOISE-GATED.
- Notas: la construcción que cierra el gap #2 es VIABLE pero paga decisivamente sólo con feedback limpio/abundante; el
  producto (prior de complementariedad) sigue siendo baseline por DEFECTO. Sirve al GOAL (R-VALOR). Próximo (CYCLE 85):
  subir la calidad del feedback (más S de control, re-observación sorpresa-gateada) para volver la recuperación decisiva.

## [2026-06-25] CYCLE 85 — H-V4-7c APOYADA (cierra el noise-gating del gap #2): la calidad del feedback destraba la recuperación
- Archivos: cognia_x/experiments/exp069_feedback_quality/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle85_feedback_quality.py (new),
  cognia_x/tests/test_cycle85_feedback_quality.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 7/7; arco 83-85 + engine 36/36; cycle85 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (64 seeds): adv(poly2−producto) bajo sustitutos crece monótona con la calidad del feedback q0=+0.017 →
  q1=+0.038 → q2=+0.052 → q3=+0.059 → clean=+0.059; cruza el umbral decisivo (+0.03) en feedback no-perfecto, sin
  sacrificar complementos.
- Notas: el noise-gating de CYCLE 84 es una PENDIENTE, no una pared — subir la calidad del feedback (no sólo el volumen)
  destraba la recuperación decisiva. SUB-ARCO gap #2 CERRADO (83 acota / 84 construye-noise-gated / 85 destraba). Política:
  producto por DEFECTO; calidad de feedback + combinador aprendido en régimen de sustitutos. Sirve al GOAL (R-VALOR).
  Próximo (CYCLE 86): detección AUTOMÁTICA del régimen (conmutar producto<->aprendido sin saberlo a priori).

## [2026-06-25] CYCLE 86 — H-V4-7d APOYADA (CAPSTONE gap #2): el aprendido domina; detectar el régimen es innecesario
- Archivos: cognia_x/experiments/exp070_regime_policy/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle86_regime_policy.py (new),
  cognia_x/tests/test_cycle86_regime_policy.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 6/6; arco 84-86 + engine 34/34; cycle86 por el engine APOYADA, verify_no_loss=OK.
- Resultado exp (48 seeds): always_learned DOMINA sobre gate=q1 (a q2 dom comp=+0.006, subs=+0.051); el oracle_selector
  (detector PERFECTO) supera a always_learned por sólo +0.001 y el selector real por −0.002 (<=0.02) -> detección
  INNECESARIA. Mecanismo: poly2 NESTA el producto (cr es feature).
- Notas: ARCO gap #2 (83-86) CERRADO. Política FINAL de reconstrucción de R-VALOR = COMPUERTA DE CALIDAD DE FEEDBACK
  (aprendido si feedback adecuado, producto si pobre), sin switch por régimen. Sirve al GOAL (R-VALOR). Próximo: valor
  no-factorizable y feedback de un lazo de acción-consecuencia REAL (gaps #1/#3, verificador exp018) y SCALE (GPU).

## [2026-06-25] CYCLE 87 — H-V4-7e REFUTADA (puente gaps #1/#3): feedback action-gated NO atrapa; exploración innecesaria
- Archivos: cognia_x/experiments/exp071_action_gated_feedback/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle87_action_gated_feedback.py (new),
  cognia_x/tests/test_cycle87_action_gated_feedback.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; arco 85-87 + engine 32/32; cycle87 por el engine REFUTADA, verify_no_loss=OK.
- Resultado exp (48 seeds): bajo feedback action-gated, sustitutos learned_greedy=0.979 = learned_random(insesgado)=0.979
  = explore=0.979 > product=0.929. NO hay trampa de sesgo de selección; la exploración NO aporta. La selección top-k
  abarca suficiente espacio de features para generalizar max().
- Notas: REFUTADA informativa (robustez POSITIVA): ACOTA R-INTERVENCIÓN ('explorar para aprender el valor' no hace falta
  aquí) y REFUERZA la política gap #2 (always-learn robusta también bajo feedback de acción-consecuencia, sin maquinaria
  de exploración). Caveat: no se probó concentración extrema del soporte. Sirve al GOAL (R-VALOR). Próximo: lazo de
  acción-consecuencia REAL con verificador chequeable (sandbox exp018), feedback con costo, dinámica secuencial.

## [2026-06-25] CYCLE 88 — H-V4-7f REFUTADA (cierra caveat CYCLE 87): ni la concentración extrema del soporte atrapa
- Archivos: cognia_x/experiments/exp072_support_concentration/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle88_support_concentration.py (new),
  cognia_x/tests/test_cycle88_support_concentration.py (new), research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 4/4; arco 86-88 + engine 32/32; cycle88 por el engine REFUTADA, verify_no_loss=OK.
- Resultado exp (48 seeds): probando el peor caso (POOL FIJO + k_obs=1) el greedy NO se atrapa — gap random−greedy=0.037
  (<=0.05, sin trap); fresh tampoco. El ridge-poly2 sobre pocos puntos both-high con SPREAD generaliza max().
- Notas: cierra el caveat de CYCLE 87 con robustez MÁS fuerte; cierra el SUB-TEMA feedback-realismo (87-88). R-INTERVENCIÓN
  no liga aquí (2ª refutación consecutiva). Matiz: costo MILD sub-umbral de concentración que la exploración cierra.
  Sirve al GOAL (R-VALOR). Próximo (el salto grande): lazo de acción-consecuencia REAL con verificador chequeable
  (sandbox exp018) y SCALE (GPU).

> NOTA DE CONTINUIDAD: los CYCLES 89–134 se registraron en `research_log.md` (log canónico de investigación) +
> `decomposition_tree.md` / `roadmap.md`, no en este manager_log. Resumen del arco 89–134: consolidación R-VALOR
> (asignación vector/cost-aware 100-114), arco de FRAGILIDAD del auto-entrenamiento (115-121), payoff DECISIONAL bajo
> escasez (122-126), y la rama CONTROL/ACCIÓN (127-134: keystone valor=ctrl×rel, el agente descubre AMBOS factores de
> una experiencia). Ver research_log para el detalle por ciclo.

## [2026-06-26] CYCLE 135 — H-V4-10i MIXTA (núcleo apoyado + 3 overclaims retractados por verificación adversarial, 5to ciclo): la relevancia bajo meta NO-LINEAL es discoverable con una BASE de credit-assignment expresiva (cierra el caveat EJE2 de 134)
- Archivos: cognia_x/experiments/exp119_basis_relevance/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle135_basis_relevance.py (new), cognia_x/tests/test_cycle135_basis_relevance.py (new),
  research_log.md / decomposition_tree.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 5/5; engine 20/20; cycle135 por el engine MIXTA, D-V4-97 aceptada, verify_no_loss=OK.
- Resultado exp (200 seeds): bajo meta PAR la base LINEAL de 134 cae (ambos=0.640 vs ctrl_solo 0.490, corr_w 0.18) por
  ORTOGONALIDAD-DE-PARIDAD; la base MATCHED y la RICA genérica la RESUCITAN (ambos=1.000, +0.360, t~17.6), robustas a las 4 formas
  y a sustratos más duros (graded, disociado, D=16); leakage-free (4 controles nulos). NÚCLEO APOYADO.
- Notas: VERIFICACIÓN ADVERSARIAL de 4 agentes (5to ciclo seguido) confirmó el núcleo y CAZÓ 3 overclaims -> MIXTA (directiva v4,
  bundle de claims): (1) 'el prior paga' es ~80% artefacto de sub-regularizar la base rica (gap σ_g=20 +0.29@ridge0.01 -> +0.07@
  ridge0.3, cross-validable); (2) 'no hay base fija universal' FALSO (relu fijo peor-caso 0.99; sólo falla la paridad-PURA
  ortogonal); (3) 'une R-VALOR con R-PRIOR' = puente sugerido, no testeado. El experimento se reescribió para AUTO-DOCUMENTAR la
  MIXTA (probe robustez-a-ridge + relu peor-caso en run.py). Sirve al GOAL (R-VALOR; acota el factor RELEVANCIA bajo no-linealidad).
  Próximo: testear R-PRIOR EXPLÍCITO (aprender/seleccionar la base; ¿iguala un aprendiz sin-forma a la base matched? si sí, el
  cuello R-PRIOR queda refutado).

## [2026-06-26] CYCLE 136 — H-V4-10j MIXTA (refutación ACOTADA al régimen abundante; verificación adversarial de 3 agentes, 6to ciclo): el cuello R-PRIOR de la relevancia bajo no-linealidad es REGIME-DEPENDENT (neutralizado en abundancia, reaparece en escasez)
- Archivos: cognia_x/experiments/exp120_learned_basis/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle136_learned_basis.py (new), cognia_x/tests/test_cycle136_learned_basis.py (new),
  research_log.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 5/5; cycle136 por el engine MIXTA, D-V4-98 aceptada, verify_no_loss=OK.
- Resultado exp (200 seeds): testea si un aprendiz que cross-valida (rich_cv: ridge por K-fold CV; select_cv: elige base por CV)
  -SIN conocer la forma de la meta- iguala al oracle-prior. ABUNDANCIA (T=300): neutraliza ~85% del gap de 135 (σ_g=20: +0.245 ->
  +0.04); la fairness no lo derriba (matched_cv apenas mejora -> el 'prior paga' de 135 ERA sub-regularización). ESCASEZ
  (T~24-30~#columnas, σ_g=5): rich_cv colapsa (0.49), el prior paga +0.31. Refutación genuina sin leakage (3 controles nulos).
- Notas: VERIFICACIÓN ADVERSARIAL de 3 agentes (6to ciclo seguido) confirmó la refutación GENUINA pero la ACOTÓ a MIXTA: (1)
  'IGUALA'='CASI IGUALA' (residual +0.04 a σ_g=20 chico pero significativo, t~2.2 -- varianza de columnas extra); (2) regime-
  dependent (el prior reaparece bajo escasez, escala con datos/parámetros); (3) select_cv no es del todo form-agnostic (su menú ES
  un prior grueso). El experimento se reescribió para AUTO-DOCUMENTAR (matched_cv + barrido-T escasez + t pareado). CIERRA/ACOTA el
  arco no-linealidad de R-VALOR (134->135->136). Sirve al GOAL (R-VALOR). Próximo: relevancia bajo sustrato ACOPLADO (133); lazo
  acción-consecuencia REAL; active inference; SCALE.

## [2026-06-26] CYCLE 137 — H-V4-10k APOYADA (con caracterización HONESTA tras verificación adversarial de 3 agentes, 7mo ciclo): el agente DESCUBRE el R-VALOR de un sustrato ACOPLADO de UN stream (b̂+Â+ŵ) y lo compone en la reach-relevancia; unifica 128+133+134
- Archivos: cognia_x/experiments/exp121_coupled_discovery/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle137_coupled_discovery.py (new), cognia_x/tests/test_cycle137_coupled_discovery.py (new),
  research_log.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 7/7; cycle137 por el engine APOYADA, D-V4-99 aceptada, verify_no_loss=OK.
- Resultado exp (200 seeds): intersección de la frontera de 134 (relevancia bajo sustrato ACOPLADO): el agente descubre b̂ (ctrl),
  Â (acople, system-ID) y ŵ (relevancia, credit-assignment) de UN stream y compone |b̂·(I-Â)^-T ŵ|. Load-bearing = (i) estimación
  de un stream basta (composed converge desde abajo, T=30 0.76 -> 1.000) y (ii) la forma es necesaria (transpuesta incorrecta 0.49,
  1-hop falla en multihop, local 0.42 falla). Reach_net sobre control puro +0.49. Colinealidad NO confunde ŵ (corr_w=1.00).
- Notas: VERIFICACIÓN ADVERSARIAL de 3 agentes (7mo ciclo) confirmó el núcleo leakage-free (decoy/ruido colapsan a ctrl_solo; la
  transpuesta incorrecta falla) pero ACOTÓ la presentación a APOYADA-CON-CARACTERIZACIÓN-HONESTA: no sobre-vender el 1.000 (forma=
  oracle por construcción, lo load-bearing son los gaps); baseline justo (reach_net +0.49 sobre control puro, el +0.59 sobre el
  local sobre-vende porque el local se auto-sabotea); fallo del local condicional (extremo adversarial); válido con radio<1 (DAG).
  El experimento se reescribió para AUTO-DOCUMENTAR (composed_noT + ctrl_only + reach_net). CIERRA la frontera de 134 y UNIFICA el
  arco control/acción 127-137. Sirve al GOAL (R-VALOR). Próximo: acople con CICLOS; lazo acción-consecuencia REAL; active inference;
  SCALE.

## [2026-06-26] CYCLE 138 — H-V4-10l MIXTA (puente TEÓRICO a active inference válido + emergencia EMPÍRICA tautológica; verificación adversarial de 3 agentes, 8vo ciclo): el keystone es el límite binary+uniforme de la EFE pragmática, pero la corrección robusta es la varianza-prior v, no el cuadrado w²
- Archivos: cognia_x/experiments/exp122_active_inference/{__init__,run}.py (new),
  cognia_x/research/cycles/cycle138_active_inference.py (new), cognia_x/tests/test_cycle138_active_inference.py (new),
  research_log.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 5/5; cycle138 por el engine MIXTA, D-V4-100 aceptada, verify_no_loss=OK.
- Resultado exp (400 seeds): ¿emerge el keystone de minimizar la energía libre esperada? PUENTE TEÓRICO válido: el término
  pragmático de la EFE (modelo lineal-gaussiano + preferencia gaussiana) = w²·v·ctrl; el keystone (w·ctrl, 129) es su LÍMITE
  binary+uniforme (w²=w, v=1) -> grounding normativo del producto. El producto es learnable leakage-free (T=10 0.67 -> 1.00).
- Notas: VERIFICACIÓN ADVERSARIAL de 3 agentes (8vo ciclo) confirmó el puente teórico pero cazó un OVERCLAIM MAYOR -> MIXTA: la
  'emergencia EMPÍRICA' es TAUTOLÓGICA (el scorer efe_pragmatic ES byte-idéntico a la métrica del eval -> efe=oracle por
  construcción); el '+0.43 refinamiento' es artefacto de un canónico hand-tuned (mediana ~0 en 200 configs aleatorias); el mecanismo
  w² es FALSO (la varianza-prior v hace el grueso; bajo estimación el cuadrado DAÑA: w·v·ctrl > w²·v·ctrl) -> la corrección robusta
  es incluir v; la unificación con exploración es conjetura. El experimento se reescribió para AUTO-DOCUMENTAR. APORTE NETO: el
  puente normativo (keystone=límite EFE) + la corrección por varianza-prior v. Sirve al GOAL (R-VALOR; grounding normativo). Próximo:
  extender el puente EFE a no-lineal/acoplado; lazo acción-consecuencia REAL; SCALE.

## [2026-06-26] CYCLE 139 — H-V4-10m MIXTA (núcleo apoyado + 4 overclaims retractados por verificación adversarial de 4 agentes, 9no ciclo): la reach de estado-estacionario CRUDA del 137 es NUMÉRICAMENTE FRÁGIL cerca de radio espectral 1 (necesita regularización), pero el gap es artefacto de K=1, la forma horizonte no es única, y la relevancia es colineal
- Archivos: cognia_x/experiments/exp123_cyclic_substrate/{__init__.py,run.py,results/results.json} (nuevo);
  cognia_x/research/cycles/cycle139_cyclic_substrate.py (nuevo); cognia_x/tests/test_cycle139_cyclic_substrate.py (nuevo);
  research_log.md / manager_log.md / roadmap.md (append).
- Resultado tests: PASS — test dirigido 7/7; cycle139 por el engine MIXTA, D-V4-101 aceptada, verify_no_loss=OK.
- Resultado exp (200 seeds): ataca el caveat EXPLÍCITO de 137 ("acople con ciclos cerca de radio 1 degrada"). Sustrato lineal con
  un CICLO de feedback (radio=a+g->1) que COMPITE con un lazo FAST de 1-hop por la capacidad K. NÚCLEO (leakage-free, sim-validado):
  la reach de estado-estacionario CRUDA del 137 ((I-Â)^-1) es NUMÉRICAMENTE FRÁGIL cerca de radio 1 -- el modo casi-crítico la infla
  y bajo K=1 mis-rankea el modo top (radio 0.95: reach_inf 0.43 vs reach_H 1.00); ES LA FORMA (reach_inf_true 0.43 vs 1.00); una
  REGULARIZACIÓN la cura (descontada, cap-de-autovalor SIN-H). Estimable (T=12 0.42 -> T=1000 1.00; Â:=0 -> 0.06); sim_check 1.00.
- Notas: VERIFICACIÓN ADVERSARIAL de 4 agentes (9no ciclo; lentes tautología/leakage/fairness/robustez, todos con probes reales)
  confirmó el núcleo pero CAZÓ 4 OVERCLAIMS -> MIXTA: (1) el gap titular es ARTEFACTO de K=1 winner-take-all (a K>=2 evapora:
  gap_true +0.57 -> +0.00; reach_inf identifica el conjunto correcto, sólo invierte #1<->#2); (2) la forma horizonte-H NO es
  privilegiada (una reach-∞ regularizada por cap-de-autovalor SIN H la iguala -> la novedad es regularizar el modo casi-crítico, no
  el horizonte); (3) la RELEVANCIA es COLINEAL (ŵ≡unos no colapsa a ctrl_only -> el control shuffle daba falso positivo; load-bearing
  = la controlabilidad-reach, no la relevancia); (4) 'falla cerca de radio 1' requiere COMPETENCIA de escalas temporales (un único
  lazo no falla hasta radio 0.99). El experimento se REESCRIBIÓ para AUTO-DOCUMENTAR la MIXTA (agregó barrido de K, reach_inf_reg,
  control ŵ≡unos, barrido de estructura). HALLAZGO honesto: caveat REAL de CONDICIONAMIENTO al 137 (la reach-∞ cruda necesita
  regularización bajo ciclos), pero la forma no es única, el efecto vive bajo K=1 y la relevancia no se aísla aquí. ACOTA -- no
  cierra -- la frontera 'ciclos' de 137. Sirve al GOAL (R-VALOR; caracteriza el dominio del factor de controlabilidad-reach).
  Próximo: aislar la relevancia bajo ciclos; el efecto de la capacidad K; el puente EFE (138) bajo condicionamiento; lazo real; SCALE.

## [2026-06-26] CYCLE 140 — H-V4-9g MIXTA (SALIR DEL ORÁCULO; 4 retracciones por verificación adversarial de 4 agentes, 10mo ciclo): primer intento de aterrizar el payoff decisional del R-VALOR en un LAZO TORCH REAL — el paso (decisión endógena + verificador real) es real y hay una ventaja de ranking AUROC modesta del durable, pero el titular precision@m estaba CONFUNDIDO con el base-rate, no es significativo a N=4, el mecanismo era falso y el framing sobre-vendido
- Archivos: cognia_x/experiments/exp124_decisional_real_loop/{__init__.py,run.py,results/results.json} (nuevo);
  cognia_x/research/cycles/cycle140_decisional_real_loop.py (nuevo); cognia_x/tests/test_cycle140_decisional_real_loop.py (nuevo);
  research_log.md / manager_log.md / roadmap.md (append). Rumbo elegido por autonomía ("haz lo que quieras"): atacar el hueco #1
  de la auditoría de la teoría (salir del numpy-con-oráculo hacia un lazo real).
- Resultado tests: PASS — test dirigido 6/6 (lógica de veredicto sobre per_seed sintético; el lazo torch real es lento ~30min y se
  verifica corriendo el experimento, no en el test); cycle140 por el engine MIXTA, D-V4-102 aceptada, verify_no_loss=OK.
- Resultado exp (4 seeds × 8 rondas, PyTorch CPU): reusa el lazo cerrado REAL (HybridLM genera 'N=a*b' -> verificador REAL sandbox
  exp018 -> confianza ENDÓGENA -> self-train con/sin cura 119). NÚCLEO: la decisión es endógena (ranking por confianza, el oráculo
  sólo mide) + verificador real; ventaja de RANKING base-rate-INVARIANTE del durable AUROC 0.885 vs naive 0.802 (+0.083, 4/4 seeds,
  jackknife-min +0.058, t=3.23), MODESTA.
- Notas: VERIFICACIÓN ADVERSARIAL de 4 agentes (10mo ciclo; lentes confound/tautología/robustez/framing, todos con probes reales)
  confirmó el núcleo (sin leakage; decisión endógena + verificador real) pero CAZÓ 4 OVERCLAIMS -> MIXTA: (1) CONFOUND DE BASE-RATE
  -- el titular precision@m estaba confundido (los brazos generan distinto #correctas; la 1ra versión NI logueaba el del naive ->
  irrecuperable); corregido con AUROC/lift/base-rate de ambos brazos (en el régimen completo el confound resultó chico). (2) NO
  significativo a N=4 (underpowered). (3) MECANISMO FALSO (no hay pico en f=1; pico en f=0.5 trivial, monótono-decreciente; el gate
  decision_driven era vacuo). (4) FRAMING sobre-vendido ('sale del oráculo' acotado -el verificador supervisa todo el lazo-;
  'transfiere' es eco atenuado vs exp107). El experimento se REESCRIBIÓ para AUTO-DOCUMENTAR. APORTE NETO: el paso metodológico real
  (decisión endógena + verificador real) + una ventaja AUROC modesta + la LECCIÓN (controlar base-rate con AUROC/lift + N suficiente).
  El payoff decisional LIMPIO del R-VALOR sigue SIN aterrizar fuera del juguete. Sirve al GOAL (R-VALOR; ataca el hueco #1 de la
  auditoría). Próximo: re-correr con N>=8 + base-rate emparejado; SCALE; verificador rico; lazo secuencial.

## [2026-06-27] CYCLE 141 — H-V4-9h MIXTA (SALIR DEL ORÁCULO POWERED; 5 sub-claims retractados por verificación adversarial de 3 agentes, 11mo ciclo): potenciar a N=8 NO resuelve limpio el underpowered de 140 — la ventaja de ranking AUROC de la cura 119 en el lazo real EXISTE y es base-rate-invariante, pero su significancia es FRÁGIL (sign-test no la sostiene, magnitud diluyéndose con N) y el 'mecanismo creciente' es un artefacto del cero de la ronda-1 (efecto inmediato, no acumulado)
- Archivos: cognia_x/experiments/exp125_decisional_powered/{__init__.py,run.py,results/results.json} (nuevo);
  cognia_x/research/cycles/cycle141_decisional_powered.py (nuevo); cognia_x/tests/test_cycle141_decisional_powered.py (nuevo);
  research_log.md / manager_log.md / roadmap.md (append). Continuación natural de 140 (autonomía total hasta deadline).
- Resultado tests: PASS — test dirigido 6/6 (lógica de veredicto powered sobre per_seed sintético; el lazo torch es lento ~60min y
  se verifica corriendo el experimento); cycle141 por el engine MIXTA, D-V4-103 aceptada, verify_no_loss=OK.
- Resultado exp (8 seeds × 8 rondas, PyTorch CPU): potencia a N=8 la ventaja de ranking del durable que 140 dejó underpowered.
  AUROC durable 0.878 vs naive 0.827 (gap +0.050, 7/8 seeds), base-rate-INVARIANTE (corr(nc,auroc) dentro de brazo ≈0).
- Notas: VERIFICACIÓN ADVERSARIAL de 3 agentes (11mo ciclo; lentes significancia/base-rate/mecanismo, todos con probes reales sobre
  el log) confirmó que la ventaja EXISTE y es base-rate-invariante pero CAZÓ 5 OVERCLAIMS -> MIXTA: (1) significancia FRÁGIL (sign-
  test p=0.070 NO sig -el test que definió el underpowered de 140-; jackknife tumba 2/8); (2) magnitud DILUYÉNDOSE con N (1ra mitad
  +0.083 vs 2da +0.018; winner's curse); (3) 'base-rate emparejado' FALSO (la defensa es invariancia empírica); (4) 'mecanismo
  crece/previene colapso' ARTEFACTO del cero de la ronda-1 (pendiente sin ronda-1 -0.003 t=-0.4; ambos colapsan; efecto INMEDIATO no
  acumulado); (5) casi-tautológico (el unlikelihood optimiza lo que AUROC mide) + strawman. El experimento se REESCRIBIÓ para
  AUTO-DOCUMENTAR. APORTE: honestidad de que potenciar NO rescató el efecto (se diluyó) + mecanismo corregido (inmediato) +
  invariancia empírica como defensa correcta. El underpowered de 140 no se resuelve limpio. Sirve al GOAL (R-VALOR; rigor sobre el
  payoff decisional en el lazo real). Próximo: N=16; baseline regularizador alternativo; SCALE.

## [2026-06-27] CYCLE 142 — H-V4-10n MIXTA (EJE DE CAPACIDAD del keystone; 3 acotaciones por verificación adversarial de 2 agentes, 12mo ciclo): el producto R-VALOR importa bajo la INTERACCIÓN de capacidad escasa (K bajo) × disociación (ctrl≠rel) -explica el K=1-load-bearing de 139- pero el decaimiento-en-K es parcialmente trivial (random también decae a K=D), es una RECOMBINACIÓN de escasez (123-126) + disociación (130), y vale sólo para marginales graduadas (binarias invierten el orden)
- Archivos: cognia_x/experiments/exp126_capacity_keystone/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle142_capacity_keystone.py (nuevo); cognia_x/tests/test_cycle142_capacity_keystone.py (nuevo); research_log/manager_log/roadmap (append). Pivote a numpy-rápido tras el arco torch 140-141 (autonomía total).
- Resultado tests: PASS — 6/6; cycle142 por el engine MIXTA, D-V4-104 aceptada, verify_no_loss=OK.
- Resultado exp (numpy, 300 seeds): AUC ventaja anti=0.202>indep=0.107>corr=0.015 (monótona/suave en ρ_bw); K* relativo ≈0.7·D.
- Notas: verificación adversarial de 2 agentes confirmó el núcleo (graduado, robusto en D/RHO/seeds) pero acotó 3 cosas (decaimiento parcialmente trivial -random también decae-; recombinación -forma universal-; binario invierte) -> MIXTA. El experimento se reescribió para auto-documentar. Aporte: la síntesis capacidad×disociación que explica el K=1-load-bearing de 139. Sirve al GOAL (R-VALOR; unifica el eje de capacidad). Próximo: aislar la relevancia bajo ciclos (resto de 139); SCALE.

## [2026-06-27] CYCLE 143 — H-V4-10o MIXTA (aislar la relevancia bajo ciclos reach≠relevancia; 3 acotaciones por verificación adversarial de 2 agentes, 13mo ciclo): bajo escasez de capacidad K=1 + decoys la relevancia es load-bearing (robusto radio/T/seeds), pero EVAPORA a K>=#drivers (el artefacto K=1 que 139 ya había retractado), el cierre depende de los decoys (n_decoy=0 reproduce 139), y reach=oracle es tautológico -> NO cierra el caveat de 139 incondicionalmente
- Archivos: cognia_x/experiments/exp127_relevance_isolation/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle143_relevance_isolation.py (nuevo); cognia_x/tests/test_cycle143_relevance_isolation.py (nuevo); research_log/manager_log/roadmap (append). Frontera #1 de 139 (autonomía total).
- Resultado tests: PASS — 5/5; cycle143 por el engine MIXTA, D-V4-105 aceptada, verify_no_loss=OK.
- Resultado exp (numpy, 200 seeds): K=1 reach=1.0 (+0.725 sobre ctrl_only, +1.0 sobre rel_only, ambos controles rompen); EVAPORA a K=3=#drivers (reach-ctrl +0.0, reach-ones +0.0); n_decoy=0 reproduce 139 (ones-break +0.0).
- Notas: la verificación cazó que estaba "cerrando" 139 con el mismísimo artefacto K=1 que 139 había retractado (no barría K) + tautología reach=oracle + dependencia de decoys. El experimento se reescribió para auto-documentar (barrido K + n_decoy=0). Aporte: honestidad de que el cierre es condicional (escasez+decoys) + conexión con 142. Sirve al GOAL (R-VALOR; rigor sobre la disociación reach/relevancia). Próximo: aislamiento sin dependencia de K=1; SCALE.

## [2026-06-27] CYCLE 144 — H-V4-10p MIXTA (caracteriza el hallazgo neto de 138 -corrección por varianza-prior v-; mi hipótesis REFUTADA + mapa de régimen que VINDICA el 138; verificación adversarial de 2 agentes, 14mo ciclo): la forma robusta a través del eje es la EFE-completa w²·v·ctrl (no la simplificada w·v·ctrl que yo proponía); 'incluir v' es casi definicional + v̂=Var(x) contaminado por el control; el cuadrado es REGIME-DEPENDENT (daña con ŵ ruidoso -138 confirmado-, ayuda a baja-het)
- Archivos: cognia_x/experiments/exp128_variance_prior/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle144_variance_prior.py (nuevo); cognia_x/tests/test_cycle144_variance_prior.py (nuevo); research_log/manager_log/roadmap (append). Frontera #5 (varianza-prior v); autonomía total.
- Resultado tests: PASS — 5/5; cycle144 por el engine MIXTA, D-V4-106 aceptada, verify_no_loss=OK.
- Resultado exp (numpy, 300 seeds): el cuadrado daña con ŵ ruidoso (σ_g=5: v_corr-efe +0.096), ayuda a baja-het (+0.059); efe-completa domina; v̂ contaminado (corr b²~0.2-0.6), daña a baja-het.
- Notas: la verificación cazó mi overclaim BIDIRECCIONAL (definicional + refutación-deshonesta de 138) y protegió la AUTOCONSISTENCIA del ledger (yo refutaba erróneamente el 138 muestreando el rincón limpio). El experimento se reescribió para auto-documentar el mapa de régimen. Aporte: mapa de régimen del cuadrado + vindicación de 138. Sirve al GOAL (R-VALOR; rigor sobre la forma del valor bajo estimación). Próximo: la varianza-prior como saliencia en un sustrato real; SCALE.

## [2026-06-27] CYCLE 145 — H-V4-10q MIXTA (ataca el artefacto recurrente K=1 de 139/142/143 con capacidad CONTINUA; verificación adversarial de 2 agentes, 15mo ciclo): la ventaja del criterio de VALOR sobre el mejor factor-solo SOBREVIVE bajo water-filling de un presupuesto + escala con la disociación (robusto g/D/RHO/seeds) -> NO es específica del top-K discreto; PERO escaso-continuo es un winner-take-all BLANDO (soft top-k) -> el K=1 se REINTERPRETA como concentración-bajo-escasez, no se disuelve; residual permanente; decaimiento g-dependiente; value=oracle (recombinación de 142)
- Archivos: cognia_x/experiments/exp129_continuous_capacity/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle145_continuous_capacity.py (nuevo); cognia_x/tests/test_cycle145_continuous_capacity.py (nuevo); research_log/manager_log/roadmap (append). Ataca el caveat recurrente K=1; autonomía total.
- Resultado tests: PASS — 5/5; cycle145 por el engine MIXTA, D-V4-107 aceptada, verify_no_loss=OK.
- Resultado exp (numpy, 300 seeds): núcleo anti +0.385 (escaso), AUC continua anti=0.215>indep=0.142>corr=0.041; participación 1.84 a B=0.5 (soft top-2) -> 7.1 a B=32; residual +0.076; g=√a plana (0.105->0.105).
- Notas: la verificación cazó el overclaim 'sin winner-take-all / decae igual' (concentración + g-dependencia + residual). El experimento se reescribió para auto-documentar. Aporte: la ventaja del valor NO es discreto-específica + marco 'escasez=concentración blanda'. NOTA DE RUMBO: 5 MIXTA seguidos en la vena keystone/capacidad -> rendimientos decrecientes; pivotar a asignación real/SCALE. Sirve al GOAL (R-VALOR; rigor sobre si la ventaja del valor es un artefacto de selección).

## [2026-06-27] CYCLE 146 — H-V4-10r MIXTA (PIVOTE: ¿la factorización del keystone ayuda a APRENDER el valor? verificación adversarial de 2 agentes, 16mo ciclo): la factorización PRODUCTO ctrl×rel es un sesgo inductivo de BAJA CAPACIDAD útil para ESTIMAR el valor bajo escasez (robusto λ-justo/δ/noise/grado/seeds; minimalidad load-bearing) PERO condicional a la alineación-con-el-producto (con residuo ortogonal hunde al estimador, no free lunch); anti-tautología débil; decisión confundida por suficiencia de w·c
- Archivos: cognia_x/experiments/exp130_inductive_bias/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle146_inductive_bias.py (nuevo); cognia_x/tests/test_cycle146_inductive_bias.py (nuevo); research_log/manager_log/roadmap (append). PIVOTE fuera de la vena saturada; autonomía total.
- Resultado tests: PASS — 5/5; cycle146 por el engine MIXTA, D-V4-108 aceptada, verify_no_loss=OK.
- Resultado exp (numpy/ridge, 300 seeds): núcleo N=6 struct 0.005 < flex 0.014 < add 0.044; CONDICIONAL: w_only struct 0.028 > flex 0.010 (se hunde); colinealidad prod2 0.947; pairwise gana con prod2, colapsa con ortogonal.
- Notas: la verificación cazó un overclaim TRIPLE (anti-tautología vacua + decisión mis-caracterizada -suficiencia, no robustez- + incondicionalidad). El experimento se reescribió para auto-documentar. Aporte: el keystone como prior útil-si-matchea (bias-variance estándar) + estimar≠decidir. Sirve al GOAL (R-VALOR; rigor sobre si la factorización ayuda a APRENDER el valor). NOTA DE RUMBO: incluso fuera de la vena saturada, el keystone toy da resultados estándar acotados -> frontera real = sesgo inductivo APRENDIDO + SCALE.

## [2026-06-27] CYCLE 147 — SÍNTESIS-CAPSTONE del arco R-VALOR (no-experimental; barato, sin torch ni agentes — decisión de manager por uso 75% cerca del umbral)
- Archivos: cognia_x/research/STATUS_RVALOR.md (nuevo); manager_log/research_log (append).
- Qué: estado HONESTO del arco 79-146 anclado en veredictos reales commiteados — PROBADO (§1: keystone como límite EFE 138, forma robusta w²·v·ctrl 144, ventaja no-discreto-específica 145, sesgo inductivo útil-si-matchea 146, brújula decisional 120-123) / ASUMIDO-ACOTADO (§2) / REFUTADO-RETRACTADO (§3: tabla de los 9 overclaims cazados 138-146) / SATURACIÓN + FRONTERA REAL (§4: lazo real / salir-del-oráculo / SCALE) / % honesto (§5: ~70% mapa toy, ~10-15% real, 0% SCALE).
- Por qué sirve al GOAL: tras 6 MIXTA seguidos el toy lineal está saturado; la síntesis evita que el próximo ciclo re-derive lo establecido y apunta a la frontera real. Patrón completeness-critic. Decisión de no arrancar el lazo torch (~60 min + agentes) con uso 75% para no pasar el presupuesto y poder cerrar limpio.
- Resultado: documento permanente, grounded; no requiere pytest (no es código ejecutable). Regla registrada: el próximo ciclo ataca §4 o declara el bloqueo de hardware; verificación adversarial innegociable.

## [2026-06-27] CYCLE 148 — VERIFICACIÓN DE INTEGRIDAD de la corrida (barato: solo pytest, sin torch ni agentes — uso ~76%)
- Qué: corrí los tests de regresión de los 5 ciclos numpy de esta corrida (142-146) juntos -> 26 passed (5+5+5+5+6) en 233s. "Código que corre o no cuenta" aplicado a la obra de la sesión.
- Por qué sirve al GOAL: confirma que los 5 ciclos toy agregados (cada uno ya con su test 5/5 al cerrarse + verify_no_loss=OK en el engine) siguen verdes juntos -> la base acumulada es sólida antes del corte por deadline/reset.
- Resultado tests: PASS — 26/26. (140-141 son torch-lentos vía exp124/exp106; ya verificados al cerrarse, no re-corridos por presupuesto.)
- Notas: decisión de manager de hacer un ciclo barato de integridad en vez del lazo torch caro (~60 min + agentes) con uso 76% cerca del umbral 80%, para cerrar la corrida limpio. Capstone STATUS_RVALOR (147) + integridad (148) dejan la corrida en estado consultable y sólido.

## [2026-06-27] CYCLE 149 — H-V4-9i APOYADA (¡PRIMER APOYADA limpio del arco!; FRONTERA REAL §4.2 — resuelve a potencia el limbo del lazo real): en el lazo torch REAL la confianza endógena del durable (unlikelihood=cura 119) es MÁS INFORMATIVA sobre la correctness real que la del naive (ventaja AUROC base-rate-invariante, N=16 CI bootstrap [+0.027,+0.069] excluye 0, t=4.22; REPLICA out-of-sample 6/6 frescos -> N=22 t=5.87); verificación adversarial CONFIRMATORIA (5 métodos de CI, jackknife, mecanismo persistente, base-rate-invariante); acotación de régimen (concentrado donde el base-acc tiene margen)
- Archivos: cognia_x/experiments/exp131_decisional_resolution/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle149_decisional_resolution.py (nuevo); cognia_x/tests/test_cycle149_decisional_resolution.py (nuevo); research_log/manager_log/roadmap/STATUS_RVALOR (append/update). Aprovechó el reset de uso a 0% para atacar la frontera real (lazo torch).
- Resultado tests: PASS — 4/4; cycle149 por el engine APOYADA, D-V4-109 aceptada, verify_no_loss=OK.
- Resultado exp (lazo torch real, ~2-3 min/seed): N=16 gap AUROC durable-naive +0.047 (14/16, t=4.22, CI [+0.027,+0.069] excluye 0); out-of-sample 6/6 frescos -> N=22 t=5.87. Durable AUROC 0.875 vs naive 0.828.
- Notas: descubrir que el lazo es rápido habilitó N=16 (el 'underpowered' de 140-141 no era tiempo). La verificación CONFIRMÓ (por primera vez en el arco) con out-of-sample. Cierra el hueco #1 de la auditoría (salir del oráculo). Sirve directamente al GOAL (payoff/calibración del R-VALOR en un sistema REAL). Próximo: ¿cura privilegiada (tercer brazo)?; SCALE.

## [2026-06-27] CYCLE 150 — H-V4-9j REFUTADA (FRONTERA REAL §4.2 — el hueco que el 149 dejó EXPLÍCITO: ¿la cura 119 es PRIVILEGIADA?): NO lo es — un regularizador de TARGET-SMOOTHING genérico (label smoothing, label-agnostic) iguala su ranking AUROC y SUPERA su capacidad; ACOTACIÓN load-bearing: el AUROC está confundido con la riqueza de generación → NO se aísla 'calibración' como mecanismo (cualifica retroactivamente el 149). Verificación adversarial de 4 sondas (Workflow) CONFIRMATORIA
- Archivos: cognia_x/experiments/exp132_privileged_cure/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle150_privileged_cure.py (nuevo); cognia_x/tests/test_cycle150_privileged_cure.py (nuevo); research_log/manager_log/roadmap/STATUS_RVALOR (append/update).
- Diseño: mismo lazo torch real que exp124/exp131 (HybridLM → verificador real → confianza endógena → self-train), 5 brazos que difieren SÓLO en el regularizador del self-train: naive, durable (=cura 119, unlikelihood label-aware), ent_lo (entropy/confidence-penalty), ls_lo/ls_hi (label smoothing). Temperatura DESCARTADA a priori (AUROC-invariante por monotonía). Métrica: privilege_gap = AUROC(durable) − AUROC(mejor genérico por seed) + control de degeneración GATED + dump crudo.
- Resultado exp (lazo torch real, N=8 reducido — rounds=5, steps=70 por costo CPU ~10min/seed a settings full): privilege_gap −0.040, CI bootstrap 95% [−0.070,−0.012] ENTERAMENTE negativo (t=−2.48, 2/8 pos) → el genérico es SIGNIFICATIVAMENTE mejor, no empatado. AUROC durable 0.956 ≤ mejor-genérico 0.996 > naive 0.895. SANITY durable_vs_naive +0.060 (7/8) reproduce el 149. real_acc final: ls_lo 0.654 >> naive 0.174 > durable 0.129 (la cura termina DEBAJO del naive en accuracy).
- Verificación adversarial (Workflow, 4 sondas + síntesis): 3 'confirma' + 1 'acota' (mecanismo, severidad media). Cazó un ERROR FACTUAL en mi prosa del veredicto ("el CI incluye el cero" — FALSO, es enteramente negativo; bug `ci_excludes_zero=lo>0` sólo testea exclusión positiva → corregido con ci_below_zero) y un OVERCLAIM (re-localización a "calibración en general" sobre-vende: el AUROC está confundido con la riqueza de generación, arms en regímenes de ncorrect disjuntos, iguales en la banda de solape → reformulado a "target-smoothing reemplaza a la cura; no se aísla calibración"). Sondas: sanity-149 (harness válido), degeneración (gate FORTALECE la refutación; la degeneración infla al DURABLE no al genérico), justicia (durable pierde vs ls_lo solo, sin winner's curse), mecanismo (el confound de generación).
- Resultado tests: PASS — 3/3 (test_cycle150); cycle150 por el engine REFUTADA, D-V4-110 aceptada, verify_no_loss=OK.
- Notas: REFUTADA que AFINA, no demuele. La cura 119 NO es la pieza privilegiada (un target-smoothing barato la reemplaza y preserva mejor la capacidad). Y el hallazgo más valioso es el confound METODOLÓGICO: el payoff AUROC del lazo real (149 incluido) está entangled con la supresión/riqueza de generación → el 149 queda cualificado. Método: 17mo ciclo del arco con verificación adversarial antes del ledger; cazó error factual + overclaim. Próximo: DESCONFUNDIR calibración-de-generación (controlar #correctas); régimen base-acc alta; pago downstream; SCALE.

## [2026-06-28] CYCLE 151 — H-V4-9k MIXTA (FRONTERA REAL §4.2 — DESCONFOUND, el caveat load-bearing que el 150 descubrió): el "payoff de calibración" del lazo real es MAYORMENTE riqueza de generación; la atribución del 149 queda REFUTADA. Verificación adversarial de 4 sondas (Workflow) recomendó MIXTA ("NO usar APOYADA") y cazó 5 errores factuales/framing
- Archivos: cognia_x/experiments/exp133_deconfound_calibration/{run.py,results/results.json} (run.py CORREGIDO: error factual "generados desde el base"→CONSTRUIDOS; compuerta de veredicto endurecida CI-tautológico→t-test; results regenerado N=6); cognia_x/research/cycles/cycle151_deconfound_calibration.py (nuevo); cognia_x/tests/test_cycle151_deconfound_calibration.py (nuevo); research_log/manager_log/roadmap/STATUS_RVALOR (append/update).
- VERIFICAR-ANTES-DE-CONSTRUIR (cazado al arrancar): el results.json de exp133 estaba OBSOLETO respecto al run.py en disco (log guardado: "384 cands generado-desde-base, 7% positivos"; run.py: pool CONSTRUIDO BALANCEADO 96 cands 48/48 etiquetado por el verificador real). El run.py fue editado 3min DESPUÉS del results.json → re-correr obligatorio.
- Diseño: mismo lazo torch real que exp124/exp131/exp132, 3 brazos (naive, durable=cura 119, ls_lo=label smoothing ganador del 150). DESCONFOUND: además del AUROC_own (pool propio, métrica confundida del 149/150), TODOS los brazos rankean un POOL FIJO COMPARTIDO Y BALANCEADO (por prompt n: 1 positivo canónico + 1 negativo de-otro-target, etiquetados por el verificador real, 48/48 exacto, idéntico para los 3 brazos y fijo a lo largo de rondas) → AUROC_fixed aísla la separación-de-confianza de la riqueza de generación.
- Resultado exp (N=6 = merge 0-2 smoke + 3-5, escala smoke rounds=4/steps=50 por costo CPU): durable−naive OWN +0.057 → FIXED −0.210 (CI [−0.245,−0.175], t=−10.6, 6/6 seeds NEG; AUROC_fixed durable 0.760 vs naive 0.970) → la cura se INVIERTE: su ventaja del 149 era ENTERAMENTE riqueza de generación (genera 11.8 correctas vs naive 95.9). ls_lo−naive OWN +0.052 → FIXED +0.018 (6/6 positivos PERO t=1.98 < t_crit df=5=2.015) → sólo SIGNO, NO robusto.
- Verificación adversarial (Workflow, 4 sondas + síntesis): 1 CONFIRMA (la inversión del durable es genuina, monótona, 6/6; trained-only ~0.62 → aún más profunda que el titular) + 3 ACOTAN (sev media): (C) la supervivencia ls_lo NO es robusta — 'CI bootstrap excluye 0' es TAUTOLÓGICO con gaps un-signo, t-test sub-significativo, media partida a la mitad N=3→N=6, 2/6 seeds, régimen-dependiente; (A) AUROC_fixed es sondeo IN-DISTRIBUTION casi-en-techo (no held-out); (D) 'APOYADA-calibración' lavanderiza (agrupa 149-refutado con residuo genérico) → re-etiquetar MIXTA. Cazó 5 errores factuales/framing (incl. "generados desde el base"→CONSTRUIDOS, y la compuerta tautológica). REACCIÓN: corregí run.py (error factual + compuerta robusta por t-test), re-sumaricé → MIXTA.
- Resultado tests: PASS — 4/4 (test_cycle151: lógica refutada/apoyada/mixta del desconfound + consistencia + balance del pool); 11/11 (149+150+151); 24/24 (engine). cycle151 por el engine MIXTA, D-V4-111 aceptada, verify_no_loss=OK.
- Notas: 18vo ciclo del arco con verificación adversarial antes del ledger. MIXTA honesta y deflacionaria: cierra el caveat del 150 (confound de generación CONFIRMADO) y REFUTA la atribución 'calibración' del 149 (la observación durable>naive OWN persiste; su interpretación cae). Lo no-artefacto del lazo real es genérico, mínimo y no robusto. Lección transversal: el CI-bootstrap-excluye-0 NO prueba robustez con gaps un-signo; usar t-test pareado. Próximo: ¿el residuo genérico PAGA DOWNSTREAM en una decisión real bajo escasez (precision@top-m sobre el pool fijo)?; N≥8 con t-test; régimen base-acc alta; ranking held-out; SCALE.

## [2026-06-28] CYCLE 152 — H-V4-9l MIXTA-ACOTADA (FRONTERA REAL §4.2 — la pregunta viva del 151: ¿el residuo paga DOWNSTREAM?): el residuo genérico NO paga ROBUSTAMENTE bajo escasez, PERO el test SATURA y NO instancia la escasez real → ACOTADA, no refutación-plana. Verificación adversarial de 4 sondas (design_valid=False) cazó un DEFECTO DE DISEÑO (sev ALTA)
- Archivos: cognia_x/experiments/exp134_downstream_payoff/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle152_downstream_payoff.py (nuevo); cognia_x/tests/test_cycle152_downstream_payoff.py (nuevo); research_log/manager_log/roadmap/STATUS_RVALOR (append/update).
- Diseño: mismo lazo torch real, 3 brazos. Cada brazo asigna confianza a DOS pools fijos balanceados 48/48 (compartidos, etiquetados por el verificador real): INDIST (forma canónica '1+(n-1)') y HELDOUT (forma NOVEL '2+(n-2)' no entrenada, ataca la acotación in-distribution de la sonda-A del 151). Métrica decisional: precision@top-m = #correctas entre las top-m por confianza / min(m,#correctas), barrido m={1..24}; gap ls_lo−naive y durable−naive (AUC sobre rondas).
- Resultado exp (N=6 merge 0-2 smoke + 3-5): MIXTA-ACOTADA. (a) el residuo ls_lo NO paga ROBUSTAMENTE (falla CI+t-test+6/6). (b) DEFECTO DE DISEÑO: el pool balanceado 50/50 SATURA precision@top-m → INDIST near-ceiling (naive payoff de escasez=1.0) → gap CERO ESTRUCTURAL (no-informativo); y por la lección de exp124 (f=m/#correct), con #correct=48 todo m de escasez → f<=0.17 (trivial), m_max=24 → f<=0.5 (nunca f≈1) → la tesis 123 (calibración paga bajo escasez q-bajo) NUNCA se testeó. (c) HELDOUT (único informativo, headroom): ls_lo−naive m=6 +0.028 (CI [0.007,0.056], t=2.0 < t_crit 2.015; 3/6 seeds+, 0 neg) → DÉBIL BORDERLINE no-robusto. (d) HALLAZGO ROBUSTO: el durable (cura 119) es robustamente NEGATIVO downstream en AMBOS pools (indist m=8 −0.042, t=−2.70) → confirma su INVERSIÓN del 151, también en la decisión y fuera-de-forma.
- Verificación adversarial (Workflow, 4 sondas + síntesis; recomendó MIXTA, design_valid=False): 1 CONFIRMA (saturación INDIST genuina, no bug) + 2 ACOTA (señal heldout débil/no-robusta; CI excluye 0 sólo por discretización) + 1 REFUTA (sev ALTA: el test no valida la tesis 123 — pool no escaso + saturado). Cazó: el mislabel "m chico=ESCASEZ" (contradice exp124, que abandonó el m-absoluto por f=m/#correct); el overstatement de negatividad (fusiona INDIST-saturado con evidencia adversa); el overclaim "señal genuina" del heldout; el criterio APOYADA inalcanzable por construcción en INDIST. REACCIÓN: añadí detección de SATURACIÓN al gate (un pool near-ceiling es no-informativo → veredicto sólo sobre pools informativos), reporté f=m/#correct, re-etiqueté MIXTA-ACOTADA.
- Resultado tests: PASS — 4/4 (test_cycle152: refutada/apoyada/mixta-por-saturación + consistencia + balance); 15/15 (149-152); cycle152 por el engine MIXTA, D-V4-112 aceptada, verify_no_loss=OK.
- Notas: 19no ciclo del arco con verificación adversarial antes del ledger. Un ciclo FALLIDO-INSTRUCTIVO: la verificación cazó un defecto de diseño (no de prosa) → el test no respondió su propia pregunta (régimen escaso real sin medir), pero confirmó la inversión del durable downstream y dejó sembrado el diseño correcto. Honestidad: ACOTADA, no refutación-plana. Próximo (CYCLE 153): pool fijo COMPARTIDO de BAJA base-rate (q≈0.1) o medir a f≈1, preservando el desconfound del 151; subir N; reportar f=m/#correct.

## [2026-06-28] CYCLE 153 — H-V4-9m MIXTA (1er POSITIVO-LEANING del arco, NO APOYADA): el diseño escaso/f≈1 que el 152 sembró FUNCIONA y da la 1ª señal positiva — pero NO robusta (LOO/Bonferroni) y RANK-ONLY (re-expresa el AUROC del 151, no testea calibración). Verificación adversarial de 4 sondas (signal_is_real=FALSE, overclaim_risk=ALTO) cazó un ERROR DE CATEGORÍA
- Archivos: cognia_x/experiments/exp135_scarce_downstream/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle153_scarce_downstream.py (nuevo); cognia_x/tests/test_cycle153_scarce_downstream.py (nuevo); research_log/manager_log/roadmap/STATUS_RVALOR (append/update).
- Diseño (corrige el 152): pool fijo COMPARTIDO ESCASO (base-rate 0.125 = 1 positivo + 7 negativos por prompt, #correct=20, etiquetado por el verificador real, desconfound del 151 preservado), 2 pools INDIST (forma canónica) + HELDOUT (forma novel '2+(n-2)'). Métrica decisional: precision@top-m POR f=m/#correct, barriendo el régimen DISCRIMINANTE f≈1 (recall de las pocas correctas). Compuerta HONESTA: el veredicto descansa en el f PRE-REGISTRADO 1.0 (no el max-t, anti cherry-pick).
- Resultado exp (N=6 merge 0-2 smoke + 3-5): MIXTA — 1er positivo-leaning del arco. (a) el DISEÑO funciona: pools NO saturan (informativos), f≈1 discrimina. (b) señal positiva: ls_lo−naive a f=1.0 positivo t-significativo SIN corregir en AMBOS pools (indist +0.054 CI[0.015,0.098] t=2.29 5/6+; heldout +0.029 CI[0.006,0.048] t=2.36) y monótono en indist. (c) PERO no robusto (falla 6/6 -5/6-, leave-one-out del seed más favorable -t→1.83 indist / 1.77 heldout < 2.015-, Bonferroni -familia 14, t_crit 4.382-; indist cargado 77% por 2 seeds, monótono no replica en heldout; N=6 smoke). (d) durable robusto NEG downstream (indist f=1.0 −0.271, t=−8.58) → confirma su inversión del 151/152 fuera-de-forma.
- Verificación adversarial (Workflow, 4 sondas + síntesis; recomendó MIXTA, design_valid=True, signal_is_real=FALSE, overclaim_risk=ALTO): 1 CONFIRMA (MIXTA es honesto, ni APOYADA-overclaim ni REFUTADA-deflación) + 3 ACOTA. Cazó (sonda-mecanismo, load-bearing): ERROR DE CATEGORÍA — precision@top-m vía np.argsort es RANK-ONLY (invariante a transformaciones monótonas de la confianza, igual que AUROC) → NO testea CALIBRACIÓN, testea RANKING; la ventaja del ls_lo RE-EXPRESA el AUROC del 151 (+0.018, co-mueven round-level r≈0.87) → 0 información decisional independiente → NO prueba la tesis 123, sólo la APUNTA. También: el t_crit Bonferroni estaba subestimado (4.382 no ~3.0); 'no es artefacto de 1-2 seeds' es FALSO para indist (LOO + corr cruzada ~0). REACCIÓN: añadí el caveat rank-only al veredicto de exp135; el gate ya usa el f pre-registrado (anti cherry-pick) y reporta lslo_robust_anyf separado.
- Resultado tests: PASS — 5/5 (test_cycle153: refutada/apoyada-en-f1/mixta-por-saturación + anti-cherry-pick + consistencia + base-rate escaso); 151+152+153 13/13; cycle153 por el engine MIXTA, D-V4-113 aceptada, verify_no_loss=OK.
- Notas: 20mo ciclo del arco con verificación adversarial antes del ledger. PRIMER positivo-leaning tras 4 deflacionarios → verificación EXTRA dura contra overclaim (el sesgo a evitar). El arco toca su 1er positivo pero sugestivo-no-concluyente y rank-only → la pregunta '¿la calibración paga downstream?' queda BIEN PLANTEADA. Lección: una métrica rank-only NO testea calibración; el 1er positivo tras una racha deflacionaria es el de mayor riesgo de overclaim (bar más alto: LOO + Bonferroni + métrica que separe mecanismo). Próximo (CYCLE 154): métrica decisional NO invariante-a-monótonas (cost-weighted / umbral-abstención) que SEPARE calibración de ranking; N≥12; LOO + Bonferroni; réplica out-of-sample.

## [2026-06-28] CYCLE 154 — H-V4-9n REFUTADA-de-RELIABILITY (CAPSTONE del arco downstream): el residuo del lazo real es RANKING, no CALIBRACIÓN. Métricas magnitude-sensitive (ECE=reliability pura) resuelven el limbo rank-only del 153. Verificación adversarial de 4 sondas (3 ACOTA + 1 REFUTA) acotó el oversell del negativo
- Archivos: cognia_x/experiments/exp136_calibration_metric/{__init__.py,run.py,results/results.json} (nuevo); cognia_x/research/cycles/cycle154_calibration_metric.py (nuevo); cognia_x/tests/test_cycle154_calibration_metric.py (nuevo); research_log/manager_log/roadmap/STATUS_RVALOR (append/update).
- Diseño (el test DECISIVO que el 153 definió): sobre el pool fijo ESCASO del 153 (desconfound del 151 preservado), la confianza endógena (mean-logprob) se convierte a probabilidad p=exp(logprob) y se miden métricas SENSIBLES A MAGNITUDES (NO rank-invariantes): BRIER, ECE (10 bins, reliability PURA threshold-free), NET umbral-abstención cost-weighted (accept iff p≥τ*=λ/(1+λ), λ=3 pre-registrado), en PARALELO al AUROC rank-only. EL CONTRASTE: si la ventaja del ls_lo vive en AUROC pero se desvanece en ECE → era RANKING, no calibración. Compuerta anclada en ECE (robust_ece), no en Brier/NET (que mezclan resolution).
- Resultado exp (N=6 merge 0-2 smoke + 3-5): REFUTADA-de-RELIABILITY. (a) la reliability PURA (ECE) del ls_lo NO paga — plano-a-PEOR en AMBOS pools (indist −ECE −0.006 t=−1.28, ls_lo levemente peor; heldout +0.0004; el durable también peor). (b) el único payoff ROBUSTO es RANKING (heldout AUROC +0.017 t=3.74, disociación limpia: AUROC robusto con ECE/Brier nulos). (c) trazas indist −Brier +0.007 (t=2.21) y NET(λ3) +0.081 (t=1.95) son sub-robustas PERO RESOLUTION=ranking (co-mueven con AUROC ~0.82). (d) NET heldout DEGENERADO (nadie cruza τ OOD).
- Verificación adversarial (Workflow, 4 sondas + síntesis; recomendó REFUTADA-de-reliability, dissociation_clean=False, net_degenerate=True): 0 confirma + 3 ACOTA + 1 REFUTA. La conclusión de fondo (la reliability NO paga) es CORRECTA y las métricas VÁLIDAS (exp monótona → AUROC invariante; ECE/Brier sensibles a magnitud sin bug). Acotó el OVERSELL del negativo: (1) el −Brier/NET indist NO se desvanecen (CI excl 0) — son resolution=ranking, no reliability; (2) el NET heldout es DEGENERADO (cero estructural, no-evidencia); (3) FRAGILIDAD A N=6 (el label flipea por lote: seeds 3-5 solos darían APOYADA vía Brier/resolution = falso positivo del gate). REACCIÓN: anclé el veredicto en ECE (robust_ece), añadí detección de net_degenerate, reframé Brier/NET como resolution=ranking, suavicé 'cierra el arco' a 'no se detecta reliability vía ECE'.
- Resultado tests: PASS — 4/4 (test_cycle154: apoyada-ECE-robusta / refutada-rank-only / mixta-inconcluso + net_degenerate + consistencia); 151-154 17/17; cycle154 por el engine REFUTADA, D-V4-114 aceptada, verify_no_loss=OK.
- Notas: 21er ciclo del arco con verificación adversarial antes del ledger. CAPSTONE: CIERRA el arco downstream '¿calibración o ranking?' (149-154) del lado RANKING — lo que sobrevivió al desconfound del 151 es una señal de RANKING/discriminación, NO una señal de valor más calibrada; la tesis 123 ('la calibración paga') NO queda tocada por este residuo en el lazo real desconfundido. ACOTADO: N=6 smoke batch-frágil → 'no se detecta reliability residual', no 'demostrado imposible'. Mapa §5: sistema real 29%→31% (la pregunta calibración-vs-ranking RESUELTA). Próximo: réplica N≥12 con barra simétrica + umbral EV-óptimo por-brazo; o PIVOTE (régimen base-acc alta / transferencia / SCALE).

## [2026-06-28] CYCLE 155 — ROBUSTEZ: réplica N=12 del capstone 154 (H-V4-9n) → CONFIRMA la REFUTADA-de-RELIABILITY y resuelve la batch-fragilidad hacia REFUTADA
- Archivos: cognia_x/experiments/exp136_calibration_metric/results/results.json (regenerado a N=12 = merge seeds 0-5 + 6-11); STATUS_RVALOR/manager_log/research_log/roadmap (nota de robustez). NO es una hipótesis nueva (misma H-V4-9n) → réplica de potencia, registrada proporcionadamente sin ledger separado.
- Motivación: la verificación del 154 marcó el label batch-frágil a N=6 (seeds 3-5 solos darían APOYADA vía Brier/resolution). Extendí a N=12 (seeds 6-11) para firmar el resultado ECE con barra simétrica.
- Resultado (N=12): REFUTADA-de-reliability SE SOSTIENE. robust_ece=False, rank_only=True. ECE indist −0.0014 (t=−0.46, plano-a-peor); heldout +0.0017 (t=1.98, 9/12) — emerge una TRAZA positiva MINÚSCULA con más potencia PERO negligible en magnitud y NO robusta (no unánime 9/12, no Bonferroni). El payoff dominante sigue RANKING (AUROC indist t=2.25 / heldout t=2.73; −Brier=resolution t=4.24/2.85). La batch-fragilidad del N=6 se RESUELVE: el artefacto APOYADA de seeds 3-5 se lava a N=12.
- Resultado tests: PASS — test_cycle154 4/4 contra el results.json N=12 (REFUTADA, net_degenerate heldout, no robust_ece).
- Notas: confirma el capstone del arco downstream. El residuo del lazo real es RANKING; la reliability, a lo sumo, una traza negligible no-robusta. Próximo: PIVOTE de frontera (régimen base-acc alta donde el 149 se apagaba / transferencia a otra tarea) — el arco downstream está cerrado; SCALE sigue hardware-bloqueado.

## [2026-06-28] TRANSICIÓN INVESTIGACIÓN→CONSTRUCCIÓN — Readiness GO-CONDICIONADO + set completo de planos de build
- Tarea (/goal del dueño): "continuar en cognia-x hasta creer que podemos iniciar la práctica de construcción; cuando se pueda, crear TODOS los planos a nivel experto, detallados, honestos y con bases sólidas para construir."
- DECISIÓN DE READINESS: **GO CONDICIONADO** (cognia_x/construccion/00_READINESS.md). 4.5/5 criterios cumplen. Fundamento honesto: (C1) la ciencia toy R-VALOR está SATURADA — el propio lab lo declara tras 6 MIXTA seguidos (141-146) + arco downstream CERRADO 149-155; (C2) los subsistemas centrales están demostrados-en-pequeño (verificador real exp018/CYCLE51-55, lazo STaR 0.30→0.78 CYCLE48-50, coordinación no-regret CYCLE43, auto-eval+abstención CYCLE46, engine de hipótesis CYCLE22, meta-router CYCLE12-21); (C3) decisiones de arquitectura con evidencia (alta en dirección, MEDIA en constantes); (C4) el v0 HybridLM CORRE (verificado: 1.56M params, forward+features+generate+entrena 5.56→2.03); (C5) los 3 frentes que mueven la aguja REQUIEREN construir/escalar, no más toy. El medio-cumplimiento de C3 (constantes sin medir) hace el GO condicionado, no limpio.
- CONDICIONES DURAS (M0 = fase de validación, no más investigación): G1=A-018 (ahorro de banda SSM/SWA con kernels CPU SIN verificar; precedente exp007; RAMA DE FALLBACK Transformer GQA denso ya prevista), G2=fragilidad de recall del híbrido (estructural, exp002/010-015), G3=E4 RAG vs LoRA. SCALE=0% hardware-bloqueado (i3 sin CUDA → Kaggle para entrenar). R-VALOR usado como BRÚJULA decisional acotada (el arco 149-155 cerró del lado RANKING, no calibración).
- ENTREGABLE: cognia_x/construccion/ — 13 documentos, ~5400 líneas. 00_READINESS (GO/NO-GO), 01 arquitectura del sistema, 02 backbone CPU-first (rama A híbrido / B GQA), 03 entrenamiento+datos (Kaggle+STaR+ledger procedencia), 04 verificador real-chequeable (1ra clase), 05 lazo auto-mejora+guardia, 06 aprendizaje continuo (RAG+LoRA+FedEx-LoRA), 07 inferencia/cuantización (llama.cpp+Q4), 08 expertos/routing (LoRA por dominio), 09 razonamiento↔comunicación+meta-razonamiento+hipótesis, 10 registro de riesgos (44 riesgos priorizados), 11 plan maestro de build (M0…M6, orden Apéndice A: verificador→lazo+guardia→expertos), 00_INDICE.
- MÉTODO (el del lab, aplicado al meta-nivel): reconocimiento con 6 agentes extractores sobre los docs canónicos → 2 workflows (autor experto + verificador adversarial por plano, refutar-antes-de-aceptar) → crítico de completitud cross-file. La verificación adversarial CAZÓ defectos REALES de honestidad: exp019/exp020 (H-LEARN-4/5, ambos REFUTADA) citados como APOYO de "RL hackea/imitación no" en planos 04/05/03/09 → corregidos a REFUTADA con la nota de que la preferencia por imitación es precaución (literatura+exp017), no hack medido; numeración cruzada desfasada en el plano 01 → re-numerada a la canónica de 00_INDICE; roofline sobre-vendido en 07; ruta de test inexistente en 08. Todos resueltos y re-verificados.
- CAVEATS HONESTOS no escondidos: constantes de ARQUITECTURA confianza-media (las de runtime de inferencia SÍ medidas, plano 07); transferencia toy→escala = mayor incógnita (SCALE 0%); FedAvg-naive AÚN presente en coordinator/federated_store.py (corregir a FedEx-LoRA en M4, exp003 mide el error); piezas PENDIENTES (dos núcleos, pizarra, jerarquía de expertos) tratadas como fase tardía. El sistema entrega valor incluso en el peor caso de cada gate (rama B, PISTA-ADAPT, fine-tune offline, LoRA-para-hechos): ningún fallo de gate bloquea el build, solo redirige una caja.
- PRÓXIMO: arrancar M0 (validación de gates; G1 requiere bajar un GGUF SWA-nativo) con M1/M2 (verificador→lazo) EN PARALELO sobre el HybridLM tiny que ya corre. La investigación toy NO se reanuda (saturada); la construcción es ahora el experimento de mayor valor.

## [2026-06-28] M0 / Gates G1 (A-018) y G2 — herramienta de validación lista y verificada
- Contexto: tras los planos (commit 3547ae6), el dueño pidió RESOLVER G1 y G2 (lo que necesite GPU -> Colab). Son los gates que convierten el GO-CONDICIONADO en GO-LIMPIO sobre la arquitectura del backbone (rama A híbrido vs B GQA denso).
- G1 (CPU, A-018): cognia_x/construccion/m0_g1_bandwidth.py — stdlib, levanta node/llama-server.exe (b9391, --parallel 1, n_gpu_layers=0), barre L={512,2048,4096,8192}, mide decode tok/s(L) + prefill + RSS (PowerShell WorkingSet64, locale-robusto) + KV (best-effort). Veredicto: RAMA A si el SWA conserva >=70% del decode al crecer L Y mejor que el full. VERIFICADO contra Qwen-3B full presente: decode 8.48->5.98 tok/s (cae con L = firma de atención full); harness corre end-to-end. Falta UN GGUF SWA-nativo (los 6 locales son Qwen full).
- G2 (GPU, recall híbrido a escala): cognia_x/construccion/m0_g2_recall_colab.py — SELF-CONTAINED (embebe HybridLM fiel a model/hybrid.py + recall_task), corre en Colab T4 gratis sin clonar/instalar. 3 ejes: RATIO (mínima cuota de atención que cruza recall), ARREGLO (linear/attn-first/front/back), VENTANA (SWA local vs global). Escala d=256/12 capas/n_pairs=64. VERIFICADO: smoke CPU corrió los 12 configs end-to-end -> tabla+JSON+veredicto (el smoke tiny no entrena, sólo verifica el plumbing).
- Entrega: M0_G1_G2_ejecucion.md con comandos copy-paste (G1 local, G2 Colab). Próximo: correr G1 (descargar GGUF SWA Gemma-2-2B + medir) y G2 (Colab) -> interpretar -> fijar rama A/B en 02_backbone + 00_READINESS (GO-LIMPIO). NINGÚN resultado bloquea el build: sólo fija qué caja 02 se construye (el resto es agnóstico al backbone).

## [2026-06-28] M0 / G1 RESULTADO MEDIDO (A-018) — SWA ahorra MODESTO en CPU; lean RAMA B
- Corrí G1 yo (descargué gemma-2-2b-it-Q4_K_M, 1.7GB público; medí SWA vs full en el i3 b9391, --parallel 1, n_gpu_layers=0). Datos: results_g1/g1_{qwen3b_full,gemma2_swa}.json + M0_G1_RESULTADO.md.
- DATO: decode tok/s por L — Gemma SWA 8.11/6.20/4.95/3.70 vs Qwen full 7.67/5.19/3.79/2.72 (L=512/2048/4096/8192). Retención 2048->8192: SWA 0.597 vs full 0.525 (SWA +0.07, 36% más rápida a 8192).
- VEREDICTO honesto: la SWA SÍ ahorra banda en CPU pero MODESTO y gradual (no alcanza el umbral pre-registrado 0.70). HALLAZGO CLAVE que CONFIRMA la tesis del lab: el decode CPU es WEIGHT-READ-BOUND -> el costo dominante por token es leer los pesos (bytes/token), NO la atención; la SWA sólo reduce la KV (secundaria). Valida empíricamente bytes/token en el i3 (antes confianza media). Caveats: confound de tamaño (2B vs 3B), Gemma-2 es SWA débil (alterna, ventana 4096), y FALTA la mitad grande de RAMA A (el SSM O(1)/token, sin medir — pero ataca la KV secundaria).
- IMPLICACIÓN: a L<=8192 en CPU, RAMA A vs B NO es diferencia decisiva de decode (ambas weight-read-bound). Lean RAMA B (GQA denso, madura) para el v1; RAMA A se justifica por contexto MUY largo/RAM, no por decode a L moderado. El lever #1 de velocidad CPU es el TAMAÑO/cuantización, no el esquema de atención -> re-prioriza el plano 02. Lock final del backbone espera G2 (recall, en Colab) + opcional test SSM.

## [2026-06-28] Tooling — puente agente↔Colab GPU instalado (MCP fork + CLI oficial)
- A pedido del dueño (evitar copy-paste + desconexiones), instalé y verifiqué 2 herramientas (fuera del repo, en C:/Users/Tomanquito/colab-tools y .local/bin). Doc: cognia_x/construccion/COLAB_GPU_SETUP.md.
- (1) MCP fork SebastianGilPinzon/colab-mcp (arregla tools-invisibles + "Disconnected" + control GPU del oficial googlecolab/colab-mcp): uv oficial 0.11.25 instalado; clonado; primer arranche instaló 115 deps (incl pywin32) y --list-running corrió limpio; REGISTRADO en Claude Code (~/.claude.json, scope user) -> claude mcp list = ✔ Connected. 9 tools (open_colab_browser_connection + 7 notebook + change_runtime con OAuth).
- (2) CLI oficial google-colab-cli v0.6.0 (uv tool install): headless (colab new --gpu T4 / exec / log / rm). BUG de Windows cazado y parcheado: importaba termios/tty (solo-Unix) al cargar -> crasheaba; guardé los imports con try/except en console.py (sólo se usan en la consola TTY interactiva, guardada por is_tty) -> colab version/--help y comandos headless OK. CAVEAT: el parche vive en el dir del uv tool -> uv tool upgrade lo borra (re-aplicar o usar WSL).
- Verificación parada en el límite correcto: confirmé que cargan/responden (version/--help/list) SIN tocar la cuenta de Google ni provisionar GPU (eso gasta compute units del dueño + requiere su login). Lo que falta es del dueño: reiniciar Claude Code (cargar tools MCP) + colab auth (login Google) + opcional OAuth GCP para change_runtime.
- Relevancia: habilita disparar G2/entrenamientos en GPU de Colab desde el agente sin copy-paste. Para runs largos el CLI headless es más robusto que el MCP de navegador (free tier: 90min idle/12h máx).

## [2026-06-28] Handoff a sesión nueva — briefing + nuevo goal (entreno + velocidad raíz)
- El dueño superó la ventana de 1M tokens y pidió un prompt de goal autocontenido para arrancar fresco. Nuevo objetivo: entrenar la IA optimizando al MÁXIMO la velocidad de entreno, reentrenable y rápida, ATACANDO LA RAÍZ de "más params=más lento"; regla 10× antes de aceptar un límite; calidad↔velocidad matched; luego avanzar construcción; autonomía total.
- Escrito cognia_x/construccion/INICIO_AQUI_entreno_velocidad.md = briefing self-contained (objetivo + qué es el proyecto + hallazgos clave G1/G2 + infra de entreno Colab CLI + palancas de desacople + reglas + orden de lectura + primer paso).
- G2: re-lanzado en T4 (data-gen ya vectorizada+verificada) pero MUY LENTO (~1 step/s, GPU subutilizada, config 1/12 sin terminar en 9 min). Detenido para liberar la GPU. Documentado como el PRIMER objetivo concreto del nuevo goal (profilar por qué HybridLM entrena lento en T4: data-gen CPU/transfer, sin AMP, sin compile, batch chico, tril por forward). Aplica la regla 10×.
- Infra lista: colab CLI autenticado (oauth2 tomascomenta@gmail.com), patrón headless desacoplado documentado en COLAB_GPU_SETUP.md. G1 ya cerrado (lean RAMA B; decode CPU weight-read-bound = la raíz medida).

## [2026-06-29] G2 SPEED PROFILE — la raíz "más params=más lento" MEDIDA en T4 (regla 10× cumplida)
- Sesión nueva arrancada del briefing INICIO_AQUI_entreno_velocidad.md. Entorno OK (venv312 torch 2.12 CPU; colab-cli autenticado oauth2 tomascomenta@gmail.com). G2 a escala NO estaba cerrado: el g2_recall_results.json en disco era solo el SMOKE en CPU (d=64, 60 steps, todo cerca del azar). La corrida lenta real se había detenido.
- PROFILER escrito: cognia_x/construccion/m0_g2_profile.py (importa el modelo EXACTO de m0_g2_recall_colab = single source). Mide desglose por componente (datagen/fwd/bwd/opt) con torch.cuda.synchronize + 7 variantes de palancas. Validado local con --smoke (CPU) antes de gastar GPU.
- Corrido en Colab T4 (headless desacoplado: launcher Popen + sentinela PROF_DONE + checker que tail-ea el log; sobrevive desconexiones). RESULTADO MEDIDO (results_g2/g2_profile_results.json):
  · datagen = 0.86 ms/step (0.6% del tiempo) -> hipótesis "data-gen CPU-bound" REFUTADA.
  · cuda_available=True, GPU=Tesla T4 -> hipótesis "fallback CPU" REFUTADA.
  · baseline REAL = 7.0 step/s (143 ms: fwd 44.6 + bwd 93.3 + opt 4.4), NO 1 step/s. El "~1 step/s" reportado fue mala atribución (rebuild por config + eval cada 666 + configs lineal-mayoría que NUNCA hacían early-stop -> corrían el deadline entero).
  · Cuello real = fp32 + workload chico por step -> overhead/launch-bound (~6% del pico fp16; matrices d=256 no saturan SMs, sin tensor cores en fp32).
  · PALANCAS medidas: AMP fp16 = 1.9× (35.8k->67k tok/s); gpu-datagen = nulo (datagen ya despreciable); batch 256/512 satura ~74k tok/s; AMP+batch512+torch.compile = 147.8k tok/s = 4.1× sobre baseline. GPU mem máx 8.6/15 GB.
- FIX aplicado a m0_g2_recall_colab.py: AMP fp16 (autocast+GradScaler, unscale_ antes del clip; default ON en cuda, --no-amp para apagar; eval también bajo autocast) + plateau early-stop (corta no-aprendices claros: best<0.5 y patience=4 evals sin mejora -> no sesga el veredicto) + flag --compile (OFF default: recompila por config, caro en sweep) + steps 8000->5000, deadline/config 1500s->600s. Validado local con --smoke (AMP correctamente off en CPU, plateau presente, best_acc trackeado, corre completo).
- Doc: cognia_x/construccion/M0_G2_PROFILE_RESULTADO.md. Efecto esperado: sweep G2 cierra en ~15-20 min en T4 (antes >2h proyectado), sin tocar calidad (AMP fp16 ~ equivalente con GradScaler). Lección de método: el "muro" de 1 step/s era error propio, no límite del hardware (regla 10×). Headroom restante: aún con compile ~13% del pico fp16 -> las matrices chicas son el límite; subir d/batch o fusionar la atención lineal daría más.
- Próximo: relanzar G2 a escala con el fix (mismo T4), cerrar el veredicto recall (rama A/B), commitear; luego caracterizar la curva params↔velocidad (baseline medido) y atacar el desacople (cuant/MoE/distil/RAG).

## [2026-06-29] HALLAZGO: AMP fp16 producía NaN en G2 -> atención fp16-segura (calidad↔velocidad cazada)
- El sweep G2 a escala con AMP fp16 reveló `loss nan` (config ratio_ae4, step 1664). Causa raíz: la LinearAttention NO está normalizada (q@k^T con features elu+1, SIN 1/sqrt(d)) -> bajo fp16 los scores y el denom OVERFLOWean (>65504) -> inf -> NaN. Esto INVALIDÓ el veredicto del run (los configs lineal-dominantes ya venían pegados a ~0.10) y REFUTÓ mi afirmación previa "AMP es neutral en calidad" (era ASUMIDA; el profile midió throughput, no calidad). Exactamente lo que la regla calidad↔velocidad MATCHED busca cazar.
- FIX fp16-SEGURO en m0_g2_recall_colab.py: el núcleo de LinearAttention y SlidingWindowAttention se computa en fp32 (with torch.autocast(enabled=False) + .float()), las proyecciones qkv/o quedan en fp16 (tensor cores = casi toda la FLOPs). Sin NaN, calidad intacta; trade-off: algo menos de 1.9× (core fp32 sin tensor cores). Validado local --smoke (G2 + m0_g2_confirm).
- Escrito m0_g2_confirm.py: verificación dirigida de las configs críticas (atención-pura ae1 y mitad ae2) con MÁS pasos, fp16-safe vs fp32 y SIN plateau early-stop (patience inf, para no matar late-learners) -> separa 3 causas de un 'no cruza': (a) techo arquitectónico, (b) undertraining, (c) AMP degradó. Escalación si el sweep queda ambiguo.
- Matado el run contaminado (pkill, GPU liberada 0MiB/0%), re-subido el script corregido, RELANZADO el sweep G2 fp16-seguro en T4 (limpiando sentinela/log/json viejos). Doc M0_G2_PROFILE_RESULTADO.md actualizada con la CORRECCIÓN honesta. Pendiente: leer el veredicto del sweep corregido; si nada cruza, correr m0_g2_confirm. NOTA: el mismo bug fp16 vive en el modelo canónico cognia_x/model/hybrid.py -> portar el fix fp16-seguro allá como parte del harness de entreno.

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

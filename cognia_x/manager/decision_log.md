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
- **Refuerzo (exp007, medido):** int8 naïve en numpy = 8-10× más LENTO que float32; el ahorro de
  baja precisión es de memoria (4×), no de cómputo automático → la velocidad exige kernels
  especializados (T-MAC/bitnet.cpp), no basta con cuantizar. Justifica "Q4 base, ternario solo I+D".

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

## D-013 (2026-06-17) — Implementación v0: PyTorch CPU + byte-level (asumido autónomamente)
- **Decisión:** construir el modelo v0 en **PyTorch (CPU)** con entrada **byte-level** (vocab 256).
- **Razón:** (a) *fácil de entrenar* → autograd de PyTorch; la regla "numpy puro" del vault aplica a
  los NODOS de despliegue de Cognia, no a este laboratorio (Cognia-X es independiente). (b)
  byte-level elimina el tokenizador (más fácil + robusto) para un primer modelo; el "vocab moderado
  BPE" (D-008) es un upgrade de eficiencia de inferencia posterior.
- **Reversible:** sí. La arquitectura híbrida (D-007) es la misma; portar a numpy para nodos o
  cambiar el front-end de representación es trabajo futuro.

## D-CEIL-1 (2026-06-19, CYCLE 22) — Mantener el híbrido (mayoría lineal + minoría atención)
- **Decisión:** mantener el **híbrido** (mayoría lineal barata + minoría de atención para recall
  exacto) como arquitectura del lab; la atención es **necesaria** para recall a carga alta.
- **Razón:** la frontera recall↔throughput (Arora 2024, arXiv:2402.18668) + exp002 (recall ~ d²) +
  exp009 (lineal satura ~0.18, el híbrido separa a d=48: 0.292 vs 0.181) justifican mezclar: lo lineal
  da coste O(L); las pocas capas de atención compran el recall que el estado fijo no escala. Coincide
  con **Based** — el lab llegó al mismo principio de forma independiente.
- **Evidencia:** arXiv:2402.18668 (tier-1) + exp002 + exp009 (tier-5, datos propios). ACEPTADA por el
  `EvidenceLedger` (funda con tier-1 + tier-5 obtenidas; no lanza `OpinionOnlyError`).
- **Matiz honesto:** exp009 muestra que la cota EFECTIVA del lineal entrenado es la capacidad del
  feature-map (<< d²), no el d² teórico — refuerza la decisión (el lineal solo, aún a d grande, no
  alcanza el recall que la atención da). Registrada vía `cognia_x/research/cycles/cycle22_recall_ceiling.py`.
- **Reversible:** sí; se revisa si un feature-map mejor (mimetic init, arXiv:2410.11135) cerrara la
  brecha entrenada y el estado fijo solo bastara para el recall a carga alta.

## D-CEIL-2 (2026-06-19, CYCLE 23) — Descartar "ensanchar el feature-map ELU+1" (mejora descartada)
- **Decisión:** **descartar** ensanchar el feature-map ELU+1 como vía para subir el recall del
  mezclador lineal; **redirigir** el esfuerzo a **kernel Taylor + mimetic init** (H-CEIL-3).
- **Razón:** exp010 (d=24 fijo, step-parity 6000 steps): ×4 ancho = **16× más estado (576→9216)** NO
  movió el recall (**mult1=0.181 → mult4=0.181, Δ+0.000**, nulo). El cuello **no es ancho
  ni tamaño de estado**, sino la **forma del kernel** y la **optimización/init** (Based usa Taylor,
  arXiv:2402.18668; Trockman usa mimetic init, arXiv:2410.11135).
- **Evidencia:** exp010 (tier-5, dato propio obtenido) + arXiv:2402.18668 (tier-1). ACEPTADA por el
  `EvidenceLedger` (funda con tier-5 + tier-1 obtenidas; no lanza `OpinionOnlyError`). Registrada vía
  `cognia_x/research/cycles/cycle23_feature_dim.py`.
- **Tipo:** es una **mejora DESCARTADA** registrada explícitamente (la directiva pide documentar lo que
  NO se persigue y por qué, no solo lo que sí). Continúa/afina D-CEIL-1 (el lineal solo no basta para
  el recall a carga alta; ahora sabemos que tampoco lo arregla el ancho).
- **Reversible:** sí; se reabre si un kernel mejor (Taylor) o init mimética levantara el plateau y el
  estado fijo solo bastara para el recall — exactamente lo que mide H-CEIL-3.

## D-CEIL-3 (2026-06-19, CYCLE 24) — Descartar "forma del kernel (Taylor) + mimetic init" (mejora descartada)
- **Decisión:** **descartar** la forma del kernel (feature-map Taylor 2do orden) y la mimetic init como
  vías para subir el recall del mezclador lineal a d=24; junto con el ancho (D-CEIL-2), redirigir a
  profundidad/escala/optimizador o a la atención del híbrido (H-CEIL-4).
- **Razón:** exp011 (d=24, n_heads=1, n_pairs=16, seed0, steps=3000 step-parity, control de TAMAÑO con
  elu_matched a la dim de Taylor): baseline ELU+1=0.173; **taylor=0.160 (Δ−0.013, POR DEBAJO)**;
  elu_matched(dim 336)=0.181 (+0.008 ruido); **mimetic=0.183 (+0.0098, < umbral 0.02)**. taylor_vs_matched
  =−0.021. Ni la forma ni la init cruzan el ruido; el Taylor queda por debajo de su ELU size-matched
  (el control aísla forma de tamaño). [[arXiv:2402.18668]] (Based) + [[arXiv:2410.11135]] (Trockman)
  predecían que ayudaría → refutado a esta escala.
- **Evidencia:** exp011 (tier-5 propio) + arXiv:2402.18668 (tier-1). ACEPTADA por el ledger. Registrada
  vía `cognia_x/research/cycles/cycle24_kernel_init.py` (deriva el veredicto de results.json).
- **Tipo:** mejora DESCARTADA registrada explícitamente. Continúa D-CEIL-2 (ahora sabemos que tampoco lo
  arregla la forma del kernel ni la init, no solo el ancho). **Reversible:** sí (a otra escala/seed).

## D-CEIL-4 (2026-06-19, CYCLE 25) — Cerrar la línea de tuning del mezclador lineal; el remedio es la atención
- **Decisión:** **cerrar** la línea de afinar el mezclador lineal de estado fijo para subir su recall: el
  techo ~0.18 es **ESTRUCTURAL**. El recall a carga alta se obtiene con la **ATENCIÓN del híbrido**
  (D-CEIL-1/D-007), NO con tuning del mezclador lineal.
- **Razón:** exp012 (lineal PURO, n_pairs=16, seed0, steps=3000): ni profundidad (L8=0.181, +0.0075), ni
  escala-d (d48=0.183, +0.0093), ni optimizador (LR 3×=0.176, +0.0025) suben el lineal puro sobre ~0.18.
  Junto con exp010 (ancho) y exp011 (forma+init), el plateau es robusto a **SEIS levers no-atención**. La
  atención SÍ recupera (CYCLE 6: 0.255→0.998 a np alto; exp009: el híbrido separa a d=48). El techo pasa
  a `real`/estructural (pigeonhole sobre el estado fijo). [[arXiv:2508.19029]] (Okpekpe&Orvieto) predecía
  que el tuning lo arreglaría → refutado a esta escala.
- **Evidencia:** exp012 (tier-5) + arXiv:2508.19029 (tier-1). ACEPTADA por el ledger. Registrada vía
  `cognia_x/research/cycles/cycle25_depth_scale.py`. La línea H-CEIL (recall del estado fijo) CONVERGE.
- **Reversible:** sí; se reabriría si a MAYOR escala (d≫48, modelos grandes) el lineal puro cruzara el
  plateau sin atención — pero a la escala del lab el remedio es arquitectónico. **Confirmación pendiente:**
  exp013 (lineal+≥2 atención a d=24) como control positivo end-to-end a esta misma escala.

## D-CEIL-5 (2026-06-20, CYCLE 26) — Control positivo: la atención cruza el plateau (remedio confirmado)
- **Decisión:** CONFIRMAR end-to-end, a la MISMA escala de la línea H-CEIL, que el remedio del recall a
  carga alta es **ARQUITECTÓNICO**: la atención pura cruza el plateau ~0.18 que NINGÚN tuning del lineal
  mueve. Cierra la línea de recall (D-CEIL-1/D-CEIL-4 confirmados directamente).
- **Razón:** exp013 (d=24, n_pairs=16, seed0, steps=3000 step-parity): **atencion_h4 (pura) = 0.882** vs
  baseline lineal 0.173 (6 levers refutados en exp010/011/012). Cruce masivo (0.18→0.88), no ruido.
- **Caveat honesto (H-HYB-1):** el híbrido 50/50 (hibrido_h1=0.181, hibrido_h4=0.180) quedó UNDER-TRAINED
  a step-parity — trayectoria ASCENDIENTE al cortar el budget (hibrido_h4 subía 0.15→0.19), NO plateau.
  El híbrido CAN (CYCLE 6: 0.99) pero optimiza más lento a d chico. Diagnóstico antes que hallazgo: no es
  falla estructural del híbrido, es budget. → H-HYB-1 (abierta).
- **Evidencia:** exp013 (tier-5) + arXiv:2402.18668 (tier-1). ACEPTADA por el ledger. Registrada vía
  `cognia_x/research/cycles/cycle26_hybrid_control.py`. El techo del estado fijo queda `real`/estructural
  con control positivo DIRECTO.
- **Reversible:** N/A (es una confirmación, no una apuesta). La línea de recall del estado fijo se cierra.

## D-HYB-1 (2026-06-20, CYCLE 27) — Caveat a D-007: el híbrido NO recupera recall automáticamente a d chico
- **Decisión:** añadir un **caveat** a D-007 (backbone híbrido): el híbrido NO recupera recall de forma
  automática. A d chico (24) las capas LINEALES bottleneckean y el híbrido platea como el lineal puro
  (~0.18, exp014), mientras la atención pura cruza (0.95). El híbrido necesita **d suficiente** (funcionó
  a d=64, CYCLE 6) y/o el arreglo/ratio adecuado (H-HYB-2). La atención pura sigue siendo el remedio claro.
- **Razón:** exp014 (d=24, n_heads=4, n_pairs=16, seed0, steps=10000 = 3.3× exp013): hibrido_h4 platea en
  0.186 (0.180@4000→0.186@7500, PLANO) vs atencion_h4=0.948. NO es budget (plateó por el paso 4000).
  **Corrige el diagnóstico de under-training de CYCLE 26** (autocorrección por más evidencia). ACOTA H-MEZ-4
  (que recuperaba a d=64): la recuperación del híbrido es d-dependiente.
- **Evidencia:** exp014 (tier-5) + CYCLE6/H-MEZ-4 (tier-5). ACEPTADA por el ledger. Registrada vía
  `cognia_x/research/cycles/cycle27_hybrid_budget.py`. Genera H-HYB-2 (¿d / arreglo / ratio?).
- **Reversible:** N/A (es un caveat empírico). NO refuta D-007 (el híbrido a d adecuado sí recupera, CYCLE 6);
  lo acota: el híbrido a d chico no es free lunch para recall.

## D-HYB-2 (2026-06-20, CYCLE 28) — Caveat FUERTE a D-007 + PAUSAR la sub-línea del híbrido
- **Decisión:** reforzar el caveat a D-007: el híbrido naive (interleaved lineal-primero) **NO recupera
  recall robustamente** — no lo arregla subir d (exp015: d24=0.189, d48=0.253, d64=0.190, np=16; no
  monótono). Depende del ARREGLO (lineal-primero) y la CARGA (np); funcionó solo a d=64/np=8 (CYCLE 6). La
  **atención pura** es el remedio robusto (0.95). **PAUSAR** la sub-línea del híbrido (H-HYB-3) por
  rendimientos decrecientes; retomar con orientación del dueño o pivotar a F-LEARN-2 (prioridad #2).
- **Razón:** exp015 refuta H-HYB-2 (no es d). La sub-línea H-HYB-1→2→3 refuta y genera sobre una pregunta
  cada vez más estrecha (recuperación exacta de un híbrido de 4 capas a d/np tiny); la conclusión central
  de la línea de recall (lineal=estructural, atención=remedio robusto) ya es sólida y multi-verificada.
- **Evidencia:** exp015 (tier-5) + CYCLE6/H-MEZ-4 (tier-5). ACEPTADA por el ledger. Registrada vía
  `cognia_x/research/cycles/cycle28_hybrid_dscale.py`. Genera H-HYB-3 (arreglo/carga, pausada).
- **Reversible:** N/A. NO refuta D-007 (el híbrido a d=64/np=8 sí recuperó, CYCLE 6); lo acota fuerte: el
  híbrido naive es FRÁGIL a arreglo/carga para recall — un hallazgo arquitectónico real para Cognia-X.

## D-LEARN-1 (2026-06-20, CYCLE 29) — Adoptar verify-before-learn como MOTOR de auto-mejora (no solo guarda)
- **Decisión:** en tareas VERIFICABLES, adoptar verify-before-learn como **motor de AUTO-MEJORA** de
  Cognia-X (no solo como guarda anti-colapso, CYCLE 11): el modelo aprende de su propia salida
  VERIFICADO-CORRECTA y mejora (bootstrapping tipo STaR). La señal de corrección del oráculo es la palanca.
- **Razón:** exp016 (suma byte-level, modelo tiny d=64, test held-out DISJUNTO, **n=4 seeds**): verified
  es el **ÚNICO** brazo con ganancia neta sobre su base en los 4 seeds (net +0.110); los controles NO
  (random_matched −0.015, naive_all −0.007). gap verified−random_matched positivo en los 4 seeds (media
  +0.126, **t-pareado=3.22, p<0.05 df=3**, win-count 15/16). El control decisivo (random_matched: mismo
  N_keep+pasos, subconjunto ALEATORIO) aísla que el motor es la CORRECCIÓN, no el volumen ni el filtrado-per-se.
- **Evidencia:** exp016 (tier-5) + [[arXiv:2203.14465]] STaR (tier-1) + [[arXiv:2305.17493]] model-collapse
  (tier-1). ACEPTADA por el ledger. Verificada por workflow adversarial (4 lentes, todas holds=true).
- **Caveats (honestos):** efecto MODESTO (+0.11) a escala tiny (suma, d=64); métrica = media-sobre-rondas
  (el final-round es ruidoso, M=120); NO es 'colapso' de naive (su acc ~ base; la caída de diversidad es
  ruido de muestreo). Avanza CYCLE 11 (prevención→habilitación). **Reversible:** sí (a otra escala/tarea).

## D-LEARN-2 (2026-06-20, CYCLE 30) — La CALIDAD del verificador es un lever de primera clase (presupuesto ε*)
- **Decisión:** la auto-mejora verificada tolera ruido del verificador SOLO hasta un umbral; al elegir
  verificadores reales para Cognia-X, exigir **FP-rate < ε\*** (o compensar con más N/diversidad). El
  verificador no es binario "existe/no existe": su CALIDAD gobierna la auto-mejora.
- **Razón:** exp017 (dosis-respuesta, volumen+pasos FIJOS → sólo varía la contaminación): net-sobre-base de
  verified decae monótono con el FP-rate ε = {0:+0.116, 0.15:+0.074, 0.3:+0.056, 0.5:+0.001, 1:−0.001};
  caída ε0→ε1=0.117 > 2σ; **ε\*=0.15** (sobrevive con net>0 consistente). Robusto a la métrica (final-round
  y media-rondas coinciden); ε=0 reproduce exp016. Confirma causalmente que el verificador (su corrección)
  es el motor de H-LEARN-1.
- **Evidencia:** exp017 (tier-5) + [[arXiv:2203.14465]] STaR (tier-1). ACEPTADA por el ledger. Verificación
  inline (confound de volumen controlado, robustez a métrica). Registrada vía cycle30_noisy_verifier.py.
- **Reversible:** sí; ε\* es específico de la tarea/escala tiny — recalibrar para tareas/verificadores reales.

## D-LEARN-3 (2026-06-20, CYCLE 31) — Adoptar verificadores chequeables REALES (sandbox de ejecución)
- **Decisión:** la auto-mejora verificada puede usar verificadores chequeables REALES (que EJECUTAN la
  salida del modelo en un sandbox), no solo oráculos de forma cerrada. Generaliza a un verificador real.
  (Junto con D-LEARN-2: exigir verificadores FUERTES con FP-rate < ε*.)
- **Razón:** exp018 (síntesis de expresiones, sandbox ejecutor con intérprete propio sin eval(); test
  held-out DISJUNTO M=90, n=3): verified sube real_acc +0.230 sobre base (0.437) en los 3 seeds (strong
  0.667, weak 0.672) y supera a naive_all (0.358, que CAE = colapso sin filtro) por >2σ. Robusto a la
  métrica. El verificador real ES el motor.
- **Sub-claim reward-hack NO observado:** un verificador real DÉBIL es gameable en principio (Amodei 2016)
  pero el loop no-RL no descubrió el echo (verified_weak ~ strong, degenerate=0). Honesto: no forzar.
- **Evidencia:** exp018 (tier-5) + [[arXiv:2203.14465]] STaR + [[arXiv:1606.06565]] reward-hacking (tier-1).
  ACEPTADA por el ledger. Registrada vía cycle31_real_verifier.py. **Reversible:** sí (escala tiny).

## D-LEARN-4 (2026-06-20, CYCLE 32) — La auto-mejora STaR (imitación) es robusta al reward-hack; preferir verificador fuerte igual
- **Decisión:** la auto-mejora STaR de Cognia-X (imitación de lo verificado-aceptado) es ROBUSTA al
  reward-hack del verificador débil a esta escala (no caza el atajo como RL). AUN ASÍ, preferir verificadores
  FUERTES: dan MÁS competencia real (señal más pura) y cierran el atajo. El riesgo de reward-hack es
  RL-específico → tenerlo en cuenta SI se pasa a RL/maximización (no a imitación).
- **Razón:** exp019 (atajo echo SEMBRADO, p_echo=0.35, temp=1.1, n=3): weak degenerate(final)=0.085 ≈ strong
  0.004 (NO domina el echo, fluctúa sin snowball) → no hack. PERO strong real_acc=0.745 vs weak 0.474 (+0.27).
  Imitación COPIA salidas aceptadas (mayormente honestas), no MAXIMIZA aceptación (RL) → no busca el atajo.
- **Evidencia:** exp019 (tier-5) + [[arXiv:2203.14465]] STaR/imitación + [[arXiv:1606.06565]] reward-hacking.
  ACEPTADA por el ledger. Verificación inline (degenerate del weak no snowballea). Registrada vía cycle32_reward_hack.py.
- **Reversible:** sí; específico de escala tiny + loop no-RL. Refina Amodei 2016 (reward-hack = patología de RL).

## D-LEARN-5 (2026-06-20, CYCLE 33) — La imitación STaR es la opción SEGURA; el RL exige salvaguardas (no demostrado in-lab)
- **Decisión:** preferir IMITACIÓN STaR para la auto-mejora de Cognia-X (robusta al reward-hack, H-LEARN-4);
  si alguna vez se usa RL-maximización, exigir verificador FUERTE + salvaguardas (KL-reg, on-policy, budget
  controlado). El contrapunto RL (que RL SÍ se hackearía con verificador débil) NO se pudo demostrar in-lab a
  escala tiny → future work, no adoptar RL sin esa demostración/salvaguarda.
- **Razón:** exp020 (mismo verificador débil + atajo que exp019; sólo cambia el algoritmo): GRPO-lite no
  demostró el hack (rl_weak degenerate 0.059 < imit 0.115). CONFOUND: el GRPO estable apenas-entrena (para no
  colapsar) → no hay ventana limpia a igual presión que la imitación. Es un null de MÉTODO, no del mecanismo
  (la literatura/Amodei lo apoya; rl_strong degenerate=0.000 = el fuerte suprime el echo incluso bajo RL).
- **Evidencia:** exp020 (tier-5) + [[arXiv:2203.14465]] STaR + [[arXiv:1606.06565]] reward-hacking. ACEPTADA
  por el ledger. Registrada vía cycle33_rl_vs_imitation.py. **Reversible:** sí (RL estabilizado / mayor escala).

## D-V4-1 (2026-06-24, CYCLE 35) — RESET v4: R-VALOR como North Star; ACTUAR/INTERVENIR como primer motor
- **Decisión:** el reset v4 adopta **R-VALOR** (función de valor endógena: qué información importa, generada
  por el propio sistema) como North Star del laboratorio, y como PRIMER motor verificado adopta
  **ACTUAR/INTERVENIR** (R-INTERVENCIÓN). La tesis previa (bytes-por-token / híbrido) se conserva como
  restricción de **VIABILIDAD** (todo corre en CPU finita), NO como dirección a la raíz. Próximo: H-V4-1b
  (aislar el VALOR info-gain del azar-activo) y H-V4-2 (identificabilidad sin cuerpo).
- **Razón:** el árbol de descomposición raíz (`decomposition_tree.md`, 6 lentes + auditoría adversarial)
  converge en R-VALOR (5/6 lentes). exp022 (CYCLE 35): bajo intervención el pasivo queda PLANO por más
  presupuesto (flatness 0.013; muro informacional), las políticas activas → 1.0 (B−A=+0.31), gap invisible
  i.i.d. → R-INTERVENCIÓN demostrada (techo 'real'). R-VALOR específico aún 'asumido' (el azar-activo basta;
  B−C=−0.007) → backlog.
- **Evidencia:** exp022 (tier-5) + exp017 (tier-5, el lab solo había demostrado valor EXTERNO). ACEPTADA por
  el ledger. Registrada vía cycle35_endogenous_value.py. **Reversible:** sí; v1/v2/v3 conservadas
  (append-only); si H-V4-1b/H-V4-2 refutaran R-VALOR/R-INTERVENCIÓN, se reabre el rumbo.

## D-V4-2 (2026-06-24, CYCLE 36) — Pivote: explotar R-INTERVENCIÓN (act-and-verify); info-gain descartado
- **Decisión:** dejar de buscar un VALOR de exploración astuto (info-gain quedó descartado como lever, exp023)
  y EXPLOTAR R-INTERVENCIÓN como motor de inteligencia BARATO: act-and-verify (el agente ACTÚA y aprende de la
  CONSECUENCIA), que el lab ya apoya (exp016-018, H-LEARN-1) y la literatura confirma (TTS verifier-based ≫
  verifier-free, arXiv:2408.03314). R-VALOR queda abierto sólo en su forma FUERTE (valor AUTO-generado =
  empowerment, no info-gain) → H-V4-1c. Próximo integrador: lazo act-and-verify sobre el sustrato de lenguaje.
- **Razón:** exp023 (régimen duro D=40/clúster=8/ruido0.25, 24 seeds): info-gain NO supera de forma robusta al
  azar-activo (margen medio +0.004); lo robusto es ACTUAR≫observar (C-A hasta +0.36, A plano). Corroborado por
  la literatura (CAASL ~5-6% a d=10; active gana sólo en grafo grande/denso/ruido-bajo). Barato: 360 modelos
  causales en 1.0s CPU.
- **Evidencia:** exp023 (tier-5) + exp022 (tier-5) + [[arXiv:2408.03314]] TTS + [[arXiv:2606.20104]]
  action-grounded. ACEPTADA por el ledger. Registrada vía cycle36_value_isolation.py. **Reversible:** sí; si el
  régimen grande/denso/ruido-bajo mostrara que el valor SÍ gana (Choo&Shiragur O(log n)), se reabre.

## D-V4-3 (2026-06-24, CYCLE 38) — R-VALOR confirmado REAL: el valor endógeno es la CONTROLABILIDAD
- **Decisión:** R-VALOR queda CONFIRMADO real en su forma fuerte: el valor endógeno de un agente es la
  CONTROLABILIDAD (empowerment), NO el info-gain (descartado, exp023) ni la predicción pasiva. Se UNIFICA con
  R-INTERVENCIÓN (el valor que sobrevive es sobre la acción). Rumbo v4 CONSOLIDADO: construir un lazo
  ACT-AND-VERIFY barato cuyo valor endógeno sea la controlabilidad/consecuencia, sobre un sustrato chico CPU
  (híbrido/RWKV en llama.cpp), guiado por verificador barato (TTS, convergente con la literatura). Próximo:
  H-V4-1d (empowerment MEJORA una tarea downstream) y el integrador hacia lenguaje.
- **Razón:** exp024 (12 seeds): inversión limpia — EMPOWERMENT ctrl 1.71 bits vs reloj 0.0; PREDICCIÓN pasiva
  reloj 1.71 vs ctrl 0.0. El empowerment aísla lo controlable, la predicción pasiva lo PIERDE
  (controlabilidad≠predictibilidad). A diferencia del info-gain (exp023, ≈azar), el empowerment SÍ se
  distingue de lo trivial. Barato: 0.57s CPU.
- **Evidencia:** exp024 (tier-5) + [[arXiv:2606.20104]] action-grounded + [[arXiv:2510.05996]] empowerment-BA.
  ACEPTADA por el ledger. Registrada vía cycle38_empowerment.py. **Reversible:** sí; el mecanismo está
  demostrado pero la utilidad downstream/lenguaje (H-V4-1d) sigue 'asumida' — si no mejora una tarea real, se
  revisa el peso de R-VALOR frente a R-INTERVENCIÓN sola.

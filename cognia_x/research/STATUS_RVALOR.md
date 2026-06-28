# STATUS_RVALOR.md — Estado honesto del arco R-VALOR (CYCLEs 79-154)

> Síntesis-capstone (CYCLE 147, 2026-06-27). Anclada en los veredictos REALES commiteados (no en intuición).
> Escrita tras 6 MIXTA seguidos (141-146) que evidencian SATURACIÓN del toy. Append-only; no reemplaza al ledger
> (`research/store/`), lo RESUME para que el próximo ciclo no re-derive lo ya establecido.
> Método transversal: verificación adversarial (2-4 agentes con probes reales) ANTES del ledger — 16 ciclos seguidos
> (131-146) corrigiendo overclaims. Un MIXTA/REFUTADA que afila el siguiente es ÉXITO (directiva v4).

## North Star
¿Un sistema CONSTRUYE una función de valor ENDÓGENA = controlabilidad × relevancia (el "keystone"), y cuándo/cómo paga?
Todo en CPU, acumulativo, reproducible, honesto.

---

## 1. PROBADO (robusto; sobrevivió verificación adversarial)

- **El keystone como LÍMITE normativo (138).** El producto valor = ctrl × rel es el límite binary+uniforme del término
  pragmático de la energía libre esperada (EFE). Grounding derivacional legítimo (la directiva acertó). ACOTADO: la
  "emergencia empírica" en ese ciclo era tautológica (efe_pragmatic = la métrica del eval).
- **La forma ROBUSTA bajo estimación es la EFE-COMPLETA w²·v·ctrl (144), no la simplificada.** Incluir la varianza-prior v
  importa bajo heterogeneidad; el cuadrado de w es REGIME-DEPENDENT (daña con ŵ ruidoso — confirma 138 —, ayuda a baja
  heterogeneidad). v es estimable como Var(x) PERO contaminada por el control.
- **La ventaja del valor sobre un factor-solo NO es un artefacto de la selección DISCRETA top-K (145).** Bajo capacidad
  CONTINUA (water-filling) la ventaja sobrevive a presupuesto escaso y escala con la disociación ctrl-rel (robusto en
  g/D/RHO/seeds). El "artefacto K=1" recurrente es CONCENTRACIÓN-bajo-escasez, no patología del top-K.
- **La factorización producto es un sesgo inductivo útil de BAJA CAPACIDAD para ESTIMAR el valor bajo escasez (146).**
  Bias-variance estándar: bate a un flexible (sobreajusta) y a separables (sin producto); minimalidad load-bearing;
  comparación justa en λ. PERO es el resultado "no free lunch" (útil sólo si matchea).
- **La calibración del selector paga en la DECISIÓN bajo ESCASEZ (123).** No por boostear el descenso del loss, sino por
  las decisiones de asignación/abstención que USAN la señal.
- **El R-VALOR es una BRÚJULA DECISIONAL, no un acelerador de loss (re-localización, 120-123).** Vale por las decisiones
  que usan la señal, no por boostear el self-training (que es ANCLA-bound, 120-121).
- **[NUEVO 149 — PRIMER APOYADA limpio, en el LAZO REAL] La cura 119 (unlikelihood) produce una señal de valor ENDÓGENA
  más calibrada sobre la correctness REAL en un sistema con self-training.** En el lazo torch real (HybridLM → verificador
  real → confianza endógena → self-train), la confianza del brazo durable rankea la correctness real mejor que el naive:
  ventaja AUROC base-rate-INVARIANTE, gap +0.047 a N=16 (CI bootstrap [+0.027,+0.069] excluye 0, t=4.22), REPLICA
  out-of-sample (6/6 seeds frescos → N=22 t=5.87). Verificación adversarial CONFIRMATORIA (5 métodos de CI, jackknife,
  mecanismo persistente, base-rate-invariante). Resuelve el limbo 'underpowered/diluyendo' de 140-141 (era N chico; el lazo
  es rápido). ACOTADO: magnitud modesta (+0.05) y régimen-dependiente (concentrado donde el base-acc tiene margen; se apaga
  en base-acc alta, corr -0.32). Cierra el hueco #1 de la auditoría (salir del oráculo). FRONTERA ¿la cura es PRIVILEGIADA
  vs un regularizador genérico? → RESUELTA por 150: NO privilegiada. ⚠️ ATRIBUCIÓN REFUTADA por 151: el AUROC_own que sostenía este
  "APOYADA limpio" estaba CONFUNDIDO con la riqueza de generación; en un pool fijo balanceado el durable se INVIERTE (−0.210) → la
  ventaja del 149 era generación, NO calibración endógena. La observación (durable>naive OWN) se reproduce; su interpretación cae.
  Re-clasificar: el 149 NO es ya un "APOYADA limpio" sino "efecto-real-pero-mal-atribuido".
- **[NUEVO 150 — la cura 119 NO es PRIVILEGIADA; RE-LOCALIZA el 149] En el lazo torch real, un regularizador de calibración
  GENÉRICO (label smoothing, label-agnostic) IGUALA/SUPERA la ventaja AUROC del durable (cura 119, label-aware).** exp132 (N=8, mismo
  harness, 5 brazos que difieren SÓLO en el regularizador del self-train; temperature descartada a priori -AUROC-invariante por
  monotonía-): privilege_gap = AUROC(durable) − AUROC(mejor genérico) = −0.040 (CI bootstrap 95% [−0.070, −0.012] EXCLUYE el cero del
  lado NEGATIVO -el genérico gana-, t=−2.48). Verificación adversarial de 4 sondas CONFIRMATORIA: (a) SANITY durable_vs_naive +0.060
  (7/8) reproduce el 149 → harness válido; (b) sobrevive el control de DEGENERACIÓN (gated −0.040 ~ raw; endurecer el gate lo
  FORTALECE; la firma de degeneración está en el DURABLE -corr ncorrect-AUROC −0.58-, no en los genéricos -ls_lo +0.57-); (c) sin
  winner's curse (durable pierde vs ls_lo SOLO −0.039, CI ENTERAMENTE negativo). DOS CAPAS HONESTAS (afinado de la verificación —
  sonda-mecanismo ACOTA): (a) LO QUE QUEDA LIMPIO: la cura NO es la pieza privilegiada — específicamente el LABEL SMOOTHING (target-
  smoothing) la iguala en AUROC y la SUPERA en capacidad (real_acc 0.654 vs durable 0.129; el entropy-penalty sólo EMPATA). (b) LO
  QUE NO SE ESTABLECE: que el mecanismo sea 'calibración' — el AUROC está CONFUNDIDO con la riqueza de generación (corr pooled −0.54;
  durable y ls_lo en regímenes de ncorrect casi DISJUNTOS, IGUALES en la banda de solape) → el payoff AUROC del lazo real (149
  incluido) está entangled con la supresión/riqueza de generación, lo que CUALIFICA RETROACTIVAMENTE el +0.047 del 149 (sigue en pie
  como FENÓMENO —durable>naive se reproduce, sanity +0.060— pero su atribución a 'calibración pura' se debilita). ACOTACIÓN regime-
  dependiente (paralela al 149): la refutación se concentra en base-acc ALTA (corr base_acc×priv_gap −0.72); en base-acc BAJA el
  durable EMPATA (ahí 'sostiene' AUROC pero pagando el colapso de generación, corr −0.96); en AMBOS regímenes genérico≥cura. N=8,
  settings reducidos (rounds=5, steps=70, por debajo de la config powered anunciada); AUROC del genérico cerca del techo (0.998).
  FRONTERA: régimen base-acc alta; transferencia; SCALE. → DESCONFUNDIDO por 151 (abajo): el AUROC_own del 149/150 estaba
  CONFUNDIDO con la riqueza de generación; el durable se INVIERTE en un pool fijo balanceado.
- **[NUEVO 151 — DESCONFOUND, MIXTA: el payoff de calibración del lazo real es MAYORMENTE riqueza de generación; la atribución del
  149 queda REFUTADA] El AUROC_own del 149/150 confundía 'calibración' con riqueza de generación (cada brazo rankea SU pool, de
  dificultad endógena).** exp133 (N=6, mismo harness, 3 brazos rankean además un POOL FIJO COMPARTIDO Y BALANCEADO 48/48 —candidatos
  CONSTRUIDOS + etiquetados por el verificador real—): el AUROC_fixed desconfunde. (a) La CURA 119 (durable) se INVIERTE: durable−naive
  OWN +0.057 → FIXED **−0.210** (CI [−0.245,−0.175], t=−10.6, 6/6 seeds NEG; AUROC_fixed durable 0.760 vs naive 0.970) → su ventaja
  del 149 era ENTERAMENTE riqueza de generación (genera 11.8 correctas vs naive 95.9 → su pool propio es magro/fácil → AUROC_own
  inflada). El colapso entrenado es aún más profundo (trained-only ~0.62, última ronda ~0.57 ≈ azar). → la atribución 'calibración
  endógena' del durable-149 queda **REFUTADA** por el desconfound (la OBSERVACIÓN durable>naive OWN se reproduce; la INTERPRETACIÓN
  no). (b) El ÚNICO residuo que sobrevive es el GENÉRICO ls_lo y SÓLO EN SIGNO: ls_lo−naive FIXED +0.018 (6/6 gaps positivos, sign-
  test p=0.016) PERO t-test pareado t=1.98 < t_crit(df=5)=2.015 (SUB-significativo); 'CI bootstrap excluye 0' es TAUTOLÓGICO con gaps
  un-signo; la media se partió a la mitad N=3→N=6; cargado en 2/6 seeds; régimen-dependiente (cae a +0.003 donde naive_fixed roza el
  techo). Verificación adversarial de 4 sondas (1 CONFIRMA inversión + 3 ACOTAN; recomendó MIXTA, "NO usar APOYADA"; cazó 5 errores
  factuales/framing — el docstring decía "generados desde el base" siendo CONSTRUIDOS, y la compuerta "CI excluye 0" tautológica
  reemplazada por t-test). ACOTACIÓN: N=6 escala SMOKE; AUROC_fixed es un sondeo IN-DISTRIBUTION casi-en-techo (misma forma canónica
  con que cada brazo se re-entrena vía replay) → desconfunde la riqueza-de-pool (válido) pero NO certifica ranking held-out. NET: el
  payoff del lazo real NO es ENTERAMENTE artefacto (queda señal de signo genérica) pero lo no-artefacto es genérico, mínimo y no
  robusto; el componente que MOTIVÓ el arco (la cura 119 del 149) SÍ era artefacto. CIERRA el caveat load-bearing del 150. FRONTERA:
  ¿el residuo genérico PAGA downstream bajo escasez?; N≥8 con t-test; régimen base-acc alta; transferencia; SCALE.
- **[NUEVO 152 — pago DOWNSTREAM, MIXTA-ACOTADA: el residuo NO paga robustamente, PERO el test SATURA y NO instancia la escasez real;
  + hallazgo robusto: el durable se INVIERTE también downstream]** exp134 (N=6, mismo lazo real, 2 pools fijos balanceados 48/48:
  INDIST -forma canónica- y HELDOUT -forma novel '2+(n-2)' no entrenada, ataca la acotación in-distribution de la sonda-A del 151-;
  precision@top-m). Intento de medir si el residuo genérico (ls_lo) del 151 PAGA en una decisión bajo escasez (tesis brújula-decisional
  123). RESULTADO MIXTA-ACOTADA: (a) el residuo NO paga ROBUSTAMENTE (falla CI+t-test+6/6); (b) PERO **defecto de DISEÑO cazado por la
  verificación (sonda-A, sev ALTA)**: el pool balanceado 50/50 -necesario para el desconfound- SATURA precision@top-m (INDIST naive ya
  en techo 1.0 → gap CERO ESTRUCTURAL, no-informativo) y NO es escaso (por la lección de exp124, f=m/#correct<=0.5, nunca f≈1 → la
  tesis 123 de q-bajo **NUNCA se testeó**); (c) el único pool informativo (HELDOUT, con headroom) da señal DÉBIL BORDERLINE no-robusta
  (m=6, +0.028, t=2.0 < t_crit 2.015; 3/6 seeds+, 0 neg); (d) **HALLAZGO ROBUSTO**: el durable (cura 119) es robustamente NEGATIVO
  downstream en AMBOS pools (indist m=8 −0.042, t=−2.70) → confirma su INVERSIÓN del 151, ahora también en la decisión y fuera-de-forma.
  Verificación adversarial de 4 sondas (design_valid=False, recomendó MIXTA, cazó el mislabel "m chico=escasez" vs exp124 + el
  overstatement de negatividad). NET: el pago downstream del residuo queda SIN RESOLVER en el régimen escaso real (defecto de diseño,
  no evidencia adversa); la inversión del durable se confirma. FRONTERA (CYCLE 153): pool fijo COMPARTIDO de BAJA base-rate (q≈0.1) o
  f≈1, preservando el desconfound; subir N; reportar f=m/#correct.
- **[NUEVO 153 — 1er POSITIVO-LEANING del arco (MIXTA), pero RANK-ONLY → re-expresa el 151, no prueba calibración]** exp135 (N=6, el
  diseño CORRECTO que el 152 sembró: pool fijo COMPARTIDO **ESCASO** base-rate 0.125 -1 pos + 7 neg/prompt, desconfound del 151
  preservado- + precision@top-m por **f=m/#correct**, régimen discriminante f≈1; INDIST + HELDOUT). Corrige la saturación del 152 (pools
  NO saturan, informativos). RESULTADO en 3 capas: (a) el DISEÑO funciona; (b) **1ª señal positiva del arco**: ls_lo−naive a f=1.0
  pre-registrado positivo y t-significativo SIN corregir en AMBOS pools (indist +0.054 t=2.29, heldout +0.029 t=2.36) y monótono en
  indist; (c) PERO **NO robusta** (falla 6/6 -5/6-, leave-one-out del seed más favorable -t→1.8<2.015-, Bonferroni -familia 14, t_crit
  4.382-; indist cargado por 2 seeds, monótono no replica en heldout; N=6 smoke) **Y RANK-ONLY** (error de categoría cazado por la
  verificación, sev media): precision@top-m vía argsort es invariante a transformaciones monótonas de la confianza -igual que AUROC- →
  NO testea CALIBRACIÓN, testea RANKING; la ventaja del ls_lo RE-EXPRESA el AUROC del 151 (+0.018, co-mueven round-level r≈0.87) → 0
  información decisional independiente; **NO prueba la tesis 123, sólo la APUNTA**. (d) HALLAZGO ROBUSTO (multiplicity-survivor): el
  durable (cura 119) es NEGATIVO robusto downstream (indist f=1.0 −0.271, t=−8.58) → confirma su inversión del 151/152 también en la
  decisión y fuera-de-forma. Verificación adversarial de 4 sondas (design_valid=True, signal_is_real=FALSE, overclaim_risk=ALTO,
  recomendó MIXTA; cazó el error de categoría rank-only + el t_crit Bonferroni subestimado). NET: el arco toca su 1er positivo, pero
  sugestivo-no-concluyente y rank-only → la pregunta "¿la calibración paga downstream?" queda BIEN PLANTEADA y abierta. FRONTERA
  (CYCLE 154): métrica decisional NO invariante-a-monótonas (cost-weighted / umbral-abstención) que separe CALIBRACIÓN de RANKING; N≥12;
  LOO + Bonferroni; réplica out-of-sample.
- **[NUEVO 154 — CAPSTONE del arco downstream: el residuo es RANKING, no CALIBRACIÓN (REFUTADA-de-RELIABILITY)]** exp136 (N=6, el test
  DECISIVO que el 153 definió: sobre el pool fijo escaso del 153, métricas SENSIBLES A MAGNITUDES -Brier, **ECE = reliability PURA
  threshold-free**, NET umbral-abstención- vs AUROC rank-only, que SEPARAN calibración de ranking). RESULTADO: la reliability del
  residuo genérico (ls_lo) NO paga — el **ECE es plano-a-PEOR** en AMBOS pools (indist −0.006 t=−1.28, ls_lo levemente peor; heldout
  +0.0004; el durable también peor). El **único payoff ROBUSTO es RANKING** (heldout AUROC +0.017, t=3.74, disociación limpia: AUROC
  robusto con ECE/Brier nulos). ACOTACIÓN load-bearing (verificación, 3 sondas ACOTA + 1 REFUTA): NO "todo se desvanece" — en indist
  −Brier (+0.007, t=2.21, CI excl 0) y NET(λ3) (+0.081, CI excl 0) SÍ son positivos sub-robustos PERO por Brier=reliability−resolution
  +uncertainty con ECE plano son **RESOLUTION (ranking re-expresado**, co-mueve con AUROC ~0.82); el **NET heldout es DEGENERADO** (cero
  estructural, nadie cruza τ OOD) → no-evidencia. FRAGILIDAD: N=6 smoke, el label flipea REFUTADA↔APOYADA por lote (seeds 3-5 darían
  APOYADA vía Brier/resolution = falso positivo del gate). NET: **CIERRA el arco downstream "¿calibración o ranking?" (149-154) del
  lado RANKING** — lo que sobrevivió al desconfound del 151 es una señal de RANKING/discriminación, NO una señal de valor más
  calibrada; **la tesis 123 ("la calibración paga en la decisión") NO queda tocada por este residuo** en el lazo real desconfundido.
  ACOTADO: "no se detecta reliability residual vía ECE", no "demostrado imposible" (N=6 batch-frágil). FRONTERA: réplica N≥12 con barra
  SIMÉTRICA + umbral EV-óptimo POR-BRAZO (no τ fijo, que degenera OOD); o PIVOTE (régimen base-acc alta / transferencia / SCALE).

## 2. ASUMIDO / ACOTADO (real pero condicional — el grueso del arco)

- **El agente DESCUBRE ambos factores del keystone de UN stream (134-137)** — pero bajo supuestos: base de credit-assignment
  expresiva (135), régimen de abundancia para el cuello R-PRIOR (136), sustrato lineal acoplado (137).
- **El aislamiento de la relevancia bajo ciclos reach≠relevancia es CONDICIONAL a K<#drivers (143).** A K=#drivers EVAPORA
  (el artefacto K=1 que 139 ya había retractado — re-introducido sin querer, cazado por verificación). Depende de decoys
  simétricos; reach=oracle tautológico.
- **La ventaja del valor depende de la ALINEACIÓN-con-el-producto (146).** Con residuo ortogonal, el prior de baja capacidad
  HUNDE al estimador. No free lunch.
- **El pago decisional en el lazo REAL (verifier exp018) es MODESTO y frágil (140-141).** AUROC de la confianza endógena vs
  correctness tiene ventaja de ranking modesta, confundida por base-rate, underpowered a N=8 (sign-test p≈0.07, dilución).

## 3. REFUTADO / RETRACTADO (overclaims cazados por verificación adversarial)

| Ciclo | Overclaim inicial | Lo que cazó la verificación |
|---|---|---|
| 138 | "el keystone EMERGE empíricamente del control" | TAUTOLOGÍA (efe_pragmatic = la métrica del eval); la corrección robusta es v, no w² |
| 139 | "reach-∞ cruda del 137 es robusta" | el gap era artefacto K=1; la forma no es privilegiada |
| 140 | "el payoff decisional en el lazo real es claro" | CONFOUND de base-rate; no logueaba el naive |
| 141 | "N=8 resuelve la significancia" | significancia frágil + magnitud diluyendo + mecanismo = artefacto de round-1 |
| 142 | "recombinación = mecanismo nuevo de capacidad" | trivialidad parcial + recombinación universal + se invierte en binario |
| 143 | "cierra el caveat de relevancia de 139" | RE-USO del artefacto K=1 que 139 había retractado (auto-inconsistencia) |
| 144 | "w·v·ctrl bate a ambos; refuta el cuadrado de 138" | overclaim BIDIRECCIONAL: incluir-v definicional + refutación deshonesta de 138 (muestreé el rincón limpio) |
| 145 | "el continuo QUITA el winner-take-all / decae igual" | escaso-continuo ES concentrado (soft top-k); decaimiento g-dependiente; residual permanente |
| 146 | "sesgo inductivo incondicional + anti-tautología" | overclaim TRIPLE: anti-tautología vacua (~0.95 colineal) + decisión = suficiencia (no robustez) + condicional a la alineación |
| 149 | "APOYADA limpia: la confianza del durable es calibración endógena más informativa" | DESCONFUNDIDO por 151: el AUROC_own era riqueza de generación; el durable se INVIERTE (−0.210) en un pool fijo balanceado → atribución a 'calibración' REFUTADA (la observación durable>naive OWN persiste) |
| 151 | "APOYADA: hay señal de ranking genuina (CI excluye 0)" (regla pre-registrada) | la regla "CI bootstrap excluye 0" es TAUTOLÓGICA con gaps un-signo; el t-test pareado real es sub-significativo (t=1.98<2.015) → re-etiquetada MIXTA; + error factual "generados desde el base" (eran CONSTRUIDOS) |
| 152 | "REFUTADA-downstream: el residuo tampoco paga en la decisión" | DEFECTO DE DISEÑO (sev ALTA): el pool balanceado 50/50 SATURA precision@top-m (INDIST gap CERO ESTRUCTURAL) y NO es escaso (f<=0.5, nunca f≈1) → la tesis 123 NUNCA se testeó; "m chico=escasez" contradice exp124 → re-etiquetada MIXTA-ACOTADA |
| 153 | "APOYADA-downstream: el residuo paga bajo escasez (la brújula-123 vale)" | ERROR DE CATEGORÍA (sev media): precision@top-m es RANK-ONLY (invariante a monótonas, como AUROC) → NO testea calibración, RE-EXPRESA el AUROC del 151 (r≈0.87); + no robusto (falla LOO/Bonferroni/6-de-6) → re-etiquetada MIXTA (1er positivo-leaning, sugestivo no concluyente) |
| 154 | "REFUTADA-calibración: ECE/Brier/NET se desvanecen (disociación limpia)" | OVERSELL DEL NEGATIVO (3 sondas ACOTA): el −Brier/NET indist NO se desvanecen (CI excl 0) -son RESOLUTION=ranking, no reliability-; el NET heldout es DEGENERADO (no-evidencia); el label es batch-frágil (un sub-lote daría APOYADA) → re-etiquetada REFUTADA-de-RELIABILITY (anclada en ECE, la única reliability pura) |

## 4. SATURACIÓN del toy + FRONTERA REAL

**Conclusión honesta (post-146):** el toy LINEAL del keystone está SATURADO. 6 MIXTA seguidos (141-146), incluido un PIVOTE
deliberado (146, aprender el valor en vez de usarlo), dan todos el resultado ESTÁNDAR acotado en cada dirección
(tautología / recombinación / régimen / concentración / no-free-lunch). Más ciclos en esta vena rinden poco.

**La frontera que movería la aguja (ninguna tocada a fondo):**
1. Una función de valor / sesgo inductivo **APRENDIDA desde experiencia en un sistema REAL** (no asumida a mano, no toy
   lineal). Lo más cercano en CPU: el lazo real (exp018 verifier + HybridLM byte-level). Costo: torch lento (~60 min/corrida).
2. **SALIR DEL ORÁCULO con potencia:** N≥16 para la dilución de 141 + baseline regularizador-de-calibración ALTERNATIVO
   (¿la cura unlikelihood de 119 es privilegiada o cualquier regularizador sirve?); lazo SECUENCIAL.
   → AVANCE 150-151: la cura NO es privilegiada (150) y su ventaja AUROC era riqueza de generación (151, desconfundida con pool fijo).
   → 152 INTENTÓ el pago downstream (precision@top-m) pero el pool balanceado SATURÓ el test y NO instanció la escasez (f<=0.5) →
   MIXTA-ACOTADA, la tesis 123 sin testear (la inversión del durable SÍ se confirmó downstream). 153 lo rehízo bien (pool ESCASO + f≈1):
   1er POSITIVO-LEANING del arco (ls_lo−naive a f=1.0 t-sig sin corregir en ambos pools) PERO no robusto (LOO/Bonferroni) y RANK-ONLY
   (precision@top-m re-expresa el AUROC del 151, no testea calibración). 154 lo RESOLVIÓ (métricas magnitude-sensitive, ECE=reliability pura): la calibración del residuo NO paga (ECE plano-a-peor); el
   único payoff robusto es RANKING → la tesis 123 no la toca este residuo. ARCO DOWNSTREAM CERRADO del lado ranking (ACOTADO N=6). QUEDA: réplica N≥12 + umbral EV-óptimo por-brazo; o PIVOTE (base-acc alta / transferencia / SCALE).
3. **SCALE (GPU/Kaggle):** la frontera #1 de la auditoría, JAMÁS tocada (0%), hardware-bloqueada en este i3 sin CUDA.

## 5. Mapa conceptual — % honesto

- **Mapa conceptual del valor endógeno (toy):** ~70% (forma, grounding EFE, capacidad/escasez, varianza-prior, sesgo
  inductivo, decisión bajo escasez — todos caracterizados con sus acotaciones).
- **Sistema real escalado:** ~31% (149 estableció que el durable bate al naive en AUROC_own en el lazo real; 150 ACOTÓ -la cura NO es
  privilegiada, un target-smoothing genérico la iguala- y SOSPECHÓ el confound de generación; 151 lo CERRÓ con el desconfound limpio
  (pool fijo balanceado): la ventaja AUROC_own del durable era ENTERAMENTE riqueza de generación -se INVIERTE a −0.210 en el pool
  fijo, t=−10.6, 6/6 seeds- → la atribución 'calibración endógena' del 149 queda REFUTADA; sólo un residuo GENÉRICO de signo (ls_lo
  +0.018) sobrevive, no robusto por t-test. El % SUBE respecto al 22% no porque haya MÁS payoff sino porque una pregunta load-bearing
  está RESUELTA: ahora SABEMOS que el payoff del lazo real es mayormente artefacto de generación + un residuo genérico mínimo —
  entendimiento honesto, deflacionario. 152 intentó el pago DOWNSTREAM del residuo (precision@top-m) pero el pool balanceado SATURÓ el
  test y NO instanció la escasez real (f<=0.5) → MIXTA-ACOTADA, la tesis brújula-decisional (123) bajo escasez SIN testear (defecto de
  diseño, no evidencia adversa); sí se CONFIRMÓ la inversión del durable downstream y fuera-de-forma (held-out). 153 rehízo el downstream
  bien (pool ESCASO + f≈1): 1er POSITIVO-LEANING del arco PERO no robusto (LOO/Bonferroni) y RANK-ONLY (precision@top-m re-expresa el
  AUROC del 151). 154 (CAPSTONE) lo RESOLVIÓ con métricas SENSIBLES A MAGNITUDES (ECE=reliability pura): la calibración del residuo NO
  paga -ECE plano-a-peor en ambos pools-; el único payoff robusto es RANKING (heldout AUROC +0.017 t=3.74). CIERRA el arco downstream
  '¿calibración o ranking?' (149-154) del lado RANKING: lo que sobrevivió al desconfound es ranking, NO calibración → la tesis 123 NO
  la toca este residuo. ACOTADO N=6 batch-frágil ('no se detecta', no 'imposible'). Falta: réplica N≥12 + umbral EV-óptimo por-brazo;
  régimen base-acc alta; transferencia; escala. ~31%.
- **SCALE:** 0% (hardware-bloqueado en este i3 sin CUDA — la frontera #1 de la auditoría, intocada).

> Regla para el próximo ciclo: NO re-derivar lo de §1-3. El ARCO DOWNSTREAM (151-154) está CERRADO: el residuo del lazo real es
> RANKING, no calibración; la tesis 123 no la toca este residuo. Próximas fronteras §4 (elegir una): (a) RÉPLICA N≥12 del 154 con barra
> SIMÉTRICA + umbral EV-óptimo por-brazo (confirmar el cierre, hoy ACOTADO N=6 batch-frágil); (b) régimen base-acc ALTA (donde el 149
> se apagaba); (c) transferencia a otra tarea/modelo; (d) SCALE (hardware-bloqueado en este i3 — declararlo honestamente). El método
> (verificación adversarial antes del ledger) es INNEGOCIABLE. Lecciones transversales del arco 151-154: (151) 'CI bootstrap excluye 0'
> NO prueba robustez con gaps un-signo (tautológico) → t-test pareado; (152) 'm chico' NO es 'escasez' (es f=m/#correct≈1); una métrica
> saturada no puede ni apoyar ni refutar; (153) precision@top-m/AUROC son RANK-ONLY → no testean calibración; (154) separar reliability
> (ECE) de resolution (Brier/NET mezclan ranking) exige una métrica threshold-free; un umbral fijo compartido degenera OOD.

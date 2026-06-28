# STATUS_RVALOR.md — Estado honesto del arco R-VALOR (CYCLEs 79-150)

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
  vs un regularizador genérico? → RESUELTA por 150 (abajo): NO privilegiada.
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
  FRONTERA: régimen base-acc alta; transferencia; SCALE.

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

## 4. SATURACIÓN del toy + FRONTERA REAL

**Conclusión honesta (post-146):** el toy LINEAL del keystone está SATURADO. 6 MIXTA seguidos (141-146), incluido un PIVOTE
deliberado (146, aprender el valor en vez de usarlo), dan todos el resultado ESTÁNDAR acotado en cada dirección
(tautología / recombinación / régimen / concentración / no-free-lunch). Más ciclos en esta vena rinden poco.

**La frontera que movería la aguja (ninguna tocada a fondo):**
1. Una función de valor / sesgo inductivo **APRENDIDA desde experiencia en un sistema REAL** (no asumida a mano, no toy
   lineal). Lo más cercano en CPU: el lazo real (exp018 verifier + HybridLM byte-level). Costo: torch lento (~60 min/corrida).
2. **SALIR DEL ORÁCULO con potencia:** N≥16 para la dilución de 141 + baseline regularizador-de-calibración ALTERNATIVO
   (¿la cura unlikelihood de 119 es privilegiada o cualquier regularizador sirve?); lazo SECUENCIAL.
3. **SCALE (GPU/Kaggle):** la frontera #1 de la auditoría, JAMÁS tocada (0%), hardware-bloqueada en este i3 sin CUDA.

## 5. Mapa conceptual — % honesto

- **Mapa conceptual del valor endógeno (toy):** ~70% (forma, grounding EFE, capacidad/escasez, varianza-prior, sesgo
  inductivo, decisión bajo escasez — todos caracterizados con sus acotaciones).
- **Sistema real escalado:** ~22% (149 estableció a POTENCIA + out-of-sample que el durable bate al naive en AUROC en el lazo real
  -primer APOYADA limpio fuera del oráculo-; 150 AFINÓ y ACOTÓ: la cura NO es privilegiada -un target-smoothing genérico la iguala/
  supera-, PERO descubrió que el AUROC del lazo real está CONFUNDIDO con la riqueza de generación → NO se aísla 'calibración' como
  mecanismo, lo que cualifica retroactivamente el 149. Net: entendemos el payoff del lazo real MÁS HONESTAMENTE -más acotado de lo
  que el 149 sugería-. Sigue juguete-real sin escala; falta DESCONFUNDIR calibración-de-generación, el pago DOWNSTREAM y el régimen
  base-acc alta).
- **SCALE:** 0% (hardware-bloqueado en este i3 sin CUDA — la frontera #1 de la auditoría, intocada).

> Regla para el próximo ciclo: NO re-derivar lo de §1-3. Atacar §4 (lazo real: pago downstream / régimen base-acc alta /
> transferencia / SCALE) o declarar honestamente el bloqueo de hardware. El método (verificación adversarial antes del ledger) es
> INNEGOCIABLE.

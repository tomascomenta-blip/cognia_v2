# STATUS_RVALOR.md — Estado honesto del arco R-VALOR (CYCLEs 79-146)

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
- **Sistema real escalado:** ~10-15% (el lazo real existe y da señal modesta; no hay escala).
- **SCALE:** 0% (hardware-bloqueado).

> Regla para el próximo ciclo: NO re-derivar lo de §1-3. Atacar §4 (lazo real / salir-del-oráculo / SCALE) o declarar
> honestamente el bloqueo de hardware. El método (verificación adversarial antes del ledger) es INNEGOCIABLE.

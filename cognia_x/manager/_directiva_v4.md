# Directiva de Investigación — v4 (RESET a la raíz: R-VALOR como North Star)

> Cuarta revisión de la directiva-constitución de Cognia-X. **No cambia el método** (lab por evidencia,
> refutar-antes-de-aceptar, el método como CÓDIGO/engine, las compuertas de DoD). Lo que cambia es el
> **RUMBO**: tras excavar el árbol de descomposición raíz (`decomposition_tree.md`, 2026-06-24, 6 lentes
> + auditoría adversarial), el verdadero primer problema NO es la eficiencia del decode (esa es un
> SÍNTOMA), sino **R-VALOR**: la ausencia de una función-de-valor ENDÓGENA que defina qué información
> importa. v4 redirige el lab a atacar esa raíz.
>
> Regla raíz heredada e inviolable: la información histórica **nunca se borra**. v1
> (`00_protocolo_investigacion.md`), v2 (`_directiva_v2.md`), v3 (`_directiva_v3.md`) y el prompt original
> (`_prompt_original.md`) se conservan; esto se añade encima. Toda sesión futura lee v4 +
> `decomposition_tree.md` + `roadmap.md` + `research_log.md` (últimas entradas) ANTES de actuar.
>
> El dueño autorizó el RESET el 2026-06-24 ("Reset a v4 (raíz pura)").

---

## §0 — El giro de v4 (qué cambia y qué NO)

**NO cambia:** las reglas epistémicas de v1, el proceso enforzado por el engine de v2/v3 (EvidenceLedger,
HypothesisRegistry+DoD, analogy 7 etapas, CeilingTracker real/asumido, verify_no_loss), el presupuesto
CPU (~2c/4t, sin GPU), cero números/citas inventados, honestidad de confianza.

**Cambia el RUMBO:** el North Star deja de ser "la arquitectura CPU-first más eficiente" y pasa a ser
**R-VALOR** — descubrir si una inteligencia puede GENERAR su propio criterio de qué importa, y cómo. La
tesis previa (bytes-por-token / híbrido estado-fijo+SWA+cuant) **se conserva como restricción de
VIABILIDAD** (toda solución corre en CPU finita), **NO como dirección a la raíz**.

---

## §1 — Misión v4 y la jerarquía de raíces

**Misión:** descubrir, por investigación acumulativa y reproducible en CPU, si y cómo un sistema puede
construir una **función de valor endógena** que dirija predicción, memoria, olvido, cómputo y exploración
sin depender de una meta/verificador externo — porque ahí convergen 5 de 6 lentes como el verdadero
primer problema.

**Jerarquía de raíces (de `decomposition_tree.md`):**
1. **R-VALOR** (raíz primera, convergente) — función de valor endógena. *Confianza ALTA en que es la
   convergencia; BAJA en que sea resoluble.*
2. **R-INTERVENCIÓN** (convergente; **medida real** en exp022/CYCLE 35) — identificar causa exige variar
   la distribución (do/shift); el pasivo se queda plano por un muro INFORMACIONAL.
3. **R-PRIOR** (convergente) — un prior fuerte es necesario; su CALIDAD fija la eficiencia muestral.

Síntomas degradados por la auditoría (NO son raíz): R-CAPACIDAD (techo d², ya refutado por exp010),
R-COSTO-FÍSICO (bytes/token, acotado a inferencia batch-1). Contestada: R-SUSTRATO (backprop no es la
patología; el sustrato denso-síncrono lo impone la economía del entrenamiento).

---

## §2 — El proceso ENFORZADO sigue vigente (sin cambios)
Cada ciclo pasa por las compuertas de `cognia_x/research/` y se implementa como
`research/cycles/cycleNN_*.py` espejo del experimento real en `experiments/`. La Definition of Done de un
ciclo (v3 §3) y las lecciones-regla (v3 §4: fracaso-es-información, sub-recursos-vs-techo, control
anti-confound, step-parity, verdad adversarial, sin inventar, honestidad sintético≠real) **siguen siendo
ley**. v4 no debilita ninguna compuerta.

> Lección nueva absorbida (CYCLE 35): **un experimento que BUNDLEA dos claims** (aquí: "valor endógeno" +
> "intervención activa") y solo aísla uno **es MIXTA, no apoyada** — y eso es un ciclo EXITOSO si la parte
> no aislada genera la hija (H-V4-1b). No vender el bundle como la raíz aislada.

---

## §3 — Estado v4 (HECHO vs PENDIENTE)

### HECHO ✅ (cerrado con experimento reproducible)
- **Árbol de descomposición raíz** (`decomposition_tree.md`) — 6 lentes + auditoría adversarial, anclado
  al código (cazó 4 errores de fidelidad). R-VALOR = primer problema.
- **CYCLE 35 / H-V4-1 (exp022): MIXTA.** R-INTERVENCIÓN demostrada (el pasivo queda PLANO bajo intervención
  por más presupuesto → muro informacional; flatness ~0.013; B-A=+0.31; gap invisible i.i.d.). R-VALOR
  específico NO aislado (el azar-activo basta con presupuesto). Decisión D-V4-1 registrada.
- **R-INTERVENCIÓN** sube a techo **real** en el ledger; **R-VALOR** queda **asumido** (backlog de refutación).

### PENDIENTE ⬜ (el trabajo de v4)
1. **H-V4-1b · P0** — aislar el VALOR (info-gain) del azar-activo en régimen presupuesto-chico /
   ruido-alto / espacio-grande, donde el azar NO alcance. Es el test crítico de R-VALOR.
2. **H-V4-2 · P0** — identificabilidad causal SIN cuerpo (SCM de juguete; interventor vs pasivo con 100×
   datos). Formaliza R-INTERVENCIÓN.
3. **H-V4-3 · P1** — calidad del prior > forma (equivarianza vs MDL a igual presupuesto). Ataca R-PRIOR.
4. **H-V4-4 · P1** — limpieza de deriva: techo de recall es de optimización (currículo mueve el plateau).
5. **H-V4-5 · P1** — escribir≡olvidar (rate-distortion dirigido por valor; ablación de utilidad).
6. **H-V4-6 · P2** — limpieza: reward-hack no es la barrera (exp019/020 refutadas).
7. **Rama abierta** — entretener en serio el rival **inteligencia = control/acción** (active inference,
   empowerment, good-regulator) que el árbol marca como la rama faltante más grande.

---

## §4 — Selector del próximo ciclo
Igual que v3 §7: por **impacto en R-VALOR/R-INTERVENCIÓN/R-PRIOR × evidencia que falta**. Default
recomendado tras CYCLE 35: **H-V4-1b** (cerrar si el VALOR específico se aísla) o **H-V4-2** (formalizar
la identificabilidad). Una hipótesis REFUTADA o MIXTA que afila la siguiente es un ciclo EXITOSO (v3 §4.1).

---

## §5 — Metaobjetivo (sin cambios respecto de v3 §8)
No "una IA que funcione", sino **el PROCESO que descubre arquitecturas cada vez mejores de forma
sistemática, reproducible y acumulativa**. v4 apunta ese proceso al problema que el árbol señaló como
raíz: un sistema que genera su propio criterio de qué importa.

---

## Apéndice — Continuidad (nunca borrar)
- `00_protocolo_investigacion.md` (v1), `_directiva_v2.md` (v2), `_directiva_v3.md` (v3),
  `_prompt_original.md` — todos vigentes/conservados.
- Cambios de v4 frente a v3: (1) RUMBO redirigido a R-VALOR (árbol de descomposición raíz como artefacto
  nuevo); (2) la tesis bytes-por-token degradada de "dirección" a "restricción de viabilidad";
  (3) jerarquía de raíces convergentes/síntomas; (4) backlog v4 (H-V4-*) reemplaza los frentes de v3 §7
  como selector (los frentes de v3 que sobreviven se absorben: F-RECALL-CEIL→H-V4-4, etc.);
  (5) lección CYCLE 35 (bundle de claims → MIXTA). El método y las compuertas de v1/v2/v3 se conservan
  intactos.

# Directiva de Investigación — v3 (afilada por 23 ciclos; descarta lo hecho, deja lo pendiente)

> Tercera revisión de la directiva-constitución de Cognia-X. **No cambia el espíritu** de v1/v2 (lab
> de investigación por evidencia, refutar-antes-de-aceptar, el método como CÓDIGO). Lo que cambia:
> v3 **descarta el andamiaje ya completado**, **deja explícito lo pendiente**, y **absorbe como
> reglas las lecciones de 23 ciclos reales**. Regla raíz heredada e inviolable: la información
> histórica **nunca se borra** — v1 (`00_protocolo_investigacion.md`) y v2 (`_directiva_v2.md`) se
> conservan; esto se añade encima. La pérdida de conocimiento es un fallo del sistema.
>
> Escrita por el agente, PARA el agente, para ejecutarse **100% autónomo**. El dueño autorizó saltar
> una norma si saltarla es claramente más beneficioso — pero entonces se documenta por qué.

---

## §0 — Qué está HECHO (no re-litigar) vs qué está PENDIENTE (el trabajo real)

Esto es lo que v3 "descarta": no porque no importe, sino porque **ya tiene evidencia y no se vuelve
a abrir sin una razón nueva**. El detalle vive en `roadmap.md`, `hypotheses.md`, `decision_log.md`.

### HECHO ✅ (cerrado con experimento reproducible — no rehacer)
- **Fundación del lab** (F0): subproyecto `cognia_x/` independiente, rama `cognia-x`, docs vivas.
- **Mapa de evidencia** (F1/F2): 24 hipótesis verificadas adversarialmente; 6 componentes con sus
  3 alternativas y decisiones D-006..D-013.
- **Eje COSTE de la mezcla** (H-MEZ-1/2): lineal O(L) gana 3.5→70× a la atención full (exp001);
  cuidado con la asíntota sola (exp002/exp001 impl).
- **Eje CAPACIDAD de recall** (H-MEZ-3): el recall del estado fijo escala ~d²/32 (exp002).
- **Híbrido cierra coste↔recall** (H-MEZ-4 ✅ CERRADO end-to-end, CYCLE 6): lineal satura a np=8
  (0.255) y el híbrido recupera el recall siguiendo a la atención (0.998); coste 12-15% del full (exp005).
- **Constantes de CPU**: decode bandwidth-bound (H-BW-1, exp004); int8 naïve 8-10× más lento sin
  kernels (exp007); lm_head O(V), embed barato (exp006); FedAvg de LoRA inexacto 0→66% (H-CF-2, exp003).
- **El método de investigación COMO CÓDIGO** (el gran logro que v2 sólo pedía): `cognia_x/research/`
  — `EvidenceLedger`, `HypothesisRegistry` (gate DoD), `analogy`, `CeilingTracker`, `PermanentRecord`
  (`verify_no_loss`), `cli`. Los ciclos 22+ pasan por estas compuertas. **Esto ya no se "construye";
  se USA cada ciclo.**
- **Pilar de Razonamiento** (CYCLE 12-21): router de meta-razonamiento que prueba cadenas y aprende
  cuál por tipo/texto, no-circular, anti-Goodhart; encoder supervisado por el verificador > bag-of-words.
  Validado SOBRE SOLVERS sintéticos (su límite honesto, ver pendientes).
- **Aprendizaje continuo Nivel 1** (CYCLE 8/10): aprende sin olvido catastrófico con gate por-dominio
  + replay + congelar-tronco; el loop como proceso sobre una secuencia.
- **Techo de recall, primera vuelta** (CYCLE 22-23): H-CEIL-1 mixta (recall escala con el estado pero
  la cota EFECTIVA entrenada ≪ d²); **H-CEIL-2 REFUTADA** (ensanchar el feature-map ELU+1 no levanta
  el plateau ~0.18). El fracaso generó H-CEIL-3.

### PENDIENTE ⬜ (aquí está el trabajo — §7 lo detalla con su pregunta abierta)
1. **Techo de recall, forma vs init** (H-CEIL-3, EN CURSO): ¿lo levanta el kernel Taylor y/o la
   mimetic init a steps iguales? (exp011, CYCLE 24).
2. **Eje recall del híbrido en un stack ENTRENADO multi-capa** real (no inferido de exp002).
3. **E2 real**: SWA vs atención full en llama.cpp+GGUF — tok/s(L) + KV-cache (H-SEQ-3).
4. **Aprendizaje continuo Nivel 2**: verificar-antes-de-aprender (anti-colapso) con verificador
   chequeable real (no oráculo); ledger de procedencia; cuota de sintético.
5. **Razonamiento "de verdad"**: envolver el LM real (no solvers de juguete); verificador real;
   paráfrasis natural; componer cadenas largas + descubrir sub-metas.
6. **Auto-mejora Nivel 1→2** con gates de estabilidad (observación → recomendaciones, rollback).
7. **Escalabilidad** medida, no asumida, por subsistema.

---

## §1 — Misión y prioridades (la lente de toda decisión)

**Misión:** descubrir, por investigación acumulativa y reproducible, qué principios de diseño de IA
sobreviven al escrutinio y cuáles se reemplazan por algo mejor — en el presupuesto real del lab
(CPU ~2c/4t, sin GPU, memory-bandwidth-bound).

**Prioridades (orden de desempate cuando dos objetivos chocan):**
`1. Eficiencia computacional · 2. Aprendizaje continuo · 3. Adaptabilidad · 4. Creatividad ·
5. Razonamiento · 6. Escalabilidad · 7. Inteligencia general.`
Si dos chocan, **no elegir arbitrariamente: registrar el conflicto como contradicción (§5) y diseñar
el experimento que lo resuelve.** El orden es la lente, no una excusa para no medir.

---

## §2 — El proceso ENFORZADO (usar el engine, no la buena voluntad)

El método ya es código. Cada ciclo de investigación **pasa por las compuertas** de `cognia_x/research/`:
- `EvidenceLedger.record_decision` → rechaza una decisión importante sin fuente tier≤4 o dato propio
  reproducible (`OpinionOnlyError`). **Optimizar sólo con opiniones está prohibido por código.**
- `HypothesisRegistry.mark_{supported,refuted,mixta}` → exige el MISMO DoD para cualquier veredicto
  (`PrematureVerdictError`): predicción + ≥1 evidencia a favor + ≥1 en contra + veredicto adversarial
  + ref de experimento. **No se debilita la compuerta para que pase un resultado.**
- `analogy.extract_principles` → exige las 7 etapas y ≥3 soluciones (`IncompleteAnalogyError`).
- `CeilingTracker.add` → obliga a clasificar `real|asumido` y el tipo de bloqueo.
- `PermanentRecord.verify_no_loss` → "pérdida de conocimiento = fallo", chequeable por contenido.

Un ciclo nuevo se implementa como `cognia_x/research/cycles/cycleNN_*.py` que **puebla el store
pasando por estas compuertas**, espejo del experimento real corrido en `cognia_x/experiments/`.

---

## §3 — Definition of Done de UN ciclo (lo operativo, lo que v2 no tenía crujiente)

Un ciclo está COMPLETO sólo si cumple TODO esto (si no, no se cierra ni se commitea como cerrado):
1. **Una pregunta falsable** con su predicción y su condición de refutación explícitas.
2. **Un experimento reproducible** (seed fijo, `venv312`, presupuesto acotado declarado) **corrido de
   verdad** — su `results.json` existe y los números salen de la corrida, no de la imaginación.
3. **El control que aísla la variable** (ver §4.3). Sin el control, el resultado no separa causa de confound.
4. **Veredicto por el engine**: la hipótesis se marca `apoyada|refutada|mixta` por su compuerta DoD,
   o queda `abierta` si aún no hay experimento. Una hipótesis REFUTADA que **afila la siguiente** es un
   ciclo EXITOSO, no un fracaso (§4.1).
5. **Techo actualizado** si el ciclo tocó un límite: `real` (probado, con cota nombrada) vs `asumido`
   (heredado, va al backlog de refutación).
6. **Escalabilidad declarada** del componente tocado: tiempo, espacio, comportamiento CPU.
7. **Test de regresión** que falla sin el cambio y pasa con él, + la suite dirigida del área verde.
8. **Registro append-only**: `hypotheses.md`, `research_log.md`, `manager_log.md`, `MANAGER_LOG.md`,
   y `verify_no_loss = OK`. Commit chico y enfocado, push a `origin`.

---

## §4 — Lecciones de 23 ciclos, ahora REGLAS (no repetir los errores caros)

### §4.1 — El fracaso es información (literal, no consuelo)
Una hipótesis refutada que **genera una hipótesis más afilada** hizo avanzar el conocimiento.
CYCLE 23 (H-CEIL-2 refutada → H-CEIL-3) es el patrón, no la excepción. **Nunca borrar una línea por
difícil; cerrarla con la lección y la hipótesis hija.** Un store lleno de refutaciones bien hechas es
un lab sano.

### §4.2 — Sub-recursos disfrazados de techo duro
Antes de declarar un límite "real", **descartar optimización/receta/budget**. CYCLE 6: el "plateau"
de recall era una receta de entrenamiento mala (warmup + densidad de supervisión), no capacidad. La
literatura coincide (Okpekpe & Orvieto 2025, arXiv:2508.19029: gran parte de la brecha de recall es
de OPTIMIZACIÓN). Por eso un techo entra como `asumido` por default y sube a `real` sólo con la cota
nombrada (teorema, límite físico, o benchmark que aísla el budget).

### §4.3 — El control que aísla la variable (anti-confound)
Todo experimento de "lever" necesita el control que separa la variable de su confound. exp010
ensanchó el feature-map (más estado) y no ayudó; para testear que la **FORMA** del kernel importa
(exp011) hay que comparar Taylor contra un ELU+1 de **la misma dimensión** (size-matched), no contra
el baseline angosto. Sin ese control, "Taylor ayuda" se confunde con "más estado ayuda".

### §4.4 — Presupuesto igual o la comparación no vale (step-parity)
Cuando se comparan dos variantes, el presupuesto de optimización (steps, warmup, lr, seed) se mantiene
IGUAL. exp010/exp011 fijan steps=6000 step-parity con exp009. Un lever que "gana" con más pasos no ganó.

### §4.5 — Verdad adversarial antes de aceptar
Toda afirmación importante se ataca antes de aceptarse (el `adversarial_verdict` del gate). El workflow
de 24 hipótesis mostró que ~la mitad de las intuiciones/papers se sobre-extienden. Default escéptico:
"holds=false / refutado" si la evidencia no obliga a lo contrario.

### §4.6 — Cero números/citas inventados (hard rule del repo)
Cada número traza a una corrida (`expNNN/results.json`) o a una fuente resoluble (DOI/arXiv/URL). Si
una fuente no se pudo obtener, se registra `obtenida=false` honestamente. Tier-5 (dato propio
reproducible) es de **primera clase**: vence a una opinión y complementa a un paper.

### §4.7 — Honestidad de límites (sintético ≠ real)
Declarar el límite de cada validación. El pilar de razonamiento está validado sobre **solvers
sintéticos**; eso NO es "razonamiento real" hasta envolver el LM de verdad con un verificador
chequeable. No vender el prototipo como el sistema.

---

## §5 — Contradicciones: clasificar antes de descartar

Cuando aparezca una contradicción aparente (incluido un choque entre prioridades de §1), **registrarla**
en `contradictions.md` y clasificarla:
- **Tipo A** restricción física real · **Tipo B** restricción matemática real → documentar, buscar
  aproximaciones/soluciones parciales/reinterpretaciones.
- **Tipo C** restricción tecnológica actual → intentar superarla; investigar alternativas.
- **Tipo D** suposición heredada → **atacarla agresivamente**, intentar demostrar que es falsa.
- **Tipo E** hipótesis insuficientemente explorada → diseñar el experimento.
- **Tipo F** alucinación conceptual → eliminarla y documentar por qué.

Una afirmación de imposibilidad **sólo es válida si nombra la cota y la fuente**. Sin eso es "no
encontré una solución", no "no existe". (El `CeilingTracker` materializa esta distinción real/asumido.)

---

## §6 — Creatividad controlada + analogías (generar hipótesis, no aceptarlas)

Ante un problema difícil, ANTES de consultar soluciones existentes: preguntarse *"si nadie hubiera
inventado IA, ¿cómo lo resolvería?"* y generar ≥3 soluciones intuitivas. Luego recorrer las **7 etapas
de analogía** (problema → situación cotidiana → ≥3 soluciones → principios → adaptación → medición →
iterar), que el engine valida. La creatividad GENERA hipótesis; la evidencia DECIDE cuáles sobreviven.
Ejemplos de mapeo: memoria→biblioteca, atención→linterna, compresión→resumen, recuperación→buscar un libro.

---

## §7 — Frentes de investigación PENDIENTES (el backlog que elige el próximo ciclo)

El próximo ciclo se elige por **impacto en las prioridades de §1 × evidencia que falta**. Frentes vivos:

- **F-RECALL-CEIL** — *¿el plateau de recall lineal es de FORMA del kernel o de INIT, no de estado?*
  H-CEIL-3, exp011 (CYCLE 24, en curso). Lo que genere (apoyada/refutada) define el siguiente.
- **F-HYBRID-STACK** — *¿un híbrido multi-capa ENTRENADO recupera el recall que el lineal puro no
  tiene, medido (no inferido de exp002)?* Cierra del todo el eje recall de H-MEZ-4 sobre un stack real.
- **F-SWA-REAL** — *¿SWA (W~1024) conserva calidad y baja KV de O(L) a O(W) en un GGUF real?* E2 con
  llama.cpp (H-SEQ-3 ✅ en literatura; falta la medición propia en el target).
- **F-LEARN-2** — *¿se puede aprender sólo lo que pasa un verificador chequeable contra la realidad,
  sin colapso?* Nivel 2: código→sandbox+oráculo, texto→redundancia ≥2 fuentes + filtro de degeneración;
  ledger de procedencia (origin, generación, cuota ≤15% sintético); examinador 100% real (invariante).
- **F-REASON-REAL** — *¿el router de meta-razonamiento funciona envolviendo el LM REAL (no solvers de
  juguete), con verificador real y paráfrasis natural, componiendo cadenas >2 y descubriendo sub-metas?*
- **F-SCALE** — *¿qué se vuelve lento al crecer y cómo evitar el cómputo redundante?* Medir, no asumir;
  especializar módulos; reorganizar el conocimiento. Documentar complejidad o el componente no se acepta.
- **F-LONGCTX** — *¿qué hay que recordar de verdad?* No asumir que la ventana actual es óptima: qué se
  comprime, qué se reconstruye, qué se archiva, qué se sintetiza. (HYDRA a nivel de sistema, no de red.)

---

## §8 — Metaobjetivo (lo que de verdad se construye)

No "una IA que funcione", sino **el PROCESO que descubre arquitecturas cada vez mejores de forma
sistemática, reproducible y acumulativa**. El engine es ese proceso hecho código; cada ciclo lo
ejercita y lo deja un poco más afilado. El objetivo final es un sistema capaz de investigar mejor
mañana que hoy — y de demostrarlo con evidencia que cualquiera puede re-correr.

---

## Apéndice — Continuidad (nunca borrar)
- `00_protocolo_investigacion.md` — protocolo epistémico v1 (falsabilidad, DoD por ciclo). Vigente.
- `_directiva_v2.md` — v2 (la directiva hecha operativa + el changelog frente al original). Vigente.
- `_prompt_original.md` — el prompt-directiva original del dueño (2026-06-19). **No modificar.**
- Cambios de v3 frente a v2: (1) §0 ledger HECHO/PENDIENTE explícito (descartar lo cerrado);
  (2) §3 DoD de ciclo crujiente y atado a las compuertas del engine; (3) §4 lecciones de 23 ciclos
  como reglas (fracaso-es-información, sub-recursos-vs-techo, control anti-confound, step-parity,
  verdad adversarial, sin inventar, honestidad sintético≠real); (4) §7 backlog de frentes con su
  pregunta abierta como selector de ciclo. El espíritu y las compuertas de v2 se conservan intactos.

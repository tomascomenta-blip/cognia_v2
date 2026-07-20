# 09 — Núcleos de razonamiento y comunicación + planificador/verificador + meta-razonamiento + hipótesis

> **Propósito.** Especificar cómo se ensambla el **lado cognitivo** del sistema: la **separación física
> en dos núcleos** (el *razonador* produce ideas verificadas, el *comunicador* las expresa en lenguaje
> natural), el **lazo planificador-rápido → verificador-profundo → re-planificación**, el **router de
> meta-razonamiento** (que YA EXISTE y corre, CYCLE 12-21), el **engine de generación + clasificación de
> hipótesis** (que YA está en código, CYCLE 22) y la **auto-evaluación + abstención calibrada** (CYCLE
> 46). El eje conceptual del plano es **qué de todo esto se internaliza DENTRO del modelo entrenado vs
> qué queda como herramienta externa de proceso** — y por qué. DoD: **un razonamiento multi-paso
> verificado end-to-end con comunicación desacoplada**.

> **Anclaje de fuentes (verificado leyendo el código, no asumido):**
> - **Router de meta-razonamiento que corre hoy:** `cognia_x/reason/router.py` (`Router`,
>   `mode="verifier"|"confidence"`, `select`, `_is_unsure`, `solve(ask_budget)`, `solve_ood`,
>   `solve_noisy`), `cognia_x/reason/composer.py` (`Composer`, `run_program`, `enumerate_programs`),
>   `cognia_x/reason/supervised_router.py` (`SupervisedLMRouter`, `chain_success_target`),
>   `cognia_x/reason/chains.py` (`CHAINS`, `STEP_CHAINS`, `graded_chain`),
>   `cognia_x/reason/problems.py` (`is_correct`). Resultados: `cognia_x/reason/README.md` / `RESULTS.md`.
> - **Engine de hipótesis que corre hoy:** `cognia_x/research/hypotheses.py` (`HypothesisRegistry`,
>   `PrematureVerdictError`, `_check_dod`, `mark_supported/refuted/mixta`),
>   `cognia_x/research/ledger.py` (`EvidenceLedger`, `OpinionOnlyError`),
>   `cognia_x/research/schema.py` (`Hypothesis`, `Source`, `Decision`, `TIER_NAMES`, `OPINION_TIER`),
>   `cognia_x/research/record.py` (`PermanentRecord`, `journaled_append`).
> - **Visión del dueño:** `cognia_x/manager/ARQUITECTURA_OBJETIVO.md` (§1 separación razonar↔hablar,
>   §Planificador Rápido, §Verificador Profundo, §Metarrazonamiento, §Generación de Hipótesis,
>   §Autoevaluación, Apéndice A).
> - **Planos hermanos (en `cognia_x/construccion/`):** `01_arquitectura_sistema.md` (flujo + contratos de
>   interfaz + §3.6 separación de núcleos), `04_verificador.md` (la pieza de 1ª clase, `cognia_x/verify/`),
>   `05_lazo_automejora.md` (STaR + guardia), `00_READINESS.md` (GO CONDICIONADO, orden Apéndice A).

---

## 1. Propósito y alcance

### 1.1 Qué resuelve
- **Separa razonar de hablar.** `ARQUITECTURA_OBJETIVO.md` §1 lo exige: *"El razonador produce ideas. El
  comunicador las expresa."* Este plano define la **interfaz** entre los dos núcleos (qué cruza la
  frontera, qué NO) y cómo se realiza en el v1 sobre el backbone híbrido único (plano 02).
- **Ata el planificador rápido al verificador profundo** en un lazo `plan → verify → (re-plan)` donde la
  **calidad del verificador es el cuello de botella declarado** del sistema entero (plano 04; lever
  dominante = FP-rate < e\*).
- **Conecta tres capacidades de proceso ya demostradas-en-pequeño** al flujo de producción: el router de
  meta-razonamiento (elegir CÓMO razonar por tipo, anclado a un examinador no circular), el engine de
  hipótesis (generar/clasificar afirmaciones falsables con DoD enforzado en código) y la abstención
  calibrada (saber cuándo NO sé).
- **Decide la frontera internalización ↔ herramienta:** qué de estas capacidades vive como **peso/comportamiento
  del modelo entrenado** y qué vive como **andamiaje externo** que el modelo invoca. Es la decisión de
  diseño central del plano (§3.6).

### 1.2 Qué NO cubre (se delega)
- **El verificador real-chequeable en sí** (`verify()`, FP-rate, sandbox de código, forma cerrada,
  hechos) → **plano 04** (`04_verificador.md`). Aquí se **consume** su interfaz `VerifyResult`, no se
  reimplementa.
- **El lazo STaR de auto-mejora** que entrena el sustrato con las salidas verificadas (imitación,
  dedup+replay como política de entrenamiento) → **plano 05** (`05_lazo_automejora.md`). Aquí se define
  cómo el razonador *produce* trazas verificadas; **entrenar con ellas** es del plano 05.
- **El director de expertos / jerarquía de adapters LoRA por dominio** → plano de expertos. Aquí solo se
  asume su contrato `ExpertTask`/`ExpertResult` (de `01_arquitectura_sistema.md §3.2`).
- **El router de 3 bandas + pizarra + RAG doc-level** → plano de memoria/contexto. Aquí la pizarra se usa
  como **canal**, no se especifica su sustrato.
- **El backbone híbrido** que ejecuta ambos núcleos → plano 02.

> **Honestidad sobre la numeración.** En disco hoy existen `00`–`07`. El mapa de `01_arquitectura_sistema.md
> §3.7` propone otra numeración (donde "09" era solo hipótesis+autoeval). Este plano **agrupa** núcleos +
> planificador/verificador + meta-razonamiento + hipótesis + autoeval por pedido explícito; **solapa** con
> lo que ese mapa asignaba a "05" y "09". Cuando se consolide la numeración, este archivo y ese mapa son
> las dos fuentes a reconciliar. No hay doble implementación: este plano define **interfaces y orquestación**;
> los módulos concretos (verificador, lazo, director) los implementan sus planos.

### 1.3 Alcance honesto (PROBADO / ASUMIDO / PENDIENTE)
- **PROBADO-PEQUEÑO (corre hoy, leído):** el router de meta-razonamiento (CYCLE 12-21, `reason/`) y el
  engine de hipótesis (CYCLE 22, `research/`). Son **solvers/registros deterministas en CPU+stdlib (+torch
  para la cabeza supervisada del CYCLE 21)**; demuestran el **MECANISMO**, no son un claim sobre LLMs
  reales ni sobre escala (`reason/README.md` §Honestidad).
- **ASUMIDO (confianza media):** que estos mecanismos transfieren de "5 cadenas sobre aritmética de juguete"
  a "estrategias de razonamiento sobre un LLM chico real con un verificador ejecutable". El propio
  `reason/README.md §Frontier` lista esto como pendiente ("envolver el LM real, no solvers de juguete").
- **PENDIENTE (no demostrado ni en pequeño):** la **separación física en dos núcleos** (el arco v4 trabajó
  el razonador **sin acoplarlo al lenguaje**; `ARQUITECTURA_OBJETIVO.md` Apéndice A fila 1, `00_READINESS.md
  §5.5`). La **internalización** de las capacidades de proceso dentro de los pesos (vs herramienta externa)
  es **conjetura de diseño**, sin exp propio. SCALE = 0%.

---

## 2. Estado de partida (qué existe y corre hoy)

| Pieza | Existe | Corre | Cita (archivo real) | Resultado honesto |
|---|---|---|---|---|
| Router de meta-razonamiento (bandit contextual por tipo, anclado al verificador) | Sí | Sí | `reason/router.py` (`Router`) | CYCLE 12: `mode="verifier"` **1.000** vs mejor cadena fija 0.793; `mode="confidence"` (circular) **0.432** (held-out, `README.md`) |
| Anti-Goodhart (examinador no circular vs auto-confianza) | Sí | Sí | `router.py:train_one` (`reward = is_correct` vs `reward = conf`) | el fanfarrón `direct` (conf ~0.95) secuestra la política si se premia por confianza propia |
| "Preguntar bajo presupuesto" + "saber que no sé" (OOD) | Sí | Sí | `router.py:solve(ask_budget)`, `_is_unsure`, `solve_ood`, `_ood_unsure` | escala (pregunta) cuando las 2 mejores cadenas están empatadas o sin evidencia; pregunta MUCHO temprano, MENOS al aprender |
| Robustez a oráculo RUIDOSO (voto mayoritario + acumulación) | Sí | Sí | `router.py:solve_noisy`, `_noisy_oracle` | CYCLE 13: robust-aggregate **1.000** vs blind 0.56 @ruido 0.4 (`README.md`) |
| Composición de cadenas multi-paso (programa = secuencia) | Sí | Sí | `composer.py` (`Composer`, `run_program`, `enumerate_programs`) | CYCLE 14: cadena sola ~**0.196**; el composer descubre el programa → **1.000** |
| Competencia GRADUADA (rompe el techo perfecto; brecha honesta) | Sí | Sí | `chains.py:graded_chain`, `Router(graded=True)` | CYCLE 15: oráculo **~0.89 (<1.0)**, router ~0.76, brecha ~0.13 |
| Inferir la clase de problema desde el TEXTO (sin la etiqueta de tipo) | Sí | Sí | `text_router.py`, `lm_router.py`, `supervised_router.py` | CYCLE 21 (capstone): encoder **supervisado por el verificador** le gana al Naive-Bayes en TODOS los niveles de ruido |
| Encoder supervisado por el verificador (señal = `is_correct` sobre cadenas) | Sí | Sí | `supervised_router.py:chain_success_target`, `SupervisedLMRouter.fit` | la representación rica solo paga **una vez** que recibe la MISMA señal del verificador que el bag-of-words ya tenía |
| Engine de hipótesis: falsabilidad + DoD enforzado en código | Sí | Sí | `research/hypotheses.py` (`HypothesisRegistry`, `_check_dod`, `PrematureVerdictError`) | `mark_supported/refuted/mixta` **lanzan** si falta prediction/evidence_for/evidence_against/adversarial_verdict/experiment_ref |
| Clasificación de hipótesis (abierta/apoyada/refutada/mixta) | Sí | Sí | `research/schema.py:Hypothesis.status`, `hypotheses.py:mark_*` | append-only; un experimento refutado cierra con su lección, NUNCA se borra |
| Ledger de evidencia con tiers (la compuerta "nunca optimizar solo con opiniones") | Sí | Sí | `research/ledger.py` (`EvidenceLedger`, `OpinionOnlyError`), `schema.py:TIER_NAMES/OPINION_TIER` | una decisión importante se RECHAZA si solo cita fuentes grado-opinión (tier 6/sin ref/no obtenidas) |
| Auto-evaluación + abstención calibrada | Sí (toy) | Sí | CYCLE 46 (`exp032_abstention_noisy` / `research/store/cycle46_abstention_noisy`) | abstención calibrada **sube precisión** a costa de cobertura (referido en `04_verificador.md §3.5`) |
| **Separación física en dos núcleos** (razonador ↔ comunicador) | **No** | — | `ARQUITECTURA_OBJETIVO.md` §1; `00_READINESS.md §5.5` | PENDIENTE; el arco v4 trabajó solo el razonador, sin lenguaje |
| **Internalización** de proceso dentro de los pesos | **No** | — | Este plano §3.6 | conjetura de diseño, sin exp propio |

**Lectura honesta.** Las **capacidades de proceso ya existen como código que corre** (router de
meta-razonamiento + engine de hipótesis). Lo que falta es (a) **envolverlas para un LLM real** (hoy operan
sobre solvers de juguete y un examinador-oráculo), (b) **separar físicamente los dos núcleos**, y (c)
decidir/medir **cuánto se internaliza**. NO se parte de cero: se **adapta `reason/Router`** como política de
selección de estrategia y se **reusa `research/HypothesisRegistry`** tal cual (ya enforza el DoD).

### 2.1 Una lección de diseño ya aprendida (no repetirla)
El hilo conductor de TODO `reason/` es **anti-Goodhart** (`README.md §El hilo conductor`): si la política
aprende por su **propia confianza** (señal circular), el fanfarrón `chain_direct` (conf ~0.95 siempre,
acierte o no — `chains.py:BLUFFER_CONF`) **secuestra** la política y la accuracy se desploma (1.000 →
0.432, CYCLE 12). Es la misma lección que **H-SELF-2** (auto-mejora) aplicada a la *selección de
razonamiento*: **ninguna señal interna del modelo puede ser su propio juez**. **Implicación dura para este
plano:** el meta-razonador y la auto-evaluación de §3.5 deben anclar su recompensa al **verificador real
(plano 04)**, NUNCA a la log-prob/entropía/auto-confianza del propio modelo. Cualquier diseño que cierre el
lazo sobre la auto-confianza está refutado de antemano por el ledger.

---

## 3. Diseño detallado

### 3.0 El flujo cognitivo (dónde encaja cada pieza)

```
Query
  │
  ▼
┌──────────────────────┐   Plan (task_type, expert_route, budget_alloc, confidence)
│ PLANIFICADOR RÁPIDO  │──────────────────────────────────────────────┐
│ (barato, tolera error│                                               │
│  meta-router elige    │   ¿qué ESTRATEGIA de razonar? ◀── §3.3       │
│  CÓMO razonar)        │                                               ▼
└──────────────────────┘                              ┌────────────────────────────┐
        │                                             │ VERIFICADOR PROFUNDO (04)  │
        │  el meta-router corre la cadena/programa    │ verify(candidate)->         │
        ▼  y produce un CANDIDATO                      │   VerifyResult{ok,conf,     │
┌──────────────────────┐                              │   evidence,abstained}       │
│ NÚCLEO RAZONADOR     │  candidate ──────────────────▶│ (real-chequeable, NO opina) │
│ (motor de razon.)    │◀── VerifyResult ──────────────└────────────────────────────┘
│  - meta-router §3.3  │        │ approved / abstain / reject
│  - hipótesis §3.4    │        ▼
│  - autoeval §3.5     │   re-plan / retry / backtrack (presupuesto adaptativo)
└──────────────────────┘        │ (ok)
        │ ReasoningTrace{idea, chain, value_signal, checked=True}
        ▼   ◀── FRONTERA DE NÚCLEOS (solo cruza la idea verificada, NO el scratchpad)
┌──────────────────────┐
│ NÚCLEO COMUNICADOR   │   Response{text, style, citations}
│ (motor de comunic.)  │──────────────────────────────────────────────▶ Usuario
│  expresa, NO razona  │
└──────────────────────┘
```

Las cajas `PLANIFICADOR` y `VERIFICADOR` y `DIRECTOR` son **compartidas** con `01_arquitectura_sistema.md`
(mismos contratos `Plan`/`VerifiedPlan`/`ExpertTask`). Este plano detalla el **interior cognitivo**: cómo el
razonador elige estrategia, genera hipótesis, se auto-evalúa, y **qué cruza la frontera al comunicador**.

### 3.1 La separación de los dos núcleos — la interfaz (PENDIENTE, se diseña aquí)

**Principio (`ARQUITECTURA_OBJETIVO.md` §1):** el razonador resuelve/planifica/coordina/evalúa/detecta
errores; el comunicador genera lenguaje/adapta estilo/traduce/interactúa. **La arquitectura no asume que
razonar y hablar son la misma tarea.**

**Lo único que cruza la frontera** es un `ReasoningTrace` **verificado y mínimo** (contrato de
`01_arquitectura_sistema.md §3.2`, anclado aquí):

```python
# Frontera razonador -> comunicador. PLANO: dict serializable, sin acoplar estados internos.
ReasoningTrace = {
    "idea": str,            # la conclusión/solución YA verificada (no el scratchpad entero)
    "chain": str,           # qué estrategia meta-razonadora se usó (auditoría, no se re-ejecuta)
    "value_signal": float,  # R-VALOR como BRÚJULA (asignación/abstención), NO acelerador (00_READINESS §5.2)
    "checked": bool,        # True sii pasó el verificador profundo (plano 04). Si False -> ver abstención §3.5
    "evidence": [str],      # IDs de trazas reales del verificador (para citations del comunicador)
    "hypotheses": [str],    # IDs en el HypothesisRegistry (§3.4), si la idea es exploratoria
}
# El comunicador produce:
Response = {"text": str, "style": str, "citations": [str]}   # cita evidence/hypotheses, NO inventa
```

**Reglas duras de la frontera (anti-acoplamiento, de `01 §3.2`):**
1. El comunicador **nunca lee el scratchpad/pizarra del razonador** ni su estado interno. Solo ve
   `ReasoningTrace`. Esto encarna "comunicación basada en necesidad" + "cero contexto innecesario".
2. El comunicador **NO razona**: no recalcula, no decide, no verifica. Si `checked=False`, **no debe
   afirmar la idea como cierta** — debe expresar la abstención (§3.5) en lenguaje ("no estoy seguro, pero…").
   Un comunicador que "rellena" una idea no verificada reintroduce el reward-hacking por la puerta del
   lenguaje (R-COMM-1, §6).
3. `citations` se construye **solo** desde `evidence`/`hypotheses` (trazas reales del verificador / IDs del
   registro). El comunicador no fabrica citas.

**Cómo se realiza en el v1 (mapeo a sustrato, `01 §3.6`):** ambos núcleos corren sobre el **mismo backbone
híbrido** (plano 02). Tres realizaciones, conservadora → radical:

| Realización | Cómo | Coste | Evidencia / riesgo |
|---|---|---|---|
| **Conservadora (v1 default)** | **Dos modos de decodificación** del MISMO `HybridLM`: razonar = decodificación interna con verificación (cadenas/programas); comunicar = decodificación de superficie estilizada condicionada a `ReasoningTrace`. | 0 params extra | Sin separación física; el riesgo es que el modo-comunicar "se filtre" al razonar. Confianza media. |
| **Moderada** | **Dos adapters LoRA** (r≤16) sobre el mismo base congelado: `razonador` vs `comunicador`, entrenables/fusionables por separado (compatible con FedAvg-sobre-LoRA, restricción dura). | +~1-3% params/adapter | Separación lógica real, reversible. Permite re-entrenar el comunicador sin tocar el razonador (modularidad `ARQUITECTURA_OBJETIVO.md §Escalabilidad`). |
| **Radical** | **Dos modelos distintos** (razonador chico que emite trazas estructuradas + comunicador que verbaliza). | 2× memoria | Máxima separación; costoso en el i3 (2c/4t, 11.8 GB). No para v1. |

**Decisión:** arrancar **conservadora** (un modelo, dos modos), subir a **moderada (dos adapters)** en
cuanto haya señal de filtración o cuando el comunicador necesite re-entrenarse independientemente.
**Confianza media** en que la separación física pague (sin exp propio; `01 §3.6`).

### 3.2 Planificador rápido + verificador profundo (el lazo plan → verify → re-plan)

**Planificador rápido (`ARQUITECTURA_OBJETIVO.md §Planificador Rápido`):** muy rápido, bajo costo,
**tolerante a errores**. Clasifica la tarea, elige estrategia de razonamiento inicial (vía el meta-router
§3.3) y los recursos/bandas previstos. Produce un `Plan` (contrato `01 §3.2`). NO intenta ser correcto —
intenta ser **barato y suficiente para arrancar**.

**Verificador profundo (`§Verificador Profundo`; implementado en plano 04):** analiza críticamente el
candidato. Detecta inconsistencias, expertos faltantes/innecesarios, corrige la planificación. Devuelve
`VerifyResult{ok, confidence, evidence, abstained}` (plano 04). **Su `ok` cuelga de una señal POSITIVA
chequeable** (tests que pasan / valor exacto / ≥2 fuentes), nunca de la ausencia de error.

**El lazo (concreto), anclado al meta-router de `reason/`:**

```python
def reason_step(query, planner, meta_router, verifier, budget):
    plan = planner.plan(query)                       # barato, tolera error
    # el meta-router elige la ESTRATEGIA (cadena/programa) por tipo de tarea (§3.3)
    strategy = meta_router.select(plan["task_type"])
    candidate = run_strategy(strategy, query)        # produce un candidato (idea + traza)
    vr = verifier.verify(to_candidate(candidate))    # VerifyResult (plano 04) — examinador REAL
    # APRENDIZAJE ONLINE del meta-router con la señal REAL (NUNCA con auto-confianza, §2.1):
    meta_router.update(plan["task_type"], strategy, 1.0 if vr.ok is True else 0.0)
    if vr.ok is True:
        return ReasoningTrace(idea=candidate.idea, chain=strategy, checked=True,
                              value_signal=value_brujula(candidate), evidence=vr.evidence)
    if vr.abstained:                                 # el verificador NO sabe -> abstención (§3.5)
        return abstain_trace(candidate, vr)
    # rechazo: re-planificar / retry / backtrack bajo presupuesto ADAPTATIVO
    if budget.left() > 0:
        return reason_step(replan(query, vr), planner, meta_router, verifier, budget.spend())
    return abstain_trace(candidate, vr)              # se agotó el presupuesto -> abstener, no inventar
```

**Por qué este lazo y no otro (evidencia del arco v4, vía `04`/`05` y Apéndice A):**
- **El verificador es el cuello.** `00_READINESS.md` y `04_verificador.md` lo declaran: el lever dominante
  del sistema es el **FP-rate** del verificador; toda la orquestación rinde de forma **compuesta solo si el
  paso base es preciso**. Este lazo **no compensa** un verificador malo — lo **respeta**.
- **Presupuesto adaptativo por paso** (no fijo): el lab midió (CYCLE 45) que un presupuesto **adaptativo
  per-step** rescata cadenas largas (~4.1×) frente a uno uniforme; **retry/backtracking** (CYCLE 47)
  recupera cobertura; **verificación de PROCESO** (CYCLE 44) frena el *compounding* de errores en multi-paso.
  Estos son hallazgos **demostrados-pequeño** (toy); el lazo los hereda como estructura, **confianza media**.
- **El meta-router aprende online de la señal real** (`router.py:train_one` con `mode="verifier"`): la
  política mejora dentro de la sesión sin tocar los pesos del modelo.

**Verificador que aparece DOS veces** (`01 §3.5`): una vez sobre el `Plan` (¿la planificación es coherente?)
y otra sobre el `candidate` (¿la solución es correcta?). Misma maquinaria `verify()`, distintos dominios.

### 3.3 El router de meta-razonamiento (YA EXISTE — cómo se envuelve para el sistema real)

**Qué es (corre hoy, `reason/router.py`):** un **bandit contextual sobre estrategias de razonamiento**,
indexado por **tipo de problema**. Aprende "qué forma de razonar funciona para qué clase de problema",
**generaliza** a tipos nuevos, **escala a preguntar bajo presupuesto**, **compone** cadenas multi-paso
(`composer.py`) e **infiere la clase desde el texto** (`supervised_router.py`). Todo decidido por un
**examinador que no se puede engañar con confianza propia** (anti-Goodhart).

**Mecánica real (leída del código):**
- `Router.select(ptype)` — ε-greedy (UCB opcional) sobre las cadenas de ese tipo: explora temprano,
  explota después. `stats[type][chain] = [correct, total]`.
- `Router.train_one(problem)` — elige cadena, la corre, **premia con `is_correct` (verificador real)** si
  `mode="verifier"`, o con la confianza auto-reportada si `mode="confidence"` (el modo **circular** que
  existe SOLO para demostrar que falla — CYCLE 12: 0.432).
- `Router.solve(problem, ask_budget)` — si está **dudoso** (`_is_unsure`: las 2 mejores cadenas empatadas o
  sin evidencia) y queda presupuesto, **pregunta al oráculo** una vez, elige la cadena confirmada, descuenta.
- `Router.solve_ood(...)` / `_ood_unsure` — "sabe que no sabe": en un tipo nuevo (0 obs) escala/pregunta en
  vez de adivinar confiado.
- `Composer` (`composer.py`) — el "brazo" es una **secuencia** de cadenas (un pequeño *programa de
  razonamiento*); `run_program` encadena intermedios (output del paso 1 = input del paso 2). Espacio chico y
  explorable (5 step-chains → 30 programas de longitud ≤2).
- `SupervisedLMRouter` (`supervised_router.py`) — rutea **desde el texto** del problema, con una cabeza MLP
  supervisada por `chain_success_target` (el target es `is_correct` sobre cada cadena — la realidad, NUNCA
  `problem["type"]`/`["answer"]`).

**Qué cambia al envolverlo para el sistema real (el trabajo de este plano):**

| Aspecto | Hoy (toy, `reason/`) | v1 (sistema real) | Confianza |
|---|---|---|---|
| Cadenas/estrategias | 5 solvers deterministas (`direct/stepwise/backwards/unit_rate/decision`) | estrategias de prompting/decodificación del LLM (CoT, descomposición, hacia-atrás, verificar-y-revisar) | media |
| Tipo de problema | etiqueta `problem["type"]` (4-7 tipos) | inferido del texto por el sustrato (como `SupervisedLMRouter`, ya demostrado CYCLE 21) | media |
| Verificador (la recompensa) | oráculo perfecto `is_correct` | `verify()` real-chequeable del plano 04 (ejecuta/calcula/corrobora) — **con FP-rate > 0** | **media-baja** |
| Soporte | en memoria, por sesión | persistido vía `PermanentRecord`/`db_pool` (sin `sqlite3.connect` directo) | alta |

**Riesgo clave del envoltorio (declarado):** el toy usa un **oráculo perfecto**; el sistema real usa un
verificador **con FP-rate > 0**. El router ya tiene defensa parcial (`solve_noisy`: voto mayoritario +
acumulación, robusto a ruido **independiente** — CYCLE 13), pero **NO** contra un FP **sistemático/sesgado**
(un verificador que se equivoca siempre igual enseña el error — `04 §6 R3`). Mitigación: heredar la guardia
del plano 05 y mantener `mode="verifier"` anclado al examinador real. **No resuelto a escala.**

### 3.4 El generador + clasificador de hipótesis (YA en código — cómo se conecta)

**Qué es (corre hoy, `research/hypotheses.py` + `research/ledger.py` + `research/schema.py`):** un registro
que **EXIGE en código** que una hipótesis sea falsable y pase un DoD antes de poder marcarse apoyada/refutada/
mixta. Es el "Sistema de Generación de Hipótesis" de `ARQUITECTURA_OBJETIVO.md §Generación de Hipótesis`
(observación → patrón → hipótesis → evaluación → priorización → verificación) ya instanciado como herramienta
del lab (CYCLE 22), con la **misma taxonomía** que pide la visión.

**Mecánica real (leída del código):**
- `Hypothesis` (`schema.py`): `{id, statement, prediction, status, confidence, evidence_for,
  evidence_against, adversarial_verdict, experiment_ref}`. `status ∈ {abierta, apoyada, refutada, mixta}`.
- `HypothesisRegistry.mark_supported/refuted/mixta` → `_check_dod` **lanza `PrematureVerdictError`** salvo
  que se cumpla **TODO**: `prediction` no vacía (falsable), `evidence_for ≥ 1`, **`evidence_against ≥ 1`
  (refutar-antes-de-aceptar)**, `adversarial_verdict` no vacío, `experiment_ref` no vacío (afirmación
  empírica = experimento CORRIDO, no opinión). Append-only: un refutado **nunca se borra**.
- `EvidenceLedger.record_decision` → **`OpinionOnlyError`** si una decisión importante solo cita fuentes
  grado-opinión (tier 6 / sin ref / no obtenidas). Tiers: `1 paper > 2 libro > 3 doc > 4 benchmark >
  5 dato_propio > 6 secundaria` (`schema.TIER_NAMES`).

**Mapeo a la taxonomía de la visión** (`ARQUITECTURA_OBJETIVO.md §Clasificación de hipótesis`):

| Visión | `status` en código | Compuerta |
|---|---|---|
| Confirmadas (evidencia suficiente) | `apoyada` | `_check_dod` completo + `adversarial_verdict` |
| Probables (parcial) | `confidence` ∈ {media} con `status='abierta'/'mixta'` | evidencia parcial registrada |
| Exploratorias (insuficiente) | `abierta`, `confidence='baja'` | sin DoD aún (no se puede marcar) |
| Descartadas (contradictorias) | `refutada` | `_check_dod` + lección registrada |

**Cómo se conecta al flujo cognitivo:**
- Cuando el razonador produce una **idea nueva no verificable de un tiro** (no es código/forma-cerrada/hecho
  corroborable), **no la afirma**: la **registra como hipótesis exploratoria** (`HypothesisRegistry.add`,
  `status='abierta'`) y devuelve su ID en `ReasoningTrace.hypotheses`. El comunicador la expresa como
  *hipótesis*, no como hecho (§3.1 regla 2).
- El **lazo de auto-mejora** (plano 05) y el **director** consumen el registro: una hipótesis solo asciende a
  `apoyada` cuando un **experimento corrido** + crítica adversaria lo justifican. Esto traslada el método
  epistémico del lab (que ya gobierna 155 ciclos) **al runtime del modelo**.
- El `IntegratedResult.hypotheses` (`01 §3.2`) son **IDs de este registro** — el integrador no inventa, apunta.

**Por qué esto importa para anti-Goodhart:** el registro **estructuralmente impide** "aceptar una idea por
gusto" (la compuerta lanza). Es el mismo principio que el verificador no circular, pero sobre **afirmaciones
nuevas**: refutar-antes-de-aceptar en código.

### 3.5 Auto-evaluación + abstención calibrada (CYCLE 46 — "saber cuándo no sé")

**Qué es:** la capacidad de estimar la **calidad de la propia salida** y **abstenerse** cuando no alcanza el
umbral, en vez de afirmar con confianza falsa. Demostrado-pequeño (CYCLE 46, `exp032_abstention_noisy`,
veredicto **H-V4-1k MIXTA**): la abstención calibrada **sube la precisión** a costa de cobertura
(falta backtracking para recuperar cobertura — caveat del ledger; referido en `04_verificador.md §3.5`,
`05_lazo_automejora.md`).

**Cómo se realiza (consume la calibración del plano 04):**
- El verificador devuelve `confidence` **calibrada** (`VerifyResult.confidence`, plano 04 §3.6). El razonador
  decide con un **umbral por dominio** τ: acepta si `confidence ≥ τ`; **abstiene** en la zona gris; rechaza
  bajo el piso. τ se fija para que el **FP-rate efectivo quede < e\*** (plano 04 §3.9), **no a ojo**.
- **Abstención como ciudadana de 1ª clase:** un dominio **sin verificador chequeable** abstiene
  (`ok=None`), **NO** inventa un proxy. Esto encarna la restricción dura *"nunca proxy auto-generado como
  fitness"*. El lazo (plano 05) trata `ok=None` como "no entrenar con esto" (ni positivo ni negativo).
- **La auto-evaluación NO usa la auto-confianza del LLM como juez** (§2.1). Usa la señal del verificador real
  + la calibración medida sobre un *gold* disjunto. La "auto" en auto-evaluación es **del sistema**, no del
  modelo juzgándose a sí mismo.

> **Matiz honesto del ledger (R-VALOR):** el arco downstream 149-155 cerró que el residuo del lazo **real**
> es **RANKING** (discriminación), **no calibración**. La tesis "la calibración paga en la decisión bajo
> escasez" (CYCLE 123) sigue **intacta pero NO confirmada en el lazo real** — sólida solo en toy/oráculo
> (`00_READINESS.md §5.2`). Por eso la abstención aquí se usa como **brújula decisional acotada** (umbral de
> aceptar/abstener), **no** como afirmación de que mejora el loss. **Confianza media.**

### 3.6 Internalización vs herramienta externa (el eje conceptual del plano)

**La pregunta:** ¿estas capacidades de proceso (elegir cómo razonar, generar/clasificar hipótesis,
auto-evaluarse) viven como **comportamiento aprendido en los pesos** del modelo, o como **andamiaje externo**
(código `reason/`+`research/`) que el modelo invoca?

**Respuesta de diseño (escalonada, honesta sobre lo que NO está probado):**

| Capacidad | Arranca como | Internalización propuesta | Por qué / evidencia | Confianza |
|---|---|---|---|---|
| **Verificación** (¿es correcto?) | **Herramienta externa SIEMPRE** | **NUNCA se internaliza** | "Código que corre o no cuenta": el verificador debe ser **ejecutable/chequeable**, no un juicio del modelo. Internalizarlo = auto-recompensa circular = la **rama CIRCULAR de H-SELF-2** (❌ refutada; H-SELF-2 sólo se sostiene **condicional ✅** con evaluador held-out NO-circular, CYCLE 8) + H-SELF-1 (✅ true: evaluador verificable > proxy auto-generado). | alta |
| **Selección de estrategia** (meta-router) | Herramienta externa (`reason/Router`, bandit online) | **Destilación**: una vez que el router aprende qué estrategia por tipo, se **entrena el modelo** (vía lazo 05) a **emitir esa estrategia por defecto** — el router se vuelve un *prior* en los pesos. | El lab probó que un encoder **supervisado por el verificador** internaliza la señal (CYCLE 21, `supervised_router.py`); la cabeza es el primer paso de internalización. | media |
| **Generación de hipótesis** | Andamiaje (`HypothesisRegistry` enforza el DoD) | **Parcial**: el modelo aprende a **proponer** hipótesis falsables (formato `prediction`+evidencia); el **registro/compuerta sigue externo** (el DoD no se delega a los pesos). | El registro garantiza falsabilidad **estructuralmente**; los pesos no pueden garantizar eso (un modelo puede "decir" que algo es falsable sin serlo). | media |
| **Auto-evaluación / abstención** | Calibración externa (plano 04 §3.6) sobre *gold* disjunto | **Parcial**: el modelo aprende a **emitir una señal de incertidumbre**; el **umbral τ y la calibración** se fijan/miden externamente. | El arco R-VALOR dice que la señal endógena es brújula, no juez (`00_READINESS §5.2`). La decisión final NO se internaliza. | media-baja |

**El principio que separa lo internalizable de lo no-internalizable:**
> **Lo que es VERIFICACIÓN (juzgar si algo es cierto/correcto) NUNCA se internaliza** — sería auto-recompensa
> circular (H-SELF-2). **Lo que es GENERACIÓN/PROPUESTA (qué estrategia probar, qué hipótesis plantear)
> SÍ se internaliza** vía destilación de las decisiones que el andamiaje externo + el verificador real ya
> validaron. El andamiaje **enseña** al modelo (lazo 05); el verificador **siempre** queda afuera como juez.

Esto es coherente con el **giro estratégico del lab (CYCLE 47)**: el lever no es más routing/andamiaje, sino
**mejor sustrato + verificador**. La internalización es exactamente "convertir andamiaje validado en mejor
sustrato", con el verificador siempre como compuerta externa no circular.

**Mecanismo concreto de internalización (vía plano 05, no aquí):** las trazas `ReasoningTrace{checked=True}`
que el meta-router produce y el verificador aprueba se vuelven **datos de imitación** (STaR) para entrenar el
backbone a **emitir la estrategia ganadora por defecto**. **Imitación (STaR), NO RL** — pero con
honestidad sobre la evidencia del ledger: in-lab **NI** el verificador débil se hackeó (CYCLE 32 /
`exp019_reward_hack`, **H-LEARN-4 REFUTADA**) **NI** se demostró que RL hackee más que la imitación
(CYCLE 33 / `exp020_rl_vs_imitation`, **H-LEARN-5 REFUTADA**, *null de MÉTODO*: GRPO-lite a escala tiny
es inestable / colapsa el modelo, rl_weak 0.059 ≈ imit 0.115). El mecanismo "RL más hack-prone que
imitación" se apoya **sólo en literatura (Amodei)** + la asimetría estructural; la elección
imitación-sobre-RL la refuerza, además, que el RL **colapsó** el modelo tiny en el lab (razón práctica
extra para no usar RL en CPU). El entrenamiento grande va a **Kaggle GPU** (i3 bloqueado; `00_READINESS §5.1`).

### 3.7 Configuración concreta (sin constantes mágicas dispersas)

Ubicación propuesta: `cognia_x/reasoncore/config.py` (un módulo auditado, análogo a `verify/config.py`).
Valores iniciales **confianza media**, a re-medir (§5):

```python
# meta-router (envoltorio de reason/Router para el sistema real)
META_EPS            = 0.1     # ε-greedy (= reason/Router default)
META_UNSURE_MARGIN  = 0.05    # _is_unsure: 2 mejores estrategias dentro de este margen -> dudoso
META_UCB_C          = 0.0     # UCB off por default (= toy); subir si la exploración es cara
ASK_BUDGET          = 2       # cuántas veces puede "preguntar al verificador" por consulta dudosa
# lazo plan->verify->replan
MAX_REPLAN_STEPS    = 3       # retry/backtrack bajo presupuesto (CYCLE 47, adaptativo)
PROCESS_VERIFY      = True    # verificar el PROCESO, no solo el resultado final (CYCLE 44)
# abstención (consume calibración del plano 04)
TAU_ABSTAIN         = {"code": 0.80, "closed_form": 0.99, "fact": 0.75}  # = verify/config (calibrar §5)
# separación de núcleos
NUCLEI_MODE         = "single_model_two_modes"   # conservadora; -> "two_lora_adapters" si filtra
```

---

## 4. Decisiones y alternativas

| # | Decisión | Conservadora | Moderada (elegida) | Radical | Evidencia |
|---|---|---|---|---|---|
| D1 | Separación de núcleos | Un modelo, **dos modos de decodificación** | (default v1) — subir a **dos adapters LoRA** si hay filtración | Dos modelos distintos | `01 §3.6`; sin exp propio (confianza media). Adapters son reversibles + FedAvg-compatibles. |
| D2 | Recompensa del meta-router | — | **Verificador real** (`mode="verifier"`) | Auto-confianza del modelo | CYCLE 12: confianza propia **secuestra** la política (1.000→0.432). Circular = refutado (§2.1). |
| D3 | Internalizar la **verificación** | — | **NO internalizar (siempre externa)** | Verificador en los pesos | H-SELF-2: evaluar sobre lo que uno auto-escribe es el fallo. "Código que corre o no cuenta". |
| D4 | Internalizar la **selección de estrategia** | Mantener andamiaje externo siempre | **Destilar el router a un prior en los pesos** (vía lazo 05, imitación) | RL online con la señal | CYCLE 21 (encoder supervisado internaliza la señal — sólido). El contrapunto "RL hackea, imitación no" **NO está demostrado in-lab**: CYCLE 32/33 (exp019/exp020, H-LEARN-4/5) **REFUTADAS** (null de método, GRPO-lite tiny inestable); apoyo **sólo de literatura (Amodei)** + RL colapsa en CPU. |
| D5 | Idea no verificable de un tiro | Afirmarla con baja confianza | **Registrarla como hipótesis exploratoria** (DoD enforzado) | Descartarla | `research/hypotheses.py` ya enforza falsabilidad; no afirmar lo no-verificado (§3.1 regla 2). |
| D6 | Qué cruza al comunicador | Todo el scratchpad | **Solo `ReasoningTrace` mínimo verificado** | Solo la respuesta final sin trazas | "Comunicación por necesidad" (`ARQUITECTURA_OBJETIVO.md`); citations necesita `evidence`. |
| D7 | Presupuesto de re-planificación | Fijo por consulta | **Adaptativo per-step + retry/backtrack** | Ilimitado hasta resolver | CYCLE 45 (adaptativo 4.1×), CYCLE 47 (retry recupera cobertura). Toy, confianza media. |

**Por qué D3+D4 son la columna vertebral conceptual:** la frontera "verificación afuera, generación
adentro" es lo que hace el sistema **honesto y no circular**. Si se internalizara la verificación, el modelo
se volvería su propio juez (colapso). Si NUNCA se internalizara la generación, el andamiaje externo sería un
techo permanente (el modelo no mejoraría su *prior* de razonamiento). La combinación elegida deja que el
modelo **mejore su forma de razonar** mientras un juez externo **siempre incorruptible** lo mantiene anclado.

---

## 5. Plan de validación (cómo se mide que funciona, CPU vs Kaggle)

El DoD es **un razonamiento multi-paso verificado end-to-end con comunicación desacoplada**. El plan lo mide
por capas, barato → caro, todo en CPU salvo el entrenamiento de internalización.

### 5.1 Validación de los componentes que YA corren (regresión, CPU)
- **A-RC1 (meta-router):** correr `reason/run_cycle12..21` con `venv312` y **reproducir los números del
  ledger** (`README.md`): verifier **1.000** vs mejor-fija 0.793 vs circular 0.432 (CYCLE 12); composer
  ~0.196→1.000 (CYCLE 14); oráculo graded ~0.89 / router ~0.76 (CYCLE 15); E>NB en todos los niveles (CYCLE
  21). **CHECK:** los summary.json (`cognia_x/runs/cycleNN/`) coinciden. `pytest cognia_x/tests/ -k reason -q`
  (~21 passed).
- **A-RC2 (engine de hipótesis):** test que `mark_supported/refuted/mixta` **lanzan `PrematureVerdictError`**
  sin el DoD completo y **pasan** con él; que `EvidenceLedger.record_decision` **lanza `OpinionOnlyError`**
  con solo fuentes tier 6. **CHECK:** comportamiento de compuerta verificado (no solo que importa el módulo).

### 5.2 Validación del envoltorio nuevo (sistema real chico, CPU)
- **A-RC3 (meta-router sobre un LLM chico real):** reemplazar los 5 solvers de juguete por estrategias de
  decodificación de un GGUF chico (0.5B local) y el oráculo perfecto por `verify()` real (plano 04, dominio
  forma-cerrada/código). **CHECK:** el router con `mode="verifier"` supera a la mejor estrategia fija en
  held-out; el `mode="confidence"` colapsa (replica anti-Goodhart en el LM real). Esto cierra el `Frontier`
  de `reason/README.md`.
- **A-RC4 (lazo plan→verify→replan):** una tarea multi-paso (p.ej. problema compuesto tipo `afford_packs`)
  resuelta por `Composer` + `verify()` real, con presupuesto adaptativo y retry. **CHECK:** el lazo recupera
  cobertura con retry vs sin retry (replica CYCLE 47 con verificador real).

### 5.3 Validación de la separación de núcleos (end-to-end, CPU)
- **A-RC5 (DoD):** una consulta entra → planificador → meta-router elige estrategia → candidato → `verify()`
  aprueba → `ReasoningTrace{checked=True}` cruza la frontera → comunicador produce `Response` con
  `citations` derivadas de `evidence`. **CHECK explícito (output real):** (a) la `Response` **cita** la
  evidencia del verificador; (b) ante un candidato **no verificado** (`checked=False`), el comunicador
  expresa **abstención** ("no estoy seguro…"), NO afirma; (c) el comunicador **no** accedió al scratchpad
  (auditar que solo recibió `ReasoningTrace`).
- **A-RC6 (filtración de núcleos):** test adversarial — un razonamiento incorrecto-pero-fluido NO debe salir
  como afirmación correcta por el comunicador. **CHECK:** `checked` gobierna el modo del comunicador.

### 5.4 Validación de la internalización (Kaggle GPU)
- **A-RC7 (destilación del router):** entrenar (imitación/STaR, plano 05) el backbone con trazas
  `checked=True` y medir si **emite la estrategia ganadora por defecto** sin el bandit online. **CHECK:** la
  accuracy held-out con router-internalizado ≥ router-externo, **sin** reward-hacking (se usa
  **imitación/STaR, NO RL**; el contrapunto "RL hackea más" **NO se demostró in-lab** — CYCLE 33 /
  `exp020`, H-LEARN-5 **REFUTADA**, null de método; se apoya en literatura, no en un exp del lab).
  **Esto va a Kaggle** (entrenamiento grande bloqueado en el i3, `00_READINESS §5.1`).

### 5.5 CPU vs Kaggle
- **CPU (i3):** todo el andamiaje (meta-router bandit, engine de hipótesis, lazo plan→verify→replan,
  abstención, comunicación) — son solvers/registros/parseo + un GGUF chico de inferencia. Sin GPU.
- **Kaggle GPU:** **solo** la internalización (A-RC7), porque entrena pesos. El verificador y el andamiaje
  **no entrenan nada** y quedan en CPU.

---

## 6. Lo que NO está probado / riesgos

| # | Riesgo | Severidad | Estado | Mitigación |
|---|---|---|---|---|
| R-RC1 | **Transferencia toy→real del meta-router.** `reason/` opera sobre 5 solvers deterministas + oráculo perfecto; el sistema real son estrategias de un LLM + verificador con FP>0. | Alta | **ASUMIDO** | A-RC3/A-RC4 lo miden antes de comprometer. El `Frontier` del README ya lo declara pendiente. |
| R-RC2 | **Separación física de núcleos sin exp propio.** Que dos modos/adapters paguen vs un modelo único es conjetura. | Media | **PENDIENTE** | Arrancar conservadora (un modelo); A-RC6 detecta filtración; subir a adapters solo con señal. |
| R-RC3 | **Internalización del juicio por error.** Si la destilación arrastra la verificación a los pesos, el modelo se vuelve su propio juez (H-SELF-2). | Alta | Inherente | D3: la verificación **NUNCA** se internaliza; el verificador externo es la compuerta. Test de no-circularidad. |
| R-RC4 | **Verificador sesgado enseña el error al meta-router.** El router es robusto a ruido independiente (`solve_noisy`) pero NO a FP sistemático. | Alta | Heredado (`04 §6 R3`) | FP-rate medido/monitoreado (plano 04); guardia dedup+replay (plano 05); `mode="verifier"` anclado al examinador real. |
| R-RC5 | **El comunicador "rellena" una idea no verificada** y la afirma como cierta (reward-hack por el lenguaje). | Alta | Mitigado por diseño | §3.1 regla 2 + `checked` gobierna el modo; A-RC6 lo testea adversarialmente. |
| R-RC6 | **R-VALOR como acelerador (sobre-apoyo).** Usar `value_signal` para más que asignación/abstención. | Media | Acotado | Solo brújula decisional; el arco 149-155 cerró que el residuo real es ranking, no calibración (`00_READINESS §5.2`). |
| R-RC7 | **Andamiaje que no internaliza = techo permanente.** Si la destilación (A-RC7) no transfiere, el sistema queda atado al bandit externo. | Media | **ASUMIDO** (Kaggle) | A-RC7 lo mide; si falla, el andamiaje externo es un fallback funcional (no bloquea el v1, solo el "mejor sustrato"). |
| R-RC8 | **Solapamiento de planos** (este 09 vs el "05/09" de `01 §3.7`). Riesgo de doble implementación. | Baja | Conocido | Este plano define **interfaces/orquestación**; los módulos los implementan 04/05/06. Reconciliar numeración. |
| R-RC9 | **SCALE = 0%.** Todo está en juguete + GGUF chico; el comportamiento a 1-3B reales es la mayor incógnita. | Alta | Hardware-bloqueado | Honestidad explícita; M0 + telemetría; entrenos a Kaggle. No esconder el caveat. |
| R-RC10 | **La elección imitación-sobre-RL (D4) NO tiene exp propio que la respalde.** Las dos pruebas in-lab del reward-hack de RL — `exp019`/`exp020` (H-LEARN-4/5) — están **REFUTADAS** (null de método: GRPO-lite tiny inestable/colapsa); el mecanismo "RL más hack-prone" se apoya **sólo en literatura (Amodei)**. | Media | **ASUMIDO (literatura)** | Usar imitación/STaR por defecto (también porque RL colapsa el modelo tiny en CPU); no citar exp019/020 como APOYO; demostrar el contrapunto requeriría RL estabilizado (KL/on-policy) o más escala. |

---

## 7. Definición de Hecho (DoD) + dependencias + riesgos de cierre

### 7.1 DoD verificable
- [ ] **Razonamiento multi-paso verificado end-to-end con comunicación desacoplada (A-RC5):** una consulta
      atraviesa planificador → meta-router → candidato → `verify()` real → `ReasoningTrace{checked=True}` →
      comunicador → `Response` con `citations` derivadas de `evidence`. **Output real mostrado**, con CHECK
      explícito de los tres puntos (cita evidencia / abstiene si no verificado / comunicador no vio el
      scratchpad).
- [ ] **Meta-router envuelto para LLM real (A-RC3):** `reason/Router` opera con estrategias de un GGUF chico
      y `verify()` real; `mode="verifier"` supera a la mejor estrategia fija y `mode="confidence"` colapsa
      (anti-Goodhart replicado en el LM real). Cierra el `Frontier` del `reason/README.md`.
- [ ] **Lazo plan→verify→replan (A-RC4):** retry/backtrack bajo presupuesto adaptativo recupera cobertura vs
      sin retry, con verificador real.
- [ ] **Engine de hipótesis conectado:** una idea no verificable se **registra** (`HypothesisRegistry.add`,
      `status='abierta'`) y su ID viaja en `ReasoningTrace.hypotheses`; el comunicador la expresa como
      hipótesis. Compuertas `PrematureVerdictError`/`OpinionOnlyError` verificadas (A-RC2).
- [ ] **Abstención calibrada operativa:** τ por dominio consume `VerifyResult.confidence` (plano 04);
      dominio sin verificador → `ok=None` (abstiene, no inventa proxy).
- [ ] **Separación de núcleos (conservadora):** `NUCLEI_MODE="single_model_two_modes"` implementado; A-RC6
      (no-filtración) verde; ruta a `two_lora_adapters` documentada.
- [ ] **Frontera internalización ↔ herramienta documentada y testeada:** D3 (verificación nunca interna) con
      test de no-circularidad; D4 (selección destilable) con A-RC7 como medición (Kaggle), o su fallback.
- [ ] Tests de regresión por capacidad (meta-router, hipótesis, frontera de núcleos, abstención); suite
      dirigida verde (`venv312\Scripts\python.exe -m pytest cognia_x/tests/ -k "reason or hypoth" -q`).
- [ ] Entrada en `MANAGER_LOG.md` + commit enfocado (qué/por qué/cómo se verificó).

### 7.2 Dependencias
- **Existentes (verificadas, leídas):** `cognia_x/reason/` (router/composer/supervised_router/chains/
  problems), `cognia_x/research/` (hypotheses/ledger/schema/record), `venv312` (Python 3.12), GGUF chico
  local (0.5B Q4_K_M) + `node/llama-server.exe` (b9391) para A-RC3/A-RC4.
- **De otros planos (bloqueantes en orden Apéndice A):** **plano 04** (`verify()` real con FP-rate medido <
  e\*) — **debe estar listo PRIMERO**; **plano 05** (lazo STaR para la internalización A-RC7); plano 02
  (backbone híbrido como sustrato de ambos núcleos); contratos `Plan`/`VerifiedPlan`/`ExpertTask`/`ExpertResult`
  de `01_arquitectura_sistema.md §3.2`.
- **Infra:** `PermanentRecord`/`journaled_append` (ya probado) para persistir el soporte del router y el
  registro de hipótesis; `db_pool.py` si existe (sin `sqlite3.connect` directo); Kaggle GPU para A-RC7.

### 7.3 Riesgos de cierre (resumen ejecutivo honesto)
El **meta-router** y el **engine de hipótesis** son **código que ya corre** y tienen respaldo experimental
directo (CYCLE 12-21, CYCLE 22) — **confianza alta en el mecanismo, media en la transferencia a un LLM real**.
La **separación física en dos núcleos** y la **internalización de proceso** son **PENDIENTES sin exp propio**
(confianza media-baja): se diseñan aquí como interfaz + plan de medición, no como hecho. El eje conceptual
—**verificación siempre externa (no circular), generación destilable a los pesos**— es **defendible por el
ledger** en su mitad sólida (H-SELF-1 ✅ + rama circular de H-SELF-2 + el giro estratégico CYCLE 47 +
internalización de la señal CYCLE 21), pero la mitad "imitación-NO-RL" se apoya **sólo en literatura** (los
exp in-lab del reward-hack de RL, `exp019`/`exp020` H-LEARN-4/5, están **REFUTADOS** — null de método; R-RC10);
y **nada está medido a escala**. El DoD central (razonamiento multi-paso
verificado con comunicación desacoplada) es **construible sobre lo que corre hoy en CPU**; la pieza que exige
Kaggle (internalización A-RC7) es **mejora de sustrato, no requisito del v1 mínimo**. No comprometer la
orquestación cognitiva antes de que el **verificador (plano 04) tenga FP-rate medido < e\*** — esa es la
regla anti-Goodhart de la dependencia (`01 §3.8`).

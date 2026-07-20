# 08 — Expertos jerárquicos y coordinación (LoRA por dominio, selección por PLAN)

> **Propósito.** Especificar la **jerarquía de expertos** (N1 general / N2 sub / N3 micro) y el
> **aprendizaje de coordinación** de Cognia-X, construidos **DESPUÉS** del verificador (plano 04) y
> el lazo de auto-mejora (plano 05) — el orden que el lab probó que paga (Apéndice A de
> `ARQUITECTURA_OBJETIVO.md`). Decisiones duras de este plano: (1) los expertos **NO** son MoE
> token-por-token; son **adapters LoRA por dominio** sobre el backbone, **seleccionados por PLAN**
> (1 decisión por consulta, no por token); (2) la coordinación es una **política adaptativa
> no-regret** que estima la **fiabilidad del verificador sin ground-truth** (test-retest), anclada en
> evidencia propia (**CYCLE 43 / exp029**); (3) la **pizarra compartida** y la **comunicación por
> necesidad** son PENDIENTES — aquí se diseña su **interfaz**, no se reclama implementación. Y la
> **honestidad central**: el propio lab concluyó (**CYCLE 47, giro estratégico**) que **el routing
> NO es el cuello de botella** → esta fase tiene **menor prioridad** que verificador + lazo. DoD:
> **añadir/actualizar un experto sin reentrenar todo.**

> **Anclaje de fuentes (verificado HOY con Read/Grep, no asumido):**
> - Visión objetivo: `cognia_x/manager/ARQUITECTURA_OBJETIVO.md` (jerarquía N1/N2/N3 §"Sistema de
>   Expertos Jerárquicos"; "Selección por PLAN, no token-por-token" §"Selección de Expertos";
>   Planificador rápido + Verificador profundo; Comunicación basada en necesidad; Memoria temporal
>   compartida; Aprendizaje de coordinación; **Apéndice A** = mapa visión→evidencia del lab).
> - **Giro estratégico (HONESTIDAD central):** `cognia_x/manager/research_log.md` líneas 1409-1417 y
>   `cognia_x/manager/paper.md §CYCLE 47`: *"los 4 mecanismos (44-47) convergen al cuello de botella
>   del verificador/precisión-por-paso → el próximo lever es el SUSTRATO, no más orquestación."*
> - **Coordinación no-regret (PROBADO en pequeño):** `cognia_x/experiments/exp029_adaptive_allocation/`
>   (CYCLE 43, H-V4-1h **apoyada**; test `cognia_x/tests/test_cycle43_adaptive_allocation.py` 4/4). Fiabilidad
>   por **test-retest** `r=clip(2·P(coinciden)−1,0,1)`, peso `w_adapt=r·w_CONSEC_V+(1−r)·w_CONSEC_FREE`,
>   `worst_regret=+0.008`. Límite declarado: detecta ruido ALEATORIO, **no** sesgo sistemático.
> - **Meta-decisión de asignación aprendible (PROBADO):** `cognia_x/experiments/exp086_meta_allocation/`
>   (CYCLE 102, **apoyada**): un **bandit ε-greedy** sobre estrategias de asignación logra no-regret
>   (`regret vs oracle_selector ADD=0.006 / COV=0.006`); + `exp098_learn_aggregation` (CYCLE 113-114):
>   bandit sobre agregaciones inciertas, no-regret (gap 0.016) > hedge fijo (+0.039).
> - **Router de meta-razonamiento que YA EXISTE y corre:** `cognia_x/reason/router.py`
>   (`Router`, CYCLE 12 — bandit ε-greedy/UCB por TIPO, recompensa = **verificador real**, "preguntar
>   al oráculo bajo presupuesto" cuando `unsure_margin`), `cognia_x/reason/text_router.py`
>   (`TextRouter`, CYCLE 16 — bandit por `signature(text)`, sin ver la etiqueta de tipo),
>   `cognia_x/reason/supervised_router.py` (CYCLE 21 — encoder supervisado por el verificador).
> - **Expertos = adapters LoRA por dominio:** plano `06_aprendizaje_continuo.md` (LoRA r≤16, fusión
>   intra-cuenca, router de 3 bandas); `shattering/model_constants.py:DOMAIN_EXPERT_CLUSTERS`
>   (`logos`=0-4 / `techne`=5-9 / `rhetor`=10-15); `coordinator/federated_store.py` (`_RANK_MAX=8`,
>   `_KEYS=("k_A","k_B","v_A","v_B")`, `_HIDDEN_DIM=2048`, `MAX_BLOB_BYTES=512_000`,
>   `AGGREGATE_EVERY_N=5`); `cognia_v3/training/qlora_trainer.py`
>   (`target_modules=["q_proj","v_proj","k_proj","o_proj"]`); pipeline Kaggle
>   `cognia_v3/training/kaggle/train_qlora_kaggle.py`.
> - **Hot-swap de experto sin reentrenar (mecanismo del DoD):** `node/llama_backend.py:_lora_args()`
>   (env `LLAMA_LORA_PATH` → `["--lora", path]`; el binario b9391 pineado soporta `--lora`).
> - Sustrato v0 que corre: `cognia_x/model/hybrid.py` (`HybridLM`, verificado HOY, ver `00_READINESS §C4`).

---

## 1. Propósito y alcance

### 1.1 Qué resuelve
La visión del dueño (`ARQUITECTURA_OBJETIVO.md`) pide **escalar por especialistas**: una jerarquía
de expertos (N1 general → N2 sub → N3 micro) que un **director** selecciona y coordina **antes** de
generar, guiado por un **planificador rápido** y un **verificador profundo**, compartiendo hallazgos
por una **pizarra** y pidiendo contexto **por necesidad**. Este plano aterriza esa visión sobre lo que
el lab YA demostró, con tres compromisos de ingeniería duros:

1. **Expertos = adapters LoRA por dominio**, no sub-redes MoE entrenadas de cero. Razón: encaja con
   la restricción dura de FedAvg-sobre-LoRA, con `qlora_trainer.py` que ya existe, y permite
   **añadir/actualizar un experto sin reentrenar el backbone** (DoD).
2. **Selección por PLAN, no token-por-token** (`ARQUITECTURA_OBJETIVO §"Selección de Expertos"`): una
   decisión de routing por **consulta** (analizar objetivo → ruta de expertos → plan → aprobar →
   ejecutar), no una decisión por cada token como en MoE clásico. Razón medida-adyacente: el costo de
   decode en el i3 es **memory-bandwidth-bound** (exp004); multiplicar decisiones de routing por la
   longitud de salida no compra nada y sí gasta banda.
3. **Coordinación = política aprendida no-regret** que estima la fiabilidad del verificador sin
   ground-truth (CYCLE 43) y, un nivel arriba, **elige la estrategia de asignación** con un bandit
   (CYCLE 102). El sistema no solo aprende conocimiento: **aprende a coordinar** (`ARQUITECTURA §"Aprendizaje
   de Coordinación"`).

### 1.2 Qué NO cubre (se delega)
- El **verificador** (sandbox que ejecuta, FP-rate, gate, rollback) → **plano 04**. Aquí el verificador
  es una **dependencia bloqueante**: la política de coordinación lo CONSUME (estima su fiabilidad), no
  lo construye.
- El **lazo de auto-mejora STaR** que entrena/mejora los expertos desde salidas verificadas → **plano 05**.
- El **formato del adapter, su rango, la fusión intra-cuenca, el router de 3 bandas y la agregación
  federada correcta** → **plano 06** (este plano los REUSA; no los redefine).
- El **backbone** que ejecuta inferencia con el adapter cargado y la **representación** → planos **02**.
- El **planificador rápido** como subsistema completo (clasificación de tarea + presupuesto) → **plano 01**
  (arquitectura de sistema). Aquí se usa su **salida** (la ruta inicial de expertos) como entrada del
  director.

### 1.3 Alcance honesto (PROBADO / ASUMIDO / PENDIENTE)
- **PROBADO (propio, pequeño):**
  - La **política adaptativa no-regret** que mezcla señal verifier-dependiente y verifier-free pesando
    por la **fiabilidad estimada** del verificador (exp029/CYCLE 43, `worst_regret=+0.008`). Confianza
    **alta** en el patrón cualitativo; **media** en que transfiera a un verificador real-ejecutable y a
    multi-paso (la propia entrada lo marca: tarea de 1 paso, verificador sintético).
  - La **meta-decisión de asignación** es ella misma aprendible con un bandit no-regret (exp086/CYCLE 102,
    `regret≈0.006`; exp098/CYCLE 113-114, gap 0.016). Confianza **alta** en pequeño/toy.
  - Un **router de meta-razonamiento que corre** (CYCLE 12-21): bandit por tipo / por firma-de-texto /
    encoder supervisado-por-verificador. **Selecciona cadenas de razonamiento, NO expertos de dominio**
    — es el primitivo más cercano a un "director", reutilizable, **no** la jerarquía de dominios en sí.
- **ASUMIDO (literatura / razonamiento, sin exp propio):** que la jerarquía N1/N2/N3 de **dominios**
  (no de cadenas) paga sobre un único adapter plano; que la selección por plan iguala o supera a MoE
  token-por-token en CALIDAD (no solo costo) a la escala objetivo. Confianza **media-baja**.
- **PENDIENTE (no construido, ni en pequeño):** la **jerarquía de expertos como tal** (N1/N2/N3 de
  dominio), la **separación en dos núcleos** razonamiento↔comunicación, la **pizarra/memoria
  compartida**, la **comunicación por necesidad** director↔experto. SCALE = 0%. Aquí se diseña su
  **interfaz** y su plan de validación, marcándolo como **fase tardía**.

### 1.4 La verdad incómoda que este plano NO esconde (prioridad)
El lab concluyó en **CYCLE 47** (giro estratégico, `research_log.md:1409`, `paper.md §CYCLE 47`) que los
mecanismos de orquestación (proceso, presupuesto adaptativo, abstención, backtracking) **convergen todos
al mismo cuello: la precisión del paso base y la fiabilidad del verificador**. Conclusión literal: *"el
próximo lever es el SUSTRATO, no más orquestación"*. **Implicación para la prioridad de build:** la
jerarquía de expertos/routing es **fase tardía** — vale **poco** sobre un sustrato impreciso o un
verificador no confiable, y **rinde de forma compuesta** solo cuando esos dos están sólidos (Apéndice A,
"lección transversal"). Este plano se construye **después** de 04 y 05, y su justificación de existir es
**modularidad** (añadir dominios sin reentrenar), **no** un salto de capacidad por routing.

---

## 2. Estado de partida (qué existe y corre hoy)

| Pieza | Existe | Corre | Cita |
|---|---|---|---|
| Router meta-razonador por TIPO (bandit ε-greedy/UCB, reward=verificador, "preguntar bajo presupuesto") | Sí | Sí | `cognia_x/reason/router.py` (`Router`, CYCLE 12; `unsure_margin`, `ucb_c`) |
| Router desde el TEXTO (bandit por `signature(text)`, sin ver el tipo) | Sí | Sí | `cognia_x/reason/text_router.py` (`TextRouter`, CYCLE 16) |
| Encoder de ruteo **supervisado por el verificador** (representación rica > bag-of-words) | Sí | Sí | `cognia_x/reason/supervised_router.py` (CYCLE 21) |
| Política de coordinación **no-regret** (estima fiabilidad por test-retest, mezcla señales) | Sí (toy) | Sí | `cognia_x/experiments/exp029_adaptive_allocation/` (CYCLE 43) |
| Meta-selector de estrategia de asignación (bandit ε-greedy, no-regret) | Sí (toy) | Sí | `cognia_x/experiments/exp086_meta_allocation/` (CYCLE 102) |
| Clusters de dominio (semilla de la jerarquía N1) | Sí | — | `shattering/model_constants.py:DOMAIN_EXPERT_CLUSTERS` (logos/techne/rhetor) |
| Entrenador de adapters por dominio (LoRA/PEFT) | Sí | Sí (Kaggle) | `cognia_v3/training/qlora_trainer.py` + `kaggle/train_qlora_kaggle.py` |
| **Hot-swap de adapter en inferencia (sin reentrenar)** | Sí | Sí | `node/llama_backend.py:_lora_args()` (`LLAMA_LORA_PATH` → `--lora`) |
| Almacén/agregación federada de adapters | Sí | Sí | `coordinator/federated_store.py` (corrección de exactitud → plano 06) |
| Sustrato v0 que ejecuta | Sí | Sí | `cognia_x/model/hybrid.py` (`HybridLM`, ver `00_READINESS §C4`) |
| **Director de expertos (jerarquía N1/N2/N3 de DOMINIO)** | **No** | — | Diseño nuevo aquí (`cognia_x/experts/director.py`) |
| **Pizarra / memoria compartida** | **No** | — | Diseño de interfaz aquí (`cognia_x/experts/blackboard.py`) |
| **Comunicación por necesidad (experto↔director)** | **No** | — | Diseño de interfaz aquí (protocolo `need()`/`provide()`) |

**Lectura honesta.** No se parte de cero en **coordinación**: hay un router meta-razonador que corre y
una política no-regret demostrada en toy. Lo que falta es (a) **re-apuntar** ese routing de "cadenas de
razonamiento" a "**expertos de dominio** (adapters)"; (b) construir el **director jerárquico** N1/N2/N3;
(c) la **pizarra** y la **comunicación por necesidad** como subsistemas. Punto sutil de reuso: el
`Router` de CYCLE 12 ya implementa **exactamente** el patrón que el director necesita — bandit indexado
por contexto, premiado por el verificador real, con "preguntar al oráculo bajo presupuesto cuando estoy
dudoso". El trabajo es **cambiar el espacio de acciones** (cadenas → adapters) y **componer la jerarquía**,
no inventar el mecanismo.

---

## 3. Diseño detallado

### 3.1 Jerarquía de expertos N1 / N2 / N3 (sobre adapters, no sub-redes)

**Modelo de datos (concreto).** Un experto es un **registro** que apunta a un adapter LoRA y a su lugar
en el árbol. No es una red separada: es `(ruta_jerárquica, adapter_path, cuenca, metadatos)`.

```
# cognia_x/experts/registry.py  (nuevo)
@dataclass
class Expert:
    expert_id: str            # "ciencias.fisica.relatividad"  (ruta N1.N2.N3)
    level: int                # 1 (general) | 2 (sub) | 3 (micro)
    parent_id: str | None     # None en N1; "ciencias.fisica" para un N3
    domain_cluster: str       # "logos" | "techne" | "rhetor"  (DOMAIN_EXPERT_CLUSTERS)
    adapter_path: str | None  # GGUF/npz del adapter LoRA; None => hereda del padre
    rank: int                 # = _RANK_MAX (8) por defecto, techo r≤16  (coherencia federación)
    basin_id: str             # cuenca de pérdida (para fusión intra-cuenca segura, plano 06)
    enabled: bool
```

- **N1 — generales** (≈ `DOMAIN_EXPERT_CLUSTERS`): Matemáticas/Física/Programación… mapeados a las
  3 cuencas existentes `logos` (razonamiento, experts 0-4), `techne` (código/técnico, 5-9), `rhetor`
  (escritura, 10-15). Esto **ancla la jerarquía en una constante real**, no en una taxonomía inventada.
- **N2 — sub** (ej. Física → Mecánica/Relatividad/Cuántica): adapters más específicos **dentro de la
  cuenca del padre**. Si un N2 no tiene adapter propio (`adapter_path=None`), **hereda el del padre**
  (degradación elegante: nunca queda sin experto).
- **N3 — micro** (ej. Relatividad → Agujeros negros/Ondas gravitacionales): hoja del árbol; el caso
  común es **sin adapter propio** y heredando del N2 (los micro-expertos se crean solo si los datos lo
  justifican — ver §5, "añadir experto bajo demanda").

**Por qué adapters y no sub-redes MoE.** (1) Restricción dura: FedAvg solo sobre LoRA. (2) `qlora_trainer.py`
ya entrena adapters; un MoE de cero exige reentrenar el backbone (rompe el DoD). (3) Memoria: en el i3
(RAM 11.8 GB, base Q4 ~1.93 GB) **no caben** N sub-redes; sí caben N adapters de rango 8 (~MB cada uno),
**uno cargado a la vez** vía `--lora`. (4) **Honestidad:** esto NO es MoE — es *adapter-switching por
plan*. No hay sparsity de expertos en una sola pasada; hay **un experto activo por consulta**. Es una
elección de ingeniería forzada por el hardware, declarada como tal.

### 3.2 Selección por PLAN (no token-por-token) — el director de expertos

**Flujo (de `ARQUITECTURA §"Método propuesto"`), instanciado:**

```
consulta
  → planificador rápido (plano 01): clasifica tarea, propone RUTA inicial de expertos (N1→N2→N3)
  → verificador profundo (plano 04): critica el plan (¿faltan expertos? ¿sobran? ¿inconsistente?)
  → director (este plano): aprueba/ajusta la ruta, fija presupuesto, ELIGE el/los adapter(s)
  → ejecución: carga adapter (--lora) UNA vez, genera, escribe hallazgos en la pizarra (§3.5)
  → integrador (plano 01) → núcleo de comunicación (PENDIENTE) → respuesta
```

**El director (`cognia_x/experts/director.py`, nuevo) reusa el mecanismo del `Router` de CYCLE 12:**
un **bandit contextual** cuyo *contexto* es la **firma de la consulta** (reusando `signature(text)` de
`text_router.py`) y cuyas *acciones* son **rutas de expertos** (no cadenas). La recompensa es el
**verificador real** (plano 04) sobre el resultado — exactamente el `mode="verifier"` que `router.py`
ya distingue del `mode="confidence"` circular (Goodhart). Decisiones concretas:

- **Una decisión por consulta.** El director elige la ruta ANTES de generar; durante la generación el
  adapter no cambia (no token-por-token). Si el verificador rechaza el resultado, hay **retry con
  re-ruteo** (mecanismo de CYCLE 47/exp033, "backtracking"), no re-decisión por token. **Caveat
  honesto:** exp033 (H-V4-1l) tiene veredicto **MIXTA** — el retry/backtracking se cita aquí como
  *mecanismo* (no como resultado APOYADO); su pago real depende del verificador (CYCLE 47: el lever
  es el sustrato, no la orquestación).
- **Presupuesto y "preguntar bajo duda".** El `Router` ya implementa: si las dos mejores rutas tienen
  accuracy rastreada dentro de `unsure_margin` y queda presupuesto, **consulta al verificador UNA vez**
  para desempatar y descuenta presupuesto. La política buena pregunta **mucho temprano, menos con el
  tiempo** (a medida que aprende). Se REUSA tal cual, cambiando el espacio de acciones.
- **Jerarquía = ruteo en cascada.** N1 primero (cuenca), luego N2 dentro del padre, luego N3. Cada nivel
  es un bandit con su propio contexto. La cascada **poda** el espacio de acciones (no se evalúan todos
  los micro-expertos globalmente), respetando el costo.
- **Selección de adapter → `LLAMA_LORA_PATH`.** El director resuelve `expert_id → adapter_path` y arranca
  (o reconfigura) el backend con `--lora <path>` (`node/llama_backend.py:_lora_args()`). Esto es el
  **mecanismo físico** que hace cumplir el DoD: cambiar de experto = cambiar de adapter, **sin tocar el
  base**.

### 3.3 Aprendizaje de coordinación — política adaptativa no-regret (PROBADO, CYCLE 43)

Este es el núcleo **demostrado** del plano. El sistema debe **aprender a coordinar** estimando la
fiabilidad de sus propias señales **sin ground-truth**, y mezclándolas con garantía **no-regret** (lo
mejor de cada señal en todo el rango de ruido).

**El mecanismo (exp029 / CYCLE 43, H-V4-1h apoyada — `test_cycle43_adaptive_allocation.py` 4/4):**
- **Fiabilidad por TEST-RETEST (sin oráculo).** Se consulta al verificador **dos veces** por muestra del
  probe y se mide su **auto-acuerdo**: `r = clip(2·P(coinciden) − 1, 0, 1)`. Esto **NO depende de que el
  modelo acierte** (a diferencia del primer estimador probado, "acuerdo verificador-vs-consenso", que
  **falló** porque el modelo débil tiene mal consenso — lección honesta del ledger).
- **Mezcla pesada por fiabilidad.** `w_adapt = r · w_CONSEC_V + (1 − r) · w_CONSEC_FREE`. Cuando el
  verificador es fiable (`r→1`) se confía en él; cuando es ruidoso (`r→0`) se cae a la señal
  verifier-free. Curva medida (vnoise → `CONSEC_V / CONSEC_FREE / ADAPT(r)`):

  | vnoise | CONSEC_V | CONSEC_FREE | **ADAPT** | r_est |
  |---|---|---|---|---|
  | 0.0 | 0.690 | 0.621 | **0.688** | 1.00 |
  | 0.1 | 0.527 | 0.550 | **0.535** | 0.61 |
  | 0.2 | 0.415 | 0.415 | **0.437** | 0.39 |

  **No-regret medido:** `worst_regret = +0.008` (ADAPT nunca cae por debajo del mínimo de sus
  componentes); *keeps_edge* (≈ CONSEC_V con verificador limpio) y *escapes_collapse* (0.437 > 0.415 con
  ruido alto, hasta supera a las dos puras). `r` calibra **monótona** con el ruido.

**Cómo se instancia en el director:**
- La señal **verifier-dependiente** = el reward del verificador real (plano 04) sobre el resultado del
  experto elegido. La señal **verifier-free** = la confianza endógena / consistencia del propio experto
  (R-VALOR como **brújula acotada**, no como verdad — ver §6).
- El director **estima `r` por dominio** (cada cuenca/experto puede tener un verificador de fiabilidad
  distinta) y mezcla. Esto generaliza el test-retest de exp029 a **fiabilidad-por-experto**.

**Un nivel arriba — meta-selección de la estrategia de coordinación (exp086 / CYCLE 102, apoyada).**
Ninguna estrategia de asignación fija domina todos los regímenes. Un **bandit ε-greedy sobre estrategias**
(p.ej. {confiar-en-verificador, mezclar-adaptativo, abstener-y-preguntar}) **DESCUBRE la correcta del
feedback de outcomes** con no-regret (`regret vs oracle_selector ADD=0.006 / COV=0.006`). Es decir: la
**meta-decisión de cómo coordinar** es ella misma aprendible. Refrendado por `exp098_learn_aggregation`
(CYCLE 113-114): bajo agregación incierta, un bandit bate al hedge fijo (+0.039) y queda no-regret
(gap 0.016) — **cuando ningún default domina, aprende del feedback en vez de fijar un supuesto.**

**Mecanismo de corrección (de `ARQUITECTURA §"Mecanismo de Corrección"`).** Cuando una ruta resulta
incorrecta (verificador la rechaza): (1) detectar el fallo (reward<umbral); (2) penalizar esa ruta en el
bandit del nivel correspondiente; (3) ajustar el ruteo futuro (el bandit ya lo hace por construcción);
(4) registrar en el `EvidenceLedger`/pizarra. **No castigo simbólico: actualización de la política.**

### 3.4 El espacio de acciones es "ruta", no "token" — por qué importa en el i3

MoE token-por-token (`ARQUITECTURA §"Método tradicional"`) tiene 3 problemas declarados: alto costo,
decisiones repetitivas, duplicación de trabajo. En el i3 esto se agrava: el decode es
**memory-bandwidth-bound** (exp004 lo midió; ~1-2 FLOP/byte, satura a 2-3 hilos). Una decisión de routing
por token **no** reduce bytes movidos por token (la métrica maestra) y sí añade overhead. La selección
**por plan** mueve la decisión fuera del hot-path de decode: **1 clasificación + 1 carga de adapter por
consulta**, amortizada sobre toda la generación. **Confianza:** alta en la dirección (es aritmética de
banda); **media** en que la CALIDAD por-plan iguale a por-token a escala (no medido — ver §6).

### 3.5 Pizarra / memoria compartida (PENDIENTE — diseño de interfaz)

`ARQUITECTURA §"Memoria Temporal Compartida"`: una **pizarra** que NO contiene todo el contexto, solo
**hallazgos relevantes**, legible por otros expertos. Interfaz propuesta (no implementada aún):

```
# cognia_x/experts/blackboard.py  (interfaz; PENDIENTE)
class Blackboard:
    # Persistencia: SQLite vía storage/db_pool.py (regla: NUNCA sqlite3.connect directo).
    # Tabla findings(id, query_id, expert_id, kind, payload, embedding BLOB, ts, confidence)
    def write(query_id, expert_id, kind, payload, confidence) -> finding_id
    def read(query_id, kind=None, top_k=None) -> list[Finding]   # por relevancia (coseno) + recencia
    def summary(query_id) -> str                                  # bloque compacto para el integrador
```

- **Solo hallazgos, no contexto completo:** cada `write` es un resultado verificado o una hipótesis con
  su `confidence` (alineado con `HypothesisRegistry`: confirmada/probable/exploratoria/descartada).
- **Reuso real:** embeddings y coseno-en-RAM ya existen (`cognia_v3/memory/cognia_embedding.py`,
  `conversation_memory.py`) y el pool SQLite (`storage/db_pool.py`) — la pizarra es el **patrón doc-level
  del plano 06 aplicado a hallazgos intra-consulta**, no infra nueva.
- **Banda:** la pizarra existe **para ahorrar contexto** — un experto lee el `summary` (hallazgos
  relevantes) en vez de re-procesar todo. En el i3 esto es directamente menos bytes en prefill.
- **Estado honesto:** **PENDIENTE**. Sin exp propio. Riesgo de que la pizarra se vuelva un cuello de
  serialización si N expertos escriben mucho (ver §6).

### 3.6 Comunicación por necesidad (PENDIENTE — diseño de interfaz)

`ARQUITECTURA §"Comunicación Basada en Necesidad"`: el experto NO recibe todo el contexto; **pide** lo que
necesita. Protocolo propuesto (no implementado):

```
# protocolo director↔experto (PENDIENTE)
experto.need(query_id) -> NeedSpec(objetivo, restricciones, info_requerida)   # qué necesito saber
director.provide(need_spec) -> ContextBlock(solo lo pedido)                    # objetivo + restricciones + relevante
```

- **Beneficio (declarado en la visión):** menor consumo de memoria y contexto → en el i3, menos prefill.
- **Estado honesto:** **PENDIENTE**. Es la pieza menos demostrada; el diseño aquí fija la **interfaz**
  para que el plano de sistema (01) la pueda ensamblar, no reclama que funcione.

---

## 4. Decisiones y alternativas (con evidencia)

| Decisión | Conservadora | Moderada (recomendada v1) | Radical | Evidencia |
|---|---|---|---|---|
| **Forma del experto** | adapter LoRA único plano por cuenca (3: logos/techne/rhetor) | jerarquía N1 (3 cuencas) → N2 con herencia del padre | árbol N1/N2/N3 completo + micro-expertos bajo demanda | `DOMAIN_EXPERT_CLUSTERS`; plano 06; MoE descartado por RAM del i3 |
| **Granularidad de selección** | una sola decisión por consulta (1 adapter) | por plan + retry/re-ruteo si el verificador rechaza | por sub-tarea dentro del plan (multi-experto secuencial) | exp004 (decode banda-bound); CYCLE 47/exp033 (retry, veredicto **MIXTA** — mecanismo, no resultado APOYADO) |
| **Coordinación** | confiar siempre en el verificador (`CONSEC_V`) | **mezcla adaptativa por fiabilidad test-retest** (exp029) | + bandit que elige la estrategia de coordinación (exp086) | **exp029/CYCLE 43** (`worst_regret +0.008`); exp086/CYCLE 102; exp098/CYCLE 113-114 |
| **Estimar fiabilidad** | fija (asumir verificador perfecto) | **test-retest** `r=clip(2P−1,0,1)` (no depende de que el modelo acierte) | + detección de SESGO sistemático (no resuelta) | exp029 (el estimador "acuerdo-con-consenso" FALLÓ; test-retest calibra) |
| **Director vs router existente** | reusar `Router` (CYCLE 12) cambiando solo las acciones | director jerárquico en cascada N1→N2→N3 | encoder supervisado-por-verificador (CYCLE 21) como contexto rico | `cognia_x/reason/router.py`; `supervised_router.py` |
| **Pizarra / comm-por-necesidad** | sin pizarra (todo el contexto a cada experto) | pizarra de hallazgos (coseno-en-RAM, db_pool) | + protocolo need/provide | `ARQUITECTURA §pizarra/comunicación`; PENDIENTE |

**Recomendación v1.** Columna "Moderada". Concretamente: (1) jerarquía N1=cuencas + N2 con herencia;
(2) selección por plan con retry; (3) **coordinación = mezcla adaptativa test-retest (exp029)**, que es
lo único PROBADO; (4) director = `Router` re-apuntado; (5) pizarra de hallazgos como interfaz, comm-por-
necesidad diferida. **El bandit meta-selector (radical en coordinación) entra solo si M-tarde muestra que
ninguna estrategia fija de coordinación domina** (replicando exp086 en el sistema real).

---

## 5. Plan de validación (CPU vs Kaggle)

> **Marco:** esta fase es **tardía** (post 04+05). Su validación NO es "el routing sube la capacidad"
> (CYCLE 47 dice que no es el lever) sino **"la modularidad funciona y la coordinación es no-regret"**.

### 5.1 V1 — Coordinación no-regret en el sistema real (CPU; reusa exp029 como test de regresión)
- **Objetivo:** confirmar que la mezcla adaptativa test-retest es **no-regret** con un **verificador real-
  ejecutable** (plano 04), no el sintético de exp029. La entrada honesta de exp029 dice que su límite es
  "verificador sintético + 1 paso" → este es el salto a cerrar.
- **Diseño:** N consultas con verificador de fiabilidad **variable por dominio** (inyectar ruido conocido).
  Medir `CONSEC_V`, `CONSEC_FREE`, `ADAPT(r)` y `worst_regret`. **Pre-registro:** APOYADA si
  `ADAPT ≥ max(componentes) − 0.02` en todo el rango y `r` calibra monótona (réplica del criterio de
  exp029). Test de regresión: `cognia_x/tests/test_cycle43_adaptive_allocation.py` debe seguir 4/4.
- **Hardware:** **i3 (CPU)** — verificador = sandbox que ejecuta (plano 04, `cognia_v3/core/sandbox_tester.py`),
  numpy para la política. No requiere GPU.

### 5.2 V2 — Selección por plan vs token (CPU + Kaggle)
- **Objetivo:** medir que la selección por plan **no pierde calidad** frente a un baseline sin
  especialización, a igual costo de banda en el i3.
- **Brazos:** (1) **base sola** (sin adapter); (2) **adapter de cuenca por plan** (director N1); (3)
  **adapter+jerarquía N2**. Métricas: accuracy verificada (plano 04) + **tok/s y RAM en el i3** (llama.cpp
  real con `--lora`). **Predicción honesta (a confirmar):** (2) y (3) ≥ (1) en su dominio sin penalizar
  banda (el adapter no cambia el tamaño del base). **Control negativo declarado:** si (2)≈(1), el routing
  no paga → confirma CYCLE 47 y se congela la fase.
- **Hardware:** **entrenamiento de adapters** → **Kaggle GPU** (`train_qlora_kaggle.py`); **inferencia +
  medición** → **i3** (`LLAMA_LORA_PATH` → `--lora`).

### 5.3 V3 — DoD de modularidad: añadir/actualizar un experto sin reentrenar (CPU + Kaggle)
- **Procedimiento:** (a) entrenar un adapter NUEVO de un sub-dominio en Kaggle; (b) registrarlo en
  `registry.py` (un `Expert` nuevo, `parent_id` apuntando a su N1); (c) sin tocar el base ni los demás
  adapters, el director lo selecciona para consultas de ese dominio (`--lora <nuevo>`); (d) verificar que
  las consultas de OTROS dominios **no cambian** (aislamiento). **DoD cumplido** si el experto nuevo sube
  accuracy en su dominio y `|Δaccuracy|≈0` en los demás, **sin reentrenar nada más**.
- **Actualizar un experto:** reemplazar `adapter_path` por una versión re-entrenada; o **fundir** dos
  adapters del mismo dominio intra-cuenca (plano 06 §3.3.1, sobre deltas reconstruidas). Verificar no-
  regresión en el resto.

### 5.4 Anti-circularidad (regla dura)
El gate de coordinación **NO** puede evaluarse sobre la misma señal que la política optimiza (sería el
fallo H-SELF-2 de Cognia: evaluar sobre la DB que se auto-escribe). La recompensa del director es el
**verificador real-ejecutable** (plano 04), **independiente** del bandit; la fiabilidad es **test-retest**
(no auto-confianza). Esto está **probado** que importa: el `mode="confidence"` de `router.py` (recompensa
= auto-confianza) es secuestrado por el "fanfarrón" (Goodhart) — usar `mode="verifier"` siempre.

---

## 6. Lo que NO está probado / riesgos

1. **El routing NO es el cuello (CYCLE 47) — prioridad, no defecto.** El propio lab concluyó que más
   orquestación no mueve la aguja; el lever es sustrato+verificador. **Riesgo de proyecto:** invertir en
   esta fase ANTES de que 04/05 estén sólidos rinde poco. **Mitigación:** construir 08 después de 04/05;
   su valor es **modularidad**, no capacidad. Confianza **alta** en esta lectura (es la conclusión
   explícita del ledger).
2. **Coordinación probada solo en TOY/1-paso (confianza media).** exp029/CYCLE 43 usa **verificador
   sintético y tarea de 1 paso**; su propio límite declarado es el multi-paso y el verificador real. V1
   (§5.1) es el salto a cerrar. Hasta entonces, "la mezcla adaptativa es no-regret en el sistema real" es
   **ASUMIDO**.
3. **Test-retest detecta ruido ALEATORIO, no SESGO sistemático (límite duro, citado).** Un verificador
   "siempre-acepta" se ve **consistente** (r alto) pero es inútil. exp029 lo declara. **Riesgo P1:** un
   experto con verificador sesgado pasaría el filtro de fiabilidad. **Mitigación:** complementar con una
   señal de SESGO (p.ej. tasa de aceptación vs base esperada) — **no resuelta**, marcar para M-tarde.
4. **Calidad por-plan vs por-token NO medida a escala (confianza media-baja).** Que la selección por plan
   IGUALE a MoE token-por-token en CALIDAD (no solo costo) es **ASUMIDO** — solo está fundado el ahorro
   de banda (exp004). V2 (§5.2) lo mide en pequeño; a escala real es incógnita.
5. **La jerarquía N1/N2/N3 de DOMINIO no está demostrada (confianza media-baja).** Lo demostrado (CYCLE
   12-21) es ruteo de **cadenas de razonamiento**, no de **expertos de dominio**. Que un árbol de
   adapters supere a un adapter plano por cuenca es **conjetura**; V2 con N2 lo testea. Riesgo: N2/N3 con
   pocos datos **degradan** (adapter de bajo rango sobre poco dato) — de ahí la **herencia del padre** y
   "micro-experto solo bajo demanda".
6. **Pizarra y comunicación por necesidad: PENDIENTES, sin exp (confianza baja).** Solo se diseña la
   interfaz. Riesgos: la pizarra puede serializar (cuello si N expertos escriben mucho); el protocolo
   need/provide puede pedir mal y omitir contexto crítico. **No reclamar funcionamiento** hasta tener exp.
7. **R-VALOR como señal verifier-free: brújula, NO acelerador (confianza media, no sobre-apoyar).** El
   arco downstream (149-155) cerró del lado RANKING: R-VALOR vale por la DECISIÓN de asignación/abstención,
   validado en toy/oráculo, **no confirmado en el lazo real**. Usar la confianza endógena como `CONSEC_FREE`
   para **ordenar/abstener**, **nunca** como única señal ni como verdad (`00_READINESS §5.2`).
8. **Memoria del i3: un experto activo por vez (limitación física).** No es MoE multi-experto en una
   pasada; es adapter-switching. Si una consulta necesita 2 dominios disjuntos, hoy se resuelve
   **secuencialmente** (cargar A, generar, cargar B), con costo de recarga de adapter. **Confianza alta**
   en el límite; el costo real de recarga `--lora` en el i3 **no está medido** (V2 lo mide).
9. **Desajuste de contrato de adapter (heredado de plano 06, riesgo P1).** `qlora_trainer` entrena
   `q,k,v,o` pero `federated_store` solo federa `k,v` (`_KEYS`). Un experto federado **pierde `q,o`**
   silenciosamente. Decisión de M0 (plano 06 §3.2). Afecta a 08 porque los expertos SON esos adapters.
10. **SCALE = 0%.** Toda la coordinación está validada en numpy/toy; la jerarquía y la pizarra ni eso. La
    transferencia a un 3B real con N adapters reales es la mayor incógnita (confianza media).

---

## 7. DoD + dependencias

### 7.1 Definición de Hecho (verificable, no "parece andar")
- [ ] **`cognia_x/experts/registry.py`** corre: registrar/listar/deshabilitar `Expert` (N1/N2/N3) con
      `parent_id`, `domain_cluster` ∈ `DOMAIN_EXPERT_CLUSTERS`, `adapter_path`, herencia del padre cuando
      `adapter_path=None`. Test CLI: árbol de 3 niveles, resolver `expert_id → adapter_path` con herencia.
- [ ] **`cognia_x/experts/director.py`** decide ruta por PLAN (no por token), reusando el bandit de
      `reason/router.py` con `mode="verifier"` y `unsure_margin`/presupuesto. Test CLI: 3 consultas de
      dominios distintos → ruta N1→N2 correcta; "preguntar al oráculo" decrece con el tiempo.
- [ ] **Coordinación no-regret (V1)**: la mezcla adaptativa test-retest sobre **verificador real** (plano
      04) cumple `ADAPT ≥ max(componentes) − 0.02` y `r` monótona; `cognia_x/tests/test_cycle43_adaptive_allocation.py`
      sigue 4/4 (test de regresión). Reportar la tabla `CONSEC_V/CONSEC_FREE/ADAPT(r)` real.
- [ ] **DoD de modularidad (V3 — el DoD central del plano):** añadir un experto NUEVO (adapter entrenado
      en Kaggle + registro) **sin reentrenar el base ni los demás adapters**; el director lo selecciona en
      su dominio (`LLAMA_LORA_PATH`→`--lora`), sube accuracy en ese dominio y `|Δaccuracy|≈0` en los otros.
      Medido con CLI real sobre Qwen2.5-Coder-3B Q4_K_M en el i3 (mostrar output, no solo pytest).
- [ ] **`cognia_x/experts/blackboard.py`** (interfaz): `write/read/summary` con persistencia vía
      `storage/db_pool.py` (NO `sqlite3.connect`), reusando `cognia_embedding`. Test CLI: escribir 5
      hallazgos, leer top-k por relevancia. **(PENDIENTE marcado; no bloquea el DoD central.)**
- [ ] **Anti-circularidad verificada:** el director usa `mode="verifier"` (no `confidence`); test que
      muestra que `mode="confidence"` es secuestrado por el fanfarrón (replica CYCLE 12) y que `verifier` no.
- [ ] Suite rápida verde: `.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q`
      (reportar N passed / M failed real).

### 7.2 Dependencias
- **Bloqueantes (orden que paga, Apéndice A):** **plano 04** (verificador real-ejecutable — el director lo
  CONSUME como recompensa y para test-retest) y **plano 05** (lazo de auto-mejora — genera los datos con
  que se entrenan los expertos). 08 **no se construye antes** de 04 y 05.
- **Dependencias de diseño (reusar, no redefinir):** **plano 06** (formato/rango del adapter, fusión
  intra-cuenca, router de 3 bandas, agregación federada correcta), **plano 02** (backbone que carga el
  adapter), **plano 01** (planificador rápido + integrador + los dos núcleos).
- **Infra que ya corre (no bloqueante, reusar):** `cognia_x/reason/router.py` / `text_router.py` /
  `supervised_router.py`, `cognia_x/experiments/exp029_adaptive_allocation/` (+ exp086, exp098),
  `shattering/model_constants.py:DOMAIN_EXPERT_CLUSTERS`, `cognia_v3/training/qlora_trainer.py` +
  `kaggle/train_qlora_kaggle.py`, `node/llama_backend.py:_lora_args()`, `coordinator/federated_store.py`,
  `storage/db_pool.py`, `cognia_v3/memory/cognia_embedding.py`.
- **Hardware:** coordinación/router/director/medición → **i3 (CPU)**; entrenamiento de adapters →
  **Kaggle GPU** (cuenta anthuananthuan). El i3 **no** entrena QLoRA y carga **un adapter a la vez**.
- **Restricciones duras aplicables:** expertos = adapters LoRA (FedAvg solo sobre LoRA, nunca base);
  selección por PLAN no token-por-token; sin `sqlite3.connect` directo (usar `db_pool`); sin constantes
  de modelo hardcodeadas (usar `model_constants.py`); gate NO circular (`mode="verifier"`, no auto-
  recompensa); R-VALOR solo como brújula acotada; nada de mocks (cada subsistema cierra con prueba CLI real).

### 7.3 Riesgos (resumen ejecutivo)
**P0 — prioridad:** esta fase es **tardía** (CYCLE 47: el routing no es el lever); construir 04/05 primero.
**P1 — sesgo del verificador:** test-retest no lo detecta (riesgo 3) + desajuste de contrato de adapter
(riesgo 9). **P2 — calidad por-plan a escala** (riesgo 4), **jerarquía de dominio no demostrada** (riesgo 5),
**pizarra/comm-por-necesidad PENDIENTES** (riesgo 6). **Transversal:** SCALE = 0% (riesgo 10).

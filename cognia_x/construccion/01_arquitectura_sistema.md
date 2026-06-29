# 01 — Arquitectura del sistema (flujo end-to-end + módulos + router de 3 bandas)

> **Propósito.** Plano de MÁS ALTO NIVEL de Cognia-X: define el flujo de datos completo
> (Usuario → Planificador → Verificador → Director → Expertos → Integrador → Motor de razonamiento →
> Motor de comunicación → Respuesta), las **fronteras de módulo**, las **interfaces** (qué entra/sale
> de cada subsistema), y el **router de memoria/contexto de 3 bandas** (LOCAL/MEDIA/GLOBAL, el análogo
> de HYDRA a nivel de sistema). Mapea cada módulo a su plano detallado (02–09) y marca, con cita al
> ledger REAL, qué está **demostrado-en-pequeño** vs **pendiente**. Es el contrato de ensamblaje:
> los planos 02–09 implementan las cajas; este define cómo se conectan.

> **Anclaje de fuentes:** `cognia_x/manager/ARQUITECTURA_OBJETIVO.md` (North Star del dueño, flujo y
> núcleos), `cognia_x/manager/architecture.md` (decisiones por componente con exp001-007),
> `cognia_x/construccion/00_READINESS.md` (GO CONDICIONADO, gates M0). Código que corre hoy:
> `cognia_x/model/hybrid.py`, `cognia_x/reason/router.py`, `cognia_x/reason/lm_router.py`,
> `cognia_x/learn/continual.py`, `cognia_x/research/hypotheses.py`,
> `cognia_x/experiments/exp018_real_verifier/`.

---

## 1. Propósito y alcance

### 1.1 Qué resuelve este plano
- Fija **las cajas y los cables**: cada módulo del flujo, su responsabilidad única, y el **tipo de dato
  exacto** que cruza cada frontera (interface). Sin esto, los planos 02–09 se construyen contra
  supuestos incompatibles.
- Define el **router de 3 bandas** (LOCAL/MEDIA/GLOBAL) como subsistema transversal de
  contexto/memoria, construido **SOBRE** el routing existente (no reemplazándolo).
- Establece el **orden de ensamblaje** que el lab probó que paga (Apéndice A de
  `ARQUITECTURA_OBJETIVO.md`): verificador → lazo de auto-mejora → recién después expertos/routing.

### 1.2 Qué NO cubre (se delega a planos detallados)
- El backbone interno (mezcla lineal + SWA + global, vocab, cuantización) → **plano 02**.
- La implementación del sandbox del verificador por dominio → **plano 04**.
- El lazo STaR y su guardia de diversidad → **plano 05**.
- Los detalles de cada subsistema → **planos 02–09** (mapeo en §3.7).
- El cronograma de milestones (M0…) y los gates G1–G3 → **plano 11 (plan maestro de build)**, ya
  referenciado por `00_READINESS.md §4`.

### 1.3 Alcance honesto (de `00_READINESS.md §6`)
Construir NO es "entrenar un GPT-4 en el i3". Es **ensamblar el sistema mínimo viable end-to-end** que
encarne la arquitectura objetivo sobre lo ya demostrado, CPU-first para inferencia + Kaggle GPU para
entrenamiento. Este plano es el mapa de ese ensamblaje. **SCALE = 0%** (hardware-bloqueado): todas las
constantes de tamaño/latencia son **confianza media** hasta M0.

---

## 2. Estado de partida (qué existe y corre hoy)

| Pieza | Existe hoy | Corre | Cita |
|---|---|---|---|
| Backbone híbrido v0 (`HybridLM`/`HybridConfig`) | Sí | Sí (tiny) | `model/hybrid.py`; verificado 2026-06-28: 1.56M params, ratio 3:1, forward+features+generate, entrena loss 5.56→2.03/30 pasos (`00_READINESS.md` C4) |
| Router de meta-razonamiento (bandit por tipo) | Sí | Sí | `reason/router.py` (`Router`), CYCLE 12-21 |
| Router con encoder LM aprendido (NCM + whitening) | Sí | Sí | `reason/lm_router.py` (`LMRouter`), CYCLE 19-20 |
| Verificador real-chequeable (sandbox que EJECUTA) | Sí | Sí | `experiments/exp018_real_verifier/` (H-LEARN-3), CYCLE 31; guardia CYCLE 50/53 |
| Lazo de auto-mejora verificada (STaR) | Sí (toy) | Sí | CYCLE 48-50: base débil 0.30→0.78 estable e iterable |
| Aprendizaje continuo Nivel 1 con gate no-circular | Sí | Sí | `learn/continual.py` (`gated_learn_domains`, `freeze_recall_trunk`), CYCLE 8-11 |
| Engine de hipótesis (registry + DoD + ledger por tiers) | Sí | Sí | `research/hypotheses.py` (`HypothesisRegistry`), CYCLE 22 |
| Tooling de inferencia | Sí | Sí | `node/llama-server.exe` b9391 + 6 GGUF + `venv312` + `cognia_v3/core/sandbox_tester.py` |
| Separación dos núcleos / pizarra / comunicación-por-necesidad / jerarquía de expertos | **No** | — | PENDIENTE (`00_READINESS.md §5.5`) |
| Router de 3 bandas LOCAL/MEDIA/GLOBAL | **No** (diseño nuevo) | — | Este plano lo especifica; se construye sobre el routing existente |

**Lectura honesta:** las cajas de **orquestación + verificación + auto-mejora** están
demostradas-en-pequeño y tienen código que corre. Las cajas de **estructura de sistema** (dos núcleos,
pizarra, bandas, jerarquía real de expertos) están en **papel**. Este plano las define como contratos
para que su construcción (fase tardía, post-verificador) no parta de cero.

---

## 3. Diseño detallado

### 3.1 El flujo end-to-end (diagrama ASCII)

El flujo canónico del dueño (`ARQUITECTURA_OBJETIVO.md` §"Estructura General"), instrumentado con las
interfaces reales y la banda de memoria que consulta cada etapa:

```
                          ┌───────────────────────────────────────────────────────────┐
                          │   ROUTER DE 3 BANDAS (memoria/contexto) — transversal       │
                          │   LOCAL (pizarra/W~1024)  MEDIA (sesión+adapters)  GLOBAL   │
                          │   (RAG doc-level + adapter store federado + ledger)         │
                          └───┬───────────┬───────────┬───────────┬───────────┬─────────┘
                              │           │           │           │           │ (cada etapa
   Usuario                    ▼           ▼           ▼           ▼           ▼  consulta la
     │  Query{text,sid,        ............................................................ banda que
     ▼  constraints,budget}    :                                                          : necesita,
 ┌─────────────────┐  Plan     :  ┌───────────────────┐ VerifiedPlan  ┌──────────────────┐: NO todo el
 │ PLANIFICADOR    │──────────────▶│ VERIFICADOR       │──────────────▶│ DIRECTOR DE      │: contexto)
 │ RÁPIDO (barato) │           :  │ PROFUNDO (real-   │   approved?    │ EXPERTOS         │:
 └─────────────────┘           :  │ chequeable)       │◀──retry/abst──▶│ (selección por   │:
   plano 09                    :  └───────────────────┘                │  PLAN, no token) │:
                               :    plano 04                           └────────┬─────────┘:
                               :                                ExpertTask{goal, │ plano 08
                               :                                constraints,     ▼ (comunicación
                               :                                ctx_band-filtrado)  POR NECESIDAD)
                               :   ┌───────────────────────────────────────────────────┐  :
                               :   │ EXPERTOS = adapters LoRA por dominio (N1/N2/N3)     │  :
                               :   │   leen SOLO lo que piden ──▶ escriben a la PIZARRA  │  :
                               :   └───────────────────────────┬───────────────────────┘  :
                               :     plano 08                  │ ExpertResult{finding,      :
                               :                               ▼ evidence, conf, verif}     :
                               :   ┌───────────────────────────────────────────────────┐   :
                               :   │ INTEGRADOR de resultados (resuelve conflictos,      │   :
                               :   │ deduplica, abstención calibrada)                    │   :
                               :   └───────────────────────────┬───────────────────────┘   :
                               :     plano 08/09               │ IntegratedResult            :
                               :....................................................▼.........:
                                   ┌───────────────────────────────────────────────────┐
                                   │ MOTOR DE RAZONAMIENTO (núcleo razonador)            │
                                   │   produce IDEAS verificadas (R-VALOR = brújula      │
                                   │   decisional de asignación/abstención)              │
                                   └───────────────────────────┬───────────────────────┘
                                     plano 02 (sustrato) + 09   │ ReasoningTrace
                                                                ▼
                                   ┌───────────────────────────────────────────────────┐
                                   │ MOTOR DE COMUNICACIÓN (núcleo comunicador)          │
                                   │   traduce idea→lenguaje natural, adapta estilo      │
                                   └───────────────────────────┬───────────────────────┘
                                     plano 02 (sustrato) + 09   │ Response{text, style}
                                                                ▼
                                                            Usuario
```

**Principio rector (del dueño):** *"El razonador produce ideas. El comunicador las expresa."*
(`ARQUITECTURA_OBJETIVO.md` §1). Los dos motores son la **separación de núcleos** PENDIENTE; en el v1
arrancan como **un único `HybridLM` con dos cabezas/modos de decodificación** (ver §4, decisión
conservadora) y se separan a medida que la evidencia lo justifique.

### 3.2 Contratos de interfaz (qué entra/sale de cada módulo)

Frontera = un **dict/dataclass plano y serializable** (estilo del repo: dicts simples, sin frameworks;
ver `reason/problems.py`, `research/schema.py`). Definidos como contratos; **NINGUNO existe en código
todavía** salvo donde se cita el módulo real.

```python
# --- Entrada del sistema ---
Query        = {"text": str, "user_id": str, "session_id": str,
                "constraints": dict, "budget": {"steps": int, "ask": int}}

# PLANIFICADOR RÁPIDO  (plano 09)  — barato, tolerante a error
#   in:  Query                    out: Plan
Plan         = {"task_type": str,            # clasificación de tarea
                "expert_route": [str],       # ruta inicial de dominios (ej. ["fisica","relatividad"])
                "budget_alloc": dict,        # cómputo por paso (P2: coste primero)
                "resources": [str],          # bandas/recursos previstos
                "confidence": float}

# VERIFICADOR PROFUNDO (plano 04)  — real-chequeable, la pieza de 1ra clase
#   in:  Plan                     out: VerifiedPlan
VerifiedPlan = {"plan": Plan,
                "add_experts": [str], "drop_experts": [str],  # corrige la planificación
                "inconsistencies": [str],
                "approved": bool, "abstain": bool}            # abstención calibrada (CYCLE 46)

# DIRECTOR DE EXPERTOS (plano 08) — selección por PLAN, no token-por-token
#   in:  VerifiedPlan             out: [ExpertTask]  (comunicación POR NECESIDAD)
ExpertTask   = {"expert_id": str, "goal": str, "constraints": dict,
                "ctx": dict}      # SOLO lo relevante, filtrado por el router de bandas (NO todo)

# EXPERTO (adapter LoRA por dominio) (plano 08)
#   in:  ExpertTask               out: ExpertResult  (escrito a la PIZARRA)
ExpertResult = {"expert_id": str, "finding": str, "evidence": [str],
                "confidence": float, "verifier_status": str}   # passed|failed|unchecked

# INTEGRADOR (plano 08/09)
#   in:  [ExpertResult] + Pizarra out: IntegratedResult
IntegratedResult = {"merged": str, "conflicts_resolved": [str],
                    "abstain": bool, "hypotheses": [str]}       # ids del HypothesisRegistry

# MOTOR DE RAZONAMIENTO (plano 02 sustrato + 09)
#   in:  IntegratedResult         out: ReasoningTrace
ReasoningTrace = {"idea": str, "chain": str,                    # cadena meta-razonadora elegida
                  "value_signal": float,                        # R-VALOR (brújula, no acelerador)
                  "checked": bool}

# MOTOR DE COMUNICACIÓN (plano 02 sustrato + 09)
#   in:  ReasoningTrace + estilo  out: Response
Response     = {"text": str, "style": str, "citations": [str]}
```

**Regla de oro de las fronteras (anti-acoplamiento):** un módulo SOLO ve su `in` y produce su `out`;
**nunca** lee el estado interno de otro. El único canal compartido es la **pizarra** (§3.4), y el único
acceso a memoria de largo plazo es vía el **router de bandas** (§3.3). Esto encarna
"comunicación basada en necesidad" + "cero contexto innecesario" (`ARQUITECTURA_OBJETIVO.md` §§
"Comunicación Basada en Necesidad", "Memoria Temporal Compartida").

### 3.3 Router de memoria/contexto de 3 bandas (el análogo de HYDRA a nivel de sistema)

**Restricción dura (CLAUDE.md):** *"HYDRA como atención en la red es INVIABLE (modelo pre-cuantizado
INT4 + pre-shardeado). El trabajo HYDRA es el análogo a nivel de SISTEMA: enrutador de contexto/memoria
de 3 bandas (LOCAL/MEDIA/GLOBAL) construido SOBRE el routing LOGOS/TECHNE/RHETOR existente."*

El router de 3 bandas decide, **por sub-consulta**, de qué nivel de memoria traer contexto. NO es
atención de red; es un **selector de fuentes** sobre las jerarquías de memoria que ya existen.

| Banda | Qué contiene | Sustrato físico | Latencia | Coste (bytes/token) |
|---|---|---|---|---|
| **LOCAL** | Pizarra de la consulta actual + ventana viva | Atención sliding-window `W~1024` (`hybrid.py` `SlidingWindowAttention`) + RAM | mínima | dominado por W, no por L |
| **MEDIA** | Turnos recientes de la sesión + adapters LoRA de la **misma cuenca** activa | KV-cache + adapter store en RAM | baja | acotado |
| **GLOBAL** | Conocimiento congelado: RAG **doc-level** (1 recuperación/consulta), adapter store federado, ledger de hipótesis | Disco/índice + `coordinator/federated_store.py` (**bug FedAvg-naïve REAL aún presente** — promedia A y B por separado; corregir a FedEx-LoRA ANTES de usar la banda federada, R5/§6) | alta (I/O) | 1 hit/consulta (NO por-token) |

**Decisión de banda (construida SOBRE el routing existente):** el routing de producción
`LOGOS/TECHNE/RHETOR` (Cognia v2/v3) clasifica la **intención**; el router de 3 bandas le agrega una
**segunda dimensión ortogonal: el alcance temporal/de memoria**. Pseudocódigo:

```python
def route_band(subquery, plan, session):
    # 1) primero LOCAL: ¿la pizarra/ventana ya tiene lo necesario? (lo más barato)
    if covered_by_scratchpad(subquery, session.scratchpad):     # LOCAL
        return "LOCAL", session.scratchpad.slice(subquery)
    # 2) MEDIA: ¿está en la sesión reciente o en un adapter de la cuenca activa?
    if in_session_or_active_adapter(subquery, session):         # MEDIA
        return "MEDIA", session.recent + active_adapter_ctx(subquery)
    # 3) GLOBAL: hecho nuevo/raro -> UNA recuperación doc-level (P5: bytes/token)
    return "GLOBAL", rag_retrieve(subquery, k=1)                # GLOBAL (doc-level, 1 hit)
```

**Por qué este orden (evidencia):** la decisión de aprendizaje continuo (`architecture.md` §4) fija
**RAG a nivel DOCUMENTO, 1 recuperación/consulta**, y **DESCARTA kNN-LM por-token** porque el retrieval
es memory-bound (~35% TTFT doc-level **según literatura, NO medido en el i3**; por-token lo multiplica).
La banda GLOBAL respeta eso: se consulta
**lo menos posible** y siempre a granularidad de documento. **Confianza media** (literatura, sin exp
propio; el A/B es el **gate G3** de M0, `00_READINESS.md §4`).

**Estado:** PENDIENTE (diseño nuevo). El sustrato de la banda LOCAL (sliding-window) ya existe en
`hybrid.py`; el RAG doc-level (GLOBAL) y la fusión de adapters (MEDIA) son objetivos de fase tardía
(plano 06). Detalle completo → **plano 06** (router de 3 bandas + RAG doc-level) y **plano 08** (pizarra).

### 3.4 La pizarra (memoria temporal compartida)

Canal único de coordinación entre expertos (`ARQUITECTURA_OBJETIVO.md` §"Memoria Temporal Compartida":
*"no contiene todo el contexto; contiene únicamente hallazgos relevantes; puede ser leída por otros
expertos. Funciona como una pizarra colaborativa."*).

```python
class Pizarra:            # PENDIENTE de implementar (plano 08)
    # append-only, mismo patrón que research/record.py (journaled_append)
    def write(self, expert_id, finding: dict): ...      # un ExpertResult relevante
    def read(self, query: str) -> list[dict]: ...        # SOLO hallazgos pertinentes (band-filtered)
```

Reusa el patrón **append-only journaleado** de `research/record.py` (`PermanentRecord`,
`journaled_append`) ya probado en el engine de hipótesis. **NO** es persistente entre consultas (eso es
banda MEDIA/GLOBAL); es el scratchpad de la consulta actual = banda LOCAL.

### 3.5 El verificador profundo (caja de 1ra clase) y su lugar en el flujo

`VERIFICADOR PROFUNDO` aparece DOS veces en la arquitectura, con la misma maquinaria:
1. **En el flujo de planificación** (`ARQUITECTURA_OBJETIVO.md` §"Verificador Profundo"): critica el
   Plan (agrega/quita expertos, detecta inconsistencias).
2. **Como evaluador del lazo de auto-mejora** (plano 05): el sandbox que EJECUTA la salida y decide si
   un ejemplo entra al entrenamiento.

Ambos comparten el **sandbox real-chequeable** ya demostrado:
`experiments/exp018_real_verifier/` ejecuta la salida en un intérprete propio con **allowlist + gramática
acotada** (regla #9; alineado con `cognia_v3/core/sandbox_tester.py`: AST+allowlist+subprocess timeout).
**PROBADO-PEQUEÑO** (CYCLE 31, H-LEARN-3 apoyada): la auto-mejora funciona con verificador real y un
verificador DÉBIL se reward-hackea → **la CALIDAD del verificador (FP-rate < e\*) es el lever dominante**
(e\*~0.15 sin guardia, exp017; sube a ~0.50 con guardia dedup+replay, CYCLE 50/53). Detalle → **plano 04**.

> **Caveat (qué está realmente demostrado vs. propuesto):** lo PROBADO-PEQUEÑO es el **uso 2** (evaluador
> del lazo: el sandbox EJECUTA una salida y discrimina fuerte/débil, exp018). El **uso 1** (criticar un
> `Plan` en lenguaje natural — agregar/quitar expertos, detectar inconsistencias de routing) viene de la
> VISIÓN (`ARQUITECTURA_OBJETIVO.md`), **NO está demostrado**, y es una tarea distinta de ejecutar código:
> probablemente exija maquinaria adicional (no la misma del sandbox de ejecución). No tratar ambos usos
> como equivalentes en madurez. **Confianza media** en que el uso 1 reutilice la maquinaria del uso 2.

**Interfaz del verificador (real, de exp018):**
```python
# E.verify(prompt_bytes, emitted_bytes, strong: bool) -> bool
#   strong=False (débil): valor==N           (acepta el echo -> reward-hack)
#   strong=True  (fuerte): valor==N Y usa operador (computación real)
```
En el flujo de producción la versión "fuerte" por dominio es la que aprueba `VerifiedPlan.approved`.

### 3.6 Motor de razonamiento ↔ Motor de comunicación (separación de núcleos)

`ARQUITECTURA_OBJETIVO.md` §1 exige separar **razonar** de **hablar**. Estado del lab: el arco v4
(CYCLE 40-50) trabajó el **núcleo de razonamiento** (act-and-verify) **sin acoplarlo al lenguaje**
(Apéndice A, fila 1). La separación física en dos núcleos es **PENDIENTE**.

- **R-VALOR como brújula del razonador (no del comunicador):** el motor de razonamiento usa la señal
  endógena valor = controlabilidad × relevancia **solo para decisiones de asignación/abstención**, NO
  para acelerar el loss. **PROBADO** en toy/oráculo (CYCLE 123/138/145-146); **NO confirmado en el lazo
  real** (arco downstream 149-155 cerró del lado RANKING: el residuo es discriminación, no calibración).
  El motor la usa como **heurística acotada, sin sobre-apoyarse** (`00_READINESS.md §5.2`).
- **Mapeo a sustrato:** ambos motores corren sobre el **mismo backbone híbrido** (plano 02). El v1 los
  realiza como **dos modos de decodificación** del mismo `HybridLM` (razonar = cadena interna verificada;
  comunicar = decodificación de superficie estilizada). La separación en dos pesos/adapters distintos es
  un objetivo de fase tardía. **Confianza media** en que la separación física pague (sin exp propio).

### 3.7 Mapa módulo → plano detallado

| # plano | Título (canónico) | Módulos del flujo que cubre | Estado del núcleo |
|---|---|---|---|
| **02** | Backbone del modelo CPU-first (híbrido + fallback) | sustrato de AMBOS motores (razonamiento+comunicación) | PARCIAL (v0 corre tiny) |
| **03** | Plan de entrenamiento y datos (Kaggle + curriculum + motor de datos verificados) | infraestructura: entrena el sustrato (02) y los expertos (08) | tooling Kaggle configurado / pipeline PENDIENTE |
| **04** | Verificador profundo real-chequeable (sandbox) | Verificador profundo (×2 usos) | DEMOSTRADO-PEQUEÑO |
| **05** | Lazo de auto-mejora verificada (STaR) + guardia de diversidad | mecanismo de mejora del sustrato | DEMOSTRADO-PEQUEÑO |
| **06** | Aprendizaje continuo (RAG doc-level + LoRA + fusión + router de 3 bandas + FedEx-LoRA) | router de memoria/contexto (3 bandas), RAG doc-level, anti-olvido | PENDIENTE (3 bandas diseño nuevo) / DEMOSTRADO-PEQUEÑO (N1) / literatura (federado) |
| **07** | Stack de inferencia y cuantización (llama.cpp + Q4 + KV-cache + telemetría) | infraestructura: ejecuta los motores en el i3, telemetría bytes/token | tooling llama.cpp b9391 corre (inferencia) |
| **08** | Expertos jerárquicos y coordinación (director, LoRA por dominio, pizarra) | Director de expertos, Expertos, pizarra, Integrador (coordinación) | PENDIENTE (jerarquía) / parcial (integrador≈abstención) |
| **09** | Núcleos de razonamiento y comunicación + planificador + meta-razonamiento + hipótesis + autoevaluación | Planificador, motores Razonamiento/Comunicación, Integrador→razonador, meta-razonamiento, hipótesis, autoevaluación | DEMOSTRADO-PEQUEÑO (router 12-21, hipótesis 22) |
| **10** | Registro de riesgos consolidado | transversal (todos los riesgos del build) | (consolidación; ver §6) |
| **11** | Plan maestro de build (milestones M0…, gates G1-G3) | cronograma + validación | (existe como referencia en `00_READINESS.md §4`) |

> **Honestidad sobre la numeración:** la numeración es la **descomposición canónica** del conjunto
> (fuente de verdad: `00_INDICE.md`). Todos los planos **02–11 ya existen** como archivos en
> `cognia_x/construccion/`. Si al refinar los detallados se reagrupa un módulo, **este mapa (§3.7) y
> `00_INDICE.md` son las fuentes de verdad a actualizar en conjunto**.

### 3.8 Diagrama de dependencias entre módulos (orden de construcción)

El orden que el lab **probó que paga** (Apéndice A: "(1) verificador real-chequeable, (2) lazo de
auto-mejora + guardia, (3) recién después jerarquía de expertos/routing"). Las flechas son
**"depende de / se construye encima de"**. **Honestidad sobre el orden:** lo que el Apéndice A demostró
es **solo el esqueleto de 3 pasos** (verificador → lazo+guardia → expertos/routing); la ubicación fina del
resto (09 entre 05 y 08, 06 transversal y al final) es **instanciación del autor**, NO probada por el
lab — **confianza media** en el ordenamiento detallado:

```
        [02 Backbone híbrido]  ◀── sustrato de todo (corre hoy, tiny)
                 │
                 ▼
        [04 Verificador]  ◀────────────── PRIMERO (lever dominante: FP-rate)
                 │
                 ▼
        [05 Lazo auto-mejora STaR] ──┐    SEGUNDO (mejora el sustrato 02 desde
                 │                    │            salidas verificadas por 04)
                 ▼                    │
        [09 Hipótesis + autoeval]    │    (autoevaluación/abstención alimenta 04 y 05)
                 │                    │
                 ▼                    ▼
        [08/09 Planificador + Director + meta-razonamiento]    TERCERO (orquestación; rinde
                 │                                COMPUESTO solo si 04 es preciso)
                 ▼
        [08 Expertos (LoRA) + Integrador]
                 │
                 ▼
        [06 Aprendizaje continuo: router 3 bandas + RAG + fusión + federado]  ◀── transversal
                                              (memoria/contexto) + anti-olvido + escalar sin reentrenar
```

**Regla anti-Goodhart de la dependencia (lección v4):** NO construir 06/08/09 antes de que 04 (verificador)
tenga FP-rate medido < e\*. "Toda la orquestación rinde de forma COMPUESTA solo si el paso base es preciso
y el verificador confiable" (`ARQUITECTURA_OBJETIVO.md`, lección transversal).

---

## 4. Decisiones y alternativas

### D-SYS-1 — Separación de núcleos razonamiento↔comunicación
- **Conservadora (v1, elegida):** un `HybridLM` con **dos modos de decodificación** (interno verificado
  vs superficie estilizada). Cero coste de separar pesos; reusa el sustrato que corre hoy.
- **Moderada:** dos **adapters LoRA** sobre el mismo base congelado (razonador vs comunicador), fusionables
  dentro de la misma cuenca (Model Soups, `architecture.md` §4).
- **Radical:** dos modelos/pesos distintos. **Rechazada para v1**: duplica RAM (el i3 tiene 11.8 GB) y no
  hay evidencia propia de que pague. → revisitar post-SCALE.
- **Evidencia:** el arco v4 razonó **sin** lenguaje (Apéndice A fila 1); la separación es del dueño, no
  medida. **Confianza media.**

### D-SYS-2 — Selección de expertos: por PLAN, no token-por-token
- **Elegida:** análisis del objetivo → ruta inicial → plan → aprobar → ejecutar
  (`ARQUITECTURA_OBJETIVO.md` §"Selección de Expertos"). Converge con el **giro estratégico CYCLE 47**:
  el lever NO es más routing sino **mejor sustrato + verificador**; expertos ≈ **adapters LoRA por dominio**.
- **Alternativa (MoE token-por-token):** **rechazada** (alto coste, decisiones repetitivas, duplicación)
  — y además inviable en CPU memory-bound (P5).
- **Confianza alta** en la dirección (giro 47 documentado); media en la jerarquía N1/N2/N3 concreta.

### D-SYS-3 — Router de 3 bandas SOBRE el routing existente (no reemplazo)
- **Elegida:** segunda dimensión (alcance de memoria) ortogonal al routing de intención
  LOGOS/TECHNE/RHETOR. Banda LOCAL = sliding-window que ya existe; GLOBAL = RAG doc-level 1-hit.
- **Alternativa (HYDRA como atención de red):** **prohibida** por restricción dura (modelo pre-INT4
  pre-shardeado).
- **Confianza media** (diseño nuevo; G3 lo valida).

### D-SYS-4 — Backbone único compartido vs especializado por módulo
- **Elegida (v1):** **un solo backbone híbrido** (plano 02) sirve a planificador, motores y encoder del
  router (el `LMRouter` ya usa `HybridLM.forward_features` como **encoder**, CYCLE 19). Minimiza RAM y
  reusa lo que corre.
- **Confianza alta en la dirección** (verificado en código: `LMRouter` usa `HybridLM.forward_features`
  como encoder Y `HybridLM` genera) — pero la evidencia es a **escala tiny** (1.56M params; SCALE=0%);
  la transferencia a escala real queda como incógnita abierta.

---

## 5. Plan de validación (cómo se mide que el ENSAMBLAJE funciona)

> Este plano valida **el flujo y las fronteras**, no cada subsistema (eso es de 02–09). La validación de
> subsistema vive en su plano; aquí se prueba que **los cables conectan**.

### 5.1 En CPU (i3, sin GPU) — barato, primero
1. **Smoke end-to-end con stubs verificables (NO mocks):** cada caja implementada como función real
   mínima que corre de verdad (regla "código que corre o no cuenta"). El test recorre
   `Query → … → Response` y comprueba **que cada interfaz respeta su contrato** (claves/tipos de §3.2).
   Marco: `tests/`, patrón de `experiments/expNNN/run.py`. **CHECK explícito** del dict en cada frontera.
2. **Verificador en el lazo (real):** correr `experiments/exp018_real_verifier/run.py --smoke` y confirmar
   que el sandbox EJECUTA y discrimina fuerte/débil (ancla la caja 04 dentro del flujo).
3. **Router de meta-razonamiento (real):** `reason/run_cycle19.py`/`run_cycle20.py` ancla la caja 09
   (ruteo por clase aprendida, premiado por verificador).
4. **Continual gate (real):** `learn/continual.gated_learn_domains` con `aggregate=False` confirma el gate
   **no circular** por-dominio (cierra H-SELF-2) — ancla la caja 06.
5. **Router de 3 bandas:** A/B **G3** (RAG doc-level vs LoRA vs kNN-LM) en CPU (RAG/kNN son CPU) para fijar
   la política de inyección de hechos (`00_READINESS.md §4 G3`).
6. **Telemetría de bytes/token (P5):** instrumentar cada etapa para reportar bytes movidos/token y RAM —
   la métrica maestra (`architecture.md` P5). Confirma que la banda GLOBAL no domina por-token.

### 5.2 En Kaggle GPU — solo lo que el i3 no puede
- Entrenar adapters LoRA por dominio (expertos), char-LM/encoder a escala, y cualquier base >0.5B.
  El i3 hace **solo inferencia** (llama.cpp, techo ~8 tok/s 3B Q4) + experimentos numpy/torch-cpu chicos
  (`00_READINESS.md §5.1`). Pipeline: `cognia_v3/training/kaggle/`.

### 5.3 Gates que condicionan este plano (de `00_READINESS.md §4`)
- **G1 (A-018, P0):** ¿el ahorro de banda SSM/SWA se materializa con kernels CPU reales? Si NO →
  **rama de fallback**: el sustrato de los motores pasa a **Transformer denso pequeño GQA + KV-cache
  4-bit** (maduro en llama.cpp HOY). El flujo de este plano **no cambia**; solo cambia la caja 02.
- **G2:** fragilidad de recall del híbrido a carga alta. **Caveat fuerte (C-01 residual / H-HYB-3):** el
  techo de recall del mezclador lineal de estado fijo es **ESTRUCTURAL** (pigeonhole sobre el estado,
  exp002; 6 levers NO-atención REFUTADOS — ancho exp010, forma/kernel Taylor+init mimética exp011,
  profundidad/escala/optimizador exp012). A d chico / carga alta el híbrido *naive interleaved* **NO**
  cruza (platea ~0.18, exp014/015); **solo la atención pura cruza** (0.88-0.95, exp013). El remedio es
  **ARQUITECTÓNICO = atención** (por eso la banda LOCAL descansa en sliding-window). M0 no solo "afina un
  ratio": puede tener que **subir la cuota de atención / ensanchar W / agregar globales** a la escala
  objetivo (afecta caja 02, no las fronteras).
- **G3:** política de inyección de hechos → fija la banda GLOBAL (§3.3).

---

## 6. Lo que NO está probado / riesgos

| # | Riesgo | Severidad | Mitigación / estado |
|---|---|---|---|
| R1 | **Separación de núcleos no demostrada** (ni en pequeño). Puede que separar razonar/hablar no pague o duplique RAM. | Alta | v1 usa modos de decodificación de un solo modelo (D-SYS-1 conservadora); separar solo si la evidencia lo justifica. PENDIENTE. |
| R2 | **Router de 3 bandas es diseño nuevo** sin exp propio. La política de banda puede no respetar bytes/token. | Media | G3 lo valida en CPU; banda GLOBAL = 1-hit doc-level por construcción (kNN-LM por-token DESCARTADO). |
| R3 | **Pizarra/comunicación-por-necesidad sin implementar.** Riesgo de filtrar "todo el contexto" y perder la eficiencia. | Media | Contrato `Pizarra.read(query)` band-filtered; reusa append-only journaleado probado (`record.py`). PENDIENTE. |
| R4 | **Jerarquía de expertos N1/N2/N3 no demostrada.** El giro CYCLE 47 sugiere que el lever es sustrato+verificador, no más routing. | Media | Expertos ≈ adapters LoRA por dominio (no MoE token); construir DESPUÉS de 03/04. |
| R5 | **Federado de adapters arrastra un bug real:** `coordinator/federated_store.py` promedia A y B por separado (avg(A)·avg(B) ≠ avg(A·B)). | Alta | exp003 MIDIÓ el error (0.4%→66% con heterogeneidad). Corregir a **FedEx-LoRA** (avg(B@A)) ANTES de usar la banda GLOBAL federada. Plano 08. |
| R6 | **R-VALOR NO confirmado en el lazo real** (solo toy/oráculo). El motor de razonamiento no debe sobre-apoyarse. | Media | Usar como **brújula acotada** de asignación/abstención (arco 149-155 cerró del lado ranking). |
| R7 | **Constantes confianza media** (ratio 3:1-4:1, W~1024, vocab 32-64k, e\*, umbrales). No medidas end-to-end en el i3. | Media | M0 + telemetría las fijan; afectan cajas internas, no las fronteras de este plano. |
| R8 | **G1 puede fallar** (kernels SSM/SWA CPU inmaduros; precedente exp007: int8 naïve 8-10× más lento sin kernel). | Alta | Rama de fallback ya prevista (GQA denso + KV-4bit); el flujo no se bloquea. |
| R9 | **Verificador circular si se descuida** (H-SELF-2): evaluar sobre la misma DB que se auto-escribe colapsa el gate. | Alta | Gate por-dominio held-out NO circular ya implementado (`gated_learn_domains aggregate=False`); el verificador del lazo usa test held-out DISJUNTO (exp018). |
| R10 | **Mocks/stubs prohibidos** pero el smoke end-to-end necesita cajas mínimas. | Baja | Cajas = funciones reales mínimas que corren (no mocks); cada frontera con CHECK real del contrato. |
| R11 | **Techo de recall ESTRUCTURAL del mezclador lineal** (C-01/H-HYB-3): a d chico/carga alta el híbrido naive NO recupera recall (platea ~0.18, exp014/015); solo atención pura cruza (exp013). NO es un knob de ratio que se "afina". | Alta | Remedio arquitectónico = atención (banda LOCAL = sliding-window); G2 fija cuota de atención / W / globales a la escala objetivo. 6 levers no-atención YA refutados (exp010-012); rama fallback GQA denso (R8) también es atención plena. |

**Caveat transversal honesto (de `00_READINESS.md §5`):** SCALE = 0% (hardware-bloqueado); todo el thesis
está validado en juguete. La transferencia a escala real es la mayor incógnita (confianza media). Los docs
de gobernanza (`hypotheses.md`/`assumptions.md`) están desfasados ~115 ciclos; los vivos son
`research_log.md` + `decomposition_tree.md` + `STATUS_RVALOR.md`.

---

## 7. Definición de Hecho (DoD) + dependencias

### 7.1 DoD verificable de ESTE plano (la arquitectura de sistema)
Se considera HECHO cuando:
1. **Existe un test end-to-end real** (`tests/test_arquitectura_flujo.py`, a crear) que recorre
   `Query → Planificador → Verificador → Director → Expertos → Integrador → Razonamiento → Comunicación →
   Response` con cajas reales mínimas, y **afirma el contrato de §3.2 en cada frontera** (claves+tipos).
   Corre con `venv312\Scripts\python.exe -m pytest tests/test_arquitectura_flujo.py -q` y pasa.
2. **El verificador real está en el lazo:** `exp018 --smoke` corre y discrimina fuerte/débil (CHECK del
   output real).
3. **El router de 3 bandas tiene `route_band()` ejecutable** que devuelve (banda, ctx) para los 3 casos
   (LOCAL/MEDIA/GLOBAL), con la banda GLOBAL limitada a 1 hit doc-level (test que lo afirma).
4. **El mapa módulo→plano (§3.7) está sincronizado** con los archivos 02–09 a medida que se crean
   (este plano es la fuente de verdad del mapeo).
5. **Telemetría de bytes/token** instrumentada en al menos una etapa (P5), con número reportado.

### 7.2 Dependencias
- **Duras (bloquean):** plano 02 (sustrato — corre hoy, tiny) ✅; plano 04 (verificador — demostrado) ✅.
  Sin un verificador con FP-rate medido < e\*, los planos 06/08/09 NO deben construirse (orden del Apéndice A).
- **De datos/tooling:** `venv312` ✅, `node/llama-server.exe` b9391 + GGUF ✅,
  `cognia_v3/core/sandbox_tester.py` ✅, Kaggle GPU para entrenar expertos ✅ (configurada).
- **Blandas (se resuelven en M0):** G1 (kernels SSM/SWA) → caja 02; G2 (ratio recall) → caja 02; G3
  (política de bandas) → caja 06.
- **Hacia adelante:** este plano alimenta los planos 02–09 (contratos de §3.2) y al plano 11 (cronograma).

### 7.3 Riesgos residuales aceptados al cerrar
- Las cajas de **estructura de sistema** (dos núcleos, pizarra, bandas, jerarquía) quedan como
  **contratos** + diseño, NO como código probado (son fase tardía por orden de construcción). Aceptado
  conscientemente: el lab probó que construirlas ANTES del verificador+lazo no paga.
- Todas las constantes siguen en **confianza media** hasta M0; este plano define **fronteras estables**
  precisamente para que cambiar una constante interna (caja 02) no rompa el ensamblaje.

---

> **Cierre honesto.** Este plano es **el mapa, no el territorio**: fija el flujo, las interfaces y el
> orden de construcción anclados en lo que el lab DEMOSTRÓ (verificador, lazo STaR, router de
> meta-razonamiento, gate continual, engine de hipótesis — todos con código que corre) y marca
> explícitamente lo PENDIENTE (dos núcleos, pizarra, 3 bandas, jerarquía de expertos, federado
> corregido). La construcción arranca por M0 (gates G1-G3) sin esperar más ciclos de investigación toy
> (`00_READINESS.md`).

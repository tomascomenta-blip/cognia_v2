# MEJORA DEL SISTEMA DE INVESTIGACIÓN + DISCIPLINA ANTI-RUIDO

**Fecha:** 2026-07-19
**Estado:** Fase 1 EN CURSO. Fase 2 DISEÑO — **no ejecutar hasta que el dueño lo indique.**
**Hardware:** Ryzen 5 9600X (6c/12t), 31 GB RAM, RTX 5060 Ti 16 GB, Windows 11.

**Pedido del dueño (transcrito de voz, dos partes):**

1. *"primero construye el sistema que me explicaste ahorita de lo que vendría siendo la
   investigación, quiero que mejores el sistema de investigación y ya"*
2. *"cuando una inteligencia artificial tú le pides que te corrija algo, se va llenando de
   ruido, se va haciendo más tonta y no termina solucionando y solo quedan parches por
   encima que a la larga dejan de funcionar (...) me gustaría que buscaras técnicas para
   evitar el ruido, evitar las confusiones, e intentarlas implementar acá (...) lo que yo
   me imagino es un respiro profundo, y después decir: me estoy equivocando en esto, voy a
   revisar desde cero, voy a arrancar el problema de raíz"*

Convención de citas: **[V]** = página abierta y leída. **[S]** = vista solo en resultados
de búsqueda, no abierta; tratar como no verificada. **[M]** = medido en esta máquina.

---

## 0. Resumen ejecutivo

- La **Fase 1** cierra la brecha medida el 2026-07-19 entre Cognia y el workflow
  multi-agente: le faltaban **fuentes** y **verificación**. Se ataca con dos piezas:
  scraper de arXiv (fuente) y contra-búsqueda de evidencia (verificación).
- La **Fase 2** es el pedido del "respiro profundo". Es un problema real y con nombre
  propio en la literatura, no una intuición vaga del dueño; pero es también donde más
  fácil se construye humo, así que va con gates y con criterio de KILL explícito.
- **Orden no negociable, fijado por el dueño:** Fase 1 completa y verificada antes de
  tocar la Fase 2.

---

## FASE 1 — Sistema de investigación

**Estado:** en curso. Lo ya hecho está commiteado en `31b2c45`.

### 1.0 Ya entregado (2026-07-19, commit `31b2c45`)

`cognia/research_engine/`: `relevance.py`, `hf_scraper.py`, `query_planner.py`,
`web_research.py`, y `github_scraper.py` parcheado. 21 tests de regresión; suite
completa 2872 passed / 0 failed **[M]**.

### 1.1 Scraper de arXiv — G1

**Por qué:** ~90% del informe que ganó la comparación salió de papers y benchmarks
(NoLiMa, HELMET, RULER) que **no están indexados en repos de GitHub ni en model cards**.
Es la fuente que más brecha cierra por unidad de esfuerzo.

**Por qué arXiv y no búsqueda web general:** arXiv tiene API pública, sin key,
estructurada (Atom XML) **[M]**. La búsqueda web general no: exige API paga (Brave,
Tavily, Serper, Exa) o raspar SERPs, lo que es frágil y suele violar los ToS. Aceptar
eso rompería la propiedad que el módulo tiene hoy — solo stdlib, cero dependencias, cero
credenciales. **Decisión: arXiv sí, búsqueda web general diferida.**

**Restricción operativa:** arXiv pide 3 segundos entre peticiones. Es lento a propósito
y hay que respetarlo; no se negocia bajándolo.

**G1 (gate):** una pregunta técnica devuelve ≥3 papers pertinentes con abstract, y los
tests de parseo pasan sobre XML real guardado.
**KILL G1:** si la API cambia de formato o exige key, se cae la pieza; no se sustituye
por scraping de la web de arXiv.

### 1.2 Contra-búsqueda de evidencia — G2

**Por qué:** en la comparación del 2026-07-19 el paso de verificación **tumbó 3 de 6
candidatos** (Qwen3.5-2B, Qwen3.5-0.8B y LFM2.5 como opción de contexto). Los tres
**ganaban en el papel**. Sin ese paso, la recomendación habría sido la equivocada.

**La decisión de diseño más importante del plan, y la contraintuitiva:** el paso de
verificación **NO emite veredictos con un LLM**. Busca evidencia en contra y te la
muestra.

Razón: refutar es la tarea de razonamiento más difícil del pipeline y es exactamente
donde los modelos pequeños fallan peor — tienden a estar de acuerdo con lo que se les
muestra. Un refutador respaldado por `llama3.2` no sería "verificación mediocre", sería
**peor que no tener nada**: pondría un sello de "verificado" sobre lo no comprobado. Hoy
Cognia no sabe; con un refutador débil, Cognia *creería que sabe*. Eso es un retroceso.

**Forma concreta:** para cada candidato fuerte, disparar contra-búsquedas dirigidas
(`"<X> limitations"`, `"<X> benchmark"`, `"<X> issues"`) y devolver las fuentes que lo
contradicen, sin juicio. Determinista, no puede alucinar un veredicto, deja el juicio en
el humano. Se promueve a juez con LLM sólo cuando haya un modelo local más fuerte.

**Presupuesto de peticiones:** GitHub sin token da 60/hora **[M]**. La contra-búsqueda
corre sobre arXiv por defecto (sin límite duro, solo la cortesía de 3 s) y se limita a
los 3 mejores candidatos con 1 query cada uno.

**G2:** sobre la pregunta de modelos de contexto largo, la contra-búsqueda encuentra al
menos una fuente que matiza o contradice al candidato mejor rankeado.
**KILL G2:** si devuelve ruido no relacionado en >50% de los casos, se saca del flujo por
defecto y queda como comando manual.

### 1.3 Fuera de alcance en Fase 1

Búsqueda web general (ver 1.1), Semantic Scholar / OpenAlex (posible G4 futuro, tienen
API libre), y **cualquier veredicto automático de un LLM**.

---

## FASE 2 — Disciplina anti-ruido ("el respiro profundo")

**Estado:** DISEÑO. **No ejecutar sin indicación explícita del dueño.**

### 2.0 El problema, dicho con precisión

El dueño lo describió por observación y acertó: un agente al que se le pide corregir algo
repetidamente **acumula parches sobre síntomas** en vez de atacar la causa, y el contexto
se llena de intentos fallidos que empeoran las decisiones siguientes. Tiene nombres en la
literatura y no es folklore: degradación por contexto largo (*context rot*), *anchoring*
sobre la primera hipótesis, y *sunk cost* sobre el trabajo ya hecho.

**Evidencia dentro de este mismo repo de que el problema es real y de que la disciplina
funciona:** el KILL pre-registrado del BDraft cortó la Pista 1 al **10% del presupuesto**
tras fallar G3 dos veces, en vez de descubrirlo tras 60 h de GPU. Esa es exactamente la
mecánica que el dueño pide, aplicada a investigación en vez de a depuración.

**Y evidencia de la sesión del 2026-07-19:** al ajustar el ranking de relevancia hice
**cuatro intentos sucesivos** (peso fijo → orden de aparición → sustantivo+modificador →
tope de longitud). Los tres primeros fueron parches sobre el síntoma; sólo el cuarto
atacó la causa (el texto de 64.765 caracteres). Lo que rompió el ciclo fue **medir el
caso real** en vez de seguir ajustando la heurística. Ese es el dato de diseño más útil
que tengo, y viene de fallar, no de teoría.

### 2.1 Investigar las técnicas — G3

Buscar técnicas reales de mitigación. **Correr esta investigación con el Cognia mejorado
en Fase 1**, que es a la vez el uso previsto del producto y su prueba honesta.

Ejes a cubrir: *context rot* y degradación por longitud; detección de bucles de
reparación; análisis de causa raíz (5 porqués, reproducción mínima, bisección);
reinicio con contexto limpio; verificación adversarial; presupuestos y gates
pre-registrados; y *ratchets* de regresión.

**G3:** ≥5 técnicas con fuente primaria, cada una con criterio de aplicabilidad y coste.
**KILL G3:** si sólo aparecen posts de opinión sin evidencia, se implementa únicamente el
disyuntor de 2.2, que ya está justificado por evidencia interna, y se cierra la fase.

### 2.2 El disyuntor de reparación ("respiro profundo") — G4

La pieza que **ya está justificada** aun si G3 no encuentra nada, porque la evidencia
interna la respalda. Boceto:

1. **Huella del síntoma:** firma estable de la falla (test que falla + firma del error).
2. **Contador de intentos** por huella. Un arreglo que no cambia la huella no cuenta como
   progreso, cuenta como parche.
3. **Disyuntor a los 2 intentos fallidos sobre la misma huella:** se prohíbe seguir
   parchando y se fuerza cambio de modo.
4. **Modo raíz:** revertir los parches acumulados, escribir la **reproducción mínima**,
   enunciar la hipótesis de causa **por escrito antes de tocar código**, y medir el caso
   real en vez de ajustar la heurística a ciegas.
5. **Métrica:** profundidad de parche y número de reversiones. Si el disyuntor no dispara
   nunca en trabajo real, sobra; si dispara siempre, el umbral está mal.

**G4:** el disyuntor dispara sobre un bucle de reparación reproducido a propósito, y no
dispara en trabajo normal (sin falsos positivos en una sesión real completa).
**KILL G4:** si estorba más de lo que ayuda en una sesión real, se degrada a aviso sin
bloqueo.

### 2.3 Pregunta abierta que hay que resolver ANTES de codificar la Fase 2

**¿Sobre qué bucle actúa el disyuntor?** Hay dos lecturas del pedido y llevan a código
distinto:

- **(a)** Sobre el bucle de auto-corrección de **Cognia** (`code_executor.py`,
  `tool_synthesis`, `background_research`), que genera y verifica herramientas y puede
  degradar en parches.
- **(b)** Sobre la disciplina de **las sesiones de trabajo** — es decir, una regla de
  método en `CLAUDE.md` más un verificador que la haga cumplir.

Son compatibles, pero el orden importa y el esfuerzo es muy distinto. **Preguntar al
dueño antes de escribir una línea.** No asumir.

---

## Registro de gates

| Gate | Qué | Estado |
|------|-----|--------|
| G0 | Ranking, HF, planificador, informe | ✅ `31b2c45`, 2872 tests verdes |
| G1 | Scraper de arXiv | ✅ ver abajo |
| G2 | Contra-búsqueda de evidencia | ✅ ver abajo |
| G3 | Investigar técnicas anti-ruido | bloqueado por 2.3 (pregunta al dueño) |
| G4 | Disyuntor de reparación | bloqueado por G3 y por 2.3 |

**G1 — cerrado 2026-07-19.** Con la pregunta *"modelo pequeño con mayor ventana de
contexto y menos KV cache"* devuelve entre otros **[M]**:

- *Short window attention enables long-term memorization* (cs.LG, 2025) — trata
  exactamente la arquitectura híbrida local/global que resultó ganadora en la
  investigación del mismo día, y era **inalcanzable** para GitHub y HuggingFace.
- *Window-Diffusion: Accelerating Diffusion Language Model Inference with Windowed
  Token Pruning and Caching* (cs.LG, 2026).

**El filtro de categorías fue el hallazgo del gate, no un detalle.** Sin él la misma
query devolvía *Locality of the windowed local density of states* (math-ph) y *Narrow
escape to small windows on a small ball modeling the viral entry into the cell nucleus*
(q-bio) **[M]**. La causa no era el umbral de relevancia: arXiv es la única de las tres
fuentes que no está acotada al dominio. Se arregló en la raíz —acotando la búsqueda—
en vez de subiendo el filtro, que habría sido el parche.

**G2 — cerrado 2026-07-19.** Para `Mamba state space model` devuelve *The Computational
Limits of State-Space Models and Mamba via the Lens of Circuit Complexity*; para `linear
attention`, *Linear Attention Architectures: Mechanisms, Trade-offs, and Cross-Layer
Routing* **[M]**.

**Comportamiento a no “arreglar”:** para candidatos oscuros (un repo de 13 estrellas)
devuelve **vacío**. Eso es la respuesta correcta —nadie publicó un paper sobre ese
repo— y devolver algo sería inventar contraevidencia. Si alguna vez parece un bug,
leer esto antes de tocarlo.

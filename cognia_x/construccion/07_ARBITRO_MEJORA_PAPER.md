# Mejora del paper LCD+MOM (§4.2, el árbitro) — con evidencia de AG-ARB

**Fecha:** 2026-07-03 · **Base:** paper del dueño `LCD_MOM_Paper.docx` §4.2 ("el
árbitro", el componente "menos precedented") + experimento AG-ARB pre-registrado
(`06_AGENTE_PLAN.md` §5) corrido en el dominio agente · **Estado:** resultados
REALES, predicción congelada ANTES de correr, veredicto abajo.

Este documento hace tres cosas que el paper pide implícitamente y que su §4.2
deja abiertas: (1) le da el **prior-art** que dice faltar ("menos precedented" ya
no es cierto), (2) reformula la afirmación central como una **bicondicional
testeable**, y (3) la **contrasta con datos** — y el resultado corrige la teoría
en un punto concreto que el paper no anticipó cuantitativamente.

---

## 1. Qué afirma el paper (§4.2) y qué queda sin resolver

El paper propone un **árbitro**: dada una salida final incorrecta, atribuir la
falla al módulo culpable de un pipeline heterogéneo (geometría / materiales /
iluminación / render) para actualizar solo ese módulo. Lo declara el componente
más especulativo y el de mayor riesgo (§4.2, §10): un árbitro sesgado
"reproduciría el colapso de expertos" (§2.3), concentrando señal en un módulo
mientras los demás se estancan. Propone tres estrategias como hipótesis, sin
validarlas: **verificación por etapa**, **renderizados de control**, y
**gradiente end-to-end como respaldo**.

Lo que queda sin resolver en el paper: *¿bajo qué condiciones* la verificación
por etapa le gana a un crítico global? El paper no lo formula como condición
falsable ni lo mide.

---

## 2. Prior-art que el paper debe citar ("menos precedented" ya no aplica)

La atribución de crédito en pipelines/agentes multi-etapa tiene literatura 2025-26
que el paper puede (y debería) citar; el árbitro no parte de cero:

- **Who&When** (Zhang et al., ICML 2025, arXiv:2505.00212): dataset y tarea de
  "¿qué agente causó el fallo y cuándo?". Mide que jueces **frontier** (o1/R1)
  atribuyen fallo de etapa con **53.5%** de accuracy — el techo real del enfoque
  crítico-LLM, dato que el paper necesita para calibrar expectativas.
- **AgenTracer** (arXiv:2509.03312): un atribuidor **liviano y especializado** le
  gana a un juez-LLM grande. Apoya directamente la tesis MoM de componentes chicos
  especializados > monolito grande, aplicada a la atribución misma.
- **MAST** (taxonomía de modos de falla multi-agente, 1600+ trazas): vocabulario
  estándar de fallas de pipeline — hace el paper indexable en la conversación
  correcta.
- **ORPS** (arXiv:2412.15118): en razonamiento sobre programas, **ejecución
  verificable + crítica** supera a un PRM aprendido. Es evidencia a favor de la
  estrategia "verificación por etapa con oráculo ejecutable" del §4.2 frente al
  "gradiente end-to-end como respaldo".
- **Design-by-Contract para agentes** (arXiv:2510.12120): formaliza los
  "contratos de entrada/salida" que el paper describe informalmente en §4.1 — el
  paper puede adoptar su nomenclatura en vez de re-derivarla.
- **Reward hacking en jueces-LLM** (arXiv:2606.04923): respalda con literatura el
  riesgo de §4.2 (árbitro sesgado → colapso), y coincide con el hallazgo propio
  (CYCLE 12) de que un juez sin oráculo duro colapsa a *gaming*.

---

## 3. Reformulación testeable (lo que el paper puede adoptar)

> **La verificación por etapa domina al crítico global ⟺ (a) existe un oráculo
> ejecutable barato en la etapa donde se introdujo la falla, Y (b) las etapas son
> semánticamente heterogéneas y no sustituibles. Donde falta el oráculo de esa
> etapa —falla que se propaga y se manifiesta aguas abajo, u oráculo (test)
> corrupto— NINGÚN método localiza la raíz sin una segunda referencia
> independiente.**

La analogía del paper (geometría ≠ materiales ≠ iluminación) cumple (b) por
construcción; lo que faltaba medir era (a). AG-ARB es exactamente el test de esa
bicondicional en un pipeline agente análogo (**plan → design → code → test**).

---

## 4. AG-ARB: el experimento y su resultado (predicción CONGELADA vs real)

**Setup:** 32 casos = 8 tareas base con solución de referencia × 4 etapas, con UNA
falla inyectada (seeded) por caso en etapa CONOCIDA (ground truth por
construcción, estilo mutation testing). Cada caso VERIFICADO en build (el pipeline
correcto no dispara contratos; el faulted rompe el output — 0 descartados). Tres
brazos: (i) **contratos** (verificación por etapa + un *control* que instancia los
"renderizados de control" del §4.2, para desambiguar el borde design/code);
(ii) **árbitro-LLM global** (Qwen2.5-3B ve solo la salida final: code + tests);
(iii) **árbitro-LLM con traza** (ve las 4 etapas).

**Predicción congelada (antes de correr):** (i) ≥80% en etapas con oráculo
ejecutable; (ii) ≤55% (Who&When: 53.5% con jueces frontier — un 3B no debería
superarlos); (iii) entre ambos.

**Resultado real:**

| brazo | global | plan | design | code | test |
|---|---|---|---|---|---|
| (i) contratos | **16/32 = 50.0%** | 0/8 | **8/8** | **8/8** | 0/8 |
| (ii) árbitro-LLM global | 10/32 = 31.2% | 0/8 | 0/8 | 8/8 | 2/8 |
| (iii) árbitro-LLM + traza | 10/32 = 31.2% | 0/8 | 0/8 | 8/8 | 2/8 |

**Veredicto (según la regla de falsación pre-registrada):** gana (i). Los
contratos aciertan **100% (16/16) en las etapas con oráculo ejecutable** (design,
code), cumpliendo el ≥80% predicho, y el árbitro-LLM queda muy por debajo (31.2%),
consistente con el techo de Who&When (un 3B < jueces frontier). El paper se
re-especifica: **el árbitro es una cascada contratos-primero con LLM solo de
fallback**, no un crítico-LLM global.

---

## 5. Lo que el paper NO anticipó y AG-ARB agrega (la corrección concreta)

Tres hallazgos empíricos nuevos, cada uno con su consecuencia para el diseño del
árbitro:

1. **El juez-LLM tiene un sesgo de "culpar al artefacto terminal".** Predijo
   `code` en **24/32** (global) y **30/32** (traza) de los casos, y **nunca**
   identificó una falla de `plan` ni de `design` (0/8 cada una). Es el colapso de
   §2.3/§4.2 **medido**: el árbitro sesgado concentra la culpa en un módulo (el
   último visible) e ignora los aguas-arriba. → **Consecuencia:** un árbitro-LLM
   sin oráculos NO debe usarse para actualizar módulos tempranos; los reforzaría
   con señal sistemáticamente errónea.

2. **Más contexto EMPEORA al juez chico.** La traza completa (iii) no mejoró la
   accuracy (misma 31.2%) y de hecho **aumentó el sesgo a `code`** (30 vs 24). →
   **Consecuencia:** contra la intuición del §4.2 ("dar la traza ayuda"), en un
   modelo chico la traza ancla más fuerte en el artefacto final. La estrategia
   "renderizados de control" del paper debe ser un **oráculo estructurado
   externo** (como en el brazo i), no "mostrarle más al crítico-LLM".

3. **Hay dos regímenes donde NINGÚN método del paper localiza la raíz**, y son
   identificables a priori: (a) **falla propagada** (raíz en `plan`, se manifiesta
   en `test`; los contratos la atribuyen a `code`, 0/8), y (b) **oráculo corrupto**
   (el `test` mismo está mal; indistinguible de `code` malo, 0/8). → **Consecuencia:**
   la bicondicional del §3 no es un detalle: define la **frontera de aplicabilidad**
   del árbitro. Fuera de ella, el paper debe reconocer que se necesita una segunda
   referencia independiente (un test de oro, o un segundo módulo redundante) — no
   un árbitro más listo.

---

## 6. Redacción sugerida para el §4.2 del paper (reemplazo)

> El árbitro no es un componente sin precedentes: la atribución de crédito en
> pipelines multi-etapa está estudiada (Who&When, ICML 2025; AgenTracer 2025;
> Design-by-Contract para agentes 2025). Su forma efectiva es una **cascada de
> verificación por etapa con oráculos ejecutables baratos**, con un crítico
> generativo solo como fallback: en un pipeline heterogéneo con oráculo ejecutable
> en la etapa de la falla, la verificación por etapa localiza la raíz con alta
> precisión, mientras que un crítico global tiende a atribuir el fallo al último
> módulo visible (sesgo medido: culpa al artefacto terminal en >75% de los casos,
> sin identificar fallas de etapas tempranas). El árbitro es aplicable **sí y solo
> sí** existe un oráculo ejecutable en la etapa candidata y las etapas no son
> sustituibles; una falla que se propaga a etapas posteriores, o un oráculo de
> etapa corrupto, no son localizables sin una segunda referencia independiente, y
> el sistema debe reconocerlo en vez de reforzar un módulo con señal errónea.

---

## 7. Límites honestos de AG-ARB (lo que NO establece)

- Pipeline **toy** de 4 etapas y tareas de función pura; no prueba el resultado
  en el dominio gráfico del paper (geometría/materiales/iluminación), solo en su
  **análogo agente**. La bicondicional es la que transfiere, no los números.
- Juez **3B**, no frontier. El 31.2% no dice "los jueces-LLM son malos"; dice que
  un juez chico sin oráculo colapsa al sesgo terminal (consistente con el 53.5%
  frontier de Who&When: el techo del enfoque es bajo incluso arriba).
- Fallas **seeded** de un tipo por etapa; no cubre fallas compuestas ni ruido de
  generación real. Extensión declarada: fallas múltiples y el árbitro sobre trazas
  del agente real (no inyectadas).
- El brazo de contratos usa el **control** (¿el code pasa los tests?) para
  desambiguar design/code; ese control ES la estrategia (iii) del paper — el
  experimento la valida donde hay oráculo, no la inventa.

**Frontera para el paper:** extender la bicondicional a fallas no-lineales/
compuestas y a un pipeline con oráculo intermedio real (no solo al final), que es
donde el §3 predice que la verificación por etapa gana más margen sobre el
crítico global.

# Arquitectura Jerárquica de IA — Expertos, Metarrazonamiento y Generación de Hipótesis

> **Documento del dueño (visión objetivo).** Especificación de la arquitectura a implementar cuando se entrene
> Cognia-X. Guardado verbatim como North Star de ingeniería; el **Apéndice A** (al final) lo enlaza con lo que
> el arco v4 (CYCLE 40-50) ya demostró en pequeño sobre el modelo propio del lab. No borrar; append-only.

## Objetivo

Diseñar una arquitectura de IA capaz de:

- Escalar mediante expertos especializados.
- Reducir el costo computacional de inferencia.
- Separar razonamiento y lenguaje.
- Crear hipótesis nuevas.
- Evaluar sus propios procesos.
- Aprender a coordinar recursos internos.
- Mantener compatibilidad con arquitecturas Transformer modernas.
- Aprovechar componentes existentes sin volverlos obsoletos.

---

## Principios Fundamentales

### 1. Separación entre razonamiento y comunicación

La arquitectura no debe asumir que razonar y hablar son la misma tarea.

Se propone separar:

**Núcleo de razonamiento** — Responsable de:

- Resolver problemas.
- Planificar.
- Coordinar expertos.
- Evaluar hipótesis.
- Detectar errores.
- Diseñar estrategias.

**Núcleo de comunicación** — Responsable de:

- Generar lenguaje natural.
- Adaptar el estilo de respuesta.
- Traducir razonamientos internos.
- Interactuar con usuarios.

El razonador produce ideas. El comunicador las expresa.

---

## Estructura General

```
Usuario
  ↓
Planificador rápido
  ↓
Verificador profundo
  ↓
Director de expertos
  ↓
Expertos
  ↓
Integrador de resultados
  ↓
Motor de razonamiento
  ↓
Motor de comunicación
  ↓
Respuesta
```

---

## Sistema de Expertos Jerárquicos

**Nivel 1 — Expertos generales.** Ejemplos: Matemáticas, Física, Biología, Programación, Ingeniería, Economía.

**Nivel 2 — Subexpertos.** Ejemplo (Física): Mecánica, Relatividad, Cuántica, Astrofísica.

**Nivel 3 — Microexpertos.** Ejemplo (Relatividad): Agujeros negros, Ondas gravitacionales, Cosmología relativista.

### Selección de Expertos

**Método tradicional.** Las arquitecturas MoE actuales seleccionan expertos token por token. Problemas:

- Alto costo computacional.
- Decisiones repetitivas.
- Duplicación de trabajo.

**Método propuesto.** Antes de generar una respuesta:

1. Analizar el objetivo.
2. Crear una ruta inicial de expertos.
3. Construir un plan de trabajo.
4. Aprobar el plan.
5. Ejecutarlo.

Ejemplo — Prompt: *"Explica cómo funciona un agujero negro."*
Ruta: Ciencias → Física → Relatividad → Agujeros negros.

---

## Planificador Rápido

**Objetivo:** encontrar una solución preliminar en pocos pasos.

Características: muy rápido, bajo costo, tolerante a errores.

Funciones: clasificar la tarea, seleccionar expertos iniciales, detectar recursos necesarios.

---

## Verificador Profundo

**Objetivo:** analizar críticamente el plan generado.

Funciones: detectar expertos faltantes, detectar expertos innecesarios, detectar inconsistencias, corregir la
planificación.

Ejemplo — Planificador: Matemáticas + Física. Verificador: agregar Estadística.

---

## Metarrazonamiento

La IA debe razonar sobre cómo razona. Preguntas internas:

- ¿Tengo suficientes expertos?
- ¿Estoy usando expertos incorrectos?
- ¿Mi estrategia es válida?
- ¿Necesito información adicional?
- ¿Existen alternativas mejores?

---

## Comunicación Basada en Necesidad

Los expertos no reciben automáticamente todo el contexto. En lugar de ello:

- **Experto:** ¿Qué necesito saber?
- **Director:** Objetivo específico. Restricciones. Información relevante.

Beneficios: menor consumo de memoria, menor uso de contexto, mayor eficiencia.

---

## Memoria Temporal Compartida

Los expertos comparten resultados mediante una memoria temporal común.

Características: no contiene todo el contexto; contiene únicamente hallazgos relevantes; puede ser leída por
otros expertos. Funciona como una pizarra colaborativa.

---

## Sistema de Generación de Hipótesis

**Objetivo:** permitir que la IA produzca explicaciones o soluciones nuevas. No limitarse únicamente a
reproducir conocimiento existente.

**Proceso:**

1. Observación.
2. Detección de patrones.
3. Construcción de hipótesis.
4. Evaluación.
5. Priorización.
6. Verificación.

**Clasificación de hipótesis:**

- **Confirmadas** — respaldadas por evidencia suficiente.
- **Probables** — respaldadas parcialmente.
- **Exploratorias** — ideas nuevas con evidencia insuficiente.
- **Descartadas** — contradictorias o inconsistentes.

---

## Sistema de Autoevaluación

La IA debe evaluar: calidad de respuestas, calidad de planificación, calidad de hipótesis, calidad de
coordinación.

---

## Aprendizaje de Coordinación

El sistema no solo aprende conocimiento. También aprende: qué expertos usar, cuándo usarlos, cómo coordinarlos,
cómo evitar errores recurrentes.

---

## Mecanismo de Corrección

Cuando una estrategia resulta incorrecta:

1. Detectar el fallo.
2. Identificar el origen.
3. Ajustar planificación futura.
4. Registrar experiencia.

No se busca castigo simbólico. Se busca optimización continua.

---

## Compatibilidad con la arquitectura actual de Cognia

**Integración.** Los Transformers continúan siendo la base. Se añaden capas superiores de: planificación,
coordinación, metarrazonamiento, generación de hipótesis.

**Escalabilidad.** La arquitectura debe permitir: añadir nuevos expertos, añadir nuevos subexpertos, actualizar
expertos individualmente, reentrenar módulos específicos — **sin reentrenar el sistema completo.**

---

## Objetivo Final

Construir una IA que no solo responda preguntas, sino que:

- Planifique.
- Coordine especialistas.
- Razone sobre su propio razonamiento.
- Genere hipótesis.
- Aprenda estrategias.
- Aproveche arquitecturas actuales.
- Escale de forma modular y eficiente.
- Evolucione continuamente sin requerir reconstrucción completa del sistema.

---

## Apéndice A — Puentes con el arco v4 ya demostrado (anotación del laboratorio)

*Esta sección NO es parte de la especificación del dueño; mapea cada pieza de la visión a evidencia ya
producida sobre el modelo propio del lab (CPU-first, desde cero), para que el entrenamiento parta de lo
verificado y no de cero. Ver `paper.md`, `research_log.md`, `decomposition_tree.md`.*

| Pieza de la visión | Estado en el lab | Referencia |
|---|---|---|
| Separar razonamiento ↔ comunicación | Pendiente de implementar como dos núcleos; el arco v4 trabajó el **núcleo de razonamiento** (act-and-verify) sin acoplarlo al lenguaje | árbol de descomposición R-* |
| Planificador rápido + Verificador profundo | **Demostrado en pequeño:** asignar cómputo barato y verificar; la calidad del verificador es el cuello de botella | CYCLE 40-43, 47 |
| Selección de expertos por PLAN (no token-por-token) | Converge con el "no orquestar de más": el lever no es más routing sino mejor sustrato + verificador | CYCLE 47 (giro estratégico) |
| Metarrazonamiento (razonar sobre cómo razona) | **Ya existe** un router de meta-razonamiento que prueba cadenas y aprende cuál por tipo (examinador no circular) | [[cognia-x-reasoning-pillar]] (CYCLE 12-21) |
| Comunicación basada en necesidad / pizarra compartida | Pendiente; alineado con "cero contexto innecesario" | — |
| Generación + clasificación de hipótesis (confirmada/probable/exploratoria/descartada) | **Ya implementado como código que lo EXIGE:** HypothesisRegistry con DoD (predicción + evidencia a favor/en contra + veredicto adversarial), EvidenceLedger por tiers | [[cognia-x-investigation-engine]] |
| Autoevaluación (calidad de respuesta/plan/hipótesis) | **Demostrado:** verificador-based test-time + abstención calibrada ("saber cuándo no sé") | CYCLE 46 |
| Aprendizaje de coordinación / corrección de estrategias | **Demostrado:** política adaptativa que estima la fiabilidad del verificador y mezcla señales (no-regret) | CYCLE 43 |
| Evolucionar sin reconstruir todo | **Demostrado:** lazo de auto-mejora verificada (STaR) — un base débil se bootstrappea a fuerte (0.30→0.78), estable e iterable, con guardia de diversidad (dedup+replay) | CYCLE 48-50 |
| Escalabilidad modular (añadir/actualizar expertos sin reentrenar todo) | Converge con FedAvg-sobre-LoRA (adapters) ya autorizado; expertos ≈ adapters por dominio | restricciones duras CLAUDE.md |

**Lección transversal del arco v4 para esta arquitectura:** toda la orquestación (planificador, verificador,
director de expertos, metarrazonamiento) rinde de forma **compuesta** solo si el **paso base es preciso** y el
**verificador es confiable**; el lazo act-and-verify no solo orquesta — **mejora el sustrato** desde sus
propias salidas verificadas, y esa mejora se **amplifica** en razonamiento multi-paso. Entrenar Cognia-X debe
priorizar: (1) un verificador real-chequeable por dominio, (2) el lazo de auto-mejora con guardia de
diversidad, (3) recién después la jerarquía de expertos/routing.

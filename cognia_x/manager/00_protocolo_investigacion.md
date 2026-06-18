# Cognia-X — Protocolo de Investigación (meta-prompt mejorado v1)

> Este documento es la **constitución operativa** de Cognia-X. Es la versión mejorada
> del prompt fundacional entregado por el dueño. El prompt original se conserva íntegro
> al final (Apéndice A) — *nunca se borra información histórica, solo se añade*.
> Toda sesión futura debe leer este archivo + `roadmap.md` + `research_log.md` (últimas
> entradas) ANTES de actuar.

---

## 0. Identidad

**Cognia-X** es un laboratorio de investigación **independiente** dentro del repo Cognia.
NO es una modificación de Cognia, NO reusa su pipeline, NO está obligado a su arquitectura.
Vive aislado en `cognia_x/` y produce evidencia, no productos.

**Pregunta raíz (no negociable):**
> *Si hoy tuviéramos que rediseñar una inteligencia artificial desde cero absoluto, usando
> todo el conocimiento moderno disponible, ¿qué construiríamos — y por qué, con evidencia?*

El objetivo NO es clonar un Transformer ni otro LLM. Es decidir, pieza por pieza, qué
componente actual sigue siendo óptimo, cuál puede mejorarse y cuál debe reemplazarse.

---

## 1. Reglas epistémicas (lo que hace a Cognia-X distinto)

1. **Evidencia sobre autoridad.** Ninguna arquitectura se acepta porque "es lo estándar"
   (ni Transformer, ni RNN, ni Mamba, ni RWKV, ni MoE, ni nada). Cada pieza justifica su
   existencia o se reemplaza.
2. **Falsabilidad obligatoria.** Toda hipótesis se enuncia con una **predicción medible que
   podría resultar falsa**. Si no se puede falsar, no es una hipótesis: es una opinión.
3. **Refutar antes de aceptar.** Por cada hipótesis se busca activamente evidencia *en contra*
   y se intenta romperla. Solo sobrevive lo que resiste el ataque.
4. **El fracaso es información.** Un experimento que falla se documenta (qué, por qué, qué se
   aprendió) y genera nuevas hipótesis. La única razón para descartar una dirección es la
   *acumulación de evidencia suficiente en contra*, no que el problema "parezca difícil".
5. **Honestidad de confianza.** Cada afirmación lleva nivel de confianza {alta, media, baja}
   y fuentes. Si la evidencia es débil, se dice. No se reporta un resultado sin haberlo corrido.
6. **Reproducibilidad.** Todo experimento: semilla fija, entorno declarado (`venv312`,
   Python 3.12, numpy/torch-cpu), script versionado, salida guardada en `results/`. "Código que
   corre o no cuenta". Nada de mocks/stubs.

---

## 2. El ciclo de investigación (artefacto por paso)

Antes de implementar **cualquier** componente se recorre este ciclo. Cada paso deja rastro
escrito en los archivos de `manager/`.

| # | Paso | Artefacto que produce |
|---|------|----------------------|
| 1 | Investigar (qué existe, qué cuesta) | entrada en `research_log.md` |
| 2 | Formular hipótesis falsable | fila en `hypotheses.md` con id `H-XXX-n` |
| 3 | Evidencia a favor | ledger en la hipótesis (fuentes) |
| 4 | Evidencia en contra | ledger en la hipótesis (fuentes) |
| 5 | Intento de refutación | veredicto adversarial (holds true/false) |
| 6 | Diseñar experimento CPU-feasible | ficha en `experiments.md` |
| 7 | Ejecutar (semilla, entorno, salida real) | `cognia_x/experiments/expNNN/results/` |
| 8 | Analizar resultados | actualización de la hipótesis + `research_log.md` |
| 9 | Documentar conclusión | `decision_log.md` (si decide algo) + `paper.md` |

**Regla:** no se salta del paso 2 al 7. No se implementa por intuición.

---

## 3. Prioridades con presupuesto concreto (orden estricto)

1. **Eficiencia computacional** — métrica primaria.
2. Aprendizaje continuo.
3. Adaptabilidad.
4. Creatividad.
5. Razonamiento.
6. Escalabilidad futura.

> Si una mejora sube inteligencia pero destruye eficiencia, debe justificarse rigurosamente
> con números. La eficiencia es la restricción dura, no un "nice to have".

**Hardware objetivo (presupuesto de diseño):** CPU de portátil, ~2 núcleos / 4 hilos, **sin
GPU**, 8–16 GB RAM. La inferencia autoregresiva en CPU suele ser **memory-bandwidth-bound**,
no compute-bound: esto reordena qué optimizaciones importan. GPU/clúster son optimización
*futura*, nunca el punto de partida.

---

## 4. Formato del Evidence Ledger (en `hypotheses.md`)

```
### H-MEZ-1
Enunciado: <afirmación falsable>
Predicción medible: <qué número esperamos y qué lo refutaría>
Estado: {abierta | apoyada | refutada | mixta}
Confianza: {alta | media | baja}
Evidencia a favor: - <fuente / resultado>
Evidencia en contra: - <fuente / resultado>
Veredicto adversarial: <holds true/false + razón>
Experimento: expNNN (link)
```

---

## 5. Definición de "hecho" por ciclo (Definition of Done)

Un ciclo de investigación está cerrado solo si:
- [ ] La hipótesis tiene predicción falsable.
- [ ] Hay evidencia a favor **y** en contra registrada con fuentes.
- [ ] Pasó por un intento de refutación explícito.
- [ ] Si afirma algo empírico → hay un experimento **corrido** con salida real en `results/`.
- [ ] `research_log.md` y (si decide) `decision_log.md` actualizados.
- [ ] Confianza y límites declarados honestamente.

---

## 6. Protocolo de bloqueo (cuando algo parece imposible)

NO detenerse, NO declarar "no hay solución", NO aceptar el statu quo por defecto. Reformular:

1. **Reducir complejidad** → "¿cuál es la versión más pequeña posible de este problema?"
2. **Buscar analogía** → naturaleza, biología, humanos, ingeniería, logística, economía,
   juegos, evolución, sistemas sociales, procesos cotidianos.
3. **Resolver la versión cotidiana** primero (olvidar la IA), generar múltiples soluciones.
4. **Readaptar** → extraer el *principio*, no copiar literal.
5. **Optimización iterativa** → medir eficiencia, simplicidad, robustez, escalabilidad.
6. **Primeros principios** → ¿por qué existe esta técnica? ¿qué problema resolvía? ¿ese
   problema sigue existiendo? ¿hay algo más simple? ¿pagamos costes innecesarios?
7. **Tres alternativas por componente** → conservadora / moderada / radical. Evaluar las tres.
8. **Persistencia** → documentar el fracaso y reintentar con nuevas hipótesis.

---

## 7. Auto-mejora — niveles con gate de estabilidad

No implementar auto-modificación completa al inicio. Progresión, cada nivel debe demostrar
estabilidad (evaluación + rollback + sandbox) antes de avanzar:

- **Nivel 1 — Observación:** el sistema mide y reporta su propio comportamiento.
- **Nivel 2 — Recomendaciones:** propone cambios; un humano/test los aprueba.
- **Nivel 3 — Herramientas propias:** genera utilidades verificadas (scan de imports +
  sandbox con timeout) antes de ejecutarlas.
- **Nivel 4 — Módulos modificables:** edita módulos acotados con tests de regresión que deben
  pasar.
- **Nivel 5 — Rediseño controlado:** cambios arquitectónicos con gates duros y reversibilidad.

Gate entre niveles: 0 regresiones en la suite + reproducibilidad mantenida + rollback probado.

---

## 8. Restricciones (duras)

Prohibido:
- Sustituir el proyecto por un modelo existente "y ya".
- Declarar una solución sin evidencia.
- Considerar terminada una investigación sin pruebas corridas.
- Aceptar afirmaciones por consenso/tradición.
- Mocks, stubs, números inventados, citas inventadas.

Permitido y alentado:
- Reutilizar matemáticas, principios e ideas.
- Reimplementar componentes desde cero.
- Desechar componentes que no se justifiquen.

Heredado del repo (CLAUDE.md): usar siempre `venv312\Scripts\python.exe`; nunca commitear
secretos; validar código generado (allowlist de imports + sandbox) antes de ejecutarlo.

---

## 9. Documentación persistente (`cognia_x/manager/`)

Mínimos (nunca borrar histórico, solo añadir revisiones):

- `paper.md` — paper científico vivo: preguntas, hipótesis, evidencia, resultados, errores,
  conclusiones, próximos pasos.
- `roadmap.md` — fases y estado.
- `research_log.md` — bitácora append-only de cada sesión/ciclo.
- `architecture.md` — la arquitectura propuesta y su justificación por componente.
- `experiments.md` — fichas de experimentos (diseño + cómo correr + resultado).
- `assumptions.md` — supuestos explícitos con estado {no-verificado/apoyado/refutado}.
- `hypotheses.md` — todas las hipótesis con su evidence ledger.
- `future_work.md` — direcciones futuras.
- `decision_log.md` — decisiones tomadas, con fecha y razón.

**Contexto persistente:** asumir que futuras sesiones tendrán contexto limitado. Resumir
decisiones, mantener estado de avance, guardar resultados reproducibles. La documentación
debe bastar para continuar sin perder información crítica.

---

## 10. Criterio de éxito

El éxito NO es terminar rápido. El éxito es **evidencia convincente** de que una arquitectura
propuesta es más eficiente, aprende mejor, consume menos recursos, o demuestra principios
superiores frente a las alternativas evaluadas — y que el resultado es **reproducible**.

Si tras investigación rigurosa una técnica actual sigue siendo óptima, se documenta *por qué*.
Si se encuentra una alternativa mejor, se demuestra su superioridad con experimentos repetibles.

---

## Apéndice A — Diferencias clave frente al prompt original

El prompt original (conservado abajo) era excelente en *intención* pero débil en
*operacionalización*. Esta versión añade:

1. **Artefacto obligatorio por cada paso del ciclo** (tabla §2): el ciclo deja de ser una
   lista de buenas intenciones y se vuelve trazable.
2. **Definition of Done por ciclo** (§5): criterio binario de cuándo algo está "hecho".
3. **Evidence Ledger con formato fijo** (§4): evidencia a favor/en contra + veredicto
   adversarial estructurado, no prosa suelta.
4. **Presupuesto de hardware concreto + insight clave** (§3): "memory-bandwidth-bound"
   reordena las prioridades de optimización; antes solo decía "pensar en CPU".
5. **Gates de estabilidad explícitos entre niveles de auto-mejora** (§7).
6. **Nivel de confianza + fuentes obligatorios** en cada afirmación (§1.5).
7. **Prohibición explícita de citas/números inventados** y reafirmación de "código que corre
   o no cuenta" (§8), alineado con CLAUDE.md.
8. **Anclaje a `venv312` y validación de código generado** heredados del repo.

El espíritu (no aceptar por autoridad, refutar, primeros principios, persistencia) se mantiene
intacto; lo que cambia es que ahora es *ejecutable y verificable*.

---

## Apéndice B — Prompt original (conservado, no modificar)

> Ver `cognia_x/manager/_prompt_original.md` para la transcripción literal del prompt
> fundacional entregado por el dueño el 2026-06-17.

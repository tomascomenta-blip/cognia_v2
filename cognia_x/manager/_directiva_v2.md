# Directiva de Investigación, Aprendizaje y Mejora Continua — v2 (mejorada y ejecutable)

> Versión mejorada del prompt-directiva entregado por el dueño el 2026-06-19.
> El original se conserva al final (Apéndice). Esta v2 **no cambia el espíritu** — lo vuelve
> *operativo, medible y enforzado por código* (`cognia_x/research/`). Regla raíz heredada:
> nunca se borra información histórica; solo se añade. La pérdida de conocimiento es un fallo.

---

## 0. Principio general (sin cambios de espíritu, afilado)
Asume que toda limitación es mejorable **hasta que exista evidencia sólida de lo contrario**.
Distinguir SIEMPRE tres estados, no dos:
- **"No encontré una solución"** (búsqueda incompleta) ≠
- **"No existe una solución bajo estas restricciones"** (cota probada, con las restricciones explícitas) ≠
- **"Existe pero no la alcanzamos por X"** (gap real vs asumido).

Mejora v2: una afirmación de imposibilidad **solo es válida si nombra la cota y la fuente** (un
teorema, un límite físico, un benchmark reproducible). Sin eso, es "no encontré", no "no existe".

## 1. Calidad de información — jerarquía CON regla de enforcement
Prioridad (tier, menor = mejor):
1. Papers revisados por pares · 2. Libros académicos · 3. Documentación técnica oficial ·
4. Benchmarks reproducibles · 5. Datos experimentales propios (reproducibles) · 6. Fuentes secundarias verificadas.

Reglas v2 (las hace el `EvidenceLedger`, no la buena voluntad):
- **Nunca optimizar solo con opiniones** → una *decisión importante* DEBE citar ≥1 fuente de tier ≤ 4,
  o ≥1 dato propio (tier 5) reproducible. El ledger **rechaza** una decisión importante sin esa fundación.
- **Cita trazable o no cuenta.** Toda fuente lleva referencia resoluble (DOI/arXiv/URL/expNNN). Citas
  o números inventados están prohibidos (hard rule del repo). Si una fuente no se pudo obtener, se
  registra `obtenida=false` honestamente — no se inventa.
- **Tier propio (5) es de primera clase** cuando es reproducible: un experimento corrido en `venv312`
  con semilla fija vence a una opinión de tier 6 y complementa a un paper de tier 1.

## 2. Sistema de Analogías Universales — 7 etapas, como artefacto verificado
Ante un problema difícil, NO atacarlo directo. Recorrer y **dejar registro de las 7 etapas**
(`AnalogyRecord` valida que las 7 existan antes de "extraer principio"):
1. Describir el problema simple. 2. Convertir a situación cotidiana (memoria→biblioteca,
atención→linterna, planificación→viaje, compresión→resumir apuntes, recuperación→encontrar un libro).
3. Resolver la cotidiana — **generar múltiples soluciones** (≥3). 4. Extraer los principios
fundamentales. 5. Adaptar los principios al sistema. 6. **Medir** resultados. 7. Repetir hasta
hallar algo superior *o* acumular evidencia de que lo actual es óptimo (con su cota).

## 3. Persistencia investigativa — el fracaso aumenta el conocimiento
No abandonar una línea por difícil. Cuando algo falla, registrar (obligatorio, `Hypothesis`/`record`):
qué se intentó · por qué falló · qué se aprendió · qué hipótesis nuevas genera. Un experimento
refutado **cierra** con estado `refutada` + lección, nunca se borra. (Ejemplo vivo: CYCLE 9
"aprendizaje por sorpresa" refutado — quedó documentado y generó la línea de congelar-tronco.)

## 4. Mejora paralela del razonamiento — track propio, nunca "terminado"
Mantener un eje dedicado y continuo (no un módulo cerrado): razonamiento lógico, causal,
planificación, autocrítica, detección de errores, estimación de incertidumbre, primeros principios.
v2: este track tiene su propio backlog en `future_work.md` y su propio ledger; cada ciclo debe poder
nombrar **qué dimensión de razonamiento tocó** (el Pilar 5 / `cognia_x/reason/` es su encarnación medible).

## 5. Búsqueda del techo teórico — por subsistema, real vs asumido
Periódicamente, por cada subsistema, responder y registrar (`CeilingRecord`):
- ¿Cuál es el límite teórico **conocido** (con fuente)? ¿Qué impide alcanzarlo?
- Clasificar cada bloqueo en **físico / de diseño / histórico**.
- Distinguir **límite real (probado)** de **límite asumido (heredado sin prueba)**.
v2: el `CeilingRecord` obliga a separar las tres clases y a marcar `real|asumido` con su evidencia.
Un "límite asumido" es una invitación a refutar, no una pared.

## 6. Escalabilidad obligatoria — documentar o no se acepta
Todo componente nuevo documenta (`ScalabilityNote`, enforzada en el ciclo): complejidad temporal,
complejidad espacial, comportamiento en CPU (el presupuesto del lab: ~2c/4t, sin GPU, memory-bandwidth-bound),
comportamiento multi-dispositivo, y estrategia de distribución futura. **Evitar soluciones que solo
viven en prototipos chicos**: si algo solo escala como prototipo, se dice explícitamente.

## 7. Registro permanente — la pérdida de conocimiento es un fallo del sistema
Toda investigación queda documentada y **append-only**: hipótesis, experimentos, métricas, resultados,
errores, decisiones, revisiones, mejoras descartadas, mejoras aceptadas. v2: el `record` journaliza
cada escritura del engine y ofrece `verify_no_loss()` (chequeo de integridad). Los markdown de
`manager/` siguen siendo la vista humana; el engine es la vista enforzada/máquina.

## 8. Metaobjetivo — construir el PROCESO, no "una IA que funcione"
El objetivo es un **proceso de investigación capaz de descubrir arquitecturas cada vez mejores de
forma sistemática, reproducible y acumulativa.** v2 lo operacionaliza: `cognia_x/research/` es ese
proceso *como código ejecutable y testeado*, de modo que el método no dependa de que un agente se
acuerde de seguirlo — el engine lo exige.

---

## Apéndice — Qué mejoró v2 frente a la directiva original (changelog)
1. **Imposibilidad con cota nombrada** (§0): "no existe" exige teorema/límite/benchmark, no es default.
2. **Jerarquía de evidencia ENFORZADA** (§1): decisión importante sin fuente tier≤4 o dato propio
   reproducible → rechazada por el ledger. Antes era una preferencia; ahora es una compuerta.
3. **Analogía de 7 etapas como artefacto validado** (§2): el registro exige las 7 etapas y ≥3
   soluciones antes de "extraer principio". Antes era prosa libre.
4. **Techo teórico con taxonomía físico/diseño/histórico + real/asumido** (§5): estructura que la
   directiva pedía en intención pero no en formato.
5. **Escalabilidad como requisito de aceptación** (§6): complejidad + CPU + multi-dispositivo
   documentadas o el componente no se acepta.
6. **Registro permanente con verificación de integridad** (§7): `verify_no_loss()` hace de "la
   pérdida de conocimiento es un fallo" algo chequeable, no un eslogan.
7. **El proceso se vuelve CÓDIGO** (`cognia_x/research/`): el metaobjetivo deja de ser aspiracional y
   pasa a ser ejecutable, testeado y reproducible — alineado con "código que corre o no cuenta".
8. **Continuidad con v1** (`00_protocolo_investigacion.md`): v2 integra esta directiva con el protocolo
   epistémico v1 (falsabilidad, refutar-antes-de-aceptar, DoD por ciclo) sin contradecirlo.

## Apéndice — Directiva original (conservada, no modificar)
Ver el prompt entregado por el dueño el 2026-06-19 en el historial de `MANAGER_LOG.md` / la invocación
`/manager`. Núcleo: principio general, jerarquía de calidad, analogías universales, persistencia,
razonamiento paralelo, techo teórico, escalabilidad, registro permanente, metaobjetivo. "Mejora ESTE
PROMPT y EJECÚTALO tú mismo, 100% autónomo."

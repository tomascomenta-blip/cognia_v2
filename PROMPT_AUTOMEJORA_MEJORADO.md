# Prompt mejorado — Auto-mejora de Cognia: herramientas autónomas + investigación + memoria

> **Versión reescrita** del prompt original "Sistema de Herramientas Autónomas e
> Investigación Continua". El original pedía *construir desde cero* una arquitectura que
> **ya existe en ~80%** (lo confirmó `AUDITORIA_ARQUITECTURA_IA_20260615.md`). Este prompt
> reorienta el trabajo a lo que de verdad falta: **cablear, completar y VERIFICAR** los
> subsistemas reales bajo las reglas duras del repo, con criterios de aceptación medibles.

## 0. Principio rector (leer antes de tocar nada)

**No reconstruir lo que existe. Cablear y cerrar gaps, con verificación real.** Antes de
implementar cualquier pieza: leer el componente real, ejecutarlo y confirmar qué hace HOY.
La métrica de éxito de cada sub-sistema es una **demostración E2E reproducible** (CLI o
script contra el modelo/DB reales), no un test que pasa en aislamiento ni un prototipo.

Reglas duras (de `CLAUDE.md` + vault `CogniaVault/brain`), **no negociables**:
- Sin PyTorch en nodos; numpy puro. Backend de inferencia real = **llama.cpp/GGUF** vía
  `ShatteringOrchestrator.infer` (`_try_load_llama` carga in-process en venv312). Sin Ollama.
- **Sin `sqlite3.connect()` directo** → `storage/db_pool.py`. En código nuevo usar SIEMPRE
  `with get_pool(db).get() as conn:` (o try/finally); el `close()` dentro de un `try` fuga la
  conexión si salta una excepción (mitigado por `_PooledConnection.__del__`, pero no abusar).
  Vigilar `pool_stats()["gc_reclaimed"]` (>0 = hay un call-site fugando).
- Sin constantes de modelo hardcodeadas → `shattering/model_constants.py`.
- **Nada de mocks/stubs como entregable**: "código que corre o no cuenta". Cada subsistema
  cierra con prueba CLI/E2E real mostrando output.
- Código generado o ejecutado: SIEMPRE scan estático de imports (allowlist) + sandbox con
  timeout antes de registrarlo o correrlo (`code_executor.run_python` + `validate_python`).
- Hardware objetivo: i3, ~8 tok/s. Presupuesto de inferencia por operación EXPLÍCITO y bajo;
  escalar con el nivel `/esfuerzo` (`cognia/effort_levels.py`), no con números mágicos.
- Cero datos personales centralizados. FedAvg solo sobre adapters LoRA (nunca params completos).
- Cada unidad verificada → commit enfocado (qué/por qué/cómo se verificó) + push +
  entrada en `MANAGER_LOG.md`.

---

## Sistema 1 — Auto-creación de herramientas/módulos

**Ya existe (`cognia_v3/core/self_architect.py` + `sandbox_tester.py` + `scoring_engine.py`):**
- Detección de necesidad: `DiagnosticEngine`, `TrendAnalyzer`, `FatigueAdvisor` (alimentan el ciclo).
- Propuesta: `ChangeProposer` (params) y `ModuleProposer` (módulos nuevos) → tabla
  `architecture_proposals` (nombre, problema, modificación, why_better, riesgos, impacto, ROI).
- Generación de código: `generate_module_code` (FASE 7c: vía `ShatteringOrchestrator`, con
  fallback a esqueleto; sin Ollama).
- Validación en sandbox: `sandbox_tester.test_module_from_code` (`validate_python` +
  `run_python` aislado con timeout) → report {passed, criteria}.
- Decisión por ROI: `StrategySelector` (usa `MetaLearningTracker`), `ChangeApplicator`.

**Gaps a cerrar (con criterio de aceptación):**
1. **Benchmark sin-herramienta vs con-herramienta.** Hoy `test_proposal` valida que el módulo
   *ejecuta*; falta comparar utilidad medible. Implementar un micro-benchmark: para la tarea
   que motivó la herramienta, medir (exactitud/latencia/tokens) con y sin ella.
   *Aceptación:* un módulo aceptado muestra `delta_utilidad > umbral_configurable`; uno que no
   mejora se DESCARTA (status `code_rejected`), demostrado con un caso real de cada tipo.
2. **Umbral configurable** vía `architecture_params` (no hardcode). *Aceptación:* cambiar el
   umbral cambia la decisión sin tocar código.
3. **Registro de herramientas útiles** que sobreviven, recuperables después (ver Sistema 3).

---

## Sistema 2 — Investigación autónoma por incertidumbre

**Ya existe:**
- Detector de gaps: `gap_detector` (KGAD) registra gaps cuando `ResponseGate` detecta calidad
  < 0.4; `curiosity_engine` (`KnowledgeGapFinder`, `ContradictionHunter`) calcula score de
  curiosidad (uncertainty/novelty/knowledge_gap/hypothesis_potential).
- Investigación: `investigador.guardar_en_cognia`, loop científico `cognia.investigate`
  (hipótesis→evaluar→analogías→validar, ya escala con `/esfuerzo`), `curiosidad_pasiva` (daemon).
- Web/repos: tools de búsqueda + `aprende_repo`.

**Gaps a cerrar:**
1. **Disparador automático de investigación** cuando la confianza cae bajo umbral, SIN que el
   usuario lo pida. Hoy el gap se *encola*; falta el lazo que lo *consuma* proactivamente
   (un tick acotado en `CuriosityWorker`). *Aceptación:* una respuesta de baja confianza
   genera —en background, presupuesto acotado— una investigación cuyo resultado queda
   disponible para el siguiente turno (demostrado E2E).
2. **Estimación de confianza unificada** (confianza + cobertura KG + antigüedad). *Aceptación:*
   función pura testeable que combina las señales y dispara sobre umbral configurable.
3. **Priorizar fuentes primarias** en el ranking de búsqueda (doc oficial/papers/repos > blogs).

---

## Sistema 3 — Memoria de aprendizaje (no de conversaciones)

**Ya existe:** `consolidation_engine` (purga/consolida/refuerza/decae), `semantic`/`episodic`,
`code_memory` (snippets/errores/soluciones), `feedback_engine`, KG, `ProjectMemory` (flujos),
recuperación vía `band_router` (HYDRA) + `semantic_search` + `_build_memory_block_for`.

**Gaps a cerrar:**
1. **"Guardar solo lo útil"** explícito: un gate de retención que separe conocimiento valioso
   (errores corregidos, soluciones, heurísticas, herramientas útiles) de ruido/temporales,
   antes de persistir. *Aceptación:* dado un lote mixto, solo lo útil queda en memoria
   (medible: N guardados vs M descartados, con la razón).
2. **Recuperación de "experiencias previas similares" inyectada automáticamente** antes de
   responder (ya hay band_router; falta el canal "investigaciones previas + herramientas
   relevantes"). *Aceptación:* una query repetida reusa la solución previa (cache hit medible).

---

## Sistema 4 — Ciclo de auto-mejora continua

**Ya existe:** `SelfArchitect.tick`/cycle (evaluate→diagnose→propose→rank→apply),
`SafeImprover` (`cognia/agents/self_improvement.py`), loop de curiosidad.

**Gap a cerrar:** **encadenar el lazo completo, end-to-end, demostrable**:
`detectar → investigar → aprender → (crear herramienta si aplica) → probar en sandbox →
benchmark → decidir → guardar → actualizar memoria → mejorar la próxima respuesta`.
*Aceptación:* una corrida real del lazo, con un problema concreto, produce un artefacto
(herramienta aceptada/rechazada con razón, o creencia actualizada) persistido y recuperable
en el siguiente turno. Presupuesto de inferencia del lazo acotado y escalado por `/esfuerzo`.

### Corrección de creencias (parte de S2+S4)
Cuando evidencia nueva contradice conocimiento previo, actualizar el KG/semántica y
**registrar la transición** (creencia antigua → evidencia → nueva creencia → motivo). Reusar
`ContradictionDetector`/`consistency_checker`. *Aceptación:* un caso real de contradicción
queda auditado con las 4 partes y el KG refleja la nueva creencia.

---

## Sistema 5 — Seguridad (transversal)

**Ya existe:** `code_executor.run_python` (subproceso aislado + timeout), `validate_python`
(scan estático), `sandbox_tester`.

**Gaps a cerrar:**
1. **Allowlist de imports explícita y auditada** para todo código auto-generado (regla 9 de
   CLAUDE.md). *Aceptación:* un módulo con import fuera de la allowlist es RECHAZADO antes de
   ejecutarse (test que lo demuestra).
2. **Log de auditoría** de toda acción de auto-modificación (propuesta, código generado, test,
   decisión, aplicación) — ya hay `ArchitectureLog`; verificar cobertura y que nada se aplica
   sin pasar validación. *Aceptación:* la auditoría reconstruye qué se cambió, cuándo y por qué.

---

## Fases de ejecución (una unidad verificada a la vez)

Cada fase: **verificar lo existente → implementar el gap → test de regresión (que falle sin el
fix) → verificación CLI/E2E REAL con output → suite completa como compuerta → commit + push +
`MANAGER_LOG`.** Si una fase necesita una decisión del dueño (p.ej. tocar producción o algo
irreversible), PARAR y preguntar.

1. **S5 primero** (seguridad es prerrequisito): allowlist auditada + verificar log. *Barato,
   desbloquea lo demás.*
2. **S1 benchmark + decisión por utilidad** (cierra el "mantener solo lo útil" de herramientas).
3. **S3 gate de retención + recuperación de experiencias** (la memoria que S4 necesita).
4. **S2 disparador automático de investigación + confianza unificada**.
5. **S4 lazo completo E2E** (integra 1–3) + corrección de creencias auditada.
6. **Demostración final**: un script/CLI que ejecute el lazo de punta a punta sobre un caso
   real y muestre los 4 artefactos del "Resultado esperado".

---

## Resultado esperado (medible, no narrativo)

Al cerrar, debe poder DEMOSTRARSE en vivo (CLI/E2E, output real):
1. **Creación de herramienta autónoma**: Cognia detecta una limitación, genera un módulo, lo
   valida en sandbox, lo benchmarkea y lo **conserva o descarta según utilidad medida**
   (mostrar un aceptado y un rechazado con su razón).
2. **Investigación autónoma**: una respuesta de baja confianza dispara investigación en
   background (presupuesto acotado) y el resultado se usa en el siguiente turno.
3. **Aprendizaje persistente**: solo conocimiento útil queda en memoria; una query repetida
   reusa la solución previa (hit medible).
4. **Actualización de creencias por evidencia**: una contradicción real queda auditada
   (vieja→evidencia→nueva→motivo) y el KG refleja el cambio.
+ Documentación técnica + tests automatizados por fase + 0 `sqlite3.connect` directos +
  `gc_reclaimed == 0` + suite completa verde.

**Trabajar autónomo, fase por fase, verificando resultados, sin esperar instrucciones** —
pero deteniéndose ante decisiones del dueño o acciones irreversibles.

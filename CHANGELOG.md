# Cognia — Registro de Cambios

---

## [2026-05-04] Sesión de revisión y corrección de bugs

### BUG #1 — CRÍTICO: `NameError: pattern_info` en `sleep()`
**Archivo:** `cognia/cognia.py` — método `sleep()`  
**Síntoma:** Cada llamada a `dormir` (o `sleep()`) terminaba con un `NameError` porque la variable `pattern_info` se referenciaba en el `return` final (línea 886) sin haber sido definida en ningún lugar del método.  
**Causa raíz:** Código preparado para integrar un `_goal_engine.run_pattern_batch()` que nunca llegó a implementarse; la variable quedó referenciada pero no inicializada.  
**Corrección:** Se añadió `pattern_info = ""` al inicio del bloque de hipótesis espontáneas, antes de cualquier `try/except`. La variable queda vacía por defecto y puede asignarse cuando el motor de patrones esté implementado.  
**Impacto:** El ciclo de sueño (consolidación, olvido, hipótesis, investigación autónoma) estaba completamente roto. Esta corrección restaura el funcionamiento básico del sistema.

---

### BUG #2 — CRÍTICO: `NameError: context` en bypass de preguntas sociales
**Archivo:** `language_engine.py` — método `respond()`, Stage 0.5  
**Síntoma:** Cualquier pregunta de tipo "social" (saludo, "¿qué eres?", "hola", etc.) causaba un `NameError` porque el campo `tiene_contexto` del `EngineResult` de retorno usaba `bool(context)`, pero `context` solo se define en la línea 485 (Stage 3/4), que nunca se alcanza en el bypass social.  
**Causa raíz:** El bypass social (Stage 0.5) sale del método antes de que `context` sea construido. Se copió un campo del bloque LLM completo sin adaptar al contexto del bypass.  
**Corrección:** Se reemplazó `bool(context)` por `bool(pre_built_context)`, que sí existe como parámetro del método desde el inicio.  
**Impacto:** Cognia fallaba al responder cualquier saludo o pregunta de identidad — el punto de entrada más común para usuarios nuevos.

---

### BUG #3 — MENOR: `except Exception: pass` silencia errores en `sleep()`
**Archivo:** `cognia/cognia.py` — método `sleep()`, bloque de hipótesis espontáneas  
**Síntoma:** Si el módulo de hipótesis fallaba (p.ej. por un error en `self.semantic.list_all()` o en `cosine_similarity()`), el error desaparecía sin dejar rastro en los logs.  
**Corrección:** Cambiado `except Exception: pass` por `except Exception as _e: logger.warning(...)` para registrar el fallo con contexto.  
**Impacto:** Facilita el diagnóstico cuando el ciclo de sueño genera 0 hipótesis de forma inexplicada.

---

### MEJORA #1 — Logging en sustitución silenciosa de predicados del KG
**Archivo:** `cognia/knowledge/graph.py` — método `add_triple()`  
**Situación anterior:** Si `add_triple()` recibía un predicado no reconocido (no en `VALID_RELATIONS`), lo reemplazaba silenciosamente por `"related_to"` sin ningún log, dificultando detectar errores en la extracción de triplas.  
**Corrección:** Se añadió un `_kg_logger.debug(...)` que registra el predicado original y los nodos afectados antes de la sustitución. El comportamiento de negocio no cambia.  
**Impacto:** Permite identificar qué predicados llegan incorrectos desde los extractores de triplas sin cambiar la lógica de almacenamiento.

---

## Estado del sistema tras los cambios

| Componente | Estado |
|---|---|
| `sleep()` / ciclo de sueño | ✅ Funcional |
| Respuestas sociales (Stage 0.5) | ✅ Funcional |
| VectorCache (invalidación) | ✅ Ya corregido (hash incluye importance+confidence) |
| KG — sustitución de predicados | ✅ Ahora logeado |
| Bare `except` en hipótesis | ✅ Ahora logeado |

---

## Bugs conocidos pendientes (sin corrección en esta sesión)

- **DB schema migration**: no hay validación ni migración automática entre versiones del schema. Si `cognia_memory.db` viene de una versión anterior con columnas faltantes, los INSERTs fallan silenciosamente.
- **CognitiveProfile no integrado completamente**: `AttentionSystem` solo se reconstruye cuando se aplica feedback; los cambios de peso no se validan en tests de integración.
- **FatigueMonitor sin reset de estado**: si el módulo falla en `__init__`, el dict de adaptaciones queda hardcodeado y el throttling nunca funciona.

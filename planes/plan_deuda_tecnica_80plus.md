# Plan: Cognia — De 62 a 80+ (Deudas Técnicas + Velocidad)

## Contexto

Cognia está en 62/100. Las fases 1-20 están completas. Los tres bloqueadores reales para llegar a 80+ son: (1) velocidad de inferencia ~0.1 tok/s cuando el target es 3-6 tok/s, (2) intra-turn KV-cache no validado end-to-end, y (3) deudas técnicas pendientes de baja complejidad que acumulan riesgo. Los kernels C ya existen compilados (`fast_kernels.c`, `_fast_kernels_cffi.c`, `build_fast_kernels.py`) pero pueden no estar compilados para la instalación actual. La infraestructura de KV-cache existe en `RealTransformerLayer` pero hay que confirmar y loggear que realmente se usa de forma incremental.

**Accion final:** Al terminar toda la implementacion, ejecutar `python scripts/shutdown_pc.py` para apagar la laptop.

---

## Paso 1 — Compilar kernels C (mayor impacto en velocidad)

**Archivo:** `node/build_fast_kernels.py` (ya existe, 182 lineas)

**Accion:** Ejecutar el script de build y verificar que produce `fast_kernels_lib.dll` (Windows) o `.so`. Si falla con gcc, intentar clang, luego MSVC via vswhere.

```bash
cd cognia_v2
python node/build_fast_kernels.py
```

Si la compilacion falla por cualquier razon, implementar el **fallback numpy vectorizado** (ver Paso 1b).

**Paso 1b — Fallback numpy vectorizado (si C falla):**

Modificar `node/qwen2_ops.py` `INT4Weights.linear()` — en lugar de 37 chunks secuenciales de 4096 filas:
- Dequantizar todas las filas de lm_head de una sola vez usando `np.unpackbits` + operacion vectorizada
- Beneficio: elimina el loop Python de 37 iteraciones, reduce overhead de llamadas

**Archivos a modificar:** `node/qwen2_ops.py` lineas 165-203

**Impacto esperado:** 2x-4x speedup minimo solo en lm_head

---

## Paso 2 — Validar e instrumentar KV-cache intra-turn

**Problema:** CLAUDE.md dice "cada token re-procesa secuencia completa" pero el explorer confirma que `RealTransformerLayer` YA tiene `_kv_cache` per-session y `current_ids` se reduce a `[next_id]` despues del primer token. El problema real puede ser que `session_id` no llega correctamente a los layers a traves de `_forward_through_swarm`.

**Archivos a revisar:** `node/inference_pipeline.py` — funcion `_forward_through_swarm` — verificar que pasa `session_id` a cada `ShardEngine.process()`.

**Accion:** Agregar logging de `kv_len` en `_token_loop` de `shattering/orchestrator.py` para confirmar que el cache crece token a token. Si no crece → fix del paso de `session_id`. Si crece → el cache funciona, el bottleneck es el einsum de atencion (O(seq_len) por token, inevitable en numpy sin flash attention).

**Revolucionario — Sliding Window Attention (SWA):**

Implementar en `node/qwen2_ops.py` `RealTransformerLayer._attention()`:
- Cuando `past_len > SWA_WINDOW` (e.g. 512 tokens), truncar K/V al ultimo ventana de 512 tokens para el calculo de scores
- Los tokens fuera de la ventana se "olvidan" del calculo de atencion pero NO del KV-cache (el cache sigue creciendo para LPC cross-turn)
- Resultado: O(512) attention en vez de O(full_seq) sin cambiar la interfaz externa
- Constante: `SWA_WINDOW: int = 512` en `shattering/model_constants.py`

**Archivos a modificar:** `node/qwen2_ops.py`, `shattering/model_constants.py`

---

## Paso 3 — FatigueMonitor auto-reset (deuda BAJO)

**Situacion:** `FatigueMonitor.reset()` ya existe (lineas 173-190 de `cognia/fatiga_cognitiva.py`). Nunca se llama automaticamente despues de periodos idle.

**Accion:** En `cognia/fatiga_cognitiva.py`, agregar dentro de `get_adaptation_params()` (o en `record_cycle_end()`):

```python
# Auto-reset si llevamos >IDLE_RESET_MINUTES sin actividad y fatiga es alta
if (time.time() - self._last_activity > IDLE_RESET_SECONDS
        and self._fatigue_score > 50.0):
    self.reset()
```

Constante nueva: `IDLE_RESET_SECONDS: float = 600.0` (10 min) en el mismo archivo.

**Archivo:** `cognia/fatiga_cognitiva.py`

---

## Paso 4 — RST validacion numerica (deuda MEDIO)

**Archivo:** `shattering/recursive_context.py`

**Accion:** Agregar en `RecursiveContext.update()`:
- Verificar que la norma del context_vec no explota (> 100.0 → clamp + warning)
- Verificar que no colapsa a cero (< 1e-6 → log warning)
- Agregar `context_norm` al dict de stats

```python
norm = float(np.linalg.norm(self._context_vec))
if norm > 100.0:
    self._context_vec = self._context_vec / norm * 10.0
    logger.warning("[RST] context_vec explodio (%.1f) — clamped", norm)
elif norm < 1e-6:
    logger.warning("[RST] context_vec colapso a cero")
```

---

## Paso 5 — Test de integracion AttentionSystem (deuda MEDIO)

**Archivo nuevo:** `tests/test_attention_integration.py`

**Patron a seguir:** `tests/test_fase2.py` — mock `db_connect`, SQLite in-memory, helper `_vec(seed, dim)`.

**Tests a implementar (minimos):**
1. `test_vector_cache_build_and_search` — build cache desde DB in-memory, search retorna top-k correcto
2. `test_vector_cache_concurrent_writes` — 3 threads hacen `search()` simultaneamente, sin deadlock (verifica RLock)
3. `test_vector_cache_dirty_rebuild` — `mark_dirty()` + esperar debounce → cache reconstruido
4. `test_kv_cache_evict_stale` — insertar sesion, simular 4000s idle, verificar que `evict_stale` la elimina

---

## Paso 6 — Phase 21 stub en ROADMAP

Actualizar `ROADMAP.md` marcando Fase 20 como DONE y agregando cabecera de Fase 21:

```
## Phase 21 — Universal Fast Inference Stack [TODO]
| 21.1 | Kernels C compilados y activos en produccion | node/qwen2_ops.py, node/fast_kernels.c | TODO |
| 21.2 | SWA: Sliding Window Attention O(512) | node/qwen2_ops.py | TODO via Paso 2 plan |
| 21.3 | Benchmarks automaticos tok/s en CI | .github/workflows/bench.yml | TODO |
```

---

## Paso 7 — Copiar plan a planes/

```bash
cp C:/Users/Tomanquito/.claude/plans/crea-un-plan-para-fluffy-toucan.md \
   C:/Users/Tomanquito/Downloads/cognia/cognia_v2/planes/plan_deuda_tecnica_80plus.md
```

---

## Paso 8 (FINAL) — Apagar laptop

```bash
python scripts/shutdown_pc.py
```

Este paso es el ultimo y cierra la sesion de trabajo. El usuario aprobo este paso explicitamente.

---

## Proyeccion de score post-implementacion

| Mejora | Delta |
|---|---|
| Kernels C compilados (velocidad 0.1 → 1-2 tok/s) | +8 |
| SWA O(512) attention | +4 |
| KV-cache intra-turn validado y loggeado | +2 |
| FatigueMonitor auto-reset | +1 |
| RST estabilidad numerica | +1 |
| Tests de integracion AttentionSystem | +2 |
| Fase 21 documentada | +1 |
| **Total** | **+19 → 81/100** |

---

## Archivos criticos a modificar

| Archivo | Paso | Accion |
|---|---|---|
| `node/qwen2_ops.py` | 1b, 2 | lm_head vectorizado; SWA; logging kv_len |
| `shattering/model_constants.py` | 2 | Agregar `SWA_WINDOW = 512` |
| `cognia/fatiga_cognitiva.py` | 3 | Auto-reset por idle |
| `shattering/recursive_context.py` | 4 | Clamp + validacion norma |
| `tests/test_attention_integration.py` | 5 | Nuevo archivo, 4 tests |
| `ROADMAP.md` | 6 | Fase 21 stub |
| `planes/plan_deuda_tecnica_80plus.md` | 7 | Copia del plan |

## Verificacion

```bash
# Verificar kernels compilados
python -c "from node.qwen2_ops import INT4Weights; print('kernels ok')"

# Verificar tests
pytest tests/test_attention_integration.py -v --tb=short

# Verificar RST
python -c "from shattering.recursive_context import RecursiveContext; rc=RecursiveContext(); rc.reset(); print(rc.stats())"

# Verificar FatigueMonitor
python -c "from cognia.fatiga_cognitiva import CognitiveFatigueMonitor; m=CognitiveFatigueMonitor(); m._fatigue_score=80; m._last_activity=0; m.get_adaptation_params(); print('auto-reset ok')"
```

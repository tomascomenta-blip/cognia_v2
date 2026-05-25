# Plan: Inferencia Rápida y Optimización de Arquitectura Cognia

## Estado
| Fase | Estado | Completado |
|------|--------|-----------|
| A — Fix Bugs Bloqueantes | DONE | 2026-05-21 |
| B — Numba JIT SIMD | PARCIAL | 2026-05-21 — codigo JIT listo con fallback; bloqueado por Python 3.14 (numba requiere <=3.12) |
| C — Speculative Decoding | DONE | 2026-05-21 — nano_draft + build_draft_model + spec loop en orchestrator |
| D — Android / ONNX / Pipeline | PENDIENTE | — |

---

## Context

El pipeline de inferencia local tiene **3 bugs bloqueantes** que causan los 10+ minutos sin
respuesta, más 2 oportunidades de optimización de arquitectura que, combinadas, producen
una mejora estimada de 100-500x sobre el estado actual.

**Bugs bloqueantes confirmados por exploración:**
1. `/infer-stream` espera todos los tokens antes de enviar cualquier byte al cliente
   (fake streaming con split por palabras + sleep de 20ms). El usuario ve cero feedback.
2. KV-cache completamente desconectado: session_id se genera pero se pierde en
   `process_bytes()` — cada token re-procesa las 36 capas desde cero (coste O(N²)).
3. `patch_shard_engine_mla()` nunca se invoca en `_build_local_pipeline()` —
   los ShardEngines corren sin MLAModule, sin cache, sin RoPE distribuido.

**Propuesta revolucionaria:** Draft-First Local Speculation + Numba JIT SIMD.
- Draft local (nano-model 2 capas, numpy puro, ~40MB) genera 6 tokens en ~2ms
- Shard chain verifica todos en UN solo forward pass batch
- Numba JIT compila INT4 matmul a instrucciones SIMD nativas (no requiere Rust/C)
- Combinado con KV-cache: latencia objetivo 2-8 segundos para respuesta de 20 tokens

---

## Fase A — Fix Bugs Bloqueantes [DONE 2026-05-21]

### A1: Real Token Streaming [DONE]
**Problema:** `cognia_desktop_api.py:168-200` — `ainfer()` bloquea hasta tener el texto completo.

**Fix aplicado:** `astream()` async generator en orchestrator. El endpoint SSE yielda
cada token inmediatamente via queue thread-safe. `_shard_infer_stream()` pone tokens
en la queue conforme se generan.

**Archivos modificados:**
- `cognia_desktop_api.py:168-200`
- `shattering/orchestrator.py` — `astream()`, `_shard_infer_stream()`

### A2: Logging en Token Loop [DONE]
**Fix aplicado:** `_token_loop` y `_shard_infer_stream` loggean tok/s cada 10 tokens.

### A3: KV-Cache End-to-End [DONE]
**Fix aplicado en cascada:**

| Archivo | Cambio |
|---------|--------|
| `node/qwen2_ops.py` | `RealTransformerLayer._kv_cache` dict; `_attention(session_id)` acumula K/V con RoPE offset correcto |
| `node/qwen2_ops.py` | `_precompute_rope(offset=0)` para posiciones correctas en decode |
| `node/shard_engine.py` | `process(session_id)`, `process_bytes(session_id)`, `forward(session_id)` |
| `node/inference_pipeline.py` | `_single_forward_pass` pasa session_id a `process_bytes` |
| `shattering/orchestrator.py` | session_id unico por llamada `f"local_{time()}"` |

**Speedup logrado:** 2-3x por KV-cache + primer token visible en <30s.

---

## Fase B — Numba JIT SIMD [PENDIENTE]

### B1: Numba en INT4Weights.linear()
**Por que Numba y no WASM/Rust:** Numba es un decorador Python (`@numba.jit`) que compila
a instrucciones nativas SIMD en x86 (SSE4/AVX2) y ARM (NEON) automaticamente. No requiere
saber C ni Rust. Dependencia: `numba>=0.59` (~50MB).

**Archivo:** `node/qwen2_ops.py` — `INT4Weights.linear()`

```python
import numba as nb

@nb.njit(parallel=True, fastmath=True, cache=True)
def _int4_linear_jit(packed, scale, orig_cols, x):
    n_rows = packed.shape[0]
    result = np.zeros((x.shape[0], n_rows), dtype=np.float32)
    for r in nb.prange(n_rows):
        high = ((packed[r] >> 4) & 0x0F).astype(np.int8) - 8
        low  = (packed[r] & 0x0F).astype(np.int8) - 8
        w = np.empty(orig_cols, dtype=np.float32)
        w[0::2] = high[:orig_cols//2 + orig_cols%2]
        w[1::2] = low[:orig_cols//2]
        w *= scale[r, 0]
        result[:, r] = x @ w
    return result
```

**Fallback:** Si numba no esta disponible, usar chunked numpy actual.

**Archivos a modificar:**
- `node/qwen2_ops.py` — `INT4Weights.linear()`
- `requirements.txt` — anadir `numba>=0.59`

### B2: Numba en RMSNorm y SwiGLU
**Archivos:** `node/qwen2_ops.py` — `_rms_norm`, `_silu`

```python
@nb.njit(fastmath=True, cache=True)
def _rms_norm_jit(x, weight, eps=1e-6): ...

@nb.njit(fastmath=True, cache=True)
def _silu_jit(x): ...
```

**Speedup esperado Fase B:** 10-20x en matmul, 3-5x en norm/activaciones.
Combinado con Fase A: respuesta de 20 tokens en ~15-40 segundos.

**Verificacion:**
```bash
python -c "
import numpy as np, time
from node.qwen2_ops import INT4Weights
from shattering.quantization import quantize_int4
W = np.random.randn(151936, 2048).astype(np.float32) * 0.01
p, s = quantize_int4(W)
lm = INT4Weights(packed=p, scale=s, orig_cols=2048)
x = np.random.randn(1, 2048).astype(np.float32)
t0 = time.perf_counter()
for _ in range(10): lm.linear(x)
print(f'{(time.perf_counter()-t0)/10*1000:.1f} ms/call')
"
```

---

## Fase C — Speculative Decoding con Nano-Draft [PENDIENTE]

### C1: Nano-Draft Model
Modelo de 2 capas transformer, mismo vocab (151936), hidden=256.
Tamano en disco: ~40MB. Se destila desde shard_0.

**Archivo nuevo:** `node/nano_draft.py`

```python
class NanoDraft:
    """2-layer transformer, hidden=256, vocab=151936. Pure numpy."""
    def __init__(self, weights_path: str): ...
    def draft(self, context_ids: np.ndarray, n: int = 6) -> list[int]:
        """Genera n tokens candidatos en ~2ms."""
        ...
```

**Archivo nuevo:** `scripts/build_draft_model.py`
Destila los primeros 2 bloques de shard_0 reducidos a hidden=256 con PCA.

### C2: Verificacion Batch en Shard Chain
Un solo forward pass con seq_len=6 verifica todos los tokens draft.

**Archivo:** `shattering/orchestrator.py` — nuevo metodo `_generate_local_speculative`

```python
while len(generated) < self._max_tokens:
    candidates = draft.draft(np.array(context + generated), n=6)
    verify_input = np.array(context + generated + candidates)
    output_batch, ok = pipeline._forward_through_swarm(verify_input, ...)
    for i, cand_id in enumerate(candidates):
        verified_id = pipeline._sample(output_batch[len(context)+len(generated)+i])
        if verified_id == cand_id:
            generated.append(cand_id); yield cand_id
        else:
            generated.append(verified_id); yield verified_id; break
```

**Speedup esperado Fase C:** 3-4x adicional sobre Fases A+B.
Combinado: respuesta de 20 tokens en **3-10 segundos**.

**Verificacion:**
```bash
# Log debe mostrar "accepted K/6 draft tokens" con K>=3 en texto coherente
python -m cognia
```

---

## Fase D — Android y ONNX Runtime [PENDIENTE]

### D1: ONNX Export de Shards
Exportar cada shard como `shard_N.onnx`. ONNX Runtime tiene backend Android ARM64 nativo.

**Condicion:** Solo si hay demanda real de uso en Android (Redmi test confirmado).

**Archivos nuevos:**
- `scripts/export_shards_onnx.py`
- `node/onnx_engine.py` — drop-in replacement de `ShardEngine`

### D2: Pipeline Parallelism Distribuido
Con 4 nodos reales: shard 0 procesa token N+1 mientras shard 1 procesa token N.
Throughput 4x en modo distribuido.

**Archivo:** `coordinator/relay.py` — buffer de pipeline entre sesiones

---

## Orden de Ejecucion y Estimados

| Fase | Duracion | Tokens/s tras completar | Respuesta 20 tokens |
|------|----------|------------------------|---------------------|
| Antes (bugs) | — | ~0.02 tok/s | >10 min sin feedback |
| A: Streaming + KV-cache | DONE | ~0.05-0.1 tok/s | 3-6 min con feedback en vivo |
| B: Numba JIT | 4 dias | ~0.5-1.5 tok/s | 15-40 seg |
| C: Speculative | 5 dias | ~2-6 tok/s | 3-10 seg |
| D: Android/Pipeline | 5 dias | ~4-12 tok/s | 2-5 seg |

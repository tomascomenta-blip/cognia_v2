# Cognia — RESEARCH.md
# Propuestas de investigacion e innovacion

> Este archivo documenta propuestas tecnicas no implementadas.
> Cada propuesta tiene estado: PROPUESTA | EN PROGRESO | DONE
> Al implementar: mover estado a DONE y anotar en CLAUDE.md.

---

## Phase 21 — Universal Fast Inference Stack [PROPUESTA - 2026-05-21]

**Objetivo:** Reducir latencia de inferencia de ~3-5s/token (numpy puro) a 0.01-0.05s/token
manteniendo universalidad total (PC x86, ARM, Android, sin GPU requerida).

**Speedup total estimado: 100-500x sobre numpy actual.**

Respuesta de 20 tokens: de ~60-100 segundos a 1-2 segundos.

---

### 21.1 — WASM SIMD INT4 Micro-Kernels

**Estado:** PROPUESTA

**El problema raiz:**
numpy hace matmul generico en float32. Cada forward pass dequantiza
matrices INT4 completas antes de multiplicar. El hardware tiene instrucciones
SIMD (SSE4/AVX2 en x86, NEON en ARM) que operan sobre INT4 directamente
pero numpy no las expone.

**La propuesta:**
Cada shard descarga junto a sus pesos un binario `.wasm` (~200KB) que contiene
kernels de matmul INT4 compilados desde Rust/C a WebAssembly SIMD.
Python los carga via `wasmtime-py` (pip, ~5MB).

```
model_shards/qwen-coder-3b-q4/
  shard_0.npz           <- pesos actuales (sin cambios)
  shard_0_kernel.wasm   <- nuevo: kernel SIMD para este shard
  shard_1.npz
  shard_1_kernel.wasm
  ...
```

**Por que es universal:**
- WASM corre en Windows, Linux, macOS, Android (Termux/embedded)
- El mismo .wasm compila a SSE/AVX en x86 y a NEON en ARM automaticamente
- `wasmtime-py` es una sola dependencia pip, Python 3.9+
- Sin compilador en el dispositivo del usuario

**Lo genuinamente nuevo:**
Ningun sistema existente distribuye kernels WASM junto a shards de modelo.
ONNX Runtime tiene kernels pero son monoliticos (~200MB). llama.cpp requiere
compilacion por arquitectura. Este approach es: un kernel minimo, por shard,
que viaja con los pesos y se ejecuta en cualquier maquina.

**Speedup estimado:** 10-20x sobre numpy para matmuls INT4.

**Archivos nuevos a crear:**
- `node/wasm_kernel.py` — loader y wrapper Python para kernels .wasm
- `kernels/int4_matmul.rs` (o `.c`) — fuente del kernel SIMD
- `kernels/build.sh` — compila a .wasm con wasm-pack o emcc
- `scripts/attach_kernels.py` — adjunta .wasm a shards existentes

**Archivos a modificar:**
- `node/qwen2_ops.py` — `INT4Weights.linear()` delega a kernel WASM si disponible
- `requirements.txt` — anadir `wasmtime>=20.0`
- `scripts/cognia_setup.py` — descarga .wasm junto a .npz

**Dependencias nuevas:**
- `wasmtime>=20.0` (Python binding oficial de Bytecode Alliance)
- `wasm-pack` o `emcc` solo en tiempo de build, no en runtime del usuario

---

### 21.2 — KV-Cache Activo en Loop Local

**Estado:** DONE (2026-05-29 — intra-turn session_id en _generate_local + _shard_infer_stream; evict_one_mla_session tras inferencia)

**El problema:**
El MLA KV-cache existe en `shattering/mla.py` pero no esta conectado al loop
de generacion local (`_token_loop` en `shattering/orchestrator.py`).
Cada token re-procesa toda la secuencia desde cero. Para una respuesta de
64 tokens, el token 64 atiende sobre 64 posiciones cuando podria atender solo 1.

El costo crece cuadraticamente: token N cuesta O(N) en atencion.

**La propuesta:**
Activar el flujo session_id → MLA cache en el loop local:

1. `_token_loop` genera un `session_id` unico por inferencia
2. Lo pasa a `_forward_through_swarm` → `engine.process_bytes`
3. `ShardEngine` enruta la sesion al `MLAModule.forward(session_id=...)`
4. MLA acumula KV latents en `CompressedKVCache`
5. Cada token nuevo solo computa Q para la nueva posicion; K/V vienen del cache

**Speedup estimado:** 2-3x para respuestas >10 tokens, acumulativo con 21.1.

**Archivos a modificar:**
- `shattering/orchestrator.py` — `_token_loop`: pasar session_id real a swarm
- `node/shard_engine.py` — `process_bytes`: aceptar session_id opcional
- `shattering/mla.py` — `forward()`: usar cache acumulado si session_id presente
- `node/inference_pipeline.py` — `_single_forward_pass`: propagar session_id

---

### 21.3 — Speculative Decoding con Nano-Draft Local

**Estado:** DONE (2026-05-29 — _shard_infer() ahora llama _try_load_draft(); NanoDraft activo si nano_draft.npz existe en SHARD_WEIGHTS_DIR)

**El problema:**
La generacion es estrictamente secuencial: 1 token → esperar chain completa → 1 token.
No importa cuan rapido sea el kernel, el numero de round-trips es el cuello de botella
en modo distribuido.

**La propuesta:**
Cada nodo lleva un modelo "borrador" de ~50MB (2 capas transformer, mismo vocab que Qwen).
Este draft model vive solo en la maquina del usuario — nunca va por red.

Flujo por iteracion:
```
1. Draft local genera 4-8 tokens en ~5-10ms
2. Una sola pasada por el shard chain verifica todos en paralelo
3. Si token K es correcto: se acepta + los siguientes que tambien lo sean
4. Primer token incorrecto: se descarta desde ahi, se retoma generacion normal
5. En texto coherente: 3-5 tokens aceptados por round-trip
```

**Por que funciona en Cognia:**
El draft es local (no depende de red, siempre disponible).
La verificacion es distribuida (un solo forward pass verifica N tokens).
Esto es novel para inferencia distribuida: ningun sistema existente separa
draft-local de verify-distribuido de esta forma.

**Speedup estimado:** 3-4x en texto coherente, acumulativo con 21.1 y 21.2.

**Archivos nuevos:**
- `node/draft_model.py` — nano-transformer 2 capas, carga desde `draft_model.npz`
- `scripts/build_draft_model.py` — destila el draft desde shard_0+shard_1

**Archivos a modificar:**
- `shattering/orchestrator.py` — `_generate_local`: modo especulativo opcional
- `node/inference_pipeline.py` — `_single_forward_pass`: modo batch para verificacion
- `scripts/cognia_setup.py` — descarga `draft_model.npz` junto a shards

---

### 21.4 — Layer Fusion en Kernel WASM

**Estado:** PROPUESTA (depende de 21.1)

**El problema:**
Actualmente cada operacion dentro de una capa transformer escribe a RAM y vuelve:
```
RMSNorm → RAM → Attention QKV → RAM → Softmax → RAM → Output → RAM → FFN gate → RAM
```
Cada write/read a RAM cuesta ~100ns. Una capa tiene ~8 operaciones = ~800ns solo en
movimiento de datos, independiente del computo.

**La propuesta:**
El kernel WASM de cada shard implementa una capa transformer completa como una
sola funcion fused. Los tensores intermedios (Q, K, V, scores, attn) viven en
registros SIMD o cache L1 sin tocar RAM principal.

```
// En el kernel .wasm
fn transformer_layer_fused(hidden: &[f32], weights: &ShardWeights) -> Vec<f32> {
    // RMSNorm + RoPE + GQA + MLP todo en un solo kernel
    // tensores intermedios en stack, no en heap
}
```

**Speedup estimado:** 1.5-2x adicional sobre 21.1 solo.
Mayor impacto en secuencias largas donde la presion de cache L2/L3 es alta.

**Archivos a modificar:**
- `kernels/int4_matmul.rs` — expandir a `transformer_layer.rs` con fusion completa
- `node/wasm_kernel.py` — exponer API de capa completa, no solo matmul

---

## Resumen del Plan de Implementacion

### Orden de ejecucion recomendado

| Fase | Componente | Tiempo est. | Speedup | Bloquea |
|------|-----------|-------------|---------|---------|
| 21.2 | KV-Cache activo | 1-2 dias | 2-3x | No |
| 21.1a | wasmtime loader + INT4 matmul basico | 3-5 dias | 5-10x | 21.4 |
| 21.3 | Draft model + speculative decoding | 3-4 dias | 3-4x | No |
| 21.1b | Kernels SIMD completos (AVX2 + NEON) | 3-5 dias | 2x adicional | 21.4 |
| 21.4 | Layer fusion en WASM | 2-3 dias | 1.5-2x | 21.1 |

**Empezar por 21.2:** no requiere dependencias nuevas, el codigo ya existe,
es solo conectar el flujo session_id. Ganancia inmediata con riesgo minimo.

**21.1a antes de 21.1b:** primero validar que wasmtime funciona en todos los
targets (Windows/Android) con un kernel simple, luego optimizar con SIMD.

### Speedup compuesto

| Despues de | Tokens/segundo (estimado) | Respuesta 20 tokens |
|-----------|--------------------------|---------------------|
| Hoy (numpy) | ~0.02-0.1 | 3-15 minutos |
| + 21.2 KV-Cache | ~0.05-0.2 | 1-5 minutos |
| + 21.1 WASM SIMD | ~0.5-2.0 | 10-40 segundos |
| + 21.3 Speculative | ~1.5-8.0 | 3-15 segundos |
| + 21.4 Layer Fusion | ~2-16.0 | 1-10 segundos |

### Restricciones de diseno a mantener

- Sin PyTorch en ningun nodo contribuidor
- Sin compilacion en el dispositivo del usuario (los .wasm llegan pre-compilados)
- Draft model maximo 100MB en disco
- wasmtime-py es la unica dependencia nueva permitida para 21.1
- KV-cache debe respetar el TTL de sesion ya definido en `coordinator/relay.py`
- Speculative decoding debe ser opt-in (flag en .env) hasta validacion

---

## Otras propuestas de investigacion (Phase 22+)

### LPC — Local Predictive Compression
Comprimir hidden states entre shards usando prediccion diferencial.
En vez de transferir 2048 floats por token, transferir solo el delta respecto
al token anterior. Para texto coherente el delta es pequeno (~10-30% del
tamano original). Reduce ancho de banda del relay coordinator.
Requiere: 21.2 (KV-cache) como prerequisito.

### PSW — Private Speculative Watermarking
Tecnica para detectar si output generado por Cognia fue modificado
sin violar privacidad del usuario. Embebe una firma estadistica
en la distribucion de tokens durante el sampling.
Requiere: 21.3 (speculative decoding) como base.

### CGEE — Confidence-Gated Early Exit
Salir del shard chain anticipadamente si la entropia de los logits
del shard actual es suficientemente baja (alta confianza).
Requiere proyeccion lm_head por shard intermedio — costoso en memoria.
Candidato para modelos >7B cuando haya mas RAM disponible por nodo.

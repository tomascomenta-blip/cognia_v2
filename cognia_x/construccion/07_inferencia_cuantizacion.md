# 07 — Stack de inferencia y cuantización (llama.cpp + Q4 + KV-cache + telemetría)

> **Propósito.** Especificar a nivel de implementación **cómo corre la inferencia de Cognia-X en el
> i3-10110U**: el binario `llama-server` PINEADO (b9391), la cuantización base (Q4_K_M), el
> threading (`threads=3`, `n_gpu_layers=0`), el manejo de **KV-cache** (full `O(L)` vs
> sliding-window `O(W)`), el único speculative-decode viable en CPU (`ngram-mod`), y la **telemetría
> de bytes/token y tok/s reales** que juzga toda la pila. Cierra con el ternario b1.58 como I+D
> FUTURO (NO decidido) y la integración por env vars sin constantes hardcodeadas.

Confianza: **alta en la DIRECCIÓN y en las constantes de inferencia** (a diferencia de los planos de
backbone/entrenamiento, **estas SÍ están medidas end-to-end en el i3 objetivo** — `node/llama_backend.py`
documenta cada número con su A/B). **Media** en las proyecciones de KV-cache a `L` largo (analíticas,
no barridas todavía) y en el ahorro real de SWA/4-bit-KV (gate **G1/A-018**, sin verificar en CPU).
Marco cada afirmación como **PROBADO** (cita exp/medición) / **ASUMIDO** (literatura/conjetura) /
**PENDIENTE** (a medir). Documento alineado con `00_READINESS.md` (G1), `02_backbone_modelo.md`
(RAMA A/B), `node/llama_backend.py` y `shattering/model_constants.py`.

---

## 1. Propósito y alcance

**Alcance:** la **capa de ejecución** de Cognia-X — el runtime que toma un GGUF y produce tokens en
el i3. Cubre: selección de binario/backend, cuantización de pesos (Q4_K_M base), threading, gestión
del KV-cache (precisión y política full/SWA), speculative decode, generación larga
(auto-continuación / jerárquica) y la **telemetría** (bytes/token, tok/s, RAM). **Fuera de alcance**
(otros planos): la arquitectura del backbone y la decisión RAMA A/B (`02`), el tokenizer/vocab,
el verificador y el lazo de auto-mejora, RAG/LoRA/federado.

**Qué decide este plano (load-bearing):**
1. El **runtime de producción HOY**: `llama-server` b9391 + Q4_K_M + `threads=3` + `n_gpu_layers=0`.
2. La **política de KV-cache**: full `O(L)` (Qwen actual) vs SWA `O(W)` (RAMA A, gate G1) +
   cuantización de KV (fp16 hoy → 4-bit en la RAMA B de fallback).
3. El **único speculative-decode permitido en CPU** (`ngram-mod`) y por qué el draft separado está
   PROHIBIDO en el código.
4. La **telemetría obligatoria** (bytes/token analítico + `timings.predicted_per_second` real) que
   cierra cada medición y alimenta los gates.
5. El **status del ternario b1.58**: I+D futuro, NO en la ruta crítica (H-BIT-1 refutada).

---

## 2. Estado de partida (qué existe y corre hoy)

**PROBADO — el runtime corre y está medido en el i3.** `node/llama_backend.py` es la fachada real
de inferencia. No es papel: arranca `llama-server`, lo adopta si ya está vivo, y expone
`generate`/`stream_generate`/`stream_chat`/`generate_long`/`generate_hierarchical`. Tooling presente
(00_READINESS): `node/llama-server.exe` (b9391) + DLLs CPU, 6 GGUF reales en `model_shards/`
(Qwen2.5-Coder 3B Q4_K_M canónico 1.93 GB, 3B Q4_0/Q3_K_S, 0.5B instruct+coder, 7B Q4_K_M),
`venv312/Scripts/python.exe`.

**Las constantes REALES de inferencia (verbatim de `node/llama_backend.py`):**

| constante | valor | justificación medida (del código) |
|---|---|---|
| binario | `node/llama-server.exe` **b9391** (7fb1e70b5) | **b9414 = −37% decode** medido en el i3 (5.2 vs 8.2 tok/s). No actualizar sin re-correr el A/B. **PROBADO**. |
| `_CTX_SIZE` | `16384` | `n_ctx_train=32768`; GQA 2 KV heads ⇒ ~36 KB/token ⇒ ~590 MB de KV a 16k en máquina de 12 GB. |
| `_N_GPU_LAYERS` | `0` | UHD integrada (Vulkan) **3.8 vs 8.8 tok/s** más lenta que CPU. **PROBADO**. |
| `n_threads` (decode y batch) | `cpu_count-1` = **3** | decode 8.09 @3t / prefill 29.3 @3t vs 22.7 @4t — el 4º hilo lógico compite con el SO y daña AMBAS fases. **PROBADO**. |
| `_DEFAULT_PORT` | `8088` | evita choque con la app (:8000). |
| `_SERVER_TIMEOUT` | `90 s` | carga fría del GGUF de 1.9 GB excede 30 s (falló el E2E del 2026-06-11). |
| flags del cmd | `--cache-reuse 256 --prio 2 --flash-attn on --log-disable` | flash-attn ON (habilita además KV cuantizado en la RAMA B); cache-reuse acelera prefills con prefijo común. |

**PROBADO — el A/B de cuantización está hecho.** Q4_K_M figura PRIMERO en `_GGUF_CANDIDATES` porque
en el i3 con b9391 es **más rápido Y de mayor calidad** que Q4_0: decode **8.09** / prefill **29.3**
tok/s (Q4_K_M) vs **7.58** / **20.3** (Q4_0). Q3_K_S queda como fallback más chico. Registry
conmutable en `model_constants.py::MODEL_GGUF_REGISTRY` (`3b`→1.93 GB, `7b`→Q4_K_M) con
`resolve_gguf_path(key)`; medición 2026-06-12: 3b 40% pass@1 ~8 tok/s, 7b 50% pass@1 ~2.2 tok/s,
cascada 3b→7b 60%.

**PROBADO — el speculative-decode ya está acotado en el código.** `_spec_args()` permite SOLO
variantes n-gram (`_SPEC_NGRAM_ALLOWED = {ngram-mod, ngram-simple, ngram-map-k, ngram-map-k4v,
ngram-cache}`), default `ngram-mod`, conmutable por `COGNIA_SPEC_TYPE`. `draft-*` está **PROHIBIDO
explícitamente** (comentario verbatim): en CPU bandwidth-bound un draft separado **mide 0.367×** en
habla (Qwen2.5-Coder-0.5B como draft, `bench_draft.py` warm; exp021/CYCLE34, verificado en
`results/results.md`). `ngram-mod` es **bit-idéntico a temp=0** (verificación exacta, SHA igual en los
3 prompts). Su ganancia lossless MEDIDA es **modesta en prosa** (speech **1.056×**, echo **1.133×**,
warm) y **nunca más lenta** en lo medido; sube a multiplicadores mayores solo en texto repetitivo/RAG.
El **1.45× lossless en eco** que se cita (1.333× warm) es de la variante **`ngram-simple`** (más
agresiva: NO bit-idéntica y **daña** habla natural a 0.81×), NO de `ngram-mod`; el ~5.5× sobre `code`
del primer pase fue **artefacto cold-mmap** (baseline 1.43 frío), descartado por el warm.

**PROBADO — la telemetría base ya existe.** Tras cada generación el backend expone
`last_tokens_predicted` (de `tokens_predicted` en `/completion`, o `timings.predicted_n` en
`/v1/chat/completions`) y `last_stop_reason` (`eos`|`limit`|`word`, mapeado por `_stop_reason`). El
endpoint `/props` se parsea con `_server_props_summary` (n_ctx, model_path, build_info). **Lo que
FALTA** (gap de este plano): capturar `timings.predicted_per_second` y derivar **bytes/token**.

**PROBADO — la integración por env vars está completa.** `LLAMA_GGUF_PATH` (`_find_gguf`),
`LLAMA_SERVER_PATH`/`LLAMA_SERVER_PORT`, `LLAMA_LORA_PATH` (`_lora_args` → `--lora`),
`COGNIA_SPEC_TYPE`, `SHARD_WEIGHTS_DIR`. Ningún path ni constante de modelo está hardcodeado fuera de
`model_constants.py` / `llama_backend.py`.

**Roofline del i3 (PROBADO, exp004):** memoria efectiva ~**16.5 GB/s** (float32, scipy-openblas,
n=4096); el f32 va ~2.2× el f64 (bandwidth-bound). Este número **explica y predice** el decode
medido (ver §5).

---

## 3. Diseño detallado

### 3.1 Métrica maestra: BYTES MOVIDOS POR TOKEN

El decode batch=1 en CPU es **memory-bandwidth-bound** (~1-2 FLOP/byte): cada token nuevo **vuelve a
leer todos los pesos del modelo** (no hay reuso entre pasos a batch=1) **más** la lectura del
KV-cache para la atención. Por tanto el techo de velocidad es puramente físico:

```
tok/s  ≈  BW_efectiva (bytes/s)  /  bytes_por_token
bytes_por_token  ≈  bytes_pesos  +  bytes_KV_leídos(L)
```

- `bytes_pesos` = tamaño del GGUF en RAM (Q4_K_M 3B ≈ **1.93 GB**; constante por token).
- `bytes_KV_leídos(L)` = lo que la atención recorre por token, que **depende de la política**:
  - **full `O(L)`** (Qwen2.5 actual): crece linealmente con la longitud → `kv_bytes_token × L`.
  - **sliding-window `O(W)`** (RAMA A): **acotado en `W`** → `kv_bytes_token × min(L, W)` (platea).

Esto es lo que convierte SWA + KV-4bit en el lever de banda; y es lo que la telemetría debe medir
para cerrar G1.

### 3.2 KV-cache: aritmética concreta (Qwen2.5-Coder-3B, de `model_constants.py`)

GQA con `n_kv_heads=2`, `head_dim=128`, `total_layers=36` (verificados, `QWEN25_CODER_3B`). Por token
el cache guarda K **y** V para cada KV-head de cada capa:

```
elems/token = 2 (K+V) × n_kv_heads(2) × head_dim(128) × n_layers(36) = 18 432 elems
```

| precisión KV | bytes/elem | **bytes/token** | KV total @ L=16384 | requiere |
|---|---|---|---|---|
| **fp16** (default llama.cpp HOY) | 2 | **36 864 B = 36.0 KiB** | **576 MiB** | — |
| **q8_0** | ~1 | ~18 KiB | ~288 MiB | `--cache-type-k/v q8_0` |
| **q4_0** (RAMA B) | ~0.56 | **~10.1 KiB** | ~162 MiB | `--cache-type-k/v q4_0` + `--flash-attn on` (ya activo) |

> **Nota de honestidad:** los 36 KB/token y 576 MiB son **PROBADOS** (aritmética exacta + coinciden
> con el comentario `~36KB/token => ~590MB` de `llama_backend.py`). El ahorro de q4_0-KV es
> **ASUMIDO** (números de llama.cpp, no barridos en el i3) y su impacto en **calidad** está sin
> medir → A/B en M0 (RAMA B).

**Política full vs SWA.** Qwen2.5 es atención **full** (todos los 6 GGUF locales lo son — bloqueo de
G1, ver §6). La RAMA A del backbone (`02`) usaría SWA con `W~1024` (target; `SWA_WINDOW=512` es el
valor early-impl en `model_constants.py`, **a re-fijar en M0**). El ahorro es DOBLE: (a) el KV total
en RAM deja de crecer con `L` (se queda en `kv_bytes_token × W`), y (b) los `bytes_KV_leídos` por
token se aplanan en `W` → tok/s deja de degradarse a contexto largo. **PENDIENTE**: ningún GGUF
SWA-nativo local (Gemma-2/3, Mistral-SWA, Phi-3) → M0 baja uno y corre el A/B.

### 3.3 Threading y placement (PROBADO)

```python
n_threads_decode = max(1, (os.cpu_count() or 4) - 1)   # = 3 en el i3 (2c/4t)
n_threads_batch  = max(1, (os.cpu_count() or 4) - 1)    # = 3 (el 4º hilo daña AMBAS fases)
# n_gpu_layers = 0  (UHD Vulkan más lenta que CPU)
# --prio 2  (sube prioridad del proceso; --flash-attn on)
```

No tocar sin re-medir: el `cpu_count-1` no es heurística, es el óptimo medido (decode 8.09@3 vs el 4º
hilo compitiendo con el SO). En máquinas con más núcleos físicos el `cpu_count-1` escala solo, pero
el target es el i3.

### 3.4 Speculative decode (PROBADO + barrera dura en código)

```python
_SPEC_NGRAM_ALLOWED = {"ngram-mod", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-cache"}
# default COGNIA_SPEC_TYPE="ngram-mod"; "none" lo desactiva; "draft-*" se ignora con warning.
```

- **Permitido:** variantes n-gram (drafter de coste de banda ~0: escanea el contexto, sin modelo
  extra ni entrenamiento). `ngram-mod` por default.
- **PROHIBIDO:** `draft-*` (draft model separado). Razón medida (exp021/CYCLE34): en CPU 2-core
  bandwidth-bound el draft compite por banda + núcleos y mide **0.37×** en habla. El `_spec_args()`
  lo rechaza con warning, no lo pasa al binario.
- **Frontera abierta (ASUMIDO, no en esta pila):** cabezas MTP/EAGLE (speculative que respeta la
  banda, 2-3× proyectado) exigirían un modelo con esas cabezas — fuera de Qwen2.5 GGUF.

### 3.5 Generación larga (PROBADO, ya implementado)

Tres caminos, todos respetando el ctx de 16k:
- `generate(prompt, max_tokens)` — una pasada; `cache_prompt=True` reusa el prefijo en KV.
- `generate_long(...)` — auto-continuación por chunks (`GEN_CONTINUATION_CHUNK=2048`) hasta
  `GEN_LONG_MAX_TOKENS=5000`, re-lanzando mientras `last_stop_reason=='limit'`. **Guarda de ctx**
  (`GEN_CTX_GUARD_RATIO=0.75`, `GEN_CTX_MARGIN_TOKENS=64`): cuando prompt+acumulado se acerca al ctx,
  manda prompt + la cola reciente (el output sigue completo). Cada continuación solo prefilla la cola
  nueva gracias a `cache_prompt`.
- `generate_hierarchical(...)` — outline (`GEN_HIERARCHICAL_SECTIONS=5`) → secciones con prefill
  acotado (resumen `GEN_SECTION_SUMMARY_CHARS=200`); rompe el techo de ctx, el único límite pasa a
  ser tiempo de pared (~8 tok/s). **Todas** estas constantes viven en `model_constants.py` (sin
  hardcodear).

### 3.6 Telemetría (PENDIENTE — el entregable nuevo de este plano)

Hoy el backend captura `tokens_predicted` pero **descarta** el bloque `timings` de la respuesta de
`llama-server`. Propuesta concreta (cambio chico, sin romper el contrato):

```python
# en _LlamaServerBackend.generate(), tras json.loads(resp.read()):
t = data.get("timings") or {}
self.last_timings = {
    "predicted_n":          t.get("predicted_n"),
    "predicted_per_second": t.get("predicted_per_second"),  # tok/s REAL del server
    "prompt_n":             t.get("prompt_n"),
    "prompt_per_second":    t.get("prompt_per_second"),      # tok/s de prefill
}
```

Y un helper analítico de bytes/token anclado en `model_constants.py` (cero constantes nuevas):

```python
# cognia_x/runs/telemetry.py  (nuevo, ~40 líneas, numpy-free)
from shattering.model_constants import QWEN25_CODER_3B as M
def kv_bytes_per_token(bytes_per_elem=2):  # fp16 default
    return 2 * M["n_kv_heads"] * M["head_dim"] * M["total_layers"] * bytes_per_elem
def bytes_per_token(weight_bytes_gb, L, window=None, kv_bpe=2):
    span = L if window is None else min(L, window)   # full O(L) vs SWA O(W)
    return weight_bytes_gb * 1e9 + kv_bytes_per_token(kv_bpe) * span
def tok_s_roofline(weight_bytes_gb, L, bw_gbps=16.5, **kw):  # exp004
    return bw_gbps * 1e9 / bytes_per_token(weight_bytes_gb, L, **kw)
```

Cada cierre de medición reporta: GGUF (key del registry), `predicted_per_second` real,
`bytes_per_token(L)` analítico, RAM de KV (`kv_bytes_per_token × min(L,W)`), `stop_reason`. Esto es lo
que alimenta G1 (SWA vs full) y se appendea a `MANAGER_LOG.md`.

### 3.7 Precisión: Q4_K_M base + el eje de baja-precisión (honesto)

- **PRODUCCIÓN HOY: Q4_K_M.** A/B ganado en el i3 (§2). Es el default y la ruta crítica.
- **El ahorro de baja precisión es de MEMORIA (4×), NO de cómputo (PROBADO, exp007):** int8 naïve en
  numpy es **8-10× MÁS LENTO** que float32 (BLAS no acelera enteros; `ratio_vs_float32` 0.109 @
  n=2048). Realizar la velocidad EXIGE **kernels especializados** — los Q4_K de llama.cpp son
  exactamente eso. Esta es la advertencia que gobierna G1: *un formato más chico no da velocidad
  gratis sin su kernel*.
- **KV 4-bit (q4_0):** ruta de la RAMA B (denso GQA), madura en llama.cpp HOY; baja la RAM de KV ~3.6×
  (§3.2). **PENDIENTE** A/B de calidad.

---

## 4. Decisiones y alternativas

| eje | **Conservadora (default HOY)** | Moderada | Radical (I+D, NO decidida) |
|---|---|---|---|
| **pesos** | **Q4_K_M** (PROBADO i3) | Q5_K_M (más calidad, ~−15% tok/s) | **ternario b1.58** (ver abajo) |
| **KV-cache** | fp16, full `O(L)`, ctx 16k | **q4_0 KV** + flash-attn (RAMA B) | SWA `O(W)` nativo (RAMA A, G1) |
| **spec-decode** | `ngram-mod` (bit-idéntico) | `ngram-cache` (RAG/repetitivo) | cabezas MTP/EAGLE (otro modelo) |
| **backend** | `llama-server` subproc (REST) | `llama-cpp-python` in-proc | — |

**Ternario b1.58 — status honesto (I+D FUTURO, NO en la ruta crítica):**
- **H-BIT-1 REFUTADA (holds=false):** los 2-6× de bitnet.cpp son **kernel-vs-kernel**, no una
  ventaja del formato per se; y **BitNet-2B4T pierde ~12% MMLU** vs Qwen2.5-1.5B. (literatura +
  conclusión del lab; **confianza media-alta en la refutación**).
- **H-LUT-1 holds=false:** T-MAC usa registros/L1, no L2 — no transfiere directo al patrón del i3.
- **Implicación:** el ternario NO entra en v1. Queda como experimento de I+D **si** aparece un kernel
  CPU que lo realice sin pérdida de calidad a 1-3B. La v1 se queda en Q4_K_M (producción) con KV-4bit
  como única baja-precisión adicional cuando pague (RAMA B).

**Backend in-process vs server.** `try_load()` prueba `llama-cpp-python` primero (más rápido,
in-proc) y cae a `llama-server` (subproceso REST, OpenAI-compatible). El server es el camino
**verificado** (todas las mediciones b9391 son vía `/completion`); el in-proc ignora `cache_prompt` y
`grammar` (limitaciones del binding, documentadas en código). **Default operativo: server.**

---

## 5. Plan de validación (cómo se mide que funciona)

**El roofline CORROBORA la métrica maestra (PROBADO en la FORMA, calibrado a contexto corto):**
exp004 mide BW efectiva **16.5 GB/s** (n=4096 f32, `measurement_default`); con `bytes_pesos=1.93 GB`
el techo es `16.5/1.93 ≈ 8.55 tok/s` — y el decode **medido es 8.09 tok/s** (5% por debajo, KV +
overhead a ctx corto). **Caveat de honestidad (no es derivación same-workload):** los 16.5 GB/s salen
de un **GEMM BLAS de array chico** (scipy-openblas, 64 MB), **no** de un read-streaming de 1.93 GB de
pesos Q4; en exp004 la BW además **varía con el working-set** (16.5–22.2 GB/s según `n`). La propia
calibración warm de exp021 (`cost_model`: 8.32 tok/s × 1.797 GiB) da **~15.0 GiB/s efectivos de
decode**, **por debajo** del 16.5 GEMM (overhead no-GEMV). El acuerdo 8.09≈8.55 funciona porque el
plano empareja la BW alta (16.5) con el tamaño de archivo grande (1.93 vs 1.797 activo) — dos
elecciones que se compensan. **Conclusión robusta:** el decode es **bandwidth-bound** y la fórmula de
§3.1 captura la FORMA correcta; **confianza media-alta** en usarla para proyectar SWA/4-bit-KV, con la
validación dura siendo el **barrido tok/s(L) PENDIENTE** del §5.1 (no este punto único).

**Mediciones a correr (CPU, i3):**
1. **tok/s(L) full** — `/completion` con prompts de `L ∈ {256, 2k, 4k, 8k, 16k}`, leer
   `timings.predicted_per_second`. **Predicción a validar:** a L=16384 el KV añade 576 MiB →
   bytes/token ≈ 2.53 GB → ~6.5 tok/s (caída del ~20% vs decode corto). **PENDIENTE de barrido.**
2. **RAM de KV(L)** — RSS del proceso `llama-server` a cada `L` (Process Explorer / `tasklist`),
   contrastado con `kv_bytes_per_token × L` (§3.2). DoD: el medido sigue la recta analítica ±10%.
3. **G1 — SWA vs full** (gate, RAMA A): mismo barrido tok/s(L) + RAM con un GGUF **SWA-nativo** vs el
   Qwen full. **Éxito:** SWA aplana tok/s y RAM más allá de `W`; el full degrada linealmente. **Si NO
   aplana en CPU → A-018 no se sostiene → RAMA B** (denso GQA + KV-4bit), ya prevista.
4. **q4_0-KV (RAMA B):** A/B RAM (−3.6×) **y calidad** (pass@1 del benchmark de código) fp16 vs q4_0.
5. **spec-decode:** re-confirmar `ngram-mod` ≥ baseline en código/RAG y **bit-idéntico a temp=0**
   (no regresión del exp021); confirmar `draft-*` sigue rechazado.

**Kaggle:** nada de esta pila va a GPU — es **inferencia CPU pura**. (El entrenamiento que produce los
GGUF/adapters es de otros planos.) La única dependencia externa sería bajar un GGUF SWA-nativo.

---

## 6. Lo que NO está probado / riesgos

- **R-1 (P0, G1/A-018) — el ahorro de banda de SWA/KV-4bit en CPU NO está verificado.** Precedente de
  fallo: exp007 (int8 8-10× más lento sin kernel). **Bloqueo concreto:** los 6 GGUF locales son
  Qwen2.5 = atención **full**; falta un GGUF SWA-nativo. *Mitigación:* M0 baja uno y corre el A/B;
  **RAMA B** (denso GQA + KV-4bit, madura HOY) lista si falla. **Confianza media.**
- **R-2 — tok/s(L) y RAM(L) a contexto largo son ANALÍTICOS, no barridos.** La fórmula §3.1 está
  validada a L corto (8.09 vs 8.55 predicho) pero el barrido a 16k está **PENDIENTE**. La predicción
  de ~6.5 tok/s @16k es **ASUMIDA**. *Mitigación:* es justo la medición 1-2 del §5.
- **R-3 — `SWA_WINDOW=512` es early-impl, NO el target.** El backbone apunta a `W~1024`; el valor de
  `model_constants.py` debe re-fijarse en M0 junto con G2 (recall). **PENDIENTE.**
- **R-4 — calidad de KV-4bit sin medir.** El ahorro de RAM es claro; el costo de calidad (pass@1) no.
  **PENDIENTE** A/B. Mantener fp16 si degrada.
- **R-5 — `b9391` es un pin frágil.** Cualquier `git pull` del binario puede traer la regresión −37%
  de b9414. *Mitigación:* el pin está documentado en el docstring + este plano; cualquier bump EXIGE
  re-correr el A/B (`/completion`, `timings.predicted_per_second`). **PROBADO el riesgo.**
- **R-6 — telemetría `timings.predicted_per_second` NO se captura aún.** Hoy solo `tokens_predicted`.
  *Mitigación:* el cambio de §3.6 (chico, retrocompatible). **PENDIENTE** de implementar + test.
- **R-7 — `llama-cpp-python` divergente del server.** Ignora `cache_prompt`/`grammar`; sus tok/s no
  están medidos. *Mitigación:* default = server; el in-proc es best-effort. **PROBADO** (limitación
  de binding, documentada).
- **R-8 — ternario b1.58:** la promesa de velocidad NO se sostiene sin kernel y pierde calidad
  (H-BIT-1 refutada). Riesgo = **invertir en una vía sin payoff**. *Mitigación:* fuera de v1, solo
  I+D gated. **Confianza media-alta en descartarlo de la ruta crítica.**
- **R-9 — adopción de server externo.** `_check_adopted_server` avisa si `n_ctx` difiere, pero un
  server ajeno puede correr otra cuantización/flags y sesgar un benchmark. *Mitigación:* el warning ya
  existe; los benchmarks deben arrancar server propio. **PROBADO el riesgo.**

---

## 7. Definición de Hecho (DoD) + dependencias

**DoD (verificable):**
1. **Telemetría completa:** `_LlamaServerBackend` captura `timings.predicted_per_second`/`prompt_per_second`
   y `cognia_x/runs/telemetry.py` deriva `bytes_per_token(L)`/`kv_bytes_per_token` desde
   `model_constants.py` (sin constantes nuevas). Test de regresión: el helper reproduce 36.0 KiB/token
   y 576 MiB @16k.
2. **tok/s(L) medido en el i3:** barrido `L ∈ {256,2k,4k,8k,16k}` con `predicted_per_second` real,
   **mostrado** (CLI real, no pytest), y contrastado con la predicción roofline (±15%).
3. **RAM de KV(L) medida:** RSS del `llama-server` a cada `L`, vs la recta analítica (±10%).
4. **G1 cerrado con número:** A/B SWA-vs-full (GGUF SWA-nativo bajado en M0) → SWA aplana tok/s+RAM, o
   se declara **RAMA B** explícitamente con su telemetría en `MANAGER_LOG.md`.
5. **Q4_K_M confirmado como base** y `ngram-mod` re-verificado bit-idéntico a temp=0 (no regresión
   exp021); `draft-*` sigue rechazado por `_spec_args`.
6. **Sin constantes hardcodeadas:** toda dimensión de KV/modelo viene de `model_constants.py`; toda
   ruta/flag por env var (`LLAMA_GGUF_PATH`/`LLAMA_SERVER_PATH`/`COGNIA_SPEC_TYPE`/`LLAMA_LORA_PATH`).
7. **Tests:** `pytest` dirigido del backend verde; suite completa como última compuerta (reportar
   N passed / M failed con `venv312/Scripts/python.exe`).

**Dependencias:**
- **Hardware:** i3-10110U (2c/4t, sin CUDA, 11.8 GB). Toda esta pila es CPU; **nada va a Kaggle**.
- **Tooling presente:** `node/llama-server.exe` b9391 + DLLs CPU, 6 GGUF (`model_shards/`),
  `node/llama_backend.py`, `shattering/model_constants.py`, `venv312/Scripts/python.exe`.
- **Tooling FALTANTE (bloqueo de G1):** un GGUF **SWA-nativo** (Gemma-2/3, Mistral-SWA, Phi-3) para el
  A/B SWA-vs-full. El binario y el resto NO faltan.
- **Planos hermanos:** `00_READINESS.md` (G1), `02_backbone_modelo.md` (RAMA A/B, ratio/ventana,
  GQA), `11_plan_maestro_build.md` (M0 instancia G1).
- **Mediciones ancla:** exp004 (roofline 16.5 GB/s), exp005 (frontera coste-decode), exp007 (int8 sin
  kernel 8-10× más lento), exp021/CYCLE34 (spec-decode), A/B b9391 in-code (decode 8.09@3t).

**Riesgo residual aceptado:** la pila de inferencia v1 puede quedar como **full O(L) + Q4_K_M + KV
fp16** (sin SWA) si G1 no habilita el ahorro de banda en CPU. Es un resultado **honesto y
entregable**: corre HOY a ~8 tok/s en el i3, con la RAMA B (KV-4bit) disponible para bajar RAM, y la
migración a SWA abierta cuando aparezca el GGUF/kernel adecuado.

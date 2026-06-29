# 02 — Backbone del modelo CPU-first (híbrido + rama de fallback)

> **Propósito.** Especificar el sustrato de secuencia de Cognia-X v1 a nivel de implementación:
> la config objetivo (tamaño, ratio, ventana, vocab, cuantización), las **dos ramas** que el build
> mantiene en paralelo —**RAMA A** híbrido (condicionada al gate G1/A-018) y **RAMA B** fallback
> Transformer denso GQA + KV-cache 4-bit (madura en llama.cpp HOY)—, cómo se resuelve la fragilidad
> de recall (G2), la migración byte-level→BPE y la telemetría de bytes/token. El build **no se
> bloquea por A-018**: si el híbrido no entrega banda en CPU, la RAMA B es el sustrato v1.

Confianza: **alta en la DIRECCIÓN** (anclada en exp001-007 + exp013-015 propios), **media en las
CONSTANTES exactas** (no medidas end-to-end en el i3 objetivo; M0 + telemetría las fijan). Marco
cada afirmación como **PROBADO** (con cita exp/CYCLE) / **ASUMIDO** (literatura/conjetura) /
**PENDIENTE** (a medir en M0). Documento alineado con `cognia_x/construccion/00_READINESS.md`
(gates G1/G2/G3) y `cognia_x/manager/architecture.md` (§1-3, decisiones D-007/D-008/D-013).

---

## 1. Propósito y alcance

**Alcance:** el componente 1 de `architecture.md` (mezcla de secuencia) + su representación de
entrada (componente 2) + su precisión (componente 3), aterrizados a una config concreta y a un plan
de validación CPU/Kaggle. **Fuera de alcance** (otros planos): RAG/LoRA/anti-olvido (componente 4,
gate G3), federado (componente 5), verificador/lazo de auto-mejora (subsistemas de 1ª clase),
routing de bandas HYDRA.

**Qué decide este plano (load-bearing):**
1. La **config v1** (y una `v1-α` de bring-up para los spikes de M0).
2. La **bifurcación A/B** y su criterio de decisión objetivo (G1).
3. El **ratio atención:lineal y el arreglo** de capas (G2).
4. La **migración** de vocab byte-level (256) → BPE byte-fallback moderado (32-64k).
5. El **objetivo de cuantización** (Q4_K_M) y la **telemetría de bytes/token** que juzga todo.

---

## 2. Estado de partida (qué existe y corre hoy)

**PROBADO — el v0 corre de verdad.** `cognia_x/model/hybrid.py` (PyTorch CPU) implementa el
backbone híbrido y está verificado HOY (00_READINESS C4): config `d=128/8 capas/ratio 3:1`,
1.56M params, `forward` + `forward_features` + `generate` OK, entrena (loss 5.56→2.03 en 30 pasos).
Entrenadores reales: `cognia_x/train/charlm.py` (char-LM) y `cognia_x/train/recall_task.py` (recall
asociativo, el banco de exp013-015).

**Los knobs REALES (`HybridConfig`, verbatim de `hybrid.py:26-59`):**

| knob | default v0 | significado (del docstring del código) |
|---|---|---|
| `vocab_size` | `256` | byte-level v0 (D-013); sin tokenizador que entrenar |
| `d_model` | `256` | ancho del residual |
| `n_layers` | `8` | nº de bloques |
| `n_heads` | `8` | cabezas; `d_head = d_model//n_heads` debe ser **par** (RoPE) |
| `d_ff` | `None`→`~8/3·d_model` redondeado a 16 (SwiGLU) | `__post_init__`: `max(16, round(8·d/3/16)·16)` |
| `window` | `128` | ventana de la SWA; **`window >= max_seq_len` ⇒ atención global** |
| `attn_every` | `4` | 1 de cada `attn_every` capas es atención; resto lineal. `<=0`⇒todo lineal; `==1`⇒todo atención |
| `max_seq_len` | `512` | contexto máx (RoPE cache + truncado en `generate`) |
| `tie_embeddings` | `True` | `lm_head.weight = embed.weight` (D-008, barato) |
| `abs_pos_emb` | `False` | pos. absolutos aprendidos (además de RoPE en attn) |
| `linear_feature_mult` | `1` | ancho del feature map de la atención **lineal** (Based/Arora 2024) |
| `linear_feature_map` | `"elu"` | forma del feature map lineal: `"elu"` (elu+1) o `"taylor"` (2º orden, ≈exp(q·k)) |
| `mimetic_init` | `False` | re-init de capas lineales cerca de una copia asociativa (Trockman 2024) |

**Arreglo que el código produce HOY** (`layer_types()`, `hybrid.py:69-78`): con `attn_every=4`
marca atención cuando `i % 4 == 3`. Es **"atención-al-final-de-cada-grupo"** (3 lineales → 1
atención → …). Con `n_layers=8` ⇒ capas `{3,7}` son atención. Con `n_layers=24` ⇒ `{3,7,11,15,19,23}`
(6 atención, ratio lineal:atención = 18:6 = **3:1**).

**Detalle del mixer lineal (`LinearAttention`, `hybrid.py:171-244`):** atención lineal causal
multi-cabeza, feature map `elu+1` por default; forma **paralela O(L²)** para entrenar = idéntica a
la **recurrente O(L)** de inferencia (estado `d_head×d_head` por cabeza). El ahorro de banda del
híbrido es de **inferencia** (forma recurrente), no de entrenamiento.

**Detalle del mixer de atención (`SlidingWindowAttention`, `hybrid.py:247-275`):** softmax causal
restringida a `W`; con `W >= L` es global. **CAVEAT de implementación:** usa MHA pura (`qkv` proyecta
a `3*d`, `n_kv_heads = n_heads`) — **NO** hay GQA en el v0. El KV-cache es proporcional a
`n_heads·d_head`, no a `n_kv_heads·d_head`. Para la RAMA B (y para abaratar la atención de la RAMA A)
hay que **añadir GQA** (ver §3.3 y §6, gap G-1).

**PROBADO — la frontera coste↔recall está MEDIDA (numpy, no i3 end-to-end):**
- **exp005** (`exp005_hybrid_decode_frontier`, L=8192, m=24 capas): coste de decode de `k` capas full
  como % del full puro:

  | k (capas atención de 24) | ratio lineal:attn | % del coste full @L=8192 |
  |---|---|---|
  | 3 | 7:1 | **12.43 %** (PROBADO) |
  | 6 | 3:1 | **25.96 %** (PROBADO) |
  | 12 | 1:1 | 48.33 % |
  | 24 | 0 (full) | 100 % |

  **Lectura honesta:** el titular "3/24 retiene ~12-15%" es el extremo **agresivo en coste** (ratio
  7:1, recall en riesgo). El ratio **recomendado 3:1** (k=6) retiene **~26%** del coste full a
  L=8192 — sigue siendo un 4× de ahorro, pero NO el 8×. Confianza alta en la **forma** de la curva,
  media en el % absoluto (numpy, no kernel CPU real → es justo lo que G1 debe re-medir).

- **exp004** (`exp004_roofline_cpu`): el i3 es **memory-bandwidth-bound** (~16.5 GB/s float32 @ n=4096,
  scipy-openblas; satura a 2-3 hilos). Confirma la métrica maestra: **bytes/token manda** (P5).

**PROBADO — el recall del híbrido naive es FRÁGIL a carga alta (G2, el caveat fuerte C-01):**
banco de recall asociativo `n_pairs=16, n_keys=160, batch=64`:

| exp | config | recall final |
|---|---|---|
| exp013 | lineal puro `d=24` | 0.173 (≈plateau) |
| exp013 | híbrido `attn_every=2, d=24` (h1/h4) | 0.180 / 0.180 |
| exp013 | **atención pura `d=24`** | **~0.882** (cruza) |
| exp014 | híbrido `d=24`, 10k steps | 0.186 (NO cierra; descarta under-training) |
| exp014 | atención pura `d=24` | 0.948 |
| exp015 | híbrido `d=24/48/64` | 0.189 / 0.253 / 0.190 (**NO monótono** en d) |

**Conclusión PROBADA (exp013-015):** a `d` chico / carga alta el híbrido interleaved **platea ~0.18**;
subir `d` **no** lo rescata robustamente (d=64 vuelve a 0.19); **solo la atención pura cruza**
(0.88-0.95). El techo del mezclador de estado fijo es **estructural** (pigeonhole sobre el estado,
exp002) y los 6 levers no-atención están **refutados**: ancho (`linear_feature_mult`, exp010), forma
Taylor + init mimética (`linear_feature_map="taylor"`, `mimetic_init`, exp011), profundidad/escala/
optimizador (exp012). **El remedio del recall es ARQUITECTÓNICO = atención.** → esto gobierna G2 (§3.4).

**Tooling presente (verificado, 00_READINESS):** `venv312/Scripts/python.exe` (3.12), llama.cpp
`node/llama-server.exe` b9391 + DLLs CPU, 6 GGUF Qwen2.5 (**todos atención FULL**),
`shattering/model_constants.py`, `cognia_v3/core/sandbox_tester.py`. **Falta** un GGUF SWA-nativo
(Gemma-2/3, Mistral-SWA, Phi-3) para el A/B de G1.

---

## 3. Diseño detallado

### 3.1 Config objetivo v1 (y `v1-α` de bring-up)

Dos escalas, conservador-primero. La `v1-α` es el **vehículo de los spikes de M0** (G1/G2): chica,
entrena rápido en Kaggle, corre holgada en el i3. La `v1` es el objetivo de sistema.

**`v1-α` (bring-up / M0) — PENDIENTE de entrenar:**

```python
HybridConfig(
    vocab_size=32768,      # BPE byte-fallback (§3.5); migrado desde 256
    d_model=768, n_layers=12, n_heads=12,   # d_head=64 (par, OK RoPE)
    d_ff=None,             # -> 2048 (8/3*768, redondeo a 16)
    window=1024,           # SWA local W~1024 (architecture §1)
    attn_every=4,          # ratio 3:1 -> capas {3,7,11} atención (3 de 12)
    max_seq_len=2048,
    tie_embeddings=True,   # D-008
    linear_feature_mult=1, linear_feature_map="elu", mimetic_init=False,  # exp010/011: no pagan
)
# ~110M params (embed tied 32768*768=25M + 12*~7M). Entrena en Kaggle en minutos-horas.
```

**`v1` (objetivo) — PENDIENTE:**

```python
HybridConfig(
    vocab_size=32768,
    d_model=2048, n_layers=24, n_heads=16,  # d_head=128 (par); == Qwen2.5-3B d_head
    d_ff=None,             # -> 5456 (8/3*2048)
    window=1024,
    attn_every=4,          # 3:1 -> 6 capas atención {3,7,11,15,19,23}
    max_seq_len=4096,      # objetivo de contexto util
    tie_embeddings=True,
    linear_feature_mult=1, linear_feature_map="elu", mimetic_init=False,
)
# ~1.27B params (embed tied 67M + 24*~50.3M [mixer 4*d^2=16.8M + SwiGLU 3*d*d_ff=33.5M]).
```

**Justificación por evidencia de cada elección:**
- **Escala ~1.3B:** `architecture.md §1` fija el conservador en 1-3B; el i3 corre 3B Q4 a ~8 tok/s
  (techo MEDIDO). Un híbrido ~1.3B Q4 entra holgado en RAM (11.8 GB) y debería superar 8 tok/s en
  decode corto (es más chico). **Confianza media** (no medido). Entrenar 1.3B desde cero **NO** cabe
  en el i3 → **Kaggle GPU** (00_READINESS caveat 1).
- **`d_head` par:** exigido por `apply_rope` (`hybrid.py:66`). 64 y 128 cumplen.
- **`attn_every=4` (3:1), NO 7:1:** `architecture.md §1` "ratio 3:1-4:1, NO 6:1"; el extremo alto
  degrada recall (ASUMIDO, arXiv:2507.06457). exp005 cuantifica el coste: 3:1 = 26% del full
  (PROBADO). El default 3:1 prioriza recall; G2 decide si se relaja a 4:1 (`attn_every=5`).
- **`window=1024`:** `architecture.md §1` (W~1024). PENDIENTE de A/B (G1) en GGUF SWA real.
- **`linear_feature_mult=1`, `feature_map="elu"`, `mimetic_init=False`:** exp010/exp011 **refutaron**
  que estos levers suban el plateau de recall (Δ≈0). No se paga su coste; el recall lo da la atención
  (§3.4). **PROBADO** que NO ayudan.
- **`tie_embeddings=True`:** D-008 + exp006 (a ≤64k tied, el head es 1-10% del modelo). PROBADO.

> **Gap de implementación G-2 (PENDIENTE):** la `v1` quiere **SWA local (W=1024) + 1-2 capas
> globales**, pero `HybridConfig` tiene un **único `window`** para todas las capas de atención. Hay
> que extender el config a un **schedule de ventana por capa** (ver §3.4, pseudocódigo). Cambio
> chico y localizado en `Block`/`HybridLM`.

### 3.2 RAMA A — Híbrido (condicionada a G1/A-018)

**Qué es:** el sustrato de `architecture.md §1` — mayoría capas de mezcla lineal (estado fijo, O(L)
inferencia) + minoría atención SWA + 1-2 globales. Es el `hybrid.py` escalado.

**El problema duro de la RAMA A (load-bearing, A-018):** el `LinearAttention` de `hybrid.py`
(feature map elu+1 / Taylor) **no tiene kernel en llama.cpp** (**ASUMIDO**: basado en conocimiento de
llama.cpp upstream —soporta `mamba`, `mamba2`, `rwkv6`, `rwkv7` y atención densa/GQA/SWA, **no** la
atención lineal custom de Cognia-X—, **NO verificado ejecutando en este repo / el build pineado
b9391**; G1 lo confirma compilando/cargando el GGUF recurrente). Por tanto,
para que la RAMA A corra a velocidad de producción en el i3 hay que **mapear las capas lineales a un
operador recurrente con kernel CPU real** y reentrenar. Dos sub-opciones:

- **A1 (recomendada si A pasa):** capas lineales = **Mamba-2 / SSD** (kernel `mamba2` en llama.cpp,
  GGUF nativo). El `hybrid.py` actual sigue siendo el **substrato de investigación** (recall toy,
  ablaciones en CPU numpy/torch); la versión de producción re-expresa el mezclador como SSD.
  **PENDIENTE** de portar + reentrenar.
- **A2 (más cerca del código actual):** capas lineales = **RWKV6/7** (también con kernel). Mismo
  patrón: reentrenar.

**Criterio de entrada a RAMA A (G1, objetivo y falsable):** se elige A **solo si** en el i3 real
(M0, §5) se cumplen LAS DOS:
1. **Banda:** un GGUF con el operador recurrente/SWA entrega **tok/s(L) plano o sub-lineal** y
   **RAM de KV acotada** vs la atención full a L≥4096 (replica el ahorro de exp005 con kernel real,
   no numpy). Umbral concreto: a L=8192, decode del híbrido ≤ **50%** del tok/s-coste del denso
   equivalente (mitad del margen de exp005, holgura por overhead de kernel). **Este 50% es un umbral
   PROPUESTO POR EL AUTOR, NO un valor del ledger** — M0 puede recalibrarlo con la banda real. **PENDIENTE.**
2. **Recall (G2):** existe una config (ratio+arreglo, §3.4) que cruza el umbral de recall al load
   objetivo. Si NINGUNA cruza sin volverse atención-mayoritaria → la ventaja de banda se evapora →
   **RAMA B**.

Si falla (1) o (2) → **RAMA B**, sin bloquear el build (es la decisión que 00_READINESS exige
documentar). Precedente de que (1) puede fallar: **exp007** midió que int8 naive es 8-10× MÁS LENTO
sin kernel especializado — el ahorro de bytes no se materializa solo. **PROBADO** que el patrón
"ahorro teórico ≠ ahorro real sin kernel" ocurre.

### 3.3 RAMA B — Fallback: Transformer denso pequeño GQA + KV-cache 4-bit (MADURA HOY)

**Qué es:** Transformer denso 1-1.5B con **GQA** y **KV-cache cuantizado 4-bit**, exactamente la
familia que llama.cpp corre HOY (los 6 GGUF Qwen2.5 locales son esto). **Confianza alta**: es código
maduro, no apuesta. Único costo: KV-cache O(L) (mitigado por 4-bit + contexto moderado).

**Config `v1-B` (PENDIENTE de entrenar, pero arquitectura PROBADA-en-producción):**

```python
# Misma fábrica que hybrid.py con attn_every=1 (todo atención) + GQA añadido:
#   - todas las capas SlidingWindowAttention con window grande (densa o SWA W=4096)
#   - GQA: n_kv_heads << n_heads (group=4-8) -> KV-cache /group
HybridConfig(
    vocab_size=32768,
    d_model=2048, n_layers=24, n_heads=16,  # d_head=128
    window=4096,           # = max_seq_len -> atención global densa (o SWA si se quiere O(W))
    attn_every=1,          # TODO atención (rama B = Transformer denso)
    max_seq_len=4096,
    tie_embeddings=True,
)
# + extender SlidingWindowAttention con n_kv_heads (GQA) -> ver gap G-1.
# Cuantización: Q4_K_M (pesos) + KV-cache q4_0 (cache-type-k/v en llama.cpp).
```

**Referencia de la familia (PROBADO en producción, `model_constants.py`):** Qwen2.5-Coder-3B =
`hidden=2048, layers=36, n_heads=16, n_kv_heads=2 (GQA group 8), head_dim=128, rope_theta=1e6`. La
`v1-B` copia ese patrón a 24 capas (~1.3B). El i3 lo corre HOY a ~8 tok/s a 3B → la `v1-B` (más
chica) debe ir igual o mejor. **Confianza alta.**

**Por qué B es un fallback honesto y no una derrota:** mantiene TODO el resto del sistema (verificador,
lazo, RAG, federado) idéntico; lo único que cambia es el mezclador. El build entrega valor con B y
**migra a A** cuando G1 lo habilite (los checkpoints de embed/head/MLP/tokenizer son reutilizables;
solo el mezclador se reentrena).

**Gap G-1 (PENDIENTE):** añadir GQA a `SlidingWindowAttention` (`qkv` → `q_proj`(d→d) + `kv_proj`
(d→2·n_kv_heads·d_head); repetir KV `n_heads/n_kv_heads` veces). Cambio chico, test de regresión:
medir recall de exp013 con GQA vs MHA. **CAVEAT (ASUMIDO, no medido): que "empate a igualdad de
params" es una HIPÓTESIS, no un hecho** — GQA reduce los KV heads (16→2-4) y por tanto la capacidad
asociativa de la atención, justo el recurso que exp013-015 PROBARON escaso (recall frágil). Si el test
muestra degradación, la regla es **mantener MHA (o más KV heads) en las capas GLOBALES load-bearing
de §3.4** y reservar el GQA agresivo para las SWA locales.

### 3.4 G2 — Fragilidad de recall: qué ratio/arreglo fijar y cómo decidirlo

**El hecho duro (PROBADO, exp013-015):** el híbrido naive interleaved platea ~0.18; **solo la
atención pura cruza** (0.88-0.95). Implicación directa: **las capas globales de atención no son
decoración — son load-bearing** para recall asociativo exacto de largo alcance. Subir `d` o los
levers lineales NO rescata (exp010-015).

**Decisión de diseño (la regla, no el número heredado del toy):**
1. **Ratio:** arrancar en **3:1** (`attn_every=4`). NO bajar de 4:1 sin evidencia (recall en riesgo).
2. **Arreglo:** el v0 pone atención **al final** de cada grupo (`i%4==3`). G2 compara contra
   **atención-al-inicio** y contra **inyectar 1-2 capas GLOBALES** en profundidades fijas (~25% y
   ~75%) mientras el resto de la atención queda SWA local.
3. **Regla de decisión objetivo:** elegir la **menor fracción de atención** (y la menor proporción
   de globales) que **cruza el umbral de recall al load OBJETIVO** (no al toy). Si SWA-local sola NO
   cruza (lo esperable por exp013), **añadir capas globales** hasta cruzar — el costo de banda extra
   de 1-2 globales es chico (exp005: el salto de coste está en pasar de pocas a muchas capas full),
   y es el remedio arquitectónico que exp013 PROBÓ que funciona.

**Cómo se mide (M0, en `v1-α`, CPU):** reutilizar `cognia_x/train/recall_task.py` con el load
**escalado** (n_keys ≫ ventana, secuencias > W para forzar el régimen de largo alcance que exp013
no estresó del todo) y barrer:

```
ratio        ∈ {3:1 (attn_every=4), 4:1 (attn_every=5)}
arreglo      ∈ {attn-último, attn-primero}
globales     ∈ {0, 1@~25%, 2@~25%+75%}   # window>=max_seq_len en esas capas
```

Métrica: recall final + coste-de-banda relativo (telemetría §3.7). **DoD de G2:** una config fija
(ratio+arreglo+#globales) que cruza el umbral de recall al load objetivo con el **mínimo** de
atención. Si A-018 ya tiró a RAMA B, G2 es trivial (B es atención-mayoritaria, recall garantizado) y
solo fija el SWA vs denso.

**Extensión de config necesaria (G-2, pseudocódigo):**

```python
# HybridConfig: añadir un schedule de ventana por capa (None = usa `window` global)
global_layers: tuple = ()        # índices de capa que son atención GLOBAL (window>=max_seq_len)
# layer_types() ya decide attn/linear; Block recibe el window efectivo:
def effective_window(cfg, i):
    if i in cfg.global_layers:   # global
        return cfg.max_seq_len
    return cfg.window            # SWA local
```

### 3.5 Migración byte-level (v0, vocab 256) → BPE byte-fallback moderado (32-64k)

**Estado (D-013):** v0 usa `vocab_size=256` (byte-level) como **atajo de arranque** (sin tokenizador
que entrenar). **Decisión v1 (architecture §2):** BPE **byte-fallback, vocab MODERADO 32-64k,
parity-aware**. NO 256k, NO byte-puro, NO BLT/H-Net a 1-3B.

**Evidencia (PROBADO/ASUMIDO):**
- **exp006 (PROBADO):** lm_head O(V) iguala 1 bloque transformer a V≈26k; a ≤64k **tied** el head es
  **1-10%** del modelo; el riesgo de cómputo+memoria aparece a 128-256k. → **vocab 32k es seguro**,
  64k es el techo prudente.
- byte-puro = ×4 pasos autoregresivos = ×4 lecturas de pesos (ASUMIDO, ByT5 2-10× más lento) → mata
  bytes/token (P5). BLT a 1B arranca PEOR que BPE (ASUMIDO, arXiv:2412.09871).

**Plan concreto:**
1. **Entrenar tokenizer** (CPU, una vez): BPE **byte-fallback** (cualquier byte representable → cero
   `<unk>`, robustez de byte-level sin su costo de pasos), `vocab_size=32768`, sobre corpus
   es/multilingüe. Tooling: `sentencepiece` (`model_type=bpe, byte_fallback=True`) o HF `tokenizers`.
   **Parity-aware:** garantizar cobertura de scripts no-Latín sin inflar el softmax (vocab fijo
   moderado; baja fertilidad >20% en no-Latín es aceptable a este vocab — ASUMIDO, architecture §2).
2. **Conmutar el modelo:** `vocab_size=256 → 32768`. `embed`/`lm_head` (tied) pasan de `256×d` a
   `32768×d`. A `d=2048`: 67M params de embed (contados 1 vez por tied). **Rompe** todo checkpoint
   byte-level (embed/head nuevos) → la v1 se **entrena desde cero** con el tokenizer nuevo (no hay
   warm-start de embeddings que preservar; el v0 es 1.56M de juguete).
3. **DoD:** el modelo entrena con `vocab=32768`, `num_params()` descuenta el embed tied una vez
   (`hybrid.py:373-377`), y la perplejidad por **byte** (normalizada, comparable cross-vocab) no
   empeora vs el char-LM v0 a igualdad de FLOPs de entrenamiento.

**Riesgo:** `tie_embeddings` exige `d_model` igual para entrada y salida (se cumple). El tokenizer
debe fijarse ANTES de entrenar la v1 (cambiarlo después = reentrenar). **Confianza alta** en la
dirección, media en `vocab=32k` vs `64k` (G3/telemetría afinan).

### 3.6 Objetivo de cuantización

**Decisión (architecture §3, PROBADO-en-producción): Q4_K_M como base de inferencia HOY.** Ternario
b1.58 es **solo I+D, NO decidido** (H-BIT-1 holds=false: los 2-6× de bitnet.cpp son kernel-vs-kernel;
BitNet-2B4T pierde ~12% MMLU vs Qwen2.5-1.5B).

**Pipeline:**
1. **Entrenar** en Kaggle GPU en **bf16/fp32** (la cuantización es post-entrenamiento para
   inferencia, no para entrenar — QLoRA 4-bit necesita GPU y es para fine-tune, no para esta base).
2. **Convertir a GGUF Q4_K_M** (RAMA B: directo, formato Qwen-like soportado; RAMA A: requiere que
   el operador recurrente tenga export GGUF — `mamba2`/`rwkv` lo tienen).
3. **KV-cache 4-bit** en runtime: `--cache-type-k q4_0 --cache-type-v q4_0` (RAMA B densa lo necesita
   por O(L); RAMA A híbrida lo necesita poco — el KV ya es O(W)).
4. **lm_head:** mantener en mayor precisión si la calidad lo exige (los GGUF Cognia dejan lm_head
   float32; exp006 dice que a 32k tied no domina, así que Q4 del head probablemente alcanza —
   PENDIENTE de A/B de calidad).

**El ahorro de baja precisión es de MEMORIA (4×), NO de cómputo (PROBADO, exp007):** realizar
velocidad EXIGE el kernel especializado de llama.cpp (Q4_K_M lo tiene; por eso es la base HOY). No
prometer velocidad de int8/ternario sin kernel.

### 3.7 Telemetría de bytes/token (la métrica maestra, P5)

**Por qué:** decode batch=1 en CPU es memory-bandwidth-bound (exp004: ~16.5 GB/s; P5). El número
que juzga TODA decisión de este plano es **bytes movidos por token de decode**. A batch=1 cada peso
se lee **una vez por token** → el término de pesos domina; el KV-cache solo manda a contexto largo
(por eso el híbrido gana a L grande, exp005).

**Modelo analítico (instrumentar y CONTRASTAR con medición real):**

```
bytes/token ≈  W_bytes            (pesos: leídos 1× por token a batch=1)
             + KV_bytes(L)        (atención: solo posiciones atendidas)
             + State_bytes        (capas lineales: estado recurrente, leído+escrito 1×)

W_bytes      = num_params * bits_por_peso / 8        # Q4_K_M ≈ 4.5 bits/peso (APROX; bpw efectivo varía)
KV_bytes(L)  = Σ_capas_attn  min(L, W) * n_kv_heads * d_head * 2(K,V) * bytes_kv
State_bytes  = Σ_capas_lin   n_heads * d_head^2 * bytes_state   # estado d_head×d_head/cabeza
```

> **CAVEAT del `State_bytes` (honestidad):** la geometría `d_head×d_head/cabeza` es la del
> `LinearAttention` elu+1 de `hybrid.py` (el **substrato de investigación**). La **RAMA A de
> producción** re-expresa el mezclador como Mamba-2/SSD o RWKV (R-2), cuyo estado tiene OTRA forma
> (`d_state×d_head`, etc.) → el `State_bytes` real de la v1 **cambiará** y hay que recomputarlo con el
> operador elegido. Estimación analítica **PENDIENTE** de medir.

**Estimación v1 (~1.27B, Q4_K_M, RAMA A 3:1, W=1024, GQA n_kv_heads=4) — PENDIENTE de medir:**
- `W_bytes ≈ 1.27e9 * 4.5/8 ≈ 715 MB/token` (DOMINANTE).
- `KV_bytes(8192) ≈ 6 capas * 1024 * 4 * 128 * 2 * 0.5B(q4) ≈ 3 MB` (acotado por W, no por L).
- `State_bytes ≈ 18 capas * 16 * 128^2 * 2B(fp16) ≈ 9 MB`.
- **Total ≈ 727 MB/token.** Techo teórico de decode: 727MB / 16.5GB/s ≈ **44 ms/tok ≈ 23 tok/s**
  (la eficiencia real ~50% lo bajaría a ~11 tok/s; consistente con que 3B Q4 da 8 tok/s medido).
  **Estos ~11-23 tok/s son PROYECTADOS** desde el modelo de banda + la analogía con Qwen 3B, **NO
  medidos en el i3** (M0/telemetría los confirma); úsense solo como cota de diseño, no como dato.

**Lectura honesta (load-bearing):** a 1.3B Q4 los **pesos dominan** → el híbrido **no acelera el
decode corto** (ahí dense≈híbrido en banda); su valor es **contexto largo** (KV plano vs el O(L) del
denso) y **RAM de KV acotada**. La propuesta de valor de la RAMA A es **largo alcance**, no velocidad
de prompt corto. Vender otra cosa sería overclaim.

**Implementación de la telemetría (DoD):**
- **Analítica:** función `bytes_per_token(...)` en el módulo de telemetría **compartido**
  `cognia_x/runs/telemetry.py` (el MISMO que usan los planos 07 y 11; consolidar ahí, NO duplicar en
  `model/`) que aplica la fórmula de arriba (PENDIENTE).
- **Medida real:** en el i3, correr llama.cpp con el GGUF y leer del log el tok/s + RSS de RAM por L;
  contrastar contra la analítica. El A/B de G1 (SWA vs full a L=512/2048/8192) **es** esta medición.
- **Gate:** cualquier cambio de backbone se reporta con su `bytes/token(L)` analítico + tok/s medido.

---

## 4. Decisiones y alternativas

| Eje | Conservadora | Moderada (DEFAULT v1) | Radical |
|---|---|---|---|
| **Mezclador** | RAMA B: Transformer denso GQA + KV 4-bit (maduro llama.cpp HOY) | RAMA A: híbrido 3:1 SWA W=1024 + 1-2 globales, lineales = Mamba-2/SSD (kernel real) | mayoría Gated-DeltaNet O(1) + 1 global cada ~8, sin SWA (máx. ahorro, recall en riesgo, CPU inmaduro) |
| **Ratio attn:lin** | todo atención (B) | **3:1** (`attn_every=4`); G2 puede ir a 4:1 | 7:1+ (exp005: 12% coste, pero recall en riesgo — exp013) |
| **Vocab** | BPE estándar | **BPE byte-fallback 32k** parity-aware tied | 64k / encoder byte-jerárquico (RECHAZADO <7B) |
| **Cuant.** | Q4_K_M denso | **Q4_K_M + KV q4_0** | ternario b1.58 nativo (I+D, NO decidido; H-BIT-1 false) |
| **Evidencia** | Qwen2.5 corre HOY (model_constants) | exp005/006/013-015 + architecture §1-3 | literatura, sin exp propio, soporte CPU inmaduro |

**Recomendación:** **default = moderada (RAMA A)**, **con RAMA B armada y lista** como fallback que
G1 puede activar sin rediseño. La radical queda como I+D post-v1.

---

## 5. Plan de validación (CPU vs Kaggle)

**M0 (spikes de validación, ANTES de comprometer la arquitectura — 00_READINESS §4):**

| Gate | Qué mide | Dónde | Artefacto |
|---|---|---|---|
| **G1 / A-018** | banda real SSM/SWA vs full: tok/s(L∈{512,2048,8192}) + RSS de KV en el i3 | **i3** (CPU) | bajar 1 GGUF SWA-nativo (Gemma-2/3, Mistral-SWA, Phi-3) y A/B con llama.cpp b9391; telemetría §3.7 |
| **G2** | recall del híbrido al load objetivo: barrido ratio×arreglo×#globales | **i3** (CPU, `v1-α`, numpy/torch) | `recall_task.py` con load escalado; tabla de recall vs coste |
| **G3** | (otro plano) RAG vs LoRA vs kNN-LM | i3 (CPU) | A/B de inyección de hechos |

**Entrenamiento de la v1 (tras M0):** **Kaggle GPU** (00_READINESS caveat 1; el i3 NO entrena a
escala). Pipeline `cognia_v3/training/kaggle/`. Salida: checkpoint bf16 → convertir GGUF Q4_K_M →
inferencia en i3.

**Verificación REAL end-to-end (regla del repo, no solo pytest):**
1. `pytest` dirigido del área del modelo (test de regresión por cada gap G-1/G-2: GQA empata MHA en
   recall; `effective_window` no rompe `forward`/`generate`).
2. **CLI real:** construir el `HybridLM(v1-α)`, `forward`+`generate` con output mostrado (como el
   smoke de C4). Para la v1 cuantizada: arrancar llama.cpp con el GGUF y mostrar tok/s + una
   generación real.
3. **Telemetría:** reportar `bytes/token(L)` analítico + tok/s medido en cada cierre.

**Criterio de éxito de la fase backbone:** (a) G1 resuelto (A o B elegida con número en mano);
(b) G2 con una config de recall fija; (c) `v1-α` entrena y genera; (d) GGUF corre en el i3 con
tok/s ≥ baseline 3B (8 tok/s) a decode corto y telemetría reportada.

---

## 6. Lo que NO está probado / riesgos

- **R-1 (P0, A-018) — el ahorro de banda del híbrido en CPU NO está verificado.** Todo exp005 es
  **numpy**, no kernel CPU real. Precedente de fallo: exp007 (int8 8-10× más lento sin kernel).
  *Mitigación:* G1 lo mide en M0; **RAMA B** lista si falla. **Confianza media.**
- **R-2 — el `LinearAttention` de `hybrid.py` no tiene kernel en llama.cpp.** La RAMA A de producción
  EXIGE re-expresar las capas lineales como Mamba-2/SSD o RWKV y **reentrenar** (§3.2). El `hybrid.py`
  queda como substrato de investigación. *Mitigación:* RAMA B no depende de esto. **ASUMIDO** (alta
  confianza: es conocimiento de llama.cpp upstream, pero **NO verificado ejecutando en este repo / el
  build pineado b9391** — el método del lab exige ejecutar antes de cerrar; G1 lo confirma al cargar el
  GGUF recurrente).
- **R-3 (G2) — recall del híbrido frágil a carga alta.** PROBADO en toy (exp013-015): solo la
  atención pura cruza. Si al load objetivo ninguna config híbrida cruza sin volverse
  atención-mayoritaria, la ventaja de banda se evapora → RAMA B. *Mitigación:* la regla de §3.4
  (añadir globales) + el fallback. **PROBADO el riesgo; PENDIENTE la resolución a escala.**
- **R-4 (SCALE=0%) — toda la tesis está validada en juguete** (numpy + `HybridLM` tiny ≤1.56M). La
  transferencia a 1.3B es la mayor incógnita. **Confianza media** (00_READINESS caveat 1).
- **R-5 — constantes de confianza MEDIA:** ratio 3:1, W=1024, vocab 32k, los % de exp005 (numpy). No
  medidos end-to-end en el i3. *Mitigación:* M0 + telemetría los fijan; el default es conservador.
- **R-6 — GQA ausente en el v0** (`hybrid.py` MHA pura). El KV-cache es mayor de lo necesario hasta
  cerrar G-1. *Mitigación:* gap chico y testeable. **Sub-riesgo (no asumir gratis):** AÑADIR GQA
  recorta los KV heads (16→2-4) → menos capacidad asociativa en la atención, justo el recurso que
  exp013-015 mostraron escaso; "GQA empata MHA en recall" es HIPÓTESIS a medir (G-1), no un hecho. Si
  degrada, mantener MHA/más KV heads en las capas globales (§3.4).
- **R-7 — `tie_embeddings` + cuantizar lm_head:** a 32k tied exp006 dice que no domina, pero Q4 del
  head podría costar calidad. **PENDIENTE** de A/B (mantener float32 si hace falta).
- **R-8 — corpus/tokenizer parity-aware** sin medir fertilidad real en es/multilingüe. **ASUMIDO**
  (architecture §2). El vocab se fija ANTES de entrenar → costoso de revertir.

---

## 7. Definición de Hecho (DoD) + dependencias

**DoD (verificable):**
1. **Config v1 fijada** (`v1-α` + `v1`) en código, con `num_params()` reportado y `forward`/
   `generate` corriendo (CLI real, output mostrado) — extiende el smoke de C4.
2. **Bifurcación A/B decidida con número:** G1 cerrado en el i3 (A/B SWA-vs-full, tok/s(L)+RSS) →
   RAMA A o RAMA B elegida explícitamente, con la telemetría §3.7 en el log.
3. **G2 cerrado:** una config (ratio+arreglo+#globales) que cruza el umbral de recall al load
   objetivo, documentada con su tabla recall-vs-coste.
4. **Tokenizer BPE byte-fallback 32k** entrenado y conmutado; la v1 entrena con él; PPL-por-byte ≤
   baseline char-LM v0.
5. **GGUF Q4_K_M** de la rama elegida corre en el i3 con tok/s ≥ 8 (baseline 3B) a decode corto y
   `bytes/token(L)` reportado.
6. **Gaps cerrados con test de regresión:** G-1 (recall GQA vs MHA **medido**; si GQA degrada, política
   "MHA/más KV heads en las globales" aplicada — NO asumir que empata), G-2 (`effective_window`/
   `global_layers` no rompen `forward`/`generate`).
7. **Tests:** `pytest` dirigido del área verde; suite completa como última compuerta (reportar
   N passed / M failed con `venv312`).

**Dependencias:**
- **Hardware:** i3 (inferencia/telemetría/G2-toy) + **Kaggle GPU** (entrenar la v1; el i3 NO entrena
  a escala). Cuenta Kaggle `anthuananthuan` configurada.
- **Tooling presente:** `venv312/Scripts/python.exe`, llama.cpp b9391 (`node/llama-server.exe`),
  `hybrid.py`, `recall_task.py`/`charlm.py`, `model_constants.py`, `sandbox_tester.py`.
- **Tooling FALTANTE (bloqueo de G1):** un GGUF **SWA-nativo** (Gemma-2/3, Mistral-SWA, Phi-3) para el
  A/B; para RAMA A, soporte GGUF del operador recurrente (`mamba2`/`rwkv` en llama.cpp).
- **Planos hermanos:** `00_READINESS.md` (gates G1/G2/G3), representación/tokenizer (G3 → aprendizaje
  continuo), cuantización avanzada, y `11_plan_maestro_build.md` (M0 instancia estos gates).
- **Decisiones ancla:** D-007 (ratio 3:1), D-008 (tied head), D-013 (byte-level v0); architecture
  §1-3; exp004/005/006/007/013/014/015.

**Riesgo residual aceptado:** la v1 puede salir como **RAMA B** (denso GQA) si G1/G2 no habilitan el
híbrido en CPU. Es un resultado **honesto y entregable**, no un fracaso: el resto del sistema no
cambia y la migración a RAMA A queda abierta cuando el kernel CPU madure.

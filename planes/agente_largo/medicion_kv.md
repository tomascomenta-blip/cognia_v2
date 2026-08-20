# Medición KV / reloj / prompt-cache — RTX 5060 Ti 16 GB

Fecha: 2026-08-19. Máquina del dueño. Todo lo de abajo está **medido en vivo**, no estimado,
salvo lo que aparece marcado explícitamente como CÁLCULO o EXTRAPOLADO.

Backend medido (línea de comandos real del proceso 12500):

```
llama-server.exe --model Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf
  --host 127.0.0.1 --port 8080 --ctx-size 200192 --parallel 1 --n-gpu-layers 99
  --threads 12 --threads-batch 12 --cache-reuse 256 --cache-ram 1024 --prio 2
  --flash-attn on --log-disable --spec-type ngram-mod
```

`/props` → `n_ctx: 200192`, `total_slots: 1`, build `b10434-7e4c0a968`.
GPU: 16311 MiB totales; 13155–13168 MiB ocupados en reposo con el backend cargado.
RAM del sistema: 31.888 MiB totales, 23.226 MiB libres.

---

## 0) Descubrimiento que cambia toda la aritmética: el modelo es HÍBRIDO

Los dos modelos del dueño son arquitectura `qwen35`, que **no es atención densa**. Leído de los
tensores del GGUF (`gguf-py`), contando la firma de tensores de cada bloque:

| Modelo | Bloques | Capas SSM (`ssm_conv1d`, `attn_qkv`) | Capas de ATENCIÓN (`attn_k/attn_v`) | Bloque NextN/MTP (ignorado al cargar) |
|---|---|---|---|---|
| Qwythos-9B (cargado) | 33 | **24** | **8** (bloques 3,7,11,…,31) | 1 (blk.32) |
| Qwen3.8-27B-Ridge | 65 | **48** | **16** | 1 (blk.64) |

El log del server confirma que el bloque NextN se descarta:
`model has unused tensor blk.32.attn_q.weight … -- ignoring` (144,0 MiB ignorados en el 9B).

**Consecuencia:** el KV sólo crece en 8 de 32 capas en el 9B (y 16 de 64 en el 27B). Las capas SSM
tienen estado **recurrente de tamaño constante** (`llama_memory_recurrent`), que no depende de
cuántos tokens haya. Cualquier cálculo de KV que use "n_layer = 33" se equivoca por **4×**.

---

## 1) ¿EL KV CRECE O SE RESERVA? — REFUTADO: se reserva entero al cargar

### Evidencia A — VRAM durante un prefill de 24k tokens (92 muestras cada 0,5 s)

Petición real al backend vivo, 24.016 tokens de prefill, muestreando `nvidia-smi` durante 49 s
(4 s antes, todo el prefill, 6 s después):

```
Valores DISTINTOS de VRAM en las 92 muestras: [13155]
```

Una sola cifra. Ni un MiB de variación. `timings`: `prompt_n=24016`, `prompt_ms=9029,8`.

### Evidencia B — natural, un prefill de 94k tokens de otro proceso

Mientras medía, un experimento ajeno (`exp.py`) tenía el slot ocupado con un prompt largo.
Muestreo de 25 s cubriendo de 92k a 93.963 tokens procesados y la vuelta a reposo:

```
t=1s  VRAM=13155  proc=True  n_prompt_tokens=93447
t=5s  VRAM=13155  proc=True  n_prompt_tokens=93963
t=6s  VRAM=13155  proc=False
t=25s VRAM=13155  proc=True  (prompt nuevo, 6144 tok)
```

De 0 a ~94.000 tokens de contexto: **13155 MiB constantes**.

### Evidencia C — experimento controlado: la VRAM depende de `--ctx-size`, no del uso

Arrancando un modelo de control (Qwen3-1.7B, denso) a distintos `--ctx-size`, **sin enviarle ni una
petición**, y midiendo el delta de VRAM en la carga:

| `--ctx-size` | VRAM base | VRAM cargado | Delta | KV predicho por fórmula |
|---|---|---|---|---|
| 2048 | 13153 | 14610 | **+1457 MiB** | 224 MiB |
| 8192 | 13157 | 15288 | **+2131 MiB** | 896 MiB |
| 16384 | 13153 | 15735 | +2582 MiB | 1792 MiB ← *no cupo, ver aviso* |

Delta 2048 → 8192 = **+674 MiB** medidos, contra **+672 MiB** predichos (6144 tokens × 112 KiB).
Error del 0,3 %. La VRAM sube por **declarar** más contexto, con cero peticiones enviadas.

### Evidencia D — llama.cpp lo dice él mismo

Con `-lv 10` el server imprime el tamaño del buffer KV **antes de aceptar la primera petición**:

```
llama_kv_cache:      CUDA0 KV buffer size =  1792.00 MiB     (Qwen3-1.7B, ctx 16384)
```

1792 MiB = 16384 × 112 KiB, exacto. Y aparece en el instante `0.00.793` del arranque, antes de
`llama_server: listening on`.

### VEREDICTO

> La creencia "el KV sigue creciendo y consumiendo VRAM" es **FALSA** en este llama.cpp.
> El KV se reserva **entero al cargar**, dimensionado por `--ctx-size`, y la VRAM es
> **plana bit a bit** mientras el contexto se llena.
>
> **La self-lobotomy NO recupera ni un MiB de VRAM.** Destruir el contexto libera *tiempo*
> (tokens que no se re-procesan) y *calidad de atención*, nunca memoria de la GPU.
> Los 6.256 MiB de KV del backend actual están comprometidos desde que arrancó, se usen o no.

### AVISO — degradación silenciosa en Windows (WDDM)

El punto de ctx=16384 pidió 1792 MiB de KV pero la VRAM sólo subió 2582 MiB (faltan ~445 MiB):
sólo había ~2900 MiB libres y **Windows lo dejó desbordar a memoria compartida del sistema sin
emitir ningún error**. CUDA incluso reportaba "14987 MiB free" con la GPU a 13 GB ocupados.
Es el fallo típico de este proyecto: no revienta, se pone lento. **No fiarse de que "cargó" quiere
decir "cupo": hay que comparar el delta de `nvidia-smi` contra la fórmula.**

---

## 2) COSTE DEL KV POR TOKEN

### Fórmula, validada tres veces contra el propio llama.cpp

```
bytes/token = n_capas_de_ATENCION × n_head_kv × (key_length + value_length) × bytes_por_elemento
```

`f16` = 2 B/elem. `q8_0` = 34 B por bloque de 32 = 1,0625 B/elem (ratio 0,53125 vs f16).

| Modelo | capas atn | n_head_kv | k_len+v_len | **f16 por token** | **q8_0 por token** |
|---|---|---|---|---|---|
| Qwythos-9B | 8 | 4 | 256+256 | **32 KiB** | **17 KiB** |
| Qwen3.8-27B-Ridge | 16 | 4 | 256+256 | **64 KiB** | 34 KiB (calc.) |
| Qwen3-1.7B (control, denso) | 28 | 8 | 128+128 | 112 KiB | — |

### Verificación directa (líneas `KV buffer size` del propio llama.cpp, `-ngl 0 --parallel 1`)

| Modelo | ctx | tipo KV | llama.cpp reporta | Fórmula |
|---|---|---|---|---|
| Qwythos-9B | 8192 | f16 | **256,00 MiB** | 256 MiB ✔ |
| Qwythos-9B | 32768 | f16 | **1024,00 MiB** | 1024 MiB ✔ |
| Qwythos-9B | 32768 | **q8_0** | **544,00 MiB** | 544 MiB ✔ |
| Qwen3.8-27B | 8192 | f16 | **512,00 MiB** | 512 MiB ✔ |
| Qwen3.8-27B | 32768 | f16 | **2048,00 MiB** | 2048 MiB ✔ |
| Qwen3-1.7B | 16384 | f16 | **1792,00 MiB** | 1792 MiB ✔ |

Seis de seis, exactos. La fórmula es fiable.

### Tablas de coste

**Qwythos-9B** (el modelo cargado ahora):

| Contexto | KV f16 | KV q8_0 |
|---|---|---|
| 1.024 tok | 32 MiB | 17 MiB |
| 8.192 tok | **256 MiB** (medido) | 136 MiB |
| 32.768 tok | **1.024 MiB** (medido) | **544 MiB** (medido) |
| 65.536 tok | 2.048 MiB | 1.088 MiB |
| 200.192 tok (**el de ahora**) | **6.256 MiB** | 3.324 MiB |

**Qwen3.8-27B-Ridge:**

| Contexto | KV f16 | KV q8_0 (calc.) |
|---|---|---|
| 8.192 tok | **512 MiB** (medido) | 272 MiB |
| 32.768 tok | **2.048 MiB** (medido) | 1.088 MiB |
| 65.536 tok | 4.096 MiB | 2.176 MiB |

### Estado recurrente (SSM) — constante, por SECUENCIA

`llama_memory_recurrent: CPU RS buffer size` con `--parallel 1`, idéntico a ctx 8192 y a 32768:

| Modelo | Estado SSM por secuencia |
|---|---|
| Qwythos-9B | **50,25 MiB** |
| Qwen3.8-27B | **149,62 MiB** |

No depende del contexto. Sí se multiplica por `--parallel` (con `--parallel 4` el 27B reportó
598,50 MiB = 4 × 149,62). **Cada agente concurrente cuesta un estado SSM fijo.**

### Cuadre del presupuesto real de VRAM (9B, ctx 200192)

| Partida | MiB | Origen |
|---|---|---|
| Pesos (sin blk.32) | 5.357,88 | `load_tensors: CPU_Mapped model buffer size` |
| KV @200192 f16 | 6.256,5 | fórmula validada |
| Estado SSM | 50,25 | medido |
| Buffers de cómputo + contexto CUDA + spec | ~1.490 | resto |
| **Total** | **13.155** | **nvidia-smi medido** |

### Implicación directa

Bajar `--ctx-size` de 200.192 a 32.768 libera **5.232 MiB de VRAM**, hoy inmovilizados en KV que
el agente nunca llena. Con eso caben dos instancias del 9B a 32k (≈7,2 GB cada una), o el modelo
más un crítico, dentro de los 16 GB.

**Cabe el 27B?** 11.682 MiB de pesos + 150 SSM + ~700 de cómputo/contexto ≈ 12.530 MiB, dejando
~2.450 MiB para KV con la pantalla encendida → **≈38k tokens en f16, ≈72k en q8_0**. Coincide con
el "ctx 65k" ya anotado en memoria para ese modelo. (CÁLCULO: no pude cargarlo en GPU porque el
backend del dueño ocupa 13 GB y no quise tumbarlo.)

---

## 3) EL RELOJ: prefill y decode

Prompt fresco cada vez (SALT único al principio) para forzar prefill en frío. 2 repeticiones hasta
24k, 1 por encima. `prompt_ms` es el tiempo que el server declara para procesar el prompt.

| Tokens de prompt | prompt_ms (rep 1) | prompt_ms (rep 2) | **tok/s prefill** | **segundos** |
|---|---|---|---|---|
| 1.022 | 405,7 | 389,1 | 2.519 – 2.627 | **0,40 s** |
| 4.022 | 1.424,3 | 1.428,8 | 2.815 – 2.824 | **1,43 s** |
| 8.036 | 2.839,6 | 2.847,3 | 2.822 – 2.830 | **2,84 s** |
| 16.036 | 5.825,8 | 5.819,3 | 2.753 – 2.756 | **5,82 s** |
| 24.007 | 8.979,3 | 8.985,5 | 2.672 – 2.674 | **8,98 s** |
| 32.018 | 12.271,2 | — | 2.609 | **12,27 s** |
| 47.990 | 19.404,5 | — | 2.473 | **19,40 s** |
| 63.997 | 27.299,5 | — | 2.344 | **27,30 s** |

Reproducibilidad excelente: las réplicas difieren <1,2 % (5825,8 vs 5819,3 en 16k).

El prefill es **casi lineal**, no cuadrático: de 1k a 64k el ritmo sólo cae de ~2.620 a
2.344 tok/s (−11 %). Es lo que cabe esperar con sólo 8 capas de atención + flash-attn.

**Decode:** 50–68 tok/s de base (58,7 a 32k; 54,5 a 48k; 50,5 a 64k). Con `--spec-type ngram-mod`
sobre texto repetitivo se dispararon lecturas de 219 y 252 tok/s: la especulación n-gram acierta
mucho cuando el texto se repite. El número honesto para planificar es **~55–65 tok/s**.

### EL NÚMERO CLAVE — coste en segundos de rehidratar tras un reset

| Memoria a rehidratar | Coste |
|---|---|
| 2k tokens | ~0,8 s |
| 4k tokens | **1,4 s** |
| 8k tokens | **2,8 s** |
| 16k tokens | **5,8 s** |
| 32k tokens | **12,3 s** |

Con ciclos de 3–5 minutos, rehidratar 8k cuesta **el 0,9–1,5 % del ciclo**. La self-lobotomy es
barata en tiempo. Lo que hay que vigilar no es el reset, es **no dejar que el contexto crezca**:
pasar de 8k a 64k multiplica por 9,6 el coste de cada rehidratación (2,8 s → 27,3 s).

---

## 4) PROMPT CACHE — reusa, pero con una regla muy dura

`cache_prompt` está activo por defecto. Todas estas medidas se tomaron con el slot libre
(cola medida < 0,12 s en todos los casos; descarté una tanda anterior contaminada por `exp.py`,
donde el wall-clock era 7–8 s contra 2,8 s de `prompt_ms`).

### 4a) Crecer el contexto (append puro) → SÓLO cuesta lo añadido

| Petición | Tokens procesados | prompt_ms |
|---|---|---|
| base 6k, en frío | 6.021 | 2.211,6 |
| +500 tokens | **514** | 225,4 |
| +1.500 tokens | **1.506** | 585,8 |
| +3.000 tokens | **3.018** | 1.158,1 |

Perfecto: el prefijo se reusa entero y sólo se paga la cola nueva.

### 4b) Cambiar algo por dentro → se paga TODO otra vez

Prompt de ~8.000 tokens; se comparte una fracción *f* al principio y cambia el resto:

| Fracción compartida | Prefijo común | Tokens procesados en la 2ª | ¿Reusa? |
|---|---|---|---|
| 10 % | 800 | 8.057 | **NO** |
| 25 % | 2.000 | 8.044 | **NO** |
| 50 % | 4.000 | 8.020 | **NO** |
| 75 % | 6.000 | 8.027 | **NO** |
| 90 % | 7.200 | 8.039 | **NO** |
| **95 %** | 7.600 | **516** | **SÍ** |
| **99 %** | 7.920 | **521** | **SÍ** |

El corte es abrupto y no está en un porcentaje: está en una **distancia absoluta**. Reusa sólo si
lo que cambia está dentro de los **últimos ~512 tokens**. Nótese que en f=0,95 y f=0,99 se
reprocesan 516 y 521 tokens — más que la cola que cambió: rebobina hasta un punto de control y
recalcula desde ahí. Encaja con `--cache-reuse 256` y con que el estado SSM sólo se puede rebobinar
a checkpoints, no a un token arbitrario.

Confirmado también en un test independiente: cabecera de 16k + cola distinta → 515 tokens
procesados (242 ms contra 5.830 ms, **24× más barato**); pero insertar una línea **en mitad** de esa
cabecera → 16.057 tokens, 5.826 ms, precio completo.

> **Regla dura para el diseño:** el bloque de memoria tiene que ser **inmutable y estar al
> principio**, y todo lo que cambie va **al final**. Editar una restricción o un hecho en mitad del
> bloque de memoria cuesta **una rehidratación completa**, no una parcial.
> Con este modelo híbrido no hay término medio.

### 4c) Cuántos contextos siguen calientes a la vez (`--cache-ram 1024`)

Se cargan N contextos distintos en frío y luego se revisitan en el mismo orden:

| N contextos | Tamaño c/u | Calientes en la revisita |
|---|---|---|
| 4 | 2k | **4 / 4** |
| 5 | 2k | 0 / 5 |
| 2 | 4k | **2 / 2** |
| 3 | 4k | **3 / 3** |
| 2 | 8k | **2 / 2** |
| 3 | 8k | 0 / 3 |
| 5 | 8k | 0 / 5 |

Coste de un cambio de contexto **caliente**: ~59 ms (5 tokens procesados) contra ~2.840 ms en frío.
**48× más barato.**

Los siete puntos son consistentes con `capacidad = min(4 estados guardados, ~1 GiB)`, siendo el
GiB el `--cache-ram 1024` actual. Es el clásico *thrashing* LRU: en cuanto se rota un contexto más
de los que caben, el acierto cae a **cero**, no se degrada suavemente.

Hay **23,2 GB de RAM libre**: subir `--cache-ram` a 8192 permitiría mantener calientes muchos más
contextos de agente (el límite de 4 estados habría que verificarlo por separado).

---

## 5) Lo que NO pude medir

- **No reinicié el backend del dueño** (:8080). Estaba sirviendo a un experimento ajeno (`exp.py`)
  y es el cerebro de Cognia. Toda la evidencia de reserva de KV viene de (a) muestreo de VRAM sobre
  el server vivo, (b) un modelo de control arrancado aparte a tres `--ctx-size`, y (c) las líneas
  `KV buffer size` que el propio llama.cpp imprime al cargar. Son tres vías independientes y
  coinciden.
- **El 27B no se cargó en GPU** (12,6 GB de pesos, sólo ~2,9 GB libres). Sus cifras de KV están
  medidas cargándolo en CPU (`-ngl 0`), que da los mismos bytes por token; el reparto de VRAM del
  27B en esta GPU es CÁLCULO, no medida.
- **q8_0 del 27B**: sólo medí el ratio q8_0/f16 en el 9B (544/1024 = 0,53125, exacto). Para el 27B
  lo apliqué; no lo arranqué con `--cache-type q8_0`.
- **No medí la CALIDAD** con KV cuantizado a q8_0. Ahorra la mitad de VRAM, pero si degrada el
  modelo, eso no sale en ninguna de estas tablas.
- **El límite de "4 estados"** del prompt-cache es la interpretación que encaja con los 7 puntos
  medidos; no leí el código de llama.cpp para confirmarlo, ni probé a subir `--cache-ram`.
- **`--slot-save-path` no está activo** en el server actual, así que no pude medir guardar/restaurar
  slots a disco (sería la vía para tener más de 4 contextos de agente persistidos).

---

## 6) Qué decide cada número, para la arquitectura

1. **La self-lobotomy no ahorra VRAM. Ahorra segundos.** La VRAM es plana y está comprometida desde
   el arranque. Justificarla por "no cabe en la GPU" es falso; por "rehidratar 8k cuesta 2,8 s y
   arrastrar 64k cuesta 27,3 s por ciclo", es cierto.
2. **El `--ctx-size 200192` actual regala 5,2 GB de VRAM.** A 32k el 9B ocupa ~7,2 GB, y entonces
   caben **dos procesos** (ejecutor + crítico) en los 16 GB. Es la vía más limpia para el agente
   crítico separado, y garantiza que el juez no comparta estado con el ejecutor.
3. **Mejor que dos procesos: un server con `--parallel 2`.** El log del propio dueño lo confirma:
   con `--parallel 2` y `--ctx-size 200192` reportó `n_slots = 2, n_ctx_slot = 100096`, es decir el
   contexto se reparte entre slots. Dos slots de 32k cuestan 2.048 MiB de KV + 100 MiB de SSM sobre
   **una sola copia de pesos** (5.358 MiB) ≈ 7,5 GB. Cada slot tiene su cache: los agentes no se
   desalojan entre sí. Es el camino para el multiagente con contextos independientes.
4. **El bloque de memoria va al principio y es inmutable.** Medido: cambiar algo a más de ~512
   tokens del final cuesta la rehidratación completa (5.826 ms contra 242 ms). Un canal de estado
   que se *reescribe* cada ciclo tira el cache entero; uno que sólo *crece por el final* es gratis.
5. **La compresión debe caber en ≤4k tokens si se quiere rotar entre agentes.** Con 2k por agente
   caben 4 calientes; con 8k sólo 2, y el tercero tira el acierto a cero de golpe.
6. **Vigilar el desbordamiento silencioso a RAM compartida.** Windows no da error al pasarse de
   VRAM: sólo se pone lento. Cualquier cambio de `--ctx-size` hay que validarlo comparando el delta
   de `nvidia-smi` contra la fórmula de este documento.

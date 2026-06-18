# experiments.md — fichas de experimentos de Cognia-X

> Cada experimento: objetivo, hipótesis ligada, método, cómo correr, resultado real,
> amenazas a la validez, conclusión. Reproducible (semilla + entorno declarado).

---

## exp001 — Escalado del coste de mezcla de secuencia en CPU  ✅ CORRIDO

- **Estado:** completo (2026-06-17).
- **Hipótesis:** [[H-MEZ-1]] — la atención full O(L²) es el cuello de botella de escalado en
  CPU frente a un mezclador de tiempo lineal O(L).
- **Pregunta del meta-prompt:** "¿Qué parte consume más recursos?"
- **Código:** `cognia_x/experiments/exp001_sequence_mixing_scaling/run.py`
- **Cómo correr:**
  `.\venv312\Scripts\python.exe cognia_x\experiments\exp001_sequence_mixing_scaling\run.py`
- **Método:** batch=1, d=64, float32, L ∈ {128…4096}, reps=3 + warmup. Tres mezcladores:
  (A) atención full softmax; (B) atención lineal (feature map elu+1, estado KV d×d); (C) SSM
  diagonal con scan en bucle Python. Tiempo = wall-clock medio. Memoria = tamaño analítico del
  tensor intermedio dominante (numpy no es fiable bajo `tracemalloc`).
- **Métrica:** ms/forward y MB del intermedio dominante; speedup y ratio de memoria.

### Resultado (ver tabla completa en `research_log.md` y `results/results.md`)
- Cruce en tiempo: **L=128** (lineal ya gana). Speedup lineal/full: 3.5× (L=128) → **70.3×** (L=4096).
- Memoria: full crece O(L²) (0.06→64 MB); lineal constante (0.0156 MB) → 4096× menos a L=4096.
- SSM-loop (O(L) teórico) **pierde** contra lineal vectorizado → factor constante domina en CPU.

### Amenazas a la validez (honestidad)
- Mide **coste**, no **calidad**: no dice nada de exactitud/recall/ICL. ⚠️ central.
- (A) y (B) son versiones **globales no-causales**; en decodificación autoregresiva causal el
  perfil cambia (KV-cache para A, estado recurrente para B/C). Pendiente exp003.
- numpy usa BLAS multihilo; los tiempos absolutos dependen de la máquina, pero las **tendencias**
  (cuadrático vs lineal) son robustas a la plataforma.
- d=64 fijo; el término O(L·d²) de la atención lineal podría importar con d grande. Pendiente barrido en d.

### Conclusión
H-MEZ-1 **apoyada para coste** (confianza alta). No habilita aún la decisión de reemplazo: falta
exp002 (calidad). El hallazgo accionable inmediato: cualquier arquitectura CPU-first debe evitar
el término O(L²) en el camino de mezcla por defecto.

---

## exp002 — Capacidad de recall asociativo  ✅ CORRIDO

- **Estado:** completo (2026-06-17).
- **Hipótesis:** [[H-MEZ-3]] — la capacidad de recall de un mezclador de estado acotado
  (atención lineal, estado d×d) está limitada por su tamaño de estado; la atención full no.
- **Código:** `cognia_x/experiments/exp002_recall_capacity/run.py`
- **Cómo correr:**
  `.\venv312\Scripts\python.exe cognia_x\experiments\exp002_recall_capacity\run.py`
- **Método:** training-free, sin hacks de temperatura. Se almacenan N pares (kⱼ→vⱼ), k,v ~
  N(0,I_d) (régimen estándar de la atención escalada). Se consulta cada kᵢ y se cuenta acierto si
  vᵢ es el vecino más cercano (coseno) entre los N valores. full = softmax(K·kᵢ/√d)·V; linear =
  estado S=Σ kⱼvⱼᵀ, lectura kᵢᵀS. d∈{32,64,128}, N∈{8…512}, 3 trials.

### Resultado
- Atención full: **accuracy ~1.0** en todo el rango (mín 0.96 en d=32,N=512).
- Atención lineal: se degrada con N. **Capacidad (máx N con acc≥0.9): 32→32, 64→128, 128→512**.
- **Capacidad = d²/32 exacto** → escala con el **tamaño del estado** (d² escalares), no con d.

### Amenazas a la validez
- Es una sonda de capacidad *representacional* (sin entrenar), no un modelo entrenado; un modelo
  entrenado podría comprimir mejor, pero el techo de estado acotado es estructural (pigeonhole).
- La constante 1/32 depende del umbral 0.9 y del ruido; lo robusto es el **escalado con d²**.

### Conclusión
H-MEZ-3 **apoyada** (confianza alta). Junto con exp001 establece un **trade-off coste↔capacidad**
medido: lineal barato pero recall acotado por estado; full caro pero recall ~ilimitado en N. →
Motiva la hipótesis del **híbrido** [[H-MEZ-4]] con evidencia en ambos lados, no por autoridad.

---

## exp003 (=E3) — Inexactitud del FedAvg de adapters LoRA  ✅ CORRIDO

- **Estado:** completo (2026-06-17). P0 del ciclo-1 (mejor impacto/coste).
- **Hipótesis:** [[H-CF-2]] — avg(B)·avg(A) ≠ avg(B·A); el FedAvg ingenuo de LoRA es inexacto.
- **Código:** `cognia_x/experiments/exp003_fedavg_lora_inexactness/run.py` (numpy puro, sin entrenar).
- **Cómo correr:**
  `.\venv312\Scripts\python.exe cognia_x\experiments\exp003_fedavg_lora_inexactness\run.py`
- **Método:** K clientes con adapters LoRA (r=8 = `_RANK_MAX` de Cognia). Comparar Δ_exact =
  mean(B_k@A_k) vs Δ_naive = mean(B_k)@mean(A_k); error relativo Frobenius. Barrer heterogeneidad
  (K=4) y nº de clientes (h=0.5). 20 trials, seed fijo.

### Resultado
- **Sanity:** heterogeneidad 0 → error = 0.00e+00 (clientes idénticos ⇒ exacto). La matemática cuadra.
- **Error vs heterogeneidad:** 0.4% → 2.7% → 10% → 33% → **66%** (h=0.1→2.0). Monótono creciente.
- **Colapso de rango (estructural):** Δ_exact rango 32 (=K·r); Δ_naive rango 8 (=r). El ingenuo
  descarta 4× la diversidad de los clientes, **independiente de la heterogeneidad**.
- **Matiz honesto:** el error *relativo* DECRECE con K (0.111→0.060 de K=2 a 16) bajo ruido iid
  alrededor de una media compartida — promediar más clientes reduce la varianza del término
  cruzado. El daño que SÍ crece con K es el colapso de rango, no la magnitud. (Refina la
  afirmación del sintetizador "error crece con K", que es model-dependiente.)

### Conclusión
H-CF-2 **apoyada** (confianza alta — es álgebra, no depende de papers). Confirma un bug real en
`coordinator/federated_store.py` de Cognia (Pass 3 promedia k_A,k_B,v_A,v_B por separado). Fix:
agregar Δ-W reconstruidas + re-SVD a rango r, o FedEx-LoRA. Hallazgo de Cognia-X con impacto en
Cognia (respeta la independencia: el experimento es standalone, el fix sería en Cognia si el dueño lo decide).

---

## exp004 (=E1) — Roofline CPU: GEMV memory-bandwidth-bound  ✅ CORRIDO
- **Estado:** completo (2026-06-17, ciclo-2 / manager CYCLE 1). **Sin llama.cpp**: microbench numpy
  puro de la operación núcleo del decode batch=1 (GEMV: matriz de pesos × vector).
- **Hipótesis:** [[A-008]]/[[H-BW-1]] — decode bandwidth-bound; bytes/peso↓ → throughput↑; hilos saturan.
- **Código:** `cognia_x/experiments/exp004_roofline_cpu/run.py` (numpy puro, determinista).
- **Cómo correr:** `.\venv312\Scripts\python.exe cognia_x\experiments\exp004_roofline_cpu\run.py`

### Resultado (i3-10110U, real)
**Eje bytes/peso (y=W@x):** float32 vs float64 → speedup ×2.40 / ×2.16 / ×2.21 (n=1024/2048/4096)
≈ proporcional a la mitad de bytes. GB/s clavado en **~15-22** pese a ×16 más cómputo de n=1024 a
4096; GFLOP/s solo 4-11 (muy bajo el pico FP) → **régimen memory-bound** (izquierda del codo del roofline).

**Eje hilos (n=4096, float32, vía OPENBLAS/OMP/MKL_NUM_THREADS):**
| hilos | ms | GB/s | speedup vs 1 |
|---|---|---|---|
| 1 | 4.383 | 15.31 | 1.00× |
| 2 | 3.932 | 17.07 | **1.11×** (pico) |
| 3 | 4.066 | 16.51 | 1.08× |
| 4 | 4.206 | 15.95 | 0.96× (peor) |

→ 1→2 hilos solo **+11%**; 3-4 hilos *empeoran* (contención de banda). Satura a ~2 hilos.

### Conclusión
H-BW-1 **confirmada por dos vías independientes**: (1) este microbench numpy (bytes/peso ≈2× ↔
mitad de bytes; GB/s plano; hilos saturan) y (2) la evidencia del vault en el decode real de
llama.cpp (spec decode 5× más lento, 3 hilos > 4, techo ~8 tok/s). Confianza ALTA. **Caveat:** el
GEMV solo modela el streaming de pesos; el decode completo además mueve KV-cache (refuerza el
argumento bandwidth, no lo debilita). El tramo bytes/peso no se extiende a ternario (unpack/LUT
es compute — coincide con el "fused int4 kernel 1.01x compute-bound" del vault).

---

## exp005 — Frontera coste↔recall del backbone híbrido (H-MEZ-4)  ✅ CORRIDO
- **Estado:** completo (2026-06-17, manager CYCLE 2). numpy puro, mide el **eje coste**; el eje
  recall viene de exp002.
- **Hipótesis:** [[H-MEZ-4]] — un stack mayormente lineal + pocas capas full se acerca al coste
  del lineal puro y al recall del full puro.
- **Código:** `cognia_x/experiments/exp005_hybrid_decode_frontier/run.py`
- **Cómo correr:** `.\venv312\Scripts\python.exe cognia_x\experiments\exp005_hybrid_decode_frontier\run.py`
- **Método:** un paso de decode por un stack de m=24 capas, k de atención full (KV-cache O(L)) +
  (24-k) lineales (estado fijo O(d²)), d=128. Caches/estados pre-construidos fuera del bucle
  cronometrado. Barrer k∈{0,1,3,6,12,24} × L∈{512,2048,8192}, 80 reps.

### Resultado (ms/token, verificado re-corriendo)
- **Pure linear (k=0): ~constante en L** (0.44→0.49 ms, +3% sobre ×16 de L).
- **Pure full (k=24): ~lineal en L** (2.4→9.9→41 ms).
- **Híbrido coste como % del full puro:** a L=8192 → k=1: ~7%, **k=3: ~12-15%**, k=6: ~26%. La
  ventaja crece con L (las capas lineales son constantes en L y dominan el ahorro).

### Conclusión
H-MEZ-4 **apoyada en su eje coste** (confianza alta). Junto a exp002 (recall: full ~ilimitado en
N, lineal acotado por d²): un híbrido **3/24 full** compra recall de nivel-full a **~12-15% del
coste de decode** del full puro a L=8192. **Caveat honesto:** a contexto corto (L=512) el ahorro
es modesto (k=3 ≈ 28% del full) — el payoff del híbrido depende de **contexto largo**. El recall
del stack híbrido aún no se midió end-to-end (requiere entrenar o construir la tarea multi-capa);
se infiere de exp002. → ciclo-3.

---

## exp006 — Coste del vocabulario: lm_head O(V) vs bloque transformer  ✅ CORRIDO
- **Estado:** completo (2026-06-17, manager CYCLE 3). numpy puro.
- **Hipótesis:** [[H-REP-1]] (input embed ≠ output lm_head) y [[H-REP-4]] (embed+head = fracción
  grande a 1-3B). Valida la decisión [[#5..]] D-008 "vocab moderado".
- **Código:** `cognia_x/experiments/exp006_vocab_lmhead_cost/run.py`
- **Cómo correr:** `.\venv312\Scripts\python.exe cognia_x\experiments\exp006_vocab_lmhead_cost\run.py`
- **Método:** d=2048, n_layers=24. (A) tiempo de lm_head `y=Eout@h` (GEMV O(V·d)) para V∈{8k…64k};
  (B) coste de 1 bloque (6 GEMVs); (C) lookup del embedding de entrada; (D) cruce; (E) memoria analítica.

### Resultado (verificado re-corriendo)
- **lm_head crece lineal con V** e **iguala 1 bloque transformer a V≈26.000** (a V=64k cuesta ~2.5×
  un bloque). Confirma el punto estilo FR-Spec donde la proyección de vocab empieza a pesar.
- **El embedding de ENTRADA es trivial:** lookup de 1 fila ≈ 0.001-0.003 ms, **~10⁴× más barato**
  que el lm_head → confirma la refutación de H-REP-1 (no confundir entrada con salida).
- **Memoria (con weight-tying):** embed+head = 1-10% a vocab moderado (≤64k), 18% a 131k, 30% a
  256k. Sin tying entra en la banda 25-37% antes (31% a 131k). → H-REP-4 cierto **a vocab grande o
  sin tying**; a vocab moderado tied la fracción es modesta.

### Conclusión
Refuerza **D-008 (vocab moderado)** desde dos ángulos: a vocab moderado el coste/token del head
queda ≤1 bloque y la huella de params es chica (1-10%); el riesgo de cómputo **y** memoria aparece
justo al ir a 128k-256k. Matiz honesto: el lm_head "domina **un** bloque" a V≈26k, pero igualar el
modelo entero (24 bloques) requiere V≈645k.

---

## exp007 — Eje de precisión: por qué int8 necesita kernels especiales  ✅ CORRIDO
- **Estado:** completo (2026-06-17, manager CYCLE 4). numpy puro.
- **Hipótesis:** caveat de [[H-BW-1]]/[[#3 D-009]] — la proporcionalidad bytes→tok/s (exp004) se
  ROMPE en int8 sin kernels dedicados; el ahorro de int8 es de memoria, no de cómputo automático.
- **Código:** `cognia_x/experiments/exp007_precision_axis/run.py`
- **Cómo correr:** `.\venv312\Scripts\python.exe cognia_x\experiments\exp007_precision_axis\run.py`
- **Método:** GEMV y=W@x, n∈{2048,4096}. Tres caminos: (1) float32 BLAS; (2) int8 naïve (matmul
  entera, sin BLAS); (3) dequant int8→float32 + BLAS. Cuantización simétrica por-tensor.

### Resultado (verificado re-corriendo)
| camino | n=2048 | n=4096 | vs float32 |
|---|---|---|---|
| float32 (BLAS) | ~1.0 ms | ~4.0 ms | 1.00× (ref) |
| int8 naïve (sin BLAS) | ~8.5 ms | ~35 ms | **~0.11× (8-10× más LENTO)** |
| dequant + float32 | ~14 ms | ~58 ms | ~0.07× (14× más lento) |
| memoria W | 16.8→4.2 MB | 67→17 MB | **4× menos (almacenamiento)** |

### Conclusión
El int8 en numpy puro **ahorra 4× de memoria pero NO acelera el cómputo** (es 8-10× más lento: la
matmul entera no toca BLAS; el dequant añade overhead). → confirma el caveat **D-009/H-BIT-1**: la
ley bytes→tok/s (exp004, válida float32 vs float64 ambos BLAS) **se rompe** en int8/ternario sin
kernels dedicados. **Esto es exactamente por qué existen T-MAC / bitnet.cpp** y coincide con el
vault ("fused int4 kernel 1.01× — compute-bound"). Realizar la velocidad de baja precisión exige
kernels especializados, no basta con cuantizar.

> Más fichas (E2 SWA vs full real con GGUF, E4 RAG vs LoRA, E5 peso de embedding en un GGUF real)
> en `future_work.md`.

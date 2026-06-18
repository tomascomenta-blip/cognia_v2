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

> Más fichas (exp005=E2 SWA vs full, E4 RAG vs LoRA, E5 peso de embedding) en `future_work.md`.

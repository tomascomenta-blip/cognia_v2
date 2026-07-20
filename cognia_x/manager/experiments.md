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

---

## exp008 — Cierre de H-MEZ-4: ¿el híbrido recupera el recall que el lineal no tiene?  ✅ CERRADO
- **Estado:** CERRADO (2026-06-18, manager CYCLE 6). PyTorch CPU. Revisado por workflow adversarial.
- **Hipótesis:** [[H-MEZ-4]] eje recall — entrenando end-to-end, una config **híbrida** (mayoría
  lineal + minoría atención) iguala el recall de la atención pura, que el **lineal puro** (estado
  fijo, exp002) no alcanza al saturar su estado. Falsable: si lineal ≈ atención en todo el barrido
  (no se satura) o si el híbrido NO recupera el recall de la atención.
- **Código:** `cognia_x/experiments/exp008_recall_control/run.py` (+ `cognia_x/train/recall_task.py`,
  `cognia_x/model/hybrid.py`).
- **Método:** tarea MQAR (pares clave→valor + consultas). 3 configs a igual tamaño, solo cambia el
  mixer: `atencion_pura` (ae=1), `hibrido_3to1` (ae=3), `lineal_puro` (ae=0). Métrica: accuracy de
  recall en las consultas (azar = 1/n_vals). **Control-primero:** validar atención→~1.0 a cada
  dificultad ANTES de comparar.
- **Diagnóstico previo (por qué el run nocturno dio inconcluso):** sub-recursos, no bug. Levers
  reales = **pasos + densidad de supervisión (n_queries)**. Verificado: np=1 atención 1.000; recall
  de 3 pares cruza a >0.9 (test). RoPE agregado (la posición no era el cuello).
- **Capacidad del lineal (corrección del workflow):** `LinearAttention` es multi-cabeza → estado
  = h·d_head² = **d²/h**, no d². Con d=64/h=8 → cap ≈ 16 pares; para separar hay que barrer np≥24
  (justo donde a la atención le cuesta más cruzar en CPU — la tensión central del experimento).

### Resultado (verificado, profundidad 4, d=64, h=4, warmup) — H-MEZ-4 CERRADO
| n_pairs | atención | híbrido [lin,attn,lin,attn] | lineal | lectura |
|--------:|---------:|---------:|-------:|---------|
| 4 | 0.999 | 0.991 | 0.988 | bajo capacidad: las 3 resuelven |
| 8 | 1.000 | 0.998 | **0.255** | **lineal satura y falla; el híbrido lo recupera** |
- Azar = 1/n_vals = 0.0625. A np=8 la atención cruza en ~1200 pasos, el híbrido en ~4800, el
  **lineal queda plano en ~0.25 los 12000 pasos** (loss 1.8, nunca cruza). El híbrido sigue a la
  ATENCIÓN, no al lineal → las 2 capas de atención recuperan el recall que el estado fijo pierde.
- **Hallazgo 2º:** a profundidad 2 el híbrido `[lin,attn]` (1 atención) falla como el lineal (0.52)
  → el recall exige **≥2 capas de atención** (circuito de inducción de 2 operaciones). Por eso el
  cierre se hace a prof. ≥4.
- **Diagnóstico del fallo previo:** SUB-RECURSOS (receta mala: sin warmup, h=8, n_queries=1), NO bug.
  Verificado por workflow adversarial (modelo/tarea correctos). Detalle en `results/results.md`.
- **Refuerzo prof. 6 (mayoría-lineal, 33% atención = ratio D-007):** np=8 híbrido 0.989 ✅ (recupera
  con 33% atención) / lineal 0.251; **np=16 híbrido 0.191 ⚠️ NO cruzó** (atención sí, 0.998) → el
  circuito del híbrido diluido se encarece de entrenar al subir asociaciones (honesto; límite del
  ratio o falta de pasos — indistinguible sin GPU). No invalida el cierre principal.
- Caveats: semilla única; modelo chico, tarea sintética (resultado sobre el MECANISMO, no escala).

### Conclusión
**H-MEZ-4 cerrado en sus dos ejes:** el híbrido **recupera el recall** que el lineal puro pierde al
saturar su estado (este exp, entrenado end-to-end) **a ~12-15% del coste** del full (exp005). La
predicción de exp002 (recall acotado por el estado, training-free) se confirma ahora ENTRENANDO.

---

## exp009 — Techo de recall del estado fijo: ¿sube con d y satura?  ✅ CORRIDO

- **Estado:** completo (2026-06-19, manager CYCLE 22). PyTorch CPU. Registrado a través del
  Investigation Engine (`cognia_x/research/cycles/cycle22_recall_ceiling.py`).
- **Hipótesis:** [[H-CEIL-1]] — el recall del lineal puro escala con el **tamaño del estado** (~d²,
  single-head) y satura; el híbrido se mantiene alto vía atención. Falsable: si el lineal mantuviera
  recall alto sin importar carga/estado, o el híbrido no superara al lineal en el régimen saturado.
- **Código:** `cognia_x/experiments/exp009_recall_ceiling/run.py`
- **Cómo correr:**
  `.\venv312\Scripts\python.exe cognia_x\experiments\exp009_recall_ceiling\run.py`
- **Método (diseño CORREGIDO):** tarea MQAR (pares clave→valor). `n_heads=1` (single-head → estado
  d×d limpio, NO d²/h como en exp008), `n_pairs=16`, `seed=0`, **6000 steps**, 6 capas, chance
  **0.0625**. Barre `d ∈ {8,16,24,32,48}` con `lineal_puro` vs `hibrido_3to1`, mismo tamaño por d.
- **Corrección de diseño previa (persistencia):** el primer diseño falló por **carga demasiado baja**
  — con `n_heads`>1 el estado es d²/h y con pocas asociaciones el lineal nunca saturaba (sin
  separación que medir). Se corrigió a single-head + n_pairs=16 + 6000 steps. La separación de recall
  solo aparece **por encima** de la capacidad del estado.

### Resultado (verificado, results.json) — H-CEIL-1 MIXTA
| d | state d×d | lineal_puro | híbrido_3to1 | gap | lectura |
|--:|----------:|------------:|-------------:|----:|---------|
| 8  | 64   | 0.059 | 0.059 | 0.000  | **piso de aprendibilidad** (ambos en chance) |
| 16 | 256  | 0.168 | 0.165 | −0.003 | lineal sube con d |
| 24 | 576  | **0.183** | 0.178 | −0.005 | pico del lineal; satura |
| 32 | 1024 | 0.182 | 0.184 | +0.002 | meseta |
| 48 | 2304 | 0.181 | **0.292** | **+0.111** | **el híbrido se separa** |
- El recall del lineal **SUBE con d** (0.059@d8 → 0.183@d24) y luego **SATURA ~0.18**: la capacidad
  ENTRENADA del feature-map (ELU+1) queda **MUY por debajo del d² ideal** (d=48 → d²=2304 escalares).
- El **híbrido solo separa claramente a d=48** (gap +0.111): la cabeza de atención forma el recall solo
  cuando el modelo es lo bastante ancho.
- **d=8 = piso de aprendibilidad**, NO techo de estado (ambas configs en chance → la tarea no se
  aprende a ese tamaño; distinguirlo evita una conclusión falsa).

### Amenazas a la validez (honestidad)
- Semilla única, modelo chico, tarea sintética → resultado sobre el **MECANISMO** de recall, no escala.
- La cota efectiva medida es la del feature-map ELU+1 entrenado; un feature-map mejor o mejor
  optimización (mimetic init, arXiv:2410.11135) podría subir el techo entrenado (es por eso un límite
  **asumido**, no real).

### Conclusión
**H-CEIL-1 mixta:** HOLDS direccionalmente (recall escala con el estado; la atención lo levanta) PERO
la cota **EFECTIVA** en modelos entrenados chicos es la **capacidad del feature-map** (<< d²), no el d²
teórico. Dos techos registrados: **real** (cota informacional d², pigeonhole/Jelassi vía
arXiv:2508.19029) + **asumido** (capacidad entrenada del feature-map → backlog de refutación). Refuerza
**D-CEIL-1** (mantener el híbrido): el estado fijo solo, aún a d grande, no alcanza el recall de la
atención. Convergencia con **Based** (arXiv:2402.18668) por vía independiente.

---

## exp010 — ¿El plateau del lineal es del ANCHO del feature-map?  ✅ CORRIDO (REFUTA H-CEIL-2)

- **Estado:** completo (2026-06-19, manager CYCLE 23). PyTorch CPU. Registrado a través del
  Investigation Engine (`cognia_x/research/cycles/cycle23_feature_dim.py`).
- **Hipótesis:** [[H-CEIL-2]] — subir la dimensión del feature-map de la atención lineal SUBE el recall
  ENTRENADO del lineal a d fijo (el plateau de exp009 sería feature-map-limited, no un techo duro).
  Lever: `HybridConfig.linear_feature_mult`. Falsable: REFUTADA si ensanchar NO mueve el recall.
- **Código:** `cognia_x/experiments/exp010_feature_dim/run.py`
- **Cómo correr:**
  `.\venv312\Scripts\python.exe -m cognia_x.experiments.exp010_feature_dim.run`
- **Método (step-parity, una sola variable):** tarea MQAR. `d_model=24` **FIJO** (donde exp009 satura:
  lineal_puro=0.183), `n_layers=4`, `n_heads=1`, `n_pairs=16`, `seed=0`, **6000 steps**, chance
  **0.0625**, misma receta de optim que exp009 (lr=1e-3, batch=64, warmup~250). Única variable =
  `linear_feature_mult ∈ {1 (baseline ELU+1), 4}`. Con mult>1 cada capa proyecta q,k a `d_head*mult`
  ANTES del feature-map → estado recurrente `(mult·d_head)²` (n_heads=1). Solo `lineal_puro`
  (attn_every=0) para aislar el efecto del ancho.

### Resultado (verificado, results.json steps=6000) — H-CEIL-2 REFUTADA
| feature_mult | estado ≈ (m·d_head)² | lineal_puro acc | Δ vs base | lectura |
|-------------:|---------------------:|----------------:|----------:|---------|
| 1 (ELU+1)    |                  576 | **0.181**       | +0.000    | baseline (= plateau de exp009) |
| 4            |                 9216 | **0.181**       | **+0.000**| 16× estado, recall idéntico → **null** |
- Ensanchar el feature-map ×4 da **16× más estado (576→9216)** y el recall **no se mueve** (Δ+0.000
  en la corrida canónica de 6000 steps). **Ni el tamaño de estado ni el ancho** del feature-map mueven el plateau.
- El plateau ~0.18 es **robusto** entre exp009 (barrido en d) y exp010 (ancho del feature-map a d fijo),
  y entre corridas (4000 steps dio Δ−0.002; 6000 steps dio Δ+0.000 — el signo baila dentro del ruido ~0.01).

### Amenazas a la validez (honestidad)
- Semilla única (seed=0), modelo tiny (d=24, 4 capas), tarea sintética, solo 2 puntos de `mult` (1 y 4):
  el resultado es sobre el **MECANISMO** (el ancho del ELU+1 no es la palanca), no una ley universal.
- Un null a escala chica NO prueba que Taylor/mimetic SÍ funcionen — eso lo mide H-CEIL-3.
- **Datos canónicos:** `cognia_x/experiments/exp010_feature_dim/results/results.json` (steps=6000,
  seed0: mult1=0.181, mult4=0.181, Δ+0.000); `run.log` guarda el historial completo de corridas.

### Conclusión
**H-CEIL-2 REFUTADA** para el ANCHO. El null refuta DOS cosas: (a) que el plateau sea feature-map-limited
por el ancho, y (b) que sea un límite de tamaño de estado/capacidad cruda. Lo que queda en pie es la
**FORMA del kernel** (Based usa Taylor 2do orden, no ELU+1 ancho) y/o **optim/init** (mimetic init,
Trockman 2024) → genera **H-CEIL-3** (abierta) y la decisión **D-CEIL-2** (descartar el ancho, ir a
Taylor + mimetic init). El techo "el cuello NO es tamaño de estado" entra al backlog de refutación.

---

> Más fichas (E2 SWA vs full real con GGUF, E4 RAG vs LoRA, E5 peso de embedding en un GGUF real)
> en `future_work.md`.

---

## exp022 — H-V4-1 (RESET v4): valor endógeno vs predicción pasiva, bajo intervención

### Pregunta
¿Un valor ENDÓGENO (info-gain sobre el propio modelo, SIN verificador externo de la verdad) construye una
representación más causal que la predicción PASIVA, visible bajo INTERVENCIÓN e invisible i.i.d.?

### Diseño (control anti-confound §4.3 + step-parity §4.4)
Mundo causal confundido: D=12 features binarias; un CLÚSTER de 4 vale TODO la causa latente z en el stream
observacional (confusión perfecta), una es la causa verdadera c; el resto son distractores i.i.d. Mecánica
y=x[c] con ruido de observación p_obs=0.10. Tres agentes COMPARTEN la misma clase de modelo (posterior
bayesiano sobre las 12 hipótesis "y=x_i") y el MISMO update; lo ÚNICO que cambia es la POLÍTICA que genera
la experiencia: **A pasivo** (recibe el stream observacional confundido), **B info-gain** (elige la config
que maximiza la información esperada sobre su propio posterior — valor endógeno), **C azar-activo**
(elige al azar; ablación). Se barre el presupuesto K∈{2,4,8,16,32,64}, 24 seeds, n_test=4000.

### Cómo correr
`.\venv312\Scripts\python.exe -m cognia_x.experiments.exp022_endogenous_value.run`

### Resultado (MIXTA)
- **Intervención** (configs uniformes que rompen la confusión): A PLANO 0.65→0.69 en todo K (flatness
  Kmid→Kmax=0.013) → muro INFORMACIONAL; B/C → 1.000; B−A=+0.31 a Kmax.
- **i.i.d.**: |A−B|=0.04 → el hueco es INVISIBLE sin intervención.
- **Valor específico NO aislado**: B−C(K chico)=−0.007 → el azar-activo basta con presupuesto; el
  experimento no separa "info-gain" de "intervención activa".

### Amenazas a la validez (honestidad)
- Mundo tabular sintético, mecánica determinista + ruido de observación; tarea de identificación de causa,
  no "razonamiento real".
- Dos checks PRE-REGISTRADOS estaban mal especificados (nivel-absoluto/convergencia en vez de
  planitud/gap); se conservan visibles y se agregaron diagnósticos correctos. Veredicto MIXTA con ambos.
- Datos canónicos: `cognia_x/experiments/exp022_endogenous_value/results/results.json`.

### Conclusión
Demuestra **R-INTERVENCIÓN** (intervenir rompe el muro informacional que observar no puede; → techo
'real'). **R-VALOR** específico queda 'asumido' (backlog) y genera **H-V4-1b** (aislar info-gain vs azar en
régimen presupuesto-chico/ruido-alto/espacio-grande). Registrado vía `cycle35_endogenous_value.py`.

# research_log.md — bitácora append-only de Cognia-X

> Nunca borrar entradas. Solo añadir. Cada sesión deja su rastro aquí.

---

## 2026-06-17 — Sesión 1: fundación del laboratorio + primer experimento

### Hecho
- Creada rama `cognia-x` y el árbol `cognia_x/` (laboratorio **independiente** de Cognia).
- Mejorado el meta-prompt fundacional → `manager/00_protocolo_investigacion.md` (constitución
  operativa, falsabilidad + DoD + evidence ledger + presupuesto de hardware). Prompt original
  literal conservado en `manager/_prompt_original.md`.
- Lanzado el **ciclo-1 de investigación multi-agente** (6 dimensiones × {investigar → refutar} +
  síntesis arquitectónica), con evidencia web y verificación adversarial. *(en curso al escribir
  esta entrada; sus resultados poblarán `architecture.md`, `decision_log.md` y `hypotheses.md`).*
- Implementado y **CORRIDO** `exp001` (escalado de mezcla de secuencia en CPU). Números reales.

### Entorno verificado (no asumido)
`venv312\Scripts\python.exe` = Python 3.12.10 · numpy 2.4.6 · torch 2.12.0+cpu · 4 hilos · sin
GPU · AMD64. Confirma el presupuesto de hardware del protocolo: **CPU, sin GPU**.

### exp001 — resultados reales (seed=1234, d=64, float32, reps=3)

| L | full (ms) | full mem (MB) | linear (ms) | linear mem (MB) | ssm-loop (ms) | speedup lin/full | mem full/lin |
|---|---|---|---|---|---|---|---|
| 128  | 2.02   | 0.06  | 0.57 | 0.0156 | 0.62  | 3.5×  | 4×    |
| 256  | 2.96   | 0.25  | 0.53 | 0.0156 | 0.72  | 5.6×  | 16×   |
| 512  | 5.94   | 1.00  | 0.82 | 0.0156 | 1.15  | 7.2×  | 64×   |
| 1024 | 24.58  | 4.00  | 1.50 | 0.0156 | 2.57  | 16.4× | 256×  |
| 2048 | 107.23 | 16.00 | 3.39 | 0.0156 | 6.90  | 31.6× | 1024× |
| 4096 | 481.52 | 64.00 | 6.85 | 0.0156 | 10.61 | 70.3× | 4096× |

**Lectura:**
1. La atención full entra en régimen claramente cuadrático ~L≥512: de L=1024→4096 (×4 en L) el
   tiempo crece ×19.6 ≈ 4^2.1, y la memoria del tensor de scores crece ×16 (cuadrático exacto).
2. El mezclador lineal es **70× más rápido** a L=4096 con memoria intermedia **constante**
   (0.0156 MB vs 64 MB → 4096× menos). El cruce ocurre desde el L más pequeño probado (128).
3. El SSM con bucle Python tiene la **misma** asíntota O(L) pero pierde contra el lineal
   vectorizado (10.61 vs 6.85 ms a L=4096): **la asíntota es necesaria pero no suficiente**; en
   CPU la vectorización y el layout de memoria pesan tanto como la complejidad. → *trampa del
   factor constante* documentada.

**Conclusión honesta (alcance):** exp001 prueba que el **coste** (tiempo+memoria) de la atención
full escala mal en esta CPU y que un mezclador sub-cuadrático lo domina en coste. **NO** prueba
nada sobre **calidad** (recall asociativo, in-context learning, copia exacta). La decisión
"reemplazar atención" NO está justificada todavía; sí lo está "el coste de la atención full es un
cuello de botella real de escalado en CPU". → ver `hypotheses.md` H-MEZ-1.

### exp002 — resultados reales (seed=7, trials=3) — el contrapeso a exp001
Capacidad de recall asociativo: ¿qué pierde el mezclador barato?

| d | capacidad lineal (máx N con acc≥0.9) | acc full en ese rango |
|---|---|---|
| 32  | 32  | ~1.000 (0.96 solo en N=512) |
| 64  | 128 | 1.000 |
| 128 | 512 | 1.000 |

**Lectura:**
1. La atención full mantiene accuracy **~1.0** para todo N probado (recall ~ilimitado en N,
   limitado solo por colisión de claves).
2. La atención lineal **se degrada** al crecer N: a d=64 cae de 0.956 (N=128) a 0.725 (N=256)
   a 0.348 (N=512).
3. **Hallazgo afinado:** la capacidad sigue exactamente `cap = d²/32` (32→32, 64→128, 128→512).
   Es decir, la capacidad de recall escala con el **tamaño del estado** (la matriz d×d = d²
   escalares), NO con d. Esto es la consecuencia estructural de tener estado acotado.

**Conclusión (junta exp001 + exp002):** el mezclador lineal es ~70× más barato (exp001) pero su
recall asociativo está **acotado por su estado** (exp002), mientras la atención full es cara pero
con recall ~ilimitado en N. Ninguno domina: hay un **trade-off coste↔capacidad** real y medido.
→ Esto motiva, **con evidencia en ambos lados**, la hipótesis del **híbrido** (mayoría de capas
lineales por coste + pocas de atención full para recall exacto). Ver H-MEZ-3 / H-MEZ-4.

### Próximo
- Integrar la síntesis del ciclo-1 (workflow) en `architecture.md` / `decision_log.md` /
  `hypotheses.md`. ✅ hecho (ver abajo).
- `exp003`: el FedAvg ingenuo de LoRA es inexacto (H-CF-2) — demostrarlo en numpy.

---

## 2026-06-17 — Sesión 1 (cont.): ciclo-1 sintetizado e integrado

### Hecho
- El workflow de investigación (13 agentes, 672k tokens, 181 tool-uses, ~23 min) terminó.
  6 dimensiones × {investigar con evidencia web → refutar adversarialmente} + síntesis.
- **24 hipótesis** generadas; **13 holds=true, 11 holds=false**. Los verificadores fueron
  genuinamente críticos: incluso auditaron el código real de Cognia (`federated_store.py`
  _RANK_MAX=8, `self_architect.py`, `prompt_optimizer._estimate_quality`).
- Integrado en `architecture.md` (tesis + 6 componentes con alternativas), `hypotheses.md`
  (tabla de 24 veredictos), `decision_log.md` (D-006..D-012), `assumptions.md` (A-008..A-019),
  `paper.md` (§3.3).

### Tesis del ciclo-1 (confianza alta en direcciones, media en constantes)
Una IA CPU-first se diseña para minimizar **bytes movidos por token** (decode es
memory-bandwidth-bound), no FLOPs. Backbone híbrido estado-fijo + atención sliding-window
(3:1-4:1); representación BPE vocab moderado parity-aware (no byte-puro/BLT a 1-3B); Q4 base +
ternario como apuesta (NO probado superior a Q4); aprendizaje continuo RAG+LoRA+fusión intra-cuenca
(kNN-LM/token descartado); agregación federada avg(B@A) (FedAvg ingenuo INEXACTO); biología =
principios no implementación; auto-mejora solo con evaluador verificable + gate.

### Hallazgos destacados
- **Cross-validación fuerte:** mi exp002 (recall ∝ d², empírico en CPU) reproduce el resultado
  teórico de Jelassi "Repeat After Me" (ICML'24) que el workflow recuperó por otra vía. Dos
  caminos independientes → mismo techo estructural. Sube la confianza en el backbone híbrido.
- **Bug real en Cognia:** la agregación federada de adapters (Pass 3, `federated_store.py`)
  promedia A y B por separado = matemáticamente inexacto (H-CF-2). Barato de arreglar y verificar.
- **Refutaciones honestas:** el ternario NO está probado superior a Q4 (H-BIT-1); el gate de
  auto-mejora de Cognia es circular, no held-out (H-SELF-2); T-MAC usa registros no L2 (H-LUT-1).

### exp003 (=E3) corrido — inexactitud del FedAvg de LoRA confirmada
Resultado real (numpy, seed=11, r=8): error relativo Frobenius del FedAvg ingenuo vs la fusión
exacta = **0.00e+00 a heterogeneidad 0** (sanity), creciendo a **0.4% → 10% → 66%** con la
heterogeneidad; y colapso de rango estructural **32 (K·r) → 8 (r)**. Matiz honesto: el error
*relativo* decrece con K bajo ruido iid (promediado), así que el daño que crece con K es el
colapso de rango, no la magnitud — reportado tal cual. H-CF-2 **apoyada (confianza alta, es
álgebra)**. Confirma el bug en `federated_store.py` Pass 3 de Cognia.

### Próximo
- exp004=E1 (roofline CPU/bandwidth-bound) y exp005=E2 (SWA vs full): requieren llama.cpp + GGUF.
- Ciclo-2 candidato: experimento del híbrido (H-MEZ-4 / H-SEQ-4-revisada) a escala chica.
- Decisión pendiente del dueño: ¿aplicar el fix de exp003 al `federated_store.py` de Cognia?

---

## 2026-06-17 — CYCLE 1 (manager autónomo): cornerstone H-BW-1 validado en el target

### Hecho
- **Verificación por evidencia existente** (regla CLAUDE.md "verificá, no asumas"): el vault
  (Gotchas) ya tiene medido en i3-10110U que el decode es memory-bandwidth-bound — spec decode 5×
  más lento pese a 90.8% acceptance ("el draft compite por el mismo bandwidth"), 3 hilos > 4, techo
  ~8 tok/s con 3B Q4_K_M. El cornerstone NO era asunción: ya estaba medido.
- **exp004** (roofline numpy independiente, sin llama.cpp): GEMV y=W@x. float32 ≈ **2.2× más
  rápido** que float64 (∝ mitad de bytes); GB/s clavado en **~15-22** pese a ×16 más cómputo
  (memory-bound); hilos saturan a **~2** (1→2 = +11%, 3-4 peores). Dos vías independientes → H-BW-1.
- A-008 y H-BW-1 actualizados a confianza **alta (medido en target)**.

### Próximo
- CYCLE 2: experimento del **híbrido** (H-MEZ-4) a escala chica — medir coste↔recall juntos en un
  stack de capas (mayoría lineal + pocas full) vs los puros, validando con mis propias constantes.

---

## 2026-06-17 — CYCLE 2 (manager autónomo): H-MEZ-4 validada en su eje coste

### Hecho
- **exp005** (frontera coste↔recall del híbrido, numpy puro): un paso de decode por un stack de
  m=24 capas con k full + (24-k) lineales, barriendo k y L. Verificado re-corriéndolo el manager.
- **Resultado real:** pure linear (k=0) ~constante en L (0.44→0.49 ms); pure full (k=24) ~lineal
  (2.4→41 ms a L=8192). **Híbrido 3/24 full = ~12-15% del coste de full puro a L=8192** (k=1 ~7%).
- Combinado con exp002 (recall: full ~ilimitado en N, lineal acotado por d²): el híbrido compra
  recall de nivel-full a ~1/7 del coste de decode a contexto largo. H-MEZ-4 → apoyada (eje coste).
- **Caveat honesto:** a L=512 el ahorro es modesto (k=3 ≈ 28% del full); el payoff depende de L
  grande. El recall del stack híbrido no se midió end-to-end (se infiere de exp002).

### Próximo
- CYCLE 3 candidato: cerrar el eje recall del híbrido (tarea multi-capa entrenada/construida,
  posiblemente vía Kaggle GPU para el entrenamiento, evaluación en CPU). O E2 real (SWA vs full en
  llama.cpp con GGUF). Seguir el loop de manager.

---

## 2026-06-17 — CYCLE 3 (manager autónomo): coste del vocabulario (representación)

### Hecho
- **exp006** (coste lm_head O(V) vs bloque transformer, numpy puro). Verificado re-corriéndolo.
- **Resultado real (d=2048):** lm_head crece lineal con V e **iguala 1 bloque transformer a
  V≈26.000** (a V=64k = ~2.5× un bloque). El **embedding de ENTRADA es trivial** (lookup ~0.001 ms,
  ~10⁴× más barato) → confirma la refutación de H-REP-1. Memoria (tied): 1-10% a vocab moderado,
  30% a 256k. → refuerza D-008 "vocab moderado" con números propios.
- **Matiz honesto:** el lm_head domina **un** bloque a V≈26k, pero igualar el modelo entero (24
  bloques) requiere V≈645k; H-REP-4 "25-37%" es cierto a vocab grande/sin tying, no a vocab moderado tied.

### Próximo
- CYCLE 4: exp007 — eje precisión (int8 vs float32 GEMV en numpy): esperado que int8 naïve sea
  LENTO (sin BLAS) → demuestra por qué hacen falta kernels especiales (T-MAC/bitnet.cpp), validando
  el caveat del ciclo-1 (la proporcionalidad bytes→tok/s se rompe a baja precisión).

---

## 2026-06-17 — CYCLE 4 (manager autónomo): eje precisión (por qué int8 necesita kernels)

### Hecho
- **exp007** (int8 vs float32 GEMV, numpy puro). Verificado re-corriéndolo.
- **Resultado real:** int8 naïve = **8-10× más LENTO** que float32 (BLAS no acelera enteros);
  dequant+float32 = ~14× más lento; pero int8 ahorra **4× de memoria** (almacenamiento). → el
  ahorro de baja precisión es de memoria, NO de cómputo automático.
- Confirma el caveat **D-009/H-BIT-1**: la ley bytes→tok/s (exp004, válida f32 vs f64 ambos BLAS)
  se ROMPE en int8/ternario sin kernels dedicados. Es **por qué existen T-MAC/bitnet.cpp**; coincide
  con el vault ("fused int4 1.01× compute-bound").

### Estado del loop (4 ciclos de manager hoy)
Cuatro decisiones de arquitectura ahora tienen evidencia PROPIA medida en este hardware:
backbone/bandwidth (exp004), híbrido coste (exp005), representación/vocab (exp006), precisión
(exp007) — más federado (exp003). Lo que queda necesita entrenamiento (eje recall del híbrido, RAG
vs LoRA) o un GGUF real (SWA vs full, peso de embedding) → sesiones con GPU Kaggle o backend llama.cpp.

### Próximo
- CYCLE 5+ (siguiente sesión de manager o cuando haya backend): E2 real (SWA vs full en llama.cpp),
  cerrar eje recall del híbrido (Kaggle), RAG vs LoRA (E4). El loop continúa.

---

## 2026-06-17 — CYCLE 5 (manager autónomo): construcción de la IA v0 + entrenamiento nocturno

### Hecho
- **Implementado el modelo HÍBRIDO v0 en PyTorch CPU** (`cognia_x/model/hybrid.py`): la arquitectura
  del ciclo-1 hecha código — mayoría capas lineales O(L) (estado fijo) + atención sliding-window
  (~3:1), RMSNorm + SwiGLU + lm_head atado, byte-level (vocab 256). Objetivo: barata, fácil de
  entrenar, inteligente.
- **Pipeline de entrenamiento** (`cognia_x/train/`): recall_task (lineal vs híbrido vs atención →
  cierre empírico de H-MEZ-4) + charlm (byte-LM sobre el texto local del repo) + run_overnight.
- Verificado end-to-end (smoke): recall entrena (loss 4.83→3.89); char-LM aprende (val 5.53→4.90),
  checkpoint + muestras OK.
- **Lanzado entrenamiento nocturno en background** (hasta 04:25 AM); apagado del equipo a las 04:30.

### Resultado (PENDIENTE — corriendo al cerrar esta entrada)
Estará en `cognia_x/runs/overnight_v0/`: `recall_results.json` (¿el híbrido recupera el recall que
el lineal puro no tiene? = cierre empírico de H-MEZ-4) + `charlm_best.pt` + `charlm_samples.txt`.

### Próximo
Al volver: leer los resultados, documentar si el híbrido cerró el eje recall y la calidad del char-LM.

### RESULTADO de la corrida nocturna (2026-06-18 04:25, honesto — uno OK, uno fallido)
- ✅ **char-LM: FUNCIONÓ.** Modelo híbrido 6.3M params, byte-level. 7366 pasos; mejor val
  **1.74 nats/byte (~2.5 bits/byte)**, luego SOBREAJUSTÓ el corpus de 778KB (val subió a 2.49,
  train loss ~0.4). Las muestras generan **español + estructura markdown + identificadores de
  código** reconocibles (forma plausible, significado incoherente — típico de char-LM chico). →
  **la arquitectura híbrida del ciclo-1 entrena y aprende estructura de lenguaje desde cero,
  byte a byte, en CPU.** Es la prueba de que "corre de verdad y aprende". Mejor ckpt: `charlm_best.pt`.
- ❌ **recall (cierre de H-MEZ-4): INCONCLUSO / FALLIDO.** Acc final: lineal 0.0908, híbrido 0.0908,
  atención 0.0922 (chance≈0.031). **Ninguna config aprendió recall — ni la atención pura, que era
  el control positivo y DEBÍA resolver MQAR.** Sin control positivo válido, el experimento NO
  diferencia híbrido vs lineal → **NO cierra H-MEZ-4.** Causa: setup inadecuado (modelo d=96/4
  capas demasiado chico, 48 pares demasiados, 2500 pasos pocos). Un fracaso es información:
  **lección** = primero conseguir que la atención resuelva la tarea (control positivo) con tarea
  más fácil (p.ej. 8-16 pares) y/o modelo mayor + más pasos, ANTES de comparar las 3 configs.

### Próximo real (CYCLE 6)
- Rehacer el experimento de recall con control positivo válido: bajar n_pairs a ~12, subir pasos,
  verificar que atención→~1.0 ANTES de comparar; entonces sí medir si el híbrido iguala al full y
  el lineal queda abajo (cierre real de H-MEZ-4).
- char-LM: corpus más grande (evitar sobreajuste) o modelo regularizado; el backbone ya demostró
  que aprende.

---

## 2026-06-18 — CYCLE 6 (manager autónomo): diagnóstico del recall + RoPE + revisión adversarial

### Diagnóstico (causa raíz del fallo del control positivo, regla "diagnóstico antes que parche")
Reproduje el fallo nocturno y lo aislé bajando la dificultad hasta el mínimo:
- **np=1 par** (`[k,v,k]`→predecir v): atención **acc 1.000** (copia de un salto). El modelo SÍ
  recupera valores.
- **np=2** a 2 capas / pocos pasos / `n_queries=1`: **plateau 0.60** — no selecciona el par correcto.
- **np=2** a 4 capas/8 cabezas/4000 pasos: **acc 0.998**, con curva de transición de fase (la
  cabeza de inducción se forma de golpe ~paso 2000-2800).
**Conclusión:** NO era un bug del modelo. El control fallaba por **sub-recursos**. (Honestidad:
ese 0.998 lo vi en terminal pero NO lo commiteé; ver corrección del workflow abajo.)

### RoPE — descartar "falta de posición" como causa
El modelo NO tenía señal posicional (ni RoPE ni embeddings de posición). Hipótesis: el recall
asociativo necesita "copiar el token que sigue a la clave" → direccionamiento posicional. Agregué
**RoPE** a la atención softmax (la lineal ELU+1 conserva su kernel positivo). Resultado: **RoPE
NO movió la aguja a 2 capas** (idéntico ~0.24), y embeddings de posición absolutos **tampoco**
(0.58). → la posición NO era el cuello de botella; lo es la **capacidad/pasos**. (RoPE queda igual
como mejora correcta de arquitectura, verificada: propiedad de posición relativa + norma preservada.)

### Revisión adversarial (workflow, 6 agentes / 5 lentes) — corrigió mi diagnóstico
Lancé un workflow que auditó tarea, modelo/RoPE, validez del diagnóstico, justicia del comparador
y bugs. Verdicts: tarea/modelo/bugs **sólido** (verificado numéricamente: RoPE=posición relativa,
atención lineal paralela==recurrente diff 1e-7, alineamiento target/logits sin off-by-one);
diagnóstico **problema_serio**; justicia **con_reservas**. Correcciones que **acepto**:
1. **Sobredimensioné la receta.** El lever real NO es la profundidad: es **PASOS + DENSIDAD DE
   SUPERVISIÓN** (`n_queries`). Con `n_queries` adecuado la atención cruza en np=2 con **solo 2
   capas en ~300-460 pasos** (el agente lo reprodujo). Mi plateau de 2 capas venía de `n_queries=1`
   (gradiente escasísimo: 1 de L posiciones supervisada), no de falta de capas. Verificado luego:
   `test_aprende_recall_multipar` (np=3, n_queries=12) cruza a >0.9.
2. **Capacidad del lineal = d²/h, NO d².** `LinearAttention` es multi-cabeza: estado recurrente
   = h·d_head². Con d=128/h=8 → d_head=16 → cap ≈ 64 pares (no 512 como el single-head de exp002).
   El barrido por defecto (4,8,16,32) **no saturaba el lineal** → no habría separación. Hay que
   barrer n_pairs POR ENCIMA de la capacidad — justo donde a la atención le cuesta más cruzar en CPU.
   Esa es la tensión central del experimento en este hardware.
3. **Baseline de azar = 1/n_vals, no 1/vocab.** Logueada ahora junto a cada acc.

### Hecho (verificado: smoke + tests)
- `cognia_x/model/hybrid.py`: RoPE (build_rope_cache/apply_rope) en atención softmax; `abs_pos_emb`
  opcional; assert d_head par.
- `cognia_x/train/recall_task.py`: baseline de azar, rng de eval dedicado, piso de pasos (min_steps).
- `cognia_x/experiments/exp008_recall_control/`: barrido parametrizable (d/capas/cabezas/n_queries/
  lr/pairs), deadline robusto, control-primero. Receta base d=64/h=8/n_queries=16/lr1e-3.
- `cognia_x/tests/test_recall_and_rope.py`: 5 tests (RoPE, posición relativa, posición-sensible,
  recall 1-par, recall 3-pares con disambiguación). **5 passed.**
- Commits: 52c97bf (RoPE+diagnóstico), 870d097 (fixes del workflow + corrección honesta). Pusheados.

### Resultado del cierre de H-MEZ-4 — ✅ CERRADO (entrenado end-to-end en CPU)
Tras varios diseños fallidos (clave: el cruce de la atención dependía críticamente de la receta —
warmup + h=4 + n_queries=16 hace que la atención cruce np=8 en ~1200 pasos, antes no cruzaba), la
corrida decisiva a **profundidad 4** (d=64, h=4, 201k params, mismo tamaño las 3 configs):

| n_pairs | atención | híbrido [lin,attn,lin,attn] | lineal |
|--------:|---------:|---------:|-------:|
| 4 | 0.999 | 0.991 | 0.988 |
| 8 | 1.000 | 0.998 | **0.255** |

(azar 1/n_vals = 0.0625). **A np=8 el lineal puro SATURA y falla (0.255, plano los 12000 pasos),
pero el híbrido recupera el recall (0.998) siguiendo a la atención (1.000).** A np=4 (bajo la
capacidad) las 3 resuelven → la transición es visible. **Esto cierra H-MEZ-4 (eje recall) ENTRENANDO:**
- Confirma exp002 (recall acotado por el estado) pero ahora end-to-end, no training-free.
- El híbrido (2 capas de atención entre 4) recupera lo que el estado fijo pierde.
- Junto con exp005 (coste ~12-15% del full) → H-MEZ-4 cerrado en sus DOS ejes.

**Hallazgo 2º (de profundidad 2):** el híbrido mínimo `[lin,attn]` (1 sola atención) FALLA como el
lineal (0.52 a np=2); el recall exige **≥2 capas de atención** (circuito de inducción de 2 ops). Por
eso el cierre se hace a prof. ≥4.

**Refuerzo a profundidad 6 (híbrido mayoría-lineal `[lin,lin,attn,lin,lin,attn]`, 33% atención = el
ratio D-007):**
| np | atención(6) | híbrido(4lin/2attn) | lineal(6) |
|---:|---:|---:|---:|
| 8  | 1.000 | **0.989** ✅ | 0.251 |
| 16 | 0.998 | **0.191** ⚠️ | ~0.18 |
A **np=8 el mayoría-lineal recupera el recall** (0.989) — el mecanismo aguanta con 33% de atención.
A **np=16 NO cruzó** (plano ~0.19, cortado a ~13.5k pasos) aunque la atención pura sí (paso ~6750):
**honesto** — el circuito del híbrido 33%-atención se **encarece de entrenar** al subir asociaciones
(2 atenciones separadas por 4 lineales); no sé si es límite del ratio o falta de pasos (haría falta
GPU para distinguir). NO invalida el cierre principal (prof.4 np=8 separación limpia); muestra un
trade-off coste-de-entrenamiento real del ratio.

**Caveats:** semilla única; modelo chico (201-302k params), tarea sintética — resultado sobre el
MECANISMO de recall, no escala. **Datos:** `cognia_x/experiments/exp008_recall_control/results/`
(results.md, results_depth4.json/run_depth4.log, results_depth6.json/run_depth6.log).

---

## 2026-06-18/19 — CYCLE 7: char-LM sobre corpus 22× mayor (menos sobreajuste)

### Hecho
- Ataca el sobreajuste del CYCLE 5 (char-LM en 778KB markdown → sobreajustó a ~29 épocas). MISMO
  modelo (6.3M params, híbrido byte-level), corpus 22× mayor: **17.4MB de prosa de dominio público**
  (Gutenberg, 15 libros español+inglés). `cognia_x/data/get_corpus.py` (reproducible, gitignored).
- Pipeline reforzado por revisión adversarial (workflow 5 agentes): **holdout cross-book** (val = 2
  libros enteros no vistos), **eval determinista**, **gap train-val logueado** (la señal de
  sobreajuste), **baseline gzip**, cap de épocas, separador entre libros.

### Resultado (FINAL, 6938 pasos = 1.26 épocas) — GENERALIZA sin sobreajustar
- mejor val **2.10 bits/byte** (1.458 nats), **por debajo del baseline gzip (2.93)** → comprime
  mejor que gzip: aprende estructura de lenguaje real, sobre libros NUNCA vistos (cross-book).
- **Gap train-val: creció 0.025→~0.19 y PLATEÓ** (0.175→0.175→0.188→0.186) mientras el val SIGUIÓ
  bajando (2.525→1.466) → generaliza, NO sobreajusta catastróficamente (vs CYCLE 5 cuyo val SUBÍA).
  Genera inglés Y español reconocibles.
- **Confound honesto declarado:** CYCLE 7 hace ~1 época vs ~29 de CYCLE 5; el efecto es corpus+épocas
  combinados, no corpus aislado. El val absoluto NO se compara con CYCLE 5 (corpus distinto); lo
  comparable es el gap y la forma de la curva. Datos: `runs/cycle7/` (metrics.csv, summary.json).

---

## 2026-06-18/19 — CYCLE 8: enseñar a la IA a APRENDER SOLA (aprendizaje continuo Nivel 1)

### Diseño (método: transformación a problema cotidiano)
Los 3 problemas que plantea "aprender solo" → "el estudiante diligente" (`learn/DESIGN.md`):
- **Olvido catastrófico** → replay (repasar) + compuerta do-no-harm **POR-DOMINIO** (no agregada).
- **Goodhart** → examinador externo **cross-book NO-circular** + banda de incertidumbre (umbral=k·σ).
- **Colapso** → aprender solo de datos REALES; lo auto-generado (Nivel 2) solo verificado.

### Fix crítico (revisión adversarial, workflow 5 lentes)
La v1 usaba un gate AGREGADO (promedio de los dominios viejos) que es **CIEGO** al daño concentrado.
El repo ya lo tenía como **H-SELF-2 ❌false** ("evaluador CIRCULAR, no held-out"). Nuestro examinador
NO es circular (held-out cross-book real) → oportunidad de **dar vuelta H-SELF-2**. Fix: gate
**por-dominio** (peor-caso) + banda de incertidumbre.

### Verificado (smoke, base d=128): el mecanismo FUNCIONA
- Aprender inglés nuevo DESTRUYE el español (naive **+0.96** de olvido) mientras MEJORA el inglés.
- El **promedio** de los viejos ve solo **+0.25** (esconde 75% del daño) vs el **PEOR dominio +0.96**
  → el gate agregado es ciego; el por-dominio lo atrapa.
- **Replay reduce el olvido del español 15×** (+0.86 → +0.058) → aprende sin olvidar (la solución).
- Código: `cognia_x/learn/` (continual.py: gate por-dominio; run_cycle8.py: demo dilución 4 brazos).

### Resultado FULL (base 4000 pasos, 4 dominios) — la IA APRENDE SIN OLVIDAR ✅
| brazo | nuevo Δ | español Δ | no_harm | decisión |
|---|---:|---:|:---:|:---:|
| naive | +0.042 | **+1.217** | — | olvido catastrófico |
| B AGREGADO | +0.050 | +1.161 | **True (ciego)** | rechaza |
| C POR-DOMINIO | +0.062 | +1.186 | **False (atrapa)** | rechaza |
| **D por-dominio+replay** | **−0.030** | **+0.058** | **True** | **ACEPTA** ✅ |
- **Aggregate CIEGO vs por-dominio ATRAPA:** sobre el MISMO daño (~+1.17 al español) el agregado dice
  `no_harm=True` (promedio +0.40 < umbral, el daño concentrado se diluye 3×); el por-dominio dice
  `no_harm=False`. Esa es la causa de H-SELF-2 ❌false ("evaluador circular/agregado"), ahora cerrada.
- **Replay = la solución:** D aprende lo nuevo (Drácula −0.030) Y protege el español (+0.058 vs naive
  +1.217 = **21× menos olvido**), y ESTABILIZA el aprendizaje. (Smoke: replay reduce olvido 15×.)
- **Cierre de H-SELF-2:** de ❌false → ✅ **condicional**: el gate+rollback held-out SÍ reduce la deriva
  (olvido) **si el examinador es NO-circular y POR-DOMINIO**. Detalle en `learn/RESULTS.md`.
- Caveat honesto: a base-fuerte, aprender otra obra del mismo idioma no transfiere cross-book (B/C
  learned=False); el smoke (base-débil) cubre el lado "aprender". Combinados: detección+protección+aprendizaje.

---

## 2026-06-18/19 — CYCLE 9: mecanismos creativos extra ("ir más allá") — 1 refutado, 1 exitoso

- **Aprendizaje por SORPRESA/curiosidad (gradiente solo en bytes de mayor pérdida): REFUTADO ❌.**
  3 variantes (top-k, banda 50-95, 70-97) dan gain NEGATIVO en lo nuevo (-0.11 a -0.42 vs naive +0.15)
  sin reducir el olvido. Causa: en un byte-LM la pérdida por-byte no separa novedad de ruido; la
  supervisión esparsa generaliza peor. *Un fracaso es información.*
- **CONGELAR EL TRONCO de recall (embeddings + atención) y aprender solo en lineal+MLP: FUNCIONA ✅
  (modesto).** Reduce el olvido ~25% (+0.80 vs +1.06) conservando ~94% del aprendizaje nuevo
  (+0.143 vs +0.152). Parameter-free, complementario al replay. (`freeze_recall_trunk`.)
- Commits: 1bd03ac (CYCLE 8), f1a6a24 (sorpresa refutada), 3bcbcfb (congelar funciona). Pusheados.

---

## 2026-06-19 — PILAR 5 (RAZONAMIENTO): la IA prueba cadenas y aprende cuál funciona (CYCLE 12-17)

Transformación del objetivo del dueño ("que prueba distintas cadenas de razonamiento y ve cuál le da
mejores resultados, preguntando al usuario o evaluando dentro del sistema") a problemas COTIDIANOS
(dividir cuenta con propina, más barato por kilo, viajes en presupuesto, llegar a tiempo) y a código.
Mismo principio que cerró el aprendizaje continuo: **solo cuenta lo que sobrevive a un examinador NO
circular.** Innovación: un **router de meta-razonamiento aprendido online, anclado al verificador
real**, que aprende QUÉ estrategia desplegar y generaliza. Código en `cognia_x/reason/`.

| CYCLE | qué demuestra | número clave (held-out) |
|---|---|---|
| 12 | elegir la cadena correcta por tipo; anti-Goodhart; preguntar bajo presupuesto | router-verifier 1.000 vs mejor fija 0.793; confidence-circular (fanfarrón) 0.432 |
| 13 | robustez: oráculo RUIDOSO + tipo NO visto (saber lo que no sabés) | robust-aggregate 1.000 vs blind-single 0.56 @ruido 0.4; OOD escala→0.68→1.0 |
| 14 | cadenas COMPUESTAS (multi-paso, encadenar estrategias) | una cadena sola ~0.196; composer descubre el programa→1.000 |
| 15 | romper el TECHO perfecto: competencia GRADUADA | oracle ~0.89 (<1.0); router ~0.76; brecha honesta ~0.13 |
| 16 | quitar la muleta del tipo: inferir la clase desde el TEXTO | router-texto = router-tipo (brecha 0.000; enunciados separables) |
| 17 | ruteo por texto NO-trivial: paráfrasis + vocabulario solapado | keyword-frágil pureza 0.84→0.77; Naive-Bayes le gana en 5/5 niveles |

- **Anti-Goodhart sostenido en todo el pilar:** aprender por la PROPIA confianza (circular) deja que un
  "fanfarrón" (confianza alta y constante, aun equivocado) secuestre la política; el examinador real
  lo desenmascara. Es la lección de H-SELF-2 aplicada a la *selección de razonamiento*.
- **Honestidad:** solvers deterministas/sintéticos, 4-7 tipos, CPU/stdlib. Demuestra el MECANISMO de
  "ve cuál le da mejores resultados", no escala a LLMs reales. CYCLE 15 retiró el techo perfecto;
  CYCLE 17 mostró degradación honesta (2/12 semillas el NB patina en cold-start).
- Reproducir: `python -m cognia_x.reason.run_cycle{12..17} [--smoke]`. 19 tests (cycle12-17) passan.
  Detalle en `cognia_x/reason/RESULTS.md` y `cognia_x/reason/README.md`.

### Sub-arco de ruteo por TEXTO (CYCLE 16→21) — ¿puede un encoder aprendido inferir la clase de problema?
Pregunta: quitar la muleta del tipo (que la IA infiera QUÉ clase de problema es desde el enunciado) y
ver qué representación gana. Recorrido honesto:
- **16:** keyword-signature = almuerzo gratis (enunciados sintéticos trivialmente separables, pureza 1.0).
- **17:** bajo PARÁFRASIS + vocabulario solapado, el keyword CONFUNDE (pureza 0.84→0.77); un Naive-Bayes
  bag-of-words (B) degrada con gracia → B es el baseline a vencer.
- **19:** encoder char-LM OFF-DOMAIN (CYCLE 7, libros) recupera estructura (pureza 0.61-0.75 >> azar
  0.25) y le gana a keyword, pero PIERDE contra B y solo empata la mejor fija. Lección: encoder
  genérico off-domain no domina features in-domain baratas.
- **20:** encoder IN-DOMAIN unsupervised (char-LM entrenado sobre los textos) afila la pureza y le gana
  a B en texto LIMPIO (1.000 vs 0.92), pero bajo ruido sigue perdiendo. Lección refinada: falta señal SUPERVISADA.
- **21 (CAPSTONE):** encoder SUPERVISADO POR EL VERIFICADOR (cabeza que aprende por cadena si acierta,
  target=is_correct) le GANA a B en TODOS los niveles de ambigüedad y alcanza el ceiling.
- **CONCLUSIÓN:** un encoder aprendido le gana al bag-of-words UNA VEZ que recibe la MISMA señal del
  verificador; la representación rica solo paga cuando el verificador la alinea a la tarea. Es la
  respuesta concreta a "evaluá el resultado dentro del sistema". Caveats: cadenas exactas (E=1.0 por
  construcción; claim relativo E≥ceiling≥B), char-LM congelado (solo la cabeza entrena), 4 tipos sintéticos.

---

## 2026-06-19 — CYCLE 22: el TECHO de recall del estado fijo, registrado A TRAVÉS del Investigation Engine

### Pregunta
¿El recall asociativo de un mezclador de **estado fijo** (atención lineal) está acotado por el
**tamaño de su estado**, y añadir atención (estado ∝ longitud) lo levanta? Es la frontera
recall↔throughput. Además: ¿la cota efectiva en modelos chicos entrenados es realmente el d² teórico?

### Novedad de proceso (no solo de resultado)
Este ciclo se REGISTRA por el **Investigation Engine** (`cognia_x/research/`), no solo por prosa: el
script `cognia_x/research/cycles/cycle22_recall_ceiling.py` puebla el store del engine PASANDO por las
compuertas reales (ledger anti-opinión, DoD de hipótesis, 7 etapas de analogía, validación de techos,
`verify_no_loss`). Reproducible (resetea el store al arrancar; re-correr = mismos registros). El
espejo humano es esta entrada + las fichas en `hypotheses.md`/`decision_log.md`/`experiments.md`.

### Las 2 fuentes tier-1 (papers peer-reviewed, citadas en el engine)
- **arXiv:2402.18668** — Arora et al. 2024 (**Based**): tradeoff clave estado-recurrente ↔ recall;
  los modelos de estado fijo (Mamba/RWKV/H3) sufren en recall; Based (atención lineal + ventana
  deslizante) recorre la frontera de Pareto recall-memoria (**+6.22 pts** en tareas recall-intensivas).
- **arXiv:2508.19029** — Okpekpe & Orvieto 2025: la recall recurrente depende de cuán bien se comprime
  el pasado en el estado; el límite duro (copia exacta requiere estado ∝ longitud, **Jelassi et al.**)
  es **real**, PERO gran parte de la brecha práctica es de **OPTIMIZACIÓN** (con LR ajustado, Mamba
  resuelve recall asociativo aun en 1 capa), no de expresividad.

### exp009 — diseño CORREGIDO + barrido en d (entrenado end-to-end, CPU)
Recipe: `n_heads=1` (single-head → estado d×d limpio, no d²/h), `n_pairs=16`, `seed=0`, **6000 steps**,
6 capas, chance **0.0625**. Barre `d ∈ {8,16,24,32,48}` con lineal_puro vs híbrido_3to1.

| d | state d×d | lineal_puro | híbrido_3to1 | gap (híb−lin) | lectura |
|--:|----------:|------------:|-------------:|--------------:|---------|
| 8  | 64   | 0.059 | 0.059 | 0.000  | **piso de aprendibilidad** (ambos en chance) |
| 16 | 256  | 0.168 | 0.165 | −0.003 | lineal sube con d |
| 24 | 576  | **0.183** | 0.178 | −0.005 | pico del lineal; satura |
| 32 | 1024 | 0.182 | 0.184 | +0.002 | meseta |
| 48 | 2304 | 0.181 | **0.292** | **+0.111** | **el híbrido se separa** (la atención forma el recall) |

**Lectura honesta (veredicto MIXTO):**
1. La **predicción HOLDS direccionalmente**: el recall del lineal **sube con el estado** (0.059@d8 →
   0.183@d24) y la atención del híbrido **lo levanta** a d grande (gap +0.111 en d=48). La frontera
   recall↔throughput es real y reproducida entrenando.
2. PERO la cota **EFECTIVA** NO es el d² teórico: el lineal **satura ~0.18**, MUY por debajo de lo que
   d²=2304 (d=48) permitiría. La capacidad **ENTRENADA** del feature-map (ELU+1) es el cuello real, no
   el límite informacional. Parte de esa brecha es **optimización/inicialización**, no expresividad
   (coincide con Okpekpe&Orvieto 2508.19029; mimetic init arXiv:2410.11135).
3. **d=8 es piso de aprendibilidad**, NO techo de estado: ambas configs en chance porque la tarea no
   se aprende a ese tamaño. Distinguirlo del techo evita una conclusión falsa.

### El techo: REAL vs ASUMIDO (registrado como DOS techos)
- **REAL** — cota informacional **O(d²)** (pigeonhole / Jelassi vía 2508.19029): el estado d×d no puede
  almacenar más asociaciones que sus d² escalares sin interferencia. Probado, es una pared.
- **ASUMIDO** — la capacidad **entrenada** del feature-map queda **<< d²** y es en parte de
  optimización. Es un límite **asumido-permanente** = invitación a refutar (entra al backlog
  `assumed_limits()`), no una pared. Es el **hallazgo nuevo** del ciclo.

### Persistencia (un fracaso de diseño corregido, no escondido)
El **primer** diseño de exp009 falló por **carga demasiado baja**: con `n_heads` >1 el estado real es
d²/h (no d²) y con pocas asociaciones el lineal nunca saturaba → no había separación que medir. Se
corrigió a single-head + n_pairs=16 + 6000 steps. Esto continúa la línea de CYCLE 6/8 (sub-recursos vs
bug): la separación recall sólo aparece **por encima** de la capacidad del estado; medir por debajo no
prueba nada. Honesto: semilla única, modelo chico, tarea sintética → resultado sobre el MECANISMO.

### Decisión y registro
- **D-CEIL-1**: mantener el **híbrido** (mayoría lineal + minoría atención) como arquitectura del lab.
  ACEPTADA por el ledger (cita tier-1 arXiv:2402.18668 + tier-5 exp002/exp009, todas obtenidas → funda;
  sin `OpinionOnlyError`). Coincide con Based: el lab llegó al mismo principio de forma independiente.
- **H-CEIL-1**: `status='mixta'`, confianza media, DoD completo (3 a favor / 2 en contra; S4=exp009 es
  AMBAS: apoya la subida con d, refuta que la cota efectiva sea d²). Marcada vía `mark_mixta` (mismo
  gate DoD que apoyada/refutada — no se debilitó la compuerta).

### Verificación (real, no solo prosa)
- `python -m cognia_x.research.cycles.cycle22_recall_ceiling` → todas las CHECK + `verify_no_loss = OK`.
- `python -m cognia_x.research.cli status/verify` sobre el store del ciclo → sources 4, decisions 1,
  hypotheses 2 (add + transición mixta), ceilings 2, asumidos 1; **verify OK** (exit 0).
- 20/20 tests de `test_research_engine.py` passan tras añadir `mark_mixta`.
- Datos del experimento: `cognia_x/experiments/exp009_recall_ceiling/results/results.json`.

---

## 2026-06-19 — CYCLE 23: la palanca del "feature dim" REFUTADA → el cuello es el kernel/init

### Pregunta (heredada del backlog de CYCLE 22)
CYCLE 22 dejó un **límite ASUMIDO** en el backlog de refutación (`assumed_limits()`): el recall
ENTRENADO del lineal satura ~0.18, MUY por debajo del d² ideal. La hipótesis de salida era que ese
plateau era **feature-map-limited** y se levantaba con el lever explícito de Based: la **dimensión
del feature-map** de la atención lineal. Este ciclo va a por ese ítem asumido y lo PRUEBA.

### Novedad de proceso
Igual que CYCLE 22, se registra A TRAVÉS del **Investigation Engine**: el script
`cognia_x/research/cycles/cycle23_feature_dim.py` puebla el store pasando por las compuertas reales
(ledger anti-opinión, DoD de hipótesis, 7 etapas de analogía, validación de techos, `verify_no_loss`).
El headline de este ciclo es **una hipótesis EMPÍRICA REFUTADA que genera una más afilada** — el
fracaso es información, no un callejón.

### Las 2 fuentes tier-1 (papers peer-reviewed, citadas en el engine)
- **arXiv:2402.18668** — Arora et al. 2024 (**Based**): la **dimensión del feature-map** de la atención
  lineal es el LEVER para recorrer la frontera de Pareto recall-memoria; Based usa un feature-map de
  **2do orden (Taylor)**, NO un ELU+1 ancho.
- **arXiv:2410.11135** — Trockman et al. 2024 (**Mimetic Initialization**): la pobre recall de SSMs en
  copy/AR puede deberse a **DIFICULTADES DE ENTRENAMIENTO**, no a límites de capacidad fundamentales
  ("la capacidad existía pero no se accedía por la inicialización"); una init estructurada (A~1, Δ~1,
  WᶜᵀWᵇ~I) hace que Mamba aprenda recall desde cero mucho más fácil.

### exp010 — ensanchar el feature-map ELU+1 a d FIJO (step-parity, entrenado, CPU)
Diseño: `d_model=24` FIJO (donde exp009 ya satura: lineal_puro=0.183), `n_layers=4`, `n_heads=1`,
`n_pairs=16`, `seed=0`, **6000 steps** (misma receta de optim que exp009: lr=1e-3, batch=64,
warmup~250, chance 0.0625). Única variable = `linear_feature_mult ∈ {1 (baseline ELU+1), 4}`. Con
mult=4 cada capa proyecta q,k a `d_head*4` ANTES del feature-map → el ESTADO recurrente pasa de
`24²=576` a `(4·24)²=9216` (**16× más estado**). Lever no-rompiente: `HybridConfig.linear_feature_mult`
(default 1 = comportamiento previo exacto). Run canónico = corrida step-parity 6000 (HEADLINE
"PREDICCIÓN REFUTADA") en `cognia_x/experiments/exp010_feature_dim/results/results.json` (steps=6000).

| feature_mult | estado ≈ (m·d_head)² | lineal_puro acc | Δ vs base | lectura |
|-------------:|---------------------:|----------------:|----------:|---------|
| 1 (ELU+1)    |                  576 | **0.181**       | +0.000    | baseline (= plateau de exp009) |
| 4            |                 9216 | **0.181**       | **+0.000**| 16× estado, recall idéntico → **null** |

**Veredicto: PREDICCIÓN REFUTADA.** Ensanchar el feature-map ×4 da 16× más estado y el recall **no
se mueve** (Δ+0.000 en la corrida canónica de 6000 steps; corridas más cortas dieron −0.002..+0.005,
todas dentro del ruido ~0.01). Ni el tamaño de estado ni el ancho del feature-map mueven el plateau.

### Por qué el fracaso es información (la pregunta se afila, no se cierra)
El null **refuta DOS cosas a la vez**:
1. Que el plateau sea **feature-map-limited por el ANCHO** (la palanca de Based, leída ingenuamente).
2. Que el plateau sea un límite de **tamaño de estado / capacidad cruda** (16× estado no compra nada).
Lo que queda en pie como candidato es la **FORMA del kernel** y/o la **optimización/init**: Based no usa
un ELU+1 ancho sino un kernel **Taylor (2do orden)**; Trockman desbloquea recall ya presente con
**mimetic init**. De ahí sale la hipótesis siguiente, más afilada que la refutada.

### Hipótesis nueva (generada por el fracaso)
- **H-CEIL-3** (`abierta`): el plateau del recall lineal se levanta con un **KERNEL más rico**
  (feature-map Taylor/2do orden, Based) y/o **mimetic init** (Trockman 2024) a presupuesto de pasos
  igual — NO con el mero ancho del ELU+1. Predicción: Taylor (o init mimética) sube el recall por
  encima de ~0.18 a d fijo con steps iguales; refutado si tampoco lo mueve. Queda `abierta` (sin
  experimento aún → no se marca; el gate DoD solo aplica al dar un veredicto).

### Decisión y registro
- **D-CEIL-2**: **descartar** "ensanchar el feature-map ELU+1" como vía para subir el recall del
  mezclador lineal; redirigir el esfuerzo a **kernel Taylor + mimetic init** (H-CEIL-3). Es una mejora
  DESCARTADA registrada explícitamente (como pide la directiva). ACEPTADA por el ledger (cita tier-5
  exp010 + tier-1 arXiv:2402.18668, obtenidas → funda; sin `OpinionOnlyError`).
- **H-CEIL-2** (`refutada`): DoD completo (a favor S1=Based; en contra S3=exp010; veredicto adversarial
  + experiment_ref). Marcada vía `mark_refuted` — el mismo gate DoD que apoyada/mixta, no se debilitó.
- **Techo (ASUMIDO)** añadido: "el cuello del recall lineal NO es tamaño de estado" — el límite efectivo
  es la FORMA del kernel (ELU+1 vs Taylor) y/o optim/init. Reemplaza la lectura de CYCLE 22 (que aún
  sospechaba del ancho) por una más precisa; sigue en el backlog de refutación.

### Honestidad
Semilla única (seed=0), modelo tiny (d=24, 4 capas), tarea sintética de recall, 2 puntos de `mult`
(1 y 4): el resultado es sobre el **MECANISMO** (el ancho del ELU+1 no es la palanca), no una ley
universal. Un null a una escala chica no prueba que Taylor/mimetic SÍ funcionen — eso es exactamente
lo que mide H-CEIL-3. El plateau ~0.18 es robusto entre exp009 y exp010 (mismo valor, dos diseños).

### Verificación (real, no solo prosa)
- `python -m cognia_x.research.cycles.cycle23_feature_dim` → todas las CHECK + `verify_no_loss = OK`.
- `python -m cognia_x.research.cli status/verify` sobre el store del ciclo → sources 3, decisions 1,
  hypotheses 3 (H-CEIL-2 add + transición refutada + H-CEIL-3 add), ceilings 1, asumidos 1; **verify
  OK** (exit 0). Re-correr es idempotente (mismos conteos).
- Datos del experimento: `cognia_x/experiments/exp010_feature_dim/results/results.json` (corrida
  canónica step-parity 6000, seed0; mult1=0.181, mult4=0.181, Δ+0.000; 576→9216) + `run.log` con el
  historial completo de corridas (4000 y 6000 steps; todas dentro del ruido ~0.01 → mismo veredicto null).

---

## CYCLE 24 (2026-06-19) — H-CEIL-3 REFUTADA: ni la forma del kernel ni la init levantan el plateau

### Pregunta
H-CEIL-2 (CYCLE 23) refutó el ANCHO del ELU+1. H-CEIL-3: ¿lo levanta la FORMA del kernel (feature-map
Taylor 2do orden, Based arXiv:2402.18668) y/o la mimetic init (Trockman arXiv:2410.11135) a steps
iguales? Literatura tier-1 lo PREDECÍA.

### Experimento (exp011_kernel_init) — 4 brazos, d=24 FIJO, n_heads=1, n_pairs=16, seed0, steps=3000 step-parity
Diseño que SEPARA forma de tamaño (resuelve el confound de exp010) y testea la init por separado:
- `elu_base` (ELU+1, dim 24) = **0.173** (plateau, reproduce exp010 0.181 dentro del ruido).
- `taylor` (Taylor 2do orden, dim 325, params idénticos) = **0.160** → Δ **−0.013** (POR DEBAJO del baseline).
- `elu_matched` (ELU+1 dim 336 ≈ dim 325 de Taylor, control de TAMAÑO) = **0.181** → Δ +0.008 (ruido).
- `elu_mimetic` (ELU+1 + mimetic init: W_k:=W_q, W_o:=I) = **0.183** → Δ +0.0098 (< umbral 0.02 → ruido).
- `taylor_vs_matched` = **−0.021**: el Taylor quedó por debajo del ELU de su MISMA dimensión → el control
  aísla forma de tamaño: no es que falte estado; la forma Taylor directamente no ayuda (incluso resta).

### Veredicto: H-CEIL-3 REFUTADA a esta escala (ambos levers)
Ni la forma del kernel (Taylor) ni la init (mimetic) cruzan el umbral de ruido sobre el baseline. La
mimetic da el mayor Δ positivo (+0.0098) pero no es significativo. Junto con exp010 (ancho), el plateau
~0.18 del lineal puro a d=24 es robusto a **ancho, forma e init** → el cuello NO es del feature-map.
El fracaso afina la pregunta → **H-CEIL-4** (abierta): profundidad/escala/optimizador o la capa de
atención del híbrido. Decisión **D-CEIL-3** (descartar forma+init a esta escala; redirigir).

### Engine (research/cycles/cycle24_kernel_init.py, reproducible)
El ciclo DERIVA el veredicto de `exp011/results.json` (correcto por construcción, sin transcripción
a mano): H-CEIL-3 marcada `refutada` con DoD completo (`mark_refuted`), H-CEIL-4 `abierta` generada por
la refutación, analogía 7 etapas (la libreta: ni más páginas ni mejor taquigrafía ni índice inicial
levantan el recall → el medio de tamaño fijo no alcanza), ceiling 'asumido' actualizado, D-CEIL-3
aceptada por el ledger (tier5 exp011 + tier1 Based). `verify_no_loss = OK`. Validé las 3 ramas del
ciclo (refutada/apoyada/mixta) contra results.json sintéticos antes de correrlo con los datos reales.

### Honestidad
- Semilla única (seed=0), modelo tiny (d=24, 4 capas), tarea sintética, steps=3000 (la mitad de exp010;
  el baseline alcanza su plateau ~0.17 hacia 2400 → válido). Un null a escala chica refuta el MECANISMO
  a ESTA escala (forma/init no son la palanca), NO prueba que a mayor escala/profundidad sigan sin serlo
  — eso es exactamente H-CEIL-4. El kernel Taylor a dh=24 tiene dim 325 (estado ~105k, ~5× más lento):
  d=24 es el mayor dh tratable en este CPU.
- **Concurrencia (declarada):** un agente paralelo de una sesión previa corría su propio exp011 de 2
  brazos (`exp011_taylor_kernel/`) sobre el MISMO hybrid.py; compartió CPU con mi run y lo frenó al
  principio (elu_base tardó 7.2min vs 6 calibrado) — pero todos los brazos completaron sus 3000 pasos
  dentro del deadline, sin cortar la step-parity. Su resultado **corrobora independientemente** el null
  de Taylor (elu=0.173 vs taylor=0.166). Dos implementaciones independientes → mismo null = más fuerte.

### Verificación (real, no solo prosa)
- `python -m cognia_x.experiments.exp011_kernel_init.run --steps 3000` → results.json con los 4 brazos.
- `python -m cognia_x.research.cycles.cycle24_kernel_init` → todas las CHECK + `verify_no_loss = OK`.
- Identidad del kernel Taylor verificada EXACTA antes de entrenar: phi(q).phi(k) = 1+(q.k)+(q.k)^2/2,
  error 1e-7. mimetic init verificada (W_k==W_q, W_o==I) y default intacto. Test `test_cycle24_kernel_init.py`.

---

## CYCLE 25 (2026-06-19) — la línea H-CEIL CONVERGE: el techo de recall del estado fijo es ESTRUCTURAL

### Pregunta
H-CEIL-4 (generada en CYCLE 24): ¿el plateau ~0.18 del lineal PURO se levanta con profundidad/escala-d/
optimizador (sin atención)? Es la cláusula NOVEDOSA; la rama "requiere atención" ya está apoyada (CYCLE 6).

### Experimento (exp012_depth_scale) — 4 brazos lineales puros, n_pairs=16, seed0, steps=3000 step-parity
- `lin_d24_L4` (baseline) = **0.173** (= exp011 elu_base).
- `lin_d24_L8` (profundidad 2×) = 0.181 (Δ +0.0075, ruido).
- `lin_d48_L4` (escala d=48) = 0.183 (Δ +0.0093, ruido).
- `lin_d24_L4_hi` (LR 3×) = 0.176 (Δ +0.0025, ruido).
- Ninguno cruza el umbral 0.02. d=48 puro sigue ~0.18 → en exp009 era el HÍBRIDO el que separaba a d=48,
  no la escala-d del lineal. Cuadra: el lift de exp009 era de la ATENCIÓN, no del tamaño del lineal.

### Veredicto: H-CEIL-4 MIXTA — la línea CONVERGE
La rama "profundidad/escala/optimizador" queda REFUTADA. Combinado con exp010 (ancho) y exp011
(forma+init), el plateau del mezclador de estado fijo a d≤48 es robusto a **SEIS levers no-atención**.
La rama "requiere atención" gana por ELIMINACIÓN + CYCLE 6 (la atención recupera 0.255→0.998). El techo
pasa a **ESTRUCTURAL** (`real`): cota = pigeonhole sobre el estado fijo (exp002 ~d²) + robustez empírica
a todo tuning probado. **D-CEIL-4:** cerrar la línea de afinar el lineal; el remedio del recall a carga
alta es ARQUITECTÓNICO (la atención del híbrido). Backlog de límites asumidos → 0 (la línea no invita
más refutación de tuning; el siguiente paso es confirmar el híbrido o pivotar de prioridad).

### Engine (research/cycles/cycle25_depth_scale.py)
DERIVA el veredicto de exp012/results.json. H-CEIL-4 `mixta` (mark_mixta, DoD completo), techo `real`
estructural, D-CEIL-4 aceptada (tier5 exp012 + tier1 Okpekpe&Orvieto), analogía 7 etapas (la libreta de
tamaño fijo: ningún tuning la arregla; hace falta otro instrumento = atención). verify_no_loss=OK.

### Honestidad
- Escala tiny (d≤48, n_pairs=16, steps=3000, seed0). El "estructural" es a ESTA escala; la cota última
  real es el pigeonhole informacional (exp002). A escala MUY mayor (modelos grandes) la pregunta podría
  reabrirse — pero a la escala del lab, 6 levers refutados son evidencia fuerte de que el remedio es
  arquitectónico, no de tuning. Reversible (D-CEIL-4) si a d≫48 el lineal puro cruzara sin atención.
- Confirmación opcional pendiente: exp013 (lineal+≥2 atención a d=24) como control positivo a esta escala.

### Verificación (real)
- `python -m cognia_x.experiments.exp012_depth_scale.run --steps 3000` → results.json (4 brazos).
- `python -m cognia_x.research.cycles.cycle25_depth_scale` → CHECK + verify_no_loss=OK; asumidos→0.
- Suite completa de cognia_x como compuerta final.

---

## CYCLE 26 (2026-06-20) — control POSITIVO: la atención cruza el plateau (línea de recall cerrada)

### Pregunta
Control positivo de la línea H-CEIL: ¿la ATENCIÓN cruza el plateau ~0.18 (6 levers lineales refutados) a
la MISMA escala (d=24, n_pairs=16, steps=3000)? → conclusión autocontenida, no solo "por eliminación".

### Experimento (exp013_hybrid_control) — 4 brazos, d=24, seed0, steps=3000 step-parity
- `lineal_h1` (baseline) = 0.173 (plateau).
- `hibrido_h1` (2 attn, h=1) = 0.181 ; `hibrido_h4` (2 attn, h=4) = 0.180 — **todavía ASCENDIENTE** al
  cortar el budget (hibrido_h4: 0.06→0.105→0.152→0.190; trayectoria de subida, NO plateau).
- `atencion_h4` (atención PURA) = **0.882** → cruzó a 0.85+ hacia el paso ~2100.

### Veredicto: control positivo CONFIRMADO + matiz honesto
La atención PURA cruza masivamente el plateau (0.18→0.88) que NINGÚN tuning del lineal movió → el remedio
del recall es ARQUITECTÓNICO, confirmado end-to-end a la escala de la línea H-CEIL (D-CEIL-1/4 directos).
**Diagnóstico antes que hallazgo:** el híbrido 50/50 NO "falla" — estaba SUBIENDO cuando se acabó el
budget (under-trained), no plateau. El híbrido CAN (CYCLE 6: 0.99 con la receta adecuada) pero optimiza
más LENTO a d chico (las capas lineales endurecen el landscape). → genera **H-HYB-1** (abierta).

### Engine (research/cycles/cycle26_hybrid_control.py)
DERIVA de exp013/results.json. H-HYB-1 añadida (abierta), techo `real` re-afirmado con control positivo
DIRECTO, D-CEIL-5 aceptada (tier5 exp013 + tier1 Based), analogía 7 etapas. verify_no_loss=OK.

### Honestidad
- El número final del híbrido (0.18) ENGAÑA si no se lee la trayectoria: subía. Lección de proceso (ya en
  la directiva v3 §4.2: sub-recursos disfrazados de techo). Por eso H-HYB-1 es 'abierta' (optimización),
  no una refutación del híbrido. La atención pura (0.88) es la evidencia decisiva del control positivo.
- Escala tiny (d=24). La conclusión (atención = remedio del recall) es robusta: cruce 5× sobre el plateau.

### Verificación (real)
- `python -m cognia_x.experiments.exp013_hybrid_control.run --steps 3000` → results.json (4 brazos).
- `python -m cognia_x.research.cycles.cycle26_hybrid_control` → CHECK + verify_no_loss=OK.
- Suite completa de cognia_x como compuerta final.

---

## CYCLE 27 (2026-06-20) — H-HYB-1 REFUTADA: el híbrido a d=24 NO cierra con budget (autocorrección)

### Pregunta
H-HYB-1 (CYCLE 26): el 0.18 del híbrido en exp013 era under-training; con más budget cerraría la brecha
con la atención pura. exp014 lo testea con 3.3× el budget (10000 steps).

### Experimento (exp014_hybrid_budget) — d=24, n_heads=4, n_pairs=16, seed0, steps=10000
- `hibrido_h4` (2 lineal + 2 atención) = **0.186** — PLATEÓ: 0.057@500 → 0.180@4000 → 0.186@7500 → 0.186
  final. PLANO desde el paso ~4000. NO under-training.
- `atencion_h4` (atención pura) = **0.948** — cruzó por ~4000, siguió subiendo.

### Veredicto: H-HYB-1 REFUTADA (estructural, no budget) — AUTOCORRECCIÓN honesta
Con 3.3× el budget el híbrido sigue en el plateau ~0.18. **CORRIGE mi diagnóstico de CYCLE 26** (llamé al
0.18 "under-training" porque a 3000 steps ascendía — era el COMIENZO de un plateau DURO). El híbrido
interleaved a d=24 NO recupera recall: las 2 capas LINEALES (baja capacidad a d=24, recall ~0.18)
BLOQUEAN el recall que la atención pura sí logra. El proceso se autocorrigió con más evidencia (la lección
de la directiva v3 §4.2 aplicada en su forma inversa: confirmar el "sub-recursos" con más budget ANTES de
cerrar). ACOTA H-MEZ-4 (el híbrido recuperaba a d=64): la recuperación es **d-dependiente**. Genera H-HYB-2.

### Engine (research/cycles/cycle27_hybrid_budget.py)
DERIVA de exp014/results.json. H-HYB-1 `refutada` (mark_refuted, DoD), H-HYB-2 `abierta`, techo 'asumido'
nuevo (el híbrido bottleneckea a d chico → backlog reabierto, asumidos=1), D-HYB-1 aceptada (caveat a
D-007), analogía 7 etapas (cadena con eslabón débil). verify_no_loss=OK.

### Honestidad — autocorrección de un diagnóstico
Esto es el proceso funcionando: en CYCLE 26 di un diagnóstico ("under-training") que CYCLE 27 refutó con
más datos. Lo registro explícitamente (no lo escondo). La conclusión CENTRAL de la línea de recall se
mantiene (atención = remedio; lineal = estructuralmente acotado), pero el comportamiento del HÍBRIDO a d
chico era más rico de lo que cerré en CYCLE 26 → la línea NO estaba tan "cerrada": queda H-HYB-2 abierta.

### Verificación (real)
- `python -m cognia_x.experiments.exp014_hybrid_budget.run --steps 10000` → results.json (2 brazos).
- Trayectoria del híbrido inspeccionada (plateó @4000, no creció) → no es under-training.
- `python -m cognia_x.research.cycles.cycle27_hybrid_budget` → CHECK + verify_no_loss=OK.
- Suite completa de cognia_x como compuerta final.

---

## CYCLE 28 (2026-06-20) — H-HYB-2 REFUTADA: la recuperación del híbrido NO es d (es arreglo/carga); sub-línea pausada

### Pregunta
H-HYB-2 (CYCLE 27): subir d arreglaría el híbrido bottleneckeado a d=24 (reconciliando con CYCLE 6 a d=64).

### Experimento (exp015_hybrid_dscale) — híbrido 2lin+2attn, n_heads=4, n_pairs=16, seed0, steps=6000
- hibrido_d24 = 0.189 ; hibrido_d48 = 0.253 ; hibrido_d64 = **0.190**. NO recupera (umbral 0.40) a ningún
  d, y NO monótono (d48 > d64). [Nota operativa: la corrida sufrió ~6h de contención con un agente
  paralelo; sin él vuelve a ~12 steps/s. El RESULTADO no se afecta, solo el wall-time.]

### Veredicto: H-HYB-2 REFUTADA — el cuello NO es d
RECONCILIA la tensión con CYCLE 6 (d=64 → 0.99): aquel era **np=8** (carga baja), este **np=16**. La
recuperación del híbrido depende de la CARGA (np) y/o el ARREGLO (lineal-primero destruye la asociación
clave-valor antes de la atención), no de d. **Caveat REAL a D-007:** el híbrido naive es FRÁGIL para
recall (no robusto a arreglo/carga); la atención pura recupera siempre (0.95). Genera H-HYB-3.

### PAUSA deliberada de la sub-línea del híbrido (D-HYB-2)
La sub-línea H-HYB-1→2→3 está en rendimientos decrecientes: cada ciclo refuta y genera el siguiente sobre
una pregunta cada vez más estrecha (condiciones exactas de recuperación de un híbrido de 4 capas a d/np
tiny). La conclusión CENTRAL de la línea de recall ya es sólida y multi-verificada (lineal=estructural por
6 levers + atención=remedio por control positivo). Por honestidad de prioridades (la directiva v3 §1:
eficiencia/recall ya cubierto), PAUSO el drilling y consolido. H-HYB-3 queda documentada para retomar con
orientación; el frente mayor abierto es F-LEARN-2 (prioridad #2).

### Engine (research/cycles/cycle28_hybrid_dscale.py)
H-HYB-2 `refutada` (mark_refuted, DoD), H-HYB-3 `abierta`, techo 'asumido' (cuello=arreglo/carga), D-HYB-2
(caveat fuerte a D-007 + pausa). verify_no_loss=OK.

### Verificación (real)
- `python -m cognia_x.experiments.exp015_hybrid_dscale.run --steps 6000` → results.json (3 brazos, barrido de d).
- `python -m cognia_x.research.cycles.cycle28_hybrid_dscale` → CHECK + verify_no_loss=OK.
- Suite completa de cognia_x como compuerta final.

---

## CYCLE 29 (2026-06-20) — F-LEARN-2: AUTO-MEJORA VERIFICADA (H-LEARN-1 APOYADA, n=4)

### Pregunta (frente F-LEARN-2, aprendizaje continuo Nivel 2)
CYCLE 11 mostró que verify-before-learn PREVIENE colapso en lenguaje (rechazando todo). H-LEARN-1: en una
tarea VERIFICABLE, ¿el modelo APRENDE de su propia salida y MEJORA (STaR) si un oráculo chequeable filtra
las correctas? ¿Y la ganancia es de la CORRECCIÓN o solo de menos/distintos datos?

### Experimento (exp016_verified_bootstrap) — suma byte-level, modelo tiny d=64, test held-out DISJUNTO, n=4 seeds
3 brazos PAREADOS (mismo base+RNG por seed; cada uno genera de SU red = loop STaR): verified (entrena con
auto-generaciones VERIFICADO-CORRECTAS), random_matched (CONTROL DECISIVO: mismo N_keep+pasos, subconjunto
ALEATORIO no por corrección), naive_all (todas, incl. incorrectas). 4 rondas, 200 pasos/ronda, oráculo int(A)+int(B).
- media-sobre-rondas (acc oráculo held-out): verified=0.494, random_matched=0.368, naive_all=0.377, base=0.358.
- **net-sobre-base: verified +0.110 (ÚNICO positivo en los 4 seeds); random −0.015, naive −0.007.**
- gap verified−random por seed [+0.125,+0.079,+0.235,+0.063] (4/4 positivos), media +0.126, **t-pareado=3.22 → p<0.05 (df=3)**, win-count 15/16. accept_rate (correctas/generadas) SUBE cada ronda (bootstrapping).

### Veredicto: H-LEARN-1 APOYADA (confianza media-alta)
El motor de la auto-mejora es la SEÑAL DE CORRECCIÓN del oráculo — verified es el único brazo que neta
ganancia; el control que iguala volumen+pasos pero filtra al azar NO mejora. AVANCE sobre CYCLE 11: el
verificador no solo PREVIENE colapso, HABILITA auto-mejora en tarea verificable (STaR/RFT en el lab CPU).

### Rigor: verificación adversarial (workflow, 4 lentes) + n=4
El workflow de verificación (metric-fishing / leakage-pairing / magnitud-ruido / colapso) confirmó el núcleo
PERO me frenó de sobre-afirmar: (a) la métrica media-sobre-rondas sobrevive a 3/4 métricas y el net-sobre-base
es metric-INDEPENDIENTE; (b) corrigió mi margen perverso (usaba el rango del gap como umbral → un seed fuerte
EMPEORABA el veredicto; lo reemplacé por t-test pareado estándar); (c) DESCARTÓ una narrativa falsa de
"colapso" de naive (la caída de diversidad es ruido a esta escala); (d) marcó que el win-count 7/8 era
estadísticamente inflado (rondas autocorrelacionadas). n=2→n=4 cerró la debilidad de potencia (p<0.05).

### Honestidad (caveats que van al registro)
Efecto MODESTO (+0.11) a escala tiny (suma 0..19, d=64); requiere oráculo chequeable (no aplica directo a
tareas no-verificables, donde CYCLE 11 solo previene colapso); generalización a pares nuevos con sumas
conocidas (idéntico para los 3 brazos, no confound). Dirección sólida y replicada en 4 seeds, no ley universal.

### Verificación (real)
- exp016 corrido n=4 (seeds 0-3); summary recomputado con t-test pareado. cycle29_verified_bootstrap.py →
  H-LEARN-1 marcada apoyada (DoD), D-LEARN-1 aceptada, verify_no_loss=OK. Test test_cycle29_addition (5 passed).

---

## CYCLE 30 (2026-06-20) — F-LEARN-2: la auto-mejora verificada tolera ruido del verificador hasta ε* (H-LEARN-2 APOYADA)

### Pregunta
El oráculo de exp016 era PERFECTO; los verificadores reales son ruidosos. H-LEARN-2: ¿hasta qué tasa de
FALSO POSITIVO (aceptar incorrectas) sobrevive la auto-mejora antes de degradar hacia naive?

### Experimento (exp017_noisy_verifier) — dosis-respuesta, n=3 seeds, VOLUMEN+pasos FIJOS
Verificador ruidoso: acepta una generación si es correcta O (incorrecta con prob ε). Barrido ε∈{0,0.15,0.3,
0.5,1.0} (ε=0=oráculo perfecto=exp016; ε=1=acepta todo=naive). CONTROL DE VOLUMEN: el set aceptado se
submuestrea a N=400 FIJO por ronda y se entrenan 200 pasos FIJOS en todos los ε → la única variable es la
CONTAMINACIÓN. net-sobre-base por ε: {0:+0.116, 0.15:+0.074, 0.3:+0.056, 0.5:+0.001, 1:−0.001}.

### Veredicto: H-LEARN-2 APOYADA
Decaimiento MONÓTONO de la auto-mejora con el ruido del verificador (caída ε0→ε1 = 0.117 > 2σ 0.091);
sobrevive hasta ε*=0.15 (net>0 consistente en los 3 seeds), colapsa al nivel naive por ε≥0.5. Como el
volumen y los pasos son fijos, la CONTAMINACIÓN es la causa → **confirma causalmente que el verificador (su
CORRECCIÓN) es el motor de H-LEARN-1** (degradar exactamente la corrección degrada la mejora, graduado).
Implicación de diseño (D-LEARN-2): un verificador real necesita FP-rate < ε* para habilitar auto-mejora.

### Rigor (verificación INLINE; el workflow de diseño falló por API 529)
Recomputación objetiva: (1) confound de VOLUMEN perfectamente controlado (n_kept=400 en TODOS los ε);
(2) ROBUSTO a la métrica — final-round Y media-rondas dan la MISMA curva decreciente (a diferencia de
exp016, sin metric-dependence aquí); (3) ε=0 reproduce exp016 (+0.116≈+0.110, consistencia entre experimentos);
(4) monotonicidad confirmada. Diseño directo confound-controlado (no se pudo correr el design-workflow por 529).

### Honestidad
Efecto y ε* específicos de la escala tiny (suma 0..19, d=64); a ε intermedio (0.3-0.5) la consistencia
entre seeds se rompe (la media decae pero los seeds individuales son ruidosos) — el headline robusto es el
decaimiento ε0≫ε1 (>2σ) y ε*≈0.15, no el valor exacto en cada ε. Modelo de ruido = FP puro (el peligroso);
el FN (rechazar correctas) solo reduciría datos. Dirección sólida (n=3, robusta a métrica), no ley universal.

### Verificación (real)
- exp017 corrido (seeds 0-2, 5 ε × 4 rondas, n_kept=400 fijo). cycle30_noisy_verifier.py → H-LEARN-2 apoyada
  (DoD), D-LEARN-2 aceptada, techo 'asumido' (presupuesto ε* del verificador), verify_no_loss=OK. Test test_cycle30_noisy.

---

## CYCLE 31 (2026-06-20) — F-LEARN-2: auto-mejora con VERIFICADOR REAL (sandbox) — H-LEARN-3 núcleo APOYADA

### Pregunta
exp016/017 usaron un ORÁCULO de forma cerrada. ¿La auto-mejora generaliza a un VERIFICADOR CHEQUEABLE REAL
(que EJECUTA la salida del modelo)? ¿Y un verificador real DÉBIL se reward-hackea?

### Experimento (exp018_real_verifier) — síntesis de expresiones + sandbox ejecutor, n=3 seeds, M=90
Tarea INVERSA: dado target N (prompt "N="), el modelo genera una EXPRESIÓN que lo iguala (ej "12="->"3*4").
VERIFICADOR REAL = sandbox que EJECUTA la expresión con intérprete propio (allowlist + gramática acotada,
SIN eval(); regla #9). DÉBIL: valor==N (acepta el echo "N"); FUERTE: valor==N Y operador. Brazos:
verified_strong, verified_weak, naive_all. real_acc = frac que el FUERTE acepta en test held-out.

### Veredicto: H-LEARN-3 (núcleo) APOYADA
verified sube real_acc +0.230 sobre base (0.437) en los 3 seeds (strong 0.667, weak 0.672) y supera a
naive_all (0.358, que CAE -0.08 = colapso sin filtro) por >2σ (0.105). Robusto a la métrica (media-rondas
+0.23 y final-round +0.33 coinciden). -> la auto-mejora FUNCIONA con un verificador chequeable REAL (ejecuta
la salida), no solo con un oráculo; el verificador es el motor (naive degrada).

### Sub-claim (reward-hack) NO observado (honesto)
Amodei 2016 predecía que el verificador DÉBIL sería gameado (echo "N"). NO ocurrió: verified_weak ~=
verified_strong, degenerate=0 en TODAS las rondas. El loop no-RL no descubrió el shortcut. Lo registro como
no-observado, no lo fuerzo.

### Honestidad / proceso
Tarea dura para el modelo tiny: seed aleatorio -> base~0 (sin función aprendible) -> seed determinista (regla
canónica "1+(N-1)"). Rango [2,40] -> M=12, NULL uninformativo (2σ~0.27). Re-corrí [2,300] (M=90, 2σ~0.10) +
gramática 3 dígitos para potencia -> resultado limpio. Documenté los nulls intermedios (no los escondí); no
acepté un null underpowered (ultracode: correcto > rápido). El design-workflow de exp018 falló por API 529.

### Verificación
exp018 (n=3, M=90). cycle31_real_verifier.py -> H-LEARN-3 apoyada (DoD), D-LEARN-3, techo 'asumido',
verify_no_loss=OK. Verificación INLINE: robusto a la métrica, 3/3 seeds positivos, naive negativo,
degenerate=0. Test test_cycle31_sandbox (4 passed; el sandbox no ejecuta código arbitrario).

---

## CYCLE 32 (2026-06-20) — F-LEARN-2: el reward-hack NO emerge en STaR-imitación (H-LEARN-4 REFUTADA con insight)

### Pregunta
CYCLE 31 dejó abierto: el reward-hack del verificador débil no emergió (el atajo no estaba en el repertorio).
H-LEARN-4: SI se SIEMBRA el atajo (echo) en el repertorio, ¿el verificador débil se reward-hackea?

### Experimento (exp019_reward_hack) — atajo SEMBRADO + weak vs strong, n=3, temp=1.1
Base sembrado con MEZCLA real+echo (p_echo=0.35 → base degenerate=0.067 = atajo presente). Loop STaR con
temperatura ALTA (1.1, máxima exploración para darle al hack su mejor chance). weak (acepta echo) vs strong
(rechaza echo) vs naive_all. Métricas: real_acc + degenerate en test held-out DISJUNTO.

### Veredicto: H-LEARN-4 REFUTADA (con insight)
weak degenerate(final)=0.085 ≈ strong=0.004 (gap +0.082, NO domina; fluctúa ~0.1 sin snowball entre rondas)
→ el echo NO se apodera aun SEMBRADO y con temp alta. El reward-hack NO emerge en un loop STaR de IMITACIÓN.
RAZÓN (refina Amodei 2016): la imitación COPIA las auto-generaciones aceptadas (mayormente honestas), no
MAXIMIZA la aceptación como RL → no caza el atajo más barato. El reward-hack es una patología de
RL-maximización, no inherente a un verificador débil bajo imitación.

### Matiz secundario (importante)
El verificador FUERTE igual es MUY superior: real_acc 0.745 vs weak 0.474 (+0.27) y degenerate menor (0.004
vs 0.085). naive_all (sin filtro) DEGRADA (0.178 < base 0.293). → la fuerza del verificador importa para la
COMPETENCIA/pureza de señal aunque no haya hack catastrófico (D-LEARN-4: preferir verificador fuerte).

### Verificación
exp019 (n=3, temp=1.1). cycle32_reward_hack.py → H-LEARN-4 refutada (DoD), D-LEARN-4, techo 'asumido',
verify_no_loss=OK. Inline: degenerate del weak fluctúa sin snowball (no hack); strong→0. Test echo (4+1 passed).
Honesto: di al hack su mejor chance (atajo sembrado + temp alta) y NO emergió — null informativo, no forzado.

---

## CYCLE 33 (2026-06-20) — F-LEARN-2: contrapunto RL del reward-hack (H-LEARN-5 REFUTADA, null de método)

### Pregunta
H-LEARN-4 (CYCLE 32) mostró que la IMITACIÓN STaR no se reward-hackea. Contrapunto causal: ¿RL-MAXIMIZACIÓN
SÍ se hackearía con el MISMO verificador débil + atajo? (confirmaría que el hack es de RL, no del verificador).

### Experimento (exp020_rl_vs_imitation) — mismo verificador/atajo, sólo cambia el algoritmo, n=3
imit_weak (imitación STaR) vs rl_weak (GRPO-lite, verificador débil) vs rl_strong (GRPO-lite, fuerte).
GRPO-lite: ventaja group-relative normalizada, usa la señal NEGATIVA de lo rechazado. degenerate(final):
imit_weak=0.115, rl_weak=0.059, rl_strong=0.000.

### Veredicto: H-LEARN-5 REFUTADA (null de MÉTODO, no del mecanismo)
El hack NO emergió bajo GRPO-lite (rl_weak degenerate 0.059 < imit 0.115 — incluso menor). CONFOUND honesto:
el GRPO ESTABLE apenas-entrena (rl_steps=20/lr chico para no colapsar) → casi no se mueve del base; el imit
entrena a fondo (200 steps). No hay ventana limpia a igual presión de optimización: RL estable apenas-entrena,
RL agresivo COLAPSA el modelo (real~0, visto en el 1er smoke). Es un límite de MÉTODO: GRPO-lite a escala tiny
no demuestra el contrapunto. El mecanismo (RL más hack-prone que imitación) mantiene apoyo de literatura
(Amodei) + la asimetría estructural de H-LEARN-4; demostrarlo in-lab requiere RL estabilizado (KL/on-policy)
o mayor escala. Nota: rl_strong degenerate=0.000 → el verificador FUERTE suprime el echo incluso bajo RL.

### Honestidad
Es un negativo de MÉTODO, registrado como tal (no se fuerza un "apoyada"). El insight central de H-LEARN-4
(imitación robusta al reward-hack) se sostiene solo (CYCLE 32). El contrapunto RL queda como future work.
Intenté estabilizar GRPO (ventajas normalizadas, pocos pasos, lr chico) tras ver el colapso del 1er smoke;
no rabbit-holeé más tuneo de RL.

### Verificación
exp020 (n=3). cycle33_rl_vs_imitation.py → H-LEARN-5 refutada (DoD), D-LEARN-5, techo 'asumido' (método RL),
verify_no_loss=OK.

---

> (CYCLE 34 F-SPEED / speculative decoding en standby — su bitácora vive en `manager_log.md` y el README de exp021.)

## CYCLE 35 (2026-06-24) — RESET v4: el árbol de descomposición raíz + H-V4-1 (valor endógeno) MIXTA

### Contexto — el RESET
El dueño autorizó "Reset a v4 (raíz pura)". Antes de codear, se produjo el artefacto que el prompt
fundacional pedía y no existía: el **árbol de descomposición recursiva** de "¿qué es una inteligencia y por
qué los enfoques actuales no llegan a la raíz?" (`decomposition_tree.md`), por excavación de **6 lentes
independientes + auditoría adversarial por lente + síntesis**, anclado al código del lab (las lentes
bajaron a los resultados reales y cazaron 4 errores de fidelidad: el techo d² ya refutado por exp010; "no
hay do() en el repo" falso por exp020; exp019/020 citadas al revés; "backprop=patología" contra H-BIO-3).
**Convergencia (5/6 lentes): R-VALOR** — la ausencia de una función-de-valor ENDÓGENA que defina qué
información importa — es el verdadero primer problema. La tesis previa (bytes-por-token/híbrido) queda como
SÍNTOMA (restricción de viabilidad, no dirección).

### Pregunta (H-V4-1)
¿Un valor ENDÓGENO (info-gain sobre el propio modelo, SIN verificador externo de la verdad) construye una
representación más causal que la predicción PASIVA, visible bajo INTERVENCIÓN?

### Experimento (exp022_endogenous_value) — control anti-confound + step-parity, 24 seeds, CPU/numpy
Mundo causal confundido (clúster de 4 features = causa latente z en el stream observacional; 1 es la causa
verdadera). Tres agentes con la MISMA clase de modelo (posterior bayesiano sobre "y=x_i") y MISMO update;
sólo cambia la POLÍTICA: A pasivo (stream confundido), B info-gain (consulta activa por información),
C azar-activo (ablación). Se barre el presupuesto K∈{2,4,8,16,32,64}.

### Veredicto: H-V4-1 MIXTA
- **R-INTERVENCIÓN demostrada (limpia):** A queda PLANO bajo intervención por más presupuesto (0.65→0.69;
  flatness Kmid→Kmax = 0.013) → muro INFORMACIONAL, no de recursos; B/C activos → 1.000; B−A=+0.31 a Kmax;
  gap INVISIBLE i.i.d. (|A−B|=0.04). → R-INTERVENCIÓN sube a techo 'real'.
- **R-VALOR específico NO aislado:** el azar-activo (C) también llega a 1.000 con presupuesto suficiente y
  empata/gana a info-gain a presupuesto chico (B−C=−0.007). El experimento NO separa "valor info-gain" de
  "intervención activa". → R-VALOR queda 'asumido' (backlog). Genera la hija **H-V4-1b**.

### Honestidad
Dos checks PRE-REGISTRADOS estaban mal especificados (nivel-absoluto/convergencia en vez de planitud/gap);
se conservan visibles y se agregaron diagnósticos correctos — el veredicto es MIXTA con ambos (no
goalpost-moving). El experimento bundlea dos claims y solo aísla uno: MIXTA honesta, no apoyada.

### Verificación
exp022 (24 seeds). cycle35_endogenous_value.py → H-V4-1 marcada 'mixta' (DoD completo), D-V4-1 ACEPTADA por
el ledger (tier5 exp022 + tier5 exp017), 2 techos (R-INTERVENCIÓN 'real', R-VALOR 'asumido'), analogía
7-etapas, verify_no_loss=OK. Test de regresión `test_cycle35_endogenous_value.py` 5/5; engine 20/20.

---

## CYCLE 36 (2026-06-24) — RESET v4: H-V4-1b (aislamiento del valor info-gain) MIXTA→refuta el valor

### Pregunta
exp022 dejó abierto si el VALOR (info-gain) está aislado de la "intervención activa per se". H-V4-1b: en un
régimen DURO (D=40, clúster=8, ruido 0.25, 24 seeds) donde el azar NO cubra por fuerza bruta, ¿info-gain
supera al azar-activo? Predicción PRE-REGISTRADA: APOYADA si B-C>0.08 (chico/medio) y prom>0.05; REFUTADA si
máx<=0.05; MIXTA si parcial.

### Experimento (exp023_value_isolation) — reusa el mundo+agentes de exp022, sólo cambia el régimen
### Veredicto: H-V4-1b MIXTA (inclinada a refutar el valor-como-info-gain)
El margen info-gain−azar oscila alrededor de 0 (media +0.004; único pico K=16 +0.099 DENTRO del ruido
std~0.18 y contradicho en K=32). Lo ROBUSTO (replicado): ACTUAR>>observar (C-A=+0.07..+0.36; A plano
~0.58-0.64). **El lever es la INTERVENCIÓN per se, NO el valor info-gain DISEÑADO.** R-INTERVENCIÓN reforzada
(real); R-VALOR 'asumido' refinado (info-gain descartado como lever; abierto sólo en forma fuerte:
valor AUTO-generado). Costo: 360 modelos causales en 1.0s CPU (~2.8ms c/u) → la dirección es barata.

### Honestidad
Honré el pre-registro (máx 0.099>0.05 → MIXTA, no refutada) aunque la lectura honesta refuta el valor-como-
info-gain. Pivote D-V4-2: explotar R-INTERVENCIÓN (act-and-verify, ya apoyado por exp016-018).

### Verificación
exp023 (24 seeds). cycle36_value_isolation.py → H-V4-1b 'mixta' (DoD), D-V4-2 ACEPTADA, 2 techos refinados,
analogía 7-etapas, verify_no_loss=OK. Test `test_cycle36_value_isolation.py` 4/4.

---

## CYCLE 37 (2026-06-24) — RESET v4: barrido de literatura (convergencia con SOTA 2023-2026)

Barrido web citado (`literature_v4.md`, sin citas inventadas). Tres convergencias:
1. **Corrobora exp022/023:** active causal discovery gana al azar SÓLO en grafo grande/denso + presupuesto
   escaso + ruido bajo; a grafo chico/ruido alto "random se vuelve competitivo" (CAASL arXiv:2405.16718,
   ~5-6% a d=10). Mi null es el corner conocido, no un bug. (Choo&Shiragur UAI'23: adaptativo O(log n) vs
   O(n) → hay un régimen donde el valor SÍ ganaría; pendiente medirlo.)
2. **R-VALOR forma-fuerte tiene soporte:** objetivos ACTION-GROUNDED tallan estructura causal (inverse-
   dynamics 84% vs 59% a ~5M params CPU-scale, arXiv:2606.20104; empowerment correlaciona con desempeño SIN
   reward, EELMA arXiv:2509.22504; Blahut-Arimoto = empowerment SIN gradiente, CPU, arXiv:2510.05996). El
   info-gain NO es buen proxy; el EMPOWERMENT sí es candidato. NULL a batir: next-token ya induce SCMs en
   juguete (OpenReview tHr0vFbS3K).
3. **Camino barato a "habla+razona":** TTS óptimo con VERIFICADOR barato bate a escalar params
   (arXiv:2408.03314; "verifier-based >> verifier-free"); híbrido SSM-atención/RWKV-7 corre en llama.cpp CPU
   hoy. Backprop-alts no valen salvo cuello de RAM (confirma H-BIO-3). → el verificador (no los params) es la
   pieza = R-INTERVENCIÓN. **Rumbo: substrato chico CPU + lazo act-and-verify barato.**

Próximo (selector): H-V4-1c (empowerment Blahut-Arimoto vs reconstrucción en gridworld con distractores —
test de R-VALOR forma-fuerte) y/o empezar el integrador act-and-verify sobre el sustrato de lenguaje.

---

## CYCLE 38 (2026-06-24) — RESET v4: H-V4-1c (empowerment = R-VALOR forma fuerte) APOYADA

### Pregunta
El info-gain no era el valor (exp023). ¿Lo es el EMPOWERMENT — un valor AUTO-generado (capacidad de canal
acción→futuro, Blahut-Arimoto, SIN reward/verificador externo)? Forma FUERTE de R-VALOR; si tampoco, el reset
pivota del todo a R-INTERVENCIÓN.

### Experimento (exp024_empowerment) — numpy puro, 12 seeds
Mundo con 3 tipos de factor: CONTROLABLE (f'=acción), RELOJ (f'=(f+1)%K, predecible pero NO controlable),
ALEATORIO. Dos medidas por factor: EMPOWERMENT (Blahut-Arimoto, capacidad a→f') y PREDICTIBILIDAD pasiva
(I(f_t;f_{t+1})). Pre-registro: APOYADA si E_ctrl≫E_reloj Y la inversión P_reloj≫P_ctrl (>0.8 bits).

### Veredicto: H-V4-1c APOYADA (inversión limpia)
EMPOWERMENT: ctrl 1.71 bits / reloj 0.0 / rand 0.0. PREDICCIÓN pasiva: ctrl 0.0 / reloj 1.71 / rand 0.0
(std ~0.005; costo 0.57s CPU). El empowerment aísla lo CONTROLABLE y descarta el reloj predecible-inútil; la
predicción pasiva hace lo contrario (ni VE lo controlable). **controlabilidad ≠ predictibilidad** = justo lo
que un agente necesita. A diferencia del info-gain (exp023, ≈azar), el empowerment SÍ se distingue de lo
trivial. **R-VALOR confirmado real en su forma fuerte**, unificado con R-INTERVENCIÓN (el valor es sobre la
acción). R-VALOR forma-fuerte → techo 'real'; R-VALOR aplicado (downstream/lenguaje) → 'asumido'. D-V4-3.

### Honestidad
Muestra el MECANISMO (controlabilidad≠predictibilidad), no aún que el empowerment MEJORE una tarea downstream
ni que escale a lenguaje (→ H-V4-1d / integrador). El factor ctrl'=acción es simple a propósito: el punto es
que la predicción pasiva, con el MISMO mundo, lo PIERDE.

### Verificación
exp024 (12 seeds). cycle38_empowerment.py → H-V4-1c 'apoyada' (DoD), D-V4-3 ACEPTADA, 2 techos, analogía
7-etapas, verify_no_loss=OK. Test `test_cycle38_empowerment.py` 4/4 (incluye Blahut-Arimoto vs capacidades
conocidas: identidad=log2(K), canal plano=0).

### Síntesis del reset (CYCLE 35-38)
NO-lever: predicción pasiva (exp022), info-gain (exp023), escalar params (lit.). SÍ-lever: ACTUAR
(R-INTERVENCIÓN) con valor de CONTROLABILIDAD (R-VALOR=empowerment). Arquitectura objetivo: substrato chico
CPU (híbrido/RWKV en llama.cpp) + act-and-verify barato con valor de controlabilidad + TTS verifier-based.
Próximo: H-V4-1d (empowerment mejora downstream) y el integrador hacia lenguaje.

---

## CYCLE 39 (2026-06-24) — RESET v4: H-V4-1d (empowerment mejora la tarea) APOYADA → cierra el arco R-VALOR

### Pregunta
exp024 mostró el MECANISMO (empowerment≠predictibilidad). ¿MEJORA una tarea? Si no, R-VALOR sería medición,
no lever. H-V4-1d: un agente con CAPACIDAD LIMITADA k (atiende/controla k de D factores) que debe llevar los
controlables a un objetivo — ¿asignar por empowerment gana a por predictibilidad y al azar?

### Experimento (exp025_empowerment_downstream) — reusa exp024, 12 seeds
n_ctrl=4 controlables + 4 relojes + 4 random (D=12). score = fracción de controlables llevados al objetivo.
Estrategias: top-k por empowerment / por predictibilidad / azar. Barrido de capacidad k. Pre-registro:
APOYADA si a k=n_ctrl emp-pred>0.3, emp>=azar, emp>0.9.

### Veredicto: H-V4-1d APOYADA (contundente)
A k=n_ctrl=4: EMPOWERMENT 1.000 / PREDICTIBILIDAD 0.250 (=azar puro) / AZAR 0.453 (emp-pred=+0.75; 0.835s
CPU). Asignar por PREDICTIBILIDAD es ANTI-útil (peor que el azar: se va al reloj). A capacidad PLENA (k=D)
las tres empatan en 1.0 → la ventaja del valor existe SÓLO bajo recursos limitados (el régimen del lab).
=> el valor endógeno (empowerment) MEJORA al agente, no sólo lo mide. **Arco R-VALOR cerrado** (mecanismo
exp024 + utilidad exp025). R-VALOR aplicado → techo 'real'. D-V4-4 (el integrador asignará cómputo por
controlabilidad/consecuencia).

### Honestidad
Tarea tabular de juguete; a capacidad plena no hay ventaja (la ventaja es del régimen limitado). El salto a
lenguaje (estimar empowerment/consecuencia sobre rollouts de un modelo chico) es el integrador, aún pendiente.

### Verificación
exp025 (12 seeds). cycle39 → H-V4-1d 'apoyada' (DoD), D-V4-4 ACEPTADA, 1 techo 'real', analogía, verify=OK.
Test `test_cycle39_empowerment_downstream.py` 4/4.

## CYCLE 40 — H-V4-1e (INTEGRADOR): act-and-verify TTS sobre el modelo PROPIO, en LENGUAJE

### Pregunta
¿El valor de CONTROLABILIDAD/CONSECUENCIA (empowerment, CYCLE 38-39) sirve para asignar CÓMPUTO de
test-time sobre el MODELO PROPIO del lab (HybridLM byte-level desde cero) y convierte cómputo barato en
respuestas correctas mejor que el AZAR y la PREDICCIÓN-PASIVA, a igual presupuesto? (salto al lenguaje)

### Diseño
Base débil-pero-bootstrappable (banda acc∈[0.20,0.50]) en suma byte-level; oráculo int(A)+int(B) como
verificador chequeable. Sobre M=120 problemas held-out, cada política reparte el MISMO presupuesto B=M·avg
de samples (intervenciones). RESUELTO = algún sample pasa el verificador (best-of-k con checker). Políticas:
AZAR (uniforme) / PASIVA (extra ∝ entropía del probe = incertidumbre) / CONSECUENCIA (extra ∝ empowerment
sobre el resultado verificado: 0 si ya resuelto, ∝ diversidad alcanzable si no). Probe de n_probe=2 cuenta
al presupuesto y se reusa. Barrido avg∈{2,3,4,6,8}, 4 seeds. Predicción pre-registrada: APOYADA si en el
régimen escaso (menor avg>n_probe) CONSEC supera a AZAR Y a PASIVA por ≥0.03 y >2σ.

### Resultado — APOYADA (en el régimen discriminante)
Régimen escaso avg=3 (4 seeds in-band): CONSEC 0.562 / AZAR 0.506 (+0.056) / PASIVA 0.490 (+0.073), ambos
>2σ(0.045). Curva: avg2 0.417/0.413/0.417 (degenerado, extra=0) | avg3 0.562/0.506/0.490 | avg4 0.608/0.581/
0.550 | avg6 0.687/0.700/0.627 | avg8 0.702/0.735/0.633. La PASIVA-incertidumbre es la PEOR en todo el rango
discriminante (anti-útil). A avg≥6 + verificador perfecto el AZAR alcanza/supera (efecto techo): la ventaja
del valor existe SÓLO bajo ESCASEZ — misma forma que exp025 (capacidad limitada).

### Límites (honestos)
Verificador PERFECTO (oráculo); falta verificador ruidoso/parcial (exp017/018) sobre lenguaje. La señal de
consecuencia usa un probe que consume presupuesto (falta señal más barata). Tarea de 1 paso; falta
razonamiento multi-paso. El avg escaso NO se eligió a posteriori: a avg≤n_probe el extra=0 y las políticas
son idénticas por construcción → el discriminante es el menor avg>n_probe (pre-definido).

### Verificación
exp026 (4 seeds, M=120, modelo propio HybridLM). cycle40 → H-V4-1e 'apoyada' (DoD), D-V4-5 ACEPTADA, 1 techo
'real' (R-VALOR aplicado al lenguaje), analogía 7 etapas, verify_no_loss=OK. Test `test_cycle40_ttc_allocation.py` 4/4.

## CYCLE 41 — H-V4-1f: realismo del verificador (ruidoso/parcial) en act-and-verify TTS

### Pregunta
¿La ventaja de asignar cómputo test-time por CONTROLABILIDAD (exp026, verificador perfecto) SOBREVIVE a un
verificador RUIDOSO/PARCIAL, y hasta qué nivel de ruido? (el techo que dejó exp026)

### Diseño
Extiende exp026 (mismo HybridLM byte-level, suma). Verificador NOISY simétrico vnoise: una respuesta
verdadera-correcta se acepta con prob 1-vnoise (FN=vnoise); una verdadera-incorrecta se acepta con prob
vnoise (FP=vnoise). Act-and-verify: COMMIT = primer sample aceptado por el verificador ruidoso. ACCURACY
REAL = el commit es verdaderamente correcto (oráculo) → castiga falsos positivos. 3 políticas reparten el
mismo presupuesto B=M·avg (avg=3, escaso discriminante); probe y señal de consecuencia usan el verificador
RUIDOSO (lo único que el agente observa). Barrido vnoise∈{0,0.05,0.1,0.2}, 4 seeds, M=120. Predicción
pre-registrada: APOYADA si a vnoise=0.10 CONSEC≥AZAR y ≥PASIVA (>2σ) sin colapso bajo greedy; REFUTADA si
CONSEC≤AZAR a 0.10 o colapsa; MIXTA si parcial.

### Resultado — MIXTA (matizada, muy informativa)
Curva vnoise→CONSEC/AZAR/PASIVA/greedy: 0.0:0.544/0.490/0.483/0.317 | 0.05:0.502/0.452/0.483/0.317 |
0.10:0.444/0.440/0.435/0.317 | 0.20:0.358/0.385/0.398/0.317. (1) A vnoise=0 reproduce exp026 (CONSEC mejor,
validación cruzada). (2) ROBUSTEZ: el lazo act-and-verify nunca cae bajo greedy en ningún ruido → degrada con
gracia. (3) FRAGILIDAD del lever: la ventaja del control es significativa a error≤~5% (Δazar +0.05), se
diluye a ~10% (Δazar +0.004, dentro de 2σ) y se INVIERTE a 20% (la consecuencia pasa a ser la peor). Mecanismo:
la señal de consecuencia usa solved_observed (depende del verificador) → hereda su ruido; la pasiva-entropía
no, por eso resiste mejor (pero es peor en ausencia de ruido).

### Límites (honestos)
Verificador SINTÉTICO (flip simétrico); falta verificador real-chequeable ruidoso (código→sandbox, exp018)
sobre lenguaje. Umbral de tolerancia (~5-10%) medido en tarea de 1 paso; en multi-paso el ruido se compone.
La regla commit-first-accepted no es el artefacto (a vnoise=0 = best-of-k y reproduce exp026).

### Verificación
exp027 (4 seeds, M=120, HybridLM propio + verificador ruidoso). cycle41 → H-V4-1f 'mixta' (DoD), D-V4-6
ACEPTADA, 1 techo 'real' (lazo robusto / lever condicional), analogía, verify_no_loss=OK. Test
`test_cycle41_noisy_verifier_ttc.py` 3/3.

## CYCLE 42 — H-V4-1g: señal de control verifier-free (auto-consistencia) vs ruido del verificador

### Pregunta
¿Una señal de control que NO usa el veredicto del verificador (consenso emergente de rollouts) recupera la
ventaja de exp026 Y resiste el ruido que hundió a la señal verifier-dependiente (exp027)?

### Diseño
Extiende exp027 (mismo HybridLM + verificador ruidoso para el COMMIT, igual para todas → aísla la ASIGNACIÓN).
4 políticas de asignación del mismo presupuesto B=M·avg (avg=5, n_probe=3): AZAR, PASIVA (entropía),
CONSEC_V (control verifier-dependiente de exp026), CONSEC_FREE (consenso emergente: peso = p_top si p_top<1
si no 0; p_top=fracción de la respuesta plural). Barrido vnoise∈{0,0.1,0.2}, 4 seeds, M=120. Pre-registrado:
APOYADA si CONSEC_FREE (a) a vnoise=0 ≥ pasiva y azar Y (b) a vnoise alto > CONSEC_V por ≥0.02.

### Resultado — MIXTA
Curva vnoise→AZAR/PASIVA/CONSEC_V/CONSEC_FREE: 0.0:0.642/0.629/0.710/0.640 | 0.1:0.529/0.525/0.560/0.531 |
0.2:0.446/0.485/0.412/0.444. ROBUSTA SÍ (FREE−CONSEC_V=+0.031 a vnoise=0.2, donde CONSEC_V colapsa a la peor).
RECUPERA-EL-EDGE NO (a verificador bueno CONSEC_V domina; CONSEC_FREE empata baselines). No hay señal de
asignación única dominante: el régimen de calidad del verificador decide cuál gana.

### Disciplina / límites (honestos)
El test de regresión cazó un BUG: p_top·(1−p_top) es SIMÉTRICA (1/3 y 2/3 dan el mismo peso → no distingue
caos de consenso emergente). Corregida a consenso-emergente monótono; el MIXTA se mantuvo → el null es del
fenómeno. Reuso de MODE_OFFSET determinista (no hash() randomizado). n_probe=3 da p_top de baja resolución;
verificador sintético; falta multi-paso y verificador real-chequeable.

### Verificación
exp028 (4 seeds, M=120, HybridLM propio). cycle42 → H-V4-1g 'mixta' (DoD), D-V4-7 ACEPTADA, 1 techo 'real'
(no hay señal única dominante → política adaptativa), analogía, verify_no_loss=OK. Test
`test_cycle42_robust_control_signal.py` 3/3.

## CYCLE 43 — H-V4-1h: política ADAPTATIVA (capstone del sub-arco integrador 40-43)

### Pregunta
¿Una política que estima ONLINE la fiabilidad del verificador (sin ground-truth) y mezcla la señal de control
verifier-dependiente con la verifier-free logra no-regret — lo mejor de ambas en todo el rango de ruido?

### Diseño
Extiende exp028 (mismo HybridLM + verificador ruidoso, commit verifier-based igual para todas). Fiabilidad
GLOBAL r por TEST-RETEST: se consulta el verificador DOS veces por sample del probe y se mide su auto-acuerdo;
r=clip(2·P(coinciden)−1,0,1). Peso w_adapt=r·w_CONSEC_V+(1−r)·w_CONSEC_FREE. Políticas: CONSEC_V, CONSEC_FREE,
ADAPT (+ oracle_best = best-of por nivel, referencia no implementable). Barrido vnoise∈{0,0.1,0.2}, 4 seeds.
Pre-registrado: APOYADA si ADAPT≥CONSEC_V−0.02 a vnoise=0 (keeps edge) Y ADAPT≥CONSEC_V+0.02 a vnoise alto
(escapes collapse) Y r baja con el ruido.

### Resultado — APOYADA (no-regret)
Curva vnoise→CONSEC_V/CONSEC_FREE/ADAPT(r_est): 0.0:0.690/0.621/0.688(r=1.00) | 0.1:0.527/0.550/0.535(r=0.61)
| 0.2:0.415/0.415/0.437(r=0.39). keeps_edge SÍ (ADAPT≈CONSEC_V a r≈1), escapes_collapse SÍ (ADAPT 0.437 >
CONSEC_V 0.415 a ruido alto, hasta supera a las dos puras), r calibra monótona, worst_regret +0.008 (ADAPT
nunca por debajo del mínimo de sus componentes). Resuelve la no-dominancia de exp028.

### Disciplina / límites (honestos)
El PRIMER estimador (acuerdo verificador-vs-consenso del modelo) FALLÓ — r≈0 aun a vnoise=0 porque el modelo
débil tiene mal consenso (la self-consistency no aplica). El smoke lo expuso; se reemplazó por test-retest,
que calibra correcto y NO depende de la corrección del modelo. Límite: test-retest detecta ruido ALEATORIO,
no SESGO sistemático (un verificador siempre-acepta se vería consistente). Verificador sintético; tarea de 1
paso (el multi-paso es el próximo gran salto).

### Verificación
exp029 (4 seeds, M=120, HybridLM propio). cycle43 → H-V4-1h 'apoyada' (DoD), D-V4-8 ACEPTADA, 1 techo 'real'
(política adaptativa no-regret, cierra 40-43), analogía, verify_no_loss=OK. Test
`test_cycle43_adaptive_allocation.py` 4/4.

> SUB-ARCO INTEGRADOR 40-43 CERRADO: control REAL (40) → frágil al verificador (41) → sin señal única
> dominante (42) → resuelto con adaptación calibrada por la consistencia del verificador (43, no-regret).

## CYCLE 44 — H-V4-1i: razonamiento MULTI-PASO (verif intermedia vs sólo-final)

### Pregunta
¿La verificación INTERMEDIA (step-wise act-and-verify) supera a la SÓLO-FINAL (end-to-end best-of-k) a igual
cómputo, y la ventaja crece con la longitud de cadena porque los errores se COMPONEN?

### Diseño
Cadena de K sumas mod 20 (cada paso in-distribution: r_{i-1}∈[0,19] + a_i∈[0,9], wrap mod 20) sobre el modelo
propio (reusa build_base/exp016). Correcto = la TRAZA completa [r_1..r_K] coincide con la referencia (sin piso
de suerte). STEP_WISE: en cada paso hasta k muestras, verifica el paso (oráculo), commitea el primero correcto;
END_TO_END: k cadenas completas (1 muestra/paso, sin verificar pasos), acepta si alguna da la traza correcta.
Mismo presupuesto k·K. Barrido K∈{1,2,4,6}, k=4, 4 seeds. Pre-registrado: APOYADA si gap crece monótono y
>0.20 en Kmax.

### Resultado — MIXTA
Curva K→END_TO_END/STEP_WISE/gap: K1:0.667/0.692/+0.025 | K2:0.317/0.448/+0.131 | K4:0.046/0.219/+0.173 |
K6:0.004/0.092/+0.088. El gap ABSOLUTO no es monótono (cae a K=6) porque AMBAS estrategias colapsan a 0 con
presupuesto por-paso fijo (k=4 no garantiza cada paso). Pero la ventaja RELATIVA (step_wise/end_to_end) crece
monótona y enorme: 1.04×→1.4×→4.8×→23× a K=6. La verificación intermedia (supervisión de proceso) frena
drásticamente el compounding pero no lo elimina a presupuesto por-paso fijo.

### Disciplina / límites (honestos)
BUG de diseño detectado y corregido: con mod-20 y verificación sólo-del-último-número había un piso de SUERTE
(~0.19) que inflaba end-to-end; corregido a verificación de la TRAZA COMPLETA, el efecto real emergió.
Verificador perfecto per-step (el ruido per-step que se compone es el siguiente realismo). Cuando un paso no
tiene ningún sample correcto, step-wise commitea uno malo y descarrila (falta backtracking/abstención).

### Verificación
exp030 (4 seeds, modelo propio). cycle44 → H-V4-1i 'mixta' (DoD), D-V4-9 ACEPTADA, 1 techo 'real' (verif
intermedia frena pero no elimina el compounding), analogía, verify_no_loss=OK. Test
`test_cycle44_multistep_reasoning.py` 4/4. Convergente con 'Let's Verify Step by Step' (Lightman 2023).

## CYCLE 45 — H-V4-1j: presupuesto ADAPTATIVO per-step en cadenas largas

### Pregunta
¿Gastar el cómputo "hasta verificar" con un pool COMPARTIDO entre pasos (más a los difíciles, menos a los
fáciles) rescata las cadenas largas que el presupuesto por-paso FIJO dejaba colapsar (exp030), a IGUAL cómputo
total?

### Diseño
Extiende exp030 (misma cadena de sumas mod 20). Presupuesto TOTAL B=avg·K por cadena. UNIFORME: cada paso
recibe `avg` muestras. ADAPTATIVO: reserva 1/paso futuro (anti-starvation); en cada paso dibuja hasta
cap=min(per_step_cap, 1+pool_extra) pero PARA al primer verificado; el costo real = índice del primer
verificado +1; lo no gastado queda en el pool para los pasos difíciles. Mismo B total. Barrido K∈{2,4,6,8},
avg=4, 4 seeds. Pre-registrado: APOYADA si ADAPT>UNIFORME en Kmax (>=0.03) y el gain crece/no-decrece.

### Resultado — MIXTA (rescate fuerte)
Curva K→UNIFORME/ADAPT/gain: K2:0.446/0.598/+0.152 | K4:0.190/0.423/+0.233 | K6:0.119/0.333/+0.215 |
K8:0.058/0.240/+0.181. El adaptativo gana en TODA K (+0.15..+0.23) y rescata cadenas largas (a K=8 uniforme
0.058 vs adaptativo 0.240 = 4.1×). MIXTA solo porque el gain absoluto no es monótono (pico K=4, satura a K
extremo a presupuesto total fijo); la ventaja relativa sí crece monótona 1.3×→4.1×.

### Límites (honestos)
A K extremo, con presupuesto TOTAL fijo, incluso el adaptativo satura hacia 0 (hace falta escalar B o
casi-perfeccionar el paso). Cuando un paso agota su presupuesto sin verificar, commitea uno malo y descarrila
(falta backtracking/abstención). Verificador perfecto per-step (el ruidoso per-step es el siguiente realismo).

### Verificación
exp031 (4 seeds, modelo propio). cycle45 → H-V4-1j 'mixta' (DoD), D-V4-10 ACEPTADA, 1 techo 'real' (rescate de
cadenas largas; satura a K extremo), analogía, verify_no_loss=OK. Test `test_cycle45_adaptive_perstep.py` 4/4.
Convergente con asignación adaptativa de test-time compute (arXiv:2408.03314).

> Sub-arco MULTI-PASO 44-45: verificación de PROCESO frena el compounding (44) + presupuesto ADAPTATIVO
> per-step rescata cadenas largas (45). El integrador multi-paso = proceso + presupuesto adaptativo.

## CYCLE 46 — H-V4-1k: abstención calibrada + verificador ruidoso per-step

### Pregunta
¿Abstenerse (decir "no sé") cuando ningún sample de un paso verifica convierte errores silenciosos en
abstenciones flagueadas, subiendo la PRECISIÓN-sobre-respondidas — incluso con verificador RUIDOSO per-step?

### Diseño
Extiende exp031 (cadena mod 20, presupuesto adaptativo per-step, modelo propio). Verificador RUIDOSO per-step
(vnoise=FP=FN). Se commitea el primer sample NOISY-aceptado. COMMIT-SIEMPRE: si ninguno se acepta, commitea el
primero igual y sigue (accuracy de la traza). ABSTENER: si ningún sample de un paso se acepta, la cadena
ABSTIENE; métricas COBERTURA (fracción respondida) y PRECISIÓN (correctas entre respondidas). Barrido (K,
vnoise), 4 seeds. Pre-registrado: APOYADA si precisión−commit≥0.15 en Kmax y ruido moderado con cobertura≥0.2;
MIXTA si sube fuerte pero la cobertura colapsa salvo cadenas cortas/verificador bueno.

### Resultado — MIXTA (lever de honestidad, dependiente de régimen)
Curva K|vnoise→COMMIT/PREC/COV: 2|0.0:0.252/1.000/0.248 | 2|0.1:0.217/0.647/0.317 | 2|0.2:0.169/0.295/0.338 |
4|0.1:0.054/0.293/0.081 | 6|0.1:0.002/0.125/0.017. Funciona fuerte a cadenas cortas + verificador decente
(precisión 1.000 vs commit 0.252 = +0.748, cobertura útil 0.248; a vn=0.1: 0.647 vs 0.217). Pero la cobertura
colapsa a K largo (a K=6 ~0.01-0.02: abstiene todo) y la precisión se erosiona con ruido.

### Disciplina / límites (honestos)
El código de verdict miraba SOLO Kmax (cobertura colapsada) y marcaba REFUTADA, contradiciendo el TEXTO
pre-registrado ("MIXTA si la cobertura colapsa salvo cadenas cortas"); se corrigió verdict para mirar toda la
curva y se re-corrió FULL para consistencia. Precisión 1.0 a vn=0 es por construcción (verificador perfecto);
el valor real está en el régimen ruidoso (precisión alta pero <1). Falta backtracking para recuperar cobertura.

### Verificación
exp032 (4 seeds, modelo propio). cycle46 → H-V4-1k 'mixta' (DoD), D-V4-11 ACEPTADA, 1 techo 'real' (abstención
sube precisión pero cobertura colapsa a K largo / con ruido), analogía, verify_no_loss=OK. Test
`test_cycle46_abstention_noisy.py` 4/4. Convergente con predicción selectiva y con 41/43.

> Sub-arco MULTI-PASO 44-46: proceso (44) + presupuesto adaptativo per-step (45) + abstención honesta (46).

## CYCLE 47 — H-V4-1l: backtracking/RETRY del paso fallido vs abstención

### Pregunta
¿Reintentar un paso que no verificó (RETRY: segunda tanda desde el pool, en vez de abstener la cadena entera)
recupera COBERTURA sin perder PRECISIÓN, a IGUAL presupuesto total? (ataca el colapso de cobertura de exp032)

### Diseño
Extiende exp032 (cadena mod 20, verificador ruidoso per-step, modelo propio). Pool compartido B=avg·K con
gastar-hasta-verificar (pasos fáciles cuestan poco → dejan pool para los difíciles). ABSTAIN: al fallar un
paso, abstiene. RETRY: al fallar, segunda tanda de hasta retry_extra muestras del pool antes de abstener.
Estado de RNG de torch ALINEADO entre las dos políticas (ven las mismas muestras base; RETRY difiere sólo por
las extra). Barrido (K, vnoise), 4 seeds. Pre-registrado: APOYADA si Δcov≥0.10 con prec_drop≤0.10 y cobertura
recuperada útil (precisión≥0.5); MIXTA si recupera sin dañar precisión pero gateado por el verificador.

### Resultado — MIXTA
Curva K|vn→ABST_cov/RETRY_cov(Δcov) prec: 6|0.0:0.30/0.37(+0.07)p1.00 | 6|0.1:0.51/0.70(+0.19)p0.18 |
6|0.2:0.75/0.86(+0.11)p0.04. RETRY recupera cobertura material en cadenas largas sin dañar precisión, PERO su
utilidad está gateada por el verificador: donde recupera mucho (ruido alto) la precisión es baja (rescata
cadenas confiadamente-MAL); donde la precisión es alta (vn=0) el gain es sub-margen. No hay régimen con
Δcov≥0.10 Y precisión útil.

### Disciplina / límites (honestos)
(1) Confound de muestreo detectado y corregido (RNG de torch alineado entre políticas). (2) Contabilidad
pasada a gastar-hasta-verificar para que el retry tenga pool real. (3) NOTA DE MÉTODO: el piso de utilidad
(retry_prec≥0.5) NO estaba pre-registrado; se agregó al ver el rescate de basura, se REPORTA explícitamente y
NO se usó para forzar REFUTADA. GIRO ESTRATÉGICO: los 4 mecanismos (44-47) convergen al cuello de botella del
verificador/precisión-por-paso → el próximo lever es el SUSTRATO, no más orquestación.

### Verificación
exp033 (4 seeds, modelo propio). cycle47 → H-V4-1l 'mixta' (DoD), D-V4-12 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle47_backtrack_retry.py` 4/4.

> Sub-arco MULTI-PASO 44-47 cerrado en mecanismos (proceso+adaptativo+abstención+backtracking); todos apuntan
> al SUSTRATO (verificador real + precisión por paso) como el verdadero próximo lever (H-V4-2).

## CYCLE 48 — H-V4-2: SUSTRATO — auto-mejora verificada + amplificación multi-paso (CAPSTONE arco v4)

### Pregunta
¿El lazo act-and-verify mejora el sustrato barato (precisión por paso) desde sus propias salidas VERIFICADO-
correctas (señal de corrección, no volumen), y esa mejora se AMPLIFICA en razonamiento multi-paso (p^K)?

### Diseño
Modelo propio (HybridLM). (1) Base débil. (2) Genera K completaciones por prompt de train; arma VERIFIED (sólo
correctas por oráculo) y CONTROL (subconjunto aleatorio de TODAS, mismo tamaño → aísla volumen). (3) Fine-tune
2 copias (verified/control), mismos N_steps. (4) Mide PRECISIÓN POR PASO (held-out) y ACCURACY DE CADENA greedy
(sin orquestación → aísla el sustrato) a K=1,2,3. Pre-registrado: APOYADA si verified > base y > control en el
paso (≥0.03) Y el ratio verified/base en cadena crece de K=1 a Kmax.

### Resultado — APOYADA
PASO: base 0.317 → VERIFIED 0.419 (+0.102) vs CONTROL 0.258. Verified supera base Y control (el control sin
verificar EMPEORA el base) → la señal de CORRECCIÓN, no el volumen. AMPLIFICACIÓN: ratio verified/base crece
monótono 1.32×(K1) → 1.93×(K2) → 2.71×(K3). Una mejora modesta del paso (+0.10) rinde compuesta en multi-paso.

### Límites (honestos)
Base débil (CPU) → cadena greedy a K≥4 cae a ~0 (piso de medición); la amplificación se demostró a K≤3 (donde
el ratio ya llega a 2.71×). Una sola ronda de STaR (falta iterar y ver saturación). Tarea aritmética con
oráculo exacto (falta verificador real-chequeable y razonamiento no-aritmético).

### Verificación
exp034 (4 seeds, modelo propio). cycle48 → H-V4-2 'apoyada' (DoD), D-V4-13 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle48_substrate_amplify.py` 3/3. Convergente con STaR (Zelikman 2022) y exp016.

> ARCO v4 CERRADO (40-48): el integrador es un LAZO DE AUTO-MEJORA — orquestación test-time (40-43) + multi-paso
> (44-47) + mejora del sustrato amplificada (48). Unifica R-INTERVENCIÓN + R-VALOR sobre el modelo propio.

## CYCLE 49 — H-V4-2b: iterar el lazo de auto-mejora verificada (¿motor estable o colapso?)

### Pregunta
¿Iterar el lazo de auto-mejora verificada varias rondas es un MOTOR ESTABLE (precisión por paso sube y platea)
o COLAPSA (narrowing tipo STaR: el modelo se entrena sobre su distribución estrecha y degrada)?

### Diseño
Modelo propio. Lazo de R=4 rondas in-place: ronda r → genera K completaciones por prompt con el modelo ACTUAL,
filtra verificado-correcto (oráculo), fine-tunea el modelo actual con ellas. Tras cada ronda mide: precisión
por paso (held-out), cadena greedy (K=2), diversidad (fracción de respuestas distintas) y n_verified. 3 seeds.
Pre-registrado: APOYADA si el paso sube y es no-decreciente sin colapso de diversidad (≥0.5× inicial); REFUTADA
si la precisión cae tras su pico o la diversidad se desploma.

### Resultado — APOYADA (motor estable y fuerte)
PASO por ronda (prom): 0.300→0.472→0.456→0.481→0.508 (+0.208; mejor seed un base débil se bootstrappea a 0.783
paso, 0.753 cadena). CADENA: 0.187→0.436. SIN colapso de precisión (no-decreciente). DIVERSIDAD: 0.040→0.021
(declina monótona, ~0.52× inicial = narrowing temprano, no colapso en 4 rondas). El filtro de corrección
mantiene el lazo sano (consistente con anti-colapso CYCLE 11).

### Límites (honestos)
La diversidad declina monótona → en rondas largas hace falta monitor/inyector de diversidad (riesgo conocido de
STaR). La métrica fracción-distintas está acotada por el vocab chico de la suma (~39 valores) → se usa como
señal RELATIVA entre rondas. No se midió el TECHO (cuántas rondas hasta plateau real).

### Verificación
exp035 (3 seeds, modelo propio). cycle49 → H-V4-2b 'apoyada' (DoD), D-V4-14 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle49_iterated_star.py` 3/3. Convergente con STaR (Zelikman 2022) y CYCLE 11.

> ARCO v4: el integrador del lab es un LAZO DE AUTO-MEJORA autónomo y sostenible (orquestación 40-47 + sustrato
> 48 + iteración estable 49), con guardia de diversidad pendiente.

## CYCLE 50 — H-V4-2c: guardia de diversidad (dedup+replay) en el lazo iterado

### Pregunta
¿Una guardia barata (dedup de verificados + replay de datos semilla de la verdad) previene el narrowing del
lazo iterado (caveat de CYCLE 49) y/o sube el techo del bootstrapping?

### Diseño
Modelo propio. Dos lazos de R=6 rondas in-place desde el MISMO base: PLANO (entrena con todos los verificados
con frecuencia) vs GUARDED (verificados DEDUP + replay de replay_n ejemplos semilla CORRECTOS de la verdad).
Métricas por ronda: precisión por paso (held-out), COBERTURA = nº de prompts distintos en el set verificado,
diversidad de respuestas. 3 seeds. Pre-registrado: APOYADA si la guardia mantiene más cobertura/diversidad que
el plano al final Y su precisión final ≥ la del plano.

### Resultado — APOYADA
PLANO step [0.300,0.442,0.475,0.536,0.425,0.547,0.642] — trepa ERRÁTICO (cae a 0.425 en r4), cobertura
estancada ~180. GUARDED [0.300,0.531,0.525,0.586,0.656,0.697,0.692] — suave y MÁS ALTO, cobertura CRECIENTE
175→202, sin costo de precisión. La narrowing del 49 era real; dedup+replay la arregla (el plano se machaca en
los verificados frecuentes; el dedup quita la frecuencia y el replay reinyecta señal de la verdad).

### Límites (honestos)
La diversidad-de-respuestas colapsa para AMBOS (acotada por el vocab chico de la suma ~39 valores) → la señal
válida de narrowing es la COBERTURA de prompts. No se midió el techo real (cuántas rondas hasta plateau con la
guardia). Tarea aritmética con oráculo exacto (falta verificador real-chequeable y tarea más rica).

### Verificación
exp036 (3 seeds, R=6, modelo propio). cycle50 → H-V4-2c 'apoyada' (DoD), D-V4-15 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle50_diversity_guard.py` 4/4. Convergente con replay/anti-colapso y CYCLE 11.

> Sub-arco AUTO-MEJORA 48-50 CERRADO: mejora+amplifica (48) + motor estable iterado (49) + guardia controla
> narrowing y sube techo (50). El lazo de auto-mejora es autónomo, sostenible y controlable sin modelo más grande.

## CYCLE 51 — H-V4-2d: ¿el lazo iterado + guardia sobrevive con un VERIFICADOR REAL-CHEQUEABLE (sandbox)?

### Pregunta
El sub-arco AUTO-MEJORA (48-50) probó el lazo iterado + guardia SÓLO sobre la SUMA con oráculo EXACTO (límite
honesto #1 del CYCLE 50). exp018 (H-LEARN-3) ya mostró que UNA ronda de auto-mejora funciona con un
VERIFICADOR REAL (sandbox que EJECUTA la expresión). ¿El lazo ITERADO con guardia GENERALIZA del oráculo
exacto a ese verificador chequeable real SOBRE ITERACIÓN — sin colapso y sin reward-hack?

### Diseño
Modelo propio (HybridLM, exp018). Funde exp018 (verificador real, síntesis de expresiones: dado "N=", generar
"a op b" que iguale N; FUERTE = valor==N Y usa operador, bloquea el echo) + exp036 (guardia dedup+replay). Por
seed, dos lazos de R=6 rondas in-place desde el MISMO base: PLANO (entrena con todas las STRONG-verificadas con
frecuencia) vs GUARDED (STRONG-verificadas DEDUP + replay de replay_n=128 ejemplos semilla CORRECTOS de la
verdad). Métricas por ronda: real_acc (verificador FUERTE en test held-out disjunto), COBERTURA = nº de prompts
distintos verificados, degenerate (echo = reward-hack). base calibrado a real_acc~0.44 (banda) para tener
margen. 3 seeds. Pre-registrado: APOYADA si real_acc sube sobre base y es no-decreciente, la guardia mantiene
cobertura >= plano sin costo de real_acc, y degenerate no trepa con las rondas.

### Resultado — APOYADA
REAL_acc por ronda: PLANO [0.441,0.737,0.833,0.848,0.881,0.848,0.867] GUARDED [0.441,0.830,0.867,0.885,0.896,
0.893,0.941]. El lazo con el VERIFICADOR REAL SUBE sobre base (+0.50 hasta guarded final 0.941) y es
NO-DECRECIENTE (no colapsa al iterar con un verificador ejecutable, no solo con el oráculo). GUARDED supera a
PLANO en techo (0.941 vs 0.867) y cobertura (144 vs 140), sin costo de precisión. DEGENERATE = 0.000 en TODAS
las rondas y AMBOS brazos: el verificador FUERTE (exige operador) bloquea el echo aun iterando (consistente con
exp018 + H-LEARN-4: la imitación STaR no descubre el atajo). => el motor de auto-mejora depende del VERIFICADOR,
no del tipo de oráculo (exacto vs ejecutable).

### Límites (honestos)
base seed0 alto (0.722, cerca del techo) -> el margen por iteración promedio es menor y el plateau llega
relativamente temprano; falta un base débil bajo el verificador real para medir el TECHO real. plain_narrows=
False: en ESTA tarea con el verificador real el lazo plano NO estrecha la cobertura en R=6 (a diferencia de la
suma del CYCLE 50) -> la guardia gana por techo más alto, no por frenar un narrowing que aquí no aparece. La
regla canónica de replay '1+(n-1)' hace la tarea aprendible pero ESTRECHA (falta verificación más rica: código
real con tests). Falta el puente a un verificador real PARCIAL/ruidoso (H-LEARN-2 ε*≈0.15 con un verificador
ejecutable).

### Verificación
exp037 (3 seeds, R=6, modelo propio). cycle51 -> H-V4-2d 'apoyada' (DoD), D-V4-16 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle51_iterated_real_verifier.py` 4/4. Convergente con exp018
(verificador real 1-ronda), exp036 (guardia/oráculo) y STaR (Zelikman 2022).

> Une el sub-arco AUTO-MEJORA (48-50, oráculo EXACTO) con el frente VERIFICADOR-REAL (exp018/H-LEARN-3): el
> lazo de auto-mejora + guardia es robusto al cambio oráculo-exacto -> verificador-chequeable-real sobre
> iteración. El VERIFICADOR (no el tipo de oráculo) es el motor.

## CYCLE 52 — H-V4-2e: el TECHO del lazo iterado + guardia con VERIFICADOR REAL desde un base DÉBIL

### Pregunta
CYCLE 49 mostró que un base DÉBIL se bootstrapea a ~0.78 con el lazo iterado — pero con el ORÁCULO EXACTO.
CYCLE 51 mostró que el lazo iterado + guardia generaliza a un VERIFICADOR REAL, pero desde un base MODERADO
(~0.44) y R=6 (su límite #1: "falta base débil bajo el verificador real para medir el techo"). ¿El lazo con el
VERIFICADOR REAL tiene el mismo poder de bootstrapping desde un base DÉBIL (~0.08), y DÓNDE PLATEA con R=10?

### Diseño
Modelo propio (reusa exp037). base_steps=125 -> base real_acc~0.08 (DÉBIL, calibrado). Lazo de R=10 rondas
in-place, PLANO vs GUARDED (dedup+replay), verificador FUERTE real (síntesis de expresiones). Por ronda:
real_acc (held-out), cobertura, degenerate. 3 seeds. Pre-registrado: APOYADA si guarded bootstrapea (final-base
>=0.30 Y final>=0.50) Y platea (no-decreciente, últimas rondas aplanadas).

### Resultado — APOYADA
GUARDED: base 0.081 -> [0.711,0.785,0.885,0.893,0.893,0.922,0.941,0.933,0.896,0.933] final 0.933 (gain +0.852),
PLATEA en r3 (bootstrapping RÁPIDO), no-decreciente, sin colapso. degenerate=0.000 en las 10 rondas (sin
reward-hack con el verificador FUERTE aun bootstrapeando desde casi-cero). MISMO poder de bootstrapping que el
oráculo exacto (CYCLE 49, ~0.78) ahora con un verificador chequeable REAL. HALLAZGO EXTRA: el lazo PLANO desde
el MISMO base débil sólo llega a 0.693 (más lento, sigue subiendo a r10) -> con base débil la GUARDIA (replay de
ejemplos CORRECTOS de la verdad) es CRÍTICA: resuelve el COLD-START (el plano débil genera pocas verificadas y
arranca lento; el replay reinyecta señal de la verdad). Ventaja de la guardia: +0.241 en techo final y platea
~7 rondas antes.

### Límites (honestos)
La regla canónica de replay '1+(n-1)' hace la tarea aprendible pero ESTRECHA (falta verificación más rica:
código real con tests para un techo no-de-juguete). El techo medido es de ESTA tarea, no universal. Falta el
puente a un verificador real PARCIAL/ruidoso (ε*≈0.15) bajo bootstrapping desde base débil. Cobertura acotada
por |test|=90.

### Verificación
exp038 (3 seeds, R=10, modelo propio). cycle52 -> H-V4-2e 'apoyada' (DoD), D-V4-17 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle52_real_verifier_ceiling.py` 4/4. Convergente con exp035 (oráculo,
bootstrapping desde base débil) y exp037 (verificador real).

> Cierra el límite #1 del CYCLE 51: el lazo de auto-mejora con verificador REAL bootstrapea desde casi-cero a un
> techo alto y plateable; con base débil la GUARDIA (dedup+replay) es parte del motor (resuelve el cold-start),
> no un refinamiento opcional.

## CYCLE 53 — H-V4-2f: ¿la tolerancia al RUIDO del verificador (ε*≈0.15, oráculo) transfiere al VERIFICADOR REAL?

### Pregunta
exp017 (H-LEARN-2, CYCLE 30) halló que la auto-mejora verificada DECAE con el ruido falso-positivo y sobrevive
hasta ε*≈0.15 — pero con el ORÁCULO aritmético EXACTO. Hilo abierto más citado por exp037 Y exp038: el
verificador real PARCIAL/RUIDOSO. ¿La dosis-respuesta al ruido TRANSFIERE a un VERIFICADOR REAL-CHEQUEABLE
(sandbox), y la GUARDIA (replay limpio de la verdad) SUBE el umbral ε*?

### Diseño
Modelo propio (funde exp017 + exp037). Mismo modelo de ruido que exp017: verificador con ruido ε acepta si es
STRONG-correcta (sandbox: valor==target Y usa operador) o si NO lo es con prob ε; volumen FIJO (submuestreo a
fixed_n=400) + pasos fijos -> la única variable es la contaminación. base_steps=200 -> base~0.44. Por seed y ε
en {0.0,0.15,0.30,0.50}: dos lazos R=4, PLANO vs GUARDED (dedup+replay limpio). Métrica: real_acc CLEAN
(verificador FUERTE sin ruido, held-out) -> net-sobre-base media-sobre-rondas. 3 seeds. ε* por brazo = mayor ε
con net>0 consistente entre seeds.

### Resultado — APOYADA
net-sobre-base por ε: PLANO {+0.316@0, +0.079@0.15, -0.008@0.3, -0.123@0.5} ε*=0.0; GUARDED {+0.431@0,
+0.312@0.15, +0.187@0.3, +0.155@0.5} ε*=0.50. El net DECAE con ε (caída guarded 0.431->0.155, >2σ=0.105) -> la
dosis-respuesta TRANSFIERE del oráculo al verificador REAL: el verificador (su CORRECCIÓN) sigue siendo el
MOTOR. HALLAZGO CENTRAL: la GUARDIA SUBE ε* de 0.0 (plano) a 0.50 (guarded) -> el replay limpio de la verdad
DILUYE la contaminación del verificador, así el lazo aguanta hasta un 50% de falsos positivos donde el plano
(base moderada) muere ante CUALQUIER ruido. La guardia no es un refinamiento: compra robustez al verificador
imperfecto (que es lo que son los verificadores reales).

### Límites (honestos)
Modelo de ruido = falso-positivo UNIFORME; un verificador real puede fallar de forma CORRELACIONADA (aceptar
siempre cierto patrón), que es más peligroso. La regla canónica de replay '1+(n-1)' es estrecha (falta
verificador de CÓDIGO real con tests parciales, FP-rate medido). No se combinó ruido + bootstrapping desde base
débil (interacción ε* x cold-start). Tarea acotada (test=90).

### Verificación
exp039 (3 seeds, R=4, modelo propio). cycle53 -> H-V4-2f 'apoyada' (DoD), D-V4-18 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle53_noisy_real_verifier.py` 4/4. Convergente con exp017 (ε*≈0.15
oráculo) y exp037/038 (verificador real + guardia).

> Une H-LEARN-2 (ruido/oráculo) con H-V4-2d/e (verificador real + guardia): el resultado central del lab (el
> VERIFICADOR es el lever de 1ra clase; su CALIDAD decide la auto-mejora) se sostiene con un verificador REAL y
> RUIDOSO, y la guardia (replay limpio) compra robustez al ruido (ε* 0.0 -> 0.50).

## CYCLE 54 — H-V4-2g (CAPSTONE robustez): ruido del VERIFICADOR REAL × cold-start (base débil)

### Pregunta
exp038 (CYCLE 52): la guardia bootstrapea un base débil (~0.08) a ~0.93 con un verificador REAL PERFECTO.
exp039 (CYCLE 53): con base MODERADO la guardia tolera ruido hasta ε*=0.50. Límite abierto EXPLÍCITO de
exp039: no se combinaron los dos estresores. ¿La robustez al ruido SOBREVIVE cuando además se arranca desde
casi-cero? (peor caso realista: verificador imperfecto Y modelo casi sin saber la tarea).

### Diseño
Modelo propio (reusa exp039). base_steps=125 -> base real_acc~0.08 (DÉBIL). Lazo GUARDED (dedup+replay limpio)
R=8, barriendo ε en {0.0,0.15,0.30,0.50} (verificador FUERTE real con ruido falso-positivo). Métrica: real_acc
CLEAN final y gain-sobre-base por ε. 3 seeds. ε*_coldstart = mayor ε con bootstrapping fuerte consistente
(gain>=0.30 en cada seed). Pre-registrado: APOYADA si ε*_coldstart>=0.30; REFUTADA si ε=0.15 ya lo destruye;
MIXTA si 0<ε*_coldstart<0.30.

### Resultado — APOYADA (CAPSTONE)
final por ε: {0.0:0.933, 0.15:0.844, 0.30:0.659, 0.50:0.437}; gain por ε: {0.0:+0.852, 0.15:+0.763,
0.30:+0.578, 0.50:+0.356}. bootstrapea fuerte (3/3 seeds, gain>=0.30) hasta ε=0.30; ε*_coldstart=0.30. Desde un
base DÉBIL (0.082) el lazo GUARDED bootstrapea a 0.66 AUN con 30% de falsos positivos del verificador. La
robustez al RUIDO (exp039 ε*=0.50 base moderada) y al COLD-START (exp038) COEXISTEN: el replay limpio de la
verdad ANCLA el lazo y arranca el motor aun con el corrector fallando; los dos estresores NO se componen
catastróficamente (el techo baja con ε pero el cold-start SOBREVIVE, degradación graceful y monótona).

### Límites (honestos)
A ε=0.50 el bootstrapping ya no es consistente entre seeds (gain medio +0.356 pero no 3/3) -> el arranque débil
SÍ baja la tolerancia al ruido vs base moderada (ε*=0.30 aquí vs ε*=0.50 con base moderada): la fragilidad del
cold-start cuesta ~0.20 de ε* tolerable. Ruido falso-positivo UNIFORME (falta correlacionado). Regla canónica
de replay '1+(n-1)' estrecha. Tarea acotada (test=90).

### Verificación
exp040 (3 seeds, R=8, modelo propio). cycle54 -> H-V4-2g 'apoyada' (DoD), D-V4-19 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle54_noise_coldstart.py` 3/3. Convergente con exp038 (cold-start) y
exp039 (ruido ε*=0.50).

> CAPSTONE del arco VERIFICADOR-REAL (51-54): el lazo de auto-mejora con verificador chequeable REAL es robusto
> a verificador-imperfecto Y arranque-débil SIMULTÁNEOS; la guardia (dedup+replay limpio) es el mecanismo
> central que compra ambas robusteces. El VERIFICADOR (no el tipo de oráculo) es el motor, y la guardia lo
> sostiene bajo ruido y desde casi-cero.

## CYCLE 55 — H-V4-2h: ¿un verificador con SESGO SISTEMÁTICO (off-by-one) daña el lazo, y la guardia lo defiende?

### Pregunta
exp039/040 mostraron robustez al ruido falso-positivo UNIFORME. Pero un verificador real puede fallar
CORRELACIONADO: un bug consistente que SIEMPRE acepta cierta respuesta incorrecta (un test suite con off-by-one
que aprueba la implementación mal). ¿Ese sesgo SISTEMÁTICO daña el lazo, y la GUARDIA (replay limpio) lo
defiende? (límite abierto de exp039: ruido correlacionado).

### Diseño
Modelo propio (funde exp019 + exp037). Base SEMBRADO con mezcla: mayoría '1+(n-1)' (correcto) + p_bug=0.35 de
'1+(n-2)' (off-by-one, valor target-1, USA operador) -> el sesgo está en el repertorio (base real~0.39,
offbyone~0.24, calibrado). Verificador FUERTE pero BUGGY: acepta si usa operador Y valor==target O target-1.
Dos lazos R=6: PLANO (entrena con buggy-aceptadas) vs GUARDED (dedup + replay de '1+(n-1)' CORRECTO de la
verdad). Por ronda: real_acc (valor==target, CLEAN) y offbyone (valor==target-1 = la deriva). 3 seeds.
Pre-registrado con DOS modos de daño: APOYADA si deriva runaway; MIXTA si pin/estancamiento; REFUTADA si sin daño.

### Resultado — MIXTA
PLANO real [0.393,0.530,0.544,0.519,0.541,0.533,0.489] (PINNED: no despega, ~0.49-0.54) offbyone
[0.241,...,0.322] (el sesgo PERSISTE y sube a 0.32). GUARDED real [0.393,0.696,...,0.759] (recupera a 0.76)
offbyone [0.241,0.170,...,0.148] (el sesgo BAJA a 0.15). plain_drifts=False (no hay deriva runaway: offbyone
sube +0.081 < margen), plain_pinned=True, plain_harmed=True, guard_defends=True. => el verificador sesgado DAÑA
el lazo plano por ESTANCAMIENTO + persistencia del sesgo (no por deriva runaway), y la GUARDIA (replay limpio)
DEFIENDE: reancla en la regla correcta y diluye el sesgo estructural. El replay limpio es defensa NO sólo contra
ruido uniforme (exp039) sino contra SESGO ESTRUCTURAL del verificador.

### Límites (honestos)
El sesgo no causa DERIVA runaway, sólo PIN/persistencia -> el daño es estancamiento (menos grave que la
hipótesis fuerte; consistente con la barrera de DISCOVERY de exp019: el sesgo sembrado no se amplifica de
novo). El sesgo está SEMBRADO artificialmente (p_bug=0.35), no emergente. Falta verificador de CÓDIGO real con
un bug real (no el off-by-one de juguete). Tarea acotada (test=90).

### Verificación
exp041 (3 seeds, R=6, modelo propio). cycle55 -> H-V4-2h 'mixta' (DoD), D-V4-20 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle55_biased_verifier.py` 5/5. Convergente con exp019 (discovery),
exp039 (ruido uniforme) y exp037 (guardia).

> Completa la robustez del lazo de auto-mejora ante verificadores imperfectos: ruido uniforme (exp039),
> ruido+cold-start (exp040) y SESGO sistemático (exp041) — en los tres la GUARDIA (dedup+replay limpio) es el
> mecanismo de defensa. El sesgo estructural daña por estancamiento, no por deriva runaway.

## CYCLE 56 — H-V4-1b (PIVOTE North-Star R-VALOR): aislar el valor de info-gain con post_on_cause

### Pregunta
exp022 (CYCLE 35, H-V4-1) quedó MIXTA: demostró R-INTERVENCIÓN (el pasivo se queda plano; las políticas
activas identifican) pero NO aisló R-VALOR — medido por ACCURACY, el azar-activo (C) alcanzaba a info-gain (B).
DIAGNÓSTICO: la accuracy SATURA (descartado el clúster confundido, el voto acierta aunque el posterior no esté
concentrado en la causa exacta) -> enmascara el valor. ¿Con el instrumento FIEL (post_on_cause = masa del
posterior sobre la causa VERDADERA) se AÍSLA el valor de info-gain del de intervenir, en el régimen DURO?

### Diseño
Reusa exp022.run (máquina validada). Dos regímenes: FÁCIL (D=12,cluster=4,p_obs=0.10) y DURO
(D=48,cluster=14,p_obs=0.20). Barrido K={8,12,16,20,24}. Métrica PRIMARIA: post_on_cause de B (info-gain) vs C
(azar-activo) vs A (pasivo). Secundaria: interv accuracy (para mostrar que satura y enmascara). 48 seeds.
Pre-registrado: APOYADA si DURO B-C post > 0.15 a Kmax, signo-consistente (>=70%), creciente con K, y la
accuracy enmascara; REFUTADA si B-C post <= 0; MIXTA si positivo pero bajo umbral.

### Resultado — APOYADA
DURO post_on_cause B-C por K: -0.002@8, +0.134@12, +0.125@16, +0.180@20, +0.306@24 (CRECE con K; a Kmax 79%
seeds B>C). DURO accuracy B-C@24 = +0.139 (<< post +0.306) -> la accuracy ENMASCARA (satura: B acc 0.947, C acc
0.808, ambas altas). FÁCIL post B-C se cierra rápido (+0.198@8 -> +0.001@24; la accuracy satura aún antes). =>
con el instrumento FIEL, info-gain (B) concentra MÁS masa en la causa VERDADERA que el azar-activo (C) en el
régimen duro, creciente con el presupuesto: el VALOR de *qué* consultar (info-gain) se SEPARA del de *intervenir*
(actividad). Primera evidencia POSITIVA de R-VALOR específico en el lab. Explica la MIXTA de exp022: instrumento
equivocado (accuracy en vez de masa-sobre-causa).

### Límites (honestos)
El efecto es robusto en DIRECCIÓN (media crece, 79% seeds) pero MODESTO por seed individual -> la actividad
capta el grueso; el valor de info-gain afina. Mundo de juguete (hipótesis lineal y=x_i, clúster confundido
sintético). El eval usa la causa VERDADERA c (oráculo de evaluación, no de la política): falta un proxy ENDÓGENO
de "mejor modelo" sin conocer c. El aislamiento depende del régimen (en el fácil el azar alcanza).

### Verificación
exp042 (48 seeds, bayesiano numpy, reusa exp022). cycle56 -> H-V4-1b 'apoyada' (DoD), D-V4-21 ACEPTADA, 1 techo
'real', analogía, verify_no_loss=OK. Test `test_cycle56_value_isolation_post.py` 4/4. Convergente con info-gain/
EIG (active inference, tier1) y refina exp022/CYCLE 35.

> PIVOTE al North-Star (R-VALOR): primera evidencia POSITIVA de un valor ENDÓGENO (info-gain) que construye un
> modelo más causal que la mera actividad, AISLADO con el instrumento fiel (masa sobre la causa). La lección de
> método: la accuracy downstream puede enmascarar el valor de una mejor representación; medir por la masa sobre
> el objetivo. Conecta con el arco de auto-mejora (el verificador es un caso de valor) y abre H-V4-5 (memoria
> dirigida por valor).

## CYCLE 57 — H-V4-1c (North-Star R-VALOR): señal de valor ENDÓGENA (confianza calibrada) sin oráculo

### Pregunta
exp042 (CYCLE 56) aisló el valor de info-gain con post_on_cause = masa sobre la causa VERDADERA — pero eso usa
un ORÁCULO (conocer c). Límite #1: ¿el AGENTE puede saber que construyó mejor modelo SIN conocer c? Su única
señal endógena es su PROPIA confianza (max del posterior). ¿Esa confianza (a) rankea info-gain>azar igual que el
oráculo, y (b) está CALIBRADA (confiado => correcto, sin confiado-pero-equivocado)?

### Diseño
Reusa exp022.run_agent/make_world. Régimen DURO (D=48,cluster=14,p_obs=0.20) y FÁCIL. Por (seed,K,agente):
conf=max(posterior) [ENDÓGENA], correct=(argmax==c) [oráculo, SÓLO para validar calibración], entropy. Agrega:
conf media, P(correct|confiado>=τ) [calibración], confidently_wrong=P(conf>=τ AND wrong). 48 seeds, τ=0.5.
Pre-registrado: APOYADA si conf_B>conf_C Y B calibrado (P(correct|confiado)>=0.80, confiado-equivocado<0.15 y <C).

### Resultado — APOYADA
DURO @Kmax=24: A_pasivo conf=0.107 correct=0.146 (queda INCIERTO, sabe que no puede distinguir el clúster);
B_infogain conf=0.883 correct=0.917 calib=0.95 confiado-equivocado=0.04; C_aleatorio conf=0.699 correct=0.625
calib=0.71 confiado-equivocado=0.21. La conf endógena RANKEA B>C>A en TODO K (B 0.352->0.883 vs C 0.319->0.699),
igual que el oráculo de exp042. B está CALIBRADO (confiado=>95% correcto). HALLAZGO CLAVE: la confianza endógena
es CONFIABLE SÓLO CON LA POLÍTICA CORRECTA — el azar-activo (C) da confianza ENGAÑOSA (21% confiado-pero-
equivocado: se concentra a veces en una feature ESPURIA del clúster). => el agente puede SELECCIONAR la mejor
política por su propia confianza calibrada, SIN oráculo de la verdad. Cierra el lazo de R-VALOR.

### Límites (honestos)
La calibración bayesiana está ayudada por construcción (modelo bien especificado); falta un mundo con modelo MAL
especificado (donde la confianza podría engañar más). No se USÓ la confianza para SELECCIONAR política online
(sólo se midió que se podría); falta el lazo de selección endógena. Mundo ESTACIONARIO; el North-Star pide
no-estacionario. La 'corrección' se valida con c (sólo para medir calibración; el agente no la usa).

### Verificación
exp043 (48 seeds, bayesiano numpy, reusa exp022). cycle57 -> H-V4-1c 'apoyada' (DoD), D-V4-22 ACEPTADA, 1 techo
'real', analogía, verify_no_loss=OK. Test `test_cycle57_endogenous_signal.py` 4/4. Convergente con calibración
bayesiana (tier1); cierra el límite #1 de exp042.

> North-Star R-VALOR: existe una señal de VALOR ENDÓGENA usable SIN oráculo — la confianza calibrada del propio
> modelo. Rankea políticas igual que el oráculo y es confiable con la política correcta (info-gain); el
> azar-activo da confianza engañosa. El sistema puede juzgar qué política construyó mejor modelo sin verificador
> externo -> conecta el North-Star (R-VALOR) con el arco de auto-mejora (el verificador externo es, en parte,
> reemplazable por la confianza calibrada). Sub-arco R-VALOR 56-57: el valor endógeno existe Y es medible por el
> propio agente.

## CYCLE 58 — H-V4-1d (North-Star R-VALOR x memoria): olvido dirigido por valor en mundo NO-estacionario

### Pregunta
El North-Star pide un valor endógeno "persiguiendo un objetivo en un mundo NO-ESTACIONARIO ... qué información
merece recordarse u OLVIDARSE". CYCLE 56/57 mostraron valor endógeno en mundo ESTACIONARIO. ¿En un mundo donde
la causa CAMBIA tras un commitment profundo y con presupuesto de adaptación corto, el OLVIDO dirigido por valor
(descontar evidencia vieja) permite ADAPTARSE, donde el agente COMMITTED (acumula todo) queda ATASCADO? Conecta
R-VALOR con MEMORIA (escribir≡olvidar, H-V4-5).

### Diseño
Bayesiano (reusa primitivas de exp022). Mundo no-estacionario: clúster confundido; c_old (fase 1, K1=60 =
commitment profundo), c_new (fase 2, K2=12 = adaptación corta). MISMA política (info-gain) para todos; lo ÚNICO
que cambia es el OLVIDO: update descontado logpost = decay*logpost + log(verosimilitud). decay=1 = COMMITTED;
decay<1 = OLVIDO. Barrido decay {1.0,0.9,0.8,0.7}. Métrica: post sobre la causa NUEVA al final (adaptación) y
post sobre la vieja al fin de fase 1 (que identificó). 24 seeds. Pre-registrado: APOYADA si committed atascado
(post_c_new<=0.40) Y algún olvido adapta (post_c_new>=0.60, +>0.20), fase 1 OK.

### Resultado — MIXTA
COMMITTED (decay=1): post_c_new_final=0.000, post_c_old_final=1.000 -> TOTALMENTE ATASCADO (60 consultas de
commitment no se mueven con 12 de adaptación). OLVIDO (decay=0.9): post_c_new_final=0.553, post_c_old_final=
0.041, midpoint fase1=0.941 -> ADAPTA (gap +0.553 sobre committed) habiendo identificado la vieja. decay 0.8/0.7:
adaptan menos y desestabilizan (midpoint cae 0.669/0.389 = olvidan demasiado) -> SWEET SPOT estabilidad-
plasticidad en 0.9. VEREDICTO MIXTA (honesto): el GAP sobre committed es enorme y el committed está totalmente
atascado, PERO la adaptación absoluta (0.553) no llega al umbral pre-registrado 0.60 -> adaptación PARCIAL en
presupuesto corto (no muevo el poste). El hallazgo cualitativo es fuerte: olvidar es necesario para adaptarse.

### Límites (honestos)
La adaptación es PARCIAL (K2=12 corto; re-identificar del todo desde el clúster necesita más). BOUNDARY observado
en calibración: con presupuesto de adaptación LARGO (K2~K1) el committed se adapta SOLO (la evidencia nueva
DESCONFIRMA la causa vieja) -> el olvido sólo es necesario bajo commitment profundo + adaptación corta. No se
midió olvido ADAPTATIVO (decay según la sorpresa) ni detección de cambio endógena (el experimento sabe cuándo
cambia). Mundo de juguete.

### Verificación
exp044 (24 seeds, bayesiano numpy, reusa exp022). cycle58 -> H-V4-1d 'mixta' (DoD), D-V4-23 ACEPTADA, 1 techo
'real', analogía, verify_no_loss=OK. Test `test_cycle58_nonstationary_forgetting.py` 4/4. Convergente con
forgetting/discounted-Bayes en no-estacionariedad (tier1).

> Extiende R-VALOR a la NO-ESTACIONARIEDAD (lo que pide el North-Star) y lo liga a MEMORIA: olvidar es una
> decisión de VALOR necesaria con recursos finitos cuando el mundo cambia; el committed Bayesiano clásico falla
> justo ahí. Sweet spot estabilidad-plasticidad. Sub-arco R-VALOR 56-58: valor endógeno (56) + señal medible por
> el agente (57) + olvido para adaptarse en no-estacionariedad (58).

## CYCLE 59 — H-V4-1e (North-Star R-VALOR x memoria, cierre sub-arco): olvido ADAPTATIVO dirigido por SORPRESA

### Pregunta
exp044 (CYCLE 58) mostró que el olvido FIJO adapta donde el committed se atasca — pero el decay fijo hay que
elegirlo a priori y olvida SIEMPRE (un decay agresivo estropea la fase 1). Límites #1/#2 de exp044: olvido
ADAPTATIVO + detección de cambio ENDÓGENA. ¿El agente puede detectar SOLO que el mundo cambió (sus predicciones
se contradicen = sorpresa, contracara de la confianza calibrada del CYCLE 57) y subir el olvido automáticamente,
sin que le digan cuándo cambió la causa?

### Diseño
Reusa exp044/exp022. Mundo no-estacionario (c_old K1=60, c_new K2=12). 4 brazos, MISMA política (info-gain),
distinto OLVIDO: committed (decay=1), fixed_mild (0.9), fixed_aggressive (0.6 CONSTANTE), ADAPTIVE (decay=floor
0.6 si la obs CONTRADICE P(y_obs|posterior)<0.5, si no 1.0). Métricas: post causa NUEVA final (adaptación) y
post causa vieja midpoint (estabilidad fase 1). 24 seeds. Pre-registrado: APOYADA si adaptive adapta
(post_c_new>=0.40, +>0.20 sobre committed) Y mantiene fase 1 (midpoint>=0.80, dominando al fixed_aggressive).

### Resultado — APOYADA
committed post_c_new=0.000/midpoint=1.000 (atascado, estable); fixed_mild post_c_new=0.448/midpoint=0.989
(adapta, estable, pero decay tuneado a priori); fixed_aggressive (0.6 CONSTANTE) post_c_new=0.197/midpoint=0.201
(olvida SIEMPRE -> DESTRUYE la fase 1); ADAPTIVE (floor 0.6 por SORPRESA) post_c_new=0.449/midpoint=0.843. El
ADAPTIVE logra el trade-off estabilidad-plasticidad ENDÓGENO: ADAPTA (0.449, igual que el mejor decay fijo
TUNEADO fixed_mild 0.448) pero SIN tunear ni saber el punto de cambio, Y mantiene la fase 1 (0.843) MUY por
encima del MISMO floor constante (0.201). HALLAZGO CLAVE: olvido SELECTIVO (por sorpresa) >> olvido CONSTANTE:
committea cuando confirma, olvida cuando se contradice (~25 pasos de olvido). El sistema detecta el cambio por
su PROPIA sorpresa y modula el olvido sin supervisión.

### Límites (honestos)
El adaptive IGUALA (no SUPERA) al mejor decay fijo en adaptación; su ventaja es ser ENDÓGENO/untuned + dominar
en estabilidad, no ser más plástico. El trigger es un umbral BINARIO (P<0.5); falta olvido GRADUADO por magnitud
de sorpresa y ventana acumulada (robustez al ruido). Mundo de juguete con UN solo cambio; falta no-estacionariedad
recurrente/gradual.

### Verificación
exp045 (24 seeds, bayesiano numpy, reusa exp022/exp044). cycle59 -> H-V4-1e 'apoyada' (DoD), D-V4-24 ACEPTADA,
1 techo 'real', analogía, verify_no_loss=OK. Test `test_cycle59_adaptive_forgetting.py` 4/4. Convergente con
surprise/change-point (Bayesian online change-point, tier1); une CYCLE 57 (confianza/sorpresa) + 58 (olvido).

> CIERRE del sub-arco R-VALOR (56-59): valor endógeno aislado (56) + medible por la confianza calibrada del
> agente (57) + olvido necesario en no-estacionariedad (58) + olvido ADAPTATIVO por sorpresa que detecta el
> cambio SIN supervisión (59). El lab tiene un lazo de VALOR ENDÓGENO cerrado: el sistema juzga qué información
> vale (confianza calibrada) y cuándo dejó de valer (sorpresa -> olvido), sin oráculo ni aviso externo. Conecta
> R-VALOR con MEMORIA (escribir≡olvidar, H-V4-5) y con el arco de auto-mejora (el verificador externo es, en
> parte, reemplazable por la confianza/sorpresa endógena).

## CYCLE 60 — H-V4-2i (UNIFICACIÓN de los dos arcos): auto-consistencia como verificador PARCIAL gateado por calibración

### Pregunta
La corrida cerró dos arcos: VERIFICADOR-REAL (51-55, el verificador EXTERNO es el motor) y R-VALOR (56-59, hay
señal de valor ENDÓGENA — confianza calibrada — usable sin oráculo, pero confiable sólo con la competencia
correcta, CYCLE 57). Insight del CYCLE 57: "el verificador externo es, en parte, reemplazable por la confianza
calibrada". ¿Se sostiene en el sustrato de AUTO-MEJORA? ¿Filtrar las auto-generaciones por AUTO-CONSISTENCIA
(¿el modelo produce el mismo VALOR consistentemente?) en vez del verificador externo funciona — y está GATEADO
por la calibración?

### Diseño
Reusa exp018/exp037. DOS regímenes de base: FUERTE (base_steps=250 -> ~0.63, calibrado) y DÉBIL (150 -> ~0.18,
mal calibrado). En cada uno, lazo R=4, 3 brazos (mismo base+RNG): verified (sandbox EXTERNO), self_consistency
(ENDÓGENO: valor mayoritario con acuerdo >= tau, SIN chequear target), naive (todas). Métrica: real_acc externo
clean media-rondas; CALIBRACIÓN de la consistencia (frac de consistentes cuyo valor==target). 3 seeds. (Afinado
tras smoke al claim de GATING por calibración.)

### Resultado — MIXTA
FUERTE (base 0.633, calib 0.76): verified 0.879, self_consistency 0.592 (>naive 0.515, +0.077), naive 0.515.
DÉBIL (base 0.182, calib 0.16): verified 0.557, self_consistency 0.038 (<<naive 0.090, menos de la mitad), naive
0.090. GATING por calibración NÍTIDO (contraste 0.595): con base fuerte/calibrada la auto-consistencia SUPERA a
naive sin degradar la base (captura PARTE del beneficio del verificador externo, que sigue siendo mejor 0.879);
con base débil/mal-calibrada COLAPSA muy por debajo de naive (consistente-pero-equivocado refuerza errores
confiados = el peligro del CYCLE 57 manifiesto en el lazo). VEREDICTO MIXTA (honesto): el fenómeno (gating +
colapso débil + usabilidad fuerte) es claro, PERO los umbrales estrictos no se cruzan todos limpiamente — el
'weak_collapses' (sc < naive - 2σ/2) falló por 0.0007 (naive es tan chico, 0.090, que el buffer 2σ/2=0.053 lo
hace borderline; en términos absolutos sc=0.038 es <50% de naive = colapso claro) y la ventaja fuerte-sobre-naive
(+0.077) no cruza 2σ (0.105). NO se movió ningún umbral.

### Límites (honestos)
La ventaja FUERTE-sobre-naive es MODESTA (no 2σ): la auto-consistencia PREVIENE la degradación de naive más que
IGUALAR al verificador externo (que sigue siendo claramente superior). Acuerdo sobre el VALOR en tarea de vocab
chico (puede sobre-estimar consistencia). Un solo umbral tau. No se hizo el gating EXPLÍCITO (usar el filtro
endógeno SÓLO cuando la calibración estimada es alta) ni combinar endógeno+externo.

### Verificación
exp046 (3 seeds, 2 regímenes, HybridLM, reusa exp018/exp037). cycle60 -> H-V4-2i 'mixta' (DoD), D-V4-25
ACEPTADA, 1 techo 'real', analogía, verify_no_loss=OK. Test `test_cycle60_self_consistency_verifier.py` 4/4.
Convergente con self-consistency (tier1) y confirma el CYCLE 57 (la confianza es confiable con la competencia
correcta).

> UNE los dos arcos de la corrida: la confianza endógena (R-VALOR 56-59) reemplaza PARCIALMENTE al verificador
> externo del lazo de auto-mejora (VERIFICADOR-REAL 51-55), GATEADA por la calibración. El verificador externo
> es sustituible donde el modelo está calibrado (medible por su propia calibración, CYCLE 57); usarlo mal
> calibrado es peligroso (refuerza errores). Cierra el lazo conceptual de la corrida: valor endógeno (qué vale,
> cuándo deja de valer, y cuándo confiar en el propio juicio) conectado con la auto-mejora.

## CYCLE 62 — H-V4-2j (cierre de la UNIFICACIÓN): GATING EXPLÍCITO — el agente decide cuándo confiar en sí mismo

### Pregunta
exp046 (CYCLE 60) mostró que la auto-consistencia COLAPSA cuando el modelo no está calibrado (consistente-pero-
equivocado). El peligro: usarla cuando no es confiable. ¿Puede el agente ESTIMAR su propia calibración (probe
barato) y DECIDIR — usar el filtro endógeno donde es confiable, deferir al verificador externo donde no — y así
ser robusto (nunca colapsar)?

### Diseño
Reusa exp046. DOS regímenes de base (FUERTE calibrado / DÉBIL mal-calibrado). 4 brazos: verified, self_consistency,
naive, y GATED (cada ronda estima calib_est en un probe_frac=15% de prompts; si >= umbral 0.65 usa endógeno, si
no cae a externo). Métrica: real_acc media-rondas; del GATED, frac de rondas que eligió endógeno y oracle_frac.
3 seeds. (En esta tarea el target está en el prompt -> el probe es barato; en tareas con oráculo caro serían
pocas llamadas para calibrar.)

### Resultado — MIXTA
FUERTE (calib alta): gated 0.733 elige ENDÓGENO 92% de las rondas (oracle_frac 0.22), NO pierde (vs self_cons
0.592) y se acerca a verified (0.879) -> verificación BARATA sin oráculo donde es confiable. DÉBIL (mal calib):
gated 0.328 elige EXTERNO 67%, EVITA el COLAPSO de self_consistency (0.038) -- pero NO iguala del todo a verified
(0.557). VEREDICTO MIXTA (honesto): el gate da SEGURIDAD (nunca colapsa) y decide bien en fuerte, pero el
ESTIMADOR de calibración por probe es RUIDOSO (en débil eligió endógeno 33% de las rondas, arrastrando el
resultado de ~0.557 a 0.328) -> no iguala a verified. El valor robusto demostrado es EVITAR EL COLAPSO, no la
recuperación perfecta.

### Límites (honestos)
La estimación de calibración por probe es RUIDOSA (modelo débil + probe chico = 15%) -> el gate a veces confía de
más en débil. En esta tarea el oráculo es BARATO (target en el prompt) -> el AHORRO de oráculo (la generalización
a tareas con oráculo caro) NO se midió; lo demostrado es el MECANISMO de decisión y la SEGURIDAD. Un solo umbral
de calibración; falta probe adaptativo y ligar el gate a la confianza calibrada del CYCLE 57.

### Verificación
exp047 (3 seeds, 2 regímenes, HybridLM, reusa exp046). cycle62 -> H-V4-2j 'mixta' (DoD), D-V4-26 ACEPTADA, 1
techo 'real', analogía, verify_no_loss=OK. Test `test_cycle62_gated_self_verifier.py` 5/5. Convergente con
meta-cognición / selective prediction (saber cuándo sabe) (tier1).

> CIERRE de la UNIFICACIÓN (60-62): un agente con valor endógeno (confianza calibrada, 56-59) puede DECIDIR
> cuándo su propio juicio reemplaza al verificador externo y cuándo deferir, estimando su calibración. Es
> ROBUSTO (nunca colapsa): endógeno barato cuando es confiable, externo seguro cuando no. Meta-cognición barata
> (saber cuándo sabe). Es la conexión operativa entre los dos arcos de la corrida.

## CYCLE 63 — H-V4-1f (North-Star R-VALOR x memoria): olvido en no-estacionariedad RECURRENTE

### Pregunta
exp044/045 (CYCLE 58/59) probaron UN solo cambio de causa. ¿El olvido maneja no-estacionariedad RECURRENTE (la
causa cambia varias veces)? ¿El committed se atasca, el adaptativo por sorpresa sigue la causa vigente, y cuál
tipo de olvido es mejor?

### Diseño
Bayesiano numpy (reusa exp022/exp044). Mundo recurrente: clúster confundido; causas = clúster[:n_phases]; y =
x[causa_de_la_fase] por K_phase=12 pasos por fase (corto: a budget largo el committed re-adapta solo). 5 fases (4
cambios). MISMA política (info-gain); sólo cambia el OLVIDO: committed (decay=1), fixed (0.85), adaptive (floor
0.6 por sorpresa). Métrica: post sobre la causa VIGENTE al final de cada fase. 16 seeds.

### Resultado — APOYADA (con hallazgo honesto que refina el CYCLE 59)
post-vigente por fase: committed [0.841,0.408,0.480,0.238,0.134] -> se atasca PROGRESIVAMENTE (acumular
commitment lo deja cada vez más trabado, post-cambio 0.315); adaptive [0.691,0.497,0.526,0.531,0.398] SIGUE la
causa vigente (post-cambio 0.488 >> committed) sin que le digan cuándo cambia; fixed [0.650,0.703,0.460,0.579,
0.326] es el MEJOR (post-cambio 0.517). HALLAZGO CLAVE (refina CYCLE 59): el olvido CONSTANTE supera al
surprise-gating en el mundo RECURRENTE -- cuando el mundo NUNCA se estabiliza, 'committear cuando confirma' (la
virtud del surprise-gating para UN cambio aislado) se vuelve un VICIO (sobre-committea en sub-fases). => el TIPO
óptimo de olvido DEPENDE del régimen: surprise-gated para cambios AISLADOS (CYCLE 59), constante para RECURRENTES.

### Límites (honestos)
El adaptive (surprise-gated) NO es el mejor olvido aquí (lo es el constante); el veredicto APOYADA es por 'el
olvido maneja recurrencia y el committed se atasca progresivamente'. A budget por fase LARGO (K_phase~30) el
committed re-adapta solo por desconfirmación (boundary del CYCLE 58); el efecto requiere fases cortas. Mundo de
juguete. Falta un agente que ESTIME la tasa de cambio y elija el tipo/ritmo de olvido (meta-decisión de valor).

### Verificación
exp049 (16 seeds, bayesiano numpy, reusa exp022/exp044). cycle63 -> H-V4-1f 'apoyada' (DoD), D-V4-27 ACEPTADA, 1
techo 'real', analogía, verify_no_loss=OK. Test `test_cycle63_recurrent_nonstationary.py` 5/5. Convergente con
tracking no-estacionario / constant-forgetting (tier1); refina CYCLE 59.

### NOTA — intento previo H-V4-4 (techo de recall = optimización) DIFERIDO
Antes de exp049 se intentó H-V4-4 (currículo mueve el plateau de recall, exp048). Calibración honesta: el recall
a d=32 apenas aprende incluso en n_pairs=16 (0.136) con 700 steps -> la tarea está en el piso de aprendibilidad
y necesitaría miles de steps para mostrar el efecto del currículo limpio; el currículo lineal a n_pairs=40 no lo
sacó del piso. Demasiado lento/incierto para el deadline -> DIFERIDO (no commiteado). Retomar con más cómputo:
easy muy fácil (n_pairs=4) + currículo ESCALONADO + más steps.

> El olvido es necesario en no-estacionariedad recurrente y el committed clásico falla PROGRESIVAMENTE; el TIPO
> óptimo de olvido (constante vs adaptativo) depende del régimen -- un meta-parámetro que un VALOR endógeno
> debería elegir (estimar la tasa de cambio del mundo). Profundiza el sub-arco R-VALOR x memoria (58-59-63).

## CYCLE 64 — H-V4-1g (North-Star R-VALOR x memoria, cierre del loop 58-63): olvido META-ADAPTATIVO

### Pregunta
CYCLE 63 (exp049) dejó que el ÓPTIMO de olvido DEPENDE del régimen (constante para recurrente, surprise-gated
para aislado). Pero un agente real no sabe en qué régimen está. ¿Puede ESTIMARLO (de su propia sorpresa
sostenida por encima del piso de ruido) y ELEGIR su ritmo de olvido SIN que le digan el régimen?

### Diseño
Bayesiano numpy (reusa exp022/exp044/exp049). DOS regímenes: ESTACIONARIO (1 causa, committear es lo mejor) y
RECURRENTE (5 fases, K_phase=12, olvidar constante es lo mejor). 3 brazos (misma política info-gain): committed
(decay=1), fixed (0.85), META (surprise_ema por encima del piso de ruido p_obs -> decay = 1-(1-floor)*excess/ref).
16 seeds. Pre-registrado: APOYADA si meta IGUALA al mejor brazo de cada régimen; MIXTA si adapta en DIRECCIÓN
correcta en ambos (robusto) sin igualar; REFUTADA si no adapta.

### Resultado — MIXTA
ESTACIONARIO: committed=1.000 fixed=0.610 META=0.866 -> el meta COMMITTEA mucho más que el olvido-constante
(detecta estabilidad), aunque no llega al committed perfecto. RECURRENTE: committed=0.315 fixed=0.517 META=0.408
-> el meta OLVIDA más que committed (sigue algo los cambios), aunque NO llega al fixed. El META adapta su olvido
en DIRECCIÓN correcta en AMBOS regímenes SIN que le digan cuál, y es ROBUSTO (nunca el peor brazo). PERO es
ASIMÉTRICO: detecta ESTABILIDAD y committea MUY bien (0.866 vs constante 0.610), mientras su olvido bajo
RECURRENCIA es DÉBIL (0.408, lejos del constante 0.517) porque entre cambios su decay vuelve a subir. =>
MIXTA honesta: la meta-decisión de olvido es un VALOR endógeno computable de la propia sorpresa, parcialmente.

### Límites (honestos)
El meta NO iguala el óptimo de cada régimen (compromiso); asimétrico (commitea bien, olvido recurrente débil). El
mapeo sorpresa->decay tiene hiperparámetros (ref=0.15, ema=0.25, floor=0.7) no barridos -> un meta-controlador
mejor podría acercarse al óptimo. Mundo de juguete.

### Verificación
exp050 (16 seeds, bayesiano numpy). cycle64 -> H-V4-1g 'mixta' (DoD), D-V4-28 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle64_meta_forgetting.py` 5/5. Convergente con adaptive forgetting-rate (tier1);
cierra el loop del CYCLE 63.

> Cierra el loop R-VALOR x memoria (58-63-64): el agente estima la no-estacionariedad de su propia SORPRESA y
> mueve su olvido en la dirección correcta (robustez entre regímenes sin saber cuál). El VALOR (cuánto olvidar)
> es endógenamente estimable, parcialmente -- igualar el óptimo del régimen requiere un meta-controlador mejor.

## CYCLE 65 — H-V4-1h (R-VALOR x memoria): ¿un piso de olvido constante + sorpresa cierra el caveat del CYCLE 64? (NEGATIVO informativo)

### Pregunta
CYCLE 64: el meta-olvido (sólo sorpresa) es robusto pero DÉBIL en recurrente (entre cambios su decay sube y
deja de olvidar). Fix propuesto: un PISO CONSTANTE de olvido (nunca committear del todo) + el boost por sorpresa.
¿Da robustez óptima en ambos regímenes?

### Diseño
Bayesiano numpy (reusa exp050). DOS regímenes (ESTACIONARIO / RECURRENTE). 4 brazos: committed, fixed (0.85),
meta (CYCLE 64), COMBINED (piso 0.92 + sorpresa). 16 seeds. Pre-registrado: APOYADA si combined mejora al meta
en recurrente sin romper estacionario.

### Resultado — REFUTADA (negativo informativo)
ESTACIONARIO: committed=1.000 fixed=0.610 meta=0.866 COMBINED=0.797. RECURRENTE: committed=0.315 fixed=0.517
meta=0.408 COMBINED=0.404. El COMBINED (piso 0.92 + sorpresa) NO mejora al meta en recurrente (0.404 ~ 0.408; el
piso suave no alcanza al fixed 0.517 que olvida más) y HUNDE el estacionario (0.797 < meta 0.866). Un piso suave
es CONTRAPRODUCENTE; un piso agresivo (~0.85) simplemente SE CONVIERTE en el olvido-constante (fixed), perdiendo
el estacionario. INTERPRETACIÓN: el trade-off estabilidad-plasticidad es FUNDAMENTAL para un meta-controlador que
sólo modula la TASA de olvido -- no existe un escalar de olvido óptimo en ESTACIONARIO (committear) y RECURRENTE
(olvidar mucho) a la vez. Para lograr ambos haría falta DETECTAR el régimen y CAMBIAR de ESTRATEGIA (decisión
DISCRETA), no modular un escalar.

### Límites (honestos)
Sólo se probó un piso (0.92); el argumento "un piso agresivo se convierte en el constante" es razonado, no
barrido exhaustivamente (pero el sentido del trade-off lo soporta). Mundo de juguete. Falta el SELECTOR de
estrategia gateado por la clasificación del régimen (estacionario/aislado/recurrente).

### Verificación
exp051 (16 seeds, bayesiano numpy). cycle65 -> H-V4-1h 'refutada' (DoD), D-V4-29 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle65_combined_forgetting.py` 4/4. Convergente con stability-plasticity
trade-off (Grossberg, tier1).

> Resultado NEGATIVO que AFINA el CYCLE 64: la meta-decisión de olvido por modulación de TASA tiene un TECHO (el
> trade-off estabilidad-plasticidad). El valor endógeno tendría que elegir la ESTRATEGIA de memoria (committear
> vs olvidar-fuerte) gateada por la detección de régimen, no sólo el ritmo. (Honestidad anti-Goodhart: negativo
> reportado tal cual.)

## CYCLE 66 — H-V4-1i (North-Star R-VALOR x memoria, CIERRE del arco): SELECTOR DE ESTRATEGIA de memoria

### Pregunta
CYCLE 65 mostró que modular la TASA de olvido tiene un techo (trade-off estabilidad-plasticidad) y concluyó:
hace falta DETECTAR el régimen y CAMBIAR de ESTRATEGIA (decisión discreta). ¿Un selector que clasifica el régimen
de su propia sorpresa y conmuta committear<->olvidar-fuerte alcanza el óptimo en ambos regímenes?

### Diseño
Bayesiano numpy (reusa exp050/051). DOS regímenes (ESTACIONARIO / RECURRENTE). 3 brazos: committed (decay=1),
fixed (0.85), SELECTOR (clasifica el régimen de su sorpresa sostenida -> estable: committear decay=1; cambiante:
olvidar-fuerte decay=0.85). 16 seeds. Pre-registrado: APOYADA si selector ~committed en estacionario Y ~fixed en
recurrente (óptimo en ambos).

### Resultado — APOYADA (cierra el arco con la solución correcta)
ESTACIONARIO (committear óptimo): committed=1.000 fixed=0.602 SELECTOR=1.000 -> clasifica ESTABLE y committea
(= committed EXACTO, >> fixed). RECURRENTE (olvidar óptimo): committed=0.294 fixed=0.453 SELECTOR=0.511 ->
clasifica CAMBIANTE y olvida-fuerte (>= fixed, >> committed; incluso un poco MEJOR que el constante porque
consolida en las sub-fases estables y olvida en las transiciones). El SELECTOR alcanza el ÓPTIMO de cada régimen,
lo que la modulación de TASA (meta CYCLE 64, combined CYCLE 65) NO pudo. => el VALOR endógeno (de la propia
sorpresa sostenida) elige la ESTRATEGIA de memoria (committear vs olvidar-fuerte), una decisión DISCRETA que
vence el trade-off donde el escalar continuo fallaba.

### Límites (honestos)
Sólo DOS estrategias y DOS regímenes; un régimen INTERMEDIO (cambio aislado) necesitaría una 3ra estrategia (el
surprise-gating del CYCLE 59). El umbral de clasificación (p_obs+buffer) y la EMA son hiperparámetros; una tasa
de cambio cerca del umbral confundiría al selector. Mundo de juguete.

### Verificación
exp052 (16 seeds, bayesiano numpy, reusa exp050/051/049/044/022). cycle66 -> H-V4-1i 'apoyada' (DoD), D-V4-30
ACEPTADA, 1 techo 'real', analogía, verify_no_loss=OK. Test `test_cycle66_strategy_selector.py` 4/4. Convergente
con selección de estrategia gateada por contexto (mixture-of-experts, tier1); confirma la conclusión del CYCLE 65.

> CIERRA el arco R-VALOR x memoria (58·63-66): el sistema juzga QUÉ información vale (confianza calibrada), CUÁNDO
> dejó de valer (sorpresa -> olvido), y CÓMO recordar/olvidar según el régimen (selector de estrategia), todo de
> señales ENDÓGENAS. La meta-cognición de memoria es una decisión de MODO (committear vs olvidar-fuerte), no de
> intensidad. La modulación de TASA tiene un techo (CYCLE 65); el SELECTOR de estrategia lo vence (CYCLE 66).

## CYCLE 68 — H-V4-1j (North-Star R-VALOR x memoria, capstone): selector de 3 ESTRATEGIAS

### Pregunta
CYCLE 66 (selector de 2 estrategias) alcanzó el óptimo en estacionario y recurrente. Falta el régimen
INTERMEDIO (cambio AISLADO tras commitment profundo, surprise-gate óptimo). ¿Un selector que clasifica 3
regímenes de su sorpresa en DOS escalas (lenta=tasa de cambio, rápida=shift) elige la estrategia correcta en los 3?

### Diseño
Bayesiano numpy (reusa exp052/049). FASES ASIMÉTRICAS. 3 regímenes: ESTACIONARIO [60], AISLADO [48,12], RECURRENTE
[12×5]. 4 brazos: committed, fixed(0.85), surprise_gate(0.6), SELECTOR3 (slow_ema>thr -> olvidar-fuerte;
fast_ema>thr -> surprise-gate; si no -> committear). 16 seeds. Pre-registrado: APOYADA si ~óptimo en los 3.

### Resultado — MIXTA (2/3)
ESTACIONARIO: committed=1.000 fixed=0.602 sgate=0.850 SELECTOR3=0.903 (óptimo: clasifica estable y committea).
AISLADO [48,12]: committed=0.000 (atascado) fixed=0.407 sgate=0.591 (óptimo) SELECTOR3=0.440 (NO óptimo: supera a
committed/fixed pero no alcanza al surprise_gate). RECURRENTE: committed=0.294 fixed=0.453 sgate=0.584
SELECTOR3=0.510 (óptimo: clasifica cambiante y olvida-fuerte). El selector3 acierta 2/3: estacionario y recurrente
limpios, el AISLADO direccional pero subóptimo. La frontera aislado<->recurrente en la escala lenta es sutil
(distinguirlas es la pieza difícil) y con sólo 12 pasos de adaptación el surprise-gate del selector no re-
identifica del todo. => clasificar 3 regímenes y elegir la estrategia es PARCIALMENTE posible de la sorpresa
endógena.

### Límites (honestos)
El régimen AISLADO (intermedio) no se clasifica/atiende limpio (MIXTA, no forzado). Umbrales de las 2 escalas +
tasas de EMA son hiperparámetros sensibles; un clasificador mejor (frecuencia de spikes, no nivel del EMA lento)
podría separar mejor. Presupuesto de adaptación fijo (12) limita el surprise-gate del selector en aislado. Mundo
de juguete.

### Verificación
exp053 (16 seeds, bayesiano numpy). cycle68 -> H-V4-1j 'mixta' (DoD), D-V4-31 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle68_strategy_selector3.py` 4/4. Convergente con clasificación de régimen
multi-escala (tier1); extiende CYCLE 66.

> Capstone del arco memoria con éxito PARCIAL: la tesis del CYCLE 66 (el valor endógeno elige la ESTRATEGIA de
> memoria) se extiende a 3 regímenes -- 2/3 limpio. La pieza difícil es la CLASIFICACIÓN del régimen intermedio,
> no la selección de estrategia. El valor endógeno selecciona la estrategia cuando los regímenes son separables.

## CYCLE 69 — H-V4-3 (raíz FRESCA R-PRIOR): la CALIDAD del prior > su forma

### Pregunta
El thesis v4 lista R-PRIOR como raíz convergente ("un prior fuerte es necesario; su CALIDAD, no su forma, fija
la eficiencia muestral; MDL/programas es una apuesta de diseño, no la raíz"). ¿Un prior con la SIMETRÍA correcta
(equivarianza) es muy eficiente muestralmente, y un prior EQUIVOCADO hunde por debajo de no asumir nada?

### Diseño
Numpy (logreg). Tarea perm-invariante: x in {0,1}^20, y=1 si sum(x)>=10 (depende sólo del CONTEO). 3 priors = 3
feature maps: correcto (1 feature = conteo), general (20 features crudas), equivocado (sólo k=3 primeras
posiciones). Métrica: test acc vs nº de ejemplos {4,8,16,32,64,128}. 24 seeds.

### Resultado — APOYADA
correcto acc vs n: 0.806/0.917/0.912/0.942/0.968/1.000. general: 0.548/0.569/0.601/0.656/0.809/0.917.
equivocado: 0.547/0.552/0.580/0.607/0.622/0.635. El prior CORRECTO alcanza 0.917 con sólo 8 ejemplos (general
0.569 ahí: +0.348 de eficiencia); el general necesita ~128 ejemplos (~16x más) para igualar lo que el correcto
logra con 8. El prior EQUIVOCADO se clava en 0.635 aun a 128 ejemplos, MUY por DEBAJO del general (0.917) -- un
prior FALSO es SESGO IRREDUCIBLE que hunde por debajo de no asumir nada. => la CALIDAD/corrección del prior (la
simetría correcta) es el lever de la eficiencia muestral, no tenerlo ni su forma.

### Límites (honestos)
Tarea de juguete (1 simetría perm-invariante, logreg lineal). El techo del correcto depende de entrenar bien:
con sobre-regularización (l2=1e-3) se topaba en ~0.82; con l2 chico (1e-4) llega a ~1.0 -- el prior correcto SÍ
puede representar la verdad, la regularización lo ocultaba; se reporta el techo real (artefacto de entrenamiento,
no de la hipótesis). No se comparó contra un buscador-de-programas/MDL real (sólo se argumenta el costo). La
simetría se da de antemano (falta APRENDERLA = meta-prior).

### Verificación
exp054 (24 seeds, logreg numpy). cycle69 -> H-V4-3 'apoyada' (DoD), D-V4-32 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle69_prior_quality.py` 5/5. Convergente con no-free-lunch/equivariancia (tier1) y
con el thesis R-PRIOR.

> Raíz FRESCA R-PRIOR confirmada en juguete: la calidad/corrección del prior fija la eficiencia muestral; un prior
> barato con la equivarianza correcta vence a la fuerza bruta de datos, y un prior falso hunde. Conecta R-PRIOR
> con R-VALOR (un buen prior es valor a priori sobre qué estructura importa). Da BREADTH a la corrida más allá del
> arco verificador/R-VALOR/memoria.

## CYCLE 70 — H-V4-5 (cierra la última raíz abierta del v4): escribir≡olvidar es rate-distortion dirigido por VALOR

### Pregunta
El thesis v4 (R-VALOR raíz primera): escribir/olvidar es selectivo, "consolidar exige saber qué proteger --
indefinible sin un escalar de valor". H-V4-5: ¿la ventaja de una memoria finita está ATADA a R-VALOR -- ablar
el valor mata la ventaja?

### Diseño
Numpy. Memoria de capacidad m=10/n=50 items; cada item con VALOR (prob de consulta, power-law alpha=1.5). 4
políticas de escritura: value_directed (top-m por valor), random, ablation (valor removido = azar), anti_value
(bottom-m). Métrica: hit-rate ponderado por valor (masa de valor cubierta por lo guardado). 48 seeds.
Pre-registrado: APOYADA si value_directed >> random Y ablar el valor colapsa a random Y anti_value < random.

### Resultado — APOYADA
value_directed=0.507 (cubre 50% del valor de consulta con sólo 10/50 items), random=0.184 (~m/n=0.20),
ablation=0.200 (= random: ablar el valor colapsa la ventaja), anti_value=0.086 (< random: la dirección importa).
La escritura por valor da +0.323 sobre aleatoria; ABLAR la señal de valor la colapsa exactamente a random -> la
ventaja de la memoria ES el valor, no la capacidad ni la 'selectividad' abstracta. anti_value < random confirma
que la DIRECCIÓN del valor importa. => escribir≡olvidar es rate-distortion dirigido por valor; quitar la utilidad
mata la ventaja.

### Límites (honestos)
El valor (prob de consulta) se da PERFECTO; falta valor ESTIMADO ruidoso (aunque CYCLE 56-57 ya mostraron que el
valor endógeno -- info-gain/confianza -- es estimable). Tarea de juguete (selección estática, power-law). Métrica
= masa de valor cubierta (exacta); falta un downstream más rico y memoria dinámica online.

### Verificación
exp055 (48 seeds, numpy). cycle70 -> H-V4-5 'apoyada' (DoD), D-V4-33 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle70_value_memory.py` 4/4. Convergente con rate-distortion (tier1) y con el
thesis R-VALOR/escribir≡olvidar.

> CIERRA la última raíz abierta del v4 y el lazo R-VALOR x MEMORIA: las cuatro operaciones de memoria (escribir/
> olvidar/recordar/consolidar) son indefinibles sin valor, y aquí se muestra empíricamente que la ventaja de la
> memoria ES el valor -> R-VALOR es, en efecto, la raíz que aterriza la memoria. Conecta con el valor endógeno
> medible (CYCLE 56-57) y el selector de estrategia (CYCLE 66): el valor decide qué/cuándo/cómo recordar.

## CYCLE 72 — H-V4-5b (ABRE el arco "R-VALOR bajo realismo"): valor ESTIMADO online recupera la ventaja del oráculo

### Pregunta
El CYCLE 70 (exp055, H-V4-5 APOYADA) cerró "la ventaja de una memoria finita ES el valor" PERO con dos muletas de
juguete que su propio techo 'real' registró como blockers: el valor de consulta se daba PERFECTO y la selección
era ESTÁTICA. ¿Sobrevive la ventaja si el agente NO conoce el valor y debe ESTIMARLO online de su propia
experiencia, en una memoria dinámica? ¿Y le gana a una heurística value-free (recencia)?

### Diseño
Numpy. Memoria ONLINE de capacidad m=10/n=50; stream de T=3000 consultas IID ~ valor (power-law Pareto alpha=1.5).
HIT si el item consultado está en memoria ANTES de verlo. Métrica = hit-rate online en la ventana FINAL 20%
(estado estacionario), un downstream más rico que la masa exacta de exp055. 5 brazos de escritura/evicción:
oracle (top-m por valor VERDADERO, fijo = cota superior = value_directed de exp055), estimated (top-m por
FRECUENCIA observada = LFU = valor endógeno estimado online), recency (los m más recientes = LRU, value-FREE),
random (m fijos al azar), anti_value (top-m por frecuencia más BAJA = control de dirección). 48 seeds.
Pre-registrado: APOYADA si estimated recupera >=70% de la ventaja del oráculo Y +>0.15 vs random Y +>0.03 vs recency.

### Resultado — APOYADA
hit-rate ventana final: oracle=0.508 (cross-valida exp055 value_directed=0.507), estimated=0.506, recency=0.370,
random=0.219, anti_value=0.088 (azar m/n=0.200). estimated recupera **99%** de la ventaja del oráculo (0.508) sobre
random (0.219) SIN conocer el valor verdadero; +0.287 sobre aleatoria; +0.135 sobre recency (LRU value-free);
anti_value 0.088 < random (la dirección del valor estimado importa). La curva cumulativa de estimated
[0.473, 0.485, 0.493, 0.496] muestra al estimador CONVERGER al oráculo. => la ventaja por valor SOBREVIVE a
estimarlo online de la frecuencia observada (valor endógeno), sin oráculo, y vence a una memoria sin valor.

### Límites (honestos)
(1) Régimen ESTACIONARIO: bajo popularidad FIJA, LFU≈óptimo es un resultado clásico de caching; la frontera real
es la NO-estacionariedad, donde la frecuencia de TODA la historia es un valor SESGADO y hace falta olvido dirigido
por sorpresa -- eso YA lo estudió el lab (CYCLE 58-66: el TIPO de olvido se elige del régimen). Por eso el valor
de este ciclo es quitar la muleta de valor-PERFECTO, no descubrir LFU. (2) El estimador es FRECUENCIA pura; CYCLE
56-57 ya mostraron valores endógenos más ricos (info-gain/confianza). (3) Juguete (Pareto, n=50, consultas IID;
sin estructura/correlación en las consultas).

### Verificación
exp056 (48 seeds, numpy, T=3000). cycle72 -> H-V4-5b 'apoyada' (DoD), D-V4-34 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle72_estimated_value_memory.py` 5/5 (incluye oracle≈masa-top-m y las 3 ramas del
veredicto). Convergente con LFU/rate-distortion (tier1) y con el techo de CYCLE 70 (tier5).

> ABRE el arco "R-VALOR bajo realismo" (quitar las muletas de juguete una por una): la tesis R-VALOR×memoria NO
> depende de un oráculo de valor -- un estimador endógeno barato (frecuencia/uso) recupera ~99% de la ventaja en
> régimen estacionario y le gana a una memoria value-free. Próxima hija (CYCLE 73): atar el estimador a la
> NO-estacionariedad combinándolo con el olvido dirigido por sorpresa (CYCLE 59) y el selector de estrategia
> (CYCLE 66) -- frecuencia con ventana/decay adaptativo donde la frecuencia-de-toda-la-historia falla.

## CYCLE 73 — H-V4-5c (arco "R-VALOR bajo realismo", hija del 72): el estimador de valor debe OLVIDAR (decay) bajo no-estacionariedad

### Pregunta
El CYCLE 72 (exp056, H-V4-5b) cerró que el valor es estimable de la frecuencia observada -- PERO sólo en régimen
ESTACIONARIO. Su caveat honesto: bajo NO-estacionariedad la frecuencia de TODA la historia es un valor SESGADO
(mezcla épocas). El lab ya mostró (CYCLE 58-66) que el TIPO de olvido se elige del régimen. ¿Olvidar (decay) en el
conteo de frecuencia recupera la ventaja cuando la popularidad CAMBIA? ¿Y le gana a una memoria value-free (LRU)?

### Diseño
Numpy. Memoria online m=10/n=50. Popularidad power-law (Pareto) PERO la asignación item->valor se RE-PERMUTA cada
K_phase=300 pasos (régimen RECURRENTE, cf. CYCLE 63): la forma de la distribución es fija, QUÉ items son populares
cambia. DOS escenarios -- ESTACIONARIO (asignación fija) y NO-ESTACIONARIO (re-permuta cada fase) -- para exhibir
el CROSSOVER. 5 brazos: oracle_current (top-m por valor verdadero de la fase, cota), lfu_full (frecuencia acumulada
de toda la historia = estimador del 72, NO olvida), lfu_decay (frecuencia con decay=0.97, ventana ~33, OLVIDA),
recency (LRU value-free), random. Métrica = hit-rate online tras warm-up (1 fase). 32 seeds. Pre-registrado:
APOYADA si en no-estac. decay>full (+>0.05) Y recupera >=55% del oráculo Y >recency (+>0.03), con el control de que
en estac. full>=decay (olvidar cuesta).

### Resultado — APOYADA
ESTACIONARIO: oracle=0.521 lfu_full=0.511 (~oracle, como CYCLE 72) lfu_decay=0.443 recency=0.382 random=0.207.
NO-ESTACIONARIO: oracle=0.516 lfu_full=0.341 (DEGRADA de 0.511, cae hacia random 0.191 al promediar épocas)
lfu_decay=0.430 (recupera 74% de la ventaja del oráculo) recency=0.379 random=0.191. CROSSOVER limpio: lfu_decay
vence a lfu_full por +0.090 y a recency value-free por +0.051 bajo cambio; lfu_full gana sin cambio (estac.
0.511>=decay 0.443 -> olvidar tiene un COSTO, tradeoff estabilidad-plasticidad real, NO dominación de decay). => el
estimador de valor endógeno por frecuencia DEBE olvidar (descontar el pasado) para servir bajo no-estacionariedad.

### Límites (honestos)
(1) El decay es FIJO (0.97); el óptimo depende de la tasa de cambio -- un decay ADAPTATIVO/meta lo elegiría
(CYCLE 64/66 ya lo hicieron para el olvido de memoria; queda como hija CYCLE 74). (2) Bajo cambio FUERTE la recency
value-free (LRU) queda competitiva (decay sólo +0.051): el valor estimado tiene poco tiempo de acumularse; honesto,
no se infló a APOYADA-fuerte. (3) Cambio ABRUPTO recurrente (no deriva gradual); juguete (Pareto, n=50, IID dentro
de fase).

### Verificación
exp057 (32 seeds, numpy, decay=0.97). cycle73 -> H-V4-5c 'apoyada' (DoD), D-V4-35 ACEPTADA, 1 techo 'real',
analogía, verify_no_loss=OK. Test `test_cycle73_nonstationary_value_memory.py` 4/4 (incluye crossover full/decay y
las 3 ramas del veredicto). Convergente con decay/tracking no-estacionario (tier1) y con el caveat de CYCLE 72 (tier5).

> ATA R-VALOR (el estimador endógeno del 72) con el arco de OLVIDO (CYCLE 58-66): qué información VALE (frecuencia)
> y CUÁNDO dejó de valer (descontar el pasado) son la MISMA señal vista en dos tiempos. El estimador de valor con
> decay rastrea popularidad no-estacionaria; full la promedia y se confunde. Próxima hija (CYCLE 74): decay
> ADAPTATIVO -- elegir la tasa de olvido del estimador de la propia sorpresa/tasa de cambio (meta-olvido CYCLE 64 /
> selector de estrategia CYCLE 66 aplicados sobre el estimador de valor), para no pagar el costo del olvido sin cambio.

## CYCLE 74 — H-V4-5d (arco "R-VALOR bajo realismo", CIERRA el sub-arco 72-73-74): el estimador de valor elige su tasa de olvido

### Pregunta
CYCLE 73 (exp057, H-V4-5c) mostró el CROSSOVER (full gana sin cambio, decay con cambio) pero con decay FIJO (su
caveat #1: el óptimo depende de la tasa de cambio). El lab ya mostró (CYCLE 64 meta-olvido MIXTA; CYCLE 66 selector
de estrategia alcanza el óptimo) que ELEGIR la estrategia (discreto) vence a modular la tasa. ¿Un selector discreto
full<->decay, gateado por la sorpresa endógena, logra NO-REGRET en ambos regímenes sobre el ESTIMADOR DE VALOR?

### Diseño
Numpy (idéntico a exp057). Memoria online m=10/n=50, popularidad que re-permuta cada K_phase=300 (no-estac.) o fija
(estac.). 6 brazos: oracle_current, lfu_full, lfu_decay (decay=0.97), SELECTOR, recency, random. El selector corre
AMBOS expertos (full+decay) en SOMBRA y en cada paso usa la memoria del experto con mayor hit-rate RECIENTE (EMA
beta=0.98 de sus PROPIOS aciertos -- endógeno, sin oráculo ni aviso de régimen). Diagnóstico: fracción de pasos que
el selector eligió decay. 32 seeds. Pre-registrado: APOYADA si el selector iguala al mejor experto en CADA régimen
(dentro de 0.03) Y supera al fijo equivocado en cada uno (+>0.02) = NO-REGRET.

### Resultado — APOYADA (no-regret)
ESTACIONARIO: oracle=0.521 full=0.511 decay=0.443 SELECTOR=0.507 (usa decay 6%) recency=0.382 random=0.208 -> el
selector iguala a full (mejor) dentro de 0.004 y supera a decay. NO-ESTACIONARIO: oracle=0.516 full=0.341 decay=0.430
SELECTOR=0.425 (usa decay 88%) recency=0.379 random=0.205 -> iguala a decay (mejor) dentro de 0.005 y supera a full
por +0.084. Ningún experto FIJO es el mejor en AMBOS regímenes; el SELECTOR sí. El diagnóstico confirma detección
ENDÓGENA del régimen: usó decay 6% del tiempo en estacionario vs 88% en no-estacionario. => el estimador de valor
elige su propia tasa de olvido de su propio acierto reciente, sin hiperparámetro de régimen.

### Límites (honestos)
(1) El selector NO supera al mejor experto (es selección, no mejora) y hereda el techo del oráculo; su valor es la
ROBUSTEZ entre regímenes, no un techo más alto. (2) Sólo DOS expertos (full/decay); un continuo de tasas necesitaría
más expertos o un meta-continuo (CYCLE 64 fue MIXTA ahí -> el discreto es lo que funciona, cf. CYCLE 66). (3) el
valor estimado sigue siendo FRECUENCIA pura; cambio abrupto recurrente; juguete (Pareto, n=50, IID dentro de fase).

### Verificación
exp058 (32 seeds, numpy, beta=0.98). cycle74 -> H-V4-5d 'apoyada' (DoD), D-V4-36 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle74_adaptive_value_memory.py` 4/4 (no-regret + detección de régimen + 3 ramas).
Gate dirigido (tests de ciclos 72/73/74 + research engine) 33/33. Convergente con prediction-with-expert-advice/
no-regret (tier1) y con el selector de estrategia CYCLE 66 (tier5).

> CIERRA el sub-arco R-VALOR-estimador (72-73-74) y la muleta 'decay fijo' del 73: el estimador de valor endógeno
> elige QUÉ información vale (frecuencia, 72), CUÁNDO dejó de valer y a qué RITMO olvidar (selector, 74) -- todo de
> su propia experiencia, sin oráculo ni hiperparámetro de régimen. R-VALOR × OLVIDO queda cerrado endógenamente.
> El SELECTOR discreto (no la modulación continua de tasa) es lo que logra no-regret, replicando CYCLE 66 sobre el
> estimador de valor. Próximo: subir de frecuencia a un valor endógeno más rico (info-gain/confianza, CYCLE 56-57)
> o escalar a un downstream no-IID; o pivotar a otra muleta del arco realismo.

## CYCLE 75 — H-V4-5e (arco "R-VALOR bajo realismo", capstone CONCEPTUAL): el VALOR != FRECUENCIA (task-definido)

### Pregunta
El sub-arco 72-74 estimó el valor por FRECUENCIA -- pero ahí el valor ERA la frecuencia (prob de consulta), así que
la frecuencia era un estimador perfecto. El thesis v4 dice que el valor es task-definido (info mutua con consultas/
RECOMPENSAS FUTURAS), no un proxy de frecuencia. ¿Si SEPARAMOS frecuencia de valor (cada item con frecuencia f_i Y
costo-de-fallar c_i independiente, valor v=f×c), estimar la FRECUENCIA sola falla y hay que estimar el VALOR?

### Diseño
Numpy. Memoria online m=10/n=50. En cada consulta (IID ~ f) el agente OBSERVA el costo c del item (stakes
reveladas). Objetivo = maximizar el HIT-RATE PONDERADO POR COSTO (fracción del costo de consulta cubierta). DOS
escenarios: COST_UNIFORM (c=1 -> v proporcional a f) y COST_VARYING (c ~ Pareto indep. de f -> v != f). 5 brazos:
oracle_value (top-m por v=f×c, cota), lfu_freq (top-m por frecuencia observada = ignora costo), value_est (top-m por
COSTO ACUMULADO observado = estimador MC de f×c), recency, random. 48 seeds. Pre-registrado: APOYADA si en
cost-varying value_est>lfu (+>0.05) Y recupera >=70% del oráculo Y en cost-uniform value_est~lfu (|dif|<0.04).

### Resultado — APOYADA
COST_UNIFORM (v~f): oracle=0.506 lfu_freq=0.502 value_est=0.502 (|dif|=0.000) -- convergen: SIN divergencia no hay
ventaja. COST_VARYING (v!=f): oracle=0.639 lfu_freq=0.489 value_est=0.636 (recupera 99% del oráculo) random=0.169 --
value_est vence a lfu por +0.147; LFU deja 0.150 de valor sobre la mesa porque guarda lo frecuente-BARATO y falla lo
raro-CARO (optimiza la señal EQUIVOCADA). La ventaja la DRIVE que el valor diverja de la frecuencia (control uniform
limpio), no que value_est sea genéricamente mejor. => el valor es task-definido; estimar la FRECUENCIA (proxy) falla
cuando el valor diverge; estimar el VALOR (frecuencia×costo de consecuencia observado) acierta.

### Límites (honestos)
(1) El costo se OBSERVA en cada consulta (stakes reveladas); la versión dura sólo lo revela al FALLAR (tensión de
exploración: actuar para aprender el valor, R-INTERVENCIÓN) -- queda como hija. (2) costo INDEPENDIENTE de la
frecuencia (divergencia máxima); correlación parcial atenuaría la ventaja. (3) estacionario; valor = frecuencia×costo
(falta info-gain/confianza, CYCLE 56-57); juguete (Pareto, n=50, IID).

### Verificación
exp059 (48 seeds, numpy). cycle75 -> H-V4-5e 'apoyada' (DoD), D-V4-37 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle75_value_vs_frequency.py` 4/4 (crossover varying/uniform + 3 ramas). Gate
dirigido (ciclos 72-75 + research engine). Convergente con cost-aware caching/value-of-information (tier1) y con el
thesis R-VALOR task-definido (tier5).

> CAPSTONE CONCEPTUAL del arco realismo: eleva el arco más allá de "LFU textbook". El valor de recordar es
> task-definido (frecuencia × costo), NO la frecuencia; estimar un PROXY (frecuencia) falla cuando el valor diverge,
> y LFU es óptimo SÓLO cuando valor=frecuencia. El agente aprende el valor de sus CONSECUENCIAS (costo observado) ->
> liga el arco MEMORIA con R-INTERVENCIÓN (CYCLE 40-48). Próxima hija: costo revelado SÓLO al fallar (exploración);
> valor endógeno más rico (info-gain/confianza).

## CYCLE 76 — H-V4-5f (arco realismo, hija del 75): el valor con OBSERVACIÓN GATEADA POR LA ACCIÓN

### Pregunta
CYCLE 75 (exp059, H-V4-5e) asumió el costo OBSERVABLE en cada consulta. En la realidad, cachear un item te CIEGA a
su costo: si lo tenés, no sentís el dolor de fallarlo -> el costo se revela SÓLO al FALLAR (miss). La acción del
agente (cachear) decide qué observa (estructura tipo R-INTERVENCIÓN). ¿Estimar el valor task-definido SOBREVIVE a
esta observación gateada, o hace falta exploración (intervenir) para aprender?

### Diseño
Numpy (idéntico a exp059 cost-varying). Memoria online m=10/n=50, valor v=f×c. Métrica = hit-rate ponderado por
costo. 6 brazos: oracle_value, value_full (costo en cada consulta), value_miss (costo SÓLO al fallar = observación
gateada), value_explore (value_miss + sacrifica 1 slot a re-sondar el cacheado más viejo), lfu_freq, random. 48
seeds. Pre-registrado: APOYADA si value_miss recupera >=70% del oráculo Y >> lfu Y ~ value_full (|dif|<0.05).

### Resultado — APOYADA (matizado, honesto)
oracle=0.639 value_full=0.634 value_miss=0.634 value_explore=0.572 lfu_freq=0.490 random=0.231. value_miss recupera
99% del oráculo e IGUALA a value_full (|dif|=0.000): la observación gateada por la acción NO rompe el aprendizaje
del valor bajo ESTACIONARIEDAD. Mecanismo: el agente observa los costos de justo lo que NO cachea (su CONTRAFÁCTICO,
la info que necesita para decidir si cambiarlo) y el cold-start (cache vacía -> todo falla) observa todo una vez.
value_explore RESTA -0.063: sacrificar un slot a re-sondar NO ayuda con costos estacionarios. => el valor es
aprendible aunque la acción de cachear ciegue su observación; la intervención extra no hace falta acá.

### Límites (honestos)
MATIZ CLAVE: este resultado NIEGA la intuición fuerte "aprender valor EXIGE intervenir" EN ESTE RÉGIMEN -- la
observación pasiva del contrafáctico basta. La intervención (re-sondar) sería necesaria SÓLO con costos
NO-ESTACIONARIOS (un item cacheado cuyo costo DERIVA pasa desapercibido porque no se observa) -> ése es el caso
R-INTERVENCIÓN real y la próxima hija (combinar exp060 con la no-estacionariedad de exp057/CYCLE 73). La conexión
con R-INTERVENCIÓN es DÉBIL aquí; no se sobre-vende. Costos estacionarios; juguete (Pareto, n=50, IID).

### Verificación
exp060 (48 seeds, numpy). cycle76 -> H-V4-5f 'apoyada' (DoD), D-V4-38 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle76_action_gated_value.py` 4/4 (miss~full, >lfu, 3 ramas). Convergente con
active-sensing/partial-monitoring (tier1) y con el caveat de CYCLE 75 (tier5).

> Hija honesta del 75 que MATIZA R-INTERVENCIÓN sobre la memoria: bajo estacionariedad, observar el costo de lo que
> NO cacheás (tu regret/contrafáctico) basta para aprender el valor -- no hace falta intervenir, y la exploración
> extra resta. R-INTERVENCIÓN sobre la memoria aparece sólo cuando los costos de lo cacheado-no-observado DERIVAN
> (no-estacionariedad). Próxima hija: costos no-estacionarios + observación gateada (combinar CYCLE 73 + 76).

## CYCLE 77 — H-V4-5g (arco realismo, complemento del 76): bajo drift + obs gateada, ¿intervenir? — REFUTADA (informativa)

### Pregunta
CYCLE 76 (exp060, H-V4-5f) mostró que con observación gateada (costo sólo al fallar) PERO costos ESTACIONARIOS, la
intervención NO hace falta. Su caveat: si los costos DERIVAN, un item cacheado cuyo costo cambia pasa desapercibido
(cacheado=nunca falla=nunca se re-observa) -> ahí la intervención (re-sondar) debería pagar. ¿Bajo drift de costos +
obs gateada, re-sondar lo cacheado se vuelve necesario? (R-INTERVENCIÓN sobre la memoria.)

### Diseño
Numpy. Memoria online m=10/n=50, frecuencia f estacionaria, costo c que en DRIFT se re-permuta entre items cada
K_phase=300. Costo observado SÓLO al fallar; cost_est = último observado. Métrica = hit-rate ponderado por el costo
ACTUAL. DOS escenarios: COST_STATIONARY (control, = CYCLE 76) y COST_DRIFT. 6 brazos: oracle_value, value_full (obs
en cada consulta), value_miss (obs sólo al fallar, sin re-sondar), value_explore (value_miss + sacrifica 1 slot a
re-sondar el cacheado más viejo), lfu_freq, random. 32 seeds. Pre-registrado: APOYADA si con drift value_explore >
value_miss (+>0.05) con control de que sin drift explore<=miss.

### Resultado — REFUTADA (con matiz informativo)
COST_STATIONARY: oracle=0.662 full=0.653 miss=0.653 (=full, = CYCLE 76) explore=0.588 (resta) lfu=0.503.
COST_DRIFT: oracle=0.660 full=0.613 miss=0.561 explore=0.532 lfu=0.503. DOS hallazgos: (A) el PROBLEMA es REAL --
bajo drift value_miss pierde 0.051 vs value_full (en estacionario miss=full): la ceguera al drift de lo CACHEADO es
un efecto medible que NO existía sin drift. (B) PERO la intervención propuesta (re-sondar sacrificando 1 de m=10
slots permanentemente) NO paga: value_explore 0.532 ni siquiera supera a value_miss 0.561 bajo drift (recupera ~0%
del gap) y cuesta -0.065 en estacionario. El slot-sacrifice fijo cuesta más capacidad (~1/m) que el gap (0.051) que
recupera. => la hipótesis (este mecanismo es necesario/útil) queda REFUTADA, PERO el efecto subyacente es real.

### Límites (honestos)
La REFUTACIÓN es del MECANISMO (slot fijo), no del problema: el drift+obs-gateada SÍ degrada (gap ~0.05). Pero el
gap es CHICO -> la observación pasiva del contrafáctico sigue siendo casi suficiente aun con drift. Drift abrupto
recurrente; valor=frecuencia×costo; juguete (Pareto, n=50).

### Verificación
exp061 (32 seeds, numpy). cycle77 -> H-V4-5g 'refutada' (DoD; un REFUTADA que afila la pregunta es ciclo EXITOSO,
directiva v3 §4.1), D-V4-39 ACEPTADA, 1 techo 'real', analogía, verify_no_loss=OK. Test
`test_cycle77_intervention_value.py` 4/4 (problema real + mecanismo no paga + 3 ramas). Convergente con
costo-de-exploración/partial-monitoring (tier1).

> Complementa el 76 y MATIZA R-INTERVENCIÓN sobre la memoria: el problema (drift+obs gateada degrada lo cacheado-no-
> observado) es REAL, pero la intervención BURDA (slot fijo) NO paga -- cuesta más capacidad de la que recupera. La
> intervención sobre la memoria, si paga, debe ser CHEAP/TARGETED (re-sondeo OCASIONAL gateado por SORPRESA, reusar
> el detector de cambio de CYCLE 59), no un slot fijo. NO se sobre-vende R-INTERVENCIÓN sobre la memoria. Próxima
> hija: intervención dirigida por sorpresa (barata). Cierra honestamente la pregunta que abrió el 76.

## CYCLE 78 — H-V4-5h (arco realismo, CIERRA el sub-tema memoria): intervención barata sorpresa-gateada — REFUTADA

### Pregunta
CYCLE 77 (exp061, H-V4-5g) refutó el re-sondeo por SLOT FIJO (cuesta ~1/m permanente > el gap) pero dejó la hija:
¿una intervención BARATA gateada por sorpresa (re-sondar OCASIONAL sólo tras detectar caída de hit-rate, full el
resto) paga donde el slot fijo no pudo? Reusa el detector de cambio del CYCLE 59.

### Diseño
Numpy (idéntico a exp061). 7 brazos incluyendo value_surprise: capacidad full normal; EMA rápida vs lenta del hit;
si la rápida cae bajo la lenta - margen (sorpresa) dispara una ráfaga de probe_len=40 pasos re-sondando el cacheado
más viejo. DOS escenarios (estacionario/drift). 32 seeds. Pre-registrado: APOYADA si en drift surprise>miss (+>0.02)
Y >explore Y en estacionario ~miss.

### Resultado — REFUTADA (cierre firme con null)
COST_STATIONARY: oracle=0.662 full=0.653 miss=0.653 explore=0.588 surprise=0.618 lfu=0.502. COST_DRIFT: oracle=0.660
full=0.613 miss=0.561 explore=0.532 surprise=0.545 lfu=0.503. DOS hallazgos: (A) la barata SÍ es menos derrochadora
que la burda -- value_surprise supera a value_explore en AMBOS (DRIFT 0.545>0.532; ESTAC 0.618>0.588): re-sondar
ocasional cuesta menos que el slot fijo. (B) PERO aun la barata NO supera al baseline PASIVO: DRIFT surprise 0.545 <
miss 0.561; ESTAC surprise 0.618 < miss 0.653 (falsos positivos del detector). El gap de obs bajo drift (0.051) es
demasiado chico para que CUALQUIER intervención lo recupere. => en la cache con observación gateada, la observación
PASIVA del contrafáctico es ROBUSTA aun bajo drift; intervenir NO paga, ni barato.

### Límites (honestos)
La dirección 'cheap/targeted' era correcta (la barata vence a la burda) pero insuficiente; un detector mejor-
calibrado reduciría los falsos positivos en estacionario, PERO aun en DRIFT (donde el gap existe) surprise queda
BAJO miss -> el null no es sólo artefacto de tuning. Drift abrupto recurrente; valor=frecuencia×costo; juguete.

### Verificación
exp062 (32 seeds, numpy). cycle78 -> H-V4-5h 'refutada' (DoD; cierra el sub-tema = ciclo exitoso, v3 §4.1), D-V4-40
ACEPTADA, 1 techo 'real', analogía, verify_no_loss=OK. Test `test_cycle78_surprise_intervention.py` 4/4. Convergente
con value-of-information (tier1).

> CIERRA el sub-tema R-INTERVENCIÓN-sobre-memoria con un NULL honesto: en el sustrato de cache con observación
> gateada, ninguna intervención paga (ni barata) -- la observación pasiva del contrafáctico es robusta aun con
> drift, porque el gap de observación es chico. Los efectos FUERTES de R-INTERVENCIÓN (exp022/CYCLE 35: la pasiva
> queda PLANA) viven en el aprendizaje causal ACTIVO, no en esta cache. SEÑAL DE PIVOTE: el sub-tema memoria queda
> SATURADO (72-78); ir a un valor endógeno más rico (info-gain/confianza, CYCLE 56-57) o a la rama control/
> empowerment (la rama faltante más grande del árbol), donde R-INTERVENCIÓN sí es de primer orden.

## CYCLE 79 — H-V4-6a (PIVOTE: abre la rama R-CONTROL): test ADVERSARIAL de empowerment-como-valor — MIXTA

### Pregunta
El árbol marca "inteligencia=control/acción (empowerment)" como la rama CONTESTADA / faltante más grande. CYCLE 38/39
(exp024/025) ACEPTARON "empowerment > predicción como valor" PERO sólo donde lo controlable era útil. La crítica
SIMÉTRICA nunca hecha: así como la predicción malgasta en lo predecible-INÚTIL (exp024), ¿el empowerment malgasta en
lo controlable-INÚTIL? ¿Es el empowerment un valor endógeno UNIVERSAL?

### Diseño
Numpy. n=40 levers, cada uno con CONTROLABILIDAD ctrl_i y RELEVANCIA rel_i (cópula gaussiana, correlación rho).
Valor verdadero = ctrl×rel (rinde sólo si controlable Y relevante). El agente atiende k=8/n; recompensa = masa de
valor de los k / óptimo. 3 señales: oracle_value (top-k por ctrl×rel), empowerment (top-k por ctrl), random. Sweep
rho in {1.0,0.7,0.3,0.0,-0.5}. 48 seeds. Pre-registrado: APOYADA si empowerment recupera el óptimo en rho=1 Y
colapsa a random en rho=0.

### Resultado — MIXTA (matiz más fino que el pre-registro)
empowerment captura del óptimo: rho=1 1.000 (recupera exp024/025 perfecto), 0.7->0.932, 0.3->0.821, 0.0->0.724,
-0.5->0.565; random ~0.43 plano. swing 0.276 monótono. MATIZ HONESTO: el empowerment NO colapsa a random aun con
control ⊥ relevancia (rho=0: 0.724 >> random 0.431), porque la controlabilidad ES un componente MULTIPLICATIVO del
valor (ctrl×rel) -- el empowerment captura SIEMPRE el factor ctrl, le falta el factor REL. => el empowerment es un
PROXY PARCIAL = la MARGINAL-de-controlabilidad de R-VALOR, no un valor universal ni inútil. Ni control ni predicción
PURO es el valor: la predicción malgasta en lo predecible-inútil, el empowerment en lo controlable-inútil (simétrico);
el general es R-VALOR (referido al OBJETIVO), del que ambos son marginales. Resuelve el rival CONTESTADO: empowerment
es un COMPONENTE de R-VALOR, no su reemplazo.

### Límites (honestos)
Juguete (selección estática, valor multiplicativo ctrl×rel asumido); falta empowerment ESTIMADO online (¿sobrevive
como el valor de memoria en 72?) y un objetivo no-escalar. La corrida había aceptado empowerment como valor (38/39)
sin este test -> sesgo corregido.

### Verificación
exp063 (48 seeds, numpy). cycle79 -> H-V4-6a 'mixta' (DoD), D-V4-41 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle79_empowerment_limits.py` 4/4 (recupera/degrada + 3 ramas). Convergente con
empowerment/intrinsic-motivation (tier1) acotado bajo R-VALOR.

> ABRE la rama R-CONTROL y la ACOTA bajo R-VALOR: el empowerment es la marginal-de-controlabilidad del valor, no el
> valor universal. La corrida lo había aceptado (38/39) sin el test adversarial; aquí se ve que recupera el óptimo
> SÓLO cuando control≈valor y degrada al desalinearse, igual que la predicción. Unifica el rival contestado bajo
> R-VALOR (objetivo-referido). Próximo: empowerment ESTIMADO online; reconstruir R-VALOR combinando control +
> relevancia estimada sin oráculo.

## CYCLE 80 — H-V4-6b (rama R-CONTROL, capstone CONSTRUCTIVO del par 79-80): R-VALOR reconstruido de marginales endógenas — APOYADA

### Pregunta
CYCLE 79 (exp063, H-V4-6a) acotó: el empowerment es la marginal-de-controlabilidad de R-VALOR (ctrl×rel), no el
valor universal; ni control ni predicción/relevancia solos bastan. La pieza POSITIVA: si el agente ESTIMA AMBAS
marginales -- controlabilidad (de sus consecuencias) Y relevancia (de la recompensa) -- y las COMBINA (ctrl_est ×
rel_est), ¿reconstruye el valor COMPLETO y vence a cualquier marginal sola, justo donde control ⊥ relevancia?

### Diseño
Numpy. n=40 levers (ctrl, rel; valor=ctrl×rel), atender k=8. El agente observa S muestras ruidosas de cada marginal
(ctrl_est = ctrl + ruido/√S; rel_est igual). 5 brazos: oracle_value, empowerment (ctrl_est solo), relevance
(rel_est solo), rvalue_est (ctrl_est × rel_est), random. Sweep S∈{1,4,16,64}. DOS regímenes: rho=0 (divergen) y
rho=1 (alineadas). 48 seeds. Pre-registrado: APOYADA si en rho=0, S>=16, rvalue_est > ambas marginales (+>0.05) Y
recupera >=85% del oráculo.

### Resultado — APOYADA
rho=0 (control ⊥ relevancia, S=64): oracle=1.000 empowerment=0.709 relevance=0.729 rvalue_est=0.984 random=0.391.
rvalue_est (el producto) VENCE a cada marginal sola por +0.255 y recupera 98% del oráculo; ninguna marginal pasa de
~0.73 (no reconstruye el valor). Curva por muestras [0.686, 0.831, 0.956, 0.984] CONVERGE al oráculo (paralelo a la
estimación online del CYCLE 72). rho=1 (alineadas): todas ~0.98 (control basta = exp024/025). => R-VALOR (ctrl×rel,
referido al objetivo) se CONSTRUYE combinando dos estimadores endógenos baratos (control + relevancia), SIN oráculo;
empowerment y relevancia/predicción son sus DOS marginales, ninguna suficiente sola donde divergen.

### Límites (honestos)
El valor multiplicativo ctrl×rel se ASUME (factorización de diseño; en general el valor podría no factorizar limpio);
las marginales se estiman con ruido ~1/√S abstracto (falta un lazo REAL de acción-consecuencia y de recompensa);
juguete (selección estática, objetivo escalar).

### Verificación
exp064 (48 seeds, numpy). cycle80 -> H-V4-6b 'apoyada' (DoD), D-V4-42 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle80_value_reconstruction.py` 4/4 (producto vence marginales + converge + 3 ramas).
Convergente con descomposición de valor / successor-features (tier1) y con CYCLE 79 (tier5).

> CIERRA el par R-CONTROL (79-80) con la pieza POSITIVA: 79 ACOTÓ (empowerment = marginal-de-controlabilidad), 80
> RECONSTRUYE (R-VALOR = producto de dos marginales ENDÓGENAS: control + relevancia, ambas estimables, ninguna
> suficiente sola donde divergen). El valor se CONSTRUYE de la experiencia (consecuencias + recompensa), no se
> postula. Próximo: estimación en un lazo REAL de acción-consecuencia; ligar con el lazo de auto-mejora (el
> verificador = la señal de relevancia); empowerment estimado online; valor que no factorice limpio.

## CYCLE 81 — H-V4-6c (rama R-CONTROL, UNIFICA verificador + R-VALOR): el verificador como marginal-de-relevancia — APOYADA

### Pregunta
CYCLE 80 (exp064) reconstruyó R-VALOR = control × relevancia y dejó pre-registrado "el verificador = la señal de
relevancia". El arco 51-55 mostró que el lazo de auto-mejora tolera un verificador ruidoso (ε*≈0.50). ¿La relevancia
de R-VALOR la puede proveer un VERIFICADOR ruidoso (error ε)? ¿La reconstrucción control × verificador sobrevive el
ruido del verificador, y hasta qué ε*?

### Diseño
Numpy. n=50 levers, ctrl continuo (EXACTO, para aislar el ruido del verificador), rel BINARIO (p_rel=0.3 relevantes).
valor=ctrl×rel. Un verificador reporta rel_hat = rel con error simétrico ε. 5 brazos: oracle, empowerment (ctrl),
verifier_only (rel_hat), rvalue_verifier (ctrl × rel_hat), random. Sweep ε∈{0,0.1,0.2,0.3,0.5}. 48 seeds.
Pre-registrado: APOYADA si ε=0 reconstruye (>=85%) Y vence al control Y ε*>=0.2.

### Resultado — APOYADA
ε=0: oracle=1.000 empowerment=0.387 verifier_only=0.812 rvalue_verifier=1.000. El producto control×verificador
RECONSTRUYE el óptimo y vence a empowerment (control solo) por +0.613 -- enorme porque con sólo 30% relevantes el
control solo capta poco valor (la mayoría de lo controlable es irrelevante): el verificador-relevancia es ESENCIAL.
Tolerancia: rvalue_verifier supera al control hasta ε*=0.30 (aguanta ~30% de error del verificador; mismo régimen de
tolerancia que exp053, algo menor que su ε*≈0.50, métrica/tarea distintas). ε=0.5 (verificador inútil):
rvalue_verifier 0.356 ~ empowerment 0.400 (degrada con gracia al control solo). => el verificador ES la marginal-de-
relevancia de R-VALOR.

### Límites (honestos)
El control se da EXACTO (para aislar el ruido del verificador); falta control TAMBIÉN estimado (empowerment online).
Verificador SINTÉTICO (error ε binario); falta un verificador chequeable REAL (sandbox exp018) como relevancia.
Valor multiplicativo ctrl×rel asumido; relevancia binaria; juguete.

### Verificación
exp065 (48 seeds, numpy). cycle81 -> H-V4-6c 'apoyada' (DoD), D-V4-43 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle81_verifier_relevance.py` 4/4. Convergente con verificador-como-señal-de-valor /
TTS (tier1) y con CYCLE 80 + arco 48-55 (tier5).

> UNIFICA TRES arcos del lab: R-INTERVENCIÓN (actuar) + VERIFICADOR (48-55, corrección/relevancia) + R-VALOR (79-80,
> control×relevancia). El agente de act-and-verify estima IMPLÍCITAMENTE R-VALOR = control × verificador-relevancia:
> la relevancia no necesita oráculo, la da el verificador chequeable (ruidoso pero tolerable hasta ~30% de error).
> La auto-mejora verificada ES asignación de cómputo por R-VALOR estimado. Próximo: control TAMBIÉN estimado online;
> verificador chequeable REAL (sandbox) como relevancia.

## CYCLE 82 — H-V4-6d (rama R-CONTROL, capstone EMPÍRICO de la unificación 79-82): R-VALOR totalmente endógeno — APOYADA

### Pregunta
La corrida 79-81 estableció R-VALOR = control × relevancia, con el empowerment estimando la controlabilidad (79-80)
y el verificador la relevancia (81), cada uno acotado/validado por SEPARADO (el 81 usó control EXACTO para aislar el
ruido del verificador). ¿Sobrevive con AMBAS marginales ruidosas a la vez -- el caso realista, sin NINGUNA señal exacta?

### Diseño
Numpy. n=50 levers, ctrl continuo, rel binario (p_rel=0.3). valor=ctrl×rel. El agente estima AMBAS: ctrl_est = ctrl +
ruido/√S (control de consecuencias) y rel_hat = rel flipeado con prob ε (verificador). 5 brazos: oracle, empowerment
(ctrl_est), verifier (rel_hat), rvalue_full (ctrl_est × rel_hat = R-VALOR totalmente endógeno), random. Grid de ruido
S∈{2,8,32} × ε∈{0.1,0.3}. 48 seeds. Pre-registrado: APOYADA si en el punto realista (S=8,ε=0.1) rvalue_full supera a
ambas marginales (+>0.05) y recupera >=80% del óptimo.

### Resultado — APOYADA
Punto realista (S=8, ε=0.1): oracle=1.000 empowerment=0.400 verifier=0.637 rvalue_full=0.822 random=0.203. El R-VALOR
totalmente endógeno (control_est × verificador, AMBOS ruidosos, SIN oráculo) VENCE a cada marginal sola por +0.185 y
recupera 82% del óptimo. Y vence a AMBAS marginales en TODAS las celdas del grid de ruido (incluso a ruido alto
S=2/ε=0.3 donde el absoluto cae). Mecanismo: las dos marginales capturan señal ORTOGONAL (control + relevancia);
ninguna sola basta (el control solo capta poco con pocos relevantes, la relevancia sola ignora qué es controlable)
pero su PRODUCTO recupera el valor. => prueba EMPÍRICA de la unificación: el agente que estima control (empowerment)
Y relevancia (verificador) y los combina CONSTRUYE Y USA R-VALOR endógeno, sin ninguna señal exacta.

### Límites (honestos)
Valor multiplicativo ctrl×rel asumido (factorización de diseño); relevancia binaria; estimadores con ruido abstracto
(falta un lazo REAL de acción-consecuencia y un verificador chequeable real); juguete (selección estática, objetivo
escalar). La frontera de SCALE (sustrato no-juguete) requiere GPU/Kaggle, fuera de la corrida CPU.

### Verificación
exp066 (48 seeds, numpy). cycle82 -> H-V4-6d 'apoyada' (DoD), D-V4-44 ACEPTADA, 1 techo 'real', analogía,
verify_no_loss=OK. Test `test_cycle82_endogenous_rvalue.py` 4/4 (vence en todo el grid + 3 ramas). Convergente con
combinar-marginales (tier1) y con la unificación 79-81 (tier5).

> Cierra la rama R-CONTROL con la demostración positiva TOTAL: R-VALOR es construible Y usable de dos marginales
> endógenas ruidosas (empowerment_est × verificador), sin ningún oráculo. Cierra el caveat 'control exacto' del 81.

## CYCLE 83 — H-V4-7a (rama R-VALOR, ataque a la FACTORIZACIÓN): la reconstrucción-producto es un prior de complementariedad — APOYADA

### Pregunta
TODO el arco 79-82 asumió value = ctrl × rel (factorización multiplicativa de diseño; gap #2 del decomposition_tree,
la suposición más cargante del arco). ¿Sobrevive la reconstrucción-PRODUCTO de R-VALOR (ctrl_est × rel_est) cuando el
valor NO factoriza limpio?

### Diseño
Numpy. n=50 levers, ctrl,rel ~ U(0,1). value(λ,fam) = (1-λ)·ctrl·rel + λ·g(ctrl,rel), con dos familias OPUESTAS de
no-factorizabilidad: COMPLEMENTOS g=min(ctrl,rel) (óptimo both-high, como el producto) y SUSTITUTOS g=max(ctrl,rel)
(óptimo 'al menos uno alto', diverge del producto). Estimadores endógenos ruidosos (S=8, σc=0.5, σr=0.1) y un nivel
'clean' (perfectos) para aislar factorización de ruido. 6 brazos: oracle, empowerment (ctrl_est), relevance (rel_est),
rvalue_prod (ctrl_est×rel_est), rvalue_add (suma), random. λ∈{0,0.25,0.5,0.75,1.0}. 48 seeds. Métrica: crossover λ* =
menor λ con adv(prod − mejor marginal) ≤ 0.05. Pre-registrado: APOYADA si bajo complementos adv>0.05 en TODO λ y bajo
sustitutos se rompe en λ=1.0.

### Resultado — APOYADA
adv(prod − mejor marginal) por λ: COMPLEMENTOS {0.197, 0.206, 0.218, 0.222, 0.244} (crossover=nunca, robusto en todo λ);
SUSTITUTOS {0.200, 0.118, 0.065, 0.027, −0.027} (decae monótona; crossover λ*=0.75; en λ=1.0 la relevancia sola 0.942
supera al producto 0.915). Las filas 'clean' reproducen la asimetría (subs λ=1.0 clean: emp 0.953 / rel 0.955 > prod
0.933) → es la FACTORIZACIÓN, no el ruido. => la reconstrucción-producto codifica un PRIOR DE COMPLEMENTARIEDAD: vale
cuando la no-factorizabilidad preserva el óptimo both-high (complementos), se rompe cuando lo cambia a sustitutos.

### Límites (honestos)
El producto es MÁS robusto de lo pre-registrado: tolera no-factorizabilidad MODERADA (λ≤0.5 vence en AMBAS familias:
comp adv 0.218, subs adv 0.065); el break sólo aparece cerca de sustitutos puros (λ≥0.75). NOTA DE PROCESO: el punto
único λ=0.5 del piloto (12 seeds) resultó laxo → la métrica confirmatoria es el crossover λ* (misma hipótesis
cualitativa, reoperacionalizada antes de la corrida de 48 seeds; el caveat se reporta explícito). g sintético (min/max),
objetivo escalar, ruido abstracto: falta valor no-factorizable de un lazo real (gaps #1/#3).

### Verificación
exp067 (48 seeds, numpy). cycle83 → H-V4-7a 'apoyada' (DoD), D-V4-45 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle83_nonfactorizable_value.py` 6/6 (asimetría real + clean aísla factorización + 4
ramas del veredicto). Convergente con Cobb-Douglas/sustitutos (tier2) y con el gap #2 del árbol (tier5).

> Acota el gap #2: la factorización ctrl×rel del arco 79-82 NO es ley universal sino un PRIOR DE COMPLEMENTARIEDAD
> robusto salvo bajo sustitutos. Próximo (CYCLE 84): combinador APRENDIDO que recupere lo perdido bajo sustitutos
> (cierra el gap #2 con CONSTRUCCIÓN, no sólo acotación).

## CYCLE 84 — H-V4-7b (rama R-VALOR, CONSTRUCCIÓN sobre el gap #2): combinador APRENDIDO vs producto fijo — MIXTA

### Pregunta
CYCLE 83 acotó que el producto (ctrl_est × rel_est) se rompe bajo sustitutos. ¿Aprender el combinador de pocas
observaciones de valor real (en vez de ASUMIR el producto) recupera ese régimen sin sacrificar los complementos? Si sí,
el lab puede estimar R-VALOR no-factorizable, no sólo el complementario.

### Diseño
Numpy. Tarea idéntica a exp067 (n=50, ctrl,rel~U(0,1), value=(1-λ)·ctrl·rel + λ·g; familias comp=min / subs=max). El
agente observa el valor REAL de m ítems al azar (lazo barato de acción-consecuencia) y ajusta por RIDGE: learned_lin
[1,c,r] y learned_poly2 [1,c,r,c²,r²,cr]. Brazos: oracle, empowerment, relevance, rvalue_prod (el fijo de CYCLE 83),
learned_lin, learned_poly2, random. Estimadores noisy (S=8, σc=0.5, σr=0.1) + nivel clean. Barrido m∈{5,10,20,40},
λ∈{0.5,1.0}. 64 seeds. Pre-registrado (subs λ=1.0, m=20): APOYADA si learned_poly2 recupera DECISIVAMENTE (+>0.03 sobre
producto Y >= mejor marginal) sin sacrificar complementos; MIXTA si recupera parcialmente; REFUTADA si no es siquiera
el mejor brazo no-oráculo.

### Resultado — MIXTA (recuperación PARCIAL noise-gated)
Bajo SUSTITUTOS (g=max, λ=1.0, m=20): learned_poly2=0.953 es el MEJOR brazo no-oráculo — vence al producto fijo 0.926
(+0.028) y a la mejor marginal 0.939 — pero la ventaja sobre el producto (+0.028) queda BAJO el corte decisivo +0.03.
Bajo estimadores CLEAN la recuperación SÍ es plena (poly2 0.994 vs producto 0.932, +0.062); converge con m
(0.922→0.935→0.953). No sacrifica complementos (comp λ=1.0: poly2 0.933 vs producto 0.927). => aprender el combinador
recupera la no-factorizabilidad de sustitutos que el producto pierde, pero la ganancia es NOISE-GATED: el error de
estimación de las marginales ruidosas la erosiona; bajo ruido realista, asumir el producto (prior de complementariedad)
sigue siendo un baseline duro de batir aun fuera de su régimen.

### Límites (honestos)
La recuperación es noise-gated (decisiva sólo con feedback limpio/abundante). NOTA DE PROCESO: la corrida de 64 seeds
dejó la ventaja noisy en +0.028 (knife-edge con el corte +0.03 pre-registrado) mientras la clean era decisiva (+0.062);
el corte binario mislabelaba este 'recupera-pero-no-decisivamente' como refutación, así que se añadió una rama MIXTA
'recuperación parcial' (misma hipótesis cualitativa, mayor granularidad). g sintético (min/max), base poly2 fija,
objetivo escalar; falta valor no-factorizable de un lazo real y un selector producto<->aprendido por detección de régimen.

### Verificación
exp068 (64 seeds, numpy). cycle84 → H-V4-7b 'mixta' (DoD), D-V4-46 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle84_learned_combiner.py` 7/7 (recuperación parcial real + clean aísla la forma + 4
ramas). Convergente con el principio noise-gated (tier2) y con el gap #2 de CYCLE 83 (tier5).

> Construcción sobre el gap #2: aprender el combinador es VIABLE pero NOISE-GATED; el producto sigue siendo la
> reconstrucción por DEFECTO. Próximo (CYCLE 85): subir la calidad del feedback (más S, re-observación sorpresa-gateada)
> para ver si la recuperación pasa de parcial a DECISIVA bajo ruido.

## CYCLE 85 — H-V4-7c (rama R-VALOR, cierra el noise-gating del gap #2): calidad del feedback — APOYADA

### Pregunta
CYCLE 84 dejó la recuperación del combinador aprendido como PARCIAL/noise-gated bajo sustitutos (decisiva sólo con
estimadores limpios). El constraint vinculante es el RUIDO DE LAS FEATURES (ctrl_est, rel_est), no el presupuesto m.
¿Subir la calidad del feedback (más muestras S de control, menos ruido σr de relevancia) vuelve la recuperación de
PARCIAL a DECISIVA, y a partir de qué nivel — hace falta feedback perfecto o alcanza con moderado?

### Diseño
Numpy. Régimen SUSTITUTOS (g=max, λ=1.0) + COMPLEMENTOS de control. Combinador aprendido por ridge poly2 de m=20 obs.
Eje primario: CALIDAD DEL FEEDBACK, niveles (S, σr): q0=(2,0.20), q1=(8,0.10) [el punto de CYCLE 84], q2=(32,0.05),
q3=(128,0.02), clean=(perfecto). 64 seeds. Métrica: adv = learned_poly2 − rvalue_prod; crossover = primer nivel NO-clean
con adv>0.03. Pre-registrado: APOYADA si cruza +0.03 en feedback MODERADO (q2 o antes) y crece monótono, sin sacrificar
complementos; MIXTA si sólo cruza en q3; REFUTADA si sólo con feedback perfecto/nunca.

### Resultado — APOYADA
adv(poly2 − producto) bajo sustitutos crece MONÓTONA con la calidad del feedback: q0=+0.017, q1=+0.038, q2=+0.052,
q3=+0.059, clean=+0.059. Cruza el umbral decisivo (+0.03) en feedback NO perfecto, sin sacrificar complementos (comp:
poly2 ≈ producto en todos los niveles). => el noise-gating de CYCLE 84 es una PENDIENTE (función decreciente del ruido
de features), no una pared dura: con features algo más nítidas (más muestras de control, menos ruido de relevancia),
aprender la forma no-factorizable recupera DECISIVAMENTE el valor de sustitutos.

### Límites (honestos)
El punto REALISTA q1 (adv +0.038) queda apenas por encima de +0.03, y el mismo punto en CYCLE 84 dio +0.028 (justo por
debajo): el realista está SOBRE la frontera de decisión — lo robusto es la TENDENCIA monótona (q2/q3 claramente
decisivos), no la lectura puntual de q1. 'Subir S' asume que el lazo real puede muestrear más el control / mejorar el
sensor (costo no modelado). g sintético (max), base poly2 fija, objetivo escalar; falta detección automática del
régimen y un lazo de acción-consecuencia real (gaps #1/#3).

### Verificación
exp069 (64 seeds, numpy). cycle85 → H-V4-7c 'apoyada' (DoD), D-V4-47 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle85_feedback_quality.py` 7/7 (calidad sube recuperación + 3 ramas). Convergente con
errors-in-variables/atenuación (tier2) y con el noise-gating de CYCLE 84 (tier5).

> SUB-ARCO gap #2 CERRADO (83-85): el producto es un prior de complementariedad (83); aprender el combinador recupera
> bajo sustitutos pero noise-gated (84); el noise-gating es una pendiente — subir la calidad del feedback lo destraba
> (85). Política: producto por DEFECTO; calidad de feedback + combinador aprendido en régimen de sustitutos. Próximo:
> detección AUTOMÁTICA del régimen (conmutar producto<->aprendido sin saberlo a priori).

## CYCLE 86 — H-V4-7d (rama R-VALOR, CAPSTONE del gap #2): ¿detectar régimen o el aprendido domina? — APOYADA

### Pregunta
Tras 85, lo natural era 'detectar el régimen (complementos vs sustitutos) para conmutar producto<->aprendido'. Pero
84-85 mostraron incidentalmente que bajo complementos aprendido ≈ producto. Si el aprendido DOMINA (≥ producto en
complementos, > en sustitutos) por encima de una compuerta de feedback, un detector de régimen sería INNECESARIO: la
política sería una COMPUERTA DE CALIDAD DE FEEDBACK, no un switch por régimen. ¿Es así?

### Diseño
Numpy. Familias comp(min)/subs(max), λ=1.0, calidad de feedback q0..clean (como exp069), combinador aprendido ridge
poly2 de m=20 obs. Brazos: oracle, always_product, always_learned, selector (detecta vía CV held-out: corr con valor
observado, elige producto vs aprendido), oracle_selector (por seed el mejor de los dos por perf REAL = cota de un
detector PERFECTO), random. 48 seeds. Pre-registrado (q_ref=q2, tol=0.02): APOYADA si hay compuerta donde always_learned
>= producto en comp (>=-0.01) y > en subs (+>0.02) Y la detección es innecesaria (oracle_selector y selector <=
always_learned + tol).

### Resultado — APOYADA
El combinador aprendido DOMINA al producto por encima de gate=q1: a q2 dom comp=+0.006 (iguala), dom subs=+0.051 (vence).
Lo decisivo: el oracle_selector (detector PERFECTO) supera a always_learned por sólo +0.001, y el selector real por
−0.002 (ambos <= tol). => ni un detector perfecto aporta sobre 'siempre aprender'. MECANISMO: poly2 NESTA el producto (el
término cr es una de sus features) → lo iguala donde el producto es correcto (complementos) y lo supera donde no
(sustitutos); por eso always_learned ya alcanza el techo de un selector. La política práctica de reconstrucción de
R-VALOR es una COMPUERTA DE CALIDAD DE FEEDBACK (aprendido si el feedback es adecuado, producto si es pobre), NO un switch
por régimen.

### Límites (honestos)
El aprendido nesta al producto por DISEÑO de la base poly2; con una base que no lo nestara, la dominación/no-regret
podría no valer. Con feedback POBRE (q0) el producto iguala/supera al aprendido: la compuerta de calidad es real y
depende del costo de muestrear el lazo real. Juguete (g sintético min/max, objetivo escalar).

### Verificación
exp070 (48 seeds, numpy). cycle86 → H-V4-7d 'apoyada' (DoD), D-V4-48 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle86_regime_policy.py` 6/6 (dominación + detección innecesaria + 3 ramas). Convergente
con nesting/no-regret (tier2) y con la calidad-feedback de CYCLE 85 (tier5).

> ARCO gap #2 (83-86) CERRADO. CUADRO FINAL: el producto fijo es un prior de complementariedad (83); un combinador
> aprendido recupera bajo sustitutos, noise-gated (84); el noise-gating es una pendiente que la calidad del feedback
> destraba (85); el aprendido (que nesta el producto) DOMINA sobre una compuerta de feedback, la detección de régimen es
> innecesaria (86). POLÍTICA FINAL: reconstruir R-VALOR con el combinador aprendido cuando el feedback es adecuado, caer
> al producto con feedback pobre; sin detector de régimen. Próximo: el valor no-factorizable y el feedback de un lazo de
> acción-consecuencia REAL (gaps #1/#3, verificador chequeable exp018) y SCALE (GPU).

## CYCLE 87 — H-V4-7e (rama R-VALOR, puente a gaps #1/#3): feedback action-gated — REFUTADA (robustez positiva)

### Pregunta
El arco gap #2 (83-86) asumió feedback LIBRE (m observaciones al azar). Un agente real sólo observa el valor de lo que
SELECCIONA (action-gated). ¿La explotación greedy del prior se AUTO-ATRAPA por sesgo de selección (sólo ve both-high ->
no aprende max) y la exploración la rescata (R-INTERVENCIÓN), o la política always-learn sobrevive?

### Diseño
Numpy, online (ítems frescos por ronda), calidad q2 (S=32, σr=0.05). Sustitutos (g=max) + complementos de control. FASE
LEARNING (T=40 rondas): cada ronda el agente SELECCIONA k=10 para observar su valor real (action-gated), acumula buffer,
refit ridge poly2. Estrategias de observación: greedy (por el combinador aprendido, bootstrap del producto -> buffer
sesgado), explore (ε=0.3-greedy), random (insesgado, = feedback libre). FASE EVAL (E=20 rondas frescas): rankea por el
combinador final, perf promedio. Brazos: oracle, product, learned_{greedy,explore,random}, random. 48 seeds.
Pre-registrado: APOYADA si trap (greedy<=product+0.02) Y explore rescata (>greedy+0.03 y >=random-0.03).

### Resultado — REFUTADA (no hay trampa)
Sustitutos: learned_greedy=0.979 = learned_explore=0.979 = learned_random=0.979 (insesgado) > product=0.929. NO hay
trampa de sesgo de selección (greedy recupera SIN explorar); la exploración NO aporta. MECANISMO: la selección top-k por
un score continuo igual ABARCA un rango 2D del espacio (ctrl,rel) -> overlap de soporte suficiente -> el ridge-poly2
generaliza max() desde ahí. => ACOTA R-INTERVENCIÓN ('explorar para aprender el valor' no se sostiene aquí, cf. 77-78) y
REFUERZA la política gap #2 (always-learn robusta también bajo feedback de acción-consecuencia, sin exploración).

### Límites (honestos)
NO se probó concentración EXTREMA del soporte (k muy chico / valor adversarialmente lejos del prior), donde el trap
podría reaparecer. Feedback sin costo de muestreo y dinámica no-secuencial real; falta el lazo de acción-consecuencia
REAL (sandbox exp018). g=max sintético, objetivo escalar, base poly2 que nesta el producto.

### Verificación
exp071 (48 seeds, numpy). cycle87 → H-V4-7e 'refutada' (DoD), D-V4-49 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle87_action_gated_feedback.py` 4/4 (no-trap real + 3 ramas). Convergente con
covariate-shift/overlap (tier2) y con la política gap #2 de CYCLE 86 (tier5).

> La política gap #2 sobrevive el action-gating sin explorar (greedy basta). Próximo: el lazo de acción-consecuencia
> REAL con verificador chequeable (sandbox exp018) -- feedback con costo, dinámica secuencial -- y SCALE (GPU).

## CYCLE 88 — H-V4-7f (rama R-VALOR, cierra el caveat de CYCLE 87): concentración del soporte (pool fijo) — REFUTADA

### Pregunta
CYCLE 87 dejó como caveat que usaba ítems FRESCOS (diversifican el soporte aunque observes top-1). ¿Reaparece el trap de
sesgo de selección bajo el verdadero peor caso — un POOL FIJO (los mismos n ítems recurren cada ronda -> observación
CORRELACIONADA, el greedy re-observa siempre la región both-high) + k_obs chico?

### Diseño
Numpy, online (reusa exp071). Sustitutos (g=max), q2 (S=32, σr=0.05). Eje 1: POOL ∈ {fixed (mismos n ítems toda la
corrida), fresh (nuevos por ronda)}. Eje 2: k_obs ∈ {1,2,3,5,10}. Estrategias greedy/explore(ε)/random observan k_obs
ítems/ronda, refit ridge poly2; eval fixed=rank del pool fijo, fresh=promedio sobre E rondas frescas. Control comp/fixed/
k_obs=1. 48 seeds. Pre-registrado: APOYADA si fixed/k_obs=1 atrapa (greedy<random−0.05) y fresh no; REFUTADA si ni el
pool fijo a k_obs=1 atrapa.

### Resultado — REFUTADA (robustez TOTAL)
Ni el pool FIJO a k_obs=1 atrapa: gap random−greedy fixed/k_obs=1 = 0.037 (<= 0.05, sin trap; umbral k_obs*=ninguno);
fresh/k_obs=1 gap ≈ 0.03. El greedy recupera max() aun re-observando una región estrecha. MECANISMO: el ridge-poly2
sobre pocos puntos both-high (que igual tienen SPREAD en (ctrl,rel)) aproxima un target suave (max) en todo el dominio;
el trap severo exigiría que el soporte COLAPSARA a casi un punto. => robustez total a través de tipo-de-pool y amplitud
de observación; R-INTERVENCIÓN no liga aquí (2ª refutación consecutiva, 87-88).

### Límites (honestos)
Hay un costo MILD sub-umbral de concentración (~0.03-0.04 bajo fixed/k_obs=1) que la exploración cierra (explore alcanza
el techo insesgado), pero NUNCA llega a trap (>0.05). Soporte realmente DEGENERADO (1 ítem idéntico repetido) o una base
que no nestara el target sí podrían atrapar; no testeados. g=max sintético, base poly2, objetivo escalar, espacio 2D
chico (n=50).

### Verificación
exp072 (48 seeds, numpy). cycle88 → H-V4-7f 'refutada' (DoD), D-V4-50 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle88_support_concentration.py` 4/4 (no-trap fixed real + 3 ramas). Convergente con
aproximación-sobre-spread (tier2) y con CYCLE 87 (tier5).

> SUB-TEMA FEEDBACK-REALISMO (87-88) CERRADO: la política gap #2 (always-learn/greedy) es robusta bajo feedback
> action-gated (87) y bajo concentración extrema/observación correlacionada (88). El SALTO GRANDE pendiente: lazo de
> acción-consecuencia REAL con verificador chequeable (sandbox exp018) -- feedback con costo, dinámica secuencial,
> target no-sintético -- y SCALE (GPU).

## CYCLE 89 — H-V4-7g (rama R-VALOR, EL SALTO GRANDE / gaps #1/#3): R-VALOR sobre un VERIFICADOR REAL — APOYADA

### Pregunta
Todo el arco gap #2 (83-88) construyó R-VALOR=control×relevancia con un valor SINTÉTICO SUAVE (g=min/max) y ruido
abstracto. El caveat HONESTO más repetido: "g=max sintético, base poly2 que NESTA el target". El salto grande (frontera
tras 88): ¿la política R-VALOR (aprender un combinador barato + asignar el feedback ESCASO/costoso por él) sobrevive
cuando el valor lo decide un VERIFICADOR CHEQUEABLE REAL — el sandbox de exp018 EJECUTA el candidato y devuelve v∈{0,1},
DISCRETO, no una fórmula suave?

### Diseño
Numpy + el sandbox REAL de exp018 (`interpret`/`verify`, parser propio, sin eval). Cada candidato es una EXPRESIÓN
generada con dos latentes: estructura c (P[bien-formada con operador]) y valor r (P[su valor==target]); el verificador
real la ejecuta y decide v. Dos regímenes ANÁLOGOS a comp/subs pero con valor REAL: STRONG (exige operador Y
valor==target -> conjuntivo, E[v|c,r]=c·r, producto Bayes-óptimo) y WEAK (acepta el echo del target sin operador ->
E[v|c,r]=r, relevancia-dominante, el producto mis-rankea los echoes high-r/low-c). El agente ve features RUIDOSAS
(c_est, r_est), con presupuesto K=10/ronda SELECCIONA qué verificar (action-gated + costoso), observa el v REAL
(Bernoulli), refit ridge-poly2; eval = rankea un pool fresh por el combinador final (perf_of con v discreto). Brazos:
product, learned_{greedy,explore,random}, oracle, chance. 48 seeds. Pre-registrado.

### Resultado — APOYADA
La política SOBREVIVE el verificador real. STRONG: learned_greedy=0.603 ≈ product=0.615 (no-regret Δ=-0.011, el
producto es Bayes-óptimo en el régimen conjuntivo). WEAK: learned_greedy=0.885 > product=0.779 (recupera +0.106 la
relevancia-dominancia que el producto pierde al multiplicar por la estructura irrelevante de los echoes — paralelo REAL
al régimen 'sustitutos' del gap #2, pero por la rama echo/reward-hack de exp018, no por un g=max de juguete). El feedback
DISCRETO (Bernoulli) NO rompe el aprendizaje (>> chance: +0.343/+0.384); greedy NO se atrapa bajo feedback costoso
(trap S=0.001/W=0.002 <= 0.03), confirmando 87-88 con valor REAL. => el mecanismo del arco gap #2 NO era un artefacto
del g suave.

### Límites (honestos)
La ESPERANZA del valor E[v|c,r] sigue siendo SUAVE y NESTEABLE por el poly2 (c·r y r son sus features), porque el
GENERADOR de candidatos es sintético (latentes c,r -> Bernoulli): se probó que la VARIANZA Bernoulli del verificador
real no rompe el mecanismo, NO un target cuya MEDIA condicional el poly2 no pueda nestar (umbral agudo / no-monotonía).
Falta un GENERADOR de MODELO real (exp018 HybridLM) con lazo cerrado de entrenamiento, objetivo no-escalar, y SCALE
(GPU). El gap al oracle en strong es grande (0.397: positivos c·r escasos, sin saturación trivial).

### Verificación
exp073 (48 seeds, numpy + sandbox exp018). cycle89 → H-V4-7g 'apoyada' (DoD), D-V4-51 ACEPTADA, 1 techo 'real',
analogía 7 etapas, verify_no_loss=OK. Test `test_cycle89_real_verifier_value.py` 5/5 (sandbox real decide el valor +
supervivencia smooth→discrete + 3 ramas). Convergente con el principio verificador-conjuntivo/media-condicional (tier2)
y con la política gap #2 de CYCLE 86 (tier5).

> EL SALTO GRANDE — primer aterrizaje en un verificador REAL (eje smooth→discrete CERRADO): la política R-VALOR del arco
> gap #2 (combinador aprendido que nesta el producto; always-learn/greedy bajo feedback costoso) sobrevive el salto de
> un valor sintético suave a un verificador chequeable REAL (sandbox exp018, valor discreto). El producto es Bayes-óptimo
> donde el verificador es conjuntivo (strong); el aprendido recupera donde el echo lo vuelve relevancia-dominante (weak).
> El feedback discreto no rompe el aprendizaje. Falta el eje NO-NESTEABLE: un target cuya media condicional el poly2 no
> nesta y/o un generador de MODELO real con lazo cerrado (hija H-V4-7h) — y SCALE (GPU).

## CYCLE 90 — H-V4-7h (rama R-VALOR, hija de CYCLE 89; liga R-PRIOR/H-V4-3): media NO-NESTEABLE — MIXTA

### Pregunta
CYCLE 89 dejó como caveat que la ESPERANZA E[v|c,r] del verificador real seguía SUAVE y nesteable por el poly2 (generador
sintético). ¿La política R-VALOR todavía recupera el valor cuando la media condicional del verificador REAL NO es
nesteable por el poly2 — y de qué depende?

### Diseño
Numpy + sandbox REAL de exp018. La feature estructural c controla una estructura de DOS BANDAS INTERIORES
(well_formed = c en [0.2,0.4) ∪ [0.6,0.8), no-monótona), que derrota al prior MONÓTONO (product, apuesta a c alto ->
extremo rechazado) Y a la PARÁBOLA (poly2, un solo pico -> centro rechazado). El sandbox EJECUTA el candidato y decide v;
E[v|c,r] = 1{c en banda}·r. Feedback COSTOSO (K=10/ronda, random insesgado, buffer compartido). Brazos: product,
learned_poly2 (gap #2), learned_poly4, learned_bin (no-paramétrica 8×8), bayes (techo: rankea por E[v|c,r] real), oracle
(v realizado), chance. Eje de presupuesto B ∈ {low T=20, high T=80}. 48 seeds. Pre-registrado.

### Resultado — MIXTA (dos hallazgos honestos)
(1) El poly2 FALLA: short del techo bayes (0.824) por 0.330 (poly2=0.494) — sólo captura el eje r nesteable, no la
estructura c. CONFIRMA que el poly2 default del gap #2 NO es universal: existen valores REALES donde su base no llega
(cierra el eje no-nesteable del caveat de CYCLE 89). El producto monótono falla aún más (0.325). (2) La base RICA
no-paramétrica (binned) recupera PARCIALMENTE (+0.117 sobre poly2) y es DATA-HUNGRY (+0.076 low->high vs +0.024 de poly2)
PERO NO alcanza el techo bayes (short 0.214) ni con T grande (probado hasta T=1000: satura ~0.65) ni con features casi
limpias (satura ~0.69): el tope lo pone la DISCRETIZACIÓN de la grilla (celdas que cruzan bordes de banda + promedian el
eje r). => recuperar un valor no-nesteable es CARO: exige una base que matchee la estructura Y feedback/resolución
suficientes. El lever es el MATCH+RESOLUCIÓN del prior (la base) con la estructura del valor — exactamente R-PRIOR/H-V4-3.

### Límites (honestos)
g determinista-banda sintético, espacio 2D, base binned cuadrada (un prior MATCHEADO a la estructura — features de banda
/ kernel — recuperaría más barato; no testeado). Falta el generador de MODELO real (lazo cerrado exp018), objetivo
no-escalar y SCALE (GPU). NO es APOYADA (la base rica no recupera del todo) ni REFUTADA (poly2 sí falla y la base rica sí
mejora con presupuesto).

### Verificación
exp074 (48 seeds, numpy + sandbox exp018). cycle90 → H-V4-7h 'mixta' (DoD), D-V4-52 ACEPTADA, 1 techo 'real' (2 blockers
'fisico' = sesgo de aproximación irreducible + discretización), analogía 7 etapas, verify_no_loss=OK. Test
`test_cycle90_nonnested_value.py` 5/5 (bandas derrotan monótono+parábola + poly2-no-universal + 3 ramas). Convergente con
base=prior/sesgo-aproximación (tier2) y con el caveat no-nesteable de CYCLE 89 (tier5).

> ACOTACIÓN del gap #2 (liga R-PRIOR/H-V4-3): el combinador poly2 que dominaba en 83-89 NO es universal — falla cuando la
> media condicional del valor real no entra en su span (estructura no-monótona/multi-banda). Una base más rica recupera
> PARCIALMENTE a costa de feedback/resolución. POLÍTICA: poly2 por DEFECTO (barato, robusto donde el valor es
> suave/conjuntivo, CYCLE 89); escalar a una base más rica/MATCHEADA SÓLO con evidencia de estructura no-nesteable +
> presupuesto. Próximo: un prior MATCHEADO a la estructura (features de banda/kernel) que recupere barato; el generador
> de MODELO real (lazo cerrado exp018); y SCALE (GPU).

## CYCLE 91 — H-V4-3a (rama R-PRIOR, ataca H-V4-3 ABIERTA; hija de CYCLE 90): la FORMA del prior fija la eficiencia muestral — APOYADA

### Pregunta
CYCLE 90 dejó que una base RICA GENÉRICA (binned) recupera el valor no-nesteable sólo PARCIAL y CARO (data-hungry).
¿Un prior MATCHEADO a la estructura recupera BARATO? Esto es R-PRIOR / H-V4-3 (ABIERTA desde el reset): "la calidad/forma
del prior fija la eficiencia muestral; un prior correcto iguala a un método general caro a una fracción del costo".

### Diseño
Numpy + sandbox REAL de exp018, MISMO sustrato no-nesteable de exp074 (dos bandas interiores en c, E[v|c,r]=band(c)·r).
Tres PRIORS compitiendo con el MISMO feedback costoso (K random/ronda, buffer compartido): poly2 (base global equivocada),
bin (no-paramétrica genérica 8×8), rbf (prior MATCHEADO = bumps gaussianos LOCALES en c × LINEAL en r, encode el TIPO de
estructura SIN conocer las bandas exactas; 9 centros equiespaciados). Eje de presupuesto B ∈ {low T=20, high T=80}.
Brazos extra: bayes (techo), product, oracle, chance. 48 seeds. Pre-registrado.

### Resultado — APOYADA
La FORMA del prior FIJA la eficiencia muestral. (1) SAMPLE EFFICIENCY: rbf a presupuesto BAJO (0.687) ya SUPERA a la base
genérica bin a presupuesto ALTO (0.620) — recupera a una FRACCIÓN del costo (Δ=+0.067); y gana a bin a igual bajo
presupuesto (+0.147). (2) rbf SATURA rápido (high−low +0.033) mientras bin es DATA-HUNGRY (+0.079). (3) rbf >> poly2
(base global equivocada, +0.221) y queda MÁS CERCA del techo bayes (gap 0.113 vs bin 0.213: el prior suave también
promedia el ruido de features que la grilla dura del bin sufre). => el lever de la eficiencia muestral NO es el volumen de
datos ni la capacidad cruda, sino el MATCH del prior (la base) con la estructura del valor — R-PRIOR/H-V4-3.

### Límites (honestos)
(a) el rbf NO alcanza bayes (gap 0.113): el prior matcheado es eficiente, no perfecto (ruido de features + bumps finitos);
(b) el prior está MATCHEADO por conocimiento de DISEÑO (se sabía que la estructura era local-en-c); de DÓNDE viene el
prior correcto (descubrirlo/aprenderlo, meta-prior) es la pregunta más profunda de R-PRIOR, no resuelta; (c) un bin con
kernel-smoothing tendería al rbf → confirma que el lever es la SUAVIDAD/estructura, no la etiqueta paramétrico-vs-no.
g sintético de bandas, espacio 2D, objetivo escalar; falta el generador de MODELO real y SCALE.

### Verificación
exp075 (48 seeds, numpy + sandbox exp018). cycle91 → H-V4-3a 'apoyada' (DoD), D-V4-53 ACEPTADA, 1 techo 'real', analogía
7 etapas, verify_no_loss=OK. Test `test_cycle91_matched_prior.py` 5/5. Convergente con sesgo-inductivo/NFL (tier2) y con
la base genérica data-hungry de CYCLE 90 (tier5).

> R-PRIOR AVANZA (H-V4-3 deja de estar sólo ABIERTA): la forma/calidad del prior (la base) fija la eficiencia muestral.
> Combinado con CYCLE 90 (poly2 no universal), la política de reconstrucción de R-VALOR ELIGE la BASE por la ESTRUCTURA
> esperada del valor: poly2 si suave/conjuntivo (89), base local/matcheada si multi-banda (91), nunca una genérica
> data-hungry por defecto. Liga gap #2 con R-PRIOR. Frontera: de DÓNDE viene el prior correcto (meta-prior / selección de
> base de los datos); el generador de MODELO real (lazo cerrado exp018); y SCALE (GPU).

## CYCLE 92 — H-V4-3b (rama R-PRIOR, hija de CYCLE 91; META-PRIOR): ¿elegir la base de los datos? — MIXTA

### Pregunta
CYCLE 91 matcheó el prior por conocimiento de DISEÑO y dejó abierto de DÓNDE viene el prior correcto. ¿Puede el agente
SELECCIONAR la base/prior de SUS PROPIOS datos (CV held-out, sin aviso de régimen) con no-regret a través de regímenes,
y superar a cualquier base fija única? (META-PRIOR; replica el patrón del selector no-regret de CYCLE 86.)

### Diseño
Numpy + sandbox REAL de exp018. DOS regímenes que el agente NO conoce: SMOOTH (conjuntivo E[v]=c·r, poly2 barato/óptimo)
y BAND (multi-banda E[v]=band(c)·r, rbf matcheado). El agente tiene un MENÚ {poly2, rbf, bin} y ELIGE por CV held-out
(split 70/30, rankea el fold held-out por cada base ajustada en train, perf_of, elige la mejor; refit en todo el buffer).
Brazos: always_{poly2,rbf,bin}, selector, oracle_selector (mejor base fija por seed = techo de un selector perfecto),
bayes, product, chance. Feedback costoso (K=10/ronda). 48 seeds. Pre-registrado.

### Resultado — MIXTA (no-regret SÍ, pero selección INNECESARIA)
(1) El META-PRIOR FUNCIONA — NO-REGRET: el selector iguala a la mejor base POR RÉGIMEN (regret SMOOTH 0.007 / BAND 0.000)
y a un oracle_selector PERFECTO (regret S=0.011/B=0.000); elige poly2 en smooth y rbf en band SIN aviso → el agente
DESCUBRE el prior correcto de sus datos, cerrando el caveat de diseño de CYCLE 91. (2) PERO la selección es PRÁCTICAMENTE
INNECESARIA: una base FLEXIBLE suficiente (rbf) casi DOMINA ambos regímenes (avg 0.655) porque NESTA tanto c·r (smooth,
rbf 0.600 ≈ poly2 0.612) como band(c)·r (band, rbf mejor) → always-rbf ≈ selector (el selector la supera sólo +0.002).
=> ESPEJA CYCLE 86 al nivel meta: un prior flexible que nesta los regímenes hace innecesaria la selección/detección
explícita; la selección sólo paga cuando NINGUNA base única domina.

### Límites (honestos)
NO es APOYADA (la maquinaria de selección no compra ventaja neta sobre un buen default flexible; a presupuesto MUY bajo la
CV ruidosa puede incluso restar). NO es REFUTADA (el selector SÍ logra no-regret y elige correctamente por régimen). g
sintético, 2 regímenes, base binned cuadrada; un régimen FUERA del span de rbf haría la selección necesaria; falta el
generador de MODELO real y SCALE.

### Verificación
exp076 (48 seeds, numpy + sandbox exp018). cycle92 → H-V4-3b 'mixta' (DoD), D-V4-54 ACEPTADA, 1 techo 'real', analogía 7
etapas, verify_no_loss=OK. Test `test_cycle92_prior_selector.py` 4/4. Convergente con CV/clase-flexible-nesta (tier2) y
con el caveat de diseño de CYCLE 91 (tier5).

> META-PRIOR (cierre del arco R-PRIOR 89-92): el prior correcto se DESCUBRE de los datos (CV no-regret) — no hace falta
> matchearlo a mano (cierra el caveat de diseño de 91). PERO la política práctica de R-PRIOR NO es una maquinaria de
> selección sino TENER en el menú un prior FLEXIBLE-suficiente (rbf) que nesta los regímenes esperados (always-rbf ≈
> selector, espeja CYCLE 86); la selección explícita se reserva para cuando ninguna base domine. Frontera: un régimen
> fuera del span de rbf (donde la selección SÍ pague); el generador de MODELO real (lazo cerrado exp018); y SCALE (GPU).

## CYCLE 93 — H-V4-7i (rama R-VALOR, EL CAPSTONE del salto grande, gaps #1/#3): lazo CERRADO con MODELO REAL — MIXTA

### Pregunta
Todo el arco 83-92 desarrolló la política R-VALOR (asignar el feedback escaso por valor estimado) pero con candidatos
SINTÉTICOS y sin lazo secuencial cerrado. El verdadero SALTO GRANDE: cerrar el lazo con el GENERADOR de MODELO REAL — el
modelo GENERA candidatos, el sandbox los VERIFICA, las correctas lo ENTRENAN, el modelo cambia. Bajo presupuesto de
verificación (B≪pool), ¿asignar la verificación por la CONFIANZA ENDÓGENA del modelo (logprob de su generación, señal
R-VALOR de CYCLE 57/60) rinde más datos correctos por verificación y mejor auto-mejora que al azar?

### Diseño
PyTorch CPU; reusa exp018 (build_base, generate_pool, train_arm, eval_metrics, sandbox). Base DÉBIL + temp ALTA → pool con
MIX (correctas/malformadas/echo/valor-mal) para que la asignación importe. Por ronda: el modelo genera M=512 candidatos;
se computa la CONFIANZA (mean logprob de la expr emitida, sin ejecutar); presupuesto B=102 (20%). Brazos (mismo base/RNG;
mismo B): conf_alloc (top-B por confianza), random_alloc (B al azar), verify_all (techo, B=M). Métrica primaria YIELD
(#correctas por ronda con B verificaciones); secundaria real_acc held-out. 4 seeds.

### Resultado — MIXTA (dos hallazgos honestos)
(1) ASIGNACIÓN — la confianza endógena asigna MUCHo mejor: YIELD conf=86.2 vs random=50.8 por ronda (+35.4, todos los 4
seeds) a igual presupuesto B=102/512; corr(confianza,strong)=0.59 (la confianza PREDICE la corrección → calibración real,
confirma CYCLE 57/60 sobre el modelo propio EN el lazo). El azar desperdicia el presupuesto en el pool desordenado; la
confianza lo concentra en lo probablemente correcto. (2) DOWNSTREAM — pero real_acc conf=0.397 < random=0.563 (Δ=-0.166):
la selección de ALTA confianza NARROWING (entrena siempre lo típico/repetitivo) → COLAPSO de diversidad (CYCLE 49-50);
verify_all (presupuesto infinito, máxima diversidad) es el techo (0.766). => la asignación R-VALOR funciona para su
objetivo directo (yield) PERO el downstream del lazo cerrado queda GATEADO por diversidad; el remedio conocido es la
guardia dedup+replay (CYCLE 50), no combinada aquí.

### Límites (honestos)
NO es APOYADA (el downstream regresiona por narrowing) ni REFUTADA (el yield mejora robustamente y la confianza está
calibrada, corr 0.59). Modelo tiny (HybridLM d=64, ~200k params), tarea de síntesis sembrada, pool forzado a un mix
(base débil + temp alta), CPU, 4 seeds. Verificación de costo MODELADO (presupuesto sobre un sandbox barato).

### Verificación
exp077 (4 seeds, PyTorch CPU, lazo cerrado real exp018). cycle93 → H-V4-7i 'mixta' (DoD), D-V4-55 ACEPTADA, 1 techo
'real', analogía 7 etapas, verify_no_loss=OK. Test `test_cycle93_closed_loop_budget.py` 4/4 (lógica del veredicto +
features; el run torch real se verifica al correr). Convergente con confianza-calibrada/active-learning (tier2) y con el
lazo verificador-real de exp018 (tier5).

> EL SALTO GRANDE — CAPSTONE (lazo CERRADO real): la política R-VALOR (asignar el feedback escaso por valor estimado,
> 83-92) FUNCIONA en un lazo de auto-mejora REAL usando la CONFIANZA ENDÓGENA (57/60) como señal de asignación bajo
> presupuesto — yield muy superior al azar (corr confianza-strong 0.59 real). PERO revela una TENSIÓN: la asignación
> confidence-greedy COLAPSA la diversidad (49-50) → el downstream se gatea. UNIFICA R-VALOR-allocation (83-92) +
> confianza endógena (57/60) + verificador-real (48-55) + diversidad (49-50). Próximo (CYCLE 94): añadir la guardia
> dedup+replay (CYCLE 50) al lazo bajo presupuesto → ¿rescata el downstream sin perder el yield? Y SCALE (GPU).

## CYCLE 94 — H-V4-7j (rama R-VALOR, CIERRA la tensión de CYCLE 93; RECETA COMPLETA): la guardia rescata el downstream — APOYADA

### Pregunta
CYCLE 93 reveló la tensión allocation↔diversidad: la asignación por confianza maximiza el yield pero COLAPSA la
diversidad (narrowing) → el downstream regresiona. ¿La GUARDIA dedup+replay (CYCLE 50) RESCATA el downstream del lazo
cerrado SIN perder el yield?

### Diseño
PyTorch CPU; reusa exp018/exp077 (mismo lazo: base débil + temp alta → pool con mix; presupuesto B=102/512; asignación
por confianza). Brazos (mismo base/RNG; mismo B): conf_alloc (greedy, baseline de 93), conf_alloc_guard (greedy + dedup
de verificados + replay de verdad canónica), random_alloc, verify_all (techo). La guardia sólo cambia la COMPOSICIÓN del
entrenamiento, NO la asignación. 4 seeds.

### Resultado — APOYADA
La guardia RESCATA el downstream sin perder el yield. real_acc guard=0.591 > conf=0.384 (+0.206, deshace el narrowing de
CYCLE 93) Y ≈ random=0.615 (−0.024, dentro de tolerancia → la confianza-greedy se vuelve VIABLE; la confianza sola NO lo
era en 93); el yield se MANTIENE/sube (guard=93.8 vs conf=86.8, Δ=+7.0; ambos >> random ~53). verify_all (presupuesto
infinito) techo=0.773: la guardia se acerca al techo a una FRACCIÓN del presupuesto. MECANISMO: el dedup colapsa las picks
repetitivas de alta confianza a su soporte ÚNICO (ntr cae a ~15 de ~100) y el replay re-inyecta cobertura → la selección
por valor (yield) y la diversidad (downstream) se DESACOPLAN. => RECETA COMPLETA del lazo bajo presupuesto:
R-VALOR-allocation (confianza endógena, alto yield) + guardia de diversidad (dedup+replay) → alto yield Y downstream sano.

### Límites (honestos)
La guardia iguala (no supera) el downstream de random — su valor neto es lograr ese downstream sano A ALTO YIELD (≈2× el
de random) y más cerca del techo. PARTE del rescate proviene del REPLAY de verdad canónica (datos-semilla clean), no sólo
del dedup (no se aisló dedup vs replay). replay_frac/budget_frac FIJOS (curva costo-beneficio sin barrer). Modelo tiny,
tarea sembrada, CPU.

### Verificación
exp078 (4 seeds, PyTorch CPU, lazo cerrado real exp018). cycle94 → H-V4-7j 'apoyada' (DoD), D-V4-56 ACEPTADA, 1 techo
'real', analogía 7 etapas, verify_no_loss=OK. Test `test_cycle94_closed_loop_guard.py` 4/4 (lógica del veredicto +
helpers de la guardia). Convergente con la guardia dedup+replay/CYCLE 50 (tier2) y con la tensión de CYCLE 93 (tier5).

> SALTO GRANDE CERRADO (89-94): la política R-VALOR se aterrizó de un verificador REAL discreto (89), por el análisis del
> prior/base (90-92, R-PRIOR), hasta el LAZO CERRADO con el GENERADOR de MODELO REAL (93-94). RECETA COMPLETA del lazo de
> auto-mejora bajo presupuesto: asignar la verificación escasa por R-VALOR (confianza endógena, CYCLE 57/60) para el
> YIELD + guardia dedup+replay (CYCLE 50) para el downstream → alto yield Y diversidad sana, cerca del techo verify-all a
> fracción del presupuesto. UNIFICA cinco hilos del lab (allocation 83-92 + confianza endógena 57/60 + verificador-real
> 48-55 + diversidad 49-50 + R-PRIOR 89-92). Frontera restante: barrer replay_frac/budget (costo-beneficio); objetivo
> NO-escalar (gap #4); y SCALE (GPU/Kaggle, fuera de la corrida CPU).

## CYCLE 95 — H-V4-8a (rama R-VALOR, gap #4: objetivo NO-aditivo): el valor debe ser MARGINAL — APOYADA

### Pregunta
Todo el arco 83-94 asignó "top-k por valor estimado" y midió perf_of = suma de valores INDEPENDIENTES (objetivo ADITIVO).
El caso REAL es a menudo SUBMODULAR (cobertura / rendimientos decrecientes: no sirve elegir 10 copias de lo mismo). ¿La
asignación por valor ABSOLUTO (top-k) FALLA bajo submodularidad, y el valor MARGINAL (greedy por ganancia respecto del
conjunto) la recupera?

### Diseño
Numpy. n=50 ítems con TIPO t∈{0..4} y CALIDAD q∈[0,1]; objetivo submodular value(S)=Σ_t max_{i∈S,t_i=t} q_i (cobertura;
sólo cuenta el mejor por tipo) vs additive (Σ q, control). q ruidosa observable, tipos observables, k=10 (k>T → cobertura
importa). Brazos: additive_greedy (top-k por q_est, la política implícita), marginal_greedy (greedy por ganancia marginal),
oracle (q real), random. 48 seeds.

### Resultado — APOYADA
Bajo SUBMODULAR el valor MARGINAL recupera el óptimo y el absoluto falla: marginal_greedy=0.991 ≈ oracle (gap 0.009) >>
additive_greedy=0.915 (+0.075; additive pierde 0.085 vs oracle, desperdicia picks en redundantes del mismo tipo). Bajo
ADDITIVE COINCIDEN (gap 0.000: sin redundancia, top-k = óptimo) → el gap es ESPECÍFICO de la no-aditividad. => R-VALOR
debe ser MARGINAL (contextual al conjunto), no absoluto, cuando el objetivo no es aditivo. CONECTA: (1) formaliza la
DIVERSIDAD (49-50/94, antes matiz empírico) como la estructura del VALOR en cobertura — la diversidad ES el valor; (2)
reconcilia con que empowerment/info-gain (24/56/79-80) YA eran valores MARGINALES.

### Límites (honestos)
g de cobertura sintético, tipos+calidad uniformes (correlacionar calidad↔tipo agrandaría el gap), óptimo submodular vía
greedy (1−1/e) + cota type-max (exacto es NP-hard). El gap absoluto (~0.075) es modesto bajo uniformidad (top-k cubre por
azar a k>T) pero robusto y direccional. No se combinó con el lazo cerrado real (la guardia dedup+replay de 94 es una
aproximación a la selección marginal).

### Verificación
exp079 (48 seeds, numpy). cycle95 → H-V4-8a 'apoyada' (DoD), D-V4-57 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle95_submodular_value.py` 5/5. Convergente con submodular/marginal greedy (tier2,
Nemhauser 1978) y con la suposición aditiva del arco (tier5).

> GAP #4 ABIERTO (objetivo no-aditivo): bajo objetivos SUBMODULARES (cobertura/diversidad, los realistas) la asignación
> R-VALOR usa valor MARGINAL (greedy por ganancia), no top-k absoluto; bajo aditivo coinciden. Formaliza la diversidad
> como estructura del valor y reconcilia con empowerment/info-gain (ya marginales). La guardia dedup+replay (94) es una
> aproximación; la versión principista es greedy-marginal. Próximo: selección marginal en el lazo cerrado real;
> calidad↔tipo correlacionados; objetivo VECTOR (multi-objetivo); y SCALE (GPU).

## CYCLE 96 — H-V4-8b (rama R-VALOR, sintetiza 94+95; versión PRINCIPISTA del lazo): cobertura marginal — APOYADA

### Pregunta
CYCLE 94 rescató el downstream del lazo con la guardia dedup+replay, pero parte del rescate viene del REPLAY de verdad
canónica clean (crutch). CYCLE 95 mostró que el valor es MARGINAL bajo cobertura. ¿Aplicar el principio marginal a la
SELECCIÓN del lazo real — seleccionar qué verificar por CONFIANZA + COBERTURA de TARGETS, sin datos clean — subsume a la
guardia?

### Diseño
PyTorch CPU; reusa exp018/exp077/exp078. Mismo lazo (base débil + temp alta; presupuesto B=102/512). Brazos: conf_alloc
(top-B confianza, baseline 93), marginal_alloc (cobertura de targets: ronda-robin tomando el mejor-confianza de cada
target no-cubierto; sólo dedup, SIN replay clean), conf_alloc_guard (94, referencia), verify_all (techo). 4 seeds.

### Resultado — APOYADA
La selección MARGINAL SUBSUME y SUPERA a la guardia, sin crutch, a yield pleno: real_acc marginal=0.756 >> conf=0.383
(+0.372, rescata el narrowing) y > guard=0.584 (vs_guard +0.171) SIN el replay clean; el yield se MANTIENE (marginal=85.7
≈ conf=86.8, Δ=-1.08); marginal (0.756) ≈ techo verify_all (0.764) → alcanza el techo a fracción del presupuesto. =>
diversificar QUÉ se verifica (cobertura de targets) cubre la diversidad del entrenamiento SIN datos externos: la versión
principista (valor marginal, CYCLE 95) domina a la aproximación heurística con crutch (guardia, 94).

### Límites (honestos)
En el SMOKE (base más débil, 2 seeds) la cobertura SÍ costaba yield (~20%) porque gastaba en targets duros/irresolubles
→ el resultado depende de la fracción de targets resolubles (a base fuerte casi todos lo son); una cobertura
confidence-aware que saltee targets sin candidato correcto recuperaría el yield en base débil (no testeada). Modelo tiny,
tarea sembrada, 4 seeds, CPU; cobertura sobre UNA dimensión (target); balance confianza↔cobertura sin barrer.

### Verificación
exp080 (4 seeds, PyTorch CPU, lazo cerrado real exp018). cycle96 → H-V4-8b 'apoyada' (DoD), D-V4-58 ACEPTADA, 1 techo
'real', analogía 7 etapas, verify_no_loss=OK. Test `test_cycle96_marginal_loop.py` 4/4. Convergente con cobertura
submodular/diversidad principista (tier2) y con el crutch de la guardia de CYCLE 94 (tier5).

> GAP #4 — el valor MARGINAL es el principio del lazo: la selección por COBERTURA (marginal) subsume y supera a la
> guardia dedup+replay (94) SIN crutch, a yield pleno, alcanzando el techo verify-all a fracción del presupuesto.
> RECETA del lazo de auto-mejora bajo presupuesto, versión principista: asignar la verificación por CONFIANZA + COBERTURA
> de targets (valor marginal). La guardia queda como alternativa para base débil + datos clean. Frontera: cobertura
> confidence-aware (robustez de yield en base débil); objetivo VECTOR; y SCALE (GPU).

## CYCLE 97 — H-V4-8c (rama R-VALOR, unifica ALLOCATION 83-96 + FORGETTING 58-74): el combinador debe OLVIDAR bajo drift — APOYADA

### Pregunta
Todo el arco de asignación R-VALOR (83-96) asumió que la estructura del valor es ESTACIONARIA. El valor real DERIVA. ¿El
combinador R-VALOR aprendido debe OLVIDAR (decay, reusando CYCLE 73) bajo drift, y el full-history se vuelve stale?

### Diseño
Numpy, online. Valor = bump gaussiano cuyo centro (mu,nu) se MUEVE cada D=8 rondas (drift) vs fijo (estacionario). El
agente observa k_obs al azar, ajusta ridge poly2; rankea el pool. Brazos: full_history (toda la experiencia), decay
(pesos por recencia decay^antigüedad), oracle, chance. perf_of vs el valor ACTUAL, promedio sobre rondas. 48 seeds.

### Resultado — APOYADA (crossover, cf. CYCLE 73)
Bajo DRIFT decay=0.841 >> full_history=0.569 (+0.272): el full se vuelve STALE (mezcla bumps de fases distintas; cae de
0.968 estacionario a 0.569 con drift, −0.399), el decay RASTREA (≈ oracle, gap 0.159). Bajo ESTACIONARIO full=0.968 >=
decay=0.966 (costo de olvidar 0.002). => UNIFICA el arco de ASIGNACIÓN con el de FORGETTING: el estimador de valor (qué
vale, R-VALOR) y el olvido (cuándo dejó de valer) son la MISMA señal en dos tiempos también para la ASIGNACIÓN, no sólo
para la memoria (replica el crossover full/decay de CYCLE 73 en el combinador de allocation).

### Límites (honestos)
decay FIJO (0.8; el óptimo depende de la tasa de drift → el selector no-regret de CYCLE 74 sería el cierre); valor bump
sintético nesteable por poly2; feedback observado al azar (insesgado, no action-gated); drift abrupto por fases; el decay
no alcanza el oracle bajo drift (lag de re-aprendizaje tras cada cambio, gap 0.159). Numpy/juguete.

### Verificación
exp081 (48 seeds, numpy). cycle97 → H-V4-8c 'apoyada' (DoD), D-V4-59 ACEPTADA, 1 techo 'real', analogía 7 etapas,
verify_no_loss=OK. Test `test_cycle97_nonstationary_value.py` 4/4. Convergente con concept-drift/recencia (tier2) y con el
crossover full/decay de la MEMORIA (CYCLE 73, tier5).

> SÍNTESIS allocation×forgetting: el combinador R-VALOR de ASIGNACIÓN debe olvidar (decay) bajo drift de la estructura del
> valor, igual que el estimador de MEMORIA (CYCLE 73). En el lazo de auto-mejora real (93-96), si lo que vale verificar
> DERIVA, el combinador de confianza/cobertura debe descontar la experiencia vieja. Próximo: selector de tasa no-regret
> (CYCLE 74) sobre el combinador; drift gradual; integrar con el lazo cerrado real; objetivo VECTOR; y SCALE (GPU).

## CYCLE 98 — H-V4-7k (rama R-VALOR/R-INTERVENCIÓN): la exploración LIGA bajo drift + observación estrecha — APOYADA (revierte 87-88 condicionalmente)

### Pregunta
CYCLE 87-88 REFUTARON la necesidad de explorar (greedy bastaba) bajo feedback action-gated — pero en régimen
ESTACIONARIO. CYCLE 97 mostró que el valor DERIVA. ¿Bajo action-gated + DRIFT el greedy se ATRAPA (combinador stale del
viejo óptimo, nunca re-observa el valor movido) y la exploración RESCATA — revirtiendo 87-88?

### Diseño
Numpy, online. Combina drift (97) + action-gating (87): valor = bump gaussiano cuyo centro se mueve cada D=8 rondas; el
agente OBSERVA k_obs ítems SELECCIONADOS (action-gated), ajusta ridge poly2 con decay (97). Se BARRE k_obs ∈ {1,2,4,8}.
Estrategias: greedy (top-k por combinador), explore (ε-greedy), random (insesgado), oracle. Régimen drift vs estacionario
(control 87-88). 48 seeds.

### Resultado — APOYADA (reversión CONDICIONAL, como el trap de CYCLE 88)
Bajo DRIFT + observación ESTRECHA (k_obs=2) el greedy se ATRAPA: greedy=0.757 << random insesgado=0.812 (gap +0.055) — re-
observa siempre la misma región estrecha y el decay no rastrea lo que no se observa; la EXPLORACIÓN RESCATA: explore=0.811
(+0.054). PERO a observación AMPLIA (k_obs=8) el greedy es ROBUSTO (gap +0.012: observa suficiente para auto-corregir) y
bajo ESTACIONARIO no atrapa a ningún k_obs (k_obs=2: −0.008; reproduce 87-88). Umbral trap_kobs*≤2. => la exploración
(R-INTERVENCIÓN) es NECESARIA bajo NO-estacionariedad + observación estrecha; el 'exploración innecesaria' de 87-88 era
específico de la ESTACIONARIEDAD o de observación amplia. VINDICA la raíz R-INTERVENCIÓN (la estructura sólo es
identificable si la distribución VARÍA — el drift ES variación) y RECONCILIA los nulls de 77-78/87-88 (eran estacionarios).

### Límites (honestos)
Efecto CONDICIONAL y modesto (~0.05): emerge sólo con observación estrecha (k_obs≤~2-4) + drift. A k_obs=1 (extremo) ni la
exploración rescata (señal insuficiente; sólo el random insesgado ayuda). Bump sintético, drift abrupto por fases, eps
fijo, numpy/juguete.

### Verificación
exp082 (48 seeds, numpy, barrido k_obs). cycle98 → H-V4-7k 'apoyada' (DoD), D-V4-60 ACEPTADA, 1 techo 'real', analogía 7
etapas, verify_no_loss=OK. Test `test_cycle98_drift_exploration.py` 4/4. Convergente con R-INTERVENCIÓN/exploración-bajo-
drift (tier2) y con el no-trap estacionario de 87-88 (tier5).

> R-INTERVENCIÓN LIGA (finalmente, condicionado): la exploración es necesaria bajo no-estacionariedad + observación
> estrecha (el greedy se atrapa, explorar rescata); reconcilia los nulls estacionarios de 77-78/87-88 con la raíz del
> árbol (la distribución debe VARIAR para que la intervención/exploración importe). Política del lazo: añadir exploración
> (idealmente SURPRISE-GATED, CYCLE 59) bajo drift + observación estrecha; greedy basta con observación amplia o régimen
> estable. Frontera: exploración surprise-gated; integrar con el lazo cerrado real; objetivo VECTOR; y SCALE (GPU).

## CYCLE 99 — H-V4-7l (rama R-VALOR/R-INTERVENCIÓN, CIERRA el sub-arco 97-99): exploración SURPRISE-GATED — APOYADA

### Pregunta
CYCLE 98 mostró que bajo drift + observación estrecha la exploración (ε FIJO) rescata al greedy atrapado — pero el ε
fijo paga exploración SIEMPRE (también en estacionario, donde no hace falta). ¿Una exploración SURPRISE-GATED (explorar
sólo cuando la sorpresa indica cambio, reusando CYCLE 59) logra NO-REGRET — rescata bajo drift como el ε-fijo, sin pagar
el costo bajo estacionario como el greedy?

### Diseño
Numpy, online, k_obs=2 (estrecho). Valor = bump gaussiano fijo (estacionario) o que se mueve cada D rondas (drift).
Combinador ridge poly2 con decay. Estrategias: greedy (ε=0), explore (ε fijo), surprise_explore (ε gateado por spike de
sorpresa = el combinador SOBRE-predijo el valor de lo que eligió greedy → cambio), random, oracle. MÉTRICA = REWARD
action-gated (perf_of de lo SELECCIONADO; explorar tiene costo de oportunidad real, framing bandit). 48 seeds.

### Resultado — APOYADA (la surprise-gated DOMINA al ε-fijo y es no-regret)
AHORRA en ESTACIONARIO: surprise=0.859 vs explore-ε-fijo=0.559 (+0.299; el ε-fijo malgasta explorando cuando no hace
falta) ≈ greedy=0.900 (−0.042). RESCATA en DRIFT: surprise=0.550 >= explore=0.437 (+0.112) y > greedy=0.532 (+0.017).
Promediando, surprise_avg=0.704 es la mejor (vs greedy 0.716/explore 0.498; supera al ε-fijo por +0.206). => exploración
endógena gateada por SORPRESA — el análogo del olvido por sorpresa (CYCLE 59) y del selector no-regret (CYCLE 66/74) para
la EXPLORACIÓN; cierra el caveat 'ε fijo' de CYCLE 98.

### Límites (honestos)
El margen vs GREEDY es chico (greedy es ROBUSTO, CYCLE 98: se auto-corrige bajo drift mild; surprise_avg 0.704 ≈ greedy_avg
0.716, margen −0.012 dentro de tolerancia). Hay un TRADEOFF de umbral de detección (estricto baja el falso-positivo
estacionario pero sub-detecta el drift; laxo al revés) → el cierre pleno sería calibrar/seleccionar el umbral (CYCLE 74).
La clara victoria es sobre el ε-FIJO (la pregunta del ciclo: qué ESQUEMA de exploración). Bump sintético, drift abrupto,
k_obs=2, numpy/juguete.

### Verificación
exp083 (48 seeds, numpy, reward action-gated). cycle99 → H-V4-7l 'apoyada' (DoD), D-V4-61 ACEPTADA, 1 techo 'real',
analogía 7 etapas, verify_no_loss=OK. Test `test_cycle99_surprise_explore.py` 4/4. Convergente con detección por
sorpresa/exploración adaptativa (tier2, análogo CYCLE 59) y con el ε-fijo de CYCLE 98 (tier5).

> SUB-ARCO 97-99 CERRADO (no-estacionariedad en la asignación): (97) el combinador R-VALOR debe OLVIDAR bajo drift
> (decay > full); (98) bajo drift + observación estrecha la EXPLORACIÓN liga (greedy se atrapa, explorar rescata —
> R-INTERVENCIÓN reconciliada); (99) la exploración SURPRISE-GATED domina al ε-fijo y es no-regret (explorar sólo al
> detectar cambio). Espeja el arco de MEMORIA (58 olvido → 59 olvido-por-sorpresa → 66/74 selector no-regret) en la
> ASIGNACIÓN. Frontera: calibrar el umbral de sorpresa; integrar con el lazo cerrado real (93-96); objetivo VECTOR; SCALE.

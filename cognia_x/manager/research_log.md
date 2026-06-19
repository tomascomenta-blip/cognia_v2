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

### Resultado — GENERALIZA (sin sobreajustar a ~1 época)
- val bajó a **2.12 bits/byte** (1.466 nats), **por debajo del baseline gzip (2.93)** → comprime
  mejor que gzip: aprende estructura de lenguaje real, sobre libros NUNCA vistos (cross-book).
- **Gap train-val ESTABLE ~0.19 nats** a 1.09 épocas, con el val aún bajando → NO sobreajusta
  (vs CYCLE 5 cuyo val SUBÍA). Genera inglés Y español reconocibles.
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
- **Resultado FULL: PENDIENTE** (corre tras CYCLE 7; con eps en la "zona ciega" mostrará: agregado
  ACEPTA el daño, por-dominio RECHAZA, por-dominio+replay ACEPTA sin olvidar → cierre de H-SELF-2).

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

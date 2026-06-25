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

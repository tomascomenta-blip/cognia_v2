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

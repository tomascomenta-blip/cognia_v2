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

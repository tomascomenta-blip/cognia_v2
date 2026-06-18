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

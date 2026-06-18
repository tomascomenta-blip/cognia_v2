# architecture.md — arquitectura propuesta de Cognia-X (y su justificación)

> La arquitectura se construye **por evidencia**, componente a componente. Confianza **alta en
> las direcciones, media en las constantes exactas** (no medidas end-to-end en el CPU objetivo).
> Fuente: ciclo-1 (exp001/exp002 propios + workflow de 13 agentes con verificación adversarial,
> 2026-06-17). Ver `hypotheses.md` para los veredictos y `research_log.md` para la bitácora.

## Tesis central (informada por evidencia)

**No optimizar FLOPs, sino BYTES MOVIDOS POR TOKEN.** La decodificación autoregresiva batch=1
en CPU es *memory-bandwidth-bound* (intensidad aritmética ~1-2 FLOP/byte, muy a la izquierda del
codo del roofline; IISWC'24, arXiv:2402.16363). El cuello no es multiplicar: es mover pesos (y
KV-cache) por la jerarquía de memoria. Tres consecuencias acopladas:

1. El **KV-cache O(L)** del Transformer puro es el enemigo en banda → backbone híbrido de estado
   fijo + atención minoritaria sliding-window.
2. El **número de pasos autoregresivos** importa más que los FLOPs/paso → representación que no
   multiplique pasos (no byte-puro a esta escala).
3. La palanca real de eficiencia es **reducir bytes/peso** → cuantización + (quizá) ternario.

Esto **converge** con el principio biológico más valioso (co-localización memoria-cómputo evita
el cuello de von Neumann) y con mis experimentos propios (exp001: O(L²) es caro; exp002: el
recall del estado fijo está acotado por su tamaño — reproduce a Jelassi "Repeat After Me" ICML'24).

## Decisiones por componente

### 1. Mezcla de secuencia (backbone)  — *informado, dirección decidida; constantes a medir*
- **Decisión:** **híbrido** — mayoría de capas de **estado fijo** (Mamba-2/SSD o Gated-DeltaNet) +
  minoría de **atención sliding-window** (W~1024) con 1-2 capas globales. Ratio recurrente:atención
  en **3:1–4:1** (NO 6:1).
- **Conservadora:** Transformer denso pequeño (1-3B) con GQA + KV-cache cuantizado 4-bit. Maduro
  en llama.cpp hoy, pero KV-cache O(L) limita contexto largo.
- **Moderada:** réplica de Gemma-3/Jamba (4:1 SWA:global, diseño de **producción verificado**,
  riesgo mínimo); sustituir SWA→SSM a medida que madure el soporte CPU.
- **Radical:** mayoría Gated-DeltaNet puro O(1) banda + 1 atención global cada ~8, sin SWA. Máximo
  ahorro, recall en riesgo, soporte CPU inmaduro.
- **Evidencia:** exp001 (coste O(L²)) + exp002 (recall ∝ estado) propios; NVIDIA Mamba-2-Hybrid 8B
  supera Transformer 12/12 tasks ~8× decode (arXiv:2406.07887); Gemma-3 KV 60%→<15% sin perder
  perplejidad (arXiv:2503.19786); ratio 3:1-6:1, el extremo alto degrada recall (arXiv:2507.06457).
  Transformer-puro NO (KV O(L)); SSM-puro NO ("Repeat After Me" arXiv:2402.01032). **exp005
  (propio): un híbrido 3/24 capas full retiene solo ~12-15% del coste de decode del full puro a
  L=8192 → la frontera coste↔recall del híbrido está MEDIDA, no solo citada.**

### 2. Representación de entrada (tokenización/embeddings)
- **Decisión:** **BPE byte-fallback, vocab MODERADO (~32k-64k, no 256k), parity-aware** sobre el
  corpus es/multilingüe; embedding+lm_head cuantizados (8-bit) y/o weight-tied.
- **Conservadora:** BPE estándar sin tocar. **Moderada:** parity-aware a vocab fijo + cuantizar
  embedding/lm_head 8-bit (baja fertilidad no-Latín >20% sin inflar softmax). **Radical:** encoder
  byte-level jerárquico tipo BLT/H-Net — **RECHAZADO** a 1-3B (no recupera overhead).
- **Evidencia:** byte-puro ×4 pasos = ×4 lecturas de pesos (ByT5 2-10× más lento); BLT a 1B arranca
  PEOR que BPE-Llama2, gana solo a 7B+ (arXiv:2412.09871); vocab grande infla lm_head+softmax O(V),
  hasta 62% del paso (FR-Spec, arXiv:2502.14856) → vocab moderado. embedding+head = 25-37% params a
  1-3B; cuantizar 8-bit da >10% RAM con ΔPPL<1% (H-REP-4 holds=true). **exp006 (propio): lm_head
  O(V) iguala 1 bloque transformer a V≈26k y crece lineal; el embedding de ENTRADA es ~10⁴× más
  barato (lookup). A vocab moderado (≤64k tied) head = 1-10% del modelo; el riesgo de cómputo+memoria
  aparece a 128-256k → confirma "vocab moderado" con números propios.**
- **Refutación útil:** H-REP-1 (holds=false) — no confundir el embedding de ENTRADA (lookup barato)
  con la capa de SALIDA lm_head O(V), que sí mueve la latencia.

### 3. Precisión de pesos / kernels de cómputo
- **Decisión:** **Q4_K_M como base de producción HOY** + I+D en **ternario b1.58 nativo** con
  kernels LUT (T-MAC/bitnet.cpp). Decidir ternario **solo tras benchmark honesto vs Q4 denso de
  calidad igualada** — NO por autoridad.
- **Conservadora:** Q4_K_M denso (maduro, 4× menos bytes/peso). **Moderada:** Q4 + KV-cache 4-bit +
  LUT donde el SIMD lo permita. **Radical:** modelo ternario nativo entrenado desde cero (caro, NO
  demostrado superior a Q4).
- **Honestidad (refutaciones):** H-BIT-1 **holds=false** — los 2-6× de bitnet.cpp son
  kernel-vs-kernel sobre los MISMOS pesos ternarios, no ternario-vs-Q4; BitNet-2B4T pierde ~12%
  MMLU vs Qwen2.5-1.5B (53.17 vs 60.25, arXiv:2504.12285). H-LUT-1 **holds=false** — T-MAC pone las
  LUTs en REGISTROS, no en L2; el límite real es registro/L1. La proporcionalidad bytes→tok/s se
  rompe en el tramo Q4→ternario (coste LUT constante por peso). **exp007 (propio): int8 naïve en
  numpy es 8-10× más LENTO que float32 (BLAS no acelera enteros); el ahorro de int8 es de memoria
  (4×), no de cómputo → realizar la velocidad de baja precisión EXIGE kernels especializados.**

### 4. Aprendizaje continuo / anti-olvido
- **Decisión:** **triple capa** — (a) **RAG a nivel de DOCUMENTO** (1 recuperación/consulta) para
  hechos nuevos sin tocar la base; (b) **LoRA rango bajo** (r≤16) como regularizador implícito; (c)
  **fusión de adapters dentro de la misma cuenca** + router de bandas (LOCAL/MEDIA/GLOBAL) para
  tareas dispares.
- **Conservadora:** solo RAG + base congelada (cero olvido por construcción). **Moderada:** RAG +
  LoRA por dominio mantenidos separados con router. **Radical:** fusión continua de adapters
  (task-arithmetic/TIES) en el coordinator federado.
- **Evidencia:** olvido = interferencia de gradientes en subespacio de bajo rango (arXiv:2510.09181);
  LoRA olvida menos pero "aprende menos" (Biderman TMLR'24); RAG ≥ fine-tune en hechos nuevos con
  cero olvido (Ovadia 2024). **kNN-LM por-token DESCARTADO** (retrieval memory-bound, ~35% TTFT
  document-level; por-token lo multiplica). Fusión segura solo dentro de una cuenca (Model Soups).

### 5. Agregación federada de adapters (impacto en `coordinator/federated_store.py` de Cognia)
- **Decisión:** agregar promediando las **delta-W reconstruidas** (avg(B@A)) o residual exacto
  estilo **FedEx-LoRA**, **NO promediar A y B por separado** (matemáticamente INEXACTO, no
  subóptimo: avg(A)·avg(B) ≠ avg(A·B)).
- **Evidencia:** FedEx-LoRA (arXiv:2410.09432); el error crece con heterogeneidad y se vuelve
  cuadrático bajo el ruido DP que Cognia exige. La verificación adversarial halló que la agregación
  real de Cognia (Pass 3, `federated_store.py`) acumula k_A,k_B,v_A,v_B linealmente por separado =
  el FedAvg ingenuo señalado. **Hallazgo accionable y barato → exp003.**

### 6. Principios biológicos: qué tomar / qué NO (gobierna 1-5, no es un bloque aparte)
- **TOMAR:** esparsidad de activación (reduce banda; pero requiere ReLU, no SwiGLU); memoria
  asociativa (= atención, útil como mecanismo no como dogma); neuromodulación/gating para
  aprendizaje continuo (con señal de contexto fiable).
- **NO copiar por eficiencia:** SNN/neuromórfico (solo ganan en hardware dedicado; en CPU ~0.78-0.85×
  y pagan exactitud), Forward-Forward (~2× más lento), predictive coding como reemplazo de backprop
  (~100× el coste). El mito "20W del cerebro" no debe guiar decisiones.
- **Refutación útil:** H-BIO-4 (holds=true) — Hopfield = atención, misma operación, mismo perfil
  memory-bound: la etiqueta "biológica" no compra eficiencia extra.

### 7. Auto-mejora (gobernada por niveles 1→5 con gates, ver protocolo §7)
- **Decisión:** búsqueda evolutiva con **evaluador VERIFICABLE** (tests/ejecución) + **gate humano**
  + **rollback**, NUNCA RL con auto-recompensa online.
- **Evidencia:** AlphaEvolve/FunSearch funcionan con evaluate() programático; self-rewarding LMs →
  reward hacking y colapso reproducibles; STOP desactivó el sandbox en 0.42% de generaciones. El
  `prompt_optimizer._estimate_quality` de Cognia (proxy longitud+latencia, "sin feedback humano
  real") es exactamente el modo de fallo advertido.

## Principios de diseño adoptados (por evidencia)
- **P1 — Sin O(L²) por defecto** en la mezcla (exp001).
- **P2 — Coste primero, calidad como compuerta** (D-004).
- **P3 — La asíntota no basta:** validar el factor constante real en CPU (exp001 / A-004).
- **P4 — Recall acotado por estado:** el recall exacto ~ilimitado exige direccionamiento por
  posición (atención) o memoria externa (exp002 + "Repeat After Me").
- **P5 — Bytes/token es la métrica maestra** (memory-bandwidth-bound): toda optimización se juzga
  por bytes movidos por token, no por FLOPs.
- **P6 — Evaluador verificable o nada:** ninguna auto-mejora se guía por un proxy auto-generado.

## Caveats honestos (no esconder)
- Confianza **media** en TODAS las constantes (tok/s, ratios de cruce, umbrales %): no se midió
  end-to-end en el CPU objetivo. Los experimentos E1-E5 (ver `experiments.md`) las confirman antes
  de comprometer diseño.
- Soporte CPU de SSM/SWA en llama.cpp **inmaduro**: el ahorro teórico de banda puede no
  materializarse sin kernels dedicados → riesgo de que el conservador (Transformer GQA + KV-quant)
  sea lo único viable a corto plazo.
- El ternario es una **apuesta de I+D**, no decisión cerrada (H-BIT-1 refutada).
- El investigador-sintetizador señaló truncamiento del corpus en la dimensión de aprendizaje
  continuo; reconstruyó desde findings + verificación propia. Anotado por honestidad.

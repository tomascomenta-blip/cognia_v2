# M0 — Palancas de DESACOPLE de "más params = más lento" (diseño + ranking + plan de medición)

> Estado: VIVO. Se ancla en lo MEDIDO hasta ahora y se refina con cada medición. Honestidad estricta:
> cada afirmación marcada **[PROBADO]** (medido en este repo, con archivo) o **[ASUMIDO]** (literatura/
> proyección, a falsar). Método del lab: medir 10×, calidad↔velocidad matched, sin overclaims.

## 0. El problema, descompuesto (qué "lentitud" exactamente)

"Más params = más lento" no es UNA cosa; son tres costos distintos que escalan con params y se atacan
distinto:

| Costo | Qué lo domina | Dónde duele | Lo MEDIDO en cognia-x |
|---|---|---|---|
| **TRAIN step** | FLOPs (fwd+bwd) + overhead de kernels | entreno (este goal) | **[PROBADO]** a escala chica (9.5M, T4) está **overhead/launch-bound** (~6% del pico fp16): AMP=1.9×, +compile=4.1× (`results_g2/g2_profile_results.json`). A escala mayor pasa a compute-bound (∝ FLOPs ∝ params·tokens). |
| **DECODE/token** | leer los pesos desde RAM/VRAM (bytes/token) | inferencia | **[PROBADO]** en CPU (i3) el decode es **weight-read-bound** (G1, `M0_G1_RESULTADO.md`): el costo/token ∝ bytes de pesos leídos, no la atención. |
| **MEMORIA** | params + activaciones + optimizer state | cabe-o-no en la GPU | **[PROBADO]** 9.5M @batch512 fp16 = 8.6 GB en T4 (cabe). El optimizer AdamW = 2× params en estado. |

→ El goal pide atacar la RAÍZ: **desacoplar params TOTALES de (FLOPs/step, bytes/token, memoria)**. Una
palanca "desacopla" si mueve un punto FUERA de la curva baseline params↔velocidad (la que mide
`m0_paramspeed_curve.py`): mismo #params con menos costo, o más #params al mismo costo.

## 1. Palancas, por mecanismo de desacople

### A. Sparsity / MoE (compute condicional) — desacopla params TOTALES de FLOPs/token
- **Mecanismo:** sólo k de N expertos se activan por token → FLOPs ∝ params ACTIVOS, no totales. Es la
  respuesta raíz a "escalar params totales sin escalar compute".
- **Desacopla:** TRAIN FLOPs y DECODE FLOPs (sí). **NO desacopla bytes/token** salvo que los expertos no
  activados no se lean (en GPU sí se evita el matmul; en CPU weight-read-bound hay que NO leer el experto
  → requiere ruteo que evite cargar pesos → más difícil). NO desacopla memoria (todos los expertos viven
  en RAM/VRAM).
- **Sobre HybridLM:** reemplazar el `SwiGLU` de cada `Block` por un MoE-SwiGLU (router top-k sobre E
  expertos). El mixer (atención lineal/SWA) puede quedar denso. Coste de implementación: medio (router +
  balanceo de carga, aux-loss). Riesgo: el routing añade overhead que, a escala chica overhead-bound,
  puede COMER la ganancia (medir, regla 10×).
- **Estado:** [ASUMIDO] (literatura: Switch/Mixtral). A IMPLEMENTAR+MEDIR como candidato #1 de desacople.

### B. Cuantización — desacopla params de BYTES/param (ataca decode weight-read-bound y memoria)
- **Mecanismo:** menos bits/param → menos bytes a leer/token y menos memoria. 4-bit (NF4/Q4), ternario
  b1.58.
- **Desacopla:** DECODE bytes/token (sí, directo — ataca el cuello de G1) y MEMORIA (sí). TRAIN: ayuda si
  se entrena cuantizado (QLoRA), pero **[PROBADO indirecto]** la baja precisión SIN kernel dedicado es
  más LENTA (exp007: int8 naïve fue 8-10× más lento) → **la velocidad de baja-precisión EXIGE kernels**
  (bitsandbytes en GPU; en CPU, llama.cpp/GGUF — ya en uso, ~8 tok/s 3B Q4).
- **Sobre HybridLM:** para inferencia, exportar a GGUF y servir con llama.cpp (camino ya validado en el
  repo). Para entreno, QLoRA (base 4-bit congelada + LoRA fp16) — pero el i3 no tiene CUDA → QLoRA va en
  T4/Kaggle. AMP fp16 (ya aplicado) es la "cuantización de entreno" gratis y medida (1.9×).
- **Estado:** [PROBADO parcial] AMP fp16=1.9× medido. 4-bit inferencia = camino llama.cpp validado. QLoRA
  entreno = a medir en T4.

### C. Distilación / small-strong — desacopla CALIDAD de params
- **Mecanismo:** un modelo chico aprende del logits/representación de uno grande → calidad de grande en
  params de chico. Ataca el goal "no sacrificar inteligencia por velocidad" por el otro lado: subir
  calidad sin subir params.
- **Desacopla:** calidad↔params (sí). No cambia el costo del chico (ya es chico y rápido).
- **Sobre HybridLM:** teacher = un modelo fuerte (p.ej. el Qwen-3B GGUF ya en el repo) → student = HybridLM
  chico, loss = KL(logits) + CE. Coste: medio (pipeline de teacher logits).
- **Estado:** [ASUMIDO]. Candidato para la fase de calidad, después de fijar la arquitectura (G2).

### D. RAG / memoria externa — desacopla CONOCIMIENTO de params
- **Mecanismo:** sacar los "params de conocimiento" a un índice externo → el modelo queda chico y sólo
  razona/recupera. Conecta con el arco R-VALOR (memoria de 3 bandas LOCAL/MEDIA/GLOBAL del system-Chimera).
- **Desacopla:** params-de-conocimiento (sí); el modelo base se mantiene chico→rápido.
- **Sobre HybridLM:** ortogonal al backbone; es arquitectura de sistema (router de contexto). Relevante
  para la fase de construcción (11_plan_maestro), no para la velocidad de entreno del backbone.
- **Estado:** [ASUMIDO]. Diferido (es nivel-sistema, no nivel-entreno).

### E. Entreno eficiente (el combo rápido+reentrenable) — no sube params, baja el costo/calidad de entrenar
- **AMP fp16/bf16:** **[PROBADO]** 1.9× en T4. Aplicado a G2. (T4=fp16; A100/L4 también bf16.)
- **torch.compile:** **[PROBADO]** ~2× extra (4.1× combinado) en una corrida de UN modelo. Caro en sweeps
  (recompila por estructura). Para corridas largas: ON.
- **Optimizador fused (AdamW `fused=True`):** [ASUMIDO] reduce overhead de muchos kernels de optimizer en
  GPU. A medir (barato).
- **batch grande + LR scaling:** **[PROBADO]** throughput satura ~74k tok/s sin compile (batch≥256); más
  batch no sube tok/s pero reduce #steps → ayuda si la convergencia lo permite (LR √-scaling).
- **gradient checkpointing:** [ASUMIDO] ahorra MEMORIA (recomputa activaciones) a costa de ~+30% compute.
  Sólo si la memoria es el límite (no lo es a 9.5M). NO es palanca de velocidad.
- **muP (transferencia de hiperparámetros):** [ASUMIDO] tunear HP en chico y transferir a grande sin
  re-tunear = **reentrenable** (clave del goal "fácilmente reentrenable"). A implementar cuando se escale d.
- **LoRA/PEFT:** [ASUMIDO] entrenar pocos params (adapters) = rápido + reentrenable + checkpoints chicos.
  Combina con base cuantizada (QLoRA). Candidato fuerte para "rápido+reentrenable".
- **data-efficiency:** menos pasos para converger (currículo, dedup, hard-example mining). Mide tokens-a-
  calidad, no tok/s.

## 2. Ranking para cognia-x (T4 entreno + CPU inferencia), por impacto×costo

1. **AMP fp16** — HECHO, 1.9× medido, gratis en calidad. [PROBADO]
2. **torch.compile** (corridas largas) — 2× extra medido. [PROBADO]
3. **AdamW fused + batch tuning** — barato, a medir ya en la curva. [a medir]
4. **LoRA/adapters** — rápido+reentrenable+checkpoints chicos; la base de "fácilmente reentrenable". [a impl]
5. **MoE (SwiGLU top-k)** — la respuesta RAÍZ a params-totales↔FLOPs; mayor esfuerzo, medir overhead. [a impl]
6. **Cuantización 4-bit inferencia (GGUF/llama.cpp)** — ataca el decode weight-read-bound (G1). [camino validado]
7. **Distilación** — sube calidad sin params, fase posterior. [diferido]
8. **RAG / muP** — nivel-sistema / al escalar. [diferido]

## 3. Plan de medición (cada candidato: velocidad Y calidad, regla 10×)
- **Baseline:** `m0_paramspeed_curve.py` en T4 → curva params↔(train tok/s, fwd tok/s) + exponente α. [corriendo tras G2]
- **MoE:** implementar `MoESwiGLU` opcional en `hybrid.py` (flag); medir, a paridad de params ACTIVOS vs
  densos: ¿train tok/s sube? ¿recall/loss se mantiene? Punto fuera de la curva = desacople probado.
- **LoRA:** medir step-time entrenando sólo adapters vs full; tamaño de checkpoint; calidad a paridad de pasos.
- **fused AdamW / batch:** variantes en la curva.
- Cada resultado → ledger en este doc (tabla velocidad↔calidad) + commit.

## 4. Ledger de candidatos medidos (se llena al medir)

| candidato | train tok/s | Δ vs baseline | calidad (recall/loss) | ¿desacopla? | archivo | estado |
|---|---|---|---|---|---|---|
| AMP fp16 (T4) | 67k (vs 35.8k) | **1.9×** | neutral (fp16+GradScaler) | sí (precisión) | g2_profile_results.json | [PROBADO] |
| +torch.compile | 147.8k | **4.1×** | neutral (misma matemática) | sí (fusión) | g2_profile_results.json | [PROBADO] |
| curva params↔vel | — | α=? | — | baseline | g2_paramspeed_results.json | [corriendo] |

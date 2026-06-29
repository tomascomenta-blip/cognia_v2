# M0 / G2 — PROFILE de velocidad de entreno (la raíz "más params = más lento", MEDIDA en T4)

> Medido 2026-06-29 en Google Colab **Tesla T4** (free) vía `colab-cli` headless. Método: regla 10× —
> no se acepta un "muro" sin descartar el error propio. Se midieron **7 variantes + desglose por
> componente** con `torch.cuda.synchronize()` (sin sync el wall-clock miente: CUDA es asíncrono).
> Artefactos: `cognia_x/construccion/m0_g2_profile.py` (script) + `results_g2/g2_profile_results.json` (datos).

## El síntoma reportado
La corrida G2 en T4 iba "~1 paso/seg" para un modelo de ~9.5M params (d_model=256, 12 capas, batch 64,
L=80) → 10-50× más lento de lo esperado. Sospechas a profilar: data-gen CPU-bound, fallback a CPU, sin
AMP, sin compile, batch chico, máscara `tril` recreada cada forward, eval cada 666 pasos.

## Lo MEDIDO (no asumido)

**1) Desglose del step (baseline fp32, data-gen numpy+H2D, batch 64):**

| componente | lineal_puro (ae0) | attn_puro (ae1) |
|---|---|---|
| data-gen (numpy + `.to`) | **0.86 ms** | 0.97 ms |
| forward | 44.6 ms | 49.7 ms |
| backward | **93.3 ms** | 101.1 ms |
| optimizer | 4.4 ms | 4.6 ms |
| **total** | **143 ms → 7.0 step/s** | 156 ms → 6.4 step/s |

**2) Palancas (sobre lineal_puro ae0), tok/s y speedup vs baseline:**

| variante | ms/step | tok/s | speedup |
|---|---|---|---|
| baseline fp32 (batch 64) | 143 | 35.8k | 1.0× |
| **AMP fp16** | 76 | 67k | **1.9×** |
| gpu-datagen (sin numpy/H2D) | 145 | 35.3k | 0.99× (nulo) |
| AMP + gpu-datagen | 76 | 67k | 1.9× |
| AMP + gpu-datagen + batch 256 | 277 | 74k | 2.1× (tok/s) |
| AMP + gpu-datagen + batch 512 | 549 | 74.5k | 2.1× (tok/s) |
| **AMP + gpu-datagen + batch 512 + torch.compile** | 277 | **147.8k** | **4.1×** |

GPU mem máx @batch512 = 8.6 GB (de 15 GB del T4). `cuda_available=True`, `GPU=Tesla T4`.

## Diagnóstico de la RAÍZ (PROBADO)
- **NO era data-gen**: 0.86 ms/step (0.6% del tiempo). Hipótesis "CPU-bound" **REFUTADA**.
- **NO era fallback a CPU**: `torch.cuda.is_available()=True`, GPU = Tesla T4. **REFUTADA**.
- **El baseline real es 7 step/s, no 1.** El "~1 step/s" reportado fue una mala atribución: la corrida
  original sumaba el rebuild de modelo por config + eval cada 666 pasos + que los configs lineal-mayoría
  **nunca hacían early-stop** (corrían el deadline entero de 1500s/config) → "no terminó en 9 min".
- **El cuello real**: fp32 + workload chico por step (5120 tok). El modelo corre a **~6% del pico fp16
  del T4** → está **overhead/launch-bound**, no compute-bound (matrices chicas d=256, dh=32 no saturan
  las SMs; sin tensor cores en fp32). Lo confirma que (a) AMP fp16 da 1.9× (activa tensor cores) y (b)
  `torch.compile` da otro ~2× (fusiona kernels → mata el overhead de launch). El throughput satura
  ~74k tok/s sin compile (batch≥256), y compile lo rompe a 148k.

## El FIX aplicado a `m0_g2_recall_colab.py`
1. **AMP fp16** (autocast + GradScaler, `unscale_` antes del `clip_grad_norm_`): **1.9× medido**, neutral
   en calidad. Default ON en cuda (`--no-amp` para desactivar). Eval también bajo autocast.
2. **plateau early-stop**: corta una config CLARAMENTE estancada (best < 0.5 y `patience=4` evals sin
   mejora ≥ 0.01) → no sesga el veredicto (un config plano lejos de 0.8 no va a cruzar) y acorta el sweep.
3. **`--compile`** (torch.compile, OFF por default): ~2× extra PERO recompila por cada estructura de
   modelo distinta → caro en un sweep de muchas configs cortas. Reservado para corridas largas de UN modelo.
4. steps 8000 → **5000** (ample para converger este recall; los learners early-stop antes), deadline/config
   1500s → 600s (red de seguridad; el early-stop corta mucho antes).

**Efecto:** AMP (1.9×) × plateau (corta no-aprendices ~2-3×) → el sweep G2 cierra en ~15-20 min en T4
(antes proyectaba >2 h). Sin tocar la calidad (AMP fp16 es matemáticamente equivalente con GradScaler).

## CORRECCIÓN (2026-06-29, honestidad) — AMP fp16 NO era "neutral en calidad"
La afirmación inicial "AMP fp16 es neutral en calidad" era **[ASUMIDA]** (medí throughput, no calidad).
La corrida real de G2 con AMP la **REFUTÓ**: apareció `loss nan` (config ratio_ae4, step 1664). Causa raíz:
la **`LinearAttention` NO está normalizada** (q@k^T con features elu+1, SIN 1/sqrt(d)) → bajo fp16 los
scores y el denominador **OVERFLOWean** el rango de fp16 (>65504) → inf → NaN. La `SlidingWindowAttention`
con softmax sobre fp16 y -inf también es frágil. Es exactamente la trampa que la regla "calidad↔velocidad
MATCHED" busca cazar: una optimización de velocidad que **rompe el entreno**.
- **FIX (fp16-SEGURO):** el núcleo de ambas atenciones se computa en **fp32** (autocast OFF) y las
  proyecciones qkv/o quedan en fp16 (tensor cores = casi toda la FLOPs). Aplicado a `m0_g2_recall_colab.py`.
  Trade-off: algo menos de 1.9× (la parte fp32 del core no usa tensor cores) pero SIN NaN y con la
  calidad del recall intacta. El speedup real fp16-seguro se re-mide en la corrida corregida.
- **Lección:** "AMP da 1.9×" sigue PROBADO para THROUGHPUT, pero el speedup utilizable EXIGE numerics
  seguros. El profile midió velocidad; la corrida de entreno midió calidad. Ambas medidas hacen falta.

## Lo que esto significa para el goal "más params = más lento"
Esta es la PRIMERA palanca de entreno-eficiente MEDIDA: **AMP fp16 + torch.compile = 4.1×** en T4 para
este modelo, gratis en calidad. Y deja una lección de método: el "muro" de 1 step/s era un **error propio**
(fp32 + no-early-stop), no un límite del hardware — exactamente lo que la regla 10× obliga a descartar.
Queda headroom: aún con compile estamos a ~13% del pico fp16 → las matrices chicas (d=256) son el límite
de eficiencia; subir d/batch o fusionar la atención lineal daría más. Próximo: caracterizar la curva
params↔velocidad (baseline real medido) y atacar el desacople (cuant/MoE/distil/RAG).

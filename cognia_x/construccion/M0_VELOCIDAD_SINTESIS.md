# M0 — SÍNTESIS: velocidad de entreno de cognia-x (qué se midió, qué se aprendió)

> Sesión 2026-06-29. Goal: entrenar la IA optimizando AL MÁXIMO la velocidad de entreno, reentrenable, y
> ATACAR LA RAÍZ de "más params = más lento". Método: regla 10× (no aceptar un muro sin descartar error
> propio), calidad↔velocidad MATCHED, verificación REAL con números, honestidad PROBADO/ASUMIDO. Todo
> commiteado en `origin/cognia-x`. Detalle por tema en los docs `M0_*` y `results_g2/`.

## 1. La raíz "más params = más lento", MEDIDA y descompuesta
3 costos distintos (ver `M0_DESACOPLE_PALANCAS.md`): **train FLOPs/step**, **decode bytes/token** (G1:
weight-read-bound en CPU), **memoria**. El goal = desacoplar params TOTALES de estos costos.

## 2. Velocidad de entreno en T4 — PROBADO (`M0_G2_PROFILE_RESULTADO.md`, `results_g2/g2_profile_results.json`)
- El "~1 step/s" reportado era **mala atribución**: baseline real **7 step/s**. datagen=0.86ms (NO era el
  cuello) y GPU real (NO fallback) — 2 hipótesis REFUTADAS por medición. Cuello: fp32 + workload chico →
  overhead/launch-bound (~6% del pico fp16).
- Palancas: **AMP fp16 = 1.9×**, **+torch.compile = 4.1×** (35.8k→147.8k tok/s). Throughput satura ~74k
  tok/s sin compile (batch≥256).

## 3. Trampa cazada: AMP fp16 NO era "neutral en calidad" — daba NaN (PROBADO)
La `LinearAttention` no está normalizada (q@k^T con elu+1, sin 1/√d) → bajo fp16 overflow (>65504) → NaN.
**Fix fp16-SEGURO** (núcleo de atención en fp32, proyecciones en fp16) en el script G2 **y en el modelo
canónico `hybrid.py`** (6 tests pasan). Lección: una optimización de velocidad puede romper el entreno;
hay que medir AMBOS (la regla calidad↔velocidad lo cazó).

## 4. Reentrenabilidad — PROBADO (`cognia_x/train/fast_harness.py`)
Harness con AMP-safe + compile + AdamW fused + **CHECKPOINT ATÓMICO REANUDABLE** (modelo+opt+scaler+
step+rng+config; `os.replace`). Resume verificado: entrena 40 → "muere" → reanuda en 40 → 80, loss continuo.
Config declarativa. Es el "fácilmente reentrenable" del goal.

## 5. GROKKING — el hallazgo que reorienta el costo de convergencia (PROBADO local)
El recall asociativo **GROKEA**: meseta larga a acc baja (~0.35) y luego transición ABRUPTA a >0.9
(validado: 0.125→meseta(~3300 pasos)→0.79(step 3663)→0.97(3996)). Implicaciones:
- Resolvió una ANOMALÍA: el sweep G2 daba "ni la atención pura cruza" = **falso negativo** por cortar antes
  de la transición (plateau early-stop letal + deadlines de Colab). `plateau_stop` ahora DEFAULT OFF.
- **Para el goal de VELOCIDAD**: el costo de entreno dominante = **#pasos-hasta-la-transición**. Entonces
  **data-efficiency = acelerar el grokking** (weight-decay/LR) es una palanca de velocidad DIRECTA, a igual
  calidad final (Pareto puro). Se está midiendo (`m0_grok_accel.py`).

## 6. Palancas de DESACOPLE — medidas hasta ahora (ledger en `M0_DESACOPLE_PALANCAS.md`)
- **AMP fp16**: 1.9× [PROBADO] (con fix fp16-safe).
- **torch.compile**: 4.1× combinado [PROBADO].
- **MoE (compute condicional)**: candidato #1 al desacople params↔FLOPs. Preliminar CPU: MoE naive a
  0.42-0.50× del denso (ruteo Python domina) → **el desacople EXIGE kernels de dispatch** (a re-medir GPU).
- **LoRA/adapters**: rápido+reentrenable (pocos params, checkpoint chico) [PROBADO mecánica].
- **data-efficiency (grokking)**: en medición.
- Cuantización 4-bit inferencia (GGUF/llama.cpp): camino validado para el decode weight-read-bound (G1).

## 7. Lecciones de método / infra
- **Colab free es inestable**: murió a 13-67 min en 3 sesiones; GPU a veces "Service Unavailable". →
  **descargar resultados INCREMENTALMENTE** (poller PowerShell que baja el JSON cada ~75s) y, para sweeps
  largos (grokking necesita miles de pasos × muchas configs), usar **Kaggle** (9-12 h estables).
- `colab_headless.py` genera launcher/checker del patrón headless desacoplado.
- La regla **10×** evitó 2 overclaims grandes: "1 step/s es el límite" (era 7, y fp32) y "el recall exige
  atención plena/RAMA B" (era grokking cortado antes de tiempo).

## 8. Pendiente (bloqueado por GPU disponible / Kaggle)
- Curva params↔velocidad a escala en GPU (la local-CPU se corre como evidencia CPU-first).
- MoE medido en T4 a escala (¿el ruteo amortiza con más tokens? ¿torch.compile fusiona el loop de expertos?).
- Sweep G2 de arquitectura LARGO y estable (cruzar el grokking por config) → Kaggle.

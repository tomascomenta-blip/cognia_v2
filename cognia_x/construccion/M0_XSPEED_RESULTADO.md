# M0 / XSPEED — Entrenamiento ultra-rápido en la T4 de Kaggle (TAREA 1) — RESULTADO

**Fecha:** 2026-07-01 · **Hardware:** Kaggle 2× Tesla T4 15.6GB (torch 2.10.0+cu128) ·
**Datos crudos:** `results_xspeed/xspeed_results_v1.json` (ronda 1) y `results_xspeed/xspeed_results.json` (ronda 2) ·
**Kernel:** `xspeed_bench_kernel.py` + `run_kaggle_xspeed.py` · **Modelo:** HybridLM 9.5M (d=256, 12L, L=80, recall MQAR)

## Veredicto

**De 36.3k a 148.7k tok/s = 4.10× medido, con calidad verificada por 4 gates.** La config ganadora
(portada a `cognia_x/model/hybrid.py` como opt-in) es:

```
AMP fp16 + atención lineal cheap16 + SDPA en atención softmax + datos generados en GPU
+ batch 512 + torch.compile (modo default) + AdamW fused
```

El 4.1× "histórico" del 2026-06-29 (147.8k) corría el path fp16 INSEGURO que NaNea en step 1664 —
era inválido para entrenar de verdad. Hoy el mismo número es real y con gates.

## La palanca nueva: atención lineal `cheap16`

El fix fp16-seguro (núcleo en fp32) costaba 13-23% y duplicaba memoria (b512=10.4GB, b768 OOM).
`cheap16` lo reemplaza sin perder seguridad: se escala φ(q) por `1/(L·√df)` DESPUÉS del feature map.
Como la salida es el cociente `(scores@v)/denom` y numerador y denominador escalan igual, la
matemática es **idéntica** (invariancia medida con mismos pesos en fp32: rel diff 7e-06). La escala
encoge las sumas O(L·df) — la causa real del overflow fp16 (>65504) — y los matmul fp16 ya acumulan
en fp32 en tensor cores, así que la precisión no se degrada.

Gates que pasó en T4 (ronda 2):
1. **Invariancia**: rel diff 6.9e-06 (solo redondeo).
2. **NaN-watch**: 3000 steps limpios en la config EXACTA que NaNeaba (ae4 a escala, AMP; el NaN
   original era en step 1664). Loss desciende (2.99→2.96).
3. **Paridad de loss** (600 steps, mismos datos/seed/batch, ae4): fast16 1.29%, fast16+compile 0.97%
   — misma banda que amp_safe (1.0%) vs fp32.
4. **Grokking end-to-end** (config validada de m0_grok_accel): fp32, amp_safe, fast16 y
   fast16+compile+CUDA-graphs grokean TODOS en el MISMO step 3600, best_acc 0.81–0.83. El compilado
   además lo hace en la mitad del wall (34.5s vs 67.5s).

## Ledger de palancas (todo medido en T4, mismo modelo/tarea)

| palanca | tok/s | vs fp32 | veredicto |
|---|---|---|---|
| baseline fp32 b64 | 36.3–36.5k | 1.00× | referencia (reproduce el 35.8k de Colab) |
| AMP fp16-seguro b64 | 59.4k | 1.63× | el fix costaba 13% a b64… |
| AMP fp16 inseguro b64 | 68.4k | 1.87× | (NaN step 1664 — solo para dimensionar el costo) |
| **AMP cheap16 b64** | **68.1k** | **1.87×** | **recupera el 100% del costo del fix** |
| + gpu-datagen | ≈igual | — | neutro acá (datagen era 0.86ms, no era el cuello) |
| + batch 512 | 64.9k (safe) / 76.2k (cheap16) | 1.78–2.10× | satura sin compile |
| + compile default + fused | 135.9k (safe) / **148.7k (cheap16)** | 3.74× / **4.10×** | **GANADOR** |
| compile reduce-overhead (CUDA graphs) | 132.6k (safe) / 141.4k (cheap16) | — | ≈default a b512; a b64 rinde 108k (≈b512) → confirma launch-bound |
| SDPA en atención softmax | 52.5k→71.7k (ae1 b512) | +36% | adoptado (attn_sdpa) |
| híbrido real ae4: safe → fast16 | 127.0k → 140.2k | +10.4% | adoptado |
| batch 1024 (cheap16+compile) | 130.3k | — | NO mejora; 12.8GB |

## Descartado con números (no volver sin evidencia nueva)

- **torch.compile max-autotune**: 97.1k < default 109.6k (y 176s de warmup). Peor en este workload.
- **gradient checkpointing**: 43.3k (1.19×) — es palanca de MEMORIA (10.4GB→1.6GB), no de velocidad.
  Útil solo si un modelo futuro no entra en 15.6GB.
- **DataParallel 2×T4**: b512 = 113.8k vs 132–136k en UNA GPU (el scatter/gather come más que lo
  que la segunda GPU aporta a esta escala); b1024 OOM. El multi-GPU a esta escala NO paga.
- **batch >512 sin compile**: OOM (los scores fp32 del núcleo safe32 dominan memoria).
- **AdamW fused solo (sin compile)**: 63.3k ≈ neutro; el valor aparece COMBINADO con compile
  (114k→148.7k lo incluyen).

## Qué quedó en el repo

- `cognia_x/model/hybrid.py`: levers opt-in `amp_linear_core="cheap16"` y `attn_sdpa=True`
  (defaults intactos = comportamiento previo EXACTO; taylor cae a safe32, documentado).
- `cognia_x/train/recall_task.py`: `train_and_eval(..., amp_linear_core=, attn_sdpa=)`.
- `cognia_x/tests/test_xspeed_levers.py`: 6 tests (invariancia cheap16, SDPA global/ventanado,
  defaults intactos, taylor-fallback, smoke de entreno). 12/12 con la regresión previa.
- Receta de corrida rápida en GPU: `fast_harness` ya soporta amp/compile/fused; setear
  `amp_linear_core="cheap16"`, `attn_sdpa=True`, batch 512, `compile=True`, `fused=True`.

## Método (para la próxima ronda)

Las dos correcciones de esta corrida salieron de leer los datos crudos, no de teoría: (1) el gate de
grokking v1 usaba una tarea MÁS DIFÍCIL que la validada (n_keys=64 vs 24) → "no grokea" era falso
negativo del gate, no del modelo; (2) el crash de CUDA-graphs era leer un tensor del grafo ya pisado
(fix: `float(loss)` por step). Ambas están corregidas en el kernel v2.

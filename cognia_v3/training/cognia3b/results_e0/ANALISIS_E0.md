# E0 — Análisis y veredictos (v1: 2026-07-06, v2/E0b: 2026-07-07)

Kernel: `cognia-e0-perfil` (e0_perfil_kernel.py). v1 = 2×T4 shardeado (INVÁLIDO como
perfil single-GPU, conservado en `e0_results.v1.json`); **v2/E0b = 1×T4 forzada
(gpu_count=1), el perfil válido** (`e0_results.json`). Base: Qwen2.5-Coder-3B-Instruct
NF4+DQ. Stack Kaggle: torch 2.10.0+cu128, transformers 5.0.0, peft 0.19.1, bnb 0.49.2.
Costo total E0 (v1+v2): ~0.9 GPU-h de las 2 presupuestadas.

## Números centrales (single T4, 14.56 GiB visibles)

| Config (transformers+PEFT) | tok/s seq | tok/s ÚTILES | VRAM alloc |
|---|---|---|---|
| A control p2k2 (mb4 ga4, AdamW fp32, sin pack) | 558 | 25 | 13.76 |
| B + paged8bit | 548 | 25 | 13.42 |
| **D + packing (mb4)** | 532 | **511** | 13.42 |
| **G + packing + masking** | 534 | **513** | 13.42 |
| F seq2048 mb2 pack | 487 | 480 | 13.43 |
| J mb2 | 523 | 24 | 8.44 |
| H r8 qkvo mb4 pack | **647** | **620** | 13.30 |
| I r32 all mb4 pack | 525 | 504 | 13.56 |
| C/E mb8 (±pack) | OOM (logits 4.64 GiB) | — | — |
| K/L/M sin GC (mb2/mb4) | OOM (ni mb2 entra) | — | — |

| Unsloth (single T4) | tok/s seq | tok/s ÚTILES | VRAM alloc |
|---|---|---|---|
| mb4 | 674 | 26 | **5.11** |
| mb8 | 697 | 26 | 7.75 |
| **mb8 packed** | 667 | **652** | 7.75 |
| mb16 packed | 645 | 630 | 13.03 |

## Veredictos de las predicciones pre-registradas (Parte 7 §7.1 / docstring del kernel)

- **P-E0a (pesos NF4 2.0-2.4 GB): CONFIRMADA.** `peso_base_gb = 2.05` — la cuenta
  analítica de la Parte 1 (2.06 GB) clavó el número al centésimo.
- **P-E0b (paged8bit libera VRAM y habilita mb↑): PARCIAL.** Ahorra 0.34 GB alloc
  (consistente con estados de 30M params), pero mb8 sigue OOM en el path transformers:
  el bloqueo es la CABEZA DE LOGITS (4.64 GiB fp32, vocab 152k), no el optimizer.
- **P-E0c (≥800 tok/s útiles): REFUTADA.** Techo medido ~650 útiles (unsloth mb8 pack).
  Rige la rama pre-registrada: corpora conservadores de DC-8. Recalculado con el número
  real: **~650 tok/s útiles ≈ 25.7M tokens útiles/sesión de 11h ≈ ~51M/semana** (mejor
  que el piso 424-sin-packing porque útiles≈seq con packing; peor que el objetivo 800).
- **P-E0d (Unsloth ≥1.3×): CASI (1.25-1.28×), SE ADOPTA IGUAL.** 652 vs 511 útiles
  = 1.28× sobre nuestro mejor baseline, con **la mitad de VRAM** (7.75 vs 13.42 GB),
  headroom hasta mb16, y sin el acantilado de OOM de los logits (CE fusionada).
  El criterio de adopción era ≥1.3× — está al borde; la ventaja de memoria decide.
  **Condición pendiente: equivalencia de loss (±1%) se verifica como brazo A/B en E1.**

## Hallazgos no previstos

1. **GC es obligatorio incluso a mb2** en el path transformers (K/L/M OOM): el gap
   "velocidad sin GC" queda CERRADO por imposibilidad física en 14.56 GiB — no es palanca.
2. **El masking es gratis** (513 vs 511 útiles): se adopta sin costo.
3. **Packing multiplica ×20 los tokens útiles en cognia_dataset** (25→511): sin packing
   ese dataset desperdicia el 96% del cómputo.
4. **r8-qkvo es +21% más rápido que r16-all** (620 vs 511 útiles): la capacidad del
   adapter tiene costo real de throughput → E1 debe pesar calidad vs velocidad (Pareto).
   r32 ≈ r16 en velocidad (504 vs 511): subir de r16 a r32 es casi gratis en tiempo.
5. **Meseta compute-bound**: mb2→mb4 casi no cambia tok/s (523→558 seq) — la T4 ya
   está saturada a mb chico; los batches grandes solo pagan vía CE fusionada (unsloth).

## Decisión (columna para E1, congelada acá)

**Runtime E1: Unsloth** (fp16, GC "unsloth"), **mb8 packed + completion-masking,
seq 1024, paged/adamw-8bit**, ~650 tok/s útiles esperados. Brazo de control
transformers+PEFT (config G) para la equivalencia de loss. La ablación E1 mantiene
sus 4 brazos de MÉTODO (r8-qkvo / r16-all / DoRA / +NEFTune) sobre este runtime.

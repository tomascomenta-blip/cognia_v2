# E2A — A/B de runtime con steps igualados: veredicto

Kaggle 1×T4, 18.9 min de wall (kernel cognia-e2a-runtime v1). Reabre el confound
de E1 (ANALISIS_E1.md): t_r16_all había ganado G3 100% vs 50% de u_r16_all, pero
había visto 2× gradientes (mb4=92 steps vs mb8=46).

## Resultado (instrumento E1b: system neutro pareado, suites hash-verificadas)

| Brazo | steps | loss_fin | G1 | G3 | G5 | tooluse | tok/s train |
|---|---|---|---|---|---|---|---|
| t_r16_all (E1, montado) | 92 | 0.877 | 93% (+4pp) | **20/20** | 56% (−4pp) | 10/10 | 413 |
| **u_r16_all_mb4 (nuevo)** | 92 | **0.8771** | 93% (+4pp) | **20/20** | 56% (−4pp) | 10/10 | **504.3** |
| base | — | — | 89% | 0/20 | 60% | 0/10 | — |

## Predicciones pre-registradas: 3/3 CONFIRMADAS

- **P-E2A-1 CONFIRMADA**: loss_fin 0.8771 vs 0.877 — diferencia 0.01% (banda ±10%).
- **P-E2A-2 CONFIRMADA**: G3 = 20/20 (≥18/20). La brecha G3 de E1 (50%↔100%) era
  ENTERAMENTE steps, no runtime.
- **P-E2A-3 CONFIRMADA**: 504.3 tok/s ≥ 413 (unsloth 1.22× más rápido a mb4;
  mismo tok/s que a mb8 en E1 → el cuello no es el batch en este régimen).

## DECISIÓN (regla pre-registrada, vinculante para E2..E5)

**Runtime = UNSLOTH** (g3_ok ∧ g1_ok ∧ g5_ok ∧ tok_ok, decisión in-kernel).
Método columna completo: **unsloth + LoRA r16 α32 all-linear, NF4, packing +
completion-masking + GC, mb4, lr 1e-4 cosine, EPOCHS 2, seed 20260707**.
La interpretación causal de E1 queda corregida en el registro: "transformers >
unsloth" era artefacto de steps; a igualdad de gradientes son equivalentes en
calidad y unsloth gana por velocidad (+22%).

## Caveats honestos

- G5 español sigue en 56% (−4pp vs base) en AMBOS brazos — el déficit es del
  DATASET (e1_train no tiene replay es-general), no del runtime. Se ataca en E2
  con D2 (replay español), como ya estaba pre-registrado.
- tooluse sigue siendo N=10 direccional; la suite ACCION N≥100 (G2A) está en
  construcción y será gate real desde E3.
- La equivalencia de loss (0.01%) es sobre la MISMA seed/datos/orden; no es un
  claim general unsloth==transformers, es "en este pipeline son equivalentes".

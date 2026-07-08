# E2-FINAL — checkpoint candidato v1: NO APTO como checkpoint único (G1 −8pp)

Kaggle 1×T4, 254 min. Corrida colapsada de la receta ganadora de E-MIX-B
(mezcla única DC-4) + 2 fixes de G3: **D1 ×3** y **2 EPOCHS**. Corpus 12.079
pares (e1_train + d5_espanol + tooluse_v3 + D1×3 extra 2.366 + replay
on-policy 664/800), lr 1e-4 cosine, unsloth r16-all mb4 seq2048, 622 steps
@529.5 tok/s útil, loss 1.339→1.168, sin NaN.

## Veredicto contra el pre-registro (McNemar pareado vs base, suites congeladas)

| Gate | pre-registro | base | cognia3b_v1 | delta | p | veredicto |
|---|---|---|---|---|---|---|
| G3 identidad (20) | ≥18/20 | 0% | **100%** (20/20) | +100pp | 0.0 | **PASA perfecto** |
| G1 general (100) | ≥85% | 89% | **81%** | **−8pp** | **0.039** | **FALLA** (n10=10, n01=2) |
| G5 español (25) | ≥60% | 60% | 60% | 0pp | 1.0 | PASA (justo) |
| G2A ACCION (147) | ≥95% | 20.4% | **96.6%** | +76.2pp | ~0 | PASA (n01=112, n10=0) |

**`APTO_PARA_E5: false`** — la regla era "pasa todo". Falla P-FINAL-2.

## Diagnóstico: los fixes de G3 compraron identidad con olvido general

- Los 2 fixes funcionaron para lo suyo: G3 pasó de 70% (E-MIX B, D1 al 12%
  × 1 epoch) a **100%** (D1×3 × 2 epochs).
- El costo: G1 87% (E-MIX B, 1 epoch) → **81%** (2 epochs). La palanca del
  olvido es la EXPOSICIÓN TOTAL: duplicar epochs a lr 1e-4 duplica los updates
  sobre todo el corpus y erosiona capacidad general que el corpus no cubre.
  La regresión es real (p=0.039), no ruido: 10 ítems que la base acierta y el
  brazo pierde, contra 2 al revés. Se pierde parejo en CD (código) e IN
  (instrucciones), no en un solo tema.
- G5 60%: el replay evitó la caída (E1 sin replay: 56%) pero no repitió el 64%
  de E-MIX B — consistente con más olvido por más exposición.

## Decisión de arquitecto (2 vías, ninguna bloquea a la otra)

1. **El adapter v1 SÍ sirve HOY como EXPERTO del fleet** (plan A adapter VIVO,
   hallazgo re-quant de E-MIX-B v2): para tareas ACCION/agente (G2A 96.6%) e
   identidad (G3 100%) con hot-swap validado (2-41 ms, POST /lora-adapters).
   En el fleet la regresión G1 es irrelevante: las consultas generales las
   atiende la BASE sin adapter. El deploy del CLI no espera a v2.
2. **E2-FINAL-v2 lanzado** para el candidato único, con la receta E-GROK:
   **1 epoch + lr 3e-4 + warmup 10%** (mismo corpus D1×3 + replay cacheado).
   Fundamento medido: E-GROK probó que lr 3e-4+warmup logra el grokking de
   identidad en 151.6 s SIN regresión G1/G5-mini; 1 epoch reduce a la mitad
   la exposición (la palanca del olvido). Pre-registro:
   - P-V2-1: G3 ≥ 18/20 (grokking por lr alto + D1×3 compensa 1 epoch)
   - P-V2-2: G1 ≥ 85% (menos exposición → menos olvido)
   - P-V2-3: G5 ≥ 60% (replay presente)
   - P-V2-4: G2A ≥ 95% (E-MIX B lo logró con 1 epoch)
   - Regla: pasa todo → APTO_PARA_E5 (candidato único v2).

## Números operativos

- Replay on-policy: 800 → 664 aceptados (83%), 94 min (~37% del wall).
  v2 REUSA el replay.jsonl cacheado de esta corrida como dataset (lección
  E-MIX aplicada: no repagar la generación).
- Adapter: `adapters/cognia3b_v1/` (126 MB, r16 all-linear) descargado local.
- Wall total 254 min; v2 proyectado ~130 min (sin replay, 1 epoch).

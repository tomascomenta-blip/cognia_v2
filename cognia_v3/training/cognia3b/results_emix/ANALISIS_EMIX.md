# E-MIX — resultados: brazo B oro, brazo A INVALIDADO por bug de merge

Kaggle 1×T4, 282 min. Árbitro de topología DC-4 (secuencial-con-merge vs
mezcla única, §7.3). Corpus: e1_train 1.344 + d5_espanol 6.910 + replay
on-policy 664 (de 800 generados, juez heurístico) + tooluse_v3 795 ≈ 9.7k
pares, 1 epoch, unsloth r16-all mb4 seq2048 (método columna E2A).

## Lo MEDIDO válido (brazo B, mezcla única — instrumento E1b + G2A N=147)

| Gate | base | brazo B | delta | p | veredicto |
|---|---|---|---|---|---|
| G1 general (100) | 89% | 87% | −2pp | 0.75 | PASA (banda −4pp) |
| G3 identidad (20) | 0% | **70%** | +70pp | 1e-4 | NO pasa (≥18/20) |
| G5 español (25) | 60% | **64%** | +4pp | 1.0 | PASA y RECUPERA (E1: 56%) |
| G2A ACCION (147) | 20.4% | **98%** | **+77.6pp** | ~0 | **PASA con margen enorme** |

- **P-EMIX-3 CONFIRMADA ×7**: el dataset ACCION v3 (multi-paso + anti-ciclo +
  cierres) lleva el gate real de tool-calling de 20.4%→98% (n01=115, n10=1).
  El objetivo "multi-paso 0% → ≥40%" de la teoría quedó pulverizado.
- **P-EMIX-2 CONFIRMADA**: el replay español recupera G5 (64% > 60% base;
  en E1 sin replay había caído a 56%). El replay on-policy in-kernel funcionó
  (664/800 aceptados).
- G3 70% (14/20): la identidad quedó DILUIDA — D1 es 12% del corpus y fue
  1 epoch (en E1 D1 dominaba 88% × 2 epochs → 100%). Fix conocido para la
  corrida final: sobre-representar D1 (×2-3) y/o 2 epochs.

## El bug del brazo A (honestidad brutal)

El brazo A-final evaluó EXACTO como la base en G1/G3/G5 (deltas 0.0pp, CERO
ítems discordantes en 145) y solo G2A cambió (98%): **el merge manual de
etapa-1 NO aplicó el adapter** — el "merged" era la base dequantizada pelada
y la etapa-2 entrenó sobre nada. El adapter a_etapa1 está SANO (504 keys,
normas no-cero, verificado local). Causa probable: el dequant in-place
(reemplazo de módulos DURANTE la iteración de named_modules()) — patrón
frágil; causa exacta no aislada porque el fix canónico lo reemplaza entero.

- **P-EMIX-1 (el árbitro DC-4): SIN DECIDIR** — no se compara contra un brazo roto.
- **P-EMIX-4: REFUTADA POR INSTRUMENTO**, no por el método (G3 0/20 del
  A-final es el bug, no el merge DC-9 conceptual).

## Correcciones lanzadas (E-MIX-B, kernel cognia-emixb-brazoa)

1. Merge canónico: `model.dequantize()` nativo de transformers (no loop manual).
2. **Verificación DURA post-merge** (lección clave): V1 = normas de 3 tensores
   deben diferir de la base (aborta si no); V2 = eval G3/G5 del merged pelado
   ANTES de continuar (además mide si etapa-1 aprendió identidad — dato que
   E-MIX no midió). Regla nueva del programa: **ningún merge se acepta sin
   verificación post-merge**; E5 hereda este guard obligatorio.
3. Reusa el adapter a_etapa1 YA entrenado y tok_etapa2 del kernel E-MIX
   (kernel_sources) — solo re-corre merge + etapa-2 + eval (~2 GPU-h).

## Números operativos

- Replay on-policy: 800 prompts → 664 aceptados (83%), 99.7 min de generación
  batched (cara: ~1/3 del wall del kernel; para la corrida final conviene
  cachear el replay como dataset).
- Trains: brazo B 303 steps @467 tok/s; a_etapa1 206 @485; a_etapa2 100 @425.
- El merged fp16 se borra tras usarse (no entra en los 20 GB del output).

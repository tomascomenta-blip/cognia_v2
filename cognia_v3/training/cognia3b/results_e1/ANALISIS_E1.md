# E1 — Ablación de método: análisis y veredicto (con E1b corregido)

Kaggle 1×T4. E1 (entrenamiento, 85.9 min) + E1b (re-eval con instrumento corregido, 18.5 min).
Dataset: e1_train = 1.344 pares (D1 identidad 1.183 + tooluse 161). 5 brazos, misma seed.

## El confound de E1 y su corrección (E1b)

E1 evaluó con `apply_chat_template` SIN system → el template de Qwen2.5 inyecta el default
"You are Qwen, created by Alibaba Cloud", que hacía que el oráculo G3 (`not_any` qwen/alibaba)
fallara contra CUALQUIER modelo. **E1b re-evaluó los mismos adapters (sin re-entrenar) con
system neutro pareado** ("Eres un asistente útil." / "You are a helpful assistant.", idéntico
para base y brazos). Los números de abajo son los de E1b (los válidos).

## Resultados (E1b, instrumento corregido)

| Brazo | runtime | G1 no-reg | G3 identidad | G5 español | tooluse | tok/s train | veredicto |
|---|---|---|---|---|---|---|---|
| **t_r16_all** | transformers | +4pp PASA | **100%** | 56% | 0→100% | 413 | **COLUMNA** |
| t_dora_r16 | transformers | +4pp PASA | 100% | 56% | 0→100% | 220 | candidato (−47% tok/s) |
| u_r16_all | unsloth | +4pp PASA | 50% | 56% | 0→100% | 504 | descartado (G3) |
| u_r16_neft | unsloth+NEFT | +5pp PASA | 55% | 56% | 0→100% | 504 | descartado (G3) |
| u_r8_qkvo | unsloth | +1pp PASA | 0% | 60% | 0→100% | 687 | descartado (G3) |
| base | — | — | 0% | 60% | 0% | — | — |

Base: G1 89%, G3 0% (no se conoce como Cognia), G5 60%, tooluse 0%.

## Lo que E1 PRUEBA (positivo, real)

1. **La habilidad objetivo entrena limpio**: tool-use ACCION 0→100% en los 5 brazos (N=10
   direccional) con solo 1.344 pares y ~10 min de T4/brazo.
2. **Sin olvido catastrófico**: G1 (no-regresión general, N=100) pasa en todos (+1..+5pp).
3. **La identidad se aprende**: G3 0→100% en el método ganador (base no dice "Cognia" nunca).
4. **P-E1b CONFIRMADA**: DoRA cuesta −47% tok/s → descartado como columna (regla de costo).
5. **El método columna elegido por la regla pre-registrada**: **t_r16_all** (transformers,
   LoRA r16 all-linear) — pasa G1+G3+G5, tooluse 100%, 413 tok/s.

## Caveats HONESTOS (no inflar)

- **La comparación runtime está CONFUNDIDA por steps**: transformers usó mb4 = 92 steps,
  unsloth mb8 = 46 steps (mismo dataset, batch más chico = más pasos). El ganador t_r16_all
  vio 2× gradientes (loss 0.877 vs 1.273) → su ventaja en G3 puede ser "más entrenamiento",
  no "transformers > unsloth". **E2 debe re-testear unsloth con steps igualados** antes de
  abandonar el runtime rápido de E0. La decisión de la regla es válida pero su interpretación
  causal no.
- **G5 español bajó levemente**: 56% vs 60% base (pasa el gate −4pp justo, pero regresó).
  Hay que vigilar el español en las etapas siguientes (más replay es-general).
- **tooluse es N=10 direccional**, no significativo (McNemar p=0.125 con 4 discordantes).
  La suite ACCION grande (N≥50) es pre-requisito de las etapas de habilidad reales.
- **P-E1d y NEFTune INCONCLUSOS**: mb distinto invalida la equivalencia de loss; NEFTune dio
  loss idéntica al control (el hook posiblemente no disparó bajo unsloth) — sin señal.

## Decisión para E2 (congelada)

- **Método**: LoRA r16 all-linear (la capacidad extra rinde; DoRA no paga su costo).
- **Runtime**: re-abrir unsloth-vs-transformers con STEPS IGUALADOS en E2 (mini-A/B, 1 GPU-h):
  si unsloth con 92 steps iguala G3, gana por velocidad (E0); si no, transformers.
- **Vigilar**: español (subir replay es-general), y construir la suite ACCION N≥50.

# M0 / G2 — Recall del híbrido a escala: resultado + ANOMALÍA (veredicto auto INVÁLIDO)

> Corrida 2026-06-29 en Colab T4 (sesión g2b), fp16-seguro (sin NaN), 40.3 min, 12 configs, steps=4000.
> Datos: `results_g2/g2_recall_results.json` (descargado incrementalmente, robusto a muerte de sesión).

## Lo que pasó (medido)
Las 12 configs del sweep (ratio 0→100% attn, arreglo, ventana) **TODAS** terminaron en recall **≈0.09-0.10**
(azar = 0.031). Incluyendo:
- lineal puro (0% attn): 0.099
- **atención PURA (100% attn = transformer denso = RAMA B): 0.095** ← clave
- el mejor: arr_attn_first 0.105. Ninguna cruzó el objetivo 0.8.

El `best_acc` de la atención pura fue **0.092 — nunca subió de azar** (no es "lento", es "no aprende").

## Por qué el veredicto automático es INVÁLIDO (regla 10×)
El script concluye "ninguna config cruzó → el recall exige atención plena (RAMA B)". **Eso es un
overclaim/error**: si la atención PURA (el mejor caso posible para recall asociativo — un transformer
estándar que forma induction heads) tampoco cruza, entonces el experimento mide **undertraining/
optimización, NO la capacidad de la arquitectura**. La regla dura del lab: **no aceptar un "nada cruza"
como límite real cuando el best-case también falla** — es señal de error propio, no de la arquitectura.

Evidencia de que la atención SÍ puede con esta tarea (luego es optimización, no capacidad):
- En el smoke tiny (d=64, 4 capas, 200 pasos) la atención pura SUBÍA a 0.17-0.19 (sobre azar 0.0625).
- La literatura (induction heads / MQAR): un transformer forma recall asociativo de ~32 pares fácilmente.

## Hipótesis a falsar (diagnóstico en curso, `m0_g2_ae1_diag.py`)
A esta escala (d=256, 12 capas, n_pairs=32, n_vals=32, L=80, lr=1e-3, warmup=200) la atención pura no
aprende. Candidatos (probar 10×, ir a la raíz):
1. **LR demasiado alto** para 12 capas d=256 (1e-3 con 200 de warmup) → diverge a un mínimo trivial
   (predecir la marginal de los valores ≈ 0.10). Test: lr ∈ {3e-4, 1e-4}.
2. **Profundidad sin estabilización** (12 capas, sin LR-schedule decreciente) → optimización difícil.
   Test: menos capas (2-4) atención pura.
3. **fp16-safe a escala**: descartar que el path fp32-core rompa algo a d=256 (improbable: el smoke OK).
   Test: fp32 puro.
4. **Más pasos**: 4000 quizás insuficiente si forma induction tarde (pero best_acc plano sugiere que no).

## RESOLUCIÓN (2026-06-29) — es GROKKING: la tarea SÍ se resuelve, pero tras una transición tardía
Validación LOCAL decisiva (CPU, sin riesgo de Colab; atención pura, tarea chica d=64/n_pairs=6/n_vals=8,
lr=3e-4, SIN plateau-stop, 4000 pasos):
```
step 333-3330:  acc ~0.35  (meseta larga, sobre azar 0.125 pero sin resolver)
step 3663:      acc 0.793   <- transición ABRUPTA
step 3996:      acc 0.967   (RESUELTO)
```
→ **El recall asociativo GROKEA**: meseta larga a acc baja y luego salto súbito a >0.9. Esto explica TODO:
- El "ninguna config cruza" del sweep era un **FALSO NEGATIVO**: (a) mi **plateau early-stop cortaba a los
  learners en ~2080 pasos**, en plena meseta; (b) los runs de Colab estaban deadline-capeados a ~3150-4000
  pasos, **justo antes/sobre la transición** (que a escala mayor llega aún más tarde).
- La regla 10× evitó el overclaim: casi fijo "RAMA B por recall" sobre un artefacto de medición.

**Correcciones aplicadas:**
1. `m0_g2_recall_colab.py`: `plateau_stop` ahora **DEFAULT OFF** (era letal para grokking). Sólo se corta
   por ÉXITO o deadline.
2. Para el veredicto de arquitectura (mínima cuota de atención) hace falta entrenar LARGO y ESTABLE
   (cada config debe poder cruzar su transición). **Colab free es DEMASIADO INESTABLE** (murió a 13-67 min
   en 3 sesiones) → ese sweep largo es candidato para **Kaggle** (sesiones 9-12 h, briefing §4), no Colab.

**Hallazgo para el goal de VELOCIDAD (importante):** el costo de convergencia de esta tarea = **cruzar la
transición de grokking**. Entonces **data-efficiency = acelerar el grokking** (menos pasos hasta el salto)
es una palanca de velocidad DIRECTA y MEDIBLE (la literatura: weight-decay y LR son los aceleradores
clásicos del grokking). Candidato fuerte para el ledger de palancas.

## Implicación para el goal (velocidad)
G2 NO está cerrado como veredicto de arquitectura, PERO la corrida ya entregó valor al goal de VELOCIDAD:
fp16-seguro corre 40 min sin NaN para 12×4000 pasos en T4. El diagnóstico de "por qué la atención no
aprende a escala" es directamente relevante al harness de entreno (si lr=1e-3 no entrena un 12-capas,
el harness necesita LR-schedule/tuning — un hallazgo de entrenabilidad, no solo de recall). G1 ya había
inclinado el backbone a RAMA B por la banda de decode; G2 como gate de recall queda PENDIENTE de un
setup de entreno que SÍ aprenda.

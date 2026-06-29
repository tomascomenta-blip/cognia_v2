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

## Implicación para el goal (velocidad)
G2 NO está cerrado como veredicto de arquitectura, PERO la corrida ya entregó valor al goal de VELOCIDAD:
fp16-seguro corre 40 min sin NaN para 12×4000 pasos en T4. El diagnóstico de "por qué la atención no
aprende a escala" es directamente relevante al harness de entreno (si lr=1e-3 no entrena un 12-capas,
el harness necesita LR-schedule/tuning — un hallazgo de entrenabilidad, no solo de recall). G1 ya había
inclinado el backbone a RAMA B por la banda de decode; G2 como gate de recall queda PENDIENTE de un
setup de entreno que SÍ aprenda.

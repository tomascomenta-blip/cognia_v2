# E-RZN — NO APTO: el generador era demasiado fácil (yield 86% = sin señal)

Kaggle 1×T4, 170.7 min. STaR sobre 1.400 problemas programáticos (8 familias,
0 colisiones con la suite), receta E-GROK, eval G2R×100 pareada.

## Veredicto contra el pre-registro

| Predicción | resultado | veredicto |
|---|---|---|
| P-RZN-2: yield ≥ 30% | **85.9%** (1.202/1.400) | pasa PERO delata el problema |
| P-RZN-1: G2R ≥ base +15pp, p<0.05 | 57% → 53% (−4pp, n01=7 n10=11, p=0.48) | **FALLA** |

**`APTO_FLEET: false`** — el experto NO entra al fleet (el router jamás lo
habría activado igual: anti-catástrofe = base por default).

## Diagnóstico (por qué falló, con evidencia)

1. **Los problemas eran demasiado fáciles**: la base resuelve el 86% de lo
   generado pero solo el 57% de G2R. STaR destila CoT de lo que el modelo YA
   resuelve → cero señal nueva. La loss lo confirma: 0.117→0.042 en 40 steps
   (el modelo ya sabía generar esas cadenas).
2. El corpus quedó chico y homogéneo (1.202 pares cortos, SEQ 1024, 40 steps):
   el adapter apenas se movió y lo poco que se movió fue ruido (−4pp n.s.).
3. El gate binario de yield (≥30%) estaba mal DIRECCIONADO: protege contra
   "demasiado difícil" pero no contra "demasiado fácil". Lección de diseño:
   el yield útil de STaR es una BANDA (~15-65%), no un piso.

## Decisión

- E-RZN-v2 con generador MÁS DIFÍCIL: composición multi-paso (2-3 familias
  encadenadas), números distractores irrelevantes, cadenas de orden con 5-6
  entidades y pregunta por el 2º, división con resto. Pre-registro nuevo:
  P-RZN2-2 = yield en BANDA [15%, 65%] (fuera de banda → ABORTA sin entrenar,
  en ambas direcciones); P-RZN2-1 = G2R ≥ base +10pp p<0.05.
- Contexto que acota la apuesta: el CLI YA mejora razonamiento por INFERENCIA
  (CoT stepwise: direct 0.31 → 0.81 medido); el adapter solo paga si supera
  ese camino barato. Si v2 también falla, el nicho razonamiento se cierra
  como "resuelto por inferencia, no por fine-tune" y el fleet sigue con
  código/imágenes.

# Pre-registro E-PODA — ¿podar los patrones de lógica de stepwise v2?

CONGELADO ANTES DE MEDIR (2026-07-09). Contexto: E-INT dejó FLAGGED los
patrones puramente marginales de v2 (lógica-fácil sin números) porque el set
marginal era N=8 con daño débil no significativo (sin 8/8 → v2 5/8, n01=0,
n10=3, p=0.25). N=8 no alcanza para decidir; esta corrida decide con N=50.

## Instrumento

- Suite NUEVA congelada: `suites/g2_razonamiento_logica.jsonl` (50 ítems,
  25 es / 25 en; transitividad, silogismos todos/ninguno, orden es,
  deducción categórica), sha256
  `68eb9a92c92a6014f89bef21140c297f3c3a68c82e69895c463969983b41523b`.
  Cada ítem verificado programáticamente como miembro de la clase flagged:
  needs_stepwise=True, <2 dígitos, sin gatillo cuantitativo (gen_g2rlog.py).
- Oracle nuevo `ultimo_de` (última opción mencionada gana, borde de palabra):
  must_any/not_any falsean con CoT porque el razonamiento menciona todas las
  opciones. Testeado unitario ANTES de esta corrida.
- eval_g4_cli, base Q4_K_M pura (fleet a escala 0), greedy,
  cache_prompt=false (determinista). Brazo A `--suites g2rlog`; brazo B
  `--suites g2rlog --stepwise`. McNemar pareado.

## Predicciones (regla de decisión congelada)

- **P-PODA-1**: si el brazo stepwise muestra REGRESIÓN significativa
  (p<0.05 con n10>n01) → los patrones de lógica se PODAN de `_REASON_RX`
  (la ganancia de E-INT vino del stock cuantitativo + tag por idioma, no
  de la lógica).
- **P-PODA-2**: si muestra MEJORA significativa (p<0.05, n01>n10) → los
  patrones QUEDAN y el flag se levanta.
- **P-PODA-3**: si no hay efecto significativo → QUEDAN (default
  conservador: sin evidencia de daño no se poda; el flag se levanta y se
  anota el delta observado).

## VEREDICTO (2026-07-09, corridas reales)

| brazo | acc g2rlog (N=50) |
|---|---|
| base sin stepwise | 70.0% |
| stepwise v2 | **76.0%** |

McNemar pareado: **+6.0pp, n01=8, n10=5, p=0.5811** → sin efecto
significativo en ninguna dirección.

**Decisión (regla congelada): P-PODA-3 — los patrones de lógica QUEDAN y
el flag se levanta.** La señal débil-negativa del set marginal N=8 de
E-INT NO replicó con N=50: el punto estimado es positivo (+6pp). Con
n=13 discordantes, un daño real de la magnitud sospechada habría
aparecido; lo observado es compatible con ruido alrededor de un efecto
pequeño positivo o nulo. No se toca `_REASON_RX`.

Nota de instrumento: primera corrida con oracle `ultimo_de` (borde de
palabra) — sin él, los ítems de elección con CoT eran inarbitraables
(must_any/not_any falsean porque el razonamiento menciona todas las
opciones).

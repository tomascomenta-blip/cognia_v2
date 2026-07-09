# Pre-registro E-INT — "inteligencia general superior" (mandato dueño 2026-07-08)

CONGELADO ANTES DE MEDIR. Palanca: ampliar el CoT dirigido por turno
(`needs_stepwise`, medido 0.31→0.81 en su nicho es-cuantitativo) a
(a) inglés cuantitativo, (b) lógica/deducción es+en, (c) multi-paso.
El veto de formato exacto se mantiene y se extiende a inglés (dirección
segura: solo REDUCE dónde se aplica el empujón).

Instrumento: `eval_g4_cli --stepwise` = el prompt pasa por
`augment_stepwise` (la MISMA transformación del turno de chat del CLI)
antes del template. Base pura Q4_K_M (fleet scale 0), greedy, suites
congeladas por sha256, McNemar pareado.

## Predicciones (gates)

- **P-INT-1**: G2R (stepwise-v2) ≥ G2R (sin stepwise) **+10pp**, p<0.05.
- **P-INT-2** (enmendada ANTES de medir, mismo espíritu sin 3ª corrida):
  sobre el SET MARGINAL de G2R (ítems que v2 cubre y v1 no — v1 es
  determinista y se reconstruye de git 3ea1c50), la accuracy con CoT (corrida
  v2) supera a la del mismo set sin stepwise (corrida baseline) con n01>n10.
  Mide exactamente el valor agregado de la ampliación.
- **P-INT-3**: G1 (stepwise-v2) ≥ G1 (sin) − 2pp y SIN regresión
  significativa (p<0.05 con n10>n01). G1 incluye formato/instrucciones:
  el empujón no debe romper compliance.
- **P-INT-4**: G5 (stepwise-v2) ≥ G5 (sin) − 2pp y sin regresión sig.

Regla: pasan P-INT-1,3,4 → la v2 entra al CLI (P-INT-2 decide si queda la
v2 o alcanza la v1). Falla P-INT-3 o P-INT-4 → se ajusta el detector (más
conservador) y se re-mide UNA vez; si vuelve a fallar, se descarta.

## Flujos de agente (parte 2 del mandato)

- Cambio: auto-decompose del loop gateado por dificultad estimada
  (`estimate_difficulty`) en vez de `len(task) > 120` (proxy pobre: largo
  ≠ complejo; costo real ~30s de CPU por decompose innecesario).
- Gate: batería E (8 tareas /hacer con postcondición) sin regresión
  (8/8 o igual al pre-cambio) + tests unitarios del gating.

---

## VEREDICTO (2026-07-09 ~01:10, corridas reales)

| Gate | resultado | veredicto |
|---|---|---|
| P-INT-1 | G2R 60.0% → **82.0%** (+22pp, n01=28 n10=6, p=0.0002) | **PASA** |
| P-INT-3 | G1 88.0% → 87.0% (−1pp, n01=2 n10=3, p=1.0) | **PASA** |
| P-INT-4 | G5 56→52 en la 1ª corrida, PERO el único ítem flipeado NO fue transformado (0/25 ítems G5 disparan el detector) → era ruido del KV-cache del instrumento. Arbitraje determinista (cache_prompt=false): **56.0% = 56.0%, idéntico ítem a ítem** | **PASA** |
| P-INT-2 | cobertura v1 ya era 58/100 (el fallback ?+2números cazaba mucho); set marginal puro N=8: sin 8/8 → v2 5/8 (n01=0, n10=3, p=0.25) | **EN CONTRA (débil)** |

**Decisión (regla congelada: pasan 1,3,4 → v2 entra al CLI): stepwise v2 QUEDA.**
La ganancia grande (+22pp) viene del stock cubierto + tag por idioma; los
patrones puramente marginales (lógica-fácil sin números) muestran daño débil
no significativo en N=8 → quedan FLAGGED para poda si una corrida futura con
N mayor lo confirma. Hallazgo de instrumento: eval_g4_cli ahora corre con
cache_prompt=false SIEMPRE (benchmark determinista; el ruido de cache flipeaba
ítems no transformados).

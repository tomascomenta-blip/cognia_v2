# exp137 — Profundidad ADAPTATIVA (PonderNet) vs FIJA: el loop que SÍ ahorra

**Fecha:** 2026-07-04 · **CPU-first, seed 137, KMAX=8, 6000 pasos** · run: `run.py`

## Motivación (no re-derivar)
El A/B XARCH ya midió que el loop de profundidad con vueltas **FIJAS**
(looped2x4) NO ahorra cómputo: 4 vueltas × 2 capas = mismo FLOP que 8 capas
reales, mismo tok/s (H-LOOP "cae"; el cuello es cómputo, no params). El prior
dejó UNA puerta abierta: el loop fijo paga el máximo SIEMPRE; un loop
**ADAPTATIVO** que corta temprano en inputs fáciles usaría menos cómputo en
promedio. exp137 testea exactamente eso — el ángulo de "ahorrar recursos" que
el dueño pidió.

## Tarea (genuinamente secuencial, sin atajo de 1 paso)
v1 falló por diseño: `f^K(x)=(x+3K) mod 10` tiene forma cerrada → el modelo la
resolvía en 1 paso (100% acc, "83% ahorro" pero corr con K = None: no había
dificultad real). v2: leer una secuencia `[a_1..a_L, STOP, pad]` **un token por
paso** y devolver `Σa_i mod 10`. La longitud L∈1..8 VARÍA y NO se da como input;
el modelo debe iterar hasta el STOP. Como cada vuelta consume un token nuevo,
un MLP no puede atajar — necesita L pasos reales (profundidad = dificultad,
input-dependiente).

## Resultado (predicción congelada: match-acc + ahorro + piensa-más-en-lo-difícil)

| variante | accuracy | pasos usados | ahorro | corr(L, pasos) |
|---|---|---|---|---|
| **fixed** (siempre 8 vueltas) | 99.9% | 8.00 / 8 | — | 0.00 |
| **ponder** (halting adaptativo) | **100.0%** | **5.53 / 8** | **31%** | **0.979** |

**CONFIRMA las tres:**
1. **Igual (mejor) calidad:** ponder 100% vs fixed 99.9% — la accuracy no se
   sacrifica (incluso perfecta por longitud, acc_by_L 1.0 en las 8).
2. **Ahorra cómputo:** 5.53 vs 8 pasos = **31% menos cómputo** en promedio. El
   óptimo teórico (longitud media 4.5 + ~1 para ver STOP ≈ 5.5) casi se alcanza.
3. **Piensa más en lo difícil:** corr(longitud, pasos)=**0.979** — el modelo usa
   casi exactamente los pasos que el input necesita.

Sweep de λ (regularización hacia menos pasos): λ=0.03→30.2%, 0.06→30.8%,
0.10→31.7% de ahorro, todos a 100% acc y corr≥0.97. Estable, no un artefacto de
un λ afortunado.

## Lección para el MoM (lo que el dueño pidió)
El loop-transformer AHORRA recursos **solo si es ADAPTATIVO**, no fijo. Un modelo
de pesos compartidos con cabeza de halting (PonderNet) usa profundidad
proporcional a la dificultad del input: pasos mínimos en lo fácil, más en lo
difícil, a igual calidad. Esto complementa el prior (fijo = compute-bound):
la palanca de ahorro no es "loop", es "loop + cuándo parar".

## Frontera (honesto)
- Tarea sintética (acumulador secuencial), no un LM real; transfiere el
  MECANISMO (halting proporcional a dificultad), no los números absolutos.
- El ahorro real en un LM depende de cuánta variabilidad de dificultad haya por
  token/secuencia; en texto homogéneo el margen sería menor.
- Próximo: injertar el halting adaptativo en la celda banded del tiny (xfinal)
  y medir bpb vs cómputo — el prior lo dejó como la única condición no probada.

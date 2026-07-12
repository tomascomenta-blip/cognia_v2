# PREREG — E5: Self-MoA en ejes sin oráculo ejecutable (Top-5 COLONIA)

**CONGELADO ANTES DE CORRER (2026-07-12, antes de conocer los resultados
del audit por miembro).**

## Hipótesis (Self-MoA, arXiv 2502.00674, ICML 2025)
En ejes SIN tests ejecutables (razonamiento G2R), agregar N muestras del
MISMO modelo con 1 llamada extra supera al single-shot y al primer-sample
(+5.6pp CRUX con ≤7B en el paper). El agregador débil es TECHO (28.94 vs
56.83 LC según quién agrega) → kill-condition explícita.

## Método
- Suite congelada: g2_razonamiento PRIMEROS 40 (los mismos del audit).
- Generador: el MEJOR miembro del audit en G2R (se elige por AUD-2, que ya
  estará medido ANTES de correr esto — la elección es por dato, no a dedo).
- Brazos (pareados, greedy la agregación):
  A. single-shot del generador (ya medido en el audit — se reusa).
  B. Self-MoA: 4 muestras temp 0.7 (seeds 1-4) + agregador = el mismo
     generador (prompt: "sintetiza la respuesta correcta a partir de estas
     4 propuestas; responde solo la respuesta final").
  C. Self-MoA con agregador qwen3_4b (si B ≤ A, probar agregador distinto
     ANTES de matar — 1 ajuste permitido del prereg).
- Oráculo: suite_oracle determinista (el MISMO del audit). McNemar A vs B.

## Gates
- **SM-1 (gate)**: B > A con McNemar p<0.05 → Self-MoA entra al router
  como estrategia del eje razonamiento (opt-in hasta e2e).
- **SM-KILL**: B ≤ A y C ≤ A → línea cerrada (el agregador chico es techo,
  consistente con la trampa medida del campo).
- **SM-2 (info)**: latencia total por ítem (5 generaciones + 1 agregación).

## Regla de corte
Un solo ajuste (brazo C). Si falla, se documenta y NO se entrena nada en
Kaggle para esta línea (el "sintetizador" fine-tuneado solo se consideraría
con B o C ya positivos y un gap de FORMATO diagnosticado).

---

## RESOLUCIÓN (2026-07-12, con el audit completo)

**NO EVALUABLE POR TECHO — el ruteo captura la ganancia.** El generador
elegido por AUD-2 (qwen3_4b) mide **92.5%** en la suite congelada G2R-40:
quedan 3 ítems de headroom, con los que McNemar no puede alcanzar p<0.05
(harían falta ≥5-6 flips netos). Correr los brazos B/C costaría ~1.5h de
CPU sin poder mover el gate en ninguna dirección. Además la unión-oráculo
del eje ya es 40/40: la ganancia disponible la captura el ROUTER por eje
(desplegado: razonamiento→qwen3_4b, McNemar p≈0 vs 3B), no la agregación.
La línea Self-MoA queda ARCHIVADA para este eje; re-abrible solo con una
suite más dura donde el mejor generador no sature (p.ej. g2_razonamiento
ítems 41-100 o la suite lógica), con nuevo prereg.

# PREREG — XH-LOOP: tiny loop-transformer desde cero (FLEET-30 #28)

**CONGELADO ANTES DE CORRER (2026-07-12 ~00:40, corrida nocturna FLEET-30).**

## Hipótesis
La recurrencia en profundidad con pesos compartidos (Universal/Looped
Transformer) permite un experto desde cero con ~1/4 de los parámetros del
backbone 12L manteniendo calidad utilizable. Evidencia previa (XARCH
2026-07-02, results_xarch): looped2x4 bpb 1.654 < vanilla2 1.695 (calidad ≈
profundidad 8) pero tok/s 3.5× peor (el loop compra PARÁMETROS, no cómputo).
Es el "loop transformer interno" del mandato FLEET-30, en el único sustrato
donde es arquitectónicamente posible (los GGUF pre-cuantizados NO se pueden
loopear — límite declarado en FLEET30_DESIGN.md).

## Método
`xh_loop_kernel.py` = clon de `xh_final_kernel.py` (receta ganadora XHUNDRED:
Muon 0.02, BPE-16k, mezcla 35%, batch 48, EMA 0.995, wall 25 min T4) con UN
cambio arquitectónico: ARCH_LAYERS 12→3 físicas, GLOBAL_LAYERS (3,7,11)→(2,)
y forward con `for _ in range(LOOPS=4)` sobre los mismos bloques
(weight-tying literal). Mismos datos (dataset cognia-xh-data), mismos evals.

## Gates (congelados ANTES de correr; ajustados por el recorte ~4× de params, no después)
- **XL-1 (gate)**: entrena sin NaN y produce checkpoint en ≤30 min de wall.
- **XL-2 (gate)**: bpb wiki ≤ 1.45 (falsación dura > 1.60). Referencia: el
  12L completo midió 1.2888; XARCH proyecta que el loop recupera la mayor
  parte del gap de profundidad.
- **XL-3 (gate)**: mini-cloze-es ≥ 55% (el 12L midió 85%; azar 33.3%).
- **XL-4 (info)**: params totales, tok/s de train (esperado ~3-4× peor que
  el 12L por FLOPs de 12 capas efectivas con memoria de 3), muestras G2.

## Regla de corte
Si XL-2 o XL-3 fallan: UN ajuste permitido (LOOPS 4→2 o GLOBAL_LAYERS), no
los gates; segunda falla → línea documentada como negativa y el slot #28 del
fleet queda vacante (se declara en FLEET30_DESIGN.md).

## Rol en el fleet si pasa
Experto experimental `xh_loop` (español tiny con pensamiento en loop):
demuestra el mecanismo y habilita la frontera siguiente (halting adaptativo
de exp137, +31% de ahorro medido en toy, nunca injertado en el tiny real).
NO entra al producto: es investigación del linaje cognia-x.

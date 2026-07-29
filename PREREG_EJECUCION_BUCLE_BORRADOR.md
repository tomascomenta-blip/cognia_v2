# BORRADOR de prereg — Señal por EJECUCIÓN EN EL BUCLE (marco nuevo, iteración 1)

**Estado: BORRADOR, 2026-07-29 (sesión matinal). NO corre hasta tener
umbrales cerrados + revisión adversarial.** Es la vía que quedó como única
viva tras cerrar el contrato ciego (4 KILL: corregido ×2, validado, QA-fuerte
con dos modelos) y los votos de consenso (2 vueltas, regla pre-fijada de no
más variantes). Referencias: memoria contrato-interno-al-azar,
PREREG_CONSENSO2 (mecanismo: los inventos viven en los VALORES de los
checks), PREREG_QA_FUERTE (baselines de FN/FP por marco ciego).

## La enfermedad que este marco ataca (medida)

El contrato ciego se escribe desde idea + inventario DOM, ANTES de ver la
página comportarse. Consecuencia medida: expectativas con VALORES inventados
(esperado exacto que el enunciado no fija) → FN ~50% sobre páginas sanas
(condena lo que no coincide con su invento) y FP 32-50% (aprueba vacuidades).
Dos familias de modelos con el mismo perfil ⇒ es el MARCO, no el pensador.

## La idea (qué cambia exactamente)

Separar PREDICCIÓN de JUICIO. El marco ciego obliga al pensador a PREDECIR
valores exactos; el marco nuevo lo pone a OBSERVAR y JUZGAR:

1. **Sondeo:** dado el enunciado + inventario, el pensador propone K acciones
   de sondeo (click, escribir, tecla, esperar) con QUÉ mirar después de cada
   una (selectores a leer) — sin ninguna aserción todavía.
2. **Ejecución:** el harness corre las sondas con Playwright sobre la página
   REAL y devuelve lo OBSERVADO (valores de los selectores antes/después,
   texto visible, conteos).
3. **Juicio:** con el enunciado + lo observado, el pensador dictamina por
   sonda: CORRECTO / INCORRECTO / IRRELEVANTE respecto del enunciado, con
   una frase de porqué. El veredicto de la página = alguna agregación
   (p. ej. INCORRECTO en ≥1 sonda relevante → reprobada).

El punto: ya no hay valores inventados — hay comportamiento observado y un
juicio de conformidad contra el enunciado. El modo de fallo esperado cambia
de FN-por-invento a FP-por-complacencia (aceptar lo que ve). ESO es lo que
el A/B mide.

## Diseño de medición (sobre datos CONGELADOS, mismo protocolo que QA-fuerte)

- Corpus: las mismas 24 muestras juzgadas del piloto QA (estricto conocido,
  aciertos del marco ciego: gpt-oss 8/24, coder-14b 10/24; FN 14-15/19,
  FP 0/5 y 0/5). Mismo pensador (gpt-oss-20b) para aislar EL MARCO.
- Por muestra: ronda de sondeo (1 llamada LLM) → ejecución Playwright →
  ronda de juicio (1 llamada LLM). ~48 llamadas + 24 ejecuciones.
- **Piloto de futilidad pre-registrado (la lección de Nemotron):** 6 muestras
  primero; si el marco no emite sondas ejecutables en ≥4/6 o el juicio
  degenera (siempre CORRECTO / siempre INCORRECTO en las 6), KILL de aptitud
  sin gastar el bloque.
- Métrica primaria: aciertos/24 contra estricto congelado. Secundarias:
  FN/19, FP/5, nº de sondas ejecutables, tasa de complacencia (INCORRECTO
  declarado en muestras estricto=False).

## Umbrales PROPUESTOS (a cerrar con revisión antes de correr)

| lectura | veredicto |
|---|---|
| aciertos ≥ 16/24 y FP ≤ 1/5 | VIVA: pasa a validación sobre las 96 del BoN antes de declarar nada |
| aciertos 12-15/24 | GRIS: mejor que el ciego (8-10) pero sin señal usable; iterar el juicio, no el sondeo |
| aciertos ≤ 11/24 | KILL de la iteración (indistinguible del ciego) |

Nota honesta pre-declarada: 16/24 con FP bajo sería la PRIMERA señal
autogenerada por encima del azar en este proyecto; la validación en las 96
muestras del BoN y en banco fácil es requisito antes de cablear nada.

## Piezas que ya existen (inventario, verificado hoy)

- Playwright + juez con acciones click/escribir/tecla/esperar y lectura de
  selectores: `juez_ejecutable._ejecutar_paso` — el ejecutor de sondas es
  un subconjunto de lo que ya corre.
- El extractor endurecido de JSON del pensador (`_json_de_respuesta`, con
  corte de <think>): reusable para las dos rondas.
- Presupuesto de pensamiento: max_tokens 12000 + reasoning_effort según
  presupuesto-tokens-razonamiento (margen 2-3× + un reintento).
- Baselines congelados y estrictos de las 24 muestras del piloto QA.

## Riesgos declarados

- **Complacencia:** el pensador ve el comportamiento real y lo bendice. Se
  mide directo (FP y tasa de complacencia); el prompt de juicio debe pedir
  dictamen contra el ENUNCIADO, nunca "¿parece razonable?".
- **Sondas no ejecutables** (selectores inventados): se mide en el piloto de
  futilidad; el sondeo recibe el MISMO inventario DOM que el marco ciego.
- **Coste:** 2 llamadas LLM + 1 ejecución por muestra ≈ 2× el contrato
  ciego. Se paga solo si la señal aparece.
- **Fuga:** el pensador NO ve el contrato original ni el held-out; solo
  enunciado + página. Mismo aislamiento que el piloto QA.

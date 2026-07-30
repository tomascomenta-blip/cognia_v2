# PREREG — ¿Cuánta varianza es del JUEZ? (re-juzgado triple, cero GPU)

**Fecha:** 2026-07-30 ~00:25, sesión tarde-noche 29→30. **Escrito ANTES de
correr.** Cierra la caracterización del instrumento que empezó con
PREREG_LAZO_VS_REPLAY (RESULTADO: concordancia 13/24 = 54% con el MISMO
prompt; el mismo lazo midiendo 92/79/58% en una tarde).

## Pregunta

Esa varianza tiene dos fuentes posibles: el GENERADOR (el modelo produce
páginas distintas con el mismo prompt) y el JUEZ (la misma página recibe
veredictos distintos). La segunda sería mucho más grave: contaminaría
TODA medición hecha esta semana, incluidos seis KILL. Se separa
re-juzgando páginas CONGELADAS: si el juez es determinista, la varianza
observada es del generador y las conclusiones apareadas se sostienen.

## Diseño (cero GPU, cero generación)

- Corpus: las **24 páginas del brazo LAZO** de `b2_lazo_vs_replay`
  (guardadas hoy, con su veredicto estricto ya medido = evaluación #1).
- Se re-juzgan **2 veces más** con el mismo código, mismo contrato
  original y mismo held-out (evaluaciones #2 y #3), cada juzgado bajo
  presupuesto de pared propio (300 s).
- Métrica primaria: **% de páginas con veredicto estricto NO unánime** en
  las 3 evaluaciones.
- Secundarias: discordancia por contrato (original vs held-out por
  separado — para ver si el ruido vive en un examen concreto);
  discordancia por check (qué checks cambian de resultado); páginas que
  cuelgan el juez en una evaluación y no en otra.

## Umbrales (fijados ahora)

| páginas no unánimes | veredicto |
|---|---|
| ≤ 1/24 (≤4%) | **JUEZ ESTABLE**: la varianza medida es del GENERADOR. Las conclusiones apareadas de la semana se sostienen tal cual; la regla operativa (netos apareados sí, niveles entre corridas no) queda confirmada |
| 2-3/24 (8-13%) | ruido de juez MODERADO: toda tasa lleva ese error de fondo; los netos con margen ≤2 pasan a ser no concluyentes retroactivamente |
| ≥ 4/24 (≥17%) | **JUEZ INESTABLE**: hay que arreglar el instrumento antes de cualquier medición futura, y los KILL con margen estrecho deben re-examinarse |

- El resultado NO cambia ningún veredicto ya firmado por sí solo: dice
  con cuánto error de fondo hay que leerlos.
- Si una página cuelga el juez en una evaluación y no en otra, cuenta
  como no unánime (es varianza real del instrumento).

## RESULTADO (2026-07-30 ~01:00 — completo, veredicto por umbrales pre-fijados)

**JUEZ ESTABLE, en el extremo del rango: 0/24 páginas no unánimes (umbral
≤1).** Ni por contrato original (0/24) ni por held-out (0/24), y **el
conteo `checks_ok` es idéntico en las tres evaluaciones de las 24
páginas** — o sea, no es que el binario aguante por suerte: el juez
reproduce check a check.

**Consecuencia (la que importa):** la varianza medida esta semana —
concordancia 54% con el mismo prompt, ±34 pts entre corridas del mismo
sistema — es **del GENERADOR, no del instrumento**. Por tanto:

- Los netos apareados de toda la cadena (fases 1-3, discrepancia,
  validez, los seis KILL de señal) **no están contaminados por ruido de
  juez**: se sostienen tal cual.
- La regla operativa se confirma sin matices: **apareado intra-corrida =
  evidencia; niveles entre corridas = arena.**
- Y refuerza el mecanismo del BoN: si el juez es exacto y la dispersión
  es del generador, **elegir entre muestras es exactamente la palanca
  correcta** (por eso K=4 lleva 71%→100%), y el cuello sigue siendo tener
  con qué elegir en tareas nuevas.

## Presupuesto

24 páginas × 2 evaluaciones × 2 contratos × ~12-25 s ≈ **25-40 min**, solo
Playwright. Corre con la GPU libre tras el KILL de la it.2.

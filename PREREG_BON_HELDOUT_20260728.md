# PREREG — BoN de réplicas independientes con verificador de señal real (held-out)

**Fecha:** 2026-07-28, sesión nocturna 28→29 (ventana hasta 04:30).
**Escrito ANTES de implementar el runner y ANTES de correr nada.**
**Pregunta madre (META):** ¿el muestreo de réplicas independientes de primgen,
elegido por un verificador CON señal real, alcanza el nivel 8/8 del banco
brutal? Es decir: ¿el cuello del goal es el CONSTRUCTOR o la SEÑAL?

## Contexto y priors (todos medidos, con fuente)

1. **BoN k=3 fue KILL el 2026-07-26** (PREREG_BON_RONDAS), pero de un régimen
   distinto: candidatos re-generados DENTRO del lazo con el MISMO prompt y el
   MISMO mockup a temp 0.2 → clones (0/16 rescates). Las réplicas
   independientes rehacen el pipeline entero (mockup nuevo, hints nuevos):
   la diversidad ya está MEDIDA entre réplicas del A/B lazo-vs-primgen
   (brutal, 2026-07-27): hoja_calculo 3/6, carrito_stock 4/6, kanban 6/6,
   buscaminas 6/6.
2. **Subir la temperatura tiene prior EN CONTRA:** 0.9 pierde los selectores
   OBLIGATORIOS del enunciado (1/5 vs 6/7 a 0.2, comentario medido en
   diseno_a_codigo.py:507). Este experimento NO toca la temperatura: la
   diversidad viene de réplicas independientes a la temp de producción (0.2).
3. **El held-out A MANO existe y está validado** para las 4 tareas del brutal
   (b1_contratos_heldout.json, validado contra referencias frontier; FP de
   gpt-oss con él: 0/18, memoria fp-heldout-por-modelo). En la corrida
   2026-07-27 cazó 3/6 aprobados de buscaminas como "pasó el examen, no la
   materia" → el juez honesto es ESTRICTO = original ∧ held-out.
4. **La señal INTERNA autogenerada está muerta** (3 KILL convergentes,
   contrato-interno-al-azar). Este experimento NO la usa ni la re-mide.
5. **Deriva sistémica ~20 pts/12 h** (gate-e2e-flaky): todas las comparaciones
   de este prereg son INTRA-ensayo (las K muestras y el control comparten
   ensayo); ninguna resta usa referencias históricas. Los priors de arriba
   solo dimensionan n, no entran en el veredicto.

## Qué decide este experimento (y qué NO)

- NO adopta código de producción: el held-out es a mano y solo cubre el banco;
  no es un selector desplegable para ideas nuevas.
- SÍ decide INVERSIÓN, con esta lógica pre-registrada:
  - Si el muestreo tiene margen y el held-out lo captura → el cuello del goal
    es FABRICAR señal (QA más fuerte / held-outs generados por un modelo
    mejor), no el constructor. La vía "BoN + verificador" queda VALIDADA como
    arquitectura y el siguiente trabajo es el generador de señal.
  - Si el muestreo NO tiene margen ni con verificador perfecto → la vía BoN
    muere entera (con el KILL del 26 serían dos regímenes muertos) y el cuello
    es el CONSTRUCTOR (modelo o prompt).

## Diseño

- **Banco:** brutal (b1_tareas_brutales.json, 4 tareas). **Sistema:** primgen
  (correr_sistema con max_rondas=1, código de main tal cual, commit sondado).
- **Ensayo** = tarea × réplica: K=4 muestras INDEPENDIENTES de primgen,
  generadas secuencialmente (semilla `{tarea}:r{rep}:s{s}` antes de cada una
  para diversificar hints; el server además muestrea sin semilla fija).
- **R=6 réplicas**, tareas rotadas por réplica (intercalado a nivel tarea;
  el par control/BoN vive DENTRO del ensayo, concurrente por construcción).
  Total: 4×6×4 = 96 generaciones ≈ 2.5–3.5 h (media medida primgen 75 s).
- **Cada muestra se juzga SIEMPRE con los dos contratos** (original y
  held-out, sobre el HTML guardado), aprobado_estricto = ambos aprueban.
- **Brazo control implícito:** la muestra s=1 de cada ensayo (misma corrida,
  mismo reloj; no hay celdas de control separadas).
- **Selector held-out** (elige SIN mirar el contrato original):
  1º aprobado_heldout, 2º checks_ok_heldout, 3º índice menor.
  El elegido se evalúa con aprobado_estricto.

## Métricas pre-registradas (sobre los ensayos válidos, pares discordantes)

- **A — techo del muestreo:** pass@4_estricto (¿alguna de las 4 aprueba
  estricto?) vs control (s=1 estricto). Neto A = ensayos donde pass@4 sí y
  control no, menos lo inverso (lo inverso es imposible por construcción:
  s=1 ∈ las 4; se declara igual por simetría formal).
- **B — arquitectura realizable con señal:** aprobado_estricto del ELEGIDO
  por el selector held-out vs control. Neto B con la misma resta.
- **C — pérdida del selector:** A − B en ensayos (cuántos techos el selector
  no captura).
- **D — FP del contrato original, de paso:** nº de muestras con
  aprobado_original ∧ ¬aprobado_heldout, por tarea (actualiza la memoria
  fp-heldout, no decide nada aquí).

## Umbrales (fijados ahora; n objetivo = 24 ensayos)

| lectura | condición | veredicto |
|---|---|---|
| A | neto ≥ +5 | MARGEN GRANDE: el muestreo alcanza nivel ~8/8 con señal |
| A | +3..+4 | margen moderado (vía viva, dimensionar mejor) |
| A | ≤ +2 | KILL de la vía muestreo: ni el verificador perfecto la salva |
| B | ≥ A−1 | el held-out CAPTURA el margen (selector válido) |
| B | ≤ A−3 | el selector pierde el margen (señal insuficiente aun a mano) |
| B intermedio | A−2 | GRIS, se reporta sin adopción |

- **Cortes parciales:** guardado incremental + `--reanudar`. Si el corte de
  las 04:14 llega antes de R=6, el veredicto usa los ensayos completos; con
  R<3 completas solo se declara DIRECCIONAL (regla n≥6 por brazo: aquí el
  "brazo" es el ensayo pareado; 12 ensayos = mínimo direccional, 24 = pleno).
- **Infra (pre-declarado):** una muestra con EXCEPCIÓN del harness, juez
  crasheado, sin HTML, o backend ≠ :8080/degradado se marca infra y sale del
  pool de selección; si s=1 es infra, el ensayo entero sale del apareado; si
  las 4 son infra, ídem. Conteos de infra se reportan. El fallback de Ollama
  se neutraliza (OLLAMA_MODEL inexistente pisado en runtime, patrón
  b2_ab_gap) para que la degradación sea ruidosa y no una celda envenenada.
- **Nada de mirar resultados intermedios para parar antes** (no hay parada
  opcional); el único corte es el reloj de la sesión.

## Presupuesto y logística

- ~96 gens × ~85 s ≈ 2.3–3 h de GPU + juzgados Playwright (2 contratos por
  muestra, ~10–20 s c/u). Cabe en la ventana con margen para análisis,
  MANAGER_LOG y memoria.
- Runner nuevo: `scripts/b2_bon_heldout.py` (patrón b2_ab_lazo: sondas de
  config en runtime, feromona redirigida, telemetría a SALIDA, incremental,
  `--reanudar`, `--replicas`).
- Revisión pre-lanzamiento: 1 agente sobre (prereg + runner) ANTES de gastar
  GPU, como en las unidades previas.

## PRIMERA ENMIENDA (2026-07-28 ~17:20, tras la revisión y ANTES de correr)

La revisión adversarial encontró 2 bloqueos + 4 arreglos baratos; todos
aplicados al runner antes de lanzar. Cambios que tocan lo pre-registrado:

1. **"sin HTML" deja de ser infra por sí solo.** Con backend sano es un
   fallo LEGÍTIMO del modelo (p. ej. `_parse_response` rechaza) y cuenta
   como reprobado: excluirlo sesgaba ANTI-BoN (se comía justo los ensayos
   donde BoN puede rescatar) y encogía n. Infra queda: EXCEPCIÓN del
   harness, juez crasheado (cualquiera de los dos), backend degradado/≠8080.
   La degradación del árbitro visual (:8081 apagado) está PREVISTA (la GPU
   la ocupa el cerebro) y NO marca infra.
2. **Ensayos incompletos (corte a mitad, <K muestras) salen del apareado**
   y se reportan aparte: un pass@2 disfrazado de pass@4 podía fabricar el
   KILL de A en el corte de las 04:14.
3. **Neutralización de Ollama doblada:** módulo `generator.OLLAMA_MODEL` Y
   `os.environ["OLLAMA_MODEL"]` (llm_local relee el env en cada llamada; el
   patch de módulo solo no cumplía lo declarado).
4. `--reanudar` aborta si commit/replicas/muestras difieren de la config
   guardada (mezclar dos sistemas sin rastro); `--solo-resumen` permite leer
   el veredicto de lo ya guardado sin gastar GPU; sondas fix2/modo_contrato
   añadidas a la config como en b2_ab_lazo.

Ningún umbral ni métrica cambia. Nada se ha corrido aún.

## RESULTADO (2026-07-28 19:15 — corrida completa, veredicto por los umbrales pre-fijados)

- **n = 24/24 ensayos válidos** (0 infra, 0 incompletos; 96 muestras). Nota
  de logística: el harness mató el proceso a los 48 min (muestra 31); se
  reanudó desacoplado con `--reanudar --acepta-commit` (commits 58a9cba +
  c13df07, solo docs/datos entre medias; registrados ambos en config).
- **Control (s=1, estricto): 17/24 (71%).**
- **A — techo pass@4: 24/24 (100%), neto A = +7 → MARGEN GRANDE** (umbral
  ≥+5). TODOS los ensayos tuvieron al menos una muestra que aprueba el juez
  estricto: las 4 réplicas independientes bastan para cubrir el banco entero.
- **B — selector held-out: 24/24 (100%), neto B = +7; C (pérdida) = 0 →
  el selector CAPTURA todo el margen** (umbral B ≥ A−1). En ningún ensayo
  eligió una muestra held-OK∧orig-NO habiendo una estricta.
- **D — FP del contrato original:** kanban 1, buscaminas 3 (4 páginas más de
  "pasó el examen, no la materia"; la memoria fp-heldout se actualiza).
- Composición del sistema en las muestras: 12/96 vía fallback create_program
  (pre-declarado como parte del camino primgen), 2/96 sin HTML (cuentan como
  reprobadas, primera enmienda). Visión del mockup degradada a idea cruda en
  TODA la corrida (max_tokens=400 no cubre el pensamiento de gpt-oss —
  régimen idéntico en ambos "brazos", validez interna intacta; fix de
  producción pendiente fuera de esta medición).

**Conclusión de inversión (la pre-registrada):** el cuello del goal NO es el
constructor — es FABRICAR SEÑAL. Con verificador de señal real, muestrear 4
réplicas independientes lleva el banco brutal de 17/24 a 24/24 (nivel 8/8
del goal, con señal a mano). La vía "BoN + verificador" queda VALIDADA como
arquitectura; el siguiente trabajo es el generador de señal (unidad 2 de
esta noche: PREREG_QA_FUERTE_20260728.md).

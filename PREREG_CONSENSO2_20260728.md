# PREREG — Consenso cruzado, iteración 2: ¿el voto sobre selectores OBLIGATORIOS y/o la mayoría-de-fracción rompen el techo del ranker?

**Fecha:** 2026-07-28 ~21:50, nocturna 28→29 (segunda noche). **Escrito ANTES
de implementar el runner y ANTES de correr.** Itera el marco cuyo baseline
quedó fijado en PREREG_CONSENSO_20260728 (RESULTADO: neto B' = +2 → KILL en
umbral, asimetría 2-0, offset severo 39/255 votos aprueban). Las dos
variantes de esta iteración son exactamente las ANOTADAS en aquel cierre —
no salen de mirar los datos nuevos, salen del diseño previo.

## Hipótesis (mecanismo pre-declarado)

El baseline mostró que los contratos ajenos condenan casi todo (15% de votos
aprueban): el criterio decisorio 1 (nº de votos todos-pasan) apenas
discrimina y el ranking cae sobre la fracción media de checks. El mecanismo
sospechado del offset: los checks sobre selectores IDIOSINCRÁTICOS del DOM
de origen (clases/atributos que la muestra de origen inventó y las hermanas
no tienen) fallan en las demás muestras por pura idiosincrasia, no por bugs.
Los checks sobre selectores OBLIGATORIOS del enunciado apuntan a lo que
TODAS las muestras deben tener → menos ruido idiosincrático, más señal de
bug real. La mayoría-de-fracción ataca lo mismo por otro lado: relaja el
todos-pasan para que el criterio 1 discrimine aunque exista el offset.

## Datos (todo CONGELADO; cero GPU, cero páginas nuevas)

- Corpus: las 94 muestras con HTML de b2_bon_heldout (commits 58a9cba +
  c13df07) con `estricto` guardado, y los 87 contratos de coder-14b + los
  255 votos congelados de b2_consenso_selector (commit 6ffe74f).
- **Medición nueva (solo Playwright, sin LLM):** re-juzgar los 255 pares
  (contrato C_s, muestra X) guardando el DETALLE POR CHECK (nombre, ok,
  critico, accion, selector, expr) — el baseline solo guardó agregados.
  Alineación check↔paso: los 4 primeros checks son los universales (carga,
  sin_errores_js, contenido, interactivo — juez_ejecutable.py:317-383);
  los siguientes van 1:1 en orden con `pasos` del contrato. Si carga falla,
  el juez corta temprano: ese voto queda con 0 checks de contrato (igual
  que el baseline: c_n=0, no computa fracción).
- El juez es el mismo binario/commit en toda la fase; commit registrado.

## Clasificador de checks OBLIGATORIOS (frozen en este prereg)

Un check es OBLIGATORIO si su `selector` o su `expr` (o el de CUALQUIER
sub-acción, en pasos anidados) matchea alguno de los tokens del enunciado
de su tarea. Tokens extraídos A MANO de b1_tareas_brutales.json:

| tarea | clases/ids (matchean como `.tok`/`#tok` o string exacta `'tok'`/`"tok"`) | data-attrs (matchean `data-tok` o `dataset.tok`) |
|---|---|---|
| hoja_calculo | celda | ref |
| carrito_stock | prod, add, linea, cant, quitar, total | id, precio, stock |
| kanban | col, card, mas, menos, cont-todo, cont-doing, cont-done | col, id |
| buscaminas | c, abierta, bandera, estado | i |

Regex por token `tok`: `[.#]tok\b` ∪ `['"]tok['"]`; por data-attr `a`:
`data-a\b` ∪ `dataset.a\b`. Pasos sin selector ni expr (tecla, esperar) no
son obligatorios. El clasificador es heurístico y queda CONGELADO aquí; la
revisión adversarial lo audita contra contratos reales ANTES de correr, y
el runner emite el conteo oblig/no-oblig por tarea como auditoría.

## Anclas de validez (pre-declaradas; si fallan, TODO es direccional)

1. **Reproducción por voto:** el `aprueba_contrato` recomputado del re-juzgado
   coincide con el congelado en ≥ 90% de los 255 votos (el juez es
   determinista salvo animaciones/waits; una tasa menor = instrumento
   inestable).
2. **Baseline reproducido:** el ranking del baseline (todos-pasan, fracción,
   −s) recomputado sobre los datos re-juzgados da neto B' en [0, +4]
   (el congelado dio +2).

## Variantes (las 3 se computan y reportan; umbral idéntico para cada una)

Sobre los mismos ensayos válidos del baseline (≥2 votos ajenos por muestra
BAJO LA VARIANTE, control s1 presente; un contrato sin checks obligatorios
NO vota en V1/V3 — si eso deja a una muestra con <2 votos, el ensayo sale
del apareado de esa variante y se reporta en sin_voto):

- **V1-oblig (datos re-juzgados):** por voto, ob_ok/ob_n sobre SOLO los
  checks obligatorios; aprueba_ob = ob_n>0 ∧ todos pasan. Ranking:
  (nº votos aprueba_ob, media de ob_ok/ob_n, −s).
- **V2-frac (votos CONGELADOS del baseline, cero medición nueva):**
  aprueba_mayoria = c_ok/c_n ≥ 0.5. Ranking: (nº votos mayoría, media de
  c_ok/c_n, −s).
- **V3-combo (datos re-juzgados):** mayoría sobre obligatorios:
  aprueba_ob_may = ob_n>0 ∧ ob_ok/ob_n ≥ 0.5. Ranking: (nº votos, media de
  ob_ok/ob_n, −s).

El resultado del elegido = `estricto` CONGELADO de la muestra elegida
(idéntico al baseline). Control = s1. Neto = gana − pierde en discordantes.

## Umbrales (fijados ahora; los del dueño para esta iteración)

| lectura (por variante) | condición | veredicto |
|---|---|---|
| neto | ≥ +5 | **VARIANTE VIVA** → pasa a validación en banco FÁCIL antes de declarar nada |
| neto | +3..+4 | señal moderada: se reporta, sin validación esta noche |
| neto | −2..+2 | KILL de la variante (no mejora el baseline +2 de forma creíble) |
| neto | ≤ −3 | la variante elige mal activamente |

- **Multiplicidad, pre-fijada:** 3 variantes = 3 oportunidades. Si ≥1 llega
  a +5, la de MAYOR neto (desempate: V1 > V3 > V2, por prior mecanístico)
  es la candidata; la validación en FÁCIL es requisito para declarar
  "marco vivo" — sin ella solo se declara "variante prometedora". Si
  ninguna llega a +5, el marco de consenso-de-contratos-ciegos queda con
  DOS KILL y la próxima vía del "marco nuevo" es otra (ejecución en el
  bucle), no una tercera vuelta de tuerca de votos.
- La validación en FÁCIL (si aplica) se pre-registra APARTE antes de
  correrla (necesita generar ensayos K=4 en el banco fácil — GPU); este
  prereg no la cubre.
- Secundarias (se reportan, no deciden): asimetría gana/pierde por
  variante; % de votos que aprueban bajo cada criterio (¿el offset se
  relaja?); coincidencia con el selector held-out; nº de contratos sin
  checks obligatorios; tasa de desalineación check↔paso si la hubiera.

## PRIMERA ENMIENDA (2026-07-28 ~22:45 — tras la revisión adversarial, ANTES de correr)

Tres agentes (diseño / implementación / auditoría ejecutada del clasificador)
revisaron prereg + runner. Dos BLOQUEA y seis arreglos aplicados; nada se ha
corrido aún salvo la auditoría estática (sin Playwright, sin outcome).

1. **BLOQUEA (diseño): el clasificador any-match no discriminaba** — 93% de
   los checks quedaban "obligatorios", 74% de los contratos votaban idéntico
   al baseline y el KILL estaba predeterminado sin probar el mecanismo.
   **Fix: clasificador ALL-MATCH por extracción de tokens** — un paso es
   obligatorio si sus selectores contienen ≥1 token de la interfaz obligada
   y NINGUNO fuera de ella. Tokens con sintaxis de selector: `.x`/`#x`/
   `[data-x]` en el campo selector y en strings citadas del js;
   `dataset.x`, `getElementById('x')`, `classList.*('x')` y
   `getAttribute('data-x')` del js crudo (la clase inventada típica —
   `mina` en buscaminas — viaja como palabra pelada en classList.contains).
   El expr crudo NO se escanea para clases con punto (acceso a propiedad).
2. **BLOQUEA (auditoría): la recursión no veía la clave anidada `pasos`**
   (coder-14b anida bajo `pasos`, no solo `acciones`): 24 pasos de kanban
   invisibles y 3 ensayos fuera del apareado por bug de schema. Fix:
   `_planos()` recursa ambas claves. Caveat pre-declarado: esos pasos
   anidados el juez no los ejecuta (accion=None → ok=False uniforme en
   todas las muestras del ensayo) — offset constante que el ranking cancela.
3. **Auditoría estática POST-fix (ejecutada, sin outcome):** oblig/total =
   buscaminas 172/185, carrito 175/184, hoja 167/193, kanban 138/140
   (652/702 = 93%); contratos sin ningún check obligatorio: 0 (la exclusión
   de ensayos por elegibilidad desaparece); contratos con ≥1 check
   no-obligatorio: 32/87. **Expectativa honesta pre-declarada:** la palanca
   del filtro es chica (7% de checks, concentrada en buscaminas) porque las
   expectativas inventadas viven mayormente en los VALORES (esperado exacto
   inventado sobre selector obligatorio), que un filtro de superficie no
   toca. Un KILL de V1 mata "filtrar por superficie de selector", NO la
   idea general de consenso; esa distinción queda fijada AHORA.
4. **Elegibilidad V1/V3 = propiedad ESTÁTICA del contrato** (clasificador
   sobre el archivo), no del re-juzgado. Y sensibilidad PEOR-CASO
   pre-declarada: cada ensayo excluido de V1/V3 (relativo al ancla 2) cuyo
   control s1 es estricto=True cuenta −1; **VIVA exige neto ≥ +5 Y
   peor-caso ≥ +5.**
5. **Criterio 1 normalizado en V1/V2/V3** (fracción de votos que aprueban,
   no conteo crudo: los denominadores difieren cuando falta el contrato de
   una hermana y el conteo crudo premiaba a la muestra sin contrato
   propio). El ancla 2 mantiene el conteo crudo del baseline (fidelidad).
6. **Comparación entre variantes solo sobre la INTERSECCIÓN de ensayos
   válidos** (netos con n distinto no se comparan); se reporta
   neto_interseccion por variante.
7. **Fuga de superficie declarada:** el held-out que define `estricto` usa
   por regla de diseño los mismos selectores obligatorios a los que V1/V3
   restringen el voto. Secundarias partidas pre-registradas (cero medición
   extra): neto de V1 contra `aprobado` solo y contra `aprobado_heldout`
   solo, con lectura fijada — si la ganancia vive solo en el conjuncto
   held-out, es reconstrucción del instrumento, no señal nueva. Un VIVA de
   V1 afirma "hay selector de producción candidato"; NO afirma que la señal
   sea independiente de la superficie del instrumento (eso lo decide la
   validación en FÁCIL + la partida).
8. **V2 re-etiquetada EXPLORATORIA** (la mayoría-de-fracción se anotó tras
   ver el offset en estos mismos 255 votos — forking paths): su eventual
   +5 NO es confirmatorio y exige la validación FÁCIL incondicionalmente.
   Robustez: V2 se computa también sobre los votos re-juzgados (V2r).
9. Menores: `desalineado` ya no marca cortes de carga (c_n=0 se reporta
   aparte); el resumen persiste votos_hechos/crasheados/parcial/ancla2_ok;
   tarea desconocida en el clasificador = KeyError ruidoso.

## RESULTADO (2026-07-28 ~22:30 — corrida completa, veredicto por umbrales pre-fijados)

**Anclas perfectas:** reproducción por voto 255/255 = 100% (umbral ≥90%);
baseline recomputado sobre el re-juzgado = +2 EXACTO (rango [0,+4]); 0
crasheos, 0 desalineados, 0 cortes de carga. El instrumento es estable.

| variante | neto | peor caso | veredicto pre-fijado |
|---|---|---|---|
| V1_oblig | **+3** | +3 (0 exclusiones extra) | señal MODERADA: se reporta, sin validación esta noche |
| V2_frac (congelados) | +2 | — | KILL (exploratoria; igual al baseline) |
| V3_combo | +3 | +3 | señal MODERADA (idéntica a V1) |
| V2r (re-juzgados) | +2 | — | robustez: V2 no cambia con el instrumento nuevo |

- **Ninguna variante llega a +5 → no hay VIVA, no hay validación en FÁCIL,
  no se adopta nada.** Por la regla de multiplicidad pre-fijada, no habrá
  tercera vuelta de tuerca a los votos: la próxima vía del "marco nuevo de
  señal" es OTRA (ejecución en el bucle), con este +3 como mejor marca del
  consenso de contratos ciegos.
- Secundarias: la asimetría mejora de 2-0 a **3-0** (V1 rescata además
  hoja_calculo:r6; sigue sin elegir peor que s1 en ningún ensayo); el
  offset se relaja poco con el filtro (votos que aprueban 39/255 → 65/255
  con todos-pasan-oblig; 176/255 con mayoría — mucha aprobación, poca
  discriminación); coincidencia con el selector held-out casi igual (6→7).
- Partidas por conjuncto (fuga de superficie): V1 da +3 contra `aprobado`
  solo Y +3 contra `aprobado_heldout` solo — la ganancia NO vive solo en el
  conjuncto held-out, así que lo poco que hay no parece mera reconstrucción
  del instrumento.
- Lectura de mecanismo (la expectativa honesta de la enmienda se cumplió):
  la palanca del filtro de superficie era chica (7% de checks) porque las
  expectativas inventadas viven en los VALORES, no en los selectores. El
  techo del consenso de contratos ciegos como ranker queda en +3/+7 del
  margen disponible — el selector held-out sigue capturando 7/7.

## Presupuesto y logística

- Fase A: 255 juzgados × ~10-15 s ≈ 45-70 min de Playwright, sin GPU (la
  flota puede quedarse apagada). Guardado incremental + `--reanudar`;
  corrida DESACOPLADA (Start-Process + log + Monitor — el harness mata
  procesos de fondo a los ~48 min).
- Fase B (resumen): instantánea, `--solo-resumen` re-lee lo guardado.
- Runner: `scripts/b2_consenso2.py`. Salida:
  `generated_programs/b2_consenso2/resultados.json`.
- Revisión adversarial (1-2 agentes) del prereg + runner ANTES de lanzar,
  con encargo explícito de auditar el clasificador de obligatorios contra
  ≥8 contratos reales.

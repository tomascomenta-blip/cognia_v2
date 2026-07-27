# PRE-REGISTRO — La SEÑAL del contrato: FN por tipo de paso y plantilla corregida

**Escrito el 2026-07-27 ~17:05, ANTES de correr el cruce y ANTES de tocar la
plantilla.** Sesión nocturna 27; continúa PREREG_CONTRATO_AMPLIO_20260727.md
(veredicto GRIS: el cuello es la CORRECCIÓN de las aserciones, no la cantidad)
y la prioridad #3 corregida de META_MODELO_GRANDE.md.

## Hipótesis mecánicas (formuladas leyendo código, ANTES de medir)

Leyendo `juez_ejecutable.py` (ejecutor + plantilla) y comparando con los
contratos held-out de `b1_tareas_brutales.json`:

- **H1 — La plantilla NO documenta la acción `escribir`.** El ejecutor la
  soporta (`el.fill(...)`, línea ~237) y el held-out la usa (hoja_calculo:
  `escribir` + `tecla Tab`), pero `_PLANTILLA_CONTRATO` solo lista click/
  tecla/texto/existe/no_existe/esperar/contar/contar_visible/js. Un pensador
  que necesita tipear improvisa: en `contrato_clasico.json` de hoja_calculo
  usó `{"accion":"texto","contiene":"5"}` con nombre "Ingresar valor" — eso
  es una ASERCIÓN sobre una celda vacía, no una escritura. Predicción: los
  pasos que "quieren escribir" fallan casi siempre sobre páginas sanas
  (FN), concentrados en tareas con entrada de texto (hoja_calculo,
  carrito con cantidades, buscaminas con flags si usa input).
- **H2 — `texto` y `contar_visible` leen `innerText`/`textContent`, que en
  `<input>`/`<textarea>` es SIEMPRE vacío.** Toda aserción de texto sobre un
  input falla aunque el producto ande (el valor vive en `.value`). El propio
  pensador a veces lo esquiva con `js` + `.value` — el tipo `js` debería
  mostrar menos FN que `texto`/`contar_visible` sobre inputs.
- **H3 — `esperado` exacto donde va `min`/`contiene`** (la lección vieja de
  [[juez-tiene-que-ejecutar]]): pese a la advertencia en la plantilla, el
  pensador sigue escribiendo igualdades exactas sobre textos/valores que no
  puede deducir (literales inventados). Predicción: los pasos con `esperado`
  exacto sobre `texto`/`js`-de-strings tienen FN mayor que los `min`/`max`.
- **H4 — Secuencias interactivas encadenadas sobre semántica improvisada:**
  un paso compuesto (acciones anidadas) que arranca con una interacción
  imposible (H1/H2) arrastra todo el paso; los pasos compuestos con
  interacción deberían concentrar el FN de los veredictos.

## Medición 1a (cero GPU: contratos YA en disco, juez local Chromium)

Corpus: las 24 páginas de `b2_sonda_prompt` (brazos crudo+full) con veredicto
del banco ya registrado (banco aprueba 19/24), y los 48 contratos ya
generados esta mañana (`contrato_clasico.json` + `contrato_amplio.json` por
página; A/B del prereg AMPLIO). NO se genera ningún contrato nuevo en 1a.

Método (`scripts/b2_fn_por_tipo.py`):
1. Re-juzgar cada página con cada contrato guardado (`juzgar_web`, mismos
   parámetros de producción). Los 4 checks universales se descartan; el
   check i+4 corresponde al paso i del contrato.
2. Clasificar cada paso por: acción dominante del fallo (la sub-acción que
   falló, identificada por el prefijo del detalle: `count(`/`visibles(`/
   `js=`/`contiene`/`existe`/`no hay elemento`/`no existe el campo`),
   presencia de interacción (click/tecla/escribir), comparador
   (esperado-exacto vs min/max vs contiene vs truthy), y si el selector
   apunta a un input/textarea (se detecta contra el DOM con `js`... no:
   estático, por heurística del selector y el inventario — se declara como
   aproximación).
3. Métricas pre-registradas:
   - **Tasa de acusación falsa por tipo** = pasos fallados de tipo T /
     pasos totales de tipo T, contando SOLO páginas que el banco aprueba.
   - **Atribución del veredicto**: por página-FN (interno reprueba, banco
     aprueba), el tipo del PRIMER paso crítico fallado.
   - Lado FP (secundario): en páginas que el banco reprueba, % de pasos que
     aprueban por tipo (mide qué tipos son ciegos).
4. Estabilidad: el re-juzgado puede diferir del juzgado de la mañana (carrera
   de animaciones); se reporta la concordancia de veredicto por
   (página, modo) contra `b2_ab_contrato/resultados.json` como sanidad. Si
   discrepa en >3 de 48, investigar antes de leer tipos.

Caveats declarados: (a) el banco es la vara — si el banco aprueba una página
con un defecto real que un paso caza de verdad, ese paso cuenta injustamente
como acusación falsa; se acepta porque el banco es el held-out escrito a
mano y auditado; (b) n=24 páginas / ~200-400 pasos es direccional por tipo;
(c) la clasificación por prefijo de detalle es una aproximación (se valida a
mano sobre 10 pasos al azar antes de leer la tabla).

## Fix 1b (menú CERRADO ahora; los datos de 1a eligen cuáles entran)

Modo nuevo `corregido` en `generar_contrato` (clásico queda intacto, como el
amplio: seleccionable, default sin tocar). Menú de cambios candidatos:

- **F1 (si H1):** documentar `{"accion":"escribir","selector":...,"texto":...}`
  + el patrón `tecla Tab` para desenfocar, con UNA línea de cuándo usarlo.
- **F2 (si H2):** regla: "el texto de un `<input>` se lee con
  `js: document.querySelector(sel).value`, NUNCA con `texto`/`contar_visible`".
- **F3 (si H3):** endurecer: "esperado exacto SOLO para conteos de elementos
  o valores que la idea dicta literalmente; para textos usa `contiene` o
  comprueba que CAMBIA tras la interacción".
- **F4 (si H4/desorden):** exigir que toda interacción venga de la lista
  literal de acciones (prohibir semántica inventada).

Un tipo entra al fix si su tasa de acusación falsa ≥ 30% con ≥5 pasos
observados, o si concentra ≥3 atribuciones de veredicto FN. La plantilla
corregida se escribe UNA vez (sin iterar mirando el A/B).

## Medición 1b (GPU liviana: solo contratos, ~40 min)

`b2_ab_contrato.py --modos clasico,corregido` sobre el MISMO corpus de 24
páginas, modos intercalados por página (mismo diseño que el A/B del amplio;
el brazo clásico se RE-GENERA en la misma corrida — control concurrente,
[[gate-e2e-flaky]]: la referencia de la mañana es solo sanidad).

Denominadores fijos (la ambigüedad del prereg del amplio, resuelta ANTES):
- **FN = páginas banco-aprobadas que el interno reprueba / 19.**
- **FP = páginas banco-reprobadas que el interno aprueba / 5.**
- Referencia clásico de la mañana (sanidad): FN 11/19 = 58%, FP 2/5.

| veredicto | condición (sobre el clásico CONCURRENTE) |
|---|---|
| **PASA** | FN_corr ≤ FN_clas − 4 celdas (≈21 pts) y FP_corr ≤ FP_clas + 1 |
| **GRIS** | FN_corr ≤ FN_clas − 2 celdas con FP_corr ≤ FP_clas + 1 — direccional, repetir antes de adoptar |
| **KILL** | FN_corr > FN_clas − 2, o FP_corr > FP_clas + 1 |

Si PASA: `corregido` pasa a candidato del lazo y la unidad 2 (lazo vs
max_rondas=1) corre con él DECLARÁNDOLO. Si GRIS/KILL: se reporta y no se
adopta; el held-out a mano por tarea sigue siendo la dirección (c) del
prereg del amplio.

Nota sobre FP con n=5: +1 celda son 20 pts — el umbral es grueso a
propósito; con este corpus el FP solo puede leerse como "no explotó".

## PRIMERA ENMIENDA (2026-07-27 ~17:50, tras la revisión de 2 agentes con
## contexto fresco, ANTES de correr 1a — el diseño original tenía 4 mayores)

Hallazgos que fuerzan cambios (workflow revision-prereg-fn-tipo):

**M1 — Cascada de víctimas.** Un paso que falla deja el estado contaminado y
los pasos siguientes fallan como víctimas (caso real: hoja_calculo r1, el
"texto/contiene:5" que quería escribir falla y los js/exacto de 8/13/CIRC
caen detrás). Cambios: (a) la tabla PRIMARIA para la regla de entrada al fix
es la de **primera culpa**: por (página, modo) cuenta SOLO la primera
sub-acción fallada del contrato — cada celda aporta a lo sumo una
observación; (b) la tabla incondicionada por sub-acción queda como
DESCRIPTIVA; (c) tras el primer fallo de un paso, las sub-acciones de
ASERCIÓN restantes (contar/contar_visible/texto/existe/no_existe/js) se
ejecutan en modo observación (`post_fallo:true`, fuera del veredicto y de la
tabla primaria; las interacciones NO se ejecutan — el estado sigue siendo el
de producción). Riesgo declarado: un `js` de observación podría en teoría
mutar el DOM; en este corpus son lecturas (.value/length), se acepta.

**M2 — Puente tipo→fix CERRADO ahora (partición CLÁSICO únicamente):**

| condición (tabla de primera culpa, SOLO modo clásico) | fix que entra |
|---|---|
| ≥3 celdas cuya primera culpa es una aserción en un paso cuyo nombre denota escritura (regex `ingres\|escrib\|tipe\|teclea\|introduc\|rellen\|llen`) y el contrato no usa `escribir` | **F1** (documentar `escribir` + Tab) |
| ≥3 celdas con primera culpa en `texto@input` o `contar_visible@input` (tag INPUT/TEXTAREA/SELECT o contenteditable, DOM inicial) | **F2** (leer inputs con js .value) |
| ≥3 celdas con primera culpa en comparador `exacto-str` (esperado string) | **F3** (exacto solo para conteos/literales dictados) |
| ≥2 celdas con primera culpa en "accion desconocida" (acción inventada) | **F4** (acciones solo de la lista literal) |
| — ya decidido por escaneo estático de la revisión: 7/24 contratos clásico sin NINGÚN `critico:true` (auto-aprueban por vacuidad) | **F5** (regla: los pasos que definen la mecánica llevan `critico:true`; un contrato sin críticos no verifica nada) |

Se borra la escotilla "/desorden" de F4. El texto del fix NO puede mencionar
tareas del banco, sus selectores ni sus literales — solo reglas genéricas.
F5 entra por el escaneo estático (dato ya visto al escribir esto; se declara).

**M3 — Celdas sin veredicto en 1b:** `interno=None` (contrato no generado o
juez crasheado, tras los 2 intentos) cuenta como **REPRUEBA** en su lado
(conservador contra el modo nuevo: en páginas sanas suma FN al brazo que no
genera). Se reporta el conteo de Nones por brazo. En 1a, un contrato ilegible
o una página que no carga se REGISTRA (no se traga): el script cuenta celdas
esperadas vs procesadas.

**M4 — Verdad de suelo re-medida:** 4 de las 5 banco-reprobadas son del
bloque r3 (firma de deriva por bloques). En la misma corrida de 1a se
re-juzga cada página con su contrato del BANCO (`juzgar_web` completo, como
la sonda) y se reporta la auto-concordancia. Las celdas cuyo veredicto del
banco NO se reproduce se EXCLUYEN de ambos denominadores de 1a Y de 1b (los
/19 y /5 se enmiendan al n estable y se declara).

**Menores adoptados:** el PASA de 1b exige además que la mejora aparezca en
≥2 tareas distintas (falso-PASA ~10% declarado con n=19; el clustering por
tarea lo empeora — humildad al leer). La atribución del veredicto registra
también el primer paso fallado de CUALQUIER criticidad (y las divergencias
con el primer crítico). `js/exacto` se parte en `exacto-num`/`exacto-str`.
Las tablas se emiten por modo Y agregadas; la regla de entrada lee SOLO
clásico. La concordancia con el juzgado de la mañana se imprime ANTES de la
tabla (gate >3/48: investigar los pares discordantes — el replay omite
universales, discrepancias por esa vía se inspeccionan antes de contarlas).
En 1b se reporta la distribución de criticidad por brazo junto al FN: si
difiere fuerte, el veredicto no es atribuible solo a F1-F4 (confound
declarado). Se registra `n_criticos` por contrato. Método de clasificación
real: campos estructurados de la sub-acción + tag del DOM inicial (mejor que
el "prefijo del detalle" del texto original; unidad = sub-acción para las
tablas, paso para la atribución). Un page nuevo por modo (no compartido).

**Lado FP:** columna DESCRIPTIVA, no criterio (un paso que aprueba en página
rota no es "ciego" si la rotura vive en otra mecánica).

## RESULTADO 1a (2026-07-27 ~18:20 — corrida completa, sanidad limpia)

Sanidad: 48/48 celdas procesadas sin error; **banco replay 24/24 concordante
(cero inestables — los denominadores /19 y /5 quedan como estaban)**; replay
vs juzgado de la mañana 48/48. La sospecha de deriva del bloque r3 (M4) NO
se confirmó: las 5 reprobadas reproducen.

Tabla de PRIMERA CULPA, modo clásico (1 observación por celda sana):

| tipo | celdas | de ellas "quería escribir" sin `escribir` |
|---|---|---|
| texto@input/contiene | 4 | 3 |
| contar_visible/exacto-num | 3 | 0 |
| texto/contiene, existe/existencia | 2 c/u | 0 |
| contar_visible@input, contar, click, no_existe, `contiene` (acción inventada) | 1 c/u | 0 |

Descriptiva clásico (extremos): **texto@input/contiene 24/24 = 100% FN** (y
en agregado 55/55, con 0/6 de acierto en páginas rotas: la aserción de texto
sobre un input es ruido puro — inner_text vacío siempre); acción inventada
`contiene` 1/1; existe/existencia 8/13 = 62%; js/exacto-num 0/3 (la vía
.value acierta cuando el pensador la encuentra solo).

**Aplicación de la regla pre-registrada (M2):**

- **F1 ENTRA** (3 celdas de escritura sin `escribir` — umbral ≥3 justo).
- **F2 ENTRA** (4+1 = 5 celdas @input ≥ 3).
- **F3 NO entra** (0 celdas exacto-str en clásico).
- **F4 NO entra** (1 celda de acción inventada < 2).
- **F5 ENTRA** (escaneo estático: 7/24 clásico sin críticos).

El modo `corregido` = plantilla clásica + F1 + F2 + F5, escrita UNA vez, sin
mencionar tareas/selectores/literales del banco. Residual declarado SIN fix
en esta ronda (los umbrales no lo habilitan): existe/existencia con
literales de selector inventados (62% FN) — la guarda anti-invención actual
no alcanza; dirección para otra sesión, junto al held-out a mano por tarea.

## RESULTADO 1b (2026-07-27 ~19:30 — A/B completo, 24 páginas × 2 modos,
## intercalado por página, clásico RE-generado como control concurrente)

| modo | FN (/19 sanas) | FP (/5 rotas) | sin contrato | aprueba con 0 críticos |
|---|---|---|---|---|
| clásico (concurrente) | 12/19 = 63% | 0/5 | 0 | **7 de sus 7 aprobaciones** |
| corregido | 11/19 = 58% | 1/5 | 0 | 1 de sus 9 |

**Veredicto por la regla pre-registrada: KILL** (FN_corr = FN_clas − 1
celda, bajo el umbral GRIS de −2). El modo `corregido` NO se adopta como
modo del lazo. Se escribe con la misma tinta que un PASA.

**Pero el confound pre-declarado en la enmienda DISPARÓ, y con mecanismo:
las 7 aprobaciones del brazo clásico son TODAS por vacuidad (0 pasos
críticos → `all()` sobre vacío → APROBADO pase lo que pase).** El clásico
no aprobó NI UNA página sana por checks reales (0/19); el corregido aprobó
8/19 con 8 críticos reales cada una. El "FN 63%" del clásico está inflado
de aprobaciones que no verifican nada: como señal del lazo, esas 7 celdas
son "APROBADO sin examen", indistinguibles de un FP en potencia. Por la
cláusula escrita ANTES de correr: el KILL no es atribuible a F1/F2 — F5
convierte exámenes vacíos en exámenes reales y eso sube el FN medido
mecánicamente.

Lectura EXPLORATORIA (partición post-hoc, se declara como tal, no entra en
el veredicto): entre contratos NO vacuos, clásico aprueba 0/12 sanas
(FN 100%) y corregido 8/18 (FN 56%).

**Mecanismo de F1/F2 verificado en los contratos generados:** corregido usa
`escribir` en 7/24 y `.value` en 6/24; clásico 0/24 y 1/24. La plantilla
llega al pensador.

**Decisión que sale de esto (fix de producción independiente del modo,
misma clase que el rechazo de malformados):** `generar_contrato` descarta
todo contrato sin ningún paso crítico (aprobaría por vacuidad; peor que
ninguno — sin contrato el lazo sella "sin verificar", que es honesto).
Test de regresión incluido. La unidad 2 (lazo vs max_rondas=1) NO corre:
su premisa pre-registrada ("si 1b mejora la señal") no se cumplió por la
regla formal. Direcciones para la próxima sesión: (a) re-plantear el A/B
del contrato con la métrica de señal REAL pre-registrada desde el inicio
(veredicto correcto POR CHECKS CRÍTICOS REALES, vacuidad excluida por
construcción — con el descarte de vacuos ya en producción, el próximo A/B
lo hereda limpio); (b) el residual existe/existencia (literales de selector
inventados); (c) held-outs a mano por tarea.

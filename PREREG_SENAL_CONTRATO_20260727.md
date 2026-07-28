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

## SEGUNDA ENMIENDA (2026-07-27 ~19:35 REAL — fe de erratas de horas: las
## marcas "~" anteriores de este archivo van corridas +1-2 h, se estimaron
## sin mirar el reloj; el orden de los hitos es correcto. El dueño extendió
## la ventana hasta las 04:30. Escrita ANTES de correr el A/B de señal real)

**A/B de SEÑAL REAL (la revancha limpia del 1b):** mismo corpus (24 páginas
de la sonda con veredicto del banco: 19 sanas / 5 rotas), mismos dos modos
(clasico re-generado como control concurrente vs corregido), intercalado
por página — pero ahora el descarte de contratos vacuos ESTÁ en producción
(commit 8006037): el clásico ya no puede aprobar por vacuidad; donde antes
aprobaba con 0 críticos ahora reintenta y, si vuelve a salir vacuo, queda
"sin contrato" (= REPRUEBA por M3, en ambos brazos por igual).

**Métrica PRIMARIA (fijada ahora): aciertos = (interno aprueba ∧ banco
aprueba) + (interno reprueba ∧ banco reprueba), sobre las 24 páginas por
modo.** Secundarias: FN/19 y FP/5 como antes; conteo de "sin contrato" por
modo; distribución de criticidad.

| veredicto | condición |
|---|---|
| **PASA** | aciertos_corr ≥ aciertos_clas + 4, FP_corr ≤ FP_clas + 1, y la mejora reparte en ≥2 tareas |
| **GRIS** | aciertos_corr ≥ aciertos_clas + 2 con FP_corr ≤ FP_clas + 1 — direccional |
| **KILL** | aciertos_corr < aciertos_clas + 2, o FP_corr > FP_clas + 1 |

Si PASA: `corregido` pasa a modo por defecto del lazo (cambio de default +
tests) y la unidad 2 corre con él DECLARÁNDOLO. Si GRIS/KILL: la unidad 2
corre con clásico. n=24 páginas por modo: direccional, se declara.

### RESULTADO del A/B de señal real (2026-07-27 ~20:55, completo)

| modo | aciertos (/24, M3: sin contrato=reprueba) | FN (/19) | FP (/5) | sin contrato |
|---|---|---|---|---|
| clásico (concurrente) | 10 | 14 | 0 | 4 |
| corregido | 9 | 14 | 1 | 1 |

**Veredicto pre-registrado: KILL** (aciertos_corr = aciertos_clas − 1; el
GRIS exigía +2). El modo `corregido` NO se adopta; la unidad 2 corre con
CLÁSICO. Se escribe con la misma tinta que un PASA, otra vez.

Lecturas honestas: (1) el descarte de vacuidad hizo su trabajo — los "sin
contrato" del clásico (4) calcan las celdas que esta mañana aprobaban con 0
críticos, y `sin_criticos=0` en ambos brazos; (2) la lectura exploratoria
del 1b (FN no-vacuos 100% vs 56%) NO replicó con contratos frescos: ambos
modos quedan en FN 14/19 (74%) — aquella partición post-hoc era
selección + deriva, y por eso era exploratoria; (3) **la palanca
"documentar escribir + leer inputs con .value" no mueve el veredicto a
nivel PÁGINA aunque el mecanismo llegue** (el corregido sí usa escribir);
el cuello restante atraviesa los tipos: literales/expectativas inventadas
contra páginas que no las violan (el residual existe/existencia de 1a, y
sus análogos). El contrato autogenerado desde idea+inventario parece tener
un TECHO de corrección en composicionales; la dirección con soporte es el
held-out A MANO por tarea de banco (una vez, auditado) y validar aserciones
contra el enunciado — queda para otra sesión con este prereg como base.

## TERCERA ENMIENDA (misma hora — Unidad 2 re-planteada, escrita ANTES de
## correrla)

**Unidad 2 — ¿el lazo SUMA o RESTA con la señal saneada?** A/B intercalado
a nivel tarea EN LA MISMA corrida, banco brutal, sistema completo, n=6 por
brazo (48 celdas):

- brazo `lazo`: config de producción (max_rondas=3, reparación esfuerzo
  default) — el sistema tal cual.
- brazo `primgen`: max_rondas=1 (primera generación juzgada, sin reparar).

Ambos brazos heredan: descarte de vacuos, fix2 en el estado que deje el A/B
v3 (si "cobra" pasa a defecto y rige en AMBOS brazos; si no, OFF en ambos),
y el modo de contrato que deje la segunda enmienda (declarado en el JSON).
La corrida guarda incremental y es reanudable; si el aterrizaje corta, se
reporta el n alcanzado como PARCIAL.

| lectura (pares apareados por celda) | condición |
|---|---|
| **el lazo SUMA** | lazo gana ≥3 celdas netas |
| **ruido** | neto en [-2, +2] |
| **el lazo RESTA** | primgen gana ≥3 celdas netas |

Si RESTA o ruido: la política de producción candidata es max_rondas=1
hasta que el contrato interno demuestre señal (el lazo gasta 3× por nada o
por daño); se deja pre-registrado que ese cambio de default requeriría su
propio A/B de confirmación en el banco fácil (no se adopta esta noche).
Referencia de sanidad (NO vara): primgen histórico 2/12 pre-fix-dashboard.

## CUARTA ENMIENDA (2026-07-27 ~19:45, tras la revisión de 2 agentes del
## diseño de la unidad 2 — 2 mayores y 4 menores; escrita ANTES de lanzar)

Reglas adicionales pre-declaradas para el A/B lazo vs primgen:

1. **Gate de lanzamiento (mayor):** fix2 hoy solo existe env-gated; si el
   A/B v3 da "cobra", el flip del default se COMMITEA en generator.py antes
   de lanzar la unidad 2 (si no, ambos brazos correrían sin fix en
   silencio). El estado real se registra con SONDA en runtime en el JSON
   (`fix2_activo_sonda`: el troceo corta o no el adorno), junto al commit,
   el modo de contrato default (inspect) y MAX_RONDAS_DEFECTO — no con un
   campo copiado del env.
2. **Pares de INFRA** (EXCEPCIÓN del harness, "sin HTML" por backend caído,
   juez crasheado) se EXCLUYEN del neto y se reportan por brazo (una caída
   del server cae asimétrica sobre el brazo lazo, que ocupa ~3× más reloj).
3. **El veredicto SUMA/RESTA exige reparto en ≥2 tareas** (24 pares pero
   solo 4 tareas: 6 réplicas de una sola bastan para fabricar ±3). Si no
   reparte, se reporta "efecto de una tarea", sin veredicto de política.
4. **PARCIAL: con n<24 pares el resultado es DIRECCIONAL y NO dispara la
   candidata max_rondas=1** (el umbral ±3 se definió para 24 pares).
5. **Asimetría declarada de sellos:** el reintento del contrato interno se
   paga "en la ronda siguiente", que en primgen no existe → primgen tendrá
   más "sin verificar" por mecánica, no por mérito. `sello_lazo` y el coste
   por celda NO se leen como señal de este A/B; el aprobado lo da el
   contrato del banco en el runner, que no se afecta.
6. **Celdas vía create_program** (fallback cuando el lazo no produce HTML):
   se cuentan por brazo y quedan visibles en el resumen; NO se excluyen del
   neto (excluirlas abriría discreción post-hoc).
7. **Recorte declarado del linaje b2:** sin sprites, sin mockup de imagen,
   candidatos=1 — la candidata "max_rondas=1" salta a un sistema con
   sprites/mockup donde las rondas podrían valer distinto; por eso el
   cambio de default exige su A/B de confirmación propio.
8. El held-out corre en try propio (un crash suyo no puede pisar el
   APROBADO primario — solo castigaría al brazo que aprobó). El rastro de
   feromona se redirige fuera del store de producción.

## RESULTADO Unidad 2 (2026-07-27 ~21:50 — COMPLETO: 24/24 pares, 0 infra)

**lazo 16/24 (67%) vs primgen 19/24 (79%); apareado: lazo gana 2 (carrito
r3, hoja r1), primgen gana 5 (carrito r2,r6; hoja r4,r6; kanban r1) —
NETO LAZO = −3, reparto en 3 tareas, n completo → veredicto pre-registrado:
EL LAZO RESTA.** create_program por brazo: lazo 3 / primgen 2 (visible, no
excluido). Config sondada: commit 06a2483, fix2 OFF, contrato clásico,
rondas 3.

Evidencia de mecanismo en los pares discordantes: en 4 de los 5 que gana
primgen, la versión del lazo tiene MENOS checks del banco que la primera
generación (18→19, 17→19, 24→27, 23→27, 16→19) — **las rondas de
reparación degradan páginas que nacieron mejor**, lo que predice
[[contrato-interno-al-azar]] (reparar guiado por una señal ~aleatoria). El
sello interno sigue ruidoso en la misma corrida (páginas banco-aprobadas
con sello FALLIDO, p.ej. hoja r1 lazo 28/28 banco con sello FALLIDO).

Nota de nivel: AMBOS brazos rinden alto esta noche (67-79%, nivel del crudo
histórico) — la brecha sistema-vs-crudo de hace dos días (17% vs 75%) no
reaparece; sin crudo concurrente esta noche, no se puede repartir entre
fixes y deriva (declarado).

**Política: la candidata max_rondas=1 queda ACTIVADA como candidata**, y
por la regla de la tercera enmienda NO se adopta sin su A/B de confirmación
en el banco fácil (donde la serie pre-fix había sugerido lo contrario:
reparar +1.33). Ese A/B se pre-registra ahora:

## QUINTA ENMIENDA (2026-07-27 ~22:00 — confirmación en banco FÁCIL,
## escrita ANTES de correr)

`b2_ab_lazo.py --banco facil` (b1_tareas.json, 6 tareas), brazos
lazo/primgen intercalados, objetivo n=6 (36 pares). Misma mecánica y
exclusiones que la cuarta enmienda. Corre hasta ~03:30; si el aterrizaje
corta antes de n=6, PARCIAL direccional y NO se adopta nada.

| lectura (36 pares completos) | condición | decisión |
|---|---|---|
| el lazo aporta EN EL FÁCIL | lazo neto ≥ +3 con reparto ≥2 tareas | rondas=3 se queda (política por banco NO: se queda global, y la resta del brutal se ataca por la señal) |
| empate | neto en [−2, +2] | **rondas=1 se adopta por COSTE** (mismo resultado, ~3× menos GPU): cambio de default + test + suite, reversible por env |
| el lazo también resta aquí | primgen neto ≥ +3 con reparto | rondas=1 se adopta con evidencia doble |

Adopción SOLO con n=36 completo (PARCIAL nunca adopta). El brazo lazo es
idéntico a producción; el JSON registra las mismas sondas de config.

### RESULTADO de la confirmación (2026-07-28 ~00:45 — COMPLETO: 36/36
### pares, 0 infra, 0 create_program)

**lazo 26/36 (72%) vs primgen 33/36 (92%); apareado: lazo gana 3 (las tres
en memoria_4x4), primgen gana 10 — NETO LAZO = −7, reparto en 3 tareas →
fila pre-registrada "el lazo también resta aquí": max_rondas=1 SE ADOPTA
con evidencia doble.** El caso más limpio: `semaforo` pierde con
reparación en LAS SEIS réplicas (primgen 6/6, lazo 0/6 de esos pares) —
regresión sistemática, no ruido ([[gate-e2e-flaky]]: concentrado =
regresión). memoria_4x4 reparte 3-3 (ruido).

Nota honesta sobre la reversión del 26/07: aquella lectura "reparar aporta
+1.33" venía de comparar SERIES EN BLOQUES entre noches (4.5 vs 3.17), el
diseño que la propia [[gate-e2e-flaky]] invalidó después al cuantificar la
deriva; los A/B intercalados de esta noche son la primera medición válida
de la pregunta, y las dos (brutal −3, fácil −7) apuntan igual.

**Adoptado (commit de esta noche): MAX_RONDAS_DEFECTO = 1**, con override
`COGNIA_MAX_RONDAS` (reversible sin release) y test de regresión que
documenta la historia completa. El lazo de reparación NO se borra: queda
íntegro tras el override y vuelve el día que el contrato interno demuestre
señal (esa sigue siendo la palanca #1 de META).

## SEXTA ENMIENDA (2026-07-28 ~01:20 — el GAP sistema-vs-crudo con control
## concurrente; escrita ANTES de correr)

La pregunta que la noche dejó sin repartir: ambos brazos del A/B del lazo
rindieron 67-92% (nivel del crudo histórico) — ¿los fixes de la semana
cerraron la brecha del 17%-vs-75%, o es deriva? Nunca se midió sistema y
crudo EN LA MISMA corrida.

**A/B GAP (`scripts/b2_ab_gap.py`):** banco brutal, intercalado a nivel
tarea con orden rotado y semilla compartida por par, objetivo n=6 (24
pares), reanudable:

- brazo `sistema`: `correr_sistema` con los defaults vigentes (rondas=1
  adoptado esta noche, descarte de vacuos, fix2 OFF — sondas en el JSON).
- brazo `crudo`: `b1_router_oraculo.generar_html(idea)` — la idea pelada
  por la vía directa, el MISMO generador del confound y de la sonda.

Misma mecánica que la cuarta enmienda (infra excluida y reportada,
create_program contado, held-out en try propio). Es MEDICIÓN de estado, no
A/B de política: ninguna adopción cuelga de esto.

| lectura (pares apareados) | condición |
|---|---|
| el envoltorio AÚN roba | crudo neto ≥ +3 con reparto ≥2 tareas — siguiente sonda: el prompt DEL LAZO completo |
| **gap CERRADO a esta potencia** | neto en [−2, +2] — los fixes cobraron; la deriva ya no puede reclamar la brecha |
| el sistema SUPERA al crudo | sistema neto ≥ +3 — primera vez; el envoltorio aporta |

PARCIAL: se reporta el n alcanzado como direccional (el aterrizaje es
04:10). Referencias históricas (17%, 75%, 92%): solo sanidad.

Ajustes de la revisión rápida (1 agente), ANTES de lanzar:
- **Fila que faltaba:** si un brazo saca neto ≥ +3 pero concentrado en UNA
  tarea → SIN veredicto global; se reporta "efecto de una tarea" y la
  siguiente sonda es específica de esa tarea.
- **Fallback de Ollama NEUTRALIZADO en esta medición** (generator.
  OLLAMA_MODEL → inexistente): _call_llm caía en silencio a llama3.2:1b si
  :8080 hipaba, y esa celda degradada contaría como fallo legítimo
  (victoria fantasma del otro brazo). Aquí la degradación es ruidosa: sin
  HTML → infra excluida. Declarado: producción CONSERVA el fallback; esto
  aplica solo al runner de medición.
- Cada celda registra `backend_activo.ultimo()` (aproximación declarada:
  en el brazo sistema hay varias llamadas por celda) y una celda con
  backend degradado o puerto ≠ 8080 cuenta como infra. `config` registra
  `backend_activo.estado()` al arrancar.
- Sin watchdog por celda (peor caso ~19 min si :8080 acepta TCP sin
  contestar): aceptado porque la corrida es reanudable y PARCIAL es una
  lectura válida aquí; si una racha de cuelgues come la ventana, se
  reporta tal cual.
- Feromona compartida entre celdas del brazo sistema (el crudo no la usa):
  coherente con "medición de estado", pero si el neto sale positivo para
  el sistema, mirar si sus victorias se concentran en reps altas antes de
  atribuirlo al envoltorio.

### RESULTADO del A/B GAP (2026-07-28 ~02:40 — PARCIAL 23/24 pares, 0
### infra; la celda buscaminas r6 se cortó colgada, ver nota)

**sistema 15/23 (65%) vs crudo 19/23 (83%); apareado: sistema gana 2
(ambas hoja_calculo), crudo gana 6 (kanban r4, hoja r6, buscaminas r2 y
r4, carrito r2 y r3 — 4 tareas) → NETO CRUDO = +4 con reparto → fila
pre-registrada: EL ENVOLTORIO AÚN ROBA** (direccional por PARCIAL, aunque
23/24 pares es casi completo). Lectura de tamaño: la brecha
sistema-vs-crudo pasó de ~58 pts (17% vs 75%, hace dos días) a ~17 pts
(65% vs 83%) — los fixes de la semana cobraron la mayor parte, la deriva
ya no puede reclamar la brecha (control concurrente), y queda un ladrón
real en el camino de generate_program. Siguiente sonda pre-registrada:
el prompt DEL LAZO completo (con checklist REQUIRED por comas, system
prompt e idea adornada — lo que el fix2 v2/v3 no pudo sondear porque la
sonda directa corría con la idea pelada).

Nota de infra (para la próxima sesión, no se debuggeó a las 02:40): la
celda `buscaminas crudo r6` quedó >45 min generando con :8080 respondiendo
/v1/models — el read-timeout de 500 s de `_preguntar_constructor`
aparentemente no dispara si los tokens gotean lento (el timeout de lectura
se resetea por chunk). Un watchdog por celda (que la revisión sugirió y se
descartó por "peor caso acotado") habría pagado: el peor caso NO está
acotado. Convertirlo en chequeo/presupuesto por celda antes del próximo
runner largo.

## SÉPTIMA ENMIENDA (2026-07-28 ~05:45, sesión matinal hasta 11:00 —
## dos unidades pre-registradas ANTES de implementar/correr)

**Unidad A — VALIDACIÓN de aserciones contra el enunciado (el ataque (c)
del plan original, nunca corrido; la dirección que ambos KILL dejaron
viva).** Modo `validado` en `generar_contrato`: se genera el contrato
CLÁSICO y un segundo paso barato le pregunta al pensador, con la IDEA y la
lista numerada de pasos, cuáles exige realmente el enunciado; los pasos no
exigidos se DESCARTAN (si el filtro deja <2 pasos o falla, se usa el
contrato clásico tal cual — el modo nunca puede ser peor que "sin
filtro" por plomería). El validador NO ve la página ni el inventario:
solo idea + pasos (no puede re-anclar al DOM).

Medición: mismo corpus de 24 páginas (banco 19/5), `b2_ab_contrato.py
--modos clasico,validado --etiqueta valid` — clásico RE-generado como
control concurrente, intercalado por página. Métrica primaria: ACIERTOS
(la de la segunda enmienda, M3: sin contrato = reprueba). Misma tabla:

| veredicto | condición |
|---|---|
| **PASA** | aciertos_val ≥ aciertos_clas + 4, FP_val ≤ FP_clas + 1, mejora en ≥2 tareas |
| **GRIS** | aciertos_val ≥ aciertos_clas + 2 con FP_val ≤ FP_clas + 1 |
| **KILL** | lo demás |

Predicción falsable (H): el filtro debe matar la clase "expectativa
inventada" (CIRC/8,00/minas en data-i) que causó el FN residual; si el
pensador no sabe distinguir "exigido" de "inventado" ni viendo solo la
idea, el techo es del PENSADOR y la única vía que queda es el held-out a
mano.

**Unidad B — re-aislar el ADORNO post-fixes.** El brazo F (séptima enmienda
del prereg BON) absolvió a `TARGET LOOK` PRE-fix-dashboard (0/12 en un
sistema que rendía 17%); nunca se re-aisló POST-fixes y con rondas=1. Con
el flag existente `COGNIA_IDEA_PELADA`: A/B intercalado por celda (mismo
runner de fix2 con `--var COGNIA_IDEA_PELADA`), banco brutal, sistema
completo con defaults vigentes, objetivo n=6 (24 pares).

| lectura (pares apareados) | condición |
|---|---|
| el adorno roba HOY | pelada gana ≥3 netas con reparto ≥2 tareas |
| sin cargo | neto en [−2, +2] |
| el adorno aporta | adornada gana ≥3 netas con reparto |
| efecto de una tarea | ≥3 netas concentradas en 1 tarea → sin veredicto global |

Si "roba": el fix candidato es construir con la idea pelada (el brief
queda para árbitro/sprites), con su propio A/B de confirmación antes de
default. PARCIAL = direccional, no adopta. Ambas unidades: infra excluida
y reportada; el fallback de Ollama sigue neutralizado SOLO en runners de
medición; backend registrado por celda donde el runner ya lo hace.

### RESULTADO Unidad A (2026-07-28 ~06:45 — A/B completo, 24 páginas × 2)

| modo | aciertos (/24, M3) | FN (/19) | FP (/5) | sin contrato |
|---|---|---|---|---|
| clásico (concurrente) | 8 | 15 | 1 | 1 |
| validado | 9 | 15 | 0 | 0 |

**Veredicto pre-registrado: KILL** (+1 acierto < umbral GRIS de +2). Y la
lectura que importa: **el filtro estuvo ACTIVO en los 24 contratos (cortó
30 pasos, 0-6 por contrato, cero fallbacks) y el FN no se movió — el
validador conserva exactamente las expectativas inventadas que acusan a
las páginas sanas.** La predicción falsable H se cumple en su rama dura:
el pensador no distingue "exigido" de "inventado" ni viendo solo la idea,
porque él mismo las inventó desde esa idea (la razón 5.4 de
[[juez-tiene-que-ejecutar]] otra vez: el que audita el examen es el mismo
que lo escribió). Con esto son TRES KILL convergentes sobre la señal
autogenerada (corregido ×2, validado): **el techo es del PENSADOR, no de
la plantilla ni del filtro. La única dirección viva es el held-out A MANO
por tarea (una vez, auditado contra referencia) — y en producción, el
sello honesto es "sin verificar" antes que un examen que acusa al 75-79%
de las páginas sanas.** Nota de nivel (deriva): el clásico concurrente dio
8/24 de aciertos donde anoche dio 10/24 — otra confirmación de que solo
los controles concurrentes valen.

### RESULTADO Unidad B (2026-07-28 ~07:00 — COMPLETO: 24 pares, 0 infra)

**pelada 19/24 (79%) vs adornada 16/24 (67%); apareado: pelada gana 4
(buscaminas r3, carrito r4 y r6, hoja r2 — 3 tareas), adornada gana 1
(kanban r3) — NETO PELADA = +3 con reparto → fila pre-registrada: EL
ADORNO ROBA HOY.** El brazo F de la séptima enmienda del prereg BON lo
había absuelto PRE-fix-dashboard (0/12 en un sistema al 17%: no había
margen que robar); post-fixes y con rondas=1, quitar el TARGET LOOK
recupera 3 celdas netas. Coherente con el mecanismo del fix2 v2: el brief
estético compite con los requisitos duros en composicionales.

## OCTAVA ENMIENDA (2026-07-28 ~07:05 — confirmación del adorno, escrita
## ANTES de correr; el umbral +3 se tocó JUSTO y la política exige doble)

Confirmación independiente: mismo runner y diseño (`--var
COGNIA_IDEA_PELADA --sufijo confirm`), n=6 nuevo (24 pares frescos),
intercalado, 0 code-change. Regla de ADOPCIÓN escrita ahora:

| confirmación | decisión |
|---|---|
| pelada neto ≥ +2 con reparto ≥2 tareas | **se adopta**: el lazo construye con la idea PELADA por defecto (el brief queda para árbitro/sprites); reversible por env `COGNIA_IDEA_ADORNADA=1`; cambio + test + suite antes del aterrizaje |
| neto en [−1, +1] | dudoso: NO se adopta; queda candidata con evidencia 1 de 2 |
| neto ≤ −2 | contradicción: NO se adopta; reportar ambas corridas |

(El umbral de adopción baja a +2 porque ya existe un +3 independiente de
la misma mañana — evidencia combinada +5 sobre 48 pares; misma lógica de
"evidencia doble" que la adopción de rondas=1.) PARCIAL nunca adopta.

### RESULTADO de la confirmación (2026-07-28 ~08:10 — 23 pares, 1 de
### infra excluido)

**pelada 18/24 vs adornada 19/24; apareado 3-3 — NETO 0 → fila
pre-registrada: DUDOSO, NO se adopta.** El +3 de la primera corrida no
replicó (interesante: hoja_calculo aporta pares a ambos lados en la misma
corrida). La regla de evidencia doble evitó adoptar por una corrida que
rozó el umbral. Candidata archivada con evidencia 1 de 2.

## NOVENA ENMIENDA (2026-07-28 ~08:15 — tercera corrida del adorno,
## escrita ANTES de correrla y DECLARANDO el estado de conocimiento)

Se corre una TERCERA serie idéntica (`--sufijo confirm2`, n=6, 24 pares).
Declaración explícita: al escribir esto se conocen los resultados de las
dos primeras (+3 y 0, total +3 sobre 47 pares) — esta enmienda fija la
lectura FINAL por el TOTAL apareado de las tres corridas (~71 pares) para
cerrar la pregunta sin dejar la decisión a discreción:

| total apareado de las 3 corridas | decisión |
|---|---|
| neto ≥ +5 con reparto ≥2 tareas | se adopta idea pelada (equivale a exigir ≥ +2 a la tercera; se declara) |
| neto en [0, +4] | la candidata se ARCHIVA: "no separable del ruido a esta potencia" — se re-abre solo con un banco más discriminante o n mucho mayor |
| neto < 0 | contradicción: vía cerrada |

Es acumulación secuencial con umbral sobre el total, declarada — lectura
direccional por construcción; la adopción (si sale) lleva la etiqueta.

### RESULTADO de la tercera serie y CIERRE (2026-07-28 ~09:25)

Tercera serie (23 pares, 1 infra): **pelada 16/24 vs adornada 21/24,
apareado 1-6 — NETO −5.** Total de las TRES series: +3, 0, −5 = **−2
sobre ~70 pares → fila pre-registrada: CONTRADICCIÓN, VÍA CERRADA.** El
adorno TARGET LOOK ni roba ni aporta de forma separable del ruido a esta
potencia; producción queda como está (adorno activo, flag
COGNIA_IDEA_PELADA disponible para experimentos).

La moraleja que queda escrita: la primera serie (+3, umbral justo) habría
adoptado "pelada" y la tercera sola (−5) habría "probado" lo contrario —
tres series intercaladas con la lectura fijada por adelantado es lo único
que impidió las dos conclusiones falsas. El patrón hoja_calculo ilustra el
ruido: aporta pares a AMBOS lados dentro de la misma corrida y entre
corridas cambió de bando (2-0 pelada en la serie 2, 0-4 en la 3).

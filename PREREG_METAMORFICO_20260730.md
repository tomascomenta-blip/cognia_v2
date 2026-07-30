# PREREG — Verificación METAMÓRFICA: señal sin examen escrito a mano

**Fecha:** 2026-07-30 ~16:00, sesión tarde-noche 30→31. **Escrito ANTES de
implementar el instrumento y ANTES de mirar una sola página.**

## Por qué esta vía, y por qué ahora

Dos hallazgos de esta semana convergen en el mismo punto:

1. **El techo que se alcanzó primero es el del DISEÑADOR de exámenes**
   (PREREG_CABECERA_NUEVA): 9 tareas escritas para romper al sistema, 6 en
   4/4 a la primera y ninguna en 0/4. Subir dificultad dentro del molde
   "tarea web verificable por ejecución" no mide progreso.
2. **El cuello es FABRICAR SEÑAL para tareas nuevas.** El 8/8 del goal se
   apoya en un selector que es un examen escrito A MANO por tarea. Las 7
   vías de señal autogenerada están muertas (6 KILL) o moderadas (+2/+3).

La instrucción que sale de (1) es *cambiar de dominio o de tipo de
verificación*. Esta vía elige **cambiar el tipo de verificación**, porque
ataca los dos problemas a la vez: es un instrumento nuevo Y no exige un
examen por tarea.

### El argumento mecánico (no es una corazonada)

Las 7 vías muertas comparten **un mismo rasgo estructural**: un LLM emite
el examen, y el modo de fallo MEDIDO es siempre el mismo — **inventa
valores que el enunciado no fija** (medido: los inventos viven en los
VALORES de los checks, no en los selectores; palanca de los selectores 7%).

**Una relación metamórfica no tiene valores.** Es una relación entre dos
ejecuciones de la MISMA página: *añadir un ítem y luego quitarlo devuelve
el estado anterior* es comprobable sin saber el precio, sin saber el
nombre del ítem y sin haber leído el enunciado. Por construcción, el modo
de fallo que mató a las 7 vías **no puede ocurrir aquí**: no hay valor
esperado que inventar.

Referencia externa del método: el testing metamórfico existe precisamente
para el "problema del oráculo" — probar sistemas cuyo resultado correcto
no se conoce de antemano. Es exactamente nuestro problema, con otro
nombre.

## Qué se construye

`scripts/b2_metamorfico.py`: un juez que, dada una página HTML **y nada
más** (sin enunciado, sin contrato, sin LLM):

1. **Descubre** las acciones disponibles leyendo el DOM (botones, inputs,
   selects, checkboxes) — emparejamiento por léxico fijo, escrito una vez.
2. **Instancia** las relaciones del catálogo que apliquen.
3. **Ejecuta** cada relación con Playwright y compara SNAPSHOTS de estado.
4. Emite APROBADO / REPROBADO / NO_CONCLUYENTE con la lista de relaciones
   violadas.

### El catálogo de relaciones (genérico, escrito UNA VEZ para todas las tareas)

| id | relación | forma |
|---|---|---|
| **R1 INVERSA** | una acción y su inversa devuelven el estado previo | `S₀ →A→ S₁ →A⁻¹→ S₂`, exige `S₂ = S₀` |
| **R2 IDEMPOTENCIA** | repetir una acción de selección/filtro no cambia más | `S₀ →A→ S₁ →A→ S₂`, exige `S₂ = S₁` |
| **R3 RESET** | reset/limpiar lleva al estado inicial exacto | `S₀ →(A,B,C)→ →reset→ S₃`, exige `S₃ = S₀` |
| **R4 DETERMINISMO** | la misma secuencia desde cero da el mismo estado | dos cargas independientes, exige igualdad |
| **R5 CONMUTATIVIDAD** | dos acciones independientes en cualquier orden | `A;B` vs `B;A`, exige igualdad |
| **R6 MONOTONÍA** | filtrar nunca aumenta las filas visibles | `visibles(post) ≤ visibles(pre)` |

Pares inversos por léxico fijo: añadir/quitar · agregar/eliminar · +/− ·
sumar/restar · marcar/desmarcar · abrir/cerrar · mostrar/ocultar ·
undo/redo (deshacer/rehacer) · iniciar/pausar · incrementar/decrementar.

### El SNAPSHOT

Estado = para cada nodo visible: `(ruta-de-selector, texto normalizado,
value, checked, disabled, clases)`. Función pura y comparable por
igualdad. Se normaliza lo volátil declarado de antemano: espacios,
`id` autogenerados, y el foco.

## La trampa que este diseño tiene que evitar, y cómo (anti-vacuidad)

**Una página muerta pasa R1 trivialmente**: si el botón no hace nada,
`S₁ = S₀` y por tanto `S₂ = S₀`. Es la vacuidad que ya nos mordió una vez
(7/24 contratos aprobaban con 0 críticos) y que ya costó un descarte en
producción. Regla pre-fijada:

> **Toda relación exige que la acción directa CAMBIE el snapshot.** Si
> tras aplicar `A` el snapshot es idéntico, la relación NO cuenta como
> aprobada: la página se marca **REPROBADA por inactividad**.

Y la cobertura se reporta siempre: nº de relaciones instanciadas por
página. Una página con **0 relaciones instanciables es NO_CONCLUYENTE**,
se cuenta aparte y **no entra** en el cálculo de aciertos (contarla como
acierto o como fallo sería fabricar el número en cualquiera de los dos
sentidos).

**Páginas con animación propia** (temporizador, serpiente): el snapshot
cambia sin que nadie actúe. Se detectan midiendo el snapshot dos veces sin
tocar nada; si difiere, la página se marca ANIMADA, sus relaciones
sensibles a estabilidad se desactivan y **se cuenta cuántas son**. Ese
número es parte del resultado, no una nota al pie.

## El riesgo REAL de esta vía, nombrado antes de medir

**Una relación genérica puede ser FALSA para el enunciado.** El caso puro
ya está en nuestro banco: `undo_redo` exige que **la rama rehacible se
invalide** — o sea, el enunciado prohíbe deliberadamente que undo/redo sea
una inversa limpia. Una página CORRECTA violaría R1.

Por eso la **métrica primaria es el FP** (acusar a páginas sanas), que es
justo el modo de fallo que ya mató al modo `amplio` del contrato (FN 75%
por acusar en masa). Si las relaciones genéricas no son universales, esta
vía muere, y muere por su propio umbral.

Y por eso hay **split de calibración/medición** (abajo): retirar una
relación después de ver que produce FP es calibrar el instrumento — pero
solo es legítimo si el número final se mide en tareas que no se usaron
para calibrar. Es el mismo procedimiento que se usó con la cabecera.

## Corpus y SPLIT (pre-registrado)

Ground truth = **veredicto estricto ya conocido** de cada página
congelada (contrato original ∧ held-out a mano). Cero GPU: las páginas ya
existen y los veredictos ya están firmados.

- **CALIBRACIÓN** (se puede mirar, se puede retirar relaciones):
  páginas de los bancos **fácil y brutal**.
- **MEDICIÓN** (se mira UNA vez, con el catálogo ya congelado):
  páginas del banco **DURO** (64 del goal, r1+r2) y de la **CABECERA**
  (36). El catálogo se congela con un commit ANTES de correr la medición,
  y el hash del commit se anota aquí.

El split es **por tarea**, no por página: ninguna tarea aparece en los dos
lados.

*(El inventario exacto de páginas y clases por lado se anota abajo, en
CORPUS MEDIDO, antes de correr nada.)*

## Métricas y umbrales — FASE 1 (viabilidad)

Sobre el lado de MEDICIÓN, con el catálogo congelado:

| métrica | definición |
|---|---|
| **FP** (primaria) | fracción de páginas ESTRICTAMENTE APROBADAS que el metamórfico reprueba |
| **FN** | fracción de páginas ESTRICTAMENTE REPROBADAS que el metamórfico aprueba |
| cobertura | relaciones instanciadas por página (mediana y mínimo) |
| NO_CONCLUYENTE | nº de páginas sin relaciones instanciables |

Línea base contra la que se compara (ya medida en este repo, misma familia
de números): **contrato ciego autogenerado — FP 32-50%, FN ~50%** (n=196).

| resultado | veredicto |
|---|---|
| **FP ≤ 15% y FN ≤ 35%** | **VIVE** — primera señal autogenerada mejor que todo lo probado; pasa a FASE 2 |
| FP ≤ 15% y FN 36-60% | **GRIS** — señal débil pero no dañina; pasa a FASE 2 solo si además nunca elige peor que s1 |
| **FP > 15%** | **KILL** — las relaciones genéricas no son universales (el modo de fallo que ya mató al contrato amplio) |
| **FN > 60%** | **KILL** — indistinguible del azar |

**Auditoría obligatoria antes de firmar** (heredada del procedimiento que
cazó 3 FN míos en el brutal): se abren a mano **TODOS los FP** y se
clasifica cada uno en

- **(a) relación no universal** → la relación es falsa para ese enunciado;
  se declara y, si viene del lado de calibración, se retira del catálogo;
- **(b) fallo REAL que el contrato a mano dejó pasar** → sería **señal
  nueva**, y el resultado más valioso posible de esta sesión: el examen a
  mano tendría un agujero que el instrumento genérico ve.

Sin esa auditoría el número no se firma.

## Métricas y umbrales — FASE 2 (valor), solo si FASE 1 no muere

El metamórfico se usa como **SELECTOR del BoN** sobre las corridas
congeladas del goal (r1 y r2, 8 tareas × 4 muestras cada una), puntuando
cada muestra por relaciones violadas y eligiendo la mejor.

| referencia (ya medida) | número |
|---|---|
| control s1 (sin BoN) | 7/8 en ambas corridas |
| MODO con selector a mano | 8/8 en ambas corridas, pérdida 0 |
| techo pass@4 | 8/8 en ambas corridas |

| resultado del selector metamórfico | veredicto |
|---|---|
| **8/8 en r1 y r2** | el goal deja de depender de un examen a mano: **"8/8 en lo que le eches"** |
| 7/8 (empata al control) | no aporta: el BoN sin señal ya da 7/8 |
| ≤6/8 | **DAÑINO**: elige peor que no elegir |

Se reporta también la **pérdida del selector** (techo − modo) y la
asimetría (cuántas veces rescata vs cuántas veces estropea), que es la
secundaria que ya se usó con el consenso.

## Lo que este diseño NO puede demostrar (dicho antes, no después)

- **No prueba corrección general.** Una página puede cumplir las seis
  relaciones y ser basura respecto al enunciado. El metamórfico es una
  condición NECESARIA, no suficiente. Si vive, su uso natural es como
  **filtro** dentro del BoN, no como juez final.
- **El ground truth y el instrumento comparten Playwright**, así que
  comparten los fallos de infraestructura (páginas con JS bloqueante). La
  independencia que se reclama es de **contenido** (el metamórfico no lee
  el enunciado), no de tecnología. Todo juzgado bajo presupuesto de pared
  de 300 s; el desborde cae como infra, no como veredicto.
- **El corpus está desbalanceado** hacia páginas aprobadas (el sistema
  aprueba ~92% en el duro). El FN se estima con pocas páginas reprobadas y
  su intervalo es ancho: se reporta el n por clase junto al porcentaje,
  siempre, y con menos de 20 reprobadas el FN se declara **direccional**.

## Presupuesto

Implementación ~1.5 h (sin GPU). Humo sobre 4-8 páginas ~10 min.
Medición completa: CPU/Playwright, ~1-2 h, **cero GPU**. FASE 2 reusa las
mismas ejecuciones. Aterrizaje 06:44; si el reloj corta, se reporta el
PARCIAL con el n alcanzado y se declara como tal.

## ENMIENDA 1 (2026-07-30 ~16:10) — lo que el HUMO obligó a cambiar

Escrita **antes de ver ningún FP/FN**, con el instrumento corriendo sobre 4
páginas del lado de CALIBRACIÓN. Tres cambios, los tres con su medición:

**(a) El descubrimiento de acciones era ciego.** Con `button, [role=button],
input[type=button], a[href]` el humo dio **4/4 NO_CONCLUYENTE: cero
relaciones instanciadas**. Causa: un `buscaminas` correcto **no tiene un solo
`<button>`** — pinta sus celdas como `<div class="c">`. Se añade la señal
universal de "esto se clica" que el propio CSS del producto declara,
`getComputedStyle(e).cursor === 'pointer'`, sobre los tags semánticos (no en
su lugar), y se descartan los contenedores cuyo hijo también es accionable.
Tras el cambio, las 4 páginas instancian.

**(b) Los índices tenían que sobrevivir a la recarga.** Descubrir sobre una
lista y clicar sobre otra recalculada habría clicado un elemento distinto del
analizado. Cada accionable se marca con `data-mm-idx`, se re-marca tras cada
`goto`, y si el producto re-pinta su lista y se lleva la marca por delante se
re-marca y se reintenta **una** vez. *Límite declarado:* si la lista cambia de
tamaño, el índice ya no significa lo mismo — es el mismo límite del
emparejamiento posicional que ya estaba declarado.

**(c) Se añade R0 ACTIVIDAD, y es la relación más importante del catálogo.**
El humo destapó que las relaciones de PAR (R1, R3) solo instancian si el
léxico encuentra la pareja, y **`carrito_stock` tiene botones `.add` y ningún
inverso**: 0 pares, 0 relaciones. Un catálogo que solo sabe emparejar se queda
mudo en media flota.

> **R0: todo control HABILITADO y visible produce algún efecto observable.**

No necesita par, ni léxico, ni enunciado, y ataca un modo de fallo **ya
observado a mano en este repo**: en `turnos_capacidad`, *"el botón de apuntar
simplemente no crea el grupo"*.

*Riesgo declarado ANTES de medirlo, porque es evidente:* existen controles
**legítimamente inertes** — un `◀` de kanban cuando la tarjeta ya está en la
primera columna, un submit que la validación bloquea. Por eso R0 entra con un
**umbral parametrizado** (`fracción de controles inertes que constituye
violación`) que se **calibra en el lado de CALIBRACIÓN y se congela con un
commit antes de tocar el lado de medición**. Si ningún umbral separa las
clases en calibración, R0 se retira y se declara.

Las relaciones que quedan activas para la calibración: **R0, R1, R3, R4**.
R5 (conmutatividad) queda apagada por coste; R2 y R6 no se implementaron.

## CORPUS MEDIDO

**Lado de CALIBRACIÓN** (se puede mirar, se pueden retirar relaciones y fijar
umbrales):

| corrida | banco | páginas | ground truth |
|---|---|---|---|
| `b2_bon_heldout` | BRUTAL (buscaminas, carrito_stock, hoja_calculo, kanban) | 94 con HTML de 96 muestras | `estricto` explícito por muestra: **72 aprobadas / 24 reprobadas** |

Es el mejor corpus del repo para esto: el único grande con el AND
original ∧ held-out ya calculado por muestra, y con **ambas clases bien
pobladas** (25% de reprobadas).

**Lado de MEDICIÓN** (se mira UNA vez, con el catálogo congelado):

| corrida | banco | páginas | ground truth |
|---|---|---|---|
| `b2_bon_heldout_duro` (r1) | DURO (las 8 del goal) | 32 | estricto **solo vía `goal.json`** → `filas[].estrictos` |
| `b2_bon_heldout_duro_r2` | DURO | 32 | estricto explícito + `goal.json` |
| `b2_bon_heldout_cabecera` | cabecera t1 | 20 | **solo contrato original** (`aprobado_heldout=null`) |
| `b2_bon_heldout_cabecera2` + `_recal` | cabecera t2 | 32 | **solo contrato original** |

*Trampa documentada por el reconocimiento, anotada para no firmar un número
falso:* en `b2_bon_heldout_duro` (r1) el `resultados.json` tiene
`aprobado_heldout=null` y `estricto=false` en las 32 muestras
(`heldout_crasheo=true`, "sin held-out (fase 1)"). El veredicto real se
recuperó re-juzgando y vive en `goal.json`, escrito 21 minutos después, que
**no reescribió** `resultados.json`. Los dos archivos del mismo directorio se
contradicen: **hay que leer `goal.json`**. Leer el otro daría "las 32
reprobadas" y un FN falso de manual.

*Consecuencia para la cabecera:* sus 52 páginas no tienen juez estricto, solo
el contrato original. Se usan **declarando que su ground truth es más débil**,
y sus números se reportan por separado de los del banco duro, nunca fundidos.

**El split es por TAREA y ninguna tarea aparece en los dos lados**: las 4
brutales solo en calibración; las 8 duras y las 9 de cabecera solo en
medición.

**Poder estadístico, dicho antes:** el lado de medición tiene ~116 páginas
pero solo ~13-18 reprobadas (el sistema aprueba el 92% del duro). Con menos de
20 reprobadas **el FN se declara direccional**, como ya fijaba el prereg.

## ENMIENDA 2 (2026-07-30 ~16:35) — la revisión adversarial, con 13 BLOQUEA

Tres revisores independientes (lente de sesgo, lente de relaciones falsas,
lente de viabilidad) sobre el prereg v1 + enmienda 1. Veredictos:
**REDISEÑAR / REDISEÑAR / CORREGIR ANTES DE CORRER**. Casi todos los
hallazgos vienen con evidencia de código congelado, no con especulación, y
**varios los he verificado yo mismo antes de aceptarlos**. Se corrigen todos
los que aplican; los que matan una pieza, la matan.

### B1 — Las etiquetas FP/FN estaban INVERTIDAS respecto a la línea base

El repo usa, desde `PREREG_CONTRATO_AMPLIO_20260727`, la convención
*FP = el examen interno APRUEBA basura* (32-50%) y *FN = CONDENA sanos*
(~50%). Mi prereg v1 llamaba FP a condenar sanos y lo comparaba contra el
32-50%. **La tabla comparaba reject-healthy contra approve-bad: no comparaba
nada, y el umbral "FN ≤35%" dejaba pasar un instrumento PEOR que el contrato
ciego ya muerto.** Era un PASA falso construido con las etiquetas.

Se renombran a nombres sin ambigüedad posible, y son los que se firman:

| métrica | definición | baseline correctamente mapeado |
|---|---|---|
| **ACUSA_SANOS** | páginas GT-aprobadas que el metamórfico reprueba | contrato ciego ~50% |
| **DEJA_PASAR** | páginas GT-reprobadas que el metamórfico aprueba | contrato ciego 32-50% |

| resultado | veredicto |
|---|---|
| ACUSA_SANOS ≤ 15% y DEJA_PASAR ≤ 20% | **VIVE** (hay que MEJORAR el 32%, no empatarlo) |
| ACUSA_SANOS ≤ 15% y DEJA_PASAR 21-40% | GRIS |
| **ACUSA_SANOS > 15%** | **KILL** |
| **DEJA_PASAR > 40%** | **KILL** |

La línea base se midió en otro corpus y con otra tasa base: es referencia de
**orden de magnitud, no comparación pareada**. Queda dicho.

### B2 — El corpus de MEDICIÓN no puede estimar DEJA_PASAR. Verificado a mano

`validacion_heldout_v2.json`, 64 filas, juez triple (orig ∧ v1 ∧ v2):
**59 aprobadas y 5 reprobadas** — `precedencia r1s2`, `tabla_compuesta r1s1`,
`tabla_compuesta r1s4`, `serpiente r2s4`, `tabla_compuesta r2s1`. Tres de las
cinco son la misma tarea.

**Con 5 reprobadas, DEJA_PASAR no es estimable en el lado de medición.** No
se va a maquillar: se declara así y se reparten los ejes.

- **ACUSA_SANOS se mide en MEDICIÓN** (59 páginas aprobadas del duro,
  tareas nunca vistas en calibración). Es la primaria y decide VIVE/KILL.
- **DEJA_PASAR se mide solo en CALIBRACIÓN** (banco brutal: 72/24, el único
  corpus del repo con ambas clases pobladas) y **se declara como número de
  calibración, no de held-out**.
- **La CABECERA sale del corpus de medición**: sus 52 páginas tienen
  `aprobado_heldout=null`, o sea no tienen juez estricto. No pueden aportar
  ninguno de los dos ejes.
- El ground truth del duro se lee de `validacion_heldout_v2.json`, no de
  `resultados.json` (que tiene `estricto=false` en las 32 de r1 por el
  held-out que no corrió) ni de `goal.json` (que da la elección del selector,
  no el veredicto por página).

### B3 — FASE 2: un selector ALEATORIO saca 8/8 el 21% de las veces

Calculado sobre los estrictos reales: r1 tiene `tabla_compuesta` con 2 de 4
muestras buenas y `precedencia` con 3 de 4 → P(azar acierte las 8) = 0.375;
r2 → 0.5625; producto **0.211**. El umbral "8/8 = el goal deja de depender de
un examen a mano" lo cruzaba el azar una de cada cinco veces.

Correcciones pre-registradas:

1. **Brazo NULO obligatorio**: 1000 selectores uniformes al azar sobre las
   mismas muestras. Se reporta la distribución y **el percentil donde cae el
   metamórfico**. El umbral pasa a ser **superar el percentil 95 del azar en
   r1 y en r2**, no un 8/8 nominal.
2. Se reporta **RESCATA vs ESTROPEA** sobre las 16 celdas tarea×corrida, que
   es la métrica con resolución. El 8/8 agregado se reporta, pero no decide.
3. r2 **no es independiente de r1** (reusa las semillas de feromona, ya
   declarado en PREREG_GOAL_DURO). El "2 de 2" está correlacionado.
4. **Una muestra sin relaciones instanciadas NO puede ganar.** En v1 tenía 0
   violaciones y por tanto puntuación perfecta: el estado que el prereg
   declara "no medible" era premiado en el uso real. Ahora la puntuación es
   la **fracción violadas/instanciadas**, y cobertura 0 es **ABSTENCIÓN** →
   se cae al control s1 y esa tarea se cuenta aparte.

### B4 — La regla anti-vacuidad dispara AL REVÉS

Verificado en las 4/4 muestras de `undo_redo`: `function addItem(text){ if(!text) return; ...}`.
El instrumento clica a ciegas con los inputs **vacíos**, que es como los
encuentra; una implementación **correcta** ignora la acción, el snapshot no
cambia, y mi regla la marcaba REPROBADA por inactividad. Es el mismo modo de
fallo (acusar en masa) que ya mató al modo `amplio` del contrato.

**Fix — SEMBRADO declarado de antemano:** antes de instanciar ninguna
relación se rellenan deterministamente todos los campos alcanzables
(texto → `"mm1"`, número → `1`, select → segunda opción, checkbox → marcar) y
se emite `Tab`. Y el resultado deja de ser binario: se distinguen **CAMBIA**
(la relación aplica), **INERTE CON PRECONDICIONES SEMBRADAS** (candidata a
inactividad) y **NO ALCANZABLE** (control `disabled` → cobertura no
alcanzada, nunca violación).

### B5 — Relaciones FALSAS por mandato del enunciado: se retiran ahora

Cada una con su evidencia en enunciado y en código congelado:

| relación | dónde es falsa | evidencia | decisión |
|---|---|---|---|
| R1 con `+/−` | `precedencia`, `parser_parentesis` | `expr += val` en 4/4: la pantalla va de `''` a `'+'` a `'+-'`. Son teclas de un teclado, no inversas | **fuera del léxico** |
| R1 `iniciar/pausar` | `temporizador` | el enunciado ordena que *"pause lo detiene MANTENIENDO el valor"*: la inversa es falsa por mandato | **fuera del léxico** |
| **R5 conmutatividad** | casi todo el banco | `tabla_compuesta` manda *"al filtrar se vuelve a la página 1"*; `tres_en_raya` y `ascensor` son por turnos/sentido | **RETIRADA del catálogo** |
| **R6 monotonía** | `tabla_compuesta` | estando en la página 3 se ven 3 filas; al filtrar salta a la 1 y se ven 10. Filtrar AUMENTA lo visible | **RETIRADA** |
| **R2 idempotencia** | `tabla_compuesta` | `#ordenar` es un TOGGLE: `ascending = !ascending` y cambia su propio texto | **RETIRADA** |

La independencia de dos acciones es una propiedad **semántica del enunciado**
— exactamente lo que este instrumento se niega a leer. R5 no es rescatable
con ninguna heurística léxica, y se dice así.

**Catálogo congelado: R0 (actividad), R1 (inversa, con léxico podado), R3
(reset), R4 (determinismo).**

### B6 — El emparejamiento por texto es inviable, y su fracaso produciría un KILL FALSO

Medido por el revisor simulando el léxico sobre las 100 páginas: **31 sin un
solo `<button>`, 50 con botones pero sin par, 19 con par** — y esas 19 son
precisamente las calculadoras donde R1 es falsa. Si se corriera así, saldría
`ACUSA_SANOS ≈ 100%` y se firmaría el KILL de *la idea metamórfica* cuando lo
que muere es *el descubridor por léxico*. **Sería un KILL falso, y cerrar una
vía todavía viva es el error más caro que se puede cometer aquí.**

Fixes: emparejar por **`data-*` compartido o ancestro común más cercano**
(nunca por texto global — verificado en `carrito_packs`, dos filas idénticas
`pan`/`leche` con `.quitar`/`.add`, donde el emparejamiento posicional cruza
filas); excluir tokens de un carácter dentro de un teclado (≥6 hermanos con
la misma clase o el mismo `data-*`); si hay más de un candidato al mismo
nivel, registrar **AMBIGUO** y contarlo aparte, nunca fundirlo con
NO_CONCLUYENTE.

### B7 — La máscara de volatilidad se deriva EMPÍRICAMENTE, por página

Fuentes de ruido verificadas en el corpus: reloj de pared en el texto
(`toLocaleTimeString` por fila), `Math.random` en el posicionado de
`serpiente`, y clases transitorias (`li.className='it new'` +
`setTimeout(()=>li.classList.remove('new'),1000)` en `undo_redo`). Comparar
por igualdad estricta acusaría a páginas sanas.

Protocolo fijado **antes** de correr: 3 snapshots sin tocar nada a
**0 / 1500 / 4000 ms**; todo campo que difiera se marca VOLÁTIL y se excluye
de las comparaciones **de esa página**, reportando cuántos se enmascararon.
Si la máscara cubre >50% de los campos, la página es NO_CONCLUYENTE.
Detección de ANIMADA también **post-acción**, no solo al cargar: el
`setInterval` de `temporizador` no existe hasta pulsar Start.

### B8 — La auditoría solo podía corregir el GT en la dirección que ayuda

En v1, un ACUSA_SANOS reclasificado como "fallo real que el examen a mano
dejó pasar" salía del numerador de la métrica primaria — y lo decidía el
mismo autor, sin regla escrita. Se firman **dos números**:

- **ACUSA_SANOS_CRUDO**, sin reclasificar nada: **es el que decide VIVE/KILL.**
- ACUSA_SANOS_AJUSTADO, tras auditoría, aparte y con la lista nominal.

Toda página reclasificada obliga a escribir el check concreto que le faltaba
al contrato a mano. Y se audita además **una muestra ciega del mismo tamaño
entre los acuerdos aprobada-aprobada**, para acotar el error del GT en la
dirección que perjudica, no solo en la que favorece.

### B9 — Independencia: R0 NO es señal nueva, y hay que decirlo

`juez_ejecutable._JS_HUELLA` + el check `interactivo` (clicar y comprobar que
la huella cambia) **ya forman parte del veredicto de referencia**. Mi R0 es
casi esa misma prueba sin contrato. Todo acuerdo en páginas muertas está
garantizado por construcción.

Se reportan **dos acuerdos**: el total, y el que **excluye las páginas cuyo
fallo en el GT vino del check `interactivo` o de `sin_errores_js`**. Solo el
segundo cuenta como señal nueva.

### B10 — Cuelgues: hay un bucle infinito REAL en el corpus

`turnos_capacidad__r1__s1` tiene `while(getOccupancy(f)>capacity){ for(...){ ... break; } }`
que **no termina** si no encuentra grupo de esa franja. El instrumento
multiplica por ~10 las cargas respecto al juez, y cada cuelgue cuesta 300 s
**más** un Chromium huérfano quemando CPU el resto de la corrida (es
literalmente lo que produjo los 595 s y los 719 s ya documentados).

Fijado: `page.set_default_timeout(5000)`, tope **por página** de 90 s además
del de corrida, contexto de navegador nuevo y cerrado explícitamente, y
**matar el Chromium por PID** al agotar el presupuesto en vez de solo
abandonar el hilo. Un cuelgue es INFRA, nunca un veredicto.

### Lo que esta enmienda NO arregla, y por qué se corre igual

El revisor de relaciones propone que el gasto defendible es publicar **solo
la tabla de cobertura**. Se acepta a medias: la cobertura se publica sí o sí
—es un número real, barato y explica el resultado sin fabricarlo— **pero se
corre también la medición**, porque con el catálogo podado y el sembrado el
argumento del FP≈100% ya no se sostiene tal cual: se apoyaba en R1/R2/R5/R6
por léxico, y de esas solo sobrevive R1 podada.

**Si la cobertura resulta ser ~0 en el lado de medición, no hay corpus y no se
firma ningún FP/FN: se declara que la vía no es medible con este banco.** Eso
también es un resultado, y es el que el revisor anticipa.

## RESULTADO (2026-07-30 ~17:30 — 158 páginas, 0 infra, cero GPU)

### KILL, y disparado en el lado donde yo tenía permiso para ajustar

| corpus | ACUSA_SANOS | DEJA_PASAR | NO_CONCLUYENTE |
|---|---|---|---|
| **CALIBRACIÓN** (brutal, 94 pág., 72/22) — umbral R0 0.34-0.50 | **43.1%** (31/72) | 36.4% (8/22) | 0 |
| **CALIBRACIÓN** — umbral R0 0.67-1.00 | **18.1%** (13/72) | **50.0%** (11/22) | 0 |
| MEDICIÓN duro r1 (32 pág., 29/3) | **31.6%** (6/19) | 66.7% (2/3) | 10 |
| MEDICIÓN duro r2 (32 pág., 30/2) | **28.6%** (6/21) | 0.0% (0/1) | 10 |

Umbrales pre-registrados: VIVE con ACUSA_SANOS ≤15% **y** DEJA_PASAR ≤20%;
KILL con ACUSA_SANOS >15% **o** DEJA_PASAR >40%.

**Ningún umbral de R0 cruza los dos listones, en ningún corpus.** Con umbral
bajo se dispara ACUSA_SANOS (43%); con umbral alto se dispara DEJA_PASAR
(50%). El KILL se cumple por ambos lados a la vez, y **ni siquiera en el lado
de calibración** —donde el prereg me permitía retirar relaciones y mover el
umbral— hay una configuración que sobreviva. No hubo nada que congelar.

### El número que manda, y que la revisión pidió publicar sí o sí

```
pares inversos instanciados: 0 en 94 páginas del brutal
                             0 en 64 páginas del duro
                             -------------------------
                             0 en 158 páginas congeladas
```

**R1 (inversa), R3 (reset) y R4 (determinismo) no se instanciaron NI UNA VEZ.**
Sin R0, las 158 páginas salen NO_CONCLUYENTE. Y 20 de las 64 del duro (31%)
no tienen ni un control descubrible.

O sea: el catálogo metamórfico se redujo, en la práctica, **a una sola
relación** — R0, "¿responde algún control?".

### El mecanismo, que vale más que el veredicto

**Para saber qué acción deshace a cuál hay que leer el enunciado.** El
descubridor puede encontrar los controles (eso se arregló: `cursor:pointer`
llevó las páginas de 4/4 NO_CONCLUYENTE a instanciar), pero **emparejarlos
como inversos exige semántica**, y ahí solo caben dos caminos y los dos están
cerrados:

- **por LÉXICO** — cobertura 0 en 158 páginas. Y donde el léxico sin podar sí
  encontraba par (19/100, medido por la revisión), eran **calculadoras donde
  `+` y `−` no son inversas sino teclas que se concatenan** (`expr += val`).
  Correrlo así habría dado ACUSA_SANOS ≈100% y habría firmado un KILL de *la
  idea metamórfica* cuando lo que moría era *el descubridor*.
- **por EFECTO MEDIDO** (probar qué botón deshace a cuál) — es **circular**:
  si el par se define como "el que devuelve el estado inicial", R1 no puede
  fallar nunca. Queda descartado por construcción, no por medición.

Y lo único que quedó instanciable, R0, **no es señal nueva**: `_JS_HUELLA` +
el check `interactivo` (clicar y ver si la huella cambia) ya forman parte del
juez que produjo el ground truth. Su DEJA_PASAR de 50% dice exactamente qué
es capaz de ver: **detecta páginas MUERTAS, no páginas INCORRECTAS.**

### La conclusión general, con su alcance declarado

> **Una verificación que no lee la especificación puede detectar
> INACTIVIDAD, pero no INCORRECCIÓN.**

Eso explica de una sola vez el patrón de las ocho vías: el contrato ciego, el
consenso de contratos, la ejecución en el bucle, el consenso conductual y
ahora el metamórfico **fallan todas en el mismo sitio**, y no por falta de
ingenio en la implementación — les falta la información que dice qué debería
pasar. La diferencia entre "la página hace algo" y "la página hace **lo
correcto**" vive en el enunciado, y ningún instrumento que se niegue a leerlo
la puede cruzar.

*Alcance:* está medido sobre tareas web verificables por ejecución, con este
catálogo de cuatro relaciones y este descubridor. No demuestra que ninguna
relación metamórfica sirva en ningún dominio — el testing metamórfico funciona
en dominios (compiladores, ML, motores de búsqueda) donde la relación viene
dada por la MATEMÁTICA del problema y no hay que descubrirla del DOM. Lo que
esta medición cierra es la vía *genérica y auto-descubierta* en este dominio.

### Lo que NO se hizo, y por qué

**FASE 2 no se corre.** Estaba condicionada a que la FASE 1 no muriera, y
murió. Además habría sido inútil por construcción: con 0 relaciones en 10 de
32 páginas por corrida y una sola relación en el resto, el selector se habría
abstenido en la mayoría de tareas. El brazo nulo aleatorio queda implementado
en `scripts/b2_metamorfico_selector.py` para quien lo necesite.

### Coste y honestidad del gasto

158 páginas juzgadas, **0 infra, 0 GPU**, ~50 min de CPU. El instrumento
(`b2_metamorfico.py`), el analizador y el selector con brazo nulo quedan en el
repo: si aparece un banco con pares inversos declarados por enunciado, la
medición se repite cambiando una ruta.

**Fe de erratas del camino:** el primer humo dio 4/4 NO_CONCLUYENTE y estuve a
punto de leerlo como "las páginas no son interactivas". Era mi descubridor,
que buscaba `<button>` en un `buscaminas` que pinta sus celdas como `<div>`.
Dos arreglos después el instrumento veía los controles — y el resultado
siguió siendo KILL, pero por una razón distinta y correcta.

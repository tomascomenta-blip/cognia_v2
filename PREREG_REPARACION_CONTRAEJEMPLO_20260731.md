# PREREG — Reparación con CONTRAEJEMPLO contra Best-of-N, a ISO-CÓMPUTO

**Escrito el 2026-07-31 a las 05:50, ANTES de generar una sola muestra.**
Banco: LiveCodeBench, estrato `hard`. Modelo: gpt-oss-20b (16 GB).

---

## 1. Por qué se reabre una vía SUSPENDIDA, y con qué derecho

La reparación guiada era la prioridad #1 histórica de `META_MODELO_GRANDE.md`.
La **suspendí yo mismo el 2026-07-28** con evidencia propia: dos A/B
intercalados mostraron que las rondas de reparación **RESTAN** (banco brutal
−3, banco fácil −7; `semaforo` perdía 6/6 al reparar).

Pero la suspensión se escribió **con una condición explícita**:

> *"TDDev/self-repair ganan con un verificador FIABLE; la nuestra no lo es
> todavía."*

Esa condición **se cumple hoy, por primera vez, y está medida**. En el dominio
web el verificador era el contrato interno autogenerado, que reprueba el
**88-94% de las páginas SANAS** y tiene un Youden J de +12.2. En LiveCodeBench
el verificador son **los tests del propio benchmark**, y anoche se midió lo que
discriminan sobre 668 muestras:

| | contrato interno (web) | tests visibles (B-LCB) |
|---|---|---|
| ACUSA_SANOS | 88-94% | **2.0%** |
| DEJA_PASAR | ~50% | **13.4%** |
| Youden J | +12.2 | **+84.6** |

*(Las dos columnas no son comparables entre sí — una es por PÁGINA contra un
juez a mano, la otra por MUESTRA y tests-contra-tests. Se ponen juntas para
mostrar el ORDEN DE MAGNITUD del cambio de verificador, no para restar.)*

Reparar con un verificador que acusa al 90% de los sanos es perseguir ruido.
Reparar con uno que acusa al 2% es otra cosa. **Eso es lo único que cambia, y
es exactamente lo que la suspensión pedía.**

## 2. La pregunta, en una frase

> Con un verificador fiable y **el mismo presupuesto de generaciones**, ¿rinde
> más gastar el cómputo en **muestras independientes** (Best-of-N) o en
> **reparar la muestra que ya tengo, mostrándole el contraejemplo**?

Y una segunda, que es la que hace interpretable la primera:

> Si reparar gana, ¿gana por el **CONTRAEJEMPLO** o por el simple hecho de
> volver a intentarlo con otro prompt?

## 3. Los TRES brazos, y por qué comparten raíz

Los tres arrancan de **la MISMA muestra `s1`** (una sola generación, compartida)
y reciben **el mismo presupuesto: 4 candidatos**. Solo cambia cómo se producen
los candidatos 2, 3 y 4. **La política de SELECCIÓN es idéntica en los tres**
(la literal de `cognia/program_creator/bon.py`: aprobado > `vis_ok` > el más
temprano), así que cualquier diferencia es de PRODUCCIÓN de candidatos, no de
selección.

| brazo | candidato 1 | candidatos 2-4 | qué recibe el modelo |
|---|---|---|---|
| **BoN** | `s1` | `s2,s3,s4` independientes, temp 0.8 | el enunciado, otra vez |
| **REP** | `s1` | `r2,r3,r4` en cadena desde el anterior | enunciado + código + **CONTRAEJEMPLO** (entrada, salida esperada, salida obtenida) |
| **PLACEBO** | `s1` | `p2,p3,p4` en cadena desde el anterior | enunciado + código + *"es incorrecto, produce una versión corregida"* — **sin contraejemplo** |

**Por qué existe el PLACEBO y no es opcional.** Un estudio con placebo
(arXiv:2606.31511) encontró que devolverle al modelo **la traza** o **el código
fallido** empata con un placebo sin contenido. El brazo REP también le devuelve
el código fallido; sin el brazo PLACEBO, un `REP > BoN` no distinguiría
*"el contraejemplo informa"* de *"reintentar con otro prompt diversifica"*.
**PLACEBO es el nulo del contenido**, igual que el AZAR es el nulo del selector.

**Lo que NO se le devuelve al modelo, y por qué:** ni la traza de la pila ni el
mensaje de excepción como pieza principal. Si la muestra revienta en vez de dar
salida, el contraejemplo **degrada** a `(entrada, esperada, EXCEPCIÓN: <tipo>)`
— se registra el reparto y se reporta, porque en esas muestras el brazo REP se
parece más al PLACEBO de lo que quisiera.

### Parada temprana, UNIFORME en los tres brazos

Si un candidato pasa **TODOS** los tests visibles, la cadena de ese brazo
**para**: no hay contraejemplo que dar, y un sistema desplegado tampoco seguiría
gastando. La regla es **la misma para BoN**, así que no favorece a nadie.

**Es LOSSLESS para la primaria:** el selector elige "aprobado > `vis_ok` > el
más temprano", así que si un candidato pasa todos los visibles es el elegido
tanto si se generan los siguientes como si no. Parar no cambia **ni un
veredicto**; solo ahorra reloj.

*Consecuencia que sí hay que declarar:* el cómputo REALIZADO por brazo será
distinto del presupuestado. Se reporta **generaciones gastadas y segundos de
pared por brazo**, y el neto se lee también **por generación gastada**.

## 4. Banco, y por qué este

- **LiveCodeBench, estrato `hard`**, del banco AMPLIADO (`lcb_test5.jsonl` +
  `lcb_test6.jsonl`, 342 tareas, 2024-09-22 → 2025-04-06, **todas posteriores
  al corte de entrenamiento del 20B**, junio 2024).
- **Por qué `hard`:** medido anoche, `easy` está **saturado al 94.8%** y no
  informa; `hard` da **pass@1 24.7%** y es donde el BoN cobró **+13.00**. Un
  banco saturado no puede validar un selector — la lección de `metrica-primaria-y-brazo-nulo`.
- **N = 70 tareas**, semilla `20260731`, `--ficheros` FIJADO a los dos
  incrementos (sin fijarlo, ampliar el pool cambia el orden barajado y el
  fichero deja de ser el mismo experimento).
- **Examen:** el de anoche, sin tocar — 5 visibles sorteados de
  `private_test_cases` con RNG determinista por tarea, el resto ocultos
  (capados a 15, entradas > 100 KB descartadas por la enmienda 2). **Ninguno
  aparece en ningún prompt.** Los `public_test_cases` NO se usan: están
  impresos en el enunciado en el 77.1% de los problemas.
- **El juez es el OCULTO**, idéntico para los tres brazos.

## 5. Primaria, nulos y criterio — escritos ANTES de mirar

**PRIMARIA:** neto **apareado a nivel tarea** `REP − BoN` sobre las tareas
**sin fallo de instrumento** en ningún brazo, puntuadas por el juez OCULTO.
Significación: **test de permutación apareado** (10.000 sign-flips sobre las
tareas discordantes).

**SECUNDARIA 1 (la que da el mecanismo):** neto apareado `REP − PLACEBO`, mismo
test. Es la que responde *"¿informa el contraejemplo?"*.

**SECUNDARIA 2:** `PLACEBO − BoN`. Si sale ≈ 0 y `REP − BoN` > 0, el
contraejemplo es el ingrediente activo. Si `PLACEBO ≈ REP`, lo activo es
reintentar, y el contraejemplo no aporta.

**LOS TRES NULOS**, sobre el pool realizado de cada brazo: `AZAR` simple,
`AZAR-CON-CÓDIGO`, `AZAR-1-TEST` (este **ya usa el examen**: no es "descartar
basura", es un selector débil). Se reportan **sobre las tareas donde el brazo
gastó el presupuesto entero** (sin parada temprana), porque en un pool truncado
por haber acertado el nulo está sesgado al alza — y también, etiquetada como
descriptiva, la versión sobre todas.

### Criterio pre-registrado

| veredicto | condición |
|---|---|
| **PASA** | `REP − BoN` > 0 con **P < 0.05** en el test apareado **Y** `REP − PLACEBO` > 0 **Y** segundos de pared de REP ≤ **1.3×** los de BoN |
| **GRIS** | `REP − BoN` > 0 con P < 0.05 pero `REP ≈ PLACEBO` (el contraejemplo no es lo activo) **o** el reloj se dispara por encima de 1.3× |
| **KILL** | `REP − BoN` ≤ 0, **o** P ≥ 0.05 |

**El KILL es el resultado esperado por la evidencia previa** (las rondas
restaban en web). Si sale KILL, la vía se cierra **también en código**, que es
donde tenía su mejor oportunidad, y eso es un resultado — no un fracaso de la
sesión.

**Regla anti-elección-con-los-datos-delante:** el estrato (`hard`), el N (70),
la semilla y los tres criterios quedan fijados aquí. No se sub-analiza por
plataforma, por longitud del enunciado ni por ningún corte que se me ocurra al
ver los números. Un corte post-hoc, si aparece, se etiqueta **descriptivo** y
**no cuenta como veredicto** — la regla que ya salvó el análisis de anoche.

## 6. Amenazas declaradas ANTES, con su control

1. **El contraejemplo podría filtrar el examen.** Los visibles se le muestran al
   modelo en el brazo REP. **No contamina el juicio**: el juez son los OCULTOS,
   disjuntos por construcción, y ningún oculto aparece nunca en ningún prompt.
   Sí cambia la interpretación: REP tiene **más información** que BoN sobre el
   examen visible. *Esto es una asimetría REAL y declarada, no un bug* — es
   justo la ventaja que la vía reclama, y por eso el criterio exige además
   ganar al PLACEBO, que tiene la misma estructura de prompt sin el contenido.
2. **Varianza entre corridas de ±34 puntos** (memoria `varianza-entre-corridas`).
   Controlada por diseño: **los tres brazos se generan en la misma corrida,
   intercalados a nivel tarea, compartiendo `s1`**. Solo se leen netos
   APAREADOS intra-corrida; ningún nivel se compara con corridas de otras
   noches.
3. **Facturar INSTRUMENTO al modelo** (107 muestras = 16% anoche). El runner
   devuelve `(resultados, MOTIVO)`, el motivo se persiste por muestra, la
   primaria excluye las tareas con fallo de instrumento en cualquier brazo, y
   **si la tasa de instrumento supera el 8% se PARA la corrida y se reproduce un
   caso a mano antes de analizar nada**.
4. **Prompt de reparación truncado.** Enunciado + código + contraejemplo puede
   pasarse de contexto. `n_ctx=16384` verificado en `/props`; el contraejemplo
   se **capa a 1200 caracteres por campo**; `finish_reason='length'` se cuenta
   como instrumento, no como fallo del modelo.
5. **Un `s1` compartido correlaciona los tres brazos.** Es deliberado: es lo que
   hace el apareado perfecto. El precio es que las diferencias entre brazos son
   más pequeñas que entre corridas independientes — y por eso la significación
   se calcula con un test **apareado**, no comparando niveles.

## 7. Lo que esta corrida NO responde

- Nada sobre el dominio **web**: allí no hay tests, y el cuello (fabricar señal
  para tareas nuevas) sigue donde estaba, con 10 vías muertas.
- Nada sobre el **pass@1 absoluto** frente a tablas publicadas: el prompt, el
  evaluador y el cap de la enmienda 2 son míos. Esa comparación es la
  Prioridad 2 de esta sesión y tiene su propio protocolo.
- Nada sobre **híbridos** (reparar dentro de BoN, o BoN sobre reparaciones). Si
  REP pasa, el híbrido es la siguiente sesión, no un brazo que se añade al ver
  los datos.

---

## ENMIENDAS

*(se appendean con fecha y hora; nunca se edita lo de arriba)*

### ENMIENDA 6 (2026-07-31 19:40) — REP-F (fallback a generación fresca): la potencia se calculó ANTES, y la vía queda SUSPENDIDA CON NÚMERO, sin gastar GPU

El corolario de diseño del resultado de la mañana pedía un brazo **REP-F**:
la cadena de reparación que cae a muestra independiente cuando el modelo se
niega o no hay nada que reparar (el contraejemplo triplica la negativa,
5.3%→15.8%, y 34 cadenas se cortaron sin gastar su presupuesto). Antes de
correrlo se calculó la potencia sobre `reparacion.json`
(`scripts/b3_potencia_repf.py`), y el cálculo pasó por verificación
adversarial independiente (2 agentes con recomputo propio).

**Primero, un error MÍO que la verificación cazó y se registra:** mi primera
cota decía *"+1 neto con fallback perfecto"*. Estaba **mal sumada**: solo
contaba las 3 tareas rescatables donde BoN también falla, y omitía que las 6
rescatables donde BoN pasa también suben el neto (+1 cada una: el discordante
a favor de BoN pasa a empate). Los dos verificadores reprodujeron mis números
crudos (135 tareas; BoN 59, REP 57; 39 cadenas cortadas = 34
`sin_codigo_previo` + 5 `sin_contraejemplo`; 9 rescatables por pool, 3 con
BoN fallando) y corrigieron la contabilidad. El script queda arreglado.

**Los números que valen (recomputados por mí y por los verificadores):**

| | |
|---|---|
| neto hoy REP − BoN | **−2** (20 discordantes, 9/11) |
| techo con fallback PERFECTO vía pool | **+7** (d=17, victorias 12/17) |
| P (1 cola) del TECHO | **0.0717** — a UNA victoria del umbral |
| victorias necesarias / MDE (1 cola, d=17) | 13 → **+9 netas** |
| mecanismo FRESCO fuera del pool | ~73 eslabones × P(4º acierta \| 3 fallan) = **2/62 = 3.2%** → ~1-2.3 aciertos esperados; con UNO, 13/18 → P = 0.0481 |

**Lectura honesta de ese cuadro:** el techo del fallback PERFECTO no alcanza
la significación (0.0717), y solo la cruza el escenario perfecto + suerte en
el mecanismo fresco. La esperanza REALISTA es mucho menor: en las 3 tareas
que moverían el neto contra BoN, el único candidato del pool que acierta es
de la cadena PLACEBO (ningún fresco), y la tasa fresca condicional es 3.2%
por muestra → neto esperado realista **+0 a +3, contra un MDE de +9**.

**DECISIÓN (antes de gastar nada):** REP-F **NO se corre esta noche**. No es
un KILL (sería matar la vía con un diseño que no puede verla — la enmienda 4
lo prohíbe) ni un "cierre por cota" (mi +1 era falso): es **SIN POTENCIA
ALCANZABLE en este banco**, decidido a coste cero. La GPU de la sesión va al
eje ESFUERZO (prioridad 1, candidato de ~18 pts). Condición de reapertura,
escrita: un banco `hard` sustancialmente mayor (154 tareas no dan más d), un
presupuesto k mayor que suba los discordantes, o evidencia externa de que
reparar-tras-fresco (el mecanismo que la cota del pool no contempla) rinde.

**Y la lección de método, otra vez:** la primera cota subcontaba en la
dirección que favorecía mi conclusión ("no correr"). La verificación
independiente del número de un solo agente —yo— no es opcional ni cuando el
número lo produje yo mismo.

### ENMIENDA 1 (2026-07-31 06:05) — antes de generar nada

Tres grados de libertad que el texto de arriba dejaba abiertos. Se cierran
**ahora**, con 0 muestras generadas, porque cerrarlos después de ver los datos
es exactamente el vicio que este método persigue.

1. **N = 90, no 70**, y con **corte por RELOJ** pre-registrado: la corrida para
   a las **09:45** o al agotar las 90 tareas, lo que llegue antes, y el análisis
   se hace sobre el **prefijo de tareas COMPLETAS**. `N_min = 50`: por debajo de
   50 tareas completas la corrida no emite veredicto, solo descriptivo.
   *Motivo, medido:* con la parada temprana, una tarea cuya `s1` ya pasa los
   visibles consume **1 sola generación** y **no discrimina entre brazos** (los
   tres arrancan y paran en el mismo sitio). En `hard` eso será ~30% de las
   tareas, así que 70 tareas dejarían ~49 informativas — justo en el filo.
2. **La P que decide es de UNA COLA** en la dirección pre-declarada
   (`REP − BoN > 0`), porque el criterio PASA es direccional. La de **dos colas
   se reporta al lado siempre**, y si discrepan del veredicto se dice en el
   resultado. *(Está implementado así en `_perm_apareado`.)*
3. **Reanudar rehace la tarea entera.** Una tarea sin marca de `cierre` se
   descarta al reanudar y se regenera completa. Sin esto sus registros
   parciales se sumarían a los nuevos y la tarea aparecería dos veces, con
   brazos de más candidatos de los que se le dieron.

**Y una verificación de instrumento que ya está hecha** (`b3_medir_contexto.py`,
sobre las 154 tareas `hard` reales): el prompt de reparación en su **peor caso**
ocupa **~2.389 tokens** de los 8.192 que quedan libres con `n_ctx=16384` y
`max_tokens=8192`. **0 de 154 se pasan de contexto.** La amenaza 4 queda cerrada
con número, no con confianza — el 8º caso de "presupuesto de pensamiento" en
este repo no va a ser este.

### ENMIENDA 3 (2026-07-31 06:15) — lo que tumbó la revisión adversarial, con 0 muestras generadas

Cuatro revisores independientes sobre el prereg y el código. **Devolvieron 19
BLOQUEA, muchos convergentes, y CUATRO cambian el experimento.** Los reproduje
yo mismo antes de aceptarlos; los números de abajo son míos, no suyos.

**1. EL BUG QUE HABRÍA MEDIDO OTRA COSA, y era mío.** `prompt_reparar` y
`prompt_placebo` construían la cabecera con `t['enunciado']` **pelado**,
mientras que BoN recibe `prompt_lcb(t)` — que además del enunciado lleva el
`starter_code` y las instrucciones de E/S (leer de stdin, escribir en stdout).
**REP y PLACEBO estaban compitiendo con MENOS información que el control**, y
el neto habría medido esa mutilación, no la reparación. Arreglado: los tres
brazos comparten la cabecera letra por letra (`_cabecera()` = `prompt_lcb`).

**2. FUGA POR CONTENIDO EN EL SPLIT, medida por mí** (`b3_fuga_split.py`, sobre
las 154 tareas `hard` reales): el split era disjunto **por índice**, pero
**12 tareas (7.8%) tienen algún caso VISIBLE cuya entrada se repite entre los
OCULTOS** — 23 de 690 visibles (3.3%). Enseñarle al brazo REP la salida
esperada de ese visible **le regala la del oculto**: la selección dejaría de
medir generalización y mediría identidad. Corregido: el oculto se queda sin los
casos cuya entrada coincida con un visible (`sin_fuga=True`), **idéntico para
los tres brazos**. *Y va con una consecuencia hacia atrás que se declara:* el
resultado de anoche (+21.00) se midió **con** esa fuga; afecta como mucho al
7.8% de las tareas y no se ha re-medido en esta sesión.

**3. EL ISO-CÓMPUTO NO SE MIDE EN RELOJ.** El criterio decía "≤1.3× los
segundos de BoN". Pero BoN manda **el mismo prompt** 3 veces y se come el caché
de prefill del servidor, mientras REP manda uno nuevo cada vez: el reloj
compara cachés, no cómputo. **La unidad pasa a ser TOKENS GENERADOS**
(`usage.completion_tokens`, que ahora se persiste por muestra). El ratio de
reloj se sigue reportando, etiquetado como contaminado.

**4. EL CONTRAEJEMPLO NO PUEDE LLEGAR MUTILADO EN SILENCIO.** Cortar la entrada
a 1200 caracteres sin decirlo produce un contraejemplo **autocontradictorio**
(una salida esperada que esos datos truncados no producen), que es peor que no
dar ninguno. Dos arreglos: **(a)** entre los casos visibles fallidos se elige
**el de entrada MÁS CORTA**, no el primero — el que más veces cabe entero;
**(b)** si aun así hay recorte, va **marcado en el prompt** con el tamaño real.

**5. LA PRIMARIA YA NO CONDICIONA SOBRE UNA VARIABLE POST-TRATAMIENTO.**
Excluir una tarea porque **alguna** de sus ~10 generaciones tuvo un fallo de
instrumento no es simétrico entre brazos (difieren en cuántas generaciones
hacen y con qué prompts). **La primaria pasa a ser TODAS las tareas**, con el
fallo de instrumento contando como fallo de ESE candidato — conservador e
idéntico para los tres. La versión limpia se reporta al lado; **si las dos
discrepan en el veredicto, se dice y no se firma ninguna.**
Y el filtro de "sucia" ahora incluye **los fallos del JUEZ** (`lote_expirado`,
arnés reventado), que la primera versión dejaba pasar como fallo del modelo —
el error exacto que costó 48 veredictos anoche.

### ENMIENDA 4 (2026-07-31 06:20) — LA POTENCIA, que es lo que casi firma un KILL falso

El hallazgo más caro de la revisión, y **lo verifiqué yo sobre los datos en
disco** (`b3_potencia_apareado.py`, sobre `lcb_uniforme.json` y
`lcb_hard_r2.json`):

| estrato | n | s1 falla visibles | discriminantes | con instrumento | **puede discordar** |
|---|---|---|---|---|---|
| easy | 43 | 2% | 14% | 0% | **2%** |
| medium | 51 | 37% | 31% | 0% | **12%** |
| **hard** | 73 | **66%** | **42%** | 23% | **18%** |

Una tarea solo puede DISCORDAR entre brazos si `s1` falla los visibles (si no,
los tres brazos paran en el mismo sitio) **y** además algún candidato puede
cambiar el veredicto oculto. En `hard` eso es el **18%**. Con N=70 eso son ~13
discordantes, y un sign-flip apareado con 13 discordantes **exige 10 victorias
de 13** para P<0.05: un efecto real de +4 tareas netas saldría P≈0.17 y **se
habría firmado KILL por falta de potencia, no por ausencia de efecto**.

Tres cambios:

1. **N = 154: TODO el estrato `hard` del banco ampliado**, con **corte por
   RELOJ pre-registrado a los 200 minutos** (implementado en el runner, y se
   comprueba ANTES de empezar cada tarea, nunca a mitad, para que el fichero
   solo contenga tareas completas).
2. **La potencia se reporta SIEMPRE junto al resultado**: discordantes
   observados, victorias necesarias para P<0.05, y **efecto mínimo
   detectable**.
3. **Se añade el veredicto `SIN POTENCIA`**, y **sustituye al KILL** cuando el
   efecto mínimo detectable es mayor que ±6 tareas netas. *Un diseño que no
   distingue "no hay efecto" de "no lo veríamos aunque lo hubiera" no tiene
   derecho a matar una vía.*

### ENMIENDA 5 (2026-07-31 06:26) — cierre de la revisión, y un fallo del instrumento cazado A MANO

**La revisión terminó con 62 hallazgos, 24 BLOQUEA propuestos y solo 2
CONFIRMADOS tras la fase de refutación** — y los dos eran el mismo:
**el contraejemplo se truncaba en silencio**. Los verificadores midieron el
tamaño del problema y el efecto del arreglo que yo ya había aplicado mientras
revisaban:

| | contraejemplos con entrada recortada |
|---|---|
| política vieja (el PRIMER visible fallido) | **24.4%** (10/41), 6 de ellos con el patrón patológico entrada-truncada + salida-esperada-completa |
| **política nueva** (el visible fallido de entrada MÁS CORTA, + marca de recorte) | **4.9%** (2/41), **los dos marcados en el prompt y registrados** |

Caso concreto que lo ilustra (`arc194_c`): entrada de **67.496 caracteres**, se
le mostraban **1.200 (1.8%)** sin marca, y debajo la salida esperada COMPLETA.
Eso no es un contraejemplo: es un par imposible de satisfacer, con la
instrucción explícita de satisfacerlo. Con KILL como resultado esperado, un
KILL habría sido **facturar instrumento al modelo en 1 de cada 4 rondas REP**.

**Residuo declarado que NO se arregla en esta corrida:** el arnés capa la
salida OBTENIDA a 1200 caracteres *dentro* del subproceso, así que
`obtenida_len` nunca la supera y la marca de recorte de ese campo concreto es
código muerto. Impacto bajo (al modelo no se le pide reproducir su propia
salida) y la corrida ya está lanzada; se arregla después y se dice.

**Y un fallo que la revisión no vio y salió de mirar la corrida a los 4
minutos.** La tasa de instrumento marcaba **28.6%**, muy por encima del 8% que
obliga a parar. Paré, y **reproduje los casos a mano**: el texto crudo decía
literalmente

> `'Sorry, I cannot provide a solution.'` — 1426 tokens de razonamiento,
> `finish_reason` normal, respuesta completa.

**No era el arnés fallando: era el modelo rindiéndose.** Eso es un fallo del
MODELO y tiene que contar como tal. Marcarlo como instrumento habría sido el
error **simétrico** al de anoche —facturarle al instrumento un fallo del
modelo— y, peor, habría expulsado de la primaria justo las tareas más
difíciles, que es donde vive el efecto. Se separan tres cosas que colapsaban
en una:

| marca | qué es | cuenta como |
|---|---|---|
| `instrumento` | respuesta vacía, truncada, HTTP, presupuesto de pared, `sin_contraejemplo` | fallo del ARNÉS |
| `sin_codigo_modelo` | respuesta completa y no truncada, sin código | **fallo del MODELO** |
| `no_generado` (`sin_codigo_previo`) | la cadena REP/PLA no tiene nada que reparar | **propiedad del MÉTODO** (y se saca del pool) |

Además, `sin_codigo`/`sin_tests` del juez dejan de contar como fallo del juez:
son la consecuencia de que no hubiera código, no una avería.

**Y se cierra un PASA degenerado** que la revisión sí cazó: `REP > PLACEBO` no
llevaba test, así que con 2-4 discordantes un `+1` de ruido bastaba para firmar
"el contraejemplo informa". Ahora exige además **P < 0.10 de una cola** en su
propio test apareado.

### ENMIENDA 2 (2026-07-31 06:05) — una predicción de MECANISMO, escrita antes de que existan datos

El brazo REP recibe **el test visible que falló**. Puede por tanto aprender a
pasar **ese test** sin arreglar el programa. Si eso ocurre, REP **ganará en
visibles y perderá en ocultos**, y su `DEJA_PASAR` (elegidos que pasan el
visible pero fallan el oculto) será **mayor que el de BoN**.

Se añade al análisis como lectura de mecanismo con la predicción firmada aquí,
para que no se pueda leer como un corte post-hoc si sale. **Es la forma más
probable de que un `REP − BoN` positivo sea un espejismo**, y también la forma
más probable de que un KILL tenga una causa legible.

**Control positivo del instrumento nuevo, PASA** (`b3_humo_contraejemplo.py`,
15 comprobaciones): la salida obtenida llega de verdad en modo `stdin` y
`functional`, la excepción se captura como tipo+mensaje **sin traza de pila**,
el código correcto no produce contraejemplo, un fallo **sin detalle** devuelve
`{}` en vez de inventarse `"(no output)"`, y **sin el flag el arnés se comporta
byte a byte como antes** (regresión `b3_humo_lcb.py`: 40/40, 31/31, 0/71).

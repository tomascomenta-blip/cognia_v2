# PREREG — Recuperar el instrumento con benchmarks PÚBLICOS de código

**Congelado el 2026-07-30 ~21:30, ANTES de generar una sola muestra.**
Cualquier cambio posterior va como ENMIENDA fechada al final, nunca editando
lo de arriba.

---

## 0. Por qué esto y no seguir en web

Medido en las sesiones previas y **no se re-litiga**:

- El sistema **construye** bien: techo pass@4 = 100% en los dos bancos web.
- El sistema **sabe elegir cuando tiene examen**: BoN +5.82 (p=0.0001) y +5.50
  (P=2.3e-4) **sobre el AZAR**, en dos corpus.
- Pero **se perdió la regla de medir**: el banco duro está saturado (pass@1
  92%) y ahí **P(un selector al azar saque 8/8) = 0.38–0.56**. De 9 tareas
  nuevas escritas para romper al sistema, **6 salieron 4/4 a la primera**.
- Y van **10 vías** de señal autogenerada muertas, explicadas de una vez por:
  *una verificación que no lee la especificación puede detectar INACTIVIDAD,
  pero no INCORRECCIÓN.*

**La razón de cambiar a benchmarks de código no es "tener tareas nuevas":
es que TRAEN LOS TESTS** — exactamente la pieza que las 10 vías no
consiguieron fabricar. Y el juez pasa a ser `subprocess + timeout` en vez de
Playwright, así que se acaban los cuelgues de JS.

---

## 1. Las dos trampas, declaradas antes de correr

**(a) CONTAMINACIÓN.** MBPP y HumanEval están en el pretraining. Se hereda
la regla que el propio repo ya escribió en `ecod_kernel.py`: *"el número
ABSOLUTO no se interpreta; el gate es el DELTA PAREADO"*. En consecuencia:

> **Prohibido comparar el pass@1 de MBPP con la tabla publicada de ningún
> modelo frontier.** MBPP solo vale como (i) humo del motor y (ii) terreno
> para un delta pareado interno (BoN vs AZAR), donde la contaminación afecta
> a los dos brazos por igual.

**(b) SATURACIÓN.** `INFORME_MISION_PROGRAMACION.md` ya registra que el easy
set de MBPP lo satura un 3B a temp 0. Cambiar un banco saturado por otro no
arregla nada. De ahí el criterio de admisión de la sección 3.

### Lo verificado EN RED hoy (2026-07-30), porque mi información podía estar vieja

| dato | valor verificado | fuente |
|---|---|---|
| Corte de entrenamiento de **gpt-oss-20b** | **junio 2024** | model card OpenAI (arXiv:2508.10925) |
| LiveCodeBench `code_generation_lite`, última versión | **release_v6**, problemas de **may-2023 → abr-2025**, 1055 problemas | HF `livecodebench/code_generation_lite` |
| ¿gated? | **No**, descargable sin cuenta y sin pagar | idem |
| Incremento más reciente | `test6.jsonl` (134 MB) | idem |

**Consecuencia:** existe una ventana temporal REAL de ~10 meses
(**jul-2024 → abr-2025**) **posterior al corte del 20B**. Ese es el único
terreno donde un número propio sería comparable con tablas públicas.

---

## 2. Diseño

### Bancos

- **B-MBPP** (humo + delta interno). 974 tareas con `test_list` de 3 asserts.
  Slice de evaluación: `task_id` 11–510, muestreado con semilla fija.
- **B-LCB** (ventana temporal). `test6.jsonl`, filtrado a
  `contest_date > 2024-06-30` — **estrictamente posterior al corte del 20B**.
  Trae `public_test_cases` y `private_test_cases` **ya separados por el propio
  benchmark**, que es el split de la sección 4 sin que lo escriba yo.

### Generación

- Backend: **gpt-oss-20b** en llama-server, `--parallel 1`, `--ctx-size 16384`
  (verificado en `/props` ANTES de gastar GPU: `total_slots == 1`).
- **K = 4** muestras independientes por tarea, **temperature 0.8**.
  *Diferencia declarada con el BoN de producción:* allí la diversidad viene de
  rehacer el pipeline entero (la temperatura perdía selectores); aquí no hay
  pipeline, hay una sola llamada, así que la diversidad **tiene que** venir de
  la temperatura. Se adopta el 0.8 de `ecod_kernel.py`.
- Prompt: el de `ecod_kernel.prompt_de` para MBPP (enunciado + primer assert
  como firma) y el estándar de LCB para B-LCB. Sin adornos.

### Juez

`subprocess` aislado + timeout 8 s + el sandbox del repo. Un test que revienta
o expira cuenta como **fallado**, nunca como infra.

---

## 3. CRITERIO DE ADMISIÓN DEL BANCO — pre-registrado, antes de mirar nada

Es el mismo que se usó para la cabecera web, y es lo que impide
auto-engañarse:

> **Un banco/slice ENTRA solo si el 20B queda en la banda `[20%, 80%]` de
> pass@1.** Fuera de esa banda **no discrimina y NO se usa para medir
> progreso**: se dice en voz alta y se busca otro slice.

- `pass@1` se estima como `aciertos_totales / (K · N)` sobre el juez OCULTO
  (sección 4), que es el pass@1 de la distribución que el BoN muestrea.
- **Junto a CUALQUIER número se reporta SIEMPRE lo que saca el AZAR en ese
  mismo banco.** Sin excepción.

**Descriptiva secundaria obligatoria (no es criterio, pero condiciona la
potencia):** fracción de tareas **discriminantes**, definidas como
`1 ≤ aciertos ≤ K−1`. Un banco puede estar en banda y aun así no dar nada que
elegir si sus tareas son todo-o-nada. Se declara.

---

## 4. EL EXPERIMENTO — BoN con los tests PARTIDOS (el de más valor)

Reproduce el diseño *contrato + held-out* **sin escribir un solo examen a
mano**, y para cientos de tareas.

### Split (congelado)

| banco | VISIBLES (los ve el selector) | OCULTOS (juzgan) |
|---|---|---|
| B-MBPP | `test_list[0]` y `test_list[1]` | `test_list[2]` + `challenge_test_list` |
| B-LCB | `public_test_cases` | `private_test_cases` |

*Límite declarado de B-MBPP, antes de ver el resultado:* el prompt ya muestra
`test_list[0]`, así que el selector comparte un assert con el generador; y el
juez oculto puede quedarse en **un solo assert**, que es un juez ruidoso.
B-LCB no tiene ninguno de los dos problemas — por eso es el banco principal
del experimento y MBPP el de humo.

### Los cuatro brazos, sobre el MISMO conjunto de muestras (apareado perfecto)

1. **CONTROL (s1)** — la primera muestra. Referencia histórica, **no** la
   referencia del veredicto.
2. **AZAR** — una muestra uniforme entre las K. **Es la referencia del
   veredicto** (regla del repo: *la referencia de un selector es el AZAR,
   nunca s1*, porque el neto del azar contra el control tiene p95 de +4 a +6).
3. **BoN** — selector sobre los VISIBLES, con la política **literal** de
   `cognia/program_creator/bon.py:157-160`:
   `pasa_todos_los_visibles > nº de visibles pasados > índice más temprano`.
4. **TECHO (pass@K)** — alguna muestra pasa los OCULTOS.

Los cuatro se puntúan **con el juez OCULTO y solo con él**.

### Métrica PRIMARIA y umbral de vida

> **PRIMARIA: neto apareado `BoN − AZAR`**, con `P(azar ≥ BoN)` estimada por
> **10.000 réplicas del nulo APAREADO** (apareado = sorteando solo sobre los
> ensayos que deciden el veredicto; mezclar ensayos sin s1 favorece al azar,
> error ya cometido y corregido el 2026-07-30).
>
> **VIVE si el neto supera el p95 del brazo nulo.** No un número absoluto.

- **KILL / NO REPLICA**: el neto no supera el p95 del nulo ⇒ la ventaja del
  BoN medida en web **no se reproduce en terreno público**, y se dice tal cual.
- Secundarias descriptivas (se reportan, **no** deciden): control s1, techo
  pass@K, pérdida del selector (ensayos donde el techo acierta y el BoN no).

### Lo que este experimento SÍ demuestra si sale

Que el mecanismo del BoN —el resultado más sólido de la semana, hasta hoy
medido solo en bancos web escritos por mí— **replica en un banco público, con
tests que no escribí, y contra la referencia correcta**.

---

## 5. Comparación con tablas públicas — la regla

Solo se compara el número de **B-LCB** (ventana post-corte). Y:

> **Si se compara con una tabla, se REPLICAN sus condiciones (prompt, k,
> temperatura, versión del dataset y ventana de fechas). Si no se replican,
> el número NO es comparable y hay que decirlo en la misma frase donde
> aparece.**

---

## 6. Higiene de corrida (heredada, no negociable)

- Revisión adversarial (1-2 agentes) **antes** de cada gasto de GPU.
- Humo barato antes de cada corrida larga.
- Corridas largas **desacopladas** (Start-Process + log + Monitor), guardado
  incremental atómico y `--reanudar`.
- Todo juzgado bajo `con_presupuesto`.
- **Verificar yo mismo los números que dé cualquier subagente.**
- Suite completa verde antes de cada commit con código.
- La flota se levanta verificando `/props` (slots=1, n_ctx≥16384) y se baja al
  terminar.

---

## 7. Lo que NO se hace en esta sesión

- **No** se abre una "vía 11" de señal autogenerada dentro de la familia
  muerta (contrato ciego / consenso / metamórfico / poda). Van 0 de 10 y hay
  un argumento estructural de por qué.
- **No** se tira el pipeline web. Cambia **dónde se mide**, no lo construido.
- **No** se gasta dinero real: nada de APIs de pago ni datasets de
  suscripción. Todo lo de arriba está verificado como descargable sin cuenta.

---

## ENMIENDAS

_(fechadas, append-only)_

---

### ENMIENDA 1 — 2026-07-30 ~21:35, tras revisión adversarial de 3 lentes

La revisión devolvió **7 BLOQUEA consolidados**. Los cinco puntos de hecho
los **reproduje yo mismo** antes de aceptarlos (regla del repo: no firmar el
número de un subagente). Se escribe ANTES de mirar el resultado final de
MBPP, que está corriendo.

#### 1.1 — La ventana temporal que firmé NO existe. Corrección.

Escribí *"ventana temporal REAL de ~10 meses (jul-2024 → abr-2025)"*. **Falso,
y era comprobable en 30 segundos sobre el fichero que ya tenía en disco:**

```
lcb_test6.jsonl: 175 problemas, 2025-01-04 .. 2025-04-06   (4 meses)
el filtro contest_date > 2024-06-30 elimina 0 de 175 -> es un NO-OP
112 atcoder / 63 leetcode · 80 hard / 52 medium / 43 easy
```

`test6.jsonl` es el **incremento** v5→v6, no el v6 completo de 1055. La
ventana sigue siendo **posterior al corte del 20B (junio 2024)**, así que el
propósito se mantiene; lo que era falso es su tamaño. Jul–dic 2024 exigiría
bajar `test5.jsonl` (557 MB), que no se hace esta noche.

**Es el mismo error que me costó tres números falsos ayer: declarar sin
medir.** Queda escrito.

#### 1.2 — BLOQUEA: los tests "públicos" de LCB están DENTRO del enunciado

El eje del prereg era *"B-LCB no tiene ninguno de los dos problemas"*.
**Medido por mí:**

| | |
|---|---|
| casos públicos con input **y** output dentro de `question_content` | **361/463 = 78.0%** |
| problemas con **TODOS** sus públicos en el enunciado | **135/175 = 77.1%** |
| problemas con ≥1 público dentro de `private` | **42/175 = 24.0%** |

El prompt incluye `question_content`, así que **el generador ve el examen del
selector** — el vicio `aprobado_sel` del gate en su forma peor. Mi frase era
falsa y en la dirección que me convenía.

**Split ENMENDADO de B-LCB** (`tests_lcb` en `b3_codigo.py`): los `public` **no
se usan**. VISIBLES = **5 casos sorteados de `private_test_cases`** con RNG
determinista por tarea (`semilla:task_id`, así reanudar o ampliar N no cambia
el examen); OCULTOS = los `private` restantes. Disjuntos por construcción y
**ninguno aparece en ningún prompt**.

*Declarado:* un caso público que además esté en `private` puede seguir en los
OCULTOS. Eso es fuga enunciado→juez, estándar en cualquier benchmark (los
ejemplos son parte del problema) y **afecta a los cuatro brazos por igual**,
así que no invalida el contraste; sí inflaría el pass@1 absoluto.

#### 1.3 — BLOQUEA: tres bugs del ARNÉS que facturaban instrumento al modelo

Los tres reproducidos por mí:

| bug | efecto | alcance medido |
|---|---|---|
| `from math import *` **sombrea el builtin `pow`** ⇒ `pow(2,10,7)` → `TypeError` | la exponenciación modular no compila | **18/175 (10.3%)** piden módulo 1e9+7 / 998244353 |
| `sys.stdin = io.StringIO(...)` **no tiene `.buffer`** ⇒ `sys.stdin.buffer.read()` → `AttributeError` | muere el idioma de entrada rápida de AtCoder | **112/175 (64%)** son AtCoder |
| preludio **concatenado** al fuente ⇒ `from __future__ import ...` → `SyntaxError` | — | — |

Arreglado: nombres concretos de `math` en vez de `*`; shim de stdin con
`.buffer`; preludio inyectado con `exec(_PRE, _g)` sobre los globals.
**Con tests de regresión en `b3_humo_lcb.py`** (una solución que usa
`pow(a,b,MOD)` y otra `sys.stdin.buffer.read()` deben pasar 40/40).

#### 1.4 — BLOQUEA: presupuesto POR TEST, y el juez deja de fallar en silencio

8 s globales contra **mediana 40 tests privados** (6537 en total; entradas de
p90 6.8 MB) reprobaría soluciones correctas en masa y tiraría el pass@1 fuera
de banda **por la razón equivocada**.

- Presupuesto **por caso**: `SEG_POR_TEST = 6` (el estándar de LCB), techo de
  lote `TOPE_LOTE = 240 s`.
- El arnés emite **una línea flusheada por caso**; un caso que expira pierde
  solo ese caso, no los otros 39.
- `_ejecuta_lote` devuelve `(resultados, motivo)` con
  `motivo ∈ {"", "lote_expirado", "sin_sentinel", "arnes_error", "sin_codigo"}`,
  guardado en la muestra como `juez_vis` / `juez_oc`. **Tres causas que antes
  colapsaban al mismo `[False]*n`** — la degradación silenciosa de siempre.
- El juez OCULTO corta al primer fallo (solo decide PASA/NO PASA).

#### 1.5 — BLOQUEA: el arnés de LCB no se puede validar con el dataset

`lcb_test6.jsonl` **no trae solución de referencia**. Un bug de protocolo daría
pass@1≈0 y el criterio de admisión lo leería como *"el banco no discrimina"*.

**Control positivo obligatorio antes de gastar GPU**: soluciones escritas a
mano (stdin + functional) contra el arnés, exigiendo el 100% de sus privados
y 0 para una solución rota. **Ya ejecutado: `abc387_b` 40/40, `3708` 31/31,
rota 0/71.** Si falla, es INFRA y se arregla — nunca se declara el banco fuera
de banda.

**B-MBPP excluye `task_id` 180 y 367**: su solución de REFERENCIA no pasa sus
propios asserts (control positivo 498/500). Defecto del dataset, no del modelo.

#### 1.6 — BLOQUEA: MBPP es humo, y su primaria NO cuenta como réplica

Dos hechos medidos que cambian el papel de MBPP:

- El juez oculto es **UN SOLO assert en 489/500 (97.8%)** del slice
  (`challenge_test_list` no vacío en 11/500). Yo escribí que "puede quedarse
  en un solo assert": son casi todos.
- **`P(pasa el oculto | pasa los visibles) = 0.849`** (2451 mutantes AST),
  y solo **51/498 tareas (10.2%)** permiten que el oculto contradiga al
  selector. En el 90% de MBPP, el juez oculto **no tiene forma de discrepar**.

> **Regla, escrita antes de ver el número final: si un banco no entra en la
> banda [20%,80%], su neto BoN−AZAR se reporta como DESCRIPTIVO y NO cuenta
> como réplica, sea cual sea su p. Y MBPP no cuenta como réplica ni entrando
> en banda**, porque su juez oculto solo discrepa en el 10% de las tareas.
> Cualquier BoN−AZAR de MBPP se publica con el **0.849 en la misma frase**.

Esto importa porque la admisión de MBPP está **derivando sobre el estimador**
(80.2% a las 212 muestras, 77.6% a las 497): decidir con ella después de verla
sería elegir el terreno con los datos delante.

**B-LCB es el único banco que puede producir un veredicto**, y su fallback
está **cerrado y ordenado aquí**: si `todo-175` no entra en banda, el único
slice de repuesto permitido es **`easy+medium` (95 tareas)**; si tampoco entra,
el veredicto es **"sin banco"**, no un veredicto sobre el BoN. **Máximo 2
intentos, ningún otro corte** (ni plataforma, ni fecha, ni `starter_code`).

#### 1.7 — BLOQUEA: pool común, y la primaria excluye los fallos de instrumento

- **Los cuatro brazos operan sobre el MISMO pool de K, sin filtrar.** Una
  muestra sin código extraíble cuenta como fallo de visibles y de ocultos en
  los cuatro. Ningún ensayo se descarta; `n` idéntico en los cuatro. (El
  `bon.py:144` de producción filtra `con_html` antes de rankear; ese filtro
  **no** se replica aquí, porque daría al selector un +neto gratis por
  descartar inválidas.)
- **PRIMARIA = neto sobre las tareas con 0 fallos de instrumento entre las K.**
  El neto con todo dentro va como secundaria. Y se declara desde ya:
  **si el efecto solo sobrevive incluyendo los fallos de instrumento, lo
  medido es INACTIVIDAD y se dice tal cual** — que es exactamente la frase
  que unifica las 10 vías muertas, reapareciendo dentro del experimento nuevo.
- Se añade el brazo descriptivo **AZAR-VÁLIDAS** (uniforme entre las muestras
  con código extraíble).

#### 1.8 — Menores adoptados

- **`max_tokens` y `reasoning_effort` congelados**: 4096 en MBPP (medido
  suficiente: 1/497 vacía, 0 truncadas), **8192 en B-LCB**;
  `chat_template_kwargs={"reasoning_effort":"low"}` explícito. Si
  `truncado_por_longitud` > 5% en el piloto, se sube **antes** de la corrida
  y se anota; nunca después de ver el veredicto.
- **`N_min = 100` tareas completas** o el banco no decide. La regla de corte
  es **el RELOJ sobre el orden ya barajado con semilla fija**, nunca el
  resultado; se analiza el prefijo completo.
- **AZAR = valor esperado** del selector uniforme (no un sorteo realizado:
  metería ruido gratis en la primaria). `vive = BoN > p95(nulo)` es
  equivalente a `P(nulo ≥ BoN) < 0.05`; se reportan los dos.
- **CONTROL (s1) es descriptivo y nada más**: aquí las K muestras son i.i.d. a
  temp 0.8, así que **s1 y AZAR son la misma distribución por construcción**.
  El "+2/+3 dentro del ruido" medido en web **no transfiere** (allí s1 venía
  del pipeline por otra ruta). No se interpreta ningún BoN−s1.
- **`P < 1e-4`**, no `P = 0.0001`: con 10.000 réplicas ese es el suelo.
- **Se retira la comparación del Youden J con el contrato interno (+12.2).**
  No es comparable: aquél se midió en unidades de PÁGINA contra un juez a
  mano, este en unidades de MUESTRA y tests-contra-tests, con severidad
  asimétrica. Es el mismo error de tabla que la revisión cazó ayer
  (reject-healthy contra approve-bad). El J se reporta **solo** como
  descriptiva interna del banco.
- **§5 queda cerrada: en esta sesión NO se compara con ninguna tabla
  pública.** El prompt no es el oficial de LCB, ni el evaluador (timeout
  propio, `==` estricto sin las tolerancias del checker oficial, preludio
  propio), y ninguna tabla reporta sobre este incremento de 175. Dejar la
  puerta abierta era invitar a una comparación ilegítima.
- **Descriptivas obligatorias añadidas**: fracción de tareas con **empate en
  visibles** (si los K empatan, `bon.py` cae en "índice más temprano" = s1 y
  el BoN **no puede** batir al azar por construcción), y tasa de timeouts por
  brazo.

#### 1.9 — Lo que la revisión confirmó que está BIEN

- La banda de admisión es **bilateral**: ninguna transformación monótona la
  cruza en una sola dirección. Es justo el diseño correcto contra el fallo de
  la poda del 2026-07-30.
- El nulo es **apareado sobre las mismas tareas que deciden**, y la
  referencia es el **AZAR**, no `s1`.
- El BoN **no relaja ni endurece** el examen: elige entre muestras con el
  examen fijo, así que la monotonicidad que mató a la poda **no se reproduce**.
- El split lo trae el benchmark: **no hay circularidad "el examen lo escribí
  yo"**, que era el vicio de las 10 vías.
- La política del selector citada coincide **literalmente** con
  `bon.py:157-160`.

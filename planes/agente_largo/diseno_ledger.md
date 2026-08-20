# Diseno: LEDGER DETERMINISTA

**Lente:** el LLM no comprime. La memoria es un registro append-only de eventos que el *harness*
escribe como efecto lateral de ejecutar herramientas, y el contexto del proximo ciclo se
**reconstruye con codigo** — una proyeccion, no un resumen. No hay resumen de resumen porque no
hay resumen.

Fecha: 2026-08-19. Arquitecto 1 de 3 (disenado sin ver a los otros dos).
Todos los numeros vienen de `medicion_kv.md`, `falsacion.md`, `estado_del_arte.md` e
`inventario_cognia.md` de esta misma carpeta. Lo que no esta medido lo digo.

---

## 0. Veredicto en una linea, y las tres premisas del dueno que este diseno TIRA

La idea de auto-lobotomia es correcta **por un motivo distinto del que la motivo**, y su pieza
central — "el agente comprime su estado" — es exactamente la pieza que hay que borrar.

| Premisa del encargo | Que hago con ella |
|---|---|
| "Se lobotomiza para ahorrar VRAM" | **Borrada.** El KV se reserva entero al cargar: 13 168 MiB @2 944 tok = 13 155 MiB @187 874 tok. La lobotomia recupera **0 MiB**. La VRAM se gestiona con `--ctx-size`, una vez, al arrancar. |
| "El agente comprime su estado" | **Borrada.** Comprime `proyeccion.py`, codigo puro, determinista, sin LLM. Coste medido de la compresion LLM en falsacion: **16,49 s**. Coste de un fold sobre 7 000 eventos: **~0,15 s**. |
| "Ventana corta" | **Borrada como hecho, conservada como disciplina.** El backend sirve 200 192 tokens. Lo que es corto no es la ventana: es el **horizonte conductual**, H(0,5) ~ 8 turnos en Gemma3-27B (arXiv:2509.09677). El ciclo se corta a los 8 pasos, no cuando se llene nada. |

Lo que **si** justifica destruir el contexto, con numero: *self-conditioning*. Qwen3-32B en el
turno 100 cae de ~85% (historial limpio) a ~70% con 25% de errores inyectados y a ~55% con 50%, y
**escalar el modelo no lo mitiga**. Destruir el contexto es desinfectar, no ahorrar. Corolario que
gobierna todo el diseno: **la traza de errores no viaja entre ciclos; viaja un contador**.

Y el hallazgo de `falsacion.md` que este diseno tiene que respetar o muere: recall de
restricciones **1,000 dejandolas verbatim en la ventana a 111 406 tokens**, 0,526 seleccionandolas
de un almacen, 0,083 en cascada. Traduccion: **cualquier cosa que seleccione restricciones esta
peor que no hacer nada**. Por eso la banda de restricciones de mi proyeccion es verbatim, integra,
sin seleccion, y si no cabe el sistema **se para** en vez de recortar.

---

## 1. El principio

Un ledger de eventos no es "otra memoria". Es la **traza de derivacion** del trabajo. La diferencia
con todo lo demas del inventario:

- `memory_compressor.py` clusteriza y **borra los originales** -> resumen de resumen. Antipatron.
- `long_term_consolidator.py` promueve a hecho **por repeticion >= 3** -> un agente que repite una
  invencion tres veces la asciende a permanente. Antipatron.
- `forgetting.py` aplica decay temporal a restricciones -> *governance decay*. Antipatron.
- El ledger **no borra, no resume, no olvida**. Invalida (evento `retractacion`) y anade. Es la
  validez temporal de Zep, que es la unica pieza de esa familia que sobrevivio a la revision de
  `estado_del_arte.md` (sus benchmarks no, sus mecanismos si).

Tres invariantes duras:

**I1 — El modelo no escribe hechos.** No existe la tool `emitir_hecho`. Un hecho entra al ledger
solo cuando lo produce una medicion (sha de disco, exit code de proceso, cita literal verificada).
Lo que el modelo dice va a un tipo distinto (`afirmacion`) con techo de confianza 0,30 y **sin ruta
de ascenso por repeticion**.

**I2 — La confianza es una funcion pura de la procedencia.** El modelo nunca emite un numero de
confianza. Se calcula. `falsacion.md` mostro por que: la confianza la emitiria el mismo modelo cuyo
juicio esta al nivel del azar (exactitud balanceada 0,517 / 0,523), o sea que produciria hechos
falsos con etiqueta creible — peor que no etiquetar.

**I3 — La proyeccion es un fold puro y se verifica recomputandola entera.** En cada reset se
recalcula desde el evento 0 y se compara sha con la version incremental. Si difieren, es un bug del
fold y se grita. Esto convierte la "degradacion de memoria" — que es invisible por definicion — en
un **evento detectable byte a byte**. Es la respuesta directa a la cascada 24->2 de H4.

---

## 2. Componentes

| Componente | Modulo | Responsabilidad |
|---|---|---|
| **Ledger** | **NUEVO** `cognia/ledger/registro.py` | Append-only JSONL con cadena de sha. Un solo escritor, lock de fichero. No expone borrado. |
| **Emisor automatico** | REUSO `cognia/harness/interceptor.py` (`antes`/`despues`) | El unico enchufe. Cada `run_tool` produce eventos `fichero`/`comando`/`verificacion` **medidos**, sin preguntarle nada al modelo. |
| **Proyector** | **NUEVO** `cognia/ledger/proyeccion.py` | `proyectar(eventos, presupuesto) -> str`. Funcion pura. Sin LLM. Sin red. Determinista bit a bit. |
| **Detector de contradicciones** | **NUEVO** `cognia/ledger/contradiccion.py` | 7 reglas mecanicas. Emite eventos `contradiccion`. |
| **Critico mecanico** | **NUEVO** `cognia/ledger/critico.py` + REUSO `estado/presupuesto_progreso.Progreso`, `flujos/examen.py` | 7 chequeos; **re-ejecuta** los comandos de criterio, no se fia del registro. |
| **Critico LLM (condicional)** | REUSO `harness/oraculo.py` (canal a otro modelo, transporte inyectado) + `agent/workflows.criticar` | Solo modo **comparativo A vs B**. Existe **si y solo si** el experimento E3 lo aprueba. |
| **Gate de arranque de ciclo** | **NUEVO** `cognia/ledger/gate.py` + REUSO `estado/canal.sembrar_trazadores` / `comprobar_trazadores` / `_presente` | Cuenta restricciones literalmente presentes en la proyeccion. <100% = ABORTA el ciclo. |
| **Motor de ciclos** | REUSO/PARCHE `cognia/agent/horizonte.py` (`ciclos_con_contrato`) | Ya hace el ciclo con contexto destruido. Cambios: quitar `_TECHO_CICLOS = 3`, sustituir `estado_tarea.resumen_para_prompt` por `proyeccion.proyectar`, resolver rutas contra el workspace y no contra el CWD del proceso. |
| **Disparador** | REUSO `harness/contexto_vivo.registrar_uso` (hoy **cero llamadores**) + `harness/limites.py` (hoy **huerfano total**, ya trae `LimiteExcedido` tipada) | `loop.py:1077` lee `resp.usage.prompt_tokens` y lo tira. Se conecta. |
| **Recuperacion** | REUSO `cognia/agent/rlm.py` (`ContextoVivo`, `_ctx_grep`, patron `register(tool)`) | El ledger es el corpus. `ledger_grep`/`ledger_ver` son dos tools nuevas registradas con el mismo patron que las 5 del RLM. |
| **Provenance de citas** | REUSO `cognia/search/evidencia.verificar_cita` (literal, sin juez) | Hoy solo se usa para web. Se usa para todo texto citado. |
| **Multiagente** | REUSO/PARCHE `delegar_subtarea` | El subagente escribe **en el ledger padre**; deja de devolver 600 chars lossy. |
| **Anticuerpos** | REUSO `cognia/inmune/anticuerpos.py` + `cognia/autopsia/causal.py` | Cada contradiccion cerrada sintetiza un chequeo que corre al arrancar. |
| **Rollback de ficheros** | REUSO `cognia/harness/checkpoints.py` | Restaura ficheros; el ledger aporta los sha para verificar que la restauracion fue correcta. |

**Lo que NO uso, y por que:** `memory/memory_compressor.py`, `memory/forgetting.py`,
`memory/long_term_consolidator.py` (los tres antipatrones de arriba), `/compactar` del CLI
(`cli.py:9532` solo llama `_console.clear()` y repinta un panel; no toca `_history`), y
`loop._recortar_mensajes` (truncado destructivo a 200 chars, sin recuperabilidad) — este ultimo se
**desactiva** con `COGNIA_LEDGER=1`, porque con reset por pasos nunca se llega al 0,8 de `n_ctx`
que lo dispara.

---

## 3. Formato exacto de la memoria

### 3.1 Los ficheros

```
.cognia/tareas/<task_id>/ledger.jsonl      # append-only, un evento por linea
.cognia/tareas/<task_id>/fold.json         # checkpoint del fold cada 1000 eventos
.cognia/tareas/<task_id>/proyeccion.txt    # ultima proyeccion emitida (auditoria)
.cognia/tareas/<task_id>/cierre.json       # veredicto final
```

Convive con `estado_tarea.dir_tareas()`, que ya usa esa ruta.

### 3.2 Cabecera comun de todo evento

| Campo | Tipo | Significado |
|---|---|---|
| `i` | int | Indice monotono, 1-based. Es la direccion estable para refs, rollback y auditoria. |
| `ts` | float | epoch **del reloj del proceso emisor**. (Leccion `evento-sellado-con-reloj-rancio`: nunca de un cache.) |
| `ciclo` | int | Ciclo en el que se emitio. |
| `t` | str | Tipo (15 valores, seccion 3.3). |
| `quien` | str | `ejecutor` \| `critico` \| `usuario` \| `harness` \| `sub:<nombre>` |
| `origen` | str | `medido` \| `usuario` \| `citado` \| `derivado` \| `modelo` |
| `conf` | float | **Derivado de `origen`, jamas emitido por un LLM.** Tabla en 3.4. |
| `refs` | [int] | Eventos de los que depende. Vacio = evento raiz. |
| `prev` | str | sha256[:6] de la linea anterior. Cadena: detecta escritura concurrente e insercion. |

### 3.3 Los 15 tipos

| `t` | Quien lo puede emitir | Persistencia | Va a la proyeccion |
|---|---|---|---|
| `objetivo` | usuario | permanente, inmutable | SIEMPRE, verbatim |
| `restriccion` | usuario, harness (derivada) | permanente, **sin caducidad ni decay** | SIEMPRE, **todas**, verbatim |
| `criterio` | usuario, harness | permanente | SIEMPRE, con su ultimo veredicto |
| `fichero` | harness (interceptor) | actualizable | ultimo por ruta, tope 20 |
| `comando` | harness (interceptor) | efimero | NO (solo como contador de firma) |
| `verificacion` | harness, critico | actualizable | como estado PASS/FAIL/NUNCA |
| `decision` | ejecutor (tool) | actualizable | ultimas 8 **con `refs` medidas** |
| `afirmacion` | ejecutor (tool) | efimera | NO. Solo por `ledger_grep`. |
| `pendiente` / `resuelto` | ejecutor, harness | actualizable | abiertos, tope 10 |
| `contradiccion` | harness (detector) | hasta cierre | SIEMPRE, **sin tope** |
| `retractacion` | usuario, critico, harness | permanente | NO (actua invalidando) |
| `leccion` | ejecutor, critico | permanente | ultimas 6, forma imperativa positiva |
| `ciclo` | harness | permanente | como contadores |
| `critica` | critico | actualizable | ultimo veredicto |

### 3.4 Tabla de confianza (funcion pura, `conf = f(origen)`)

| `origen` | Como se produce | `conf` | Puede ascender? |
|---|---|---|---|
| `medido` | sha256 de disco, exit code de proceso, `stat` | **1,00** | — |
| `usuario` | tecleado por el dueno | **1,00** | — |
| `citado` | substring literal presente en fuente nombrada, via `evidencia.verificar_cita` | **0,90** | — |
| `derivado` | funcion pura de `refs` | **min(conf de refs)** | — |
| `modelo` | lo dijo el LLM | **0,30 (techo duro)** | **NO por repeticion.** Solo emitiendo un evento NUEVO `verificacion` que lo referencie; el `modelo` original se queda en 0,30 para siempre. |

Esto es la respuesta al hueco 4 del inventario: `long_term_consolidator` promueve por frecuencia.
Aqui la frecuencia **no es evidencia** y esta prohibida por construccion.

### 3.5 Eventos reales rellenados

```jsonl
{"i":1,"ts":1755600001.02,"ciclo":1,"t":"objetivo","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"prev":"000000","texto":"Conectar anotar_restriccion/anotar_decision de cognia/estado/canal.py al bucle y darle persistencia a disco, sin romper la suite."}
{"i":2,"ts":1755600001.03,"ciclo":1,"t":"restriccion","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"prev":"a41f0c","texto":"Todo cambio detras de env COGNIA_LEDGER=1, apagado por defecto.","ambito":"*"}
{"i":5,"ts":1755600001.06,"ciclo":1,"t":"restriccion","quien":"harness","origen":"derivado","conf":1.0,"refs":[1],"prev":"77b2e9","texto":"Usar venv312\\Scripts\\python.exe, nunca el python global.","ambito":"*","regla":"CLAUDE.md"}
{"i":6,"ts":1755600001.07,"ciclo":1,"t":"criterio","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"prev":"1c9004","id":"C1","cmd":"venv312\\Scripts\\python.exe -m pytest tests/test_canal_persist.py -q","exit_esperado":0}
{"i":812,"ts":1755607412.31,"ciclo":7,"t":"fichero","quien":"ejecutor","origen":"medido","conf":1.0,"refs":[],"prev":"3c81a7","ruta":"cognia/estado/canal.py","sha":"e3b0c44298fc1c14","bytes":18441,"op":"editar","existe":true}
{"i":813,"ts":1755607419.88,"ciclo":7,"t":"comando","quien":"ejecutor","origen":"medido","conf":1.0,"refs":[812],"prev":"9f2a14","cmd":"venv312\\Scripts\\python.exe -m pytest tests/test_canal_persist.py -q","exit":1,"cola":"tests/test_canal_persist.py:41: AssertionError: assert 'R3' in render(estado)"}
{"i":814,"ts":1755607419.89,"ciclo":7,"t":"verificacion","quien":"harness","origen":"derivado","conf":1.0,"refs":[813,6],"prev":"5d70bb","id":"C1","ok":false}
{"i":815,"ts":1755607431.40,"ciclo":7,"t":"decision","quien":"ejecutor","origen":"modelo","conf":0.3,"refs":[812,813],"prev":"e0a3f1","texto":"Serializar el canal en JSON lines y no en pickle: el fichero tiene que ser diffeable.","porque":"e#813 muestra que el test compara texto"}
{"i":816,"ts":1755607433.02,"ciclo":7,"t":"afirmacion","quien":"ejecutor","origen":"modelo","conf":0.3,"refs":[],"prev":"b21c88","texto":"render() ya respeta el orden _ORDEN, asi que R3 deberia salir primero."}
{"i":903,"ts":1755607980.11,"ciclo":8,"t":"contradiccion","quien":"harness","origen":"medido","conf":1.0,"refs":[812],"prev":"4ee901","regla":"C1","texto":"cognia/estado/canal.py: sha registrado e3b0c44298fc1c14, sha en disco ahora 1a5f7d9042bb01ce. Editado fuera del agente."}
{"i":904,"ts":1755607981.55,"ciclo":8,"t":"leccion","quien":"critico","origen":"derivado","conf":1.0,"refs":[813,903],"prev":"81f7d2","texto":"Re-leer el fichero antes de editar cuando hayan pasado mas de 2 ciclos desde el ultimo sha."}
{"i":905,"ts":1755607982.00,"ciclo":8,"t":"retractacion","quien":"critico","origen":"derivado","conf":1.0,"refs":[816],"prev":"cc10ab","motivo":"afirmacion sin verificacion tras 2 ciclos; e#814 la contradice."}
```

---

## 4. Emision: quien emite, cuando, y por que no se puede callar

Tres vias, en orden de fiabilidad:

**V1 — Automatica, medida, imposible de evitar (95% del volumen).** `interceptor.despues(name, args,
ctx, out, ok)` ya recibe *todo* lo necesario. Ahi se llama a `registro.anotar()`, que reusa la
logica de `canal.anotar_fichero` (sha256 y bytes **del disco**, no de lo que el modelo dijo que
escribio; si no existe, `ok=False` aunque el modelo jure que lo creo) y `canal.anotar_comando`
(exit real, cola de 160 chars — la cola y no la cabeza, porque el traceback esta al final). El
modelo no participa. **No hay forma de trabajar sin emitir.**

**V2 — Obligatoria por gramatica (decisiones, pendientes, lecciones).** 4 tools nuevas registradas
con el patron de `rlm.register(tool)`:

| Tool | Firma | Efecto |
|---|---|---|
| `decidir` | `decidir <texto> --porque <i,i>` | Evento `decision`. **`--porque` con al menos un `i` de evento medido es obligatorio**; sin el, la tool devuelve error y no emite. |
| `pendiente` | `pendiente <texto>` | Evento `pendiente`. |
| `resolver` | `resolver <texto>` | Evento `resuelto` (casa por igualdad normalizada y luego substring, como `canal.resolver_pendiente`). |
| `leccion` | `leccion <texto imperativo>` | Evento `leccion`. Rechaza texto que empiece por "no " (forma negativa): el self-conditioning entra por ahi. |

**V3 — Derivada por codigo.** Las `restriccion` con `origen: derivado` las extrae un extractor
determinista del texto de la tarea y de `CLAUDE.md` (imperativos con negacion + rutas + nombres de
binario). Las `verificacion` se derivan de un `comando` cuando su `cmd` casa con un `criterio`.

### El ataque a mi propio diseno, parte 1: y si no emite nada?

Un ciclo de pura prosa emite 1 evento (`ciclo`) y **la proyeccion del ciclo siguiente sale identica
a la anterior**. Mismo contexto -> misma respuesta -> mismo no-evento: **punto fijo, loop infinito,
perfectamente determinista y silencioso.** Es el peor modo de fallo posible en un proyecto donde el
fallo tipico es el vacio silencioso.

Defensa, mecanica, en `gate.py`, al cerrar cada ciclo:

```
si eventos_medidos(ciclo) == 0:
    emitir contradiccion(regla="C6", texto="ciclo sin ningun evento medido")
    si dos ciclos seguidos: CORTE DURO, veredicto "mudo", informe al usuario
```

Y como una leccion en prosa no impide nada, va como test: `tests/test_ledger_mudo.py` construye un
`completar` falso que solo devuelve prosa y **exige** el corte en 2 ciclos.

### El ataque, parte 2: y si emite eventos MALOS?

| Caso | Defensa |
|---|---|
| **Miente sobre un efecto** ("escribi el fichero") | Imposible: V1 mide el disco. Si no existe, `existe:false`, `ok:false`. El evento contradice al modelo. |
| **Emite decisiones erroneas** | `conf 0,30`, no ascienden nunca, y **solo entran en la proyeccion si tienen `refs` a un evento medido**. Las demas viven en el ledger y solo salen por `ledger_grep`. (Ver "COMO ME ROMPO" #3: esto no basta.) |
| **Emite spam** (200 pendientes) | Topes duros por banda: el spam no llega al contexto. Y `gate.py` emite `contradiccion` si un ciclo emite mas de 3x la mediana de eventos-modelo de los ultimos 10 ciclos. |
| **Emite una restriccion falsa** | El modelo **no puede** emitir `restriccion`. No existe la tool. Solo usuario y extractor determinista. |
| **Emite lecciones envenenadas** | Solo forma imperativa positiva, y con `refs`; y las lecciones caen del render a las 6, ordenadas por recencia. |

---

## 5. La proyeccion (el mecanismo de compresion)

`proyectar(eventos, presupuesto_chars=12000, ts) -> str`. Funcion pura. **Sin LLM, sin red, sin
reloj propio** (el `ts` se pasa como argumento para que sea reproducible bit a bit).

### 5.1 Bandas por persistencia, y el orden importa por dos motivos distintos

| Banda | Contenido | Regla de acotado | Chars tipicos |
|---|---|---|---|
| **A. Inmutable** | objetivo + **todas** las restricciones verbatim + criterios | **Ninguna seleccion.** Si excede 4 000 chars -> `HARD_STOP` (excepcion tipada, 5.3) | ~900 |
| **B. Estado derivado** | ficheros (ultimo por ruta, 20), criterios PASS/FAIL/NUNCA, pendientes abiertos (10), decisiones con refs medidas (8), **contradicciones abiertas (sin tope)** | fold desde cero cada vez | ~900 |
| **C. Senal negativa comprimida** | contador `firma -> n, exit` + lecciones (6) + **cola de 160 chars del ultimo error del ciclo anterior, y solo ese** | topes duros | ~350 |
| **D. Indice** | "1042 eventos, 7 ciclos. ledger_grep / ledger_ver" | 1 linea | ~90 |
| **E. Recitado** | criterio activo + las 2 restricciones cuyas entidades aparecen en los pendientes abiertos | 2 lineas | ~130 |

El orden **A, B, C, D, E** resuelve dos restricciones que parecen chocar:

- *Cache de prefijo*: "memoria al principio e inmutable; lo que cambia, al final". La banda A no
  cambia entre ciclos -> vive dentro del prefijo cacheado. Medido: cabecera 16k + cola distinta =
  **242 ms vs 5 830 ms (24x)**. La regla dura es distancia absoluta ~512 tokens: por eso todo lo
  mutable va detras, junto, y nunca intercalado.
- *U-shape / recitado*: lo importante tambien tiene que estar al final. La banda E lo repite en 130
  chars. La literatura da +4% en RULER por recitar la evidencia antes de resolver. Cuesta 33 tokens.

### 5.2 La proyeccion real, rellenada

```
=== OBJETIVO (e#1, inmutable) ===
Conectar anotar_restriccion/anotar_decision de cognia/estado/canal.py al bucle
y darle persistencia a disco, sin romper la suite.

=== RESTRICCIONES (7/7 presentes, verbatim, NUNCA se resumen) ===
R1 [usuario]  No tocar cognia/agent/loop.py fuera de bucle_nativo.
R2 [usuario]  Todo cambio detras de env COGNIA_LEDGER=1, apagado por defecto.
R3 [derivada] Usar venv312\Scripts\python.exe, nunca el python global.
R4 [usuario]  No borrar ficheros del repo; solo crear o editar.
R5 [derivada] cognia/memory/ esta vetado (memory_compressor, forgetting, consolidator).
R6 [usuario]  La suite debe quedar en 5738 passed / 0 failed.
R7 [usuario]  Sin red durante los tests.

=== CRITERIOS (3) ===
C1 FAIL   venv312\Scripts\python.exe -m pytest tests/test_canal_persist.py -q
C2 PASS   venv312\Scripts\python.exe -c "import cognia.estado.canal"
C3 NUNCA  venv312\Scripts\python.exe -m pytest -q

=== FICHEROS (medidos, sha256[:8]) ===
cognia/estado/canal.py             e3b0c442  18441 B  editar  ok  c7
tests/test_canal_persist.py        9f86d081   6120 B  crear   ok  c7
cognia/ledger/registro.py          2c26b46b   4033 B  crear   ok  c5

=== PENDIENTES (2) ===
P1 conectar anotar_restriccion en loop.bucle_nativo tras run_tool
P2 anadir guardar()/cargar() al cierre de ciclo en horizonte.py

=== DECISIONES VIGENTES (3, con evidencia medida) ===
D815 JSON lines y no pickle: el fichero tiene que ser diffeable   (ref e#812,813)
D644 el sha se calcula sobre bytes, no sobre texto                (ref e#301)
D501 el canal vive en .cognia/tareas/<id>/, no en el CWD          (ref e#498)

=== CONTRADICCIONES ABIERTAS (1) — resolver antes de seguir ===
X903 [C1] cognia/estado/canal.py: sha registrado e3b0c442, en disco ahora
     1a5f7d90. Editado fuera del agente. RE-LEE antes de escribir.

=== YA INTENTADO (contador; las trazas NO viajan) ===
pytest tests/test_canal_persist.py -q      -> exit 1  x3
editar cognia/estado/canal.py              -> ok      x5
python -m pytest -q                        -> exit 2  x1
L904 Re-leer el fichero antes de editar si pasaron mas de 2 ciclos desde el ultimo sha.

=== ULTIMO ERROR (ciclo 7, cola) ===
tests/test_canal_persist.py:41: AssertionError: assert 'R3' in render(estado)

=== LEDGER: 1042 eventos, 7 ciclos. ledger_grep <regex> | ledger_ver <i> ===

=== RECITA ANTES DE ACTUAR ===
Criterio activo: C1. Restricciones en riesgo por los pendientes abiertos: R1, R3.
```

**2 240 chars = ~560 tokens** (convencion: 4 chars/token en castellano tecnico; se mide con
`contexto_vivo.estimar_tokens`). Presupuesto duro: 12 000 chars / 3 000 tokens. Se usa el 19%.

### 5.3 Que pasa cuando no cabe

**No se trunca. Nunca.** `HARD_STOP` es una excepcion tipada (patron de
`harness/limites.LimiteExcedido`) y el CLI imprime:

```
[!] LEDGER: la banda inmutable ocupa 4 210 de 4 000 chars (43 restricciones).
    No voy a recortar restricciones: recall medido 1,000 verbatim frente a 0,526
    seleccionando. Parti la tarea o retira restricciones con:
      /ledger retractar 27 "ya no aplica"
```

Es la decision de diseno mas incomoda y la asumo entera: **prefiero un agente que se planta a uno
que olvida en silencio.**

### 5.4 Coste medido

| Operacion | Coste | Fuente |
|---|---|---|
| Fold incremental (1 evento) | < 1 ms | O(1) sobre `fold.json` |
| Fold completo desde e#0, 7 000 eventos (~1,8 MB) | **~0,15 s** | ~50k lineas/s de `json.loads` |
| Render de la proyeccion | < 5 ms | concatenacion de strings |
| **Re-sembrar el contexto** (prefijo caliente + 560 tok nuevos) | **~0,24 s** | medido: cabecera 16k + cola distinta = 242 ms |
| Compactacion con LLM (lo que NO hago) | **16,49 s** | `falsacion.md` H5 |

**El reset cuesta 0,24 s. La alternativa medida costaba 16,49 s. Factor 69x.**

---

## 6. Ciclo de vida de una tarea

```
/largo "objetivo" --criterio "cmd" --restriccion "..."
        |
   [ABRIR] evento objetivo + restricciones (usuario + extractor) + criterios
        |
   +--> [GATE DE ARRANQUE]  gate.py
   |       recall de restricciones en la proyeccion == 100% ?  no -> ABORTA
   |       trazadores sembrados (canal.sembrar_trazadores, k=4)
   |       contradicciones C1/C4 abiertas ? -> a REPARACION
   |        |
   |     [CICLO]  horizonte.ciclos_con_contrato con hist = [system, proyeccion]
   |       hasta 8 pasos; cada run_tool -> interceptor -> eventos medidos
   |        |
   |     [CIERRE DE CICLO]
   |       comprobar_trazadores sobre la 1a respuesta -> leyo la proyeccion?
   |       detector de contradicciones (7 reglas)
   |       critico mecanico: RE-EJECUTA los criterios
   |       presupuesto_progreso.Progreso: coste por avance verificado
   |       evento `ciclo` con contadores
   |        |
   |       fin ? -> [CIERRE]     corrupto ? -> [REPARACION]
   +-------- si no: DESTRUIR contexto, volver al gate
```

**Cuando se resetea (pregunta 9).** Seis disparadores, el primero que salte:

| # | Condicion | Numero | De donde sale |
|---|---|---|---|
| R1 | `pasos_ciclo >= 8` | 8 | H(0,5) ~ 8 turnos en Gemma3-27B (arXiv:2509.09677). Env `COGNIA_LEDGER_PASOS`. |
| R2 | `prompt_tokens >= 0,55 * n_ctx_slot` | 18 022 de 32 768 | `contexto_vivo.registrar_uso`, hoy huerfano. Red de seguridad, no el disparador normal. |
| R3 | Misma firma `(tool, destino, exit)` dos veces seguidas | 2 | Anti-loop. |
| R4 | **Un criterio paso de FAIL a PASS** | 1 | El mejor momento para tirar la traza: hay progreso sellado que capitalizar. |
| R5 | Contradiccion abierta de tipo C1 o C4 | 1 | Seguir escribiendo sobre disco desincronizado destruye trabajo. |
| R6 | Recall de restricciones < 100% en el gate | — | Aborta, no resetea. |

Honestidad: R1 es el disparador dominante y es el unico numero del diseno importado de un paper en
vez de medido en esta maquina. El experimento E5 lo mide aqui, barriendo 4/8/16/32.

**Cuando termina (fin de tarea).** Tres salidas, todas mecanicas:

- **EXITO**: los N criterios en PASS **re-ejecutados en limpio por el critico** en un proceso nuevo,
  con `cwd` = workspace (bug del inventario: `GoalContract` resuelve rutas contra el CWD del
  proceso), y 0 contradicciones abiertas, y 0 pendientes abiertos.
- **ABANDONO**: 5 ciclos consecutivos sin cambio en el vector de veredictos de criterios **y** sin
  ningun evento `fichero` con sha nuevo. Escribe un informe y para. Es el criterio de PARADA que
  `falsacion.md` senalo como ausente.
- **MUDO**: 2 ciclos con 0 eventos medidos (seccion 4).

---

## 7. Recuperacion: como vuelve lo que no esta en la proyeccion

La proyeccion es un **indice**, no un archivo. Lo que no cabe se recupera bajo demanda con dos tools
que reusan la maquinaria del RLM (`agent/rlm.py`: `ContextoVivo` + `_ctx_grep` ya sostiene corpus de
300M tokens a coste constante ~7k tokens / 24 s):

| Tool | Uso | Coste |
|---|---|---|
| `ledger_grep <regex> [--tipo t] [--ciclo n]` | "que decidi sobre pickle?" | 10-40 lineas, < 300 tokens |
| `ledger_ver <i> [--contexto k]` | el evento, sus vecinos y su cadena de `refs` | < 200 tokens |

Y aqui entra la pieza mas infravalorada del estado del arte para este caso: **sleep-time compute**
(arXiv:2504.13171, ~5x menos computo test-time a igual precision). Con **1 slot ocioso mientras
corren las herramientas** y un objetivo estable durante horas, la condicion se cumple exacta.
Durante el tiempo de pared de un `pytest`, el harness hace dos cosas sin LLM y una con:

1. Recalcula el fold y la proyeccion del ciclo siguiente (0,15 s).
2. **Pre-calienta el cache**: manda la banda A + system como peticion de 1 token. El swap caliente
   se midio en **59 ms frente a 2 840 (48x)**. El proximo reset arranca con el prefijo residente.
3. (Condicionado a E3) Pide al critico las 3 preguntas comparativas del ciclo.

Cuidado medido: el cache aguanta `min(4 estados, ~1 GiB)` y **el acierto cae a cero de golpe**
(4x2k -> 4/4; 5x2k -> 0/5). Por eso la proyeccion se acota a 3 000 tokens: para que quepan 4
contextos calientes (ejecutor, critico, subagente, precalentado).

---

## 8. Agente critico

`falsacion.md` H3 es demoledor: exactitud balanceada **0,517 / 0,523** = azar. "Critico y riguroso"
detecta 43/43 erroneas **pero rechaza 58/60 correctas**; framing neutro aprueba 41/43 errores
reales. El adjetivo del prompt mueve la deteccion **21x**. Conclusion de diseno:

> **El critico principal de este sistema no es un LLM. Es codigo.**

### 8.1 Critico mecanico — 7 chequeos, 0 tokens

| # | Chequeo | Accion si falla |
|---|---|---|
| K1 | Re-ejecuta el `cmd` de **cada** criterio en proceso nuevo, cwd=workspace | emite `verificacion` real; nunca se fia de la registrada |
| K2 | Re-calcula el sha de cada fichero con `existe:true` | `contradiccion` C1 |
| K3 | Ninguna `afirmacion` con mas de 2 ciclos sin `verificacion` que la refiera | `retractacion` automatica |
| K4 | **Recall de restricciones en la proyeccion == 100%** (`canal._presente`, substring normalizado) | ABORTA el ciclo |
| K5 | `comprobar_trazadores` sobre la primera respuesta del ciclo | 0/4: el modelo no leyo la proyeccion -> `contradiccion` C7 |
| K6 | `presupuesto_progreso.Progreso`: tokens por avance verificado | corte si supera 3x la mediana historica |
| K7 | Anti-loop: firma repetida | reset R3 |

K1 es la unica variante de critico que `falsacion.md` vio **subir** (0,681, a 38x de coste): la que
**ejecuta**. Aqui ese 38x no se paga en tokens porque no hay LLM: se paga en segundos de `pytest`.

### 8.2 Critico LLM — existe solo si E3 lo aprueba

Si existe: `harness/oraculo.py` (transporte inyectado -> otra familia si el dueno tiene una; si no,
slot 1 del mismo servidor), **modo estrictamente comparativo**: nunca "es esto correcto?" sino
"dadas A y B, cual cumple mejor el criterio C1?" — la unica forma que sobrevivio a la revision
(CriticBench; *Small LMs Need Strong Verifiers*: <=13B solo ganan con verificador GPT-4). Su salida
es un evento `critica` con `origen: modelo`, `conf 0,30`. **No puede cerrar una tarea ni retractar
nada por si solo.** Puede abrir una `contradiccion` para que la resuelva K1.

---

## 9. Anti-alucinacion, contradicciones, snapshots, rollback

### 9.1 Anti-alucinacion

No es un detector, es una **imposibilidad estructural**: el modelo no tiene ninguna tool que escriba
un hecho. Lo que dice va a `afirmacion` con 0,30, no entra en la proyeccion, caduca por K3 a los 2
ciclos si nada la verifica, y no puede ascender por repetirse. Tres capas:

1. **Estructural** (I1): sin tool, sin hecho.
2. **Derivada** (I2): confianza = f(procedencia), nunca del LLM.
3. **Ejecutada** (K1): lo que decide es un exit code.

Para texto citado de fuentes: `search/evidencia.verificar_cita` — comprobacion **literal**, sin
juez. Si el substring no esta, no hay evento `citado`.

### 9.2 Deteccion de contradicciones (7 reglas, todas mecanicas)

| Regla | Detecta | Reaccion |
|---|---|---|
| **C1** | sha registrado != sha en disco | reset R5 + linea "RE-LEE antes de escribir" en la proyeccion |
| **C2** | dos `verificacion` del mismo criterio con `ok` distinto sin `fichero` entre medias | 1a-2a: marca `flaky`; 3a: `contradiccion` (un test flaky es un bug de instrumento, no del agente) |
| **C3** | dos `decision` con >=0,6 de solapamiento de tokens normalizados y marcador de negacion (`no `, `nunca`, `en vez de`) | `contradiccion` para revision |
| **C4** | una `restriccion` con `ambito` de ruta y un `fichero` sobre esa ruta | **VIOLACION: corte inmediato** + aviso |
| **C5** | `resuelto` sin `verificacion` posterior que lo respalde | re-abre el pendiente |
| **C6** | ciclo con 0 eventos medidos | seccion 4 |
| **C7** | 0/4 trazadores comprobados | el modelo no leyo la proyeccion |

Las contradicciones abiertas van en la proyeccion **sin tope** y **bloquean el cierre de la tarea**.
Cada contradiccion cerrada dispara `inmune/anticuerpos.py` para sintetizar un chequeo que corre al
arrancar — porque una leccion en prosa no impide nada.

### 9.3 Snapshots (pregunta 10)

**El ledger es el snapshot, y es continuo.** No hay un "momento de snapshot" que pueda perder algo:
cada evento es un punto restaurable. Un snapshot es solo un **offset** `i` mas el `fold.json` que lo
acompana, escrito cada 1 000 eventos y en cada cierre de ciclo, y que **contiene solo el fold, nunca
texto generado**.

Cuanta informacion guarda: **el snapshot no guarda informacion, guarda una direccion**. Todo esta en
el ledger. La proyeccion — lo unico que el modelo ve — son **560 tokens tipicos, 3 000 de tope
duro**. Esa es la unica cifra que importa, porque es lo unico que cuesta segundos.

### 9.4 Rollback (pregunta 17)

```
/ledger rollback --ciclo 6 "la refactorizacion del ciclo 7 rompio C2"
```

- **No borra nada.** Emite una `retractacion` en bloque que invalida `[i0..i1]`.
- El fold ignora los invalidados. La proyeccion vuelve a ser **byte a byte** la del cierre del ciclo
  6 (verificable contra `proyeccion.txt` archivada).
- Los **ficheros** se restauran aparte con `harness/checkpoints.py`, usando los sha del ledger para
  verificar que la restauracion fue correcta.
- Si el rollback deja pendientes resueltos por eventos invalidados, se **re-abren** automaticamente.
- **La retractacion es visible**: los ciclos siguientes leen `LEDGER: 12 eventos retractados en c7`.
  Nunca un rollback silencioso.

### 9.5 Estado corrupto (pregunta 16)

| Corrupcion | Deteccion | Recuperacion |
|---|---|---|
| Linea JSONL truncada (corte de luz) | el parseo falla al cargar | trunca a la ultima linea valida, emite `contradiccion`, sigue |
| Cadena `prev` rota | el sha no casa | dos escritores concurrentes: aborta y avisa; el lock deberia impedirlo |
| `fold.json` desincronizado | **re-fold completo y comparacion de sha en cada reset** (I3) | descarta el fold y recomputa. Caso barato: 0,15 s |
| Disco desincronizado | K2 / C1 | reset R5, re-lectura forzada |
| Ledger envenenado | `autopsia/causal.py` (precision@1 = 1,000 por replay contrafactual) sobre el ledger, que es exactamente la traza que ese modulo necesita | rollback al ciclo culpable + anticuerpo |

---

## 10. Protocolo entre agentes (pregunta 13)

Regla unica: **un solo escritor a la vez, y los subagentes escriben en el ledger del padre.**

```
delegar_subtarea("escribir tests para canal.persistencia", ambito="tests/")
  |
  +- proyeccion_scoped = proyectar(eventos, ambito="tests/")
  |     banda A ENTERA (las restricciones NUNCA se filtran por ambito)
  |     banda B filtrada a ficheros bajo tests/ + pendientes de ese ambito
  |     -> ~700 tokens
  +- el subagente corre en su propio ciclo, con su propio contexto
  +- sus eventos entran al ledger padre con quien="sub:tests"
  +- al terminar: su contexto se DESTRUYE. No devuelve resumen.
```

Esto arregla el defecto que senala el inventario en `delegar_subtarea` (solo vuelven 600 chars
lossy): **lo que vuelve son los eventos medidos, integros, en el ledger**. Ese resumen de 600 chars
era exactamente el resumen-de-resumen que este diseno existe para eliminar.

**Secuencial, no paralelo.** El +90,2% del multiagente de Anthropic se compra con 15x tokens y el
uso de tokens explica el 80% de la varianza; con 1 slot eso se paga en tiempo de pared. Y
`falsacion.md` H2 midio que cambiar de agente invalida el cache de prefijo: **10,68 s frente a
0,28 s**. Con `--parallel 2`: slot 0 = ejecutor (cache caliente permanente), slot 1 =
critico/oraculo — cada slot tiene su cache y no se desalojan mutuamente.

---

## 11. Estrategia de VRAM (pregunta 14)

La lobotomia no ahorra VRAM: **0 MiB**. La VRAM se decide una vez, al arrancar el servidor.

Aritmetica del hibrido (`qwen35`: el 9B tiene **8 capas de atencion** de 33 bloques; contar 33 se
equivoca por 4x):

```
llama-server -m Huihui-Qwythos-9B-...-Q4_K.gguf --ctx-size 65536 --parallel 2 --cache-ram 1024
```

| Partida | MiB | De donde |
|---|---|---|
| Pesos | 5 357,9 | medido |
| KV: 65 536 tok x 32 KiB/tok (f16) | 2 048 | formula validada 6/6 |
| Estado SSM: 50,25 x 2 slots | 100,5 | medido |
| Overhead (compute buffers, etc.) | ~1 490 | cuadre real |
| **Total** | **~8 996** | de 16 311 |

Frente a los 13 155 MiB de hoy con `--ctx-size 200192`: **libera 4,2 GB**, y da 32 768 tokens por
slot, que es 58x el tamano de mi proyeccion. Sobra sitio para un modelo chico de otra familia como
critico.

**Compuerta obligatoria** (Windows desborda a RAM compartida **sin ningun error**: en ctx=16384
pidio 1 792 MiB y la VRAM solo subio 2 582, con CUDA reportando "14987 MiB free"):

```
/ledger vram --verificar
  esperado (formula): 8 996 MiB    medido (nvidia-smi): 8 981 MiB    delta 0,17%  OK
```

Si el delta supera el 3%, el CLI se niega a arrancar el modo largo.

---

## 12. Como se teclea

```
> /largo "conectar canal.py al bucle y darle persistencia" \
      --criterio "venv312\Scripts\python.exe -m pytest tests/test_canal_persist.py -q" \
      --criterio "venv312\Scripts\python.exe -m pytest -q" \
      --restriccion "no tocar loop.py fuera de bucle_nativo" \
      --pasos 8

  LEDGER  tarea t20260819-1442  ctx 32768/slot  proyeccion 561 tok (19% de 3000)
  gate    restricciones 7/7 presentes  trazadores 4 sembrados          OK
  c1  ...........  8 pasos  14 eventos  C1 FAIL C2 PASS C3 NUNCA   41 s
      reset R1 (8 pasos)  ->  reproyeccion OK (sha identico)  0,19 s
  c2  ...........  8 pasos  11 eventos  C1 FAIL C2 PASS C3 NUNCA   38 s
      X903 contradiccion C1: canal.py editado fuera del agente
      reset R5  ->  0,21 s
  c3  ...........  6 pasos   9 eventos  C1 PASS C2 PASS C3 NUNCA   33 s
      reset R4 (progreso sellado)
  c4  ...........  7 pasos  12 eventos  C1 PASS C2 PASS C3 PASS    2 m 51 s
  CIERRE  3/3 criterios re-ejecutados en limpio  0 contradicciones  0 pendientes
          4 ciclos  46 eventos  8 m 12 s  17 402 tokens
```

| Comando | Que hace / que ve el usuario |
|---|---|
| `/ledger` | Panel: eventos, ciclos, tokens de la proyeccion, contradicciones abiertas, avisos |
| `/ledger proyectar` | Imprime **exactamente** lo que vera el proximo ciclo, con su conteo de tokens |
| `/ledger reproyectar` | Re-fold desde e#0 y compara sha con el incremental. `IDENTICO` o `DERIVA` |
| `/ledger ver 812 --contexto 3` | El evento y sus vecinos |
| `/ledger grep "pickle"` | Busca en el ledger |
| `/ledger auditar 815` | Cadena de provenance de e#815 hasta eventos medidos, con confianzas |
| `/ledger restringir "..."` | Anade restriccion (usuario, conf 1,0) |
| `/ledger retractar 816 "motivo"` | Invalida sin borrar |
| `/ledger rollback --ciclo 6 "motivo"` | Rollback en bloque + restauracion de ficheros por sha |
| `/ledger contradicciones` | Solo las abiertas |
| `/ledger vram --verificar` | Formula frente a `nvidia-smi` |

`COGNIA_LEDGER=1` para activarlo. Apagado por defecto: el repo exige opt-in por evidencia medida.

---

## 13. Las 18 preguntas

| # | Pregunta | Mecanismo concreto |
|---|---|---|
| 1 | Que es solido | Destruir el contexto (por *self-conditioning*, no por VRAM); el canal de estado explicito (recall 0,07 -> 1,00); el aislamiento de subagentes; la memoria jerarquica **por persistencia** |
| 2 | Que fallara | Todo lo que comprima con LLM; todo lo que **seleccione** restricciones (0,526 frente a 1,000); el critico del mismo modelo en modo absoluto (0,52 = azar); justificar cualquier cosa por VRAM (0 MiB) |
| 3 | Tras cientos/miles de ciclos | El ledger crece ~3,5 KB/ciclo (500 ciclos = 1,8 MB; 5 000 = 18 MB). **La proyeccion NO crece**: bandas con topes duros, ~560 tok siempre. Lo que si crece es la banda A si el usuario anade restricciones: ahi esta el modo de fallo #1 |
| 4 | Evitar degradacion de memoria | No hay resumen que degradar. La degradacion posible es un bug del fold, y se detecta: **re-fold completo + comparacion de sha en cada reset** (I3) |
| 5 | Alucinaciones persistentes | No pueden persistir: `afirmacion` no entra en la proyeccion, caduca en 2 ciclos (K3) y no asciende por repeticion. Lo que persiste esta medido |
| 6 | Que el critico no valide errores | El critico principal es codigo (K1-K7) y **re-ejecuta**. El LLM solo compara A/B, con conf 0,30, y no puede cerrar nada |
| 7 | Loops infinitos | La banda C (contador de firmas) lo hace visible al modelo; R3 corta a las 2 firmas repetidas; C6 corta el ciclo mudo; ABANDONO corta a 5 ciclos sin cambio de veredictos |
| 8 | Perdida del objetivo | K4: recall de restricciones == 100% o el ciclo **aborta**. K5: trazadores comprueban que el modelo *leyo*. Banda E recita el criterio activo |
| 9 | Cuando resetear | R1..R6 (seccion 6). R1 = 8 pasos domina |
| 10 | Cuanto guarda un snapshot | Un snapshot es un **offset**, no una copia. La proyeccion son 560 tok tipicos / 3 000 de tope |
| 11 | Estructura de la memoria | 5 bandas por persistencia (A inmutable / B derivada / C senal negativa / D indice / E recitado) sobre un ledger append-only de 15 tipos de evento |
| 12 | Provenance y confianza | `origen` en 5 clases; `conf = f(origen)`; `refs` forman un DAG auditable con `/ledger auditar`; el LLM nunca emite confianza |
| 13 | Coordinar agentes | Subagentes secuenciales, proyeccion scoped por `ambito` (las restricciones **nunca** se filtran), escriben en el ledger del padre, contexto destruido al terminar, **sin resumen de vuelta** |
| 14 | Minimizar VRAM | `--ctx-size 65536 --parallel 2` = ~9,0 GB (libera 4,2 GB). No con lobotomia: **ahorra 0 MiB** |
| 15 | Minimizar tokens de compresion/recuperacion | Compresion = **0 tokens** (es codigo). Recuperacion = `ledger_grep` bajo demanda, <300 tok. Re-sembrado = 560 tok / **0,24 s** con prefijo caliente |
| 16 | Estado corrupto | Tabla 9.5: 5 corrupciones con deteccion y recuperacion. El caso comun (fold desincronizado) cuesta 0,15 s |
| 17 | Rollback | `retractacion` en bloque (no borra) + restauracion de ficheros por sha con `harness/checkpoints.py` + re-apertura de pendientes + aviso visible |
| 18 | Evaluacion experimental | Seccion 15: E0 (brazo nulo) a E5, con MDE y condiciones de KILL pre-registradas |

---

## 14. Comparacion honesta

| Familia | Que le tomo | Que le rechazo |
|---|---|---|
| **Context compression** | nada de la variante con LLM | Todo: 16,49 s por compactacion, y recall 0,083 en cascada |
| **Summarization memory** | nada | El resumen de resumen es el problema que este diseno elimina por construccion |
| **Recurrent memory (RMT/Titans)** | El **teorema**: un estado pequeno de tamano fijo sostiene millones de tokens. Mi banda B es ese estado, en texto inspeccionable | Los checkpoints: RMT llega a 11,1M tokens con **GPT-2 fine-tuneado en BABILong**. Via cerrada |
| **External memory** | El ledger en disco: el proceso muere y la memoria no | La API tipo "el agente decide que guardar" |
| **RAG** | `ledger_grep`/`ledger_ver` como recuperacion bajo demanda | Embeddings: la busqueda sobre un ledger estructurado es exacta (tipo, ciclo, ruta, regex). Nada que aproximar |
| **Episodic memory** | Los eventos SON episodios, con `ts` y `ciclo` | El recall por similitud |
| **Hierarchical memory** | La jerarquia **por persistencia**, que es lo que pidio el dueno y es correcto | La jerarquia por resumen (corta -> media -> larga por compresion sucesiva) |
| **Agentic workflows** | Subagentes secuenciales como aislamiento; un solo escritor (donde Anthropic y Cognition coinciden) | Paralelismo: 15x tokens, 1 slot, y el cache invalidado (10,68 s frente a 0,28 s) |
| **Reflection** | `leccion` en forma imperativa positiva, con refs medidas | La reflexion libre: Huang et al. (ICLR 2024) mas el 0,52 medido aqui |
| **Verifier models** | **El que ejecuta.** Unica variante que subio (0,681) | El puntuador absoluto del mismo modelo: azar, y el adjetivo del prompt mueve la deteccion 21x |
| **State-space** | El sustrato ya es hibrido (24 capas SSM en el 9B) y por eso el KV es barato: 32 KiB/tok | Nada que anadir: es hardware, no diseno |

**Que ya existe con nombre propio:** event sourcing + CQRS (proyecciones sobre log append-only,
2005); validez temporal bitemporal (Zep/Graphiti); memoria externa; sub-agentes aislados; verificador
que ejecuta. **Nada de eso es mio.**

**Que es novedoso de verdad — tres cosas, y son pequenas:**

1. **La memoria la escribe el harness, no el agente.** La provenance deja de ser una etiqueta que el
   modelo declara y pasa a ser una propiedad **estructural** de como nacio el evento. En todos los
   sistemas de memoria de agentes revisados, es el modelo quien decide que guardar.
2. **La proyeccion se verifica recomputandola entera y comparando sha.** Convierte "degradacion de
   memoria" — invisible por definicion, y la razon de que la cascada de H4 pasara desapercibida — en
   un fallo ruidoso de 0,15 s.
3. **La senal negativa se comprime a un contador `firma -> n`, no a texto.** Preserva la senal
   anti-loop (que `falsacion.md` identifico como *la unica senal no correlacionada que existe*) y
   elimina la traza de errores que produce self-conditioning. Las dos cosas a la vez, en 350 chars.

**La combinacion mas potente** (es una suma, no una sola idea): ledger determinista **+** re-emision
verbatim del contrato (400 tok, 0,17 s, recall 1,000) **+** critico que ejecuta **+** `ledger_grep`
estilo RLM para lo que no cabe **+** sleep-time compute para pre-calentar el cache durante el tiempo
de pared de las herramientas.

---

## 15. Como se evalua (pregunta 18), con condiciones de KILL pre-registradas

| Exp | Pregunta | Diseno | Criterio |
|---|---|---|---|
| **E0** | **Brazo nulo.** El ledger aporta algo sobre "re-emitir objetivo+restricciones verbatim y nada mas"? | Proyeccion con bandas B y C **vacias**, mismas 12 tareas | Si B ~ E0, **toda la maquinaria sobra**. Es el brazo que mas me puede matar y va primero |
| **E1** | Recall de restricciones == 1,000? | 100 proyecciones sinteticas con 24 restricciones, `canal._presente` | Determinista: cualquier valor <1,000 es un bug. Sin estadistica |
| **E2** | Deriva del fold | Replay de 500 ciclos, sha(re-fold) frente a sha(incremental) | 500/500 identicos, o el diseno tiene un agujero |
| **E3** | Existe el critico LLM? | 60 correctas / 43 erroneas ya construidas en `exp/`; 3 brazos: absoluto, comparativo, azar | n=103, MDE ~ +-0,10. Absoluto ya medido en 0,52. **Si comparativo <= 0,58 -> KILL del critico LLM**; se queda el mecanico |
| **E4** | **El diseno entero gana?** | A/B pareado, 12 tareas x 2 brazos **intercalados**. A = ventana ancha 200k sin ledger (el ganador de `falsacion`). B = ledger + reset a 8 pasos. Primaria: criterios PASS re-ejecutados en limpio. Secundaria: minutos de pared | Varianza entre corridas +-34 pts -> **solo netos apareados intra-corrida**. Prediccion honesta: **B pierde en tareas de menos de 30 min**. Si B no gana en las de mas de 4 h, **el diseno muere** |
| **E5** | Cuanto dura un ciclo aqui? | Barrido de `--pasos` 4/8/16/32, n>=6 por brazo, intercalados | El 8 viene de un paper sobre Gemma3-27B, no de esta maquina. Es el numero mas prestado del diseno |

Nota metodologica vinculante: el gate e2e de este repo es flaky ~50% y los fallos concentrados
indican regresion. n>=6 por brazo, brazos intercalados, y `finish_reason`/`usage` mirados antes de
atribuir nada al modelo.

---

## 16. Numeros, juntos

| Magnitud | Valor | Origen |
|---|---|---|
| Proyeccion tipica | **2 240 chars = ~560 tokens** | ejemplo 5.2, contado |
| Tope duro de la proyeccion | 12 000 chars / 3 000 tokens | diseno (permite 4 contextos calientes: `min(4 estados, ~1 GiB)`) |
| Coste de comprimir | **~0,15 s, 0 tokens de LLM** | fold sobre 7 000 eventos |
| Coste de re-sembrar tras reset | **~0,24 s** | medido: cabecera caliente + cola distinta, 242 ms frente a 5 830 |
| Alternativa que NO uso | 16,49 s | `falsacion.md` H5 |
| Pasos por ciclo | 8 | H(0,5) ~ 8 en Gemma3-27B |
| Duracion tipica de un ciclo | **~40 s de modelo** (8 pasos x ~200 tok de decode a 55-65 tok/s + prefill incremental) mas el tiempo de herramienta | medido: decode 55-65 tok/s; append +500 -> 514 proc |
| Resets por hora | ~50-80 | derivado |
| Coste de resets en 8 h | ~450 x 0,24 s = **1,8 minutos** | derivado |
| Crecimiento del ledger | 3,5 KB/ciclo; 500 ciclos = 1,8 MB | ~14 eventos x ~250 B |
| VRAM | ~8 996 MiB de 16 311 | formula validada 6/6 |
| Ahorro de VRAM por lobotomia | **0 MiB** | 626 muestras, amplitud 21 MiB |

---

## 17. COMO ME ROMPO — los 3 modos de fallo tras 500 ciclos

### 1. La banda A revienta el presupuesto y no hay a quien culpar

Las restricciones son append-only y **no caducan nunca**, por diseno, para evitar *governance decay*.
Tras 500 ciclos con un usuario que teclea `/ledger restringir` de vez en cuando y un extractor que
deriva restricciones de `CLAUDE.md`, 7 restricciones se vuelven 45. A ~85 chars cada una son 3 800
chars = 950 tokens solo de banda A, y a 60 restricciones se dispara el `HARD_STOP`: **el agente se
para y exige intervencion humana.** No es corrupcion, es acumulacion legitima.

Y la salida obvia — filtrar restricciones por `ambito` segun los ficheros del ciclo — **reintroduce
exactamente la seleccion que `falsacion.md` midio en recall 0,526 frente a 1,000 verbatim**. La
solucion conocida es peor que el problema. No se resolverlo. Lo dejo declarado, con una alarma a
partir de 40 restricciones y con la metrica que decide (E1 re-corrido con la banda A inflada). Es la
deuda mas grande de este diseno.

### 2. El agente deja de usar herramientas y el ledger enmudece: punto fijo determinista

La emision automatica depende de pasar por `run_tool`. Un ciclo de razonamiento puro emite 1 evento
(`ciclo`), la proyeccion siguiente sale **identica**, y contexto identico con temperatura baja
produce respuesta identica: **loop infinito perfectamente estable**, sin errores, sin crecimiento
del ledger, sin nada que mirar. Es el vacio silencioso en su forma mas pura, y mi diseno lo hace
*mas* probable que uno con resumen (un resumen habria cambiado, aunque fuera para peor).

C6 lo corta a los 2 ciclos y hay un test que lo exige. Pero C6 es codigo que yo escribo, y su fallo
tiene la misma forma que el problema: si el contador de "eventos medidos" cuenta mal — por ejemplo
si un `comando` con exit 0 y salida vacia cuenta como medido — el detector no dispara nunca y el
sistema gira durante horas. **Un unico bug de conteo en `gate.py` desactiva la unica defensa.** Y
como el fold es determinista, ese bug produce el *mismo* resultado equivocado 500 veces seguidas,
que es indistinguible de funcionar bien.

### 3. Las decisiones del modelo envenenan la banda B por la puerta de atras

`decision` es la unica banda que el modelo escribe libremente y que **se muestra** (si no se
mostrara, no serviria de nada). Tienen conf 0,30, exigen `refs` a eventos medidos, y la proyeccion
solo saca las 8 ultimas no retractadas. Suena a defensa. No lo es del todo.

Una decision **erronea** tomada en el ciclo 200 desaparece sola a los 8 ciclos — bien. Pero una
decision erronea tomada **hace 3 ciclos** se re-lee tres veces seguidas, y en cada relectura llega
sin la traza que la produjo, presentada como estado consolidado con una referencia a un evento
medido real. El `refs` obligatorio garantiza que *existio* una medicion, no que la conclusion se
siga de ella. Eso es **self-conditioning por la puerta de atras**: he excluido la traza de errores y
he dejado pasar la conclusion erronea, que es la parte que mas dano hace y la unica que el modelo va
a tratar como premisa. Tras 500 ciclos habra ~150 decisiones y el envenenamiento no sera una: sera
una cadena D_n -> D_(n-1) -> ... con evidencia medida en la raiz y una inferencia rota en el medio.

La mitigacion honesta seria que el critico ejecutor **re-derive** cada decision vigente antes de
proyectarla — y eso es justamente el trabajo que ningun mecanismo mecanico sabe hacer, porque
requiere entender el argumento. Es el punto exacto donde mi tesis ("el LLM no comprime") se queda
sin respuesta: **puedo garantizar la procedencia de los hechos y no puedo garantizar la validez de
los razonamientos que los conectan.**

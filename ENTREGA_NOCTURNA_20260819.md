# Entrega nocturna 2026-08-19 — Hermes, flujos aprendidos, monitores y tres sistemas nuevos

Corrida autónoma del 18/08 23:00 al 19/08 ~06:00. Todo lo que sigue está **medido**, y
lo que no funcionó también está aquí con su número.

---

## 0. El método de la noche

Cuatro fases pedidas (Hermes → flujos grabados → monitores → inventar) y una regla
propia: **ninguna afirmación sin ejecución**. 21 agentes de investigación e
implementación, 6 workflows, y en cada fase un e2e contra el modelo real
(Qwythos-9B en `:8080`) con postcondiciones de disco.

Baseline medido ANTES de tocar nada: `e2e_happy_path.py` **5/5 en 1,6 min**.
Baseline al cerrar: **5/5 en 1,8 min**. Suite: 9420 → 9700+ tests.

---

## 1. Hermes Agent → `cognia/hermes/`

Se leyó el fuente real de Hermes Agent 0.19.1 (instalado en esta máquina, ~125k
líneas en `agent/`) con cuatro agentes en paralelo: bucle, aprendizaje, tools y
automatización. De ahí salieron los cinco mecanismos que Cognia **no tenía**, y se
cablearon en `bucle_nativo` (el bucle vivo; el `while` legacy de `cli.py` solo corre
con el perfil 3B):

| Módulo | Qué resuelve |
|---|---|
| `presupuesto_turno.py` | Presupuesto con **refund por motivo**: la vuelta administrativa (reintento por corte, compactación) ya no se come el presupuesto de la tarea. Y `RazonSalida`: todo `break` sella su razón y se loguea siempre, con alarma si el turno acaba en un resultado de tool sin cerrar. |
| `guardia_bucle.py` | Ping-pong A-B-A-B y ciclos A-B-C-A-B-C, que `register_action` (solo A-A-A) no veía. |
| `mutaciones.py` | Footer con las escrituras que **fallaron**: el modelo ya no puede afirmar que escribió lo que no escribió. |
| `parada_verificada.py` | El turno que editó código no cierra sin evidencia fresca de haberlo corrido. Continuación acotada (máx 2 nudges) con **rescate** de la respuesta ya compuesta. |
| `errores_backend.py` | 11 razones tipadas: un 503 transitorio se reintenta, un contexto excedido se **comprime antes** de reintentar, un modelo ausente no se reintenta nunca. |
| `rutinas.py` | Rutinas programadas (cron propio), ledger de tres estados terminales, script injection, contrato `[SILENT]`, puerta `wakeAgent`. Comando `/rutinas`. |

**Medición** (`scripts/ab_parada_verificada.py`, brazos intercalados, n=4):
control 3/4 y 24 s · arnés 3/4 y 20 s → **neto +0 de acierto, −4 s de pared**.
Los 41 s que asustaron en la primera corrida eran varianza, no regresión.
Lo honesto: con n=4 solo se puede afirmar que **no degrada**; el valor está en los
modos de fallo que ahora son visibles.

---

## 2. "Grabar un flujo y que el agente lo aprenda" → `cognia/flujos/`

**Hallazgo que cambia la premisa:** Cursor **no tiene** ese mecanismo. No graba
acciones, ni clics, ni terminal: genera markdown a partir del *chat*
(`/Generate Cursor Rules` fue incluso **retirado** en Cursor 2.0). El producto que sí
graba pantalla y pulsaciones es *Record a Skill* de Claude Cowork. Cursor publica el
sustrato (hooks con `afterShellExecution` / `afterFileEdit`) y **no lo conecta** con
la generación de skills. Ese hueco es lo que se construyó:

```
/grabar inicio → (el agente trabaja) → /grabar fin
/receta aprender <grabación>   →  flujo parametrizado con postcondiciones
/receta examinar <nombre>      →  EL EXAMEN: casos con parámetros NUEVOS
/receta correr <nombre> k=v    →  ejecución determinista
```

La pieza diferencial es `examen.py`: un flujo **no se activa por haber salido bien una
vez** — tiene que aprobar casos con parámetros nuevos en workspaces temporales,
juzgados por postcondiciones ejecutadas. Cuarentena por **código** (este repo ya se
quemó con un `_cuarentena/` que funcionaba por accidente del glob) y decay por fallos
en producción.

**Medición e2e** (`scripts/e2e_flujos_monitores.py`, 14/14): se grabó una tarea real
(5 pasos), se aprendió un flujo de 3 pasos con 4 huecos, el examen dio *verificado
3/3 casos nuevos*, y correr el flujo dejó los ficheros en disco en **0,01 s contra
16 s del agente (1305×)**.

---

## 3. Monitores → `cognia/monitores/` (`/centinela`)

El motor viejo (`console/monitors.py`) dispara una vez, muere al cerrar el REPL y el
agente no puede crear ninguno. El nuevo: **persistente** (sobrevive al reinicio),
recurrente, con debounce, horas de silencio, contrato `[SILENT]` y **acciones**:
avisar · ejecutar · **despertar al agente** · correr un flujo. Sondas honestas de esta
máquina (sin `nvidia-smi` dice *no medible* y **no** dispara; `puerto_ocupado_por_otro`
para el patrón real de tailscaled robándole el `:8080` al summoner).

Las tareas de "despertar al agente" entran por la **misma cola** que teclearía el
usuario: nada se ejecuta a escondidas.

---

## 4. Los sistemas nuevos

La invención se ancló en una investigación previa de la evolución de los harness
(2022→2026) y de sus **huecos abiertos publicados**. No son ideas sueltas: cada uno
cierra un hueco que la literatura declara sin resolver.

### 4.1 MULTIVERSO — bifurcación con contabilidad de efectos (`/multiverso`)

> Hueco: la búsqueda en árbol sobre trayectorias (ToT, LATS, SWE-Search) no está en
> ningún harness de producción, y la razón publicada **no es el coste: es que el
> mundo no se puede rebobinar**. Y: *"las acciones no están clasificadas por
> reversibilidad sino por tipo de herramienta"*.

- `reversibilidad.py` — el **catastro de efectos**: puro / reversible (con
  compensación concreta, patrón saga) / irreversible / desconocido. `ejecutar` se
  clasifica por el **comando**, no por el nombre de la tool (pipelines, `xargs`/`sudo`,
  redirecciones, `python -c`). Ante duda: *desconocido*, nunca *puro*.
- `instantanea.py` — instantáneas baratas en NTFS (almacén por hash + enlaces duros).
- `ramas.py` — K trayectorias reales de la misma tarea, juzgadas por postcondiciones
  **ejecutadas**; se fusiona solo la ganadora. Dentro de una rama lo irreversible se
  **veta y se encola** para correr una sola vez, en el mundo real, si esa rama gana.
- `especulacion.py` — aceptación por **equivalencia de efecto** (el hueco declarado).

**El número que nadie había publicado**, medido sobre **86.496 llamadas reales** de
este repo:

| cubo | % |
|---|---|
| puro | 26,05 |
| reversible | 57,86 |
| **irreversible** | **7,31** |
| desconocido | 8,77 |

→ **el 84% del trabajo de un agente es ramificable sin riesgo**; solo el 7,3% hay que
encolar. Ese número es el que decide si el branch-and-explore es viable, y hasta hoy
era desconocido.

### 4.2 AUTOPSIA CAUSAL + SISTEMA INMUNE (`/autopsia`)

> Hueco: *"snapshot barato + replay contrafactual, unidos"*. DeltaBox (2605.22781)
> sabe rebobinar en milisegundos; Causal Agent Replay (2606.08275) sabe qué preguntar.
> **Son comunidades disjuntas que no se citan y nadie las había juntado.**

`autopsia/motor.py` es esa unión: rebobina con la instantánea y re-ejecuta prefijos
por bisección hasta **demostrar** el paso culpable (sin él la tarea pasa; con él falla).

| método | precision@1 | reproducciones/tray |
|---|---|---|
| **bisección + contrafactual** | **1.000** (20/20) | 6,55 |
| base (a): el último paso | 0.050 (1/20) | 0 |
| base (b): el último paso fallido | 0.100 (2/20) | 0 |

Y el **sistema inmune**: el fallo atribuido se convierte en un **chequeo ejecutable**
que veta la acción que reprodujo el fallo. La compuerta que impide envenenarse: nace
en cuarentena y solo se activa si veta todo lo malo **y nada** de una batería sana.
Coste medido en el camino caliente: **0,2 µs por llamada**.

Lo mejor del módulo es lo que **no** hace: un fallo *semántico* (un `escribir_archivo`
que pisa un fichero bueno) **no produce anticuerpo**. No se fabrica prosa —
exactamente cómo murieron las skills auto-capturadas de este repo.

### 4.3 CANAL DE ESTADO VERIFICADO + PRESUPUESTO POR PROGRESO (`cognia/estado/`)

> Huecos: *"el canal de estado no está separado del de prosa, así que la compactación
> destruye el registro verificable"* (2,19–2,45 sobre 5,0, idéntico en Factory,
> Anthropic y OpenAI sobre 36.611 mensajes) y *"el presupuesto está en tokens y pasos,
> nunca en progreso verificado por unidad de coste"*.

`canal.py`: registro estructurado con hechos **medidos del disco** (sha256, bytes,
exit code), que se reinyecta entero **cuando el contexto se recorta** y **nunca pasa
por el resumidor**.

| compactador | brazo | ficheros | restricciones | trazadores | global | /5,0 |
|---|---|---|---|---|---|---|
| cola(12) | SIN canal | 0,17 | **0,00** | 0,00 | 0,07 | 0,33 |
| cola(12) | CON canal | 1,00 | **1,00** | 1,00 | 1,00 | 5,0 |

El *governance decay* reproducido en 40 mensajes: **0 de 5 restricciones sobreviven**
a la compactación y el compactador no emite ningún error. El `1,00` del brazo CON es
tautológico por construcción — **el número informativo es el contrafactual 0,07**.

`presupuesto_progreso.py`: corta por **falta de avance verificado**, no por cantidad.
Un avance no se declara, se **observa** (rojo→verde, fichero nuevo que compila,
postcondición cumplida); repetir un test que ya estaba verde suma **cero**.
Medido sobre trazas **reales** del repo:

- `promptevo` (2,69 h, resultado final +0,000): se habría cortado ahorrando **87,9%**
  del tiempo.
- `tool_rota` (318 intentos, churn puro, cero verificaciones): **98,7%** de intentos
  ahorrados.
- **0 falsas alarmas** sobre las 69 tareas de reparación que sí avanzaban (umbral
  calibrado con barrido contrafactual: 2→12 falsas, 3→6, **4→0**).

---

## 5. Lo que NO funcionó (medido)

**Ejecución especulativa de acciones**: cableada al bucle y medida con brazos
intercalados (n=3): **1 especulación, 0 aceptadas (0%)**. Diagnóstico verificado en
vivo, no supuesto: el predictor por bigramas necesita un par (prev→sig) repetido
*dentro de la tarea*, y una tarea de 2-4 pasos no llega a tenerlo. Queda **apagada**
(`COGNIA_ESPECULAR=1`) y la vía declarada es un predictor con historial **entre**
tareas, que este repo ya tiene material para alimentar.

---

## 6. Bugs propios cazados por los e2e (y por qué importan)

1. **`/flujo` y `/vigilar` ya existían** y mis `elif` los dejaban muertos — la misma
   trampa de precedencia que el repo documenta con `/modelos` vs `/modelo`. Renombrados
   a `/receta` y `/centinela`. Lo cazó la suite completa, no la revisión.
2. **El sistema inmune leía `tool` y el trace del bucle usa `action`**: `sintetizar()`
   devolvía `None` con **toda** traza real. Pasaba sus tests y estaba **muerto en
   producción**. Test de regresión añadido.
3. **La alarma de "tool pendiente" saltaba en todos los turnos sanos** (el turno final
   no se apendea a `mensajes`). Una alarma que suena siempre no es una alarma.
4. **Un check del e2e leía `inf["disparos"]`, clave inexistente** (la real es
   `disparados`): el check 9 aprobaba sin medir nada y el 10 fallaba con el monitor
   funcionando. El patrón "el test que pasa por el motivo equivocado", otra vez.

---

## 7. Comandos nuevos

```
/hermes            estado del arnés (presupuesto, guardia, parada verificada, evidencia)
/rutinas           tareas programadas: listar | crear "<horario>" <tarea> | borrar | ahora
/grabar            inicio | fin | lista | ver <id> | borrar <id>
/receta            lista | aprender <grabación> | examinar | correr <nombre> k=v | cuarentena
/centinela         lista | fichero <ruta> | backend <url> | comando <cmd> | parar | tick
/multiverso <k>    corre la tarea en K ramas aisladas y fusiona solo la ganadora
/autopsia [<id>]   cuál de los N pasos causó el fallo, por replay contrafactual
```

Palancas: `COGNIA_HERMES=0`, `COGNIA_ESTADO=0`, `COGNIA_INMUNE=0`, `COGNIA_ESPECULAR=1`.

---

## 8. Límites declarados

- Los A/B con modelo real son de **n=3-4**: sirven para descartar regresiones, no para
  afirmar mejoras pequeñas. El MDE es grande y está dicho.
- La autopsia **no re-muestrea el modelo**: reproduce las acciones grabadas. Atribuye
  fallos de ejecución, no de razonamiento.
- Nada rebobina efectos **fuera** del workspace; por eso lo irreversible se veta en vez
  de deshacerse.
- El banco de precision@1 es de **inyección sintética**: mide la atribución, no la
  dificultad de un fallo real de producción.
- El canal de estado está medido contra un compactador **de juguete** (cola de N
  líneas, el fallback universal), no contra un resumidor LLM.
- El generalizador de recetas **sobre-parametriza** (detectó `exactamente` y `hola`
  como huecos además de las dos rutas).

# ATAQUES — informe del adversario

**Encargo:** destruir `diseno_ledger.md`, `diseno_grafo.md` y `diseno_proceso.md`.
Fecha: 2026-08-19. No resumo los diseños: los ataco.

**Reglas del ataque.** Sólo uso (a) los números ya medidos en `medicion_kv.md` y `falsacion.md`,
y (b) el **código real** de este repo, leído hoy. Cuando un ataque nace de una línea de código
la cito con fichero y número de línea, porque los tres diseños apoyan su pieza central —
"la provenance la escribe la máquina, no el modelo" — en un módulo que ninguno de los tres leyó.

Veredictos: **MUERE** / **A MEDIAS** / **SOBREVIVE**.

---

## 0. El ataque que se los lleva a los tres antes de empezar

### A0 — El reloj tampoco justifica la lobotomía

Los tres diseños empiezan igual: "la VRAM está refutada (0 MiB), pero **el reloj** sigue en pie:
rehidratar 3k = 1,4 s frente a arrastrar 64k = 27,3 s, ×9,6". Es la última justificación que les
queda, y **la mata una medición que los tres citan en otra sección**.

`medicion_kv.md` §4: *"Append puro sólo cuesta lo añadido: +500→514 proc, +1.500→1.506,
+3.000→3.018."*

Traza:

1. Ciclo N en modo ancho. El contexto vivo son 64.000 tokens. Ya están en la caché KV del slot.
2. El agente llama a una tool. La salida son 800 tokens. Se **apendan**.
3. El siguiente `POST /completion` manda 64.800 tokens. llama.cpp procesa **800**, no 64.800.
   Coste: 0,31 s. **No 27,3 s.**
4. Los 27,3 s se pagan **una vez**, cuando esa ventana se llenó por primera vez. Nunca más.

Es decir: el ×9,6 sólo existe si comparas el reset contra un mundo **sin caché de prefijo** —
un mundo que esta máquina no habita. En régimen estacionario, **modo ancho y modo lobotomía pagan
exactamente el mismo prefill incremental**. Lo único que el reset ahorra de verdad es el
crecimiento del coste de *decode* con el KV grande, y eso **nadie lo ha medido aquí**: el informe
da "decode honesto 55–65 tok/s" sin desglose por ocupación de contexto.

Consecuencia para los tres: tras caerse la VRAM (medida) y caerse el reloj (por la propia
medición de caché), **la única justificación viva de toda la arquitectura es la higiene de
self-conditioning**, que es un efecto de calidad medido en Qwen3-32B en un paper, **no en esta
máquina, ni en este modelo, ni en esta tarea**. Los tres diseños construyen entre 900 y 1.400
líneas de módulos nuevos sobre un solo número prestado.

- Ledger lo tiene medio visto: su **E0 (brazo nulo)** y su **E4** predicen honestamente que
  "B pierde en tareas de menos de 30 min". No ve que el argumento del reloj también se le cae.
- Grafo lo repite sin matiz: *"Arrastrar 64k en vez de resetear: prefill 27,30 s **por llamada**
  ⇒ ×9,6. Ahí está el ahorro real."* — **"por llamada" es falso** y contradice su propia §11.
- Proceso lo repite en §5.3: *"cada paso a 64k cuesta 27,3 s de prefill contra 1,43 s"*. Mismo
  error, y encima §5.2 cita la medición correcta ("append puro sólo cuesta lo añadido") tres
  párrafos antes.

**Veredicto A0: ledger A MEDIAS, grafo MUERE, proceso MUERE.** Los dos que escriben "por llamada"
se contradicen a sí mismos en el mismo documento. Ninguno queda sin justificación *válida* —
la higiene sigue en pie — pero los tres tienen que reordenar sus experimentos y poner esto de E0.

---

## 1. Los ataques al AXIOMA compartido: "la provenance la escribe la máquina"

Los tres diseños son, en el fondo, el mismo diseño: ledger append-only + proyección determinista
+ provenance escrita por `harness/interceptor.py` + verificador que ejecuta. Los tres dicen que
el modelo **no puede** mentir sobre lo que pasó porque el interceptor lo mide.

He leído el interceptor. **No mide.**

### A8 — `ok` no es un exit code: es una regex sobre 120 caracteres

`cognia/agent/tools.py:470`:

```python
ok = not re.search(r"\bERROR\b", out.split("\n", 1)[0][:120])
```

Eso es todo lo que `interceptor.despues(name, args, ctx, out, ok)` recibe como "verdad medida".
No hay `returncode`. No hay `exit`. Hay un booleano derivado de buscar la palabra `ERROR` en la
**cabeza de la primera línea**.

Y `cognia/agent/tools.py:1699-1701` construye esa primera línea así:

```python
code = "" if r.returncode == 0 else f" (exit {r.returncode})"
return f"RESULTADO ejecutar{code}: {_head_cola(out) or '(sin output)'}"
```

**Traza del fallo, ciclo 7:**

1. El agente lanza `venv312\Scripts\python.exe -m pytest tests/estado -q`.
2. Falla: 3 tests rojos, `returncode=1`.
3. El texto devuelto es `RESULTADO ejecutar (exit 1): ===== test session starts =====...`.
4. `\bERROR\b` **no aparece** en esos 120 chars → **`ok = True`**.
5. `interceptor.despues(..., ok=True)` recibe un fallo etiquetado como éxito.

Peor todavía, el caso del centinela. `cognia/agent/sentinel.py:196-214` devuelve, cuando bloquea
o pide confirmación:

```
RESULTADO ejecutar: BLOQUEADO por Sentinel (patrón destructivo irreversible). ...
RESULTADO ejecutar: requiere confirmación (comando 'sqlite3' de riesgo desconocido). ...
```

Ninguna de las dos contiene `ERROR` en los primeros 120 chars → **`ok = True` y no hay `(exit N)`
en el texto**. Un comando que **jamás se ejecutó** llega a la capa de memoria como éxito sin exit
code.

Qué le hace a cada diseño:

**LEDGER.** §3.4: `origen: medido` ⇒ `conf = 1,00`, y §4 V1 dice *"exit real"*. No existe el
exit real. Si el emisor lo parsea de `(exit N)` y asume 0 cuando falta, el evento queda
`{"t":"comando","origen":"medido","conf":1.0,"exit":0}` para un comando **bloqueado por el
centinela**. Y V3 deriva `verificacion` de un `comando` cuyo `cmd` casa con un `criterio`:
**el criterio C1 pasa a PASS porque el centinela lo frenó.** Después R4 dispara ("un criterio pasó
de FAIL a PASS: el mejor momento para tirar la traza") y el sistema **capitaliza y resetea sobre
una victoria inexistente**. Es literalmente "el test que pasa por el motivo equivocado" con
`conf 1,00` y `origen: medido`. → **MUERE.**

**GRAFO.** §2 columna `prov.exit_code` y §5(a) `clave='cmd:...'` con valor canónico = exit code.
El interceptor no tiene ese dato. La detección de contradicciones por `GROUP BY clave HAVING
COUNT(DISTINCT valor)>1` compara exit codes inventados: dos ejecuciones, una real con exit 1 y
otra bloqueada con "exit 0" imputado, **son la contradicción** — y la resolución ("gana el que
pasa") **premia al bloqueado**. → **MUERE.**

**PROCESO.** §2.5: `prov.tipo='ejecutada'` = *"salida de un comando con exit code"*, re-verificador
= *"re-ejecutar el comando (opt-in) o **comparar exit almacenado**"*. Comparar un número consigo
mismo es un no-op; es el re-verificador vacío. Pero proceso tiene un salvavidas: su **prueba 6**
usa `GoalContract._check_command_succeeds`, que llama a `subprocess.run` **directamente**
(`cognia/agents/goal_contract.py:93-108`) y sí lee `proc.returncode`. Esa ruta es honesta.
El daño se queda en la banda F (hechos con provenance falsa) y no llega al sello. → **A MEDIAS.**

> **Corolario para los tres:** ninguno puede escribir `origen: medido` / `autor: interceptor` /
> `prov.tipo: ejecutada` hasta que `run_tool` devuelva el `returncode` real. Hoy la
> "provenance de máquina" es una heurística léxica sobre la primera línea, que es exactamente el
> tipo de instrumento que este repo tiene documentado como falible.

### A9 — El interceptor traga toda excepción: la memoria que se apaga sin decirlo

`cognia/harness/interceptor.py`, cabecera del módulo, contrato literal:

> *"CONTRATO — las dos funciones NUNCA lanzan y NUNCA bloquean por su cuenta. (…) Un fallo de
> cualquier capa degrada a 'no hacer nada' y deja pasar la llamada."*

Y el patrón en el cuerpo es, once veces, `except Exception: pass` (líneas 161, 178, 190, 203, 216,
244, 254, 264…). Además la llamada desde `run_tool` está a su vez envuelta
(`cognia/agent/tools.py:495-499`):

```python
try:
    from cognia.harness.interceptor import despues as _harness_despues
    out = _harness_despues(name, args, ctx, out, ok)
except Exception:
    pass
```

**Traza — disco lleno a las 3 de la mañana del segundo día:**

1. Ciclo 612. El agente escribe un fichero. `run_tool` llama a `despues`.
2. `registro.anotar()` intenta el append. `OSError: [Errno 28] No space left on device`.
3. `except Exception: pass`. **El modelo lee el resultado normal de su herramienta.**
4. El agente sigue trabajando 8 pasos más. Cero eventos.
5. Ciclo 613. Igual. Ciclo 614. Igual.

Qué detecta cada uno:

**LEDGER.** Regla **C6**: "ciclo con 0 eventos medidos" → contradicción → dos ciclos seguidos →
CORTE DURO "mudo". Funciona. **Pero el propio evento `contradiccion` se escribe en el ledger, que
es lo que no se puede escribir.** El corte tiene que vivir en memoria del proceso, no en el
ledger; el diseño no lo dice. Si el detector intenta persistir su hallazgo, el hallazgo se pierde
por la misma causa que lo produjo. Y el propio ledger lo admite en su modo de fallo 2:
*"un único bug de conteo en `gate.py` desactiva la única defensa"*. → **A MEDIAS** (detecta a los
2 ciclos ≈ 3 min si el corte es en RAM; MUERE si el corte pasa por disco).

**GRAFO.** Gate B: acciones huérfanas. Sin filas `prov`, el 100% de las acciones son huérfanas →
`>50%` en 2 ciclos → DERIVA → al tercero para. Detecta en 3 ciclos. Además SQLite lanza en el
mismo sitio, así que el diagnóstico llega. → **SOBREVIVE.**

**PROCESO.** Éste es el que se lleva el golpe. Con el LIBRO congelado:
- prueba 1 (sha de banda P) → **verde** (P es del ciclo 0, está en RAM).
- prueba 2 (trazadores en la proyección) → **verde** (ver A13: es tautológica).
- prueba 3 (re-lectura de artefactos) → **verde**: la banda A no creció, los artefactos que
  conoce siguen con su sha.
- prueba 4 (Q1..Q3) → **verde**: las preguntas se sacan de P y de T, que son eternas (lo dice su
  propia §11.1).
- prueba 5 (contradicción) → **verde**: no hay filas F nuevas que colisionen.
- prueba 6 (monotonía) → **verde**: los criterios no encogen.

**6/6 en verde durante horas con el libro congelado.** El único detector es su alarma
*"`tasa_de_abort == 0` durante 50 ciclos = AVERÍA DEL GATE"*, que a 90 s/ciclo tarda
**75 minutos** en disparar — y sólo si alguien la mira, porque está en `/tx estado`, no en el
bucle. → **MUERE.**

---

## 2. Los siete ataques del encargo

### A1 — La tarea de 3 días que se desvía en el ciclo 40 y nadie lo nota

Escenario fijo para los tres. Objetivo: *"cablear las 11 funciones huérfanas de
`cognia/estado/canal.py` al bucle y dejar la suite verde"*. En el ciclo 38 el agente descubre que
`estado_tarea.py` y `canal.py` tienen esquemas incompatibles. Decide "unificar los almacenes
primero". A partir del ciclo 40 trabaja en `cognia/agent/estado_tarea.py`,
`cognia/memory/hierarchical.py` y un `cognia/estado/esquema_comun.py` nuevo. **No es un delirio:
es una subtarea razonable que se come 200 ciclos y no es lo que se pidió.**

**LEDGER.** Sus defensas contra deriva son K4 (recall de restricciones == 100%) y K5 (trazadores).
- K4 compara la proyección contra las restricciones **del propio ledger**, y la banda A la escribe
  el proyector verbatim. Es `render(X) contiene X`: **100% por construcción, ciclo 1 y ciclo 500**.
  No mide nada.
- K5 sí es real (trazadores sobre la primera respuesta del modelo), pero mide *lectura*, no
  *alineación*: el agente desviado lee perfectamente la proyección y luego edita otro fichero.
- K6 (`presupuesto_progreso`, coste por avance verificado) cortaría… si no hubiera avance. Pero la
  subtarea **sí produce avance verificable**: `esquema_comun.py` existe, sus tests pasan, se
  crean criterios derivados. El coste por avance no se dispara.
- R4 ("un criterio pasó de FAIL a PASS") **premia** la deriva con un reset limpio.
- ABANDONO exige 5 ciclos sin cambio en el vector de veredictos **y** sin ningún `fichero` con sha
  nuevo. La deriva produce shas nuevos cada ciclo. Nunca dispara.

Ledger **no tiene ningún detector de acción huérfana**. Los 200 ciclos pasan. A las 5 horas el
dueño ve `/ledger`: 7/7 restricciones presentes, 0 contradicciones, 1.400 eventos, C1 FAIL.
Todo verde salvo lo que importa. → **MUERE.**

**GRAFO.** Gate B: `arista(prov→criterio,'satisface')` resuelta *"por solape de rutas/nombres, no
por LLM"*. Los ficheros de la deriva son `cognia/estado/esquema_comun.py` y
`cognia/agent/estado_tarea.py`; los criterios nombran `cognia/estado/canal.py` y
`tests/test_canal.py`. Solape por nombre de ruta: `cognia/estado/` es prefijo común →
`esquema_comun.py` **cuenta como relacionado**. `estado_tarea.py` comparte el token `estado` con
`canal`… depende del algoritmo, que el diseño no fija. Con el criterio más laxo (prefijo de
directorio) la deriva es invisible; con el más estricto (nombre base exacto) el 90% de las
acciones legítimas serían huérfanas y el gate dispararía todo el rato.
**El diseño no especifica el algoritmo, y el rango de comportamientos va de "no detecta nunca" a
"detecta siempre".** Ese hueco es la deriva. → **A MEDIAS.**

**PROCESO.** Mismo detector de huérfanas (>40% en un ciclo) con el mismo hueco, **más** la prueba
6 (monotonía) que no ayuda porque nada retrocede, **más** una defensa real que los otros no tienen:
`limites.Presupuesto` cableado con ejes segundos/tokens/pasos y `/tx iniciar --ciclos 500
--horas 12`. La deriva no se detecta, pero **se acota**: a las 12 h el `LimiteExcedido` para la
tarea con un informe. No es detección; es un despertador. → **A MEDIAS.**

> Los tres comparten la ceguera. Ninguno tiene el detector que sí funcionaría y que es barato:
> **exigir que cada ciclo declare a qué criterio congelado sirve, antes de actuar, y contar los
> ciclos que no consiguieron mover ninguno.** Proceso está a un paso (banda Q), grafo a dos
> (`arista satisface`), ledger no lo tiene.

### A2 — La alucinación del ciclo 7 que es "hecho verificado" en el 9 y contamina 300 ciclos

**LEDGER.** El modelo no puede emitir hechos (I1). Correcto. Pero **sí puede emitir `decision`**,
y las decisiones **entran en la proyección** (banda B, últimas 8 con `refs` medidas).

Traza:
1. c7: el agente corre `venv312\Scripts\python.exe -m pytest -k canal`. Salida real:
   `no tests ran in 0.31s`, exit 5. Evento `comando` #813, `origen: medido`, `conf 1,00`. **Es un
   hecho verdadero.**
2. c7: `decidir "el canal no tiene tests; hay que escribirlos desde cero" --porque 813`.
   La tool exige `--porque` con al menos un evento medido: lo tiene. Evento `decision` #815,
   `conf 0,30`, entra en banda B.
3. La realidad: los tests existen en `tests/estado/`, y `pytest -k` desde la raíz **no los
   recoge** (es exactamente la lección `N-006` del ejemplo de `diseno_proceso.md`). La inferencia
   es falsa; la evidencia es real; el `refs` es impecable.
4. c8–c15: la decisión se re-lee 8 veces, sin la traza que la produjo, presentada como estado
   consolidado con referencia a evidencia medida. El agente escribe
   `tests/test_canal_nuevo.py`. Eventos `fichero`, `origen: medido`, `conf 1,00`.
5. c16: la decisión cae del tope de 8. **Sus consecuencias no.** Ahora hay tests duplicados; el
   criterio C3 (`pytest -q`) falla por una razón nueva; y los eventos que lo sostienen tienen
   `conf 1,00`.

Ninguna de las 7 reglas de contradicción lo caza: C1 mira shas, C2 veredictos del mismo criterio,
C3 sólo compara **decisiones entre sí** con solape ≥0,6 y marcador de negación, C4 ámbitos, C5
resueltos, C6 mudez, C7 trazadores. **Una decisión falsa que nadie contradice no contradice nada.**
K3 sólo retracta `afirmacion`, no `decision`.

El propio ledger lo diagnostica en su modo de fallo 3 y termina: *"puedo garantizar la procedencia
de los hechos y no puedo garantizar la validez de los razonamientos que los conectan"*. Es la
confesión correcta. → **MUERE** (con honestidad declarada, que no es lo mismo que sobrevivir).

**GRAFO.** Aquí el ataque es más bonito porque **dos mecanismos del diseño se ciegan mutuamente**.

Traza:
1. c7: el modelo emite
   `AFIRMO clave=test:tests/test_canal.py valor='exit==0' texto="el canal esta cableado y sus
   tests lo verifican" verificador="venv312\Scripts\python.exe -m pytest -q tests/test_canal.py"
   espera=exit==0`.
2. Entra como `hipotesis`, confianza 0,15. Correcto.
3. **Control negativo (§7 C1):** se renombra `tests/test_canal.py` y se re-ejecuta. pytest
   devuelve exit 4 (`file or directory not found`). **SUSPENDE** → `examen_ok=1`. El verificador
   es legítimo: discrimina.
4. Se ejecuta de verdad: exit 0. **Ascenso a `verificado`.** Confianza =
   `1.00 × 1.0 (examen_ok) × 1.0 (frescura) × 1 = 1,00`.
5. El contenido real de `tests/test_canal.py` es
   `def test_import(): import cognia.estado.canal`. El verificador comprueba que un módulo
   importa. El `texto` afirma que **está cableado**. El verificador es honesto y la afirmación es
   falsa. Es el modo 1 que grafo declara.
6. c9 a c309: la fila entra por BM25 cada vez que la consulta menciona "canal" — o sea siempre —
   marcada `[V] 1.00`. Re-verificación programada cada ≤20 ciclos: **verde siempre**, 2,4 s.

Y ahora el remate. Grafo propone como centinela:
`poder_discriminante = |{verificadores que han fallado alguna vez en su historia}| / |verificadores|`.
**El control negativo del paso 3 ES un fallo en su historia.** Todo verificador que aprobó el
examen tiene ≥1 fallo registrado. `poder_discriminante = 1,00` para el 100% del corpus, siempre.
**El centinela del modo 1 lo neutraliza el control negativo del §7.** El diseño trae la enfermedad
y el termómetro roto en la misma caja. → **MUERE.**

**PROCESO.** `dicha` está prohibida en P/D/F. Para colar el hecho falso hay que disfrazarlo de
`leida` o de `ejecutada`.
- Vía `ejecutada`: cae en A8 (no hay exit real) → entra, pero la prueba 6 con `GoalContract`
  usa `subprocess` directo y contradice al hecho en el mismo commit. Se marca contradicción
  (prueba 5) y se fuerza `supersede`.
- Vía `leida`: `prov = {"tipo":"leida","ruta":"cognia/estado/canal.py","linea":444,
  "cita":"def conservacion(", "sha_fuente":"e77a01b3"}` con
  `texto: "conservacion() ya está cableada al bucle"`. El re-verificador es
  `verificar_cita(cita, open(ruta).read()) and sha_fuente == sha_actual`. **La cita está.
  El sha cuadra. El texto miente.** El re-verificador comprueba que el fichero contiene
  `def conservacion(`, no que esté cableada.

Ésa es la grieta estructural: **`verificar_cita` verifica la CITA, y el diseño la usa para
avalar el TEXTO.** El texto es prosa libre del modelo y no está atado a la cita por nada.
La prueba 3 lo re-lee cada commit y sale verde para siempre, porque el fichero no cambia.
Proceso dice *"un hecho falso no puede sobrevivir 2 commits"*: éste sobrevive 500.
→ **MUERE.**

> Los tres caen. **La provenance verifica el origen del fragmento, nunca la proposición que el
> fragmento supuestamente sostiene.** Es el mismo agujero con tres nombres: `decision` con `refs`
> (ledger), `texto` junto a un `verificador` trivialmente cierto (grafo), `texto` junto a una
> `cita` real (proceso).

### A3 — El loop de dos ciclos alternos que ninguna heurística de "no repetir" caza

Escenario: dos ficheros acoplados. Arreglar `canal.py` rompe `estado_tarea.py` y viceversa.
Ciclo par: edita `canal.py`, la suite baja de 5738 a 5731. Ciclo impar: edita `estado_tarea.py`,
vuelve a 5738 pero C1 falla. Sin fin.

**LEDGER.** R3 = *"misma firma `(tool, destino, exit)` **dos veces seguidas**"*. La secuencia de
firmas es `S_A, S_B, S_A, S_B, …`: **nunca dos iguales seguidas**. R3 muerto.
- La banda C ("YA INTENTADO", contador `firma → n, exit`) sí se lo enseña al modelo:
  `editar canal.py -> ok x37`. Pero es información, no corte, y `ok` no es señal de error (A8).
- ABANDONO exige 5 ciclos sin cambio de veredictos **y** sin `fichero` con sha nuevo. Cada ciclo
  produce shas nuevos. Nunca dispara.
- C2 (dos `verificacion` del mismo criterio con `ok` distinto sin `fichero` entre medias) no
  aplica: **sí** hay ficheros entre medias.
- K6 (coste por avance verificado): no hay avance, luego `coste_sin_avance` crece y **acaba
  cortando**. Ése es el único que funciona… si el numerador se mide bien. Con `ok=True` para un
  pytest fallido (A8), el sistema cree que hay avance.

→ **MUERE** (y con A8 arreglado, **A MEDIAS**: corta por presupuesto, no por detección de loop,
y el diseño no dice cuántos ciclos tarda).

**GRAFO.** Tres detectores:
1. `pasos_sin_avance() >= 6` — plausible que dispare dentro de un ciclo, pero el ciclo es de 8
   pasos y *sí* hay avance aparente (ficheros escritos, filas de interceptor creadas).
2. Firma `sha256(tool + args_normalizados)` ≥3 veces en 20 pasos → veto. **Los args cambian cada
   vez** (el contenido del parche es distinto): el sha nunca se repite. Muerto.
3. Esterilidad epistémica: 3 ciclos con `ascensos = 0`. **Y aquí está la ambigüedad letal**: la
   regla 2 del §4 dice que `autor='interceptor'` **crea `verificado` directamente**. ¿Eso cuenta
   como ascenso? El diseño no lo dice. Si cuenta —que es lo natural, es una transición a
   `verificado`— entonces **cada ciclo tiene ascensos > 0 por el mero hecho de escribir ficheros**
   y el detector no dispara nunca. Si no cuenta, dispara en 3 ciclos.

**Una ambigüedad de una frase decide entre "corta en 4,5 minutos" y "gira 12 horas".** Y el modo
de fallo es el silencioso. → **MUERE** (por indefinición; es reparable con una línea, pero hoy
está indefinido).

**PROCESO.** Es el único que diseñó explícitamente contra la oscilación.
- LOOP-A: `sha256(conjunto ordenado de (tool, ruta_destino))` del ciclo + criterios satisfechos,
  misma firma 2 ciclos seguidos. Firmas: `{canal.py}`, `{estado_tarea.py}`, `{canal.py}`…
  **alternan: nunca dos seguidas.** Muerto por la misma razón que R3 del ledger.
- LOOP-B: misma `(tool, ruta, sha(args))` con **mismo sha de salida**, 3 veces en un ciclo.
  Los args cambian. Muerto.
- **LOOP-C: oscilación del sha de un fichero A→B→A entre ciclos, 1 oscilación completa.** Éste
  sí lo caza… **si el agente reescribe bytes idénticos**. En la práctica el segundo "arreglo" de
  `canal.py` no es byte a byte el primero (una línea movida, un comentario, un orden distinto de
  imports): `sha ≠ sha`. La igualdad de bytes es **demasiado estricta para una oscilación
  semántica**.
- LOOP-D: `coste_sin_avance() > 3× mediana` → `FALLO-ESTANCADO`. Funciona, tarde, y con la misma
  dependencia de A8.

→ **A MEDIAS.** Es el único con un detector conceptualmente correcto (LOOP-C), y falla por elegir
igualdad de bytes donde hacía falta distancia. Un `sha` de AST normalizado o de conjunto de
líneas ordenadas lo arreglaría; la diferencia son 20 líneas de código.

### A4 — El estado corrupto a mitad de commit

Tres sub-casos: **(i)** proceso matado, **(ii)** disco lleno, **(iii)** JSON truncado.

**LEDGER.**
- (iii) **Bien resuelto**: cadena `prev` de sha, "trunca a la última línea válida, emite
  contradicción, sigue". Correcto. Y el repo ya tiene el escritor atómico que hace falta
  (`cognia/backend_activo.py:271 escribir_linea_jsonl`, lock entre procesos + `os.write` única
  sobre `O_APPEND` — el comentario del propio módulo dice que sin eso *"dos procesos concurrentes
  entrelazaban trozos de línea"*).
- (i) **El agujero es `fold.json`**, no el ledger. Se reescribe cada 1.000 eventos y en cada
  cierre de ciclo. Un `kill` a mitad de esa escritura deja un JSON truncado. Recuperación:
  I3 hace re-fold completo en cada reset y compara sha → **detecta y recomputa en 0,15 s**. Bien.
- (ii) A9: silencio total. → **A MEDIAS**, tirando a bien salvo por A9.

**GRAFO.** El mejor de los tres, y no por diseño sino por elección de sustrato: **SQLite con
`journal_mode=WAL` y `foreign_keys=ON`**. Un `kill` a mitad de transacción hace rollback solo.
Un disco lleno lanza `sqlite3.OperationalError` **ruidosamente** (no hay `except: pass` en la capa
`almacen`, aunque sí lo habría si la escritura va por el interceptor → A9).
`/memoria fsck` con 5 chequeos y `--reparar` es concreto y ejecutable.
Un detalle que sí le puedo romper: **la banda P tiene doble soporte (`DB` + `.cabecera.txt`) y
nada garantiza que los dos se escriban atómicamente**. `/memoria retirar 12` actualiza
`ciclo_baja` en la DB y reescribe `.cabecera.txt`; matado en medio, el fichero de texto y la DB
discrepan, y §12(e) dice que ante DB ilegible **se reconstruye P desde `.cabecera.txt`** — o sea,
desde la copia posiblemente rancia. Es un caso estrecho. → **SOBREVIVE.**

**PROCESO.** Aquí hay una contradicción interna que le cuesta un ciclo entero de trabajo.
- §3.1 p1: *"**flush WAL**: toda observación **pendiente** del ciclo → `libro.append()`, fsync"*.
  Si hay observaciones pendientes al llegar al PREPARE, es que **durante el ciclo las observaciones
  viven en memoria**.
- §6.1: *"el LIBRO se escribe siempre, resetee o no"*.

Las dos no pueden ser verdad. Y si la primera lo es:

Traza: ciclo 41, paso 6 de 8. El agente ha escrito 4 ficheros reales en disco. Corte de luz.
Al reiniciar, el LIBRO termina en `TX-0040`. Los 4 ficheros **existen** con contenido nuevo; la
banda A tiene los shas viejos. La prueba 3 del siguiente commit detecta 4 mismatches → los marca
`stale` → §2.5: *"si no se re-lee en el ciclo siguiente, se `invalidate` y desaparece de la
proyección"*. **El sistema borra de su memoria los 4 artefactos que sí produjo** y el agente los
re-deriva desde cero. Se pierde un ciclo (90 s) y, peor, si uno de esos ficheros era
`critico:true` el `GoalContract` lo ve satisfecho en disco mientras el LIBRO no sabe por qué:
**el estado y el mundo divergen y la reconciliación es en la dirección equivocada** (se cree al
libro, no al disco).
Además el `fsync` que la §3.4 presupuesta (~4 ms × 2) **no existe hoy** en
`escribir_linea_jsonl`; habría que añadirlo, y en NVMe con Windows un `fsync` por evento no son
2 ms sino más. → **A MEDIAS.**

### A5 — El crítico que aprueba porque comparte el error del principal

Los tres han hecho lo correcto con la versión obvia del ataque: sacaron al LLM de la ruta crítica.
Así que el ataque de verdad es otro: **el crítico de código comparte el error del código que
produjo el estado, porque los escribe el mismo autor con la misma suposición falsa.**

**Instancia concreta y compartida:** todos los verificadores que "ejecutan" pasan por
`ejecutar` → `_shell` → sentinel. Y el emisor de eventos también. **La suposición falsa
"`ok` significa exit 0" vive en los dos lados.** Un crítico que re-ejecuta a través de la misma
capa que produjo el hecho no es un contrafactual: es la misma medición repetida. Es exactamente
la lección de esta casa: *"cinco instrumentos aprobaron algo roto en una noche"*.

**LEDGER.** K1: *"re-ejecuta el `cmd` de cada criterio en proceso nuevo, cwd=workspace"*.
"Proceso nuevo" es lo correcto, pero si va por la tool `ejecutar` hereda el sentinel y la regex.
Si va por `subprocess` directo, **se salta el centinela**: el criterio es texto que puede haber
escrito el modelo (V3 deriva criterios; §12 permite `--criterio` del usuario, pero nada impide
que un `criterio` derivado contenga un comando destructivo). El diseño no dice cuál de las dos.
→ **A MEDIAS.**

**GRAFO.** El peor, y por una razón que el diseño no ve. **El modelo escribe el comando del
verificador**: `AFIRMO … verificador="<comando>" espera=exit==0`. Y el control negativo §7 C1
lo ejecuta **después de mutar la evidencia**: *"renombrar el fichero destino / revertir el último
diff / truncar el fichero a 0 bytes / borrar la línea que casa el patrón"*.
O sea: el sistema (1) toma una cadena de shell escrita por el LLM, (2) **destruye ficheros a
propósito**, y (3) la ejecuta. En un "workspace copia" — ver A10 para el coste de esa copia.
Si la copia falla o se hace por referencia, las mutaciones caen en el repo real.
Y hay un caso benigno igual de malo: el verificador `venv312\Scripts\python.exe -m pytest -q`
ejecutado sobre un workspace donde acabas de **truncar un fichero a 0 bytes** puede dejar
`__pycache__` envenenado o ficheros de estado en `.cognia/` que el ciclo siguiente lee como
verdad. → **MUERE** (como mecanismo seguro; el concepto de control negativo es bueno, la
implementación propuesta es una primitiva de ejecución arbitraria con destrucción previa).

**PROCESO.** El único que puso una prueba con LLM y la hizo inocua: prueba 4, tres preguntas cuya
respuesta es una **cadena literal del LIBRO**, corregidas por `normalizar(resp)==normalizar(esperada)`.
No hay juicio. Es una prueba de *lectura*, y está bien construida. El ataque que le queda es el
de A13 (de dónde salen las preguntas) y el que él mismo declara en §11.1: al muestrear las Q de
las bandas que el proyector eligió, **el detector comparte el sesgo del proyector**.
→ **SOBREVIVE** en el ataque tal como está enunciado; **A MEDIAS** contando el sesgo declarado.

### A6 — El objetivo REAL cambia: el dueño cambia de idea en el ciclo 120

Escenario: *"da igual el canal de estado; lo que quiero es que `/largo` funcione con Qwen3.8-27B"*.
Objetivo nuevo, dos restricciones nuevas, tres criterios que ya no aplican.

**LEDGER.** `objetivo` es *"permanente, inmutable"*. Sí existe `retractacion` emitible por
`usuario`, así que mecánicamente se puede. El problema son las **consecuencias**:
1. Los criterios están **CONGELADOS** en el `GoalContract`. C1/C2/C3 siguen gateando el cierre.
2. **ABANDONO**: *"5 ciclos consecutivos sin cambio en el vector de veredictos de criterios y sin
   ningún evento `fichero` con sha nuevo"*. Tras el pivote el agente trabaja en el modelo nuevo;
   el vector de los criterios viejos **es constante por definición**. Si además el trabajo es de
   configuración (editar `.env`, arrancar el servidor) puede haber ciclos sin shas nuevos.
   **El diseño escribe un informe de fracaso y para, en el ciclo 125, por haber obedecido.**
3. Las decisiones vigentes (banda B) y las lecciones (banda C) siguen siendo del objetivo viejo y
   siguen entrando en la proyección.
4. Y si el dueño **añade** las restricciones nuevas sin retirar las viejas, se acerca al
   `HARD_STOP` de 4.000 chars de banda A, que el propio ledger declara como su deuda #1.

→ **MUERE** (el pivote exige retractar objetivo + criterios + decisiones a mano, y el ledger no
tiene un comando de "re-abrir la tarea"; sólo `retractar <i>` uno a uno).

**GRAFO.** El mejor de los tres: `/memoria retirar 12 "obsoleta"` es la vía explícita, sólo el
dueño, y la fila queda con `ciclo_baja` (no se borra, se puede auditar). Añadir el objetivo nuevo
es un `INSERT` en banda P. Nada revienta.
Lo que sí le rompo: **las 218 filas `verificado` de la banda H siguen vivas, con confianza 1,00,
y BM25 las trae por relevancia léxica**. Tras el pivote a Qwen3.8-27B, la consulta menciona
"modelo", "contexto", "slot" — y trae hechos verificados bajo la premisa retirada
(`cfg:llama.n_ctx = 200192` medido con el 9B, `test:tests/test_canal.py exit==0`). Grafo no tiene
**alcance**: una fila no está atada a la restricción bajo la que se verificó. La confianza es
1,00 y el marcador es `[V]`. → **A MEDIAS.**

**PROCESO.** Aquí hay una **contradicción interna fatal**:
- §2.2 permite la op `amend` en banda P: *"requiere evento humano o de contrato"*.
- §3.2 prueba 1: *"`sha256(render_banda_P(proy_nueva)) == sha_P0` **congelado en ciclo 0**.
  Igualdad de BYTES"*, y §5.1 lo llama *"la constante del resto de la tarea"*.

**Si haces `amend`, la prueba 1 falla para siempre.** Y §4.1 dice literalmente que ABORT-PREPARE
*"sólo puede ocurrir por una causa: una banda desbordó su tope de tokens"* — así que la escalera
de recuperación (subir topes ×2 → MODO ANCHO → PARTIR LA TAREA) **no contempla este caso y
ninguno de sus tres escalones lo arregla**. Traza: ciclo 120, `amend` de P. Ciclo 121: PREPARE →
prueba 1 falla → `degradar_topes` (no cambia el sha) → falla → reintento 2 → falla → MODO ANCHO
(no cambia el sha) → ciclo 122 igual → ciclo 123 igual → **`requiere_particion` y se paran los
ciclos**. El dueño cambió de idea y el agente se suicida en 3 ciclos con un mensaje sobre
particionar la tarea.
→ **MUERE.**

### A7 — El coste: ¿cuántos segundos al día se van en comprimir, verificar y rehidratar?

Modelo de coste, todo con números medidos:
`t_prefill(n) = 0,33876·n + 1,377e-6·n² ms` (ajuste con error <1,5%); decode 60 tok/s;
**un solo slot**, así que todo serializa.

**Comprimir: los tres aciertan, y es el punto donde los tres ganan de calle.** Ninguno usa LLM
para comprimir. Ledger: fold ~0,15 s. Grafo: `SELECT` + BM25, ~0,05 s. Proceso: `proyectar()`
~5 ms. Frente a los **16,49 s** por compactación medidos en `falsacion.md`. Aquí no hay ataque:
es el mejor hallazgo compartido de los tres documentos.

**Rehidratar: barato, y menos de lo que dicen.**
- Ledger, 560 tok: `t = 190 + 0,4 = 190 ms`. El diseño dice 0,24 s "con prefijo caliente". El
  número es correcto; **el mecanismo que alega es falso** (con la caché del slot ocupada por los
  ~7k del ciclo anterior, el prefijo común es system+banda A ≈ 40% → la tabla medida dice
  **NO reusa** a 50% y ni siquiera a 90%). Da igual: 190 ms es 190 ms.
- Grafo, 3.200 tok: `t = 1.084 + 14 = 1,10 s`. Dice 1,22 s en frío y **0,25 s con caché**; la
  segunda cifra es la que no se sostiene (mismo motivo).
- Proceso, 3.050 tok: `t = 1.033 + 13 = 1,05 s`. Dice 1,43 s. Conservador. Bien.

**Verificar: aquí es donde se los come el reloj, y sólo uno lo presupuestó.**

| | Ledger | Grafo | Proceso |
|---|---|---|---|
| Trabajo por ciclo (decode + tools) | 8×200 tok /60 = 26,7 s + tools ~20 s = **46,7 s** | 8×150 /60 = 20 s + tools ~20 s = **40 s** | 8×300 /60 = 40 s + tools ~20 s = **60 s** |
| Comprimir | 0,15 s | 0,05 s | 0,005 s |
| Rehidratar | 0,19 s | 1,10 s | 1,05 s |
| **Verificar** | **K1 re-ejecuta TODOS los criterios, cada ciclo. Sin tope.** | **1,5 s duros por ciclo** (el único que lo capa) | prueba 6 amortizada ~1/3 ciclos |
| Verificar, con 3 criterios de 2 s | 6 s | 1,5 s | ~1 s |
| Verificar, con un criterio = `pytest -q` | **timeout 30 s, cada ciclo** | 1,5 s (se queda fuera del tope y **nunca se re-verifica**) | 30 s cada 3 ciclos = 10 s |
| **Sobrecarga en 24 h (criterios baratos)** | 6,3/53 = **12%** ≈ 2,9 h | 2,65/42,6 = **6,2%** ≈ 1,5 h | 2,1/62 = **3,4%** ≈ 0,8 h |
| **Sobrecarga en 24 h (criterio = la suite)** | 30,3/77 = **39%** ≈ 9,4 h | **6,2%** (por no mirar) | 11,1/71 = **16%** ≈ 3,7 h |

Lecturas del cuadro:

1. **Ledger no tiene tope de verificación y su §16 "Números, juntos" no tiene una sola línea para
   K1.** Presupuesta los resets (1,8 min en 8 h) y se deja fuera la partida que domina. En este
   repo, con la suite real, **el crítico cuesta más que el trabajo**. → **MUERE en el presupuesto.**
2. **Grafo es el más barato porque es el único que capó la verificación (1,5 s/ciclo).** Y ese
   mismo tope es lo que crea su modo 1: los verificadores caros —los únicos que verifican
   comportamiento— **nunca entran en el presupuesto y por tanto nunca se re-ejecutan**. Paga
   6,2% y compra una banda H de verdades baratas. → **SOBREVIVE en coste, y el ahorro es la
   enfermedad.**
3. **Proceso es el único que hizo la aritmética honesta** (§3.4: *"el coste que sí duele y lo
   digo"*, con la mitigación de correr el pytest sólo si cambió un artefacto crítico). Su 1,7% es
   optimista —sale 3,4% con criterios baratos y 16% con la suite— pero el orden de magnitud y el
   método son correctos. → **SOBREVIVE.**

**Y la comparación que ninguno hace.** El brazo nulo —ventana ancha, sin lobotomía, sin ledger—
tiene sobrecarga **0%** y recall de restricciones **1,000** medido a 111.406 tokens. Los tres
diseños pagan entre 3,4% y 39% de reloj para conseguir el mismo 1,000 en restricciones y una
mejora **no medida** en higiene. **Ledger es el único que registra esto como experimento (E0) y
predice honestamente que puede perder.** Los otros dos no tienen brazo nulo de la arquitectura
entera: el "nulo" de grafo es recuperación aleatoria de la banda H (nulo de un componente), y
proceso compara (a) sin reset / (b) reset sin commit / (c) reset con commit — **le falta el brazo
"sin nada de esto"**.

---

## 3. Ataques al instrumento (los que salen de leer el código)

### A10 — El criterio no cabe en el reloj: 30 s de tope contra una suite de 12 minutos

`cognia/agents/goal_contract.py:34`: `_COMMAND_TIMEOUT_SECONDS = 30`, hardcodeado, sin env.
`cognia/agent/tools.py:1763`: `timeout = min(600, max(1, int(...)))` — **tope duro 600 s**, por
defecto 30 s.
`cognia/harness/interceptor.py`, cabecera: *"en este repo la suite son **6909 tests / 12 min**"*.

12 min = 720 s > 600 s. **`command_succeeds "venv312\Scripts\python.exe -m pytest -q"` es
imposible en esta máquina por cualquiera de las dos vías.** Devuelve
`False, "timeout after 30s"`.

- **LEDGER**: su ejemplo §5.2 muestra `C3 NUNCA venv312\Scripts\python.exe -m pytest -q` y su §12
  muestra `c4 ... C3 PASS 2m51s`. Ese PASS **no puede ocurrir**. Y su condición de **ÉXITO** exige
  *"los N criterios en PASS re-ejecutados en limpio"*. Con C3 imposible, la tarea nunca cierra por
  éxito; cierra por ABANDONO a los 5 ciclos sin cambio de veredictos. → **MUERE.**
- **GRAFO**: `verificador.clase='cmd'` con `coste_ms` medido; su presupuesto de re-verificación es
  *"las ≤3 filas más antiguas cuyo `coste_ms` sume <1.500 ms"*. Un verificador de 30.000 ms
  **nunca entra**, así que nunca se re-verifica y su frescura decae a 0,4 → la fila pasa a
  `sospechoso` a los 60 ciclos y ahí se queda para siempre. Degrada con ruido, no en silencio.
  Y su cierre exige re-verificar **todos**, lo que reintroduce el timeout. → **A MEDIAS.**
- **PROCESO**: prueba 6 = `GoalContract.check()`. Devuelve `False` por timeout. Como la
  monotonía sólo exige `satisfechos_k ⊇ satisfechos_{k-1}` y ese criterio está siempre fuera del
  conjunto, **no rompe la monotonía**: degrada a "un criterio que nunca se satisface", visible en
  el panel (`criterios ████░░ 4/7`). Su ÉXITO exige los 7 → no cierra nunca por éxito, cierra por
  `FALLO-PRESUPUESTO` a las 12 h. → **A MEDIAS.**

> Los tres diseños ponen "correr la suite" como criterio de ejemplo. Ninguno comprobó que la capa
> de herramientas del propio repo lo prohíbe. El arreglo es trivial (partir la suite por
> directorio, o subir el tope), y el hecho de que ninguno lo viera es el síntoma: **los tres
> diseñaron contra los informes, no contra el código.**

### A11 — El gate flaky al 50% contra la monotonía y la contradicción

Axioma del repo: *"Gate e2e flaky (~50%)"*. Un criterio flaky oscila PASS/FAIL sin que nada cambie.

- **PROCESO** es el que más sufre. Prueba 6: *"el conjunto de criterios satisfechos **no puede
  encoger**"*. Un flaky que pasa en el ciclo 12 y falla en el 13 **rompe la monotonía** →
  **ROLLBACK-CONTRATO** (§4.3): autopsia causal atribuye un "culpable", `checkpoints.restaurar_hasta(m)`
  **revierte ficheros reales que estaban bien**, `anticuerpos` sintetiza un veto contra una llamada
  inocente, y se re-proyecta desde `TX-anterior`. **Un test flaky destruye trabajo bueno y planta
  un anticuerpo permanente que veta la acción correcta.** A 50% de flakiness y ~40 ciclos/hora,
  eso pasa varias veces por hora. → **MUERE.**
- **LEDGER** lo previó: regla **C2**, *"dos `verificacion` del mismo criterio con `ok` distinto
  sin `fichero` entre medias → 1ª-2ª: marca `flaky`; 3ª: contradicción"*, con el comentario
  correcto (*"un test flaky es un bug de instrumento, no del agente"*). Es la mejor respuesta de
  los tres documentos a este problema. Falla sólo cuando hay ficheros entre medias, que es lo
  normal en un ciclo de 8 pasos. → **A MEDIAS**, con crédito de diseño.
- **GRAFO**: `verificado --[re-verificacion.ok=0]--> sospechoso` (no `refutado`, *"puede ser el
  entorno"*) y `sospechoso --[2ª ok=0]--> refutado`. Un flaky al 50% oscila
  `verificado → sospechoso → verificado → sospechoso` sin llegar nunca a `refutado`. Sobrevive
  sin daño; el coste es ruido en el panel. → **SOBREVIVE.**

### A12 — El pre-calentado de caché destruye la caché que calienta

Ledger §7 y grafo §11 proponen lo mismo: durante el tiempo de pared de una herramienta lenta,
mandar la cabecera con `max_tokens=1` para dejar el prefijo residente (*"swap caliente 59 ms
frente a 2.840, 48×"*).

Traza, ledger, ciclo 41, paso 3:
1. El agente lanza `pytest tests/estado -q`. 25 s de pared. El slot 0 está ocioso y su caché
   contiene los **~4.000 tokens del ciclo en curso**.
2. El harness manda a slot 0 la banda A + system (≈250 tok) con `max_tokens=1`.
3. **llama.cpp reemplaza el estado del slot.** La caché de los 4.000 tokens del ciclo vivo se ha
   ido.
4. Vuelve el pytest. El agente hace su paso 4. El prompt son 4.800 tokens de los que sólo los ~250
   iniciales están calientes → se re-procesan **4.550 tokens**: `t = 1.541 + 28 = 1,57 s` en
   lugar de los ~0,25 s del append.
5. Repetido hasta 8 veces por ciclo: **+10,6 s por ciclo**, sobre un trabajo de 46,7 s. **+23%.**

Grafo intenta esquivarlo poniendo el pre-calentado en **slot 1**. Pero **las cachés son por slot**:
calentar el slot 1 no ayuda al ciclo siguiente, que corre en el slot 0. Y el slot 1 lo comparte
con el crítico C2 y con la re-verificación: `min(4 estados, ~1 GiB)` y el acierto **cae a cero de
golpe** (4×2k → 4/4; 5×2k → **0/5**). Tres inquilinos rotando en un slot es exactamente el
régimen donde la medición dice que el acierto se desploma.

- **LEDGER**: → **MUERE** el componente (sleep-time compute tal como está descrito). El resto del
  diseño no depende de él.
- **GRAFO**: → **MUERE** el componente, por inútil más que por dañino.
- **PROCESO**: no lo propone. Su §5.2 (*"durante un ciclo, nada se reescribe en la ventana"*) es
  la política correcta y es la única de las tres que respeta lo medido. → **SOBREVIVE.**

### A13 — Los trazadores comprobados contra la proyección: una tautología en el gate

`cognia/estado/canal.py:507`: `comprobar_trazadores(estado, texto)` cuenta cuántos IDs aparecen
**en un texto**. La docstring (línea 464) explica por qué funciona: *"ningún resumidor puede
reconstruirlo por sentido común, así que si aparece en el texto post-compactación es porque
SOBREVIVIÓ"*. La premisa es **"lo escribió un resumidor LLM"**.

**PROCESO §3.1 p4 lo aplica a `proy_nueva`**, que es la salida de `bandas.proyectar()`, una
función **pura y determinista** que acaba de escribir la banda T verbatim desde el LIBRO.
La prueba 2 pregunta "¿está en el texto lo que acabo de escribir en el texto?".
`recall = 6/6` en el ciclo 1 y en el 500. **Sólo puede fallar si el proyector tiene un bug en una
banda de 120 tokens con `add` sólo en el ciclo 0.** Es una de las 5 pruebas del GATE de PREPARE,
y no aporta ninguna información. Proceso lo intuye en §11.2 (*"4 de 6 pruebas se vuelven teatro"*)
pero no ve que la 2 nace tautológica, no se vuelve.

Uso correcto del mismo instrumento, para contraste: **ledger K5** (`comprobar_trazadores` sobre
**la primera respuesta del modelo**) y **proceso prueba 4** (Q1–Q3 contestadas por la sesión nueva).
Ésas sí miden algo: si el modelo *leyó*.

Daño colateral que afecta a los tres: los trazadores se siembran vía `anotar_restriccion` /
`anotar_decision` (`canal.py:499-502`), o sea que **entran en la banda de restricciones como
restricciones falsas**: `"NUNCA tocar el fichero legado_TRZ-B0E217.py"`. En ledger eso ocupa
presupuesto de la banda A —cuyo `HARD_STOP` es de 4.000 chars y es su deuda declarada #1— y peor:
la **regla C4** (*"una `restriccion` con ámbito de ruta y un `fichero` sobre esa ruta →
VIOLACIÓN: corte inmediato"*) puede dispararse contra un fichero **inventado por el instrumento**.

- **LEDGER**: K5 bien puesto; contaminación de banda A y riesgo C4. → **A MEDIAS.**
- **GRAFO**: no usa trazadores como gate (usa `gate_presencia` con `_presente`, que tiene el otro
  problema: `UMBRAL_COBERTURA = 0.6`, cobertura de tokens, **una paráfrasis puntúa "presente"** —
  `canal.py:117-123`). El gate de grafo dice "1.00" mientras el ID exacto puede haberse perdido.
  → **A MEDIAS.**
- **PROCESO**: prueba 2 tautológica en el gate; prueba 4 correcta. Y §3.3 **acierta de pleno** al
  prohibir que `conservacion()` (difuso) vote. → **A MEDIAS.**

### A14 — El rollback restaura la mitad del mundo

Los tres usan `harness/checkpoints.py` para revertir ficheros. Lo que ese módulo cubre, leído:

- Sólo se registra lo que pasa por `interceptor.antes` → `ruta_destino` → y `ruta_destino`
  (`interceptor.py:95-106`) sólo conoce **4 tools**: `escribir_archivo`, `editar_archivo`,
  `apendar_archivo`, `borrar_archivo` (`_ESCRIBEN`, líneas 48-53).
- **Todo lo que escribe `ejecutar` es invisible**: un `pytest` que deja `.pytest_cache`, un
  `black`/`ruff --fix` que reformatea 40 ficheros, un script del propio agente, un
  `git checkout`, un build. Nada de eso tiene checkpoint.
- `_MAX_BYTES_VERSIONADO = 2 MB` y `estado='no_versionado'` para lo no-utf8 o lo grande
  (`checkpoints.py:85-86, 318, 350`): *"deshacer lo AVISA y no lo toca"*.
- `_MAX_SESIONES = 20`: se poda. En una corrida de 500 ciclos con varias sesiones, los
  checkpoints viejos **se borran**.

Traza: ciclo 200, el agente corre `venv312\Scripts\python.exe -m black cognia/` (head `python` →
ALLOW en el sentinel, `sentinel.py:52`). 60 ficheros reformateados. Ciclo 201: rollback a 199.

- **LEDGER §9.4**: *"los ficheros se restauran aparte con `harness/checkpoints.py`, usando los sha
  del ledger para verificar que la restauración fue correcta"*. Los 60 ficheros **no tienen
  checkpoint**, y sus shas en el ledger tampoco cambiaron (no pasaron por el interceptor), así que
  la verificación por sha **da OK sobre un mundo que no se restauró**. Vuelve el estado y dice que
  cuadra. → **MUERE.**
- **GRAFO §12 paso 4**: *"verificar: `snapshot.vigentes_sha` recalculado debe cuadrar; si no, se
  aborta y se avisa"*. Eso verifica la **DB**, no el disco. Paso 5 (*"re-verificar los
  verificadores de las filas restauradas"*) sí re-ejecuta y detectaría el desastre **si hay un
  verificador que dependa del formato**. Con `pytest` como verificador, black no rompe nada y el
  rollback queda mudo pero inocuo. → **A MEDIAS.**
- **PROCESO §4.3**: es el que más apuesta por el rollback (es su respuesta a ROLLBACK-CONTRATO,
  que además dispara con cada flaky, A11). Restaura ficheros parcialmente, cree que restauró
  entero, y encima planta un **anticuerpo** basado en una atribución causal hecha sobre una
  trayectoria que no explica el cambio real. → **MUERE.**

---

## 4. La matriz

Filas = ataque. Columnas = diseño. **M** = MUERE, **½** = SOBREVIVE A MEDIAS, **S** = SOBREVIVE.

| # | Ataque | Ledger | Grafo | Proceso |
|---|---|---|---|---|
| **A0** | El reloj tampoco justifica la lobotomía (append incremental ya lo hace) | **½** | **M** | **M** |
| **A8** | `ok` es una regex de 120 chars, no un exit code (`tools.py:470`) | **M** | **M** | **½** |
| **A9** | El interceptor traga toda excepción: memoria apagada en silencio | **½** | **S** | **M** |
| **A1** | Deriva en el ciclo 40 de una tarea de 3 días | **M** | **½** | **½** |
| **A2** | Alucinación c7 → "hecho verificado" c9 → 300 ciclos | **M** | **M** | **M** |
| **A3** | Loop de dos ciclos alternos | **M** | **M** | **½** |
| **A4** | Estado corrupto a mitad de commit (kill / disco lleno / JSON truncado) | **½** | **S** | **½** |
| **A5** | El crítico comparte el error del principal | **½** | **M** | **S** |
| **A6** | El objetivo REAL cambia y la memoria inmutable lo impide | **M** | **½** | **M** |
| **A7** | El coste: verificar+rehidratar+comprimir contra trabajar | **M** (12–39%, sin tope) | **S** (6,2%, y el ahorro ES la enfermedad) | **S** (3,4–16%, aritmética honesta) |
| **A10** | El criterio no cabe: timeout 30 s / tope 600 s vs suite de 12 min | **M** | **½** | **½** |
| **A11** | Gate flaky al 50% contra monotonía y contradicción | **½** | **S** | **M** |
| **A12** | El pre-calentado destruye la caché que calienta | **M** (componente) | **M** (componente) | **S** |
| **A13** | Trazadores/`_presente` comprobados contra la propia proyección | **½** | **½** | **½** |
| **A14** | El rollback restaura la mitad del mundo (`checkpoints` sólo ve 4 tools) | **M** | **½** | **M** |
| | **Recuento** | **7 M · 6 ½ · 0 S** | **5 M · 5 ½ · 4 S** | **5 M · 6 ½ · 4 S** |

---

## 5. Lo que queda en pie después del ataque

**Ninguno de los tres sobrevive entero.** Pero no mueren por lo mismo, y las piezas que aguantan
no están repartidas por igual.

**Sobrevive intacto en los tres (y es el hallazgo compartido más sólido):**
la compresión sin LLM. 0,005–0,15 s contra 16,49 s medidos. Y la re-emisión **verbatim** de la
banda permanente: recall 1,000 contra 0,526 seleccionando. Esas dos decisiones son correctas y
están medidas.

**Sobrevive por diseño, en uno solo:**
- **Grafo**: SQLite/WAL como sustrato (A4 es el único ataque que ningún otro aguanta tan bien),
  el **tope duro de verificación** (1,5 s/ciclo, la única aritmética que no explota), y la
  transición `verificado → sospechoso → refutado` que absorbe los flaky sin daño (A11).
- **Proceso**: la **prueba 4** (preguntas de control con corrección por igualdad exacta) es la
  única forma correcta de meter al LLM en un gate que he visto en los tres documentos; la regla
  *"durante un ciclo nada se reescribe en la ventana"* (§5.2) es la única política de caché que
  respeta lo medido; y la §3.3 (*"el fuzzy se calcula, se muestra y no vota"*) es exactamente la
  decisión correcta sobre `canal._presente`.
- **Ledger**: la regla **C2** (un flaky es un bug de instrumento, no del agente) y la disciplina
  de **E0 / brazo nulo**, que es el único de los tres que se puso a sí mismo el experimento que
  puede matarlo.

**Lo que hay que arreglar antes de escribir una línea de cualquiera de los tres:**

1. **`run_tool` tiene que devolver el `returncode` real.** Mientras `ok` sea
   `not re.search(r"\bERROR\b", primera_linea[:120])`, la frase "la provenance la escribe la
   máquina" es falsa en los tres diseños y todo lo que se apoya en ella (`conf 1,00`,
   `autor=interceptor`, `prov.tipo=ejecutada`) es una etiqueta creíble sobre un dato inventado —
   que es literalmente el fallo que los tres dicen estar previniendo.
2. **La escritura de memoria no puede vivir dentro de un `except Exception: pass`.** El contrato
   del interceptor es "nunca lanza y degrada a no hacer nada", y eso es correcto para hooks y
   offloading; para el ledger convierte cada fallo de disco en un vacío silencioso. Necesita su
   propio canal con envelope, no el enchufe único.
3. **Un criterio no puede tardar más que el tope de la capa que lo ejecuta.** Hoy la suite de este
   repo (6.909 tests / 12 min) es inejecutable como criterio por las dos vías.
4. **Ningún diseño tiene detector de deriva que funcione.** El que funcionaría —exigir que cada
   ciclo declare a qué criterio congelado sirve y contar los ciclos estériles— está a un paso en
   proceso (banda Q) y a dos en grafo (`arista satisface`).
5. **El brazo nulo tiene que ser el experimento 1 de los tres, y tiene que ser el brazo nulo de la
   arquitectura entera**, no de un componente: ventana ancha, contrato verbatim re-emitido, nada
   más. Cuesta 0% de sobrecarga y ya midió recall 1,000. Ledger es el único que lo tiene así.

**El veredicto de una línea:** los tres diseños protegen bien lo que ya estaba medido
(restricciones verbatim, compresión sin LLM, crítico que no opina) y **ninguno protege la unión
entre una evidencia verdadera y la proposición que dice sostener** — que es por donde entra la
alucinación persistente (A2) en los tres, con tres nombres distintos y el mismo agujero.

---

*Adversario, 2026-08-19. Todo número viene de `medicion_kv.md` / `falsacion.md` o de una línea de
código citada con fichero y número. Lo que es predicción mía está dicho como predicción.*

# EL RESET COMO TRANSACCIÓN VERIFICADA

**Diseño de proceso para el agente de horizonte largo de Cognia.**
Lente: el reset es el momento peligroso → se trata como un COMMIT de base de datos.
Autor: arquitecto 3 (proceso/transacción). Fecha: 2026-08-19.
Todas las cifras vienen de `medicion_kv.md`, `falsacion.md`, `inventario_cognia.md` y `estado_del_arte.md` de esta misma carpeta. Cuando una cifra es mía y no medida, lo digo.

---

## 0. La tesis, y las tres cosas que la falsación me obliga a cambiar antes de empezar

**Tesis.** Destruir contexto es una operación destructiva sobre el único estado vivo del sistema. Ninguna base de datos permite eso sin protocolo. Por tanto: el estado sucesor se construye ANTES, se VERIFICA con pruebas objetivas contra el estado viejo mientras el viejo sigue vivo, y sólo si pasa se libera el contexto. Si no pasa: reintento acotado, o rollback, o **no resetear**.

La falsación mató tres supuestos del encargo original. El diseño los absorbe en vez de ignorarlos:

1. **La lobotomía NO ahorra VRAM.** 13 168 MiB @2 944 tok → 13 155 MiB @187 874 tok, 626 muestras, amplitud 21 MiB. El KV se reserva entero al cargar (`CUDA0 KV buffer size = 1792.00 MiB` en `0.00.793`, antes de `listening on`). **Consecuencia: prohibido justificar un solo componente de este diseño por VRAM.** El reset se justifica por dos cosas medidas y sólo por ellas: (a) el **reloj** — rehidratar 4k = 1,43 s frente a 27,3 s de un contexto de 64k; (b) la **higiene** — self-conditioning, Qwen3-32B cae de ~85 % a ~55 % de precisión en el turno 100 cuando el historial lleva 50 % de errores propios, y escalar el modelo no lo mitiga (arXiv:2509.09677).
2. **Comprimir con un LLM es caro y selectar es peor que no hacer nada.** 16,49 s por compactación; recall de restricciones: dejarlas en ventana a 111 406 tok = **1,000**, selección desde almacén inmutable = **0,526**, cascada = **0,083**. **Consecuencia: en este diseño no hay resumidor. La compresión es una función determinista y pura, sin LLM, y la banda permanente se re-emite VERBATIM.** Coste del "resumidor": 0 tokens, ~5 ms.
3. **Un crítico del mismo modelo está en el azar.** 0,517 / 0,523 de exactitud balanceada; el adjetivo del prompt mueve la detección 21×. **Consecuencia: en la ruta crítica del commit no hay ni una llamada de juicio.** El crítico EJECUTA: sha256, exit codes, substring literal, re-lectura de disco, igualdad de bytes. La única llamada al LLM que hay en el commit es una prueba de *lectura* con respuesta conocida y corrección por igualdad exacta, y su prefill es el mismo que la sesión siguiente iba a pagar de todos modos.

---

## 1. Arquitectura: LIBRO (event-sourcing) + PROYECCIÓN (CQRS) + COMMIT (2PC)

El patrón central existe y tiene nombre propio en bases de datos, no lo estoy inventando: **event sourcing + CQRS + two-phase commit + write-ahead log**. Lo novedoso es aplicarlo al contexto de un LLM y hacer que **el gate del commit sea un test de conservación**.

```
   ┌─────────────────────────────────────────────────────────────────┐
   │  LIBRO  (append-only, JSONL, en disco, LA VERDAD)               │
   │  ~/.cognia/tareas/<task_id>/libro.jsonl                         │
   └───────────────┬──────────────────────────────▲──────────────────┘
                   │ proyectar()  (pura, sin LLM) │ append (WAL)
                   ▼                              │
   ┌───────────────────────────┐      ┌───────────┴───────────────────┐
   │  PROYECCIÓN  ~3 050 tok   │      │ INTERCEPTOR (harness/         │
   │  bandas P T N D F A E Q   │      │ interceptor.py, ya existe)    │
   │  = el prompt del ciclo    │      │ toda tool escribe aquí        │
   └───────────┬───────────────┘      └───────────▲───────────────────┘
               │ es el system+user[0]             │
               ▼                                  │
   ┌───────────────────────────────────────────────┴──────────────────┐
   │  VENTANA VIVA (llama.cpp, 1 slot, ctx 32k)   = CACHÉ DESECHABLE  │
   └───────────────┬──────────────────────────────────────────────────┘
                   │ al disparador de reset
                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  COORDINADOR DE COMMIT (estado/commit.py, NUEVO)                 │
   │  PREPARE → 6 pruebas mecánicas → COMMIT → prueba 4 en la sesión  │
   │  nueva → OK  |  ABORT → reintento / MODO ANCHO / rollback        │
   └──────────────────────────────────────────────────────────────────┘
```

**Invariante fundacional:** la ventana es una **caché** del LIBRO. Destruirla es seguro **si y sólo si** es reconstruible. El commit es exactamente la prueba de esa reconstruibilidad, hecha antes de destruir.

**Segundo invariante:** `proyectar()` es una función **pura y determinista** del LIBRO. Mismo libro → misma salida byte a byte. Esto convierte "no hay resumen de resumen" en un **teorema estructural**, no en una disciplina: no existe ninguna operación que lea una proyección y escriba otra. La proyección se tira, nunca se re-comprime. El ciclo 500 proyecta desde los mismos eventos que el ciclo 1.

### 1.1 Componentes y responsabilidad

| # | Módulo | Estado | Responsabilidad |
|---|---|---|---|
| C1 | `cognia/estado/libro.py` | **NUEVO** (~320 líneas) | Ledger append-only JSONL, content-addressed, `append()`, `leer(hasta_tx=None)`, `fsync`, `sha_acumulado()`. Nada se reescribe jamás. |
| C2 | `cognia/estado/bandas.py` | **NUEVO** (~260 líneas) | `proyectar(libro, topes) -> (texto, mapa_tokens)`. Pura, sin LLM, sin red. Ordena por persistencia; banda P verbatim. |
| C3 | `cognia/estado/commit.py` | **NUEVO** (~340 líneas) | Coordinador 2PC: `preparar()`, `confirmar()`, `abortar()`, `rollback(tx)`. Emite el registro TX. |
| C4 | `cognia/verificador/ejecutor.py` | **NUEVO** (~280 líneas) | El crítico que NO opina: las 6 pruebas. Cero llamadas a LLM. |
| C5 | `cognia/estado/canal.py` | **EXISTE, 11 funciones huérfanas** | `anotar_restriccion/decision/pendiente`, `sembrar_trazadores`, `comprobar_trazadores`, **`conservacion()`**, `serializar/guardar/cargar`. Es el instrumento de conservación, ya escrito y testeado. Se conecta, no se reescribe. |
| C6 | `cognia/agent/horizonte.py` | **EXISTE, se modifica** | `ciclos_con_contrato` pasa de `_TECHO_CICLOS = 3` a techo por presupuesto; el delta `estado_tarea.resumen_para_prompt` (1200 chars) se sustituye por `bandas.proyectar`. |
| C7 | `cognia/harness/interceptor.py` | **EXISTE** | `antes()`/`despues()`: el enchufe único. Aquí se escribe cada evento al LIBRO con provenance y se detecta la acción huérfana. |
| C8 | `cognia/harness/limites.py` | **EXISTE, huérfano total** | `Presupuesto`, `Contador`, `LimiteExcedido`. Ejes segundos/tokens/pasos/USD = fin de tarea y disparador de ciclo. |
| C9 | `cognia/harness/contexto_vivo.py` | **EXISTE, `registrar_uso` con 0 llamadores** | Se cablea en `loop.py:1077` (que hoy lee `resp.usage.prompt_tokens` y lo tira). Da el disparador por saturación. |
| C10 | `cognia/estado/presupuesto_progreso.py` | **EXISTE, ON** | `pasos_sin_avance()`, `coste_sin_avance()`, `veredicto()`. Detección de loop y de tarea muerta. |
| C11 | `cognia/harness/checkpoints.py` | **EXISTE** | Blobs + `restaurar_hasta(n)`. Es el rollback **del mundo** (ficheros). El LIBRO es el rollback **del estado**. |
| C12 | `cognia/agent/rlm.py` (`ContextoVivo`, `ctx_grep`) | **EXISTE** | Recuperación bajo demanda: el LIBRO es el corpus, la búsqueda es grep por ID exacto, no embeddings. |
| C13 | `cognia/flujos/examen.py::verificar_postcondiciones` | **EXISTE** | Verificación ejecutable sobre workspace. Gate de fin de tarea. |
| C14 | `cognia/search/evidencia.py::verificar_cita` | **EXISTE** | Substring literal, sin juez. Es el validador de provenance `leida`. |
| C15 | `cognia/harness/oraculo.py` | **EXISTE** | Canal a **otro modelo/otra familia**, transporte inyectado. Único lugar donde se admite opinión de LLM, y **sólo asesora, nunca cierra un commit**. |
| C16 | `cognia/autopsia/causal.py` + `cognia/inmune/anticuerpos.py` | **EXISTE** | En ABORT: atribuir el paso culpable (precision@1 = 1,000 por replay contrafactual) y sintetizar el anticuerpo que veta esa llamada. |
| C17 | `cognia/agents/goal_contract.py::GoalContract` | **EXISTE** | 4 tipos de criterio: `file_exists`, `text_in_file`, `command_succeeds`, `text_present`. Sello de ciclo sobre evidencia de disco. |

### 1.2 Antipatrones activos, apagados explícitamente

`COGNIA_TX=1` desactiva por bandera y deja registro en el LIBRO:

- `memory/memory_compressor.py` — clustering que BORRA los originales = resumen-de-resumen. **OFF.**
- `memory/forgetting.py` — decay temporal aplicado a restricciones = governance decay. **OFF para bandas P y D.** (Una restricción no caduca por vieja; caduca porque un evento `amend` la deroga.)
- `memory/long_term_consolidator.py` — promueve a hecho del KG por repetición ≥3. Un agente que repite una invención tres veces la asciende a permanente. **OFF, sin excepción.** La frecuencia no es evidencia.
- `cli.py:3003 /compactar` — hoy sólo hace `_console.clear()` + repinta; no toca `_history`. Queda como está (cosmético) y se renombra en la ayuda a "limpiar pantalla" para que nadie crea que comprime.

---

## 2. FORMATO EXACTO DE LA MEMORIA

### 2.1 El LIBRO — `~/.cognia/tareas/<task_id>/libro.jsonl`

Una línea = un evento inmutable. Envoltura común:

```json
{"n":41,"ts":"2026-08-19T03:14:22.418Z","ciclo":7,"banda":"F","op":"add",
 "id":"F-0112","texto":"servir_flota.py arranca llama-server con --parallel 2",
 "prov":{"tipo":"leida","ruta":"cognia/flota.py","linea":88,
         "cita":"\"--parallel\", str(n_slots)","sha_fuente":"3f9a1c72e0"},
 "sha":"c81d4e2f9a03b7","prev":"7a0be1cc42d9f0"}
```

- `n` — ordinal monótono. `prev` — sha del evento anterior: el LIBRO es una cadena; romperla es detectable.
- `sha` — sha256 truncado a 14 hex de `{banda,op,id,texto,prov}` canonicalizado. Content-addressed → deduplicación gratis e idempotencia del append.
- `op ∈ {add, supersede, amend, invalidate, resolve, stale}`. **No existe `update` ni `delete`.**

### 2.2 Las siete bandas, ordenadas por PERSISTENCIA (la jerarquía que pidió el dueño)

| Banda | Qué | Ops permitidas | Tope tokens | Se re-emite… |
|---|---|---|---|---|
| **P** permanente | objetivo, restricciones, definición-de-hecho | `add` (sólo ciclo 0), `amend` (requiere evento humano o de contrato) | **400** | **VERBATIM, byte a byte, siempre** |
| **T** trazadores | canarios con ID aleatorio (`canal.sembrar_trazadores`) | `add` sólo ciclo 0 | **120** | verbatim |
| **N** negativos | lecciones de fallo, deduplicadas, en positivo | `add`, `supersede` | **300** | últimas 12 |
| **D** decisiones | decisiones tomadas, con su razón | `add`, `supersede` | **600** | últimas 20 vivas + "(N superadas)" |
| **F** hechos | hechos con provenance y estado | `add`, `invalidate`, `stale` | **750** | últimos 25 vigentes |
| **A** artefactos | ruta + sha256 + última verificación | `add`, `stale` | **540** | 30, criterio-críticos primero |
| **E** estado | posición actual + SOLO FALTA | **derivada, no almacenada** | **250** | recomputada de disco cada ciclo |
| **Q** control | 3 preguntas de control del commit | derivada | **90** | — |
| **X** charla | prosa, razonamiento, trazas de error crudas | — | **0** | **muere en el reset** |

**Total de la proyección: 3 050 tokens.** Encaja en el techo medido de "≤4k por agente si se quiere rotar (4 contextos calientes)".

**Matiz obligado por la falsación:** "charla descartable" es falso tal cual — *los comandos fallidos son la única señal no correlacionada que existe*. Por eso el fallo no se tira: se **destila mecánicamente** a banda N (`comando + exit + cola de 160 chars` → una línea "no funciona X porque Y"), y la **traza cruda** de error se queda en X y muere. Se conserva la lección, no la contaminación. Esto es exactamente lo que exige el hallazgo de self-conditioning: la lección positiva viaja, la traza de errores no.

### 2.3 Ejemplo real relleno (tarea real de este repo, ciclo 7 de 500)

`libro.jsonl` (extracto, 9 de 104 líneas):

```json
{"n":1,"ts":"2026-08-19T02:41:03.100Z","ciclo":0,"banda":"P","op":"add","id":"P-000","texto":"OBJETIVO: cablear el canal de estado de Cognia al bucle: las 11 funciones huerfanas de cognia/estado/canal.py deben tener llamador real y persistir entre ciclos.","prov":{"tipo":"dada","cita":"cablear el canal de estado","ref":"tarea#0"},"sha":"a01f3c9d7e2b41","prev":null}
{"n":2,"ts":"2026-08-19T02:41:03.104Z","ciclo":0,"banda":"P","op":"add","id":"P-001","texto":"RESTRICCION: usar SIEMPRE venv312\\Scripts\\python.exe.","prov":{"tipo":"dada","cita":"venv312","ref":"CLAUDE.md#12"},"sha":"5b7e0a41c9d3f8","prev":"a01f3c9d7e2b41"}
{"n":3,"ts":"2026-08-19T02:41:03.107Z","ciclo":0,"banda":"P","op":"add","id":"P-002","texto":"RESTRICCION: NUNCA reiniciar el backend :8080 (es el cerebro de Cognia y sirve a exp.py).","prov":{"tipo":"dada","cita":"no lo reinicie","ref":"medicion_kv.md#0"},"sha":"c3f8102aa7be55","prev":"5b7e0a41c9d3f8"}
{"n":4,"ts":"2026-08-19T02:41:03.111Z","ciclo":0,"banda":"P","op":"add","id":"P-003","texto":"DEFINICION DE HECHO: una funcion esta cableada si pytest -k canal pasa Y grep muestra un llamador fuera de tests/.","prov":{"tipo":"dada","cita":"llamador real","ref":"tarea#0"},"sha":"91ce4470bb2a08","prev":"c3f8102aa7be55"}
{"n":7,"ts":"2026-08-19T02:41:03.130Z","ciclo":0,"banda":"T","op":"add","id":"TRZ-4A9C31","texto":"el umbral acordado para TRZ-4A9C31 es 612","prov":{"tipo":"derivada","fn":"canal.sembrar_trazadores","semilla":19},"sha":"0d2b8fa1c37e90","prev":"..."}
{"n":58,"ts":"2026-08-19T03:02:17.882Z","ciclo":6,"banda":"D","op":"add","id":"D-011","texto":"anotar_restriccion se cablea en interceptor.despues y no en loop.py: interceptor es el enchufe unico y no obliga a tocar run_tool.","prov":{"tipo":"derivada","fn":"decision_agente","base":["F-0098","F-0101"]},"sha":"6e1a90c4d5f7b2","prev":"..."}
{"n":73,"ts":"2026-08-19T03:09:44.021Z","ciclo":7,"banda":"F","op":"add","id":"F-0119","texto":"canal.conservacion() devuelve recall_restricciones y recall_trazadores por separado.","prov":{"tipo":"leida","ruta":"cognia/estado/canal.py","linea":444,"cita":"\"recall_restricciones\": _r(vivos_r, len(restr))","sha_fuente":"e77a01b3"},"sha":"b4470ce9182daf","prev":"..."}
{"n":81,"ts":"2026-08-19T03:11:02.560Z","ciclo":7,"banda":"N","op":"add","id":"N-006","texto":"pytest -k canal desde la raiz NO recoge tests/estado/: hay que dar la ruta explicita.","prov":{"tipo":"ejecutada","cmd":"venv312\\Scripts\\python.exe -m pytest -k canal","exit":5,"cola":"no tests ran in 0.31s"},"sha":"2fa8b310cc47e1","prev":"..."}
{"n":88,"ts":"2026-08-19T03:12:40.903Z","ciclo":7,"banda":"A","op":"add","id":"A-004","texto":"cognia/estado/canal.py","prov":{"tipo":"ejecutada","cmd":"escribir_archivo","exit":0},"sha_art":"e77a01b3c4d980","bytes":22417,"mtime":1755573160.9,"verif_ciclo":7,"critico":true,"sha":"88f0a3b1e0c229","prev":"..."}
```

### 2.4 La PROYECCIÓN generada (esto es literalmente el prompt del ciclo 8)

```
=== P · PERMANENTE · sha 9f3c1a4e0b77d2 · NO PARAFRASEAR ===
OBJETIVO: cablear el canal de estado de Cognia al bucle: las 11 funciones
huerfanas de cognia/estado/canal.py deben tener llamador real y persistir
entre ciclos.
RESTRICCION P-001: usar SIEMPRE venv312\Scripts\python.exe.
RESTRICCION P-002: NUNCA reiniciar el backend :8080.
RESTRICCION P-003 (DEFINICION DE HECHO): una funcion esta cableada si
pytest -k canal pasa Y grep muestra un llamador fuera de tests/.
CRITERIOS CONGELADOS (GoalContract, 7):
  [x] 1 file_exists cognia/estado/libro.py
  [x] 2 text_in_file interceptor.py "anotar_restriccion"
  [ ] 3 command_succeeds "venv312\Scripts\python.exe -m pytest tests/estado -q"
  ... (4 mas)
=== T · TRAZADORES (6) ===
TRZ-4A9C31 umbral 612 · TRZ-B0E217 no tocar legado_TRZ-B0E217.py · ... (4 mas)
=== N · LO QUE NO FUNCIONA (12) ===
N-006 pytest -k canal desde la raiz no recoge tests/estado/: ruta explicita.
... (11 mas)
=== D · DECISIONES VIVAS (14, 3 superadas) ===
D-011 cablear en interceptor.despues, no en loop.py [base F-0098,F-0101]
... (13 mas)
=== F · HECHOS VIGENTES (25 de 119) ===
F-0119 conservacion() devuelve recall_restricciones y _trazadores por separado
       [leida canal.py:444 sha e77a01b3]
... (24 mas)
=== A · ARTEFACTOS (12, 12 verificados en ciclo 7) ===
A-004 cognia/estado/canal.py sha e77a01b3 22417B CRITICO ok
... (11 mas)
=== E · ESTADO (derivado de disco, ciclo 8) ===
SOLO FALTA: criterios 3,5,6,7. Pendiente P-1: falta llamador de
`conservacion` fuera de tests. Ultimo commit TX-0007 ok.
=== Q · RESPONDE ESTO ANTES DE ACTUAR (3) ===
Q1 ¿cual es el umbral acordado para TRZ-4A9C31?
Q2 ¿que interprete de Python hay que usar SIEMPRE?
Q3 ¿cual es la ruta del artefacto critico A-004?
```

Medido en el tokenizador del 9B: **3 050 ± 90 tokens**.

### 2.5 Provenance y confianza — la confianza es un TIPO, no un número

El hallazgo que obliga a esto: *"la confianza la emite el mismo modelo cuyo juicio está en el azar → hechos falsos con etiqueta creíble"*. Así que **el modelo no emite confianza nunca**. La confianza se **deriva del tipo de provenance**, y cada tipo tiene un re-verificador puro:

| `prov.tipo` | Significa | Re-verificador (puro, sin LLM) | ¿Puede entrar en P/D/F? |
|---|---|---|---|
| `dada` | literal del texto de la tarea o de CLAUDE.md | `cita in texto_tarea` | sí |
| `leida` | substring literal de un fichero con sha en t | `search/evidencia.verificar_cita(cita, open(ruta).read())` + `sha_fuente == sha_actual` | sí |
| `ejecutada` | salida de un comando con exit code | re-ejecutar el comando (opt-in) o comparar exit almacenado | sí |
| `derivada` | salida de una función determinista nombrada | re-llamar `fn` con `base` y comparar | sí |
| `dicha` | lo dijo el modelo | **ninguno** | **NO. Vive en X y muere en el reset.** |

**Ésa es toda la máquina anti-alucinación:** un hecho no puede escribirse en banda persistente si su autor no aporta una provenance que una función pura pueda re-comprobar. `interceptor.despues` es la puerta: un `add` a P/D/F/A sin `prov` re-comprobable se rechaza y vuelve como error de tool al modelo. No hay juez, no hay umbral, no hay adjetivo de prompt que lo mueva 21×.

**Alucinación persistente = un hecho `leida` cuyo fichero cambió.** Se detecta en la prueba 3 del commit (§3.2) y se degrada a `stale`; si no se re-lee en el ciclo siguiente, se `invalidate` y desaparece de la proyección. Un hecho falso no puede sobrevivir 2 commits sin que su fichero lo respalde.

---

## 3. EL PROTOCOLO DE COMMIT (el corazón del diseño)

### 3.1 Las dos fases, paso a paso

```
--- PREPARE (el contexto viejo SIGUE VIVO) --------------------------------
p0  quiesce: ninguna tool en vuelo; se espera a que la actual termine.
p1  flush WAL: toda observación pendiente del ciclo -> libro.append(), fsync.
p2  libro.append({"op":"prepare","ciclo":k,"sha_libro":H,"ckpt":m})   fsync
p3  proy_nueva = bandas.proyectar(libro)          # pura, ~5 ms, 0 tokens LLM
p4  verificador.ejecutar(pruebas 1,2,3,5,6, proy_nueva, contexto_vivo)  ~15 ms
p5  canal.conservacion(estado, proy_nueva)  -> recall_*   (asesor, ver §3.3)
    GATE: prueba1 ∧ prueba2 ∧ prueba3 ∧ prueba5 ∧ prueba6  (booleano puro)
    si falla -> ABORT-PREPARE (§4.1). NO SE DESTRUYE NADA.
--- COMMIT ----------------------------------------------------------------
c1  libro.append({"op":"commit","ciclo":k,"sha_proy":S,"tx":"TX-0007"})  fsync
c2  DESTRUIR: history = [system, proy_nueva]  (la caché KV de llama.cpp se
    invalida sola; no se libera ni un MiB de VRAM, y eso ya lo sabemos)
c3  primer turno de la sesión nueva = prueba 4: responder Q1..Q3 en un JSON
c4  corrección por igualdad exacta normalizada contra las respuestas del LIBRO
    si <3/3 -> ROLLBACK-POST (§4.2)
--- HECHO -----------------------------------------------------------------
    el ciclo k+1 sigue en esa misma ventana. La proyección NO se toca más
    durante el ciclo (regla de caché, §5.2).
```

### 3.2 Las seis pruebas del verificador que EJECUTA

Ninguna llama al LLM salvo la 4, y la 4 corrige por igualdad de cadenas.

| # | Prueba | Mecanismo exacto | Umbral | Coste |
|---|---|---|---|---|
| **1** | **Checksum de invariantes** | `sha256(render_banda_P(proy_nueva)) == sha_P0` congelado en ciclo 0. Igualdad de BYTES. | exacta | 0,4 ms |
| **2** | **Recall de trazadores** | `canal.comprobar_trazadores(estado, proy_nueva)`; los IDs son aleatorios y **no inferibles**: si aparecen es porque sobrevivieron, no porque el modelo los dedujo | **6/6 = 1,00** | 1 ms |
| **3** | **Re-lectura de artefactos** | por cada A: `mtime` cambió → `sha256(open(ruta,'rb').read())` vs `sha_art`. Los `critico:true` (los que sostienen un criterio) se leen **enteros siempre** | 100 % críticos, 0 mismatch silencioso | 3–40 ms |
| **4** | **Preguntas de control** | 3 preguntas cuya respuesta es una cadena literal del LIBRO, contestadas por la SESIÓN NUEVA, corregidas por `normalizar(resp)==normalizar(esperada)` | **3/3** | ~1,4 s (ver §3.4) |
| **5** | **Contradicción** | cada F nuevo tiene `clave` normalizada (sujeto+predicado). Dos F vigentes con misma `clave` y distinto valor → `CONTRADICCION` obligatoria: se fuerza `supersede` con provenance o se para | 0 contradicciones vivas | 2 ms |
| **6** | **Monotonía del contrato** | `GoalContract.check()` sobre evidencia de disco; el conjunto de criterios satisfechos **no puede encoger** | `satisfechos_k ⊇ satisfechos_{k-1}` | 5–300 ms |

### 3.3 La decisión de diseño más importante: **el gate usa sólo igualdad exacta**

`canal._presente()` usa cobertura de tokens normalizados con `UMBRAL_COBERTURA`. Una **paráfrasis puede puntuar "presente" con el ID perdido**. Por eso:

> **El gate del commit sólo admite pruebas de igualdad de bytes / de ID exacto / de exit code.** `canal.conservacion()` (fuzzy) se calcula, se registra y se **muestra**, pero **no vota**. Si recall_fuzzy = 0,92 y las 6 pruebas exactas pasan, se hace commit y se anota la discrepancia. Si el fuzzy pasa y una exacta falla, se aborta.

Es la respuesta directa a "¿y si la prueba de conservación es la que se equivoca?": una prueba difusa se equivoca en ambas direcciones y no lo sabes; una igualdad de bytes sólo puede equivocarse si tienes un bug, y ese bug es testeable (§9, mutación).

### 3.4 CUÁNTO CUESTA EL COMMIT (el ataque a mi propio diseño, con números)

| Partida | Coste | De dónde sale |
|---|---|---|
| Construir la proyección | **~5 ms** | Python puro sobre ~4,5 KB de JSONL/ciclo |
| Pruebas 1,2,5 | **~3 ms** | hashing y comparación de cadenas |
| Prueba 3 (artefactos) | **3–40 ms** | 12 `stat` + 2–3 lecturas completas |
| Prueba 6 (contrato) | **5–300 ms** | `command_succeeds` puede ser un pytest; se corre **una vez por commit**, no por paso |
| `fsync` × 2 | **~4 ms** | NVMe |
| **Prueba 4 (la única con LLM)** | **~1,4 s marginales** | Ver abajo |
| **TOTAL marginal** | **≈ 1,5 s** | |

**Por qué la prueba 4 es casi gratis:** su prefill son los 3 050 tokens de la proyección, **que el ciclo siguiente iba a pagar de todas formas** (medido: 4 022 tok = 1,43 s; réplicas <1,2 %). Lo único adicional es el decode del JSON de respuestas: ~80 tokens a 55–65 tok/s = **1,3 s**. Y ese decode no es puro coste: es la **recitación de evidencia** que la literatura mide en +4 % en RULER (arXiv:2510.05381). Es decir, la prueba de commit y la mitigación de degradación por longitud son **el mismo turno**.

**Contraste:** la falsación midió **16,49 s por compactación** con resumidor LLM. Mi commit cuesta **1,5 s: 11× menos**, porque el compresor no es un LLM.

**Overhead relativo:** un ciclo dura ~90 s de modelo (§5.3). 1,5 / 90 = **1,7 %**. A 500 ciclos: **12,5 minutos** de commit en ~12,5 horas de trabajo.

**El coste que sí duele y lo digo:** la prueba 6 con `command_succeeds "pytest -q"`. Si la suite tarda 40 s, el commit tarda 41,5 s y el overhead salta al **31 %**. Mitigación medida y honesta: la prueba 6 corre el pytest **sólo si la prueba 3 detectó que cambió algún artefacto crítico** desde el commit anterior; si nada cambió, el resultado anterior es válido por construcción (mismos bytes → mismo exit). Con eso el pytest cae de 1/ciclo a ~1/3 ciclos.

---

## 4. ROLLBACK Y ABORTOS

### 4.1 ABORT-PREPARE — el proyector perdió algo

Sólo puede ocurrir por una causa: **una banda desbordó su tope de tokens** (la proyección es determinista; si pierde algo es por el techo). Escalera de 3 escalones, en orden:

1. **`degradar_topes`** — se sube el tope de la banda culpable robando de N y de A (las de menor persistencia), se re-proyecta, se re-prueba. Máx. **2 reintentos**.
2. **MODO ANCHO** — se cancela el reset de este ciclo y se sigue en la misma ventana. Es una salida legítima, no un parche: la falsación midió recall **1,000** dejando las restricciones en ventana a 111 406 tokens, contra 0,526 seleccionando. El coste es el reloj (prefill de 64k = 27,3 s vs 1,43 s). **El sistema tiene que poder NO resetear.** Se registra `{"op":"modo_ancho","motivo":...}` y el contador `ciclos_anchos` es una métrica de salud.
3. **PARTIR LA TAREA** — si en 3 ciclos consecutivos no cabe, la tarea es demasiado grande para 3 050 tokens de estado. Se emite un `pendiente` de tipo `requiere_particion` y se paran los ciclos.

### 4.2 ROLLBACK-POST — la sesión nueva no sabe leer su propia memoria (Q < 3/3)

1. **Reintento con recitación**: se antepone un turno user `"recita literalmente estas 4 restricciones y estos 6 trazadores antes de actuar"` con el texto verbatim. Se repite la prueba 4. (Coste: +1,4 s.)
2. Si vuelve a fallar: **MODO ANCHO** un ciclo + `{"op":"deriva_de_proyeccion","q_fallada":...}` en el LIBRO. Tres de éstos en 20 ciclos → la proyección está mal diseñada para esta tarea; se para y se avisa al humano.

### 4.3 ROLLBACK-CONTRATO — un criterio ya satisfecho dejó de estarlo (prueba 6)

Es el caso grave: el ciclo rompió algo que ya funcionaba.

1. `autopsia.causal.atribuir(trayectoria_del_ciclo)` — replay contrafactual, precision@1 medida **1,000**. Devuelve el paso culpable.
2. `harness/checkpoints.restaurar_hasta(m)` con `m` = índice de checkpoint guardado en el registro `prepare`. Devuelve los **ficheros** al estado pre-ciclo, con blobs reales.
3. `inmune/anticuerpos` sintetiza el veto de esa llamada exacta (`ruta_de_args(tool, args)`), para que no se repita.
4. `libro.append({"op":"rollback","hasta_tx":"TX-0006","culpable":"paso#14","anticuerpo":"AB-021"})`.
5. Se re-proyecta **desde el LIBRO leído hasta TX-0006** y se reintenta el ciclo.

### 4.4 Qué significa "rollback" en un ledger append-only

**No se borra nada, nunca.** `rollback(tx)` = `bandas.proyectar(libro.leer(hasta_tx=tx))`. Es reproyectar un prefijo. Consecuencias:

- El rollback es **exacto** (no es "volver a un resumen más viejo", que sería resumen-de-resumen hacia atrás).
- El intento fallido **sigue siendo auditable**: los eventos siguen ahí, marcados como pertenecientes a una rama abortada.
- Es idempotente y no puede corromper: la operación sólo lee.
- Coste: 5 ms + relectura de un JSONL de ≤2,3 MB.

**Snapshots.** Un snapshot = `{registro TX} + {blob de la proyección} + {índice de checkpoint de ficheros}`. Proyección = 3 050 tok ≈ **12 KB de texto**; LIBRO ≈ **4,5 KB/ciclo**. A 500 ciclos: **6 MB de blobs (deduplicados por contenido, en la práctica ~2 MB) + 2,3 MB de ledger < 10 MB.** No hay ninguna razón para borrar nada, y eso es precisamente lo que hace el rollback exacto.

---

## 5. CICLO DE VIDA DE UNA TAREA, CON NÚMEROS

### 5.1 Fases

```
FASE 0  SIEMBRA (una vez, ~20 s)
  - se congela P: objetivo + restricciones + definicion-de-hecho, VERBATIM
  - GoalContract.from_spec(...) con 4 tipos: file_exists, text_in_file,
    command_succeeds, text_present. CRITERIOS CONGELADOS.
  - canal.sembrar_trazadores(estado, k=6, semilla=<task_id>) -> banda T
  - sha_P0 = sha256(render_banda_P). Es la constante del resto de la tarea.
  - checkpoints.nueva_sesion()
  - si NO hay criterios verificables -> se PARA y se pide al humano el
    criterio. (Hoy horizonte corre 1 ciclo mudo; eso es peor que parar.)

FASE 1..K  CICLOS (el bucle)
  rehidratar (1,43 s) -> prueba 4 (1,3 s) -> <=8 acciones -> commit (1,5 s)

FASE Ω  CIERRE
  triple confirmacion mecanica (§7) -> informe -> libro.append({"op":"cerrar"})
```

### 5.2 Regla de caché: **la proyección se escribe una vez y no se toca**

Medido: append puro sólo cuesta lo añadido (+3 000 → 3 018 procesados). Cambiar por dentro se paga entero: insertar una línea en mitad de 16k = **5 826 ms** contra **242 ms** (24×). Y el corte no es un porcentaje: es **distancia absoluta ~512 tokens** (95 % de prefijo común reusa, 90 % no).

Por tanto, regla dura del diseño:

> Durante un ciclo, **nada se reescribe en la ventana**. Las observaciones van al LIBRO (disco). Si el agente necesita algo que no está en la proyección, lo pide con `ctx_grep` y llega como turno nuevo **al final**. Cero invalidaciones de caché por ciclo.

Esto es la versión ejecutable de la conclusión medida *"Memoria al principio e inmutable; lo que cambia, al final"*, y es la razón por la que la banda E (lo único volátil) se recomputa **sólo en el commit**, no durante el ciclo.

### 5.3 Presupuesto de un ciclo

| Partida | Valor | Origen |
|---|---|---|
| Proyección inicial | 3 050 tok | §2.4, medido en tokenizador |
| Prefill de rehidratación | **1,43 s** | tabla medida: 4 022 tok = 1,43 s |
| Prueba 4 (decode) | 1,3 s | 80 tok @ 55–65 tok/s |
| Acciones por ciclo | **≤8** (objetivo 6) | H(0.5) ≈ 8 turnos para Gemma3-27B, 15 para Qwen3-32B (arXiv:2509.09677); el 9B es menor → 8 es techo, no meta |
| Crecimiento del contexto | 3,1k → ~12k tok | ~1,1k tok por paso (llamada+salida) |
| Prefill acumulado del ciclo | ~3,4 s | append puro: sólo lo añadido, 9k tok |
| Decode del ciclo | ~40 s | 8 × ~300 tok @ 60 tok/s |
| Tiempo de tools | 10–40 s | variable |
| **Commit** | **1,5 s (1,7 %)** | §3.4 |
| **Ciclo completo** | **~90 s** | |

**Cadencia de reset: cada ~90 s ⇒ ~40 ciclos/hora ⇒ 500 ciclos ≈ 12,5 h.** Justo el "horas o días" del encargo.

**Qué se ahorra realmente.** Sin reset, en el ciclo 40 el contexto sería 3k + 40×9k = **363k tokens**: no cabe ni en los 200 192 configurados. Y aunque cupiera, el ajuste medido `t(n)=0,33876·n + 1,377e-6·n²` ms da **2,05 min** para llenar la ventana entera una vez, y cada paso a 64k cuesta **27,3 s de prefill contra 1,43 s**. El reset no ahorra VRAM (0 MiB, medido); ahorra **el reloj**, y desinfecta.

### 5.4 Coste total de la memoria a 500 ciclos

- Compresión: **0 tokens de LLM** (proyector determinista). ~2,5 s de CPU en total.
- Recuperación: 500 × 3 050 = **1,53 M tokens de prefill** = 500 × 1,43 s = **11,9 min**.
- `ctx_grep` bajo demanda: ~2/ciclo × 150 tok = 150k tok ≈ 1 min.
- **Todo el subsistema de memoria: ~13 minutos en 12,5 horas = 1,7 %.**

---

## 6. CONDICIONES DE RESET, LOOPS Y DERIVA

### 6.1 Cuándo resetear: disparador ∧ compuerta

**Disparadores (cualquiera):**

| ID | Condición | Por qué |
|---|---|---|
| T1 | `acciones_en_ciclo ≥ 8` | horizonte multi-turno medido; más allá el modelo se auto-condiciona |
| T2 | `errores_consecutivos ≥ 2` | **el disparador más importante**: la contaminación es el motivo real del reset (85 %→55 %). Resetear pronto, no tarde |
| T3 | `contexto_vivo.estado()["ocupacion"] ≥ 0,55 · n_ctx_slot` | saturación, no reloj de pared. La falsación mató "compactar por ciclo" (137 min/día) frente a "por saturación" (19,8 min/día) |
| T4 | acaba de satisfacerse un criterio | frontera natural limpia: consolidar la victoria |

**Compuertas (todas obligatorias para destruir):** G1 ninguna tool en vuelo y WAL vacío; G2 las 5 pruebas de PREPARE en verde.

**Si el disparador salta y la compuerta no abre: NO se resetea.** Se sigue en MODO ANCHO. Resetear es opcional; **commitear no lo es** — el LIBRO se escribe siempre, resetee o no.

### 6.2 Loops — cuatro detectores, todos mecánicos

| ID | Detector | Umbral | Acción |
|---|---|---|---|
| **LOOP-A** | `sha256(conjunto ordenado de (tool, ruta_destino))` del ciclo + conjunto de criterios satisfechos | misma firma 2 ciclos seguidos sin criterio nuevo | banda N + prohibición de repetir ese conjunto; si se repite otra vez → fin de tarea `FALLO-LOOP` |
| **LOOP-B** | misma `(tool, ruta_destino, sha(args))` con **mismo sha de salida** | 3 veces en un ciclo | `anticuerpos` genera el veto en caliente; la 4ª llamada devuelve el veto como error |
| **LOOP-C** | oscilación: el sha de un fichero alterna A→B→A entre ciclos | 1 oscilación completa | se congela el fichero (anticuerpo) y se abre un `pendiente` para el humano |
| **LOOP-D** | `presupuesto_progreso.coste_sin_avance()` | > 3× `mediana_coste_por_avance` | `veredicto()` = agotado → fin de tarea `FALLO-ESTANCADO` |

Ninguno pregunta a un LLM si "parece que estoy en un bucle".

### 6.3 Pérdida del objetivo — el detector que ataca el 25 % plano

La falsación midió adherencia conductual **0,750 / 0,708 / 0,750** a 0,4k/32k/128k: **plana**. El incumplimiento no lo causa la profundidad, luego recordar más fuerte no lo arregla. Hay que **bloquear la acción**, no reforzar el recordatorio.

**Detector de acción huérfana** (en `interceptor.antes`, ya es el enchufe único):
`ruta_destino(name, args)` se compara contra el conjunto de rutas/entidades derivable de los criterios congelados + los `pendientes` abiertos. Sin correspondencia → la llamada se marca `HUERFANA` (se deja pasar, se cuenta).

- `huerfanas / total > 0,40` en un ciclo → **DERIVA**: el ciclo se aborta, se resetea con recitación de los criterios como primer turno, y se registra en el LIBRO.
- La banda P es byte-congelada (prueba 1), así que el objetivo **declarado** no puede derivar por construcción. Lo que se vigila es la conducta.
- Segundo detector: monotonía del contrato (prueba 6). Retroceso = deriva por definición.

---

## 7. FIN DE TAREA — cuatro salidas, todas mecánicas

La falsación señaló que faltaba el criterio de parada. Aquí está, explícito:

| Salida | Condición (toda mecánica, sin juez) |
|---|---|
| **ÉXITO** | (a) `GoalContract.check()` = todos los criterios; **y** (b) prueba 3 al 100 % sobre todos los artefactos (re-leídos de disco, no de memoria); **y** (c) `flujos/examen.verificar_postcondiciones` en verde sobre una **copia limpia del workspace**. Tres confirmaciones independientes. |
| **FALLO-PRESUPUESTO** | `limites.LimiteExcedido` en cualquier eje (segundos/tokens/pasos/USD). Excepción tipada, ya implementada. |
| **FALLO-ESTANCADO** | LOOP-D o LOOP-A repetido. |
| **BLOQUEADO** | un `pendiente` con `requiere_humano` (credencial ausente, decisión de producto, permiso). **Se para y se pregunta**, no se queman 400 ciclos adivinando. |

---

## 8. MULTIAGENTE, MODELOS Y VRAM

### 8.1 Protocolo entre agentes: el LIBRO es el único canal

Medido: el multiagente ahorra **0 MiB** y **cuesta** — cambiar de agente invalida la caché de prefijo, **10,68 s vs 0,28 s**. Y el +90,2 % de Anthropic se compra con **15× tokens**, donde el uso de tokens explica el 80 % de la varianza. Con 1 slot eso se paga en pared. Por tanto:

1. **Subagentes SECUENCIALES, nunca en paralelo** sobre el mismo backend.
2. **El prompt del subagente es un SUFIJO del prefijo del padre**: `[system][banda P][banda T] + <misión del subagente>`. Como P y T son byte-idénticas y la divergencia está en el último tramo, la caché de prefijo se reusa (medido: cabecera 16k + cola distinta = 242 ms vs 5 830 ms, **24×**). Los 10,68 s de cambio de agente bajan a **~0,3 s**.
3. **El subagente NO devuelve prosa.** Devuelve una lista de eventos de LIBRO con provenance. El padre hace `append`, sin fusionar y sin resumir. Reutiliza `delegar_subtarea` (roles acotados en `agent/tools.py:153`, hoy devuelve 600 chars) cambiando el formato de retorno a eventos.
4. **Un solo escritor**: sólo el proceso padre hace `append`. Es la única cosa en la que Anthropic y Cognition coinciden.
5. El contexto del subagente **muere al volver**, y no queda rastro suyo en la ventana del padre: sólo sus eventos, en el LIBRO.

### 8.2 El crítico de otra familia

En el commit el crítico **ejecuta y no opina**, así que no necesita modelo. Pero para el trabajo *creativo* (¿este diseño es razonable?) hay un canal: `harness/oraculo.py`, transporte inyectado, ya construido. Reglas:

- **Otra familia** (la lección "Cognia era mono-familia (Qwen)" es de esta casa: el primer modelo de otra familia destapó 3 fallos silenciosos).
- **Modo comparativo A vs B**, nunca puntuación absoluta. La literatura predice absoluto ≈ azar, comparativo > azar.
- **Asesor: su salida entra al LIBRO como banda D con `prov.tipo="dicha"`… y `dicha` no puede entrar en D.** Así que entra como **`pendiente`**: "el oráculo sugiere X, verificar". Sólo se convierte en decisión cuando algo ejecutable la respalda.

### 8.3 VRAM — la estrategia honesta

**El reset aporta 0 MiB. Punto.** Lo que sí decide la VRAM es la configuración de arranque:

| Config | KV | SSM | Pesos | Total | Nota |
|---|---|---|---|---|---|
| Hoy: `--ctx-size 200192 --parallel 1` | 6 256 MiB | 50 | 5 358 | **13 155** ✓ nvidia-smi | regala 5,2 GB para una ventana que este diseño nunca usa |
| **Propuesta: `--ctx-size 32768 --parallel 2`** | 2×512 = 1 024 | 100 | 5 358 | **≈ 7,5 GB** | 2 slots de 16k; cada slot con caché propia (no se desalojan) |

Con ~8 GB libres cabe **un modelo de otra familia** para el oráculo — que es exactamente lo que el estado del arte exige y lo que hoy no se puede tener. **Ése es el uso de la VRAM liberada: comprar el crítico externo, no "ahorrar".**

Reglas duras:
- Fórmula validada 6/6: `bytes/token = capas_ATENCIÓN × n_head_kv × (k_len+v_len) × bytes_elem`. **El 9B tiene 8 capas de atención de 33 bloques (es híbrido, `qwen35`)**: calcular con `n_layer=33` se equivoca **4×**.
- **Todo cambio de `--ctx-size` se valida con delta de `nvidia-smi` contra la fórmula**, porque en ctx=16384 pidió 1 792 MiB y la VRAM subió 2 582: desbordó a RAM compartida de Windows **sin ningún error**, con CUDA reportando "14987 MiB free".
- **No usar KV q8_0** hasta medir calidad. Ahorra 17 KiB/tok frente a 32, pero **no se midió calidad** y este diseño no acepta cifras no medidas.
- Rotación de contextos calientes: medido `min(4 estados, ~1 GiB)`, y el acierto cae **de golpe** (4×2k → 4/4; 5×2k → 0/5). Mi proyección de 3 050 tok deja margen para **4 agentes calientes**; con 8k sólo caben 2. Es otra razón del tope de 3k.

---

## 9. EVALUACIÓN EXPERIMENTAL (pregunta 18) — y el test de mutación del propio commit

Cuatro experimentos, todos corribles en esta máquina, cada uno con **brazo nulo** y **métrica primaria** declarada antes.

| Exp | Pregunta | Diseño | Métrica primaria | Predicción |
|---|---|---|---|---|
| **E1** | ¿el commit conserva? | 20 tareas × 40 ciclos. Brazos: (a) sin reset (modo ancho), (b) reset sin commit (horizonte actual), (c) reset con commit. **Intercalados**, n≥6/brazo | recall de trazadores a 40 ciclos, medido con `canal.comprobar_trazadores` | (a) 1,00 / (b) ≤0,53 / (c) 1,00 con 1/9 del reloj de (a) |
| **E2** | ¿el gate rechaza algo? **MUTACIÓN** | cada 25 ciclos se corrompe la proyección a propósito: se borra 1 restricción, o se cambia 1 dígito de un trazador, o se falsea 1 sha de artefacto | `tasa_de_deteccion` de la corrupción | **debe ser 1,00**. Si un commit lleva 50 ciclos sin abortar nunca y la mutación no lo despierta, **el gate está roto** |
| **E3** | ¿el crítico ejecutable bate al que opina? | 43 salidas erróneas + 60 correctas ya recogidas en la falsación. Brazos: juez 9B absoluto / juez 9B comparativo / verificador que ejecuta | exactitud balanceada | absoluto ≈ 0,52 (ya medido); ejecutable ≈ 0,68+ (ya medido, a 38× coste); comparativo, incógnita — **es el experimento barato de una tarde** |
| **E4** | ¿cuántos ciclos aguanta? | 1 tarea real, 500 ciclos, sin intervención | criterios satisfechos vs ciclo; `ciclos_anchos`; `tasa_de_abort`; recall de F más antiguos | la curva de F viejos es donde predigo que me rompo (§11.1) |

**Instrumentación permanente** (se muestra en `/tx estado`): `tasa_de_abort`, `ciclos_anchos`, `q_fallidas`, `huerfanas_pct`, `contradicciones_forzadas`, `stale_detectados`. Un cero perpetuo en cualquiera de ellas es sospechoso, no sano.

---

## 10. CÓMO SE TECLEA EN EL CLI

Opt-in `COGNIA_TX=1`, igual que `COGNIA_HORIZONTE=1`. Comandos nuevos en la tabla de `cli.py:2035` y en el despacho junto a `cli.py:9532`.

```
/tx iniciar "cablear el canal de estado al bucle" --ciclos 500 --horas 12
/tx estado
/tx libro 20
/tx probar              # corre las 6 pruebas AHORA contra el contexto vivo
/tx commit              # fuerza un commit ya, imprime la tabla de pruebas
/tx rollback TX-0006
/tx mutar               # E2: corrompe a propósito y exige que el gate aborte
/tx bandas              # tokens por banda y qué se está cayendo por el tope
```

`/tx estado` imprime:

```
╭─ TX · tarea cablear-canal-estado · ciclo 41/500 ────────────────────────╮
│ P sha 9f3c1a4e0b77d2  CONGELADA desde ciclo 0    ✓                      │
│ bandas  P 400 · T 118 · N 287 · D 594 · F 742 · A 531 · E 236 · Q 88    │
│         total 2 996 / 3 050 tok        (F recorta 94 de 119 hechos ⚠)   │
│ criterios  ████████░░░░  4/7      artefactos 12/12 verificados          │
│ pruebas    1✓ 2✓(6/6) 3✓ 4✓(3/3) 5✓ 6✓        commit 1,4 s              │
│ salud   abortos 3 · anchos 1 · Q fallidas 2 · huerfanas 11% · stale 4   │
│ reloj   11,2 h · 41 ciclos · 1,49 M tok · rehidratacion media 1,44 s    │
╰────────────────────────────────────────────────────────────────────────╯
```

Y en cada ciclo, **una sola línea**:

```
⛓ ciclo 41 COMMIT TX-0041 ok · P 9f3c1a · trz 6/6 · art 12/12 · Q 3/3 · crit 4/7 · 1,4 s · ctx 3,0k→11,8k
⛓ ciclo 42 ABORT prueba 3: A-004 canal.py sha e77a01b3→b91c4402 · re-leo y reintento
```

---

## 11. LAS 18 PREGUNTAS, RESPONDIDAS CON MECANISMO

| # | Pregunta | Respuesta |
|---|---|---|
| 1 | qué es sólido | Destruir contexto **como higiene** (self-conditioning: 85→55 % con historial sucio, no lo arregla escalar) y **como reloj** (1,43 s vs 27,3 s). La jerarquía por persistencia. Reconstruir desde disco. |
| 2 | qué fallará | El ahorro de VRAM (0 MiB, refutado). El crítico LLM (0,517). La compresión por selección (0,526 vs 1,000). El resumen encadenado (0,083 en un paso). La "confianza" emitida por el modelo. |
| 3 | tras cientos/miles de ciclos | Banda P intacta por construcción (checksum). Bandas F y A **saturan hacia el ciclo ~120** y ahí empieza la selección → §11.1. LIBRO <10 MB a 500 ciclos. |
| 4 | evitar degradación de memoria | La proyección es función **pura del ledger append-only**: no existe operación resumen→resumen. El ciclo 500 proyecta desde los mismos eventos que el 1. Teorema, no disciplina. |
| 5 | alucinaciones persistentes | Un hecho persistente exige provenance re-comprobable; `dicha` está prohibida en P/D/F. La prueba 3 re-lee el disco cada commit: un `leida` cuyo sha cambió pasa a `stale`, y si no se re-lee, `invalidate`. **No sobrevive 2 commits.** |
| 6 | que el crítico no valide errores | En la ruta crítica no hay crítico que opine: sha256, exit codes, substring literal, igualdad de bytes. El LLM sólo contesta 3 preguntas con respuesta conocida, corregidas por igualdad. El opinador (`oraculo`, otra familia, comparativo) sólo genera `pendientes`. |
| 7 | loops infinitos | LOOP-A/B/C/D (§6.2), los cuatro mecánicos, más `limites.Presupuesto` como techo duro. |
| 8 | pérdida del objetivo | P byte-congelada (prueba 1) + **acciones huérfanas >40 %** = DERIVA + monotonía del contrato (prueba 6). Se bloquea la acción, no se refuerza el recordatorio: la adherencia es plana en 0,75, recordar más no la mueve. |
| 9 | cuándo resetear | T1 8 acciones ∨ T2 2 errores ∨ T3 55 % de ocupación ∨ T4 criterio satisfecho, **∧** compuertas G1/G2. Si la compuerta no abre: MODO ANCHO. |
| 10 | cuánto guarda un snapshot | Proyección 3 050 tok ≈ 12 KB + registro TX + índice de checkpoint. LIBRO 4,5 KB/ciclo. <10 MB a 500 ciclos, deduplicado. |
| 11 | estructura de la memoria | 7 bandas por persistencia (§2.2): P T N D F A E, más X que muere. |
| 12 | provenance y confianza | Confianza = **tipo derivado de la provenance**, con re-verificador puro por tipo (§2.5). El modelo nunca emite un número de confianza. |
| 13 | coordinar agentes | Secuenciales; prompt = sufijo del prefijo del padre (caché 24×); retorno en eventos, no prosa; un solo escritor; contextos mueren al volver (§8.1). |
| 14 | minimizar VRAM | Sinceramente: **el reset no la toca**. Se minimiza en el arranque: `--ctx-size 32768 --parallel 2` → 13,2 GB → 7,5 GB, y los 5,6 GB liberados **compran el crítico de otra familia**. Validar con `nvidia-smi` vs fórmula (Windows desborda sin avisar). |
| 15 | tokens de compresión y recuperación | Compresión: **0 tokens de LLM**, ~5 ms. Recuperación: 3 050 tok/ciclo = 1,43 s. Total del subsistema a 500 ciclos: **~13 min sobre 12,5 h (1,7 %)**. |
| 16 | recuperarse de estado corrupto | El ledger encadena `prev`: una cadena rota es detectable. La recuperación es reproyectar el prefijo válido más largo. La prueba 5 fuerza `supersede` ante contradicción; la 3 marca `stale`; la 6 detecta regresión. |
| 17 | rollback | `bandas.proyectar(libro.leer(hasta_tx=n))` para el estado (5 ms, exacto, no destructivo) + `checkpoints.restaurar_hasta(m)` para los ficheros (blobs reales, ya implementado). |
| 18 | evaluación experimental | E1–E4 (§9), con brazos nulos, intercalado y n≥6, más **mutación permanente del gate**. |

---

## 12. COMPARACIÓN HONESTA CON EL ESTADO DEL ARTE

| Familia | Qué toma este diseño | Qué rechaza, y por qué |
|---|---|---|
| **Context compression** | nada de compresión aprendida | la compresión aquí es proyección determinista; comprimir con LLM costó 16,49 s y bajó recall a 0,526 |
| **Summarization memory** | — | **rechazada de raíz**: no existe operación resumen→resumen. Cascada medida: 24→2 restricciones en UN paso (91,7 %) |
| **Recurrent memory (RMT/Titans)** | el **teorema**: un estado pequeño y de tamaño fijo sostiene millones de tokens | el sustrato: los 11,1 M de RMT son GPT-2 fine-tuneado en BABILong; no hay checkpoint de 27B instruido. Aquí el estado recurrente es **texto inspeccionable**, no un vector |
| **External memory (MemGPT)** | disco como verdad, ventana como caché | la auto-gestión por el propio LLM: el modelo decide *qué* leer, nunca *qué es verdad* |
| **RAG** | recuperación bajo demanda vía `ctx_grep` | embeddings: la recuperación es por **ID exacto y grep literal**, porque el gate exige igualdad exacta |
| **Episodic memory** | el LIBRO es literalmente episódico y con timestamp | la promoción por repetición (`long_term_consolidator` ≥3): la frecuencia no es evidencia |
| **Hierarchical memory** | la jerarquía por **persistencia**, no por recencia | el decay temporal sobre restricciones (`forgetting`) = governance decay |
| **Agentic workflows** | subagentes secuenciales como aislamiento | los paralelos: +90,2 % a costa de 15× tokens, y con 1 slot eso es pared |
| **Reflection** | — | rechazada como gate: la auto-crítica del mismo modelo está en 0,517 y falla justo donde el modelo está más incierto |
| **Verifier models** | **el verificador que EJECUTA** (única variante que sube: 0,681) | el verificador que puntúa. ≤13B sólo gana con verificador GPT-4 |
| **State-space** | el modelo ya es híbrido SSM (24 SSM + 8 atención); el estado SSM es 50,25 MiB constante por secuencia | nada: es sustrato, no diseño |
| **Zep / temporal validity** | **invalidar en vez de reescribir** — es la pieza que hace imposible el resumen-de-resumen | sus números: LoCoMo usa 16k–26k tokens (cabe entero en ventana) y las cifras están disputadas entre vendedores (75,14 vs 65,99; 84 → 58,44) |
| **Sleep-time compute** | el commit **pre-computa lo que el ciclo siguiente necesita** (banda E derivada, preguntas Q, artefactos re-leídos) en vez de resumir el pasado | — |
| **Anthropic compact + re-read** | compactar y **releer de disco** (git log, progress file, lista JSON pass/fail) | — es el mismo patrón; aquí formalizado como transacción |

**Qué es novedoso de verdad (y sólo esto):**

1. **El reset como 2PC con un test de conservación como gate.** Nadie publica "no destruyas hasta que el sucesor demuestre que conserva". Todo el mundo compacta y reza.
2. **Trazadores como canarios del commit** — needle-in-a-haystack aplicado a la transacción, con IDs no inferibles, de modo que "presente" no puede confundirse con "reconstruible".
3. **Confianza como TIPO derivado de la provenance**, con re-verificador puro por tipo, en vez de un número emitido por el modelo.
4. **La proyección como función pura de un ledger append-only** (event sourcing + CQRS aplicado al contexto): convierte "sin resumen-de-resumen" en propiedad estructural.
5. **La mutación del gate como instrumentación permanente**: un commit que nunca ha rechazado nada se declara roto.

**Qué ya tiene nombre propio:** WAL, 2PC, event sourcing, CQRS, content-addressed storage, temporal validity (Zep), sleep-time compute, MemGPT, self-consistency, execution-based verification.

**La combinación más potente:** *ledger append-only + proyección determinista + banda permanente verbatim + verificador que ejecuta + reset disparado por contaminación y **gateado** por conservación + modo ancho como salida legítima.* La pieza que más aporta por sí sola, según lo medido, es **re-emitir el contrato verbatim** (400 tokens = 0,17 s de prefill, recall 1,000). Todo lo demás protege eso.

---

## 13. CÓMO ME ROMPO — los 3 modos de fallo más probables tras 500 ciclos

### 11.1 · La banda que crece sin techo: F y A empiezan a **seleccionar**, y seleccionar es 0,526

Saqué la selección de la banda P (verbatim, checksum) porque ahí está medido que hace daño. Pero **F y A no pueden ser verbatim**: a 500 ciclos hay ~2 500 hechos y ~400 artefactos, y el tope es 750 y 540 tokens. A partir de ~15 hechos/ciclo, hacia el **ciclo 120**, el proyector empieza a recortar.

El fallo es silencioso y elegante, que es lo peor: las pruebas 1, 2, 4 y 6 **siguen en verde**, porque Q se saca de P y de T, que son eternos. El agente empieza a **re-derivar cosas que ya sabía** — vuelve a leer el mismo fichero, vuelve a descubrir la misma incompatibilidad, vuelve a probar la vía que ya descartó en el ciclo 30. El coste sube y el veredicto de `presupuesto_progreso` se degrada, pero nadie sabe por qué.

**Lo que haré para que salte:** las preguntas de control se **muestrean también de F y A, ponderando los eventos MÁS ANTIGUOS** (los que primero caen del tope). Y `/tx bandas` reporta `hechos_recortados` explícitamente — la línea `F recorta 94 de 119 hechos ⚠` del panel ya está puesta para eso.
**Riesgo residual que no cierro:** eso convierte la prueba 4 en el único detector real, y la prueba 4 depende de que el proyector elija bien a quién preguntar. Es decir, el detector comparte el sesgo del sistema que vigila. Sé que esto no está resuelto.

### 11.2 · El commit que siempre pasa: 4 de 6 pruebas se vuelven teatro

Las pruebas 1, 2, 5 y 6 son funciones deterministas de una proyección que es función determinista de un ledger que sólo crece. **Sólo pueden fallar si tengo un bug.** Predicción concreta: hacia el ciclo 30 dejan de fallar para siempre, y a partir de ahí su luz verde se usa como prueba de salud del sistema. Es exactamente *"el test que pasa por el motivo equivocado"*: cinco instrumentos aprobaron algo roto en una noche y ninguno falló.

Peor todavía: cuando la prueba de conservación se equivoque, se equivocará **hacia el verde**. `canal._presente()` usa cobertura de tokens con umbral: una paráfrasis puntúa "presente" con el ID perdido. Por eso el gate sólo admite igualdad exacta y el fuzzy no vota (§3.3) — pero eso desplaza el problema, no lo elimina: si mi `render_banda_P` tiene un bug de normalización (un `\r\n` que se cuela), `sha_P0` cambia y **abortaré para siempre** sin motivo, hasta que alguien lo mire.

**Lo que haré:** `/tx mutar` cada 25 ciclos, con `tasa_de_deteccion` obligatoria = 1,00, y una alarma dura: **`tasa_de_abort == 0` durante 50 ciclos se reporta como AVERÍA DEL GATE, no como salud.**
**Riesgo residual:** la mutación prueba las corrupciones que yo se me ocurrieron. La que me mate será otra.

### 11.3 · La deriva del mundo contra el LIBRO: provenance que dice `leida` y miente

La banda A guarda `ruta + sha256`. En 12,5 horas y 500 ciclos, procesos externos tocan ficheros: builds, formateadores, el propio dueño, un `git checkout`. La prueba 3 lo detecta… si lee. Pero 400 artefactos × 500 commits = 200 000 lecturas completas, así que **voy a muestrear por `mtime`** y leer entero sólo los `critico:true`.

En cuanto muestreo, se abre la grieta: un artefacto **no crítico** cambia con un `mtime` que no se movió (lo hay: `git checkout` de un blob idéntico en tamaño, algunos filesystems, copias con `-p`), y todos los hechos `derivada` que se apoyan en él siguen vigentes **con una etiqueta de provenance impecable**. Es la peor corrupción posible en mi diseño, porque el sistema entero está construido sobre "la provenance no miente": un `dicha` disfrazado es visible, un `leida` falso es invisible.

**Lo que haré:** `mtime + size` como filtro barato y sha completo cuando cualquiera de los dos se mueva; 100 % de sha en los artefactos crítico-de-criterio en cada commit; y un **barrido completo cada 25 ciclos** (400 lecturas ≈ 0,4 s, es asumible) que re-verifica todo y cuenta `stale_detectados`.
**Riesgo residual que no cierro:** entre dos barridos pueden pasar 25 ciclos ≈ 37 minutos de trabajo apoyado en un hecho falso bien etiquetado. Y si el artefacto corrupto es una **dependencia de otro fichero** (un import, un JSON de config) su propio sha no cambia y no lo veo en absoluto. Contra eso, la única defensa real que tengo es la (c) del criterio de ÉXITO: verificar postcondiciones sobre una **copia limpia del workspace** al final. Eso descubre el desastre; no lo previene.

---

*Fin. Todo lo afirmado con número viene de las mediciones de esta carpeta; lo que es mío y no está medido está marcado como predicción.*

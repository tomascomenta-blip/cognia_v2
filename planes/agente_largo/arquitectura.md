# ARQUITECTURA — decisión del arquitecto jefe

**Fecha:** 2026-08-19. Entrada: `medicion_kv.md`, `inventario_cognia.md`, `estado_del_arte.md`,
`falsacion.md`, `diseno_ledger.md`, `diseno_grafo.md`, `diseno_proceso.md`.
**Salida:** un esqueleto ganador, tres injertos, cuatro correcciones a los tres diseños, y las
condiciones que lo matan.

---

## 0. La decisión, en una línea

> **Gana `diseno_proceso.md`: el reset es un COMMIT de dos fases con un test de conservación como
> compuerta.** Sobre el sustrato de `diseno_ledger.md` (libro append-only + proyección pura) y con el
> ascenso epistémico de `diseno_grafo.md` (**control negativo del verificador**) injertado.

La razón es una sola y está medida. Los tres diseños hacen imposible la degradación **en el almacén**
(append-only, nada se reescribe). Pero la pérdida que `falsacion.md` midió — **24 → 2 restricciones en
UN paso, 91,7 %, y después punto fijo byte a byte** — no ocurrió en el almacén: ocurrió en la
**transferencia**, en el instante de reconstruir el estado sucesor. Y después fue perfectamente
estable e invisible, que es la firma exacta del vacío silencioso.

- `diseno_ledger.md` pone su compuerta (`gate.py`, recall de restricciones) **al arrancar el ciclo
  nuevo**, o sea **después de destruir**. Si falla, la única salida que le queda es abortar la tarea.
- `diseno_grafo.md` pone `gate_presencia` en el mismo sitio: reconstruye la cabecera y, al segundo
  fallo, para.
- `diseno_proceso.md` pone la misma comprobación **antes de destruir**, con el contexto viejo vivo. Si
  falla, la salida no es abortar: es **no resetear** (MODO ANCHO) y seguir trabajando.

Esa diferencia de posición es la que decide, porque el brazo "no hacer nada" es el que midió
**recall 1,000** (restricciones verbatim en ventana a 111 406 tokens) frente a **0,526** de cualquier
selección y **0,083** de la cascada. Un diseño cuyo modo de fallo es *caer al brazo que midió 1,000*
domina a uno cuyo modo de fallo es *matar la tarea*. `falsacion.md` lo dijo entero: *la maquinaria
empeora entre 2× y 12× exactamente lo que dice proteger*. La única defensa arquitectónica contra eso
es **poder apagar la maquinaria en caliente, por ciclo, sin perder el trabajo**. Sólo el esqueleto de
proceso puede.

Segundo motivo, del mismo peso: el instrumento que decide aquí es código que yo escribo, y la lección
más cara del proyecto es *«cinco instrumentos aprobaron algo roto en una noche; ninguno falló»*.
`diseno_proceso.md` es el único de los tres que **somete su propia compuerta a mutación permanente**
(`/tx mutar` cada 25 ciclos, tasa de detección obligatoria 1,000) y declara que
**`tasa_de_abort == 0` durante 50 ciclos es AVERÍA DEL GATE, no salud**. Los otros dos escriben la
compuerta y confían en ella.

---

## 1. Diagrama de componentes

```
                      ┌──────────────────────────────────────────────────────────┐
  TECLADO  ──/tx────► │ DRIVER  cognia/tx/driver.py   (parchea agent/horizonte)  │
                      └───────────┬──────────────────────────────────────────────┘
                                  │  UN SOLO ESCRITOR
  ┌───────────────────────────────▼──────────────────────────────────────────────┐
  │ LIBRO   ~/.cognia/tareas/<id>/libro.jsonl   append-only, cadena prev-sha      │
  │ 15 tipos de evento · provenance ESCRITA POR LA MÁQUINA · no existe delete     │
  └───────┬─────────────────────────────────────────────────────▲────────────────┘
          │ proyectar()  PURA, sin LLM, sin red, ~5–150 ms       │ append + fsync
          ▼                                                      │
  ┌───────────────────────────────────┐        ┌─────────────────┴──────────────┐
  │ PROYECCIÓN  3.050 tok             │        │ INTERCEPTOR harness/interceptor│
  │ P T N D F A │ E Q                 │        │ antes()/despues() = ENCHUFE    │
  │ render GENERACIONAL (§4.3):       │        │ ÚNICO. sha de disco, exit real,│
  │ prefijo byte-estable entre ciclos │        │ ruta_destino(). El modelo NO    │
  └───────┬───────────────────────────┘        │ toca ni un campo de provenance │
          │ = system + user[0] del ciclo       └─────────────────▲──────────────┘
          ▼                                                      │ toda tool
  ┌───────────────────────────────────────────────────────────────┴─────────────┐
  │ VENTANA VIVA  llama-server :8080  slot 0 · n_ctx_slot 32.768 · CACHÉ         │
  │ el ciclo crece 3,0k → ~12k tok en ≤8 acciones. Es desechable por definición  │
  └───────┬─────────────────────────────────────────────────────────────────────┘
          │ dispara T1 (8 acciones) ∨ T2 (2 errores) ∨ T3 (18k tok) ∨ T4 (criterio)
          ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ COMMIT 2PC   cognia/tx/commit.py                                            │
  │  PREPARE  (el contexto viejo SIGUE VIVO)                    ~50 ms          │
  │    G1 sha(banda P) == sha_P0          · igualdad de BYTES                   │
  │    G2 trazadores 6/6                  · canal.comprobar_trazadores          │
  │    G3 sha de artefactos               · críticos 100 %, resto mtime+size     │
  │    G4 0 contradicciones vivas         · GROUP BY clave (vocabulario cerrado) │
  │    G5 monotonía del contrato          · GoalContract, proceso aparte, cwd=ws │
  │    G6 el ciclo NO fue mudo            · ≥1 evento medido                     │
  │    G7 ningún `verificado` sin examen  · examen_ok=1 (control negativo)       │
  │    fallo → escalera: robar topes (≤2) → MODO ANCHO (≤3) → HARD_STOP          │
  │  COMMIT                                                                     │
  │    destruir ventana → Q1..Q3 en la sesión NUEVA, igualdad exacta normalizada │
  │    Q<3/3 → recitación verbatim y reintento → MODO ANCHO. NUNCA mata la tarea │
  └───────┬─────────────────────────────────────────────────────────────────────┘
          │ slot 1 (--parallel 2): crítico COMPARATIVO / oráculo / precalentado
          ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ ROLLBACK   proyectar(libro.leer(hasta_tx))   ·  exacto, 5 ms, no destructivo │
  │           + harness/checkpoints.restaurar_hasta(m)   ·  los ficheros         │
  │ AUTOPSIA   autopsia/causal.atribuir (precision@1 = 1,000 por replay)         │
  │           → inmune/anticuerpos.sintetizar() → veto ejecutable en interceptor │
  └─────────────────────────────────────────────────────────────────────────────┘
```

**Invariante fundacional:** la ventana es una **caché** del LIBRO. Destruirla es seguro *si y sólo si*
es reconstruible, y el commit es exactamente la prueba de reconstruibilidad hecha **antes** de destruir.

**Segundo invariante:** `proyectar()` es función pura del LIBRO. Mismo libro → misma salida byte a
byte. Eso convierte «no hay resumen de resumen» en **teorema estructural**, no en disciplina: no
existe ninguna operación que lea una proyección y escriba otra. El ciclo 500 proyecta desde los mismos
eventos que el ciclo 1.

---

## 2. Qué me llevo y qué tiro de cada diseño

### 2.1 De `diseno_proceso.md` — **el esqueleto**

| Pieza | Estado |
|---|---|
| 2PC: PREPARE con el contexto viejo vivo → COMMIT → HECHO/ABORT | **NÚCLEO** |
| Trazadores como canarios del commit (IDs no inferibles) | **NÚCLEO** — es lo único que distingue «presente» de «reconstruible» |
| Sólo la **igualdad exacta** vota en la compuerta; `canal.conservacion()` (difuso, `UMBRAL_COBERTURA=0.6`) se calcula, se muestra y **no vota** | **NÚCLEO** |
| MODO ANCHO como salida legítima | **NÚCLEO**, pero **acotado** (§3, corrección 3) |
| Mutación del gate como instrumentación permanente | **NÚCLEO** |
| Rollback = reproyectar un prefijo del libro | **NÚCLEO** |
| Q1..Q3 contestadas por la sesión nueva, corregidas por igualdad | **NÚCLEO**, con el umbral estricto y la consecuencia barata (§3, corrección 2) |
| `--ctx-size 32768 --parallel 2` (16k/slot) | **DESCARTADO**: contradice el requisito de ~32k de ventana. Se adopta `65536 --parallel 2` |
| Prueba 6 corriendo el contrato en cada commit | **DESCARTADO tal cual**: si el criterio es un `pytest` de 40 s el overhead salta al 31 %. Se sustituye por la regla del criterio barato (§5.2) |

### 2.2 De `diseno_ledger.md` — **el sustrato y tres piezas**

**Injerto:**
1. **El formato de evento completo** — `i`, `ts`, `ciclo`, `t`, `quien`, `origen`, `conf`, `refs`,
   `prev`. `diseno_proceso.md` sólo lo esboza; éste lo especifica. Se adopta verbatim.
2. **`conf = f(origen)` con techo duro 0,30 para lo que dijo el modelo y SIN ruta de ascenso por
   repetición.** Es el anticuerpo directo contra `memory/long_term_consolidator.py`, que promueve a
   hecho permanente por repetición ≥3: un agente que repite una invención tres veces la asciende.
   **La frecuencia no es evidencia.**
3. **La señal negativa comprimida a un CONTADOR `firma → n, exit`**, no a texto. Son los 350 chars
   más inteligentes de los tres documentos: conserva la señal anti-loop —que `falsacion.md` identificó
   como *la única señal no correlacionada que existe*— y elimina la traza de errores que produce
   self-conditioning (85 % → 70 % → 55 %). Las dos cosas a la vez.
4. **El detector de CICLO MUDO (C6)**: 2 ciclos con 0 eventos medidos → corte duro. `diseno_proceso.md`
   no lo tiene: sus LOOP-A/B/C necesitan una *firma repetida*, y un ciclo mudo no tiene firma.
   El propio `diseno_ledger.md` declara que un bug de conteo en `gate.py` desactiva su única defensa —
   por eso aquí entra **como G6, bajo la mutación permanente del gate**. Ésa es la síntesis: la defensa
   de uno, vigilada por el instrumento del otro.
5. **`libro_grep` / `libro_ver`** como tools estilo RLM (`agent/rlm.ContextoVivo` + `_ctx_grep`, que ya
   sostiene 300M tokens a coste constante).
6. **HARD_STOP antes que truncar** la banda permanente. Es la decisión más incómoda de los tres
   documentos y es la correcta: *prefiero un agente que se planta a uno que olvida en silencio*.

**Descartado:**
- **La compuerta después de destruir.** Es el motivo por el que este diseño no es el esqueleto (§0).
- **`decision` escrita libremente por el modelo y proyectada sin re-derivar.** El propio documento lo
  declara como su modo de fallo 3 y sin solución: *he excluido la traza de errores y he dejado pasar
  la conclusión errónea*. Mitigación injertada de grafo (§2.3): una `decision` sólo se proyecta
  mientras **al menos un evento de su `base` siga vigente y no `stale`**; si su base se invalida, cae
  de la proyección automáticamente, sin que nadie opine. No valida el razonamiento — queda abierto.
- **El tope de 3.000 tokens justificado por «4 contextos calientes».** El número está mal (§3,
  corrección 4).
- **«El reset cuesta 0,24 s».** Sobre-estimado ~4×; sólo es cierto bajo una regla de render que ese
  documento no escribe. La escribo yo (§4.3) y con ella el número se recupera.

### 2.3 De `diseno_grafo.md` — **la epistemología**

**Injerto:**
1. **CONTROL NEGATIVO DEL VERIFICADOR (`examen_ok`).** La mejor idea de los tres documentos, y ninguno
   de los otros dos la tiene. Un verificador nuevo, **antes** de poder conceder un solo `verificado`,
   se corre en copia con la evidencia **destruida** (fichero renombrado, truncado a 0, línea borrada,
   campo a `null`, cita retirada). Si sigue pasando, es nulo: `cuarentena=1`, la fila vuelve a
   `hipotesis`, se emite `err:verificador_nulo:<id>`. Ataca de frente *«el test que pasa por el motivo
   EQUIVOCADO»* y aplica la doctrina que ya vive en el repo (*nada se activa por haber salido bien*,
   `flujos/examen.py` + `inmune/anticuerpos.py`) al **ascenso epistémico**.
   **Coste: una ejecución extra por verificador NUEVO, no por chequeo.** ~15 verificadores nuevos en
   500 ciclos × ~2,4 s = **36 s en toda la corrida**. Es un error de redondeo. Entra como **G7**.
2. **Vocabulario de CLAVES CERRADO emitido por el interceptor** (`archivo:` `cmd:` `test:` `err:`
   `cfg:` `regla:` `dec:` `nota:`). Convierte la detección de contradicciones en
   `GROUP BY clave HAVING COUNT(DISTINCT valor)>1`: determinista, microsegundos, cero LLM. La regla C3
   de ledger (solape de tokens ≥0,6 + léxico de negación) es una heurística léxica, y *un parámetro
   configurable siempre se falsifica*. Entra como **G4**.
3. **`sin_huella`**: toda afirmación con clave `archivo:`/`cmd:`/`test:`/`err:` que no tenga una fila
   de `prov` con esa herramienta y ese destino en los últimos 3 ciclos se marca `sospechoso`
   **aunque su verificador pase**. Es el caso «el modelo cree que escribió», medido contra el disco.
4. **`poder_discriminante`** = |verificadores que han fallado alguna vez| / |verificadores|. Un
   verificador que en 500 ciclos nunca falló es sospechoso de ser trivial. Alarma en rojo por debajo
   de 0,25. Es exactamente la misma doctrina que la mutación del gate, aplicada al otro órgano.
5. **Estado epistémico `sospechoso`** (un fallo de re-verificación puede ser el entorno, no una
   mentira) y **frescura** (>60 ciclos sin re-verificar → `sospechoso`).

**Descartado:**
- **SQLite con 8 tablas + FTS5.** No compra nada medible aquí: el almacén son <10 MB y ~6.000 filas a
  500 ciclos, y un `SELECT` sobre 6.000 filas y un fold sobre 7.000 líneas JSONL cuestan lo mismo
  (~0,15 s). A cambio trae una superficie de bloqueo que **el propio documento exhibe en sus datos de
  ejemplo**: `err:sqlite3.OperationalError:database is locked`. Y pierde la cadena `prev`-sha, que es
  la detección de corrupción semántica que el WAL de SQLite no da. **Kill condition honesta**: si E-fold
  mide el coste de proyectar por encima del 1 % de un ciclo, se añade un índice SQLite *derivado* del
  JSONL (nunca la fuente de verdad).
- **BM25/FTS5 como vía por defecto de recuperación de hechos.** `falsacion.md` midió selección desde
  almacén inmutable en **recall 0,526**, con **9 de 24 nunca cargadas**. Restringirla a la banda de
  baja persistencia es legítimo, pero convertirla en la vía por defecto no lo es: su fallo devuelve un
  conjunto plausible y equivocado — vacío silencioso otra vez. **La vía por defecto es `libro_grep`
  bajo demanda, por regex/ID exacto**, cuyo fallo es ruidoso (`0 hits` va en el envelope). BM25 queda
  opt-in detrás de E-recuperación.
- **5 estados × 10 tipos × 6 relaciones.** Demasiados grados de libertad para un consumidor de 3.050
  tokens. Se quedan **4 estados** (`hipotesis`, `verificado`, `sospechoso`, `invalidado`) y **3
  relaciones** (`deriva_de`, `invalida`, `contradice`). `satisface`/`veta`/`requiere` son derivables
  del contrato y de los anticuerpos.

---

## 3. Cuatro correcciones que hago a los tres diseños

**Corrección 1 — el argumento del reloj está inflado en los tres.**
Los tres justifican el reset con «27,3 s de prefill por llamada a 64k contra 1,43 s». Es falso para el
caso normal: está medido que **el append puro sólo cuesta lo añadido** (+500→514, +1.500→1.506,
+3.000→3.018). Una sesión que sólo crece paga el delta, no el total. Lo que sí cuesta el prefill
entero es **cada invalidación de caché**, y ahí la medición manda: cambiar algo a más de ~512 tokens
del final se paga completo (5.826 ms a 16k), cambiar de agente cuesta 10,68 s contra 0,28 s.
El argumento correcto tiene tres patas, en este orden:

1. **HIGIENE** (dominante): self-conditioning, Qwen3-32B 85 % → 70 % → 55 % en el turno 100 según el
   porcentaje de errores propios en el historial, y **escalar el modelo no lo mitiga**. Más el
   horizonte conductual H(0,5) ≈ 8 turnos en Gemma3-27B. Ésta es la razón real.
2. **EL MURO, no el reloj**: sin reset el contexto crece ~9k tok/ciclo. En el ciclo ~20 llega a los
   0,8·n_ctx que disparan `loop._recortar_mensajes`, que trunca **in-place a 200 chars** el `content`
   de los turnos `tool` viejos — destructivo, sin resumen, sin recuperabilidad — y además, al escribir
   *en mitad* del prompt, invalida la caché entera. El brazo ancho no es «caro»: es que **degrada en
   silencio a partir del ciclo ~20**. Ése es su techo real.
3. **EL COSTE DE CADA INVALIDACIÓN, que escala con el tamaño**: a 64k una invalidación cuesta 27,3 s;
   a 12k cuesta ~4,4 s (curva medida, casi lineal: 16.036 tok = 5,82 s). El reset convierte un peor
   caso de 27 s en uno de 4 s.

Consecuencia de diseño: **MODO ANCHO es más barato de lo que los tres creen, y por eso es una salida
legítima — pero sólo a corto plazo.**

**Corrección 2 — el umbral de Q va estricto y la consecuencia barata.**
Un falso negativo de Q (dice OK y la memoria se perdió) cuesta cientos de ciclos de degradación
silenciosa; un falso positivo cuesta un ciclo en MODO ANCHO (~+3 s). Asimetría brutal ⇒ **umbral 3/3,
consecuencia barata**: recitación verbatim y reintento, luego MODO ANCHO. **Q nunca mata la tarea.**
`diseno_proceso.md` acierta el umbral y falla la consecuencia (dejaba «3 en 20 ciclos → parar»).

**Corrección 3 — MODO ANCHO acotado.**
Por la corrección 1, punto 2: más allá de ~20 ciclos anchos consecutivos el brazo ancho entra en
`_recortar_mensajes` y destruye en silencio. Por tanto: **≤3 ciclos anchos consecutivos y ≤10 % de los
ciclos de la tarea.** Al superarlo, HARD_STOP con petición de partir la tarea o retirar restricciones.
`ciclos_anchos` es métrica de salud visible, no un contador oculto.

**Corrección 4 — el presupuesto de contextos calientes son 2, no 4.**
`diseno_ledger.md` fija la proyección en 3.000 tok «para que quepan 4 contextos calientes». El número
está mal: lo que se mantiene caliente no es la proyección, es **el contexto vivo del ciclo**, que
crece a ~12k tok. Con la medición `min(4 estados, ~1 GiB)` y 32 KiB/tok en el 9B: 12k tok = 384 MiB,
dos = 768 MiB, más una cabecera precalentada de 3k = 96 MiB → **~864 MiB, cabe**. Tres contextos de
trabajo = 1,15 GiB → **se cae de golpe** (medido: 3×8k → 0/3, 5×2k → 0/5; el acierto no degrada, cae a
cero). Presupuesto real: **2 contextos de trabajo + 1 cabecera precalentada**. Subir `--cache-ram` por
encima de 1024 es RAM de host, no VRAM, y es la palanca barata — **pero hay que medirla antes de
contarla**.

---

## 4. La memoria

### 4.1 Las bandas, por persistencia (la jerarquía que pidió el dueño)

| Banda | Contenido | Ops | Tope tok | Cómo se re-emite |
|---|---|---|---|---|
| **P** permanente | objetivo, restricciones, definición-de-hecho, criterios congelados | `add` (ciclo 0), `amend` (sólo humano o contrato) | 900 | **VERBATIM, entera, byte-idéntica. Sin selección jamás** |
| **T** trazadores | 6 canarios de ID aleatorio no inferible | `add` (ciclo 0) | 120 | verbatim |
| **N** negativo | contador `firma → n, exit` + ≤6 lecciones **imperativas positivas** + cola 160 chars del **último** error | `add`, `supersede` | 300 | topes duros |
| **D** decisiones | ≤20 vivas, cada una con `base` a eventos **vigentes** | `add`, `supersede` | 600 | cae sola si su base se invalida |
| **F** hechos | ≤25 vigentes, con estado epistémico y confianza | `add`, `invalidate`, `stale` | 750 | render generacional |
| **A** artefactos | ruta + sha256 + última verificación + `critico:bool` | `add`, `stale` | 540 | críticos primero |
| **E** estado | posición + «SOLO FALTA» | derivada de disco | 250 | recomputada en el commit |
| **Q** control | 3 preguntas con respuesta literal en el LIBRO | derivada | 90 | al final (recitación) |
| **X** charla | prosa, razonamiento, trazas crudas de error | — | **0** | **muere en el reset** |

**Total: 3.050 ± 90 tokens.** Orden `P T N D F A E Q`: lo inmutable delante (caché de prefijo), lo
volátil al final (regla medida: distancia absoluta ~512 tokens desde el final), y la recitación en la
última posición (U-shape; +4 % en RULER por recitar la evidencia antes de resolver).

**«Charla descartable» es falso y se corrige:** los comandos fallidos son la única señal no
correlacionada que existe. Lo que muere es la **traza cruda** (banda X); lo que viaja es la **lección
destilada mecánicamente** (`comando + exit + cola 160 chars` → una línea en positivo) y el
**contador de firmas**. Se conserva el conocimiento, no la contaminación.

### 4.2 Provenance y confianza — el modelo no tiene los campos

| `prov.tipo` | Significa | Re-verificador puro | ¿P/D/F/A? | `conf` base |
|---|---|---|---|---|
| `dada` | literal de la tarea o de `CLAUDE.md` | `cita in texto_tarea` | sí | 1,00 |
| `ejecutada` | exit code de un proceso real | re-ejecutar o comparar exit | sí | 1,00 |
| `leida` | substring literal de un fichero con sha en *t* | `search/evidencia.verificar_cita` + `sha_fuente == sha_actual` | sí | 0,90 |
| `derivada` | salida de una función determinista nombrada, con `base` | re-llamar `fn(base)` y comparar | sí | mín(base) |
| `dicha` | lo dijo el modelo | **ninguno** | **NO — vive en X y muere en el reset** | 0,30 (techo duro) |

`conf = base[origen] × ex(verificador) × fr(frescura)`, con
`ex` = 1,0 si `examen_ok=1` / 0,5 si 0 / **0,0 si cuarentena**, y
`fr` = 1,0 (<20 ciclos) / 0,7 (20–60) / 0,4 (>60, y la fila pasa a `sospechoso`).
**Banda P: `conf = 1,00` siempre, sin decay** — el decay temporal sobre restricciones es *governance
decay*, el antipatrón de `memory/forgetting.py`.

Las seis columnas de origen (`tool`, `args_sha`, `cwd`, `exit_code`, `salida_sha`, `salida_bytes`) las
escribe **`harness/interceptor.py:despues()`**, el enchufe único por el que pasa toda llamada. **El
modelo no tiene esos campos: no hay superficie de mentira que detectar, porque no existe.** La
confianza nunca la emite el LLM — `falsacion.md` midió que su juicio está en el azar (0,517 / 0,523),
o sea que produciría **hechos falsos con etiqueta creíble**, que es peor que no etiquetar.

### 4.3 REGLA DE RENDER GENERACIONAL (aportación propia, y es la que salva el número del reset)

Ninguno de los tres la escribe, y sin ella el «reset cuesta 0,24 s» de `diseno_ledger.md` es falso.

El problema: la caché de llama.cpp conserva el prompt anterior. El prompt nuevo reusa el **prefijo
común**; la medición es dura — 95 % de prefijo común reusa (516 procesados de 8k), **90 % no** (8.039).
El corte es **distancia absoluta ~512 tokens**. Si la proyección tapa una fila vieja para meter una
nueva, el prefijo se rompe **por delante** y se paga el prefill entero: **~1,08 s** para 3.050 tokens
(interpolando la curva medida 1.022 tok = 0,40 s / 4.022 = 1,43 s).

La regla:

1. Cada banda se emite en **orden monótono de `i`**, nunca por recencia.
2. Una fila invalidada **no se quita: se marca en su sitio** (`†`) hasta que su generación se cierre.
3. Cada banda se parte en **generaciones de 25 filas**. Las generaciones cerradas son **congeladas y
   byte-idénticas para siempre**. Sólo la generación abierta cambia.
4. La expulsión ocurre a granularidad de generación, no de fila: se colapsa la generación más vieja a
   una línea `… 94 hechos más antiguos → /libro grep`, y **eso sí paga un prefill completo, una vez
   cada ~25 expulsiones**.

Resultado: entre dos ciclos consecutivos el prefijo estable es `P T N` + las generaciones cerradas de
`D F A`, y sólo cambian la generación abierta + `E` + `Q` ≈ **300–700 tok**.

| Escenario | Prefill del reset | Frecuencia |
|---|---|---|
| Render generacional, prefijo caliente | **0,10–0,25 s** | ~24 de cada 25 resets |
| Expulsión de generación (prefill completo de 3.050 tok) | **~1,08 s** | 1 de cada ~25 resets |
| Sin la regla (cualquiera de los tres diseños tal cual) | **~1,08 s** | **todos** |

**En los números del ratio uso el peor caso (1,08 s).** La regla se decide con E6, no por fe.

---

## 5. El presupuesto: la maquinaria no puede comerse el trabajo

### 5.1 El ratio objetivo

> **Objetivo: la maquinaria ≤ 7 % del tiempo de pared del ciclo. Alarma dura al 15 %.**
> `overhead = (t_proyección + t_PREPARE + t_rehidratación + t_Q) / t_ciclo`, **medido y mostrado en
> cada línea de `/tx estado`. Un cero perpetuo es sospechoso, no sano.**

| Partida | Coste | De dónde |
|---|---|---|
| `proyectar()` (fold puro sobre ~7.000 eventos) | **5–150 ms** | Python sobre ~1,8 MB de JSONL |
| G1, G2, G4, G6 (hashes, comparaciones, `GROUP BY`) | ~5 ms | — |
| G3 artefactos (`stat` × 12 + 2–3 lecturas completas) | 3–40 ms | — |
| G5 contrato (criterio barato, §5.2) | ≤300 ms | `GoalContract.check()` |
| G7 examen negativo | **0 ms/ciclo** (36 s en toda la corrida) | 1 ejecución por verificador NUEVO |
| 2 × `fsync` | ~4 ms | NVMe |
| Rehidratación (peor caso, 3.050 tok) | **1,08 s** | curva medida 0,35 ms/tok |
| Q (decode de ~80 tok a 55–65 tok/s) | **1,3 s** | decode honesto medido |
| **TOTAL maquinaria** | **≈ 2,6 s** | |

Trabajo útil por ciclo: 8 acciones × ~300 tok de decode a 60 tok/s = **~40 s de decode** + 10–40 s de
herramientas ⇒ **50–80 s**.

**Ratio = 2,6 / (2,6 + 50) = 4,9 % en el peor caso; 3,3 % en el mejor.** Bajo el objetivo del 7 %.

**Por qué es alcanzable y no una promesa:** el término dominante es el decode, fijado por el hardware
en 55–65 tok/s y **no reducible por diseño**. La maquinaria es aritmética de CPU y un prefill de 3k.
De los 2,6 s, **1,3 s son el decode de Q, que no es puro coste**: es la recitación de evidencia que la
literatura mide en +4 % en RULER. La prueba del commit y la mitigación de degradación por longitud son
**el mismo turno**.

**El contraste que importa:** la alternativa medida —compactar con un LLM— cuesta **16,49 s**, o sea
**25–33 % de un ciclo, 6,3× esta maquinaria entera**. Y **comprimir aquí cuesta 0 tokens de LLM**,
porque el compresor no es un LLM: es un fold.

A 500 ciclos: maquinaria **≈ 22 min sobre ~10–12 h de trabajo**.

### 5.2 La regla del criterio barato (cierra el único agujero grande del ratio)

Si el criterio por ciclo es un `pytest -q` de 40 s, G5 sube el overhead al **31 %** y el diseño se cae.
Regla, obligatoria y tecleada:

- `coste_ms` de cada criterio se **mide en su primera ejecución** y se guarda.
- El criterio **por ciclo** debe costar **< 5 s**. Si no existe ninguno, `/tx iniciar` **lo dice y lo
  pide** antes de arrancar (hoy `horizonte` corre un ciclo mudo cuando no hay criterios derivables;
  eso es peor que parar).
- Los criterios caros corren **sólo si G3 detectó cambio en un artefacto `critico:true`**, **como
  máximo 1 de cada 3 ciclos**, y **siempre en el cierre**. Si nada cambió, el resultado anterior vale
  por construcción: mismos bytes → mismo exit.
- **Siempre en proceso nuevo con `cwd = workspace`** — `GoalContract` resuelve rutas contra el CWD del
  proceso, que es un bug identificado en el inventario.

---

## 6. VRAM, slots y el reloj (respuesta a la pregunta 14)

**La lobotomía ahorra 0 MiB.** 13 168 MiB @2 944 tok → 13 155 @187 874, 626 muestras, amplitud 21 MiB
(0,16 %), y el consumo **baja**. El KV se reserva entero al cargar (`CUDA0 KV buffer size` a los
0,793 s, antes de `listening on`). **Prohibido justificar un solo componente de esta arquitectura por
VRAM.** La VRAM se decide una vez, en el arranque del servidor.

```
llama-server -m Huihui-Qwythos-9B-...-Q4_K.gguf --ctx-size 65536 --parallel 2 --cache-ram 1024
```

| Partida | MiB | Origen |
|---|---|---|
| Pesos | 5 357,9 | medido |
| KV: 65 536 tok × 32 KiB/tok (f16) | 2 048 | fórmula validada 6/6 |
| Estado SSM: 50,25 × 2 slots | 100,5 | medido |
| Overhead (compute buffers) | ~1 490 | cuadre real |
| **Total** | **~8 996** de 16 311 | **libera 4,2 GB** |

Dos slots de **32.768** tokens sobre **una sola copia de pesos**, cada uno con su caché (no se
desalojan entre sí). **Slot 0 = ejecutor. Slot 1 = crítico comparativo / oráculo / precalentado.**
La aritmética usa **8 capas de atención de 33 bloques** (los modelos son híbridos `qwen35`): contar
`n_layer=33` se equivoca **4×**.

**KV en f16, no q8_0.** Ahorraría ~960 MiB más, pero **nadie midió calidad con q8_0 en este proyecto**
y toda esta arquitectura depende de que el modelo lea sus propias restricciones sin degradarse. Queda
como experimento, no se adopta a ciegas.

**Compuerta obligatoria antes de arrancar** — en `ctx=16384` llama.cpp pidió 1 792 MiB y la VRAM subió
2 582: **desbordó a RAM compartida de Windows sin emitir un solo error**, con CUDA reportando
«14987 MiB free».

```
/tx vram --verificar
  esperado (fórmula) 8 996 MiB · medido (nvidia-smi) 8 981 MiB · delta 0,17 %  OK
```

**Delta > 3 % ⇒ el CLI se niega a arrancar el modo largo.**

**Los 4,2 GB liberados no son un ahorro: son una compra.** Compran el crítico de otra familia, que es
lo que el estado del arte exige (≤13B sólo ganan con verificador fuerte; el self-preference bias mueve
−38 % a +90 %) y lo que la lección propia ya dijo: *Cognia era mono-familia (Qwen); el primer modelo
de otra familia destapó 3 fallos silenciosos*.

---

## 7. El crítico: ninguno de los tres lo pone en la ruta crítica, y es correcto

`falsacion.md` H3: exactitud balanceada **0,517 / 0,523** = azar. «Crítico y riguroso» detecta 43/43
erróneas **pero rechaza 58/60 correctas**; framing neutro **aprueba 41/43 errores reales**. El adjetivo
del prompt mueve la detección **21×**.

**En el commit no hay ni una llamada de juicio.** G1–G7 son sha256, exit codes, substring literal,
`GROUP BY` y comparación de bytes. La única llamada al LLM (Q) es una **prueba de lectura con
respuesta conocida corregida por igualdad exacta**, no un juicio — y su prefill es el que el ciclo
siguiente iba a pagar igual.

Tres capas, coste creciente, ninguna concede `verificado` por opinar:

| Capa | Qué es | Cuándo | Coste |
|---|---|---|---|
| **K1 Control negativo** (`flujos/examen.py`) | el verificador tiene que **suspender** con la evidencia destruida | por verificador NUEVO | ~36 s / 500 ciclos |
| **K2 Comparativo A vs B** (`agent/workflows.criticar`, slot 1) | **sólo** con dos candidatos, **nunca** «¿está bien esto?» | contradicción viva con 2 opciones | ~2 s |
| **K3 Oráculo de otra familia** (`harness/oraculo.py`, transporte inyectado) | máx. **5 consultas por tarea**; su salida entra como **`pendiente`**, no como decisión | K1 no aplica y hay contradicción viva | variable |

**K2 existe si y sólo si E3 lo aprueba.** El absoluto ya está medido en 0,52; si el comparativo no
supera 0,58 con n=103, **se borra**. Sin oráculo, `oraculo.consultar()` devuelve `sin_oraculo` y la
fila **se queda `sospechoso` — nunca asciende por defecto**. Vacío ruidoso, no silencioso.

---

## 8. Multiagente (pregunta 13)

**Secuenciales, nunca en paralelo.** El +90,2 % de Anthropic se compra con **15× tokens** y el uso de
tokens explica el **80 % de la varianza**; con 1 slot eso se paga en pared. Y cambiar de agente
invalida la caché: **10,68 s contra 0,28 s medidos**.

1. **El prompt del subagente es un SUFIJO del prefijo del padre:** `[system][P][T] + <misión>`. Como
   P y T son byte-idénticas, la caché se reusa y los 10,68 s bajan a ~0,3 s. Las restricciones
   **nunca** se filtran por ámbito — filtrarlas es la selección que midió 0,526.
2. **No devuelve prosa.** Devuelve **eventos de LIBRO tipados** con la `prov` que el interceptor grabó
   durante *su* ejecución. Hoy `delegar_subtarea` devuelve 600 chars lossy: **ése era exactamente el
   resumen-de-resumen** que esta arquitectura existe para eliminar.
3. **Sus filas entran como `hipotesis`** aunque él las declare verificadas, salvo las de
   `autor=interceptor`. Un subagente no asciende nada por su cuenta.
4. **Un solo escritor** (el padre hace `append`). Es lo único en lo que Anthropic y Cognition coinciden.
5. **Su contexto se destruye** al volver y no queda rastro suyo en la ventana del padre.
6. **Presupuesto de contextos calientes: 2 de trabajo + 1 cabecera** (§3, corrección 4). Un tercer
   agente vivo simultáneo tira los tres.

---

## 9. Cómo se teclea

Opt-in `COGNIA_TX=1` (apagado por defecto; el repo exige opt-in por evidencia medida).
`/largo` y `/memoria` **ya existen** en `cli.py` (líneas 1949 y 2037) — las familias nuevas son `/tx`
y `/libro`, ambas libres.

```
/tx iniciar "cablear el canal de estado al bucle" \
      --criterio "venv312\Scripts\python.exe -m pytest tests/estado -q" \
      --restriccion "no tocar loop.py fuera de bucle_nativo" \
      --pasos 8 --horas 12
/tx estado          panel: bandas, gates, salud, ratio de maquinaria
/tx probar          corre G1..G7 AHORA contra el contexto vivo
/tx commit          fuerza un commit ya e imprime la tabla de gates
/tx ancho           fuerza MODO ANCHO un ciclo
/tx bandas          tokens por banda y qué se está cayendo por el tope
/tx mutar           corrompe la proyección a propósito y EXIGE que el gate aborte
/tx rollback TX-0006
/tx vram --verificar

/libro 20                    últimos 20 eventos
/libro ver 812 --contexto 3  el evento, sus vecinos y su cadena de refs
/libro grep "pickle" --banda F
/libro auditar 815           cadena de provenance hasta eventos medidos, con confianzas
/libro restringir "..."      añade restricción (autor=dueño, conf 1,00)
/libro retractar 816 "motivo"  invalida sin borrar
/libro examen                re-corre el control negativo de TODOS los verificadores
/libro fsck [--reparar]
/libro exportar              JSONL completo, auditoría externa
```

Tools que ve el agente (patrón `rlm.register(tool)`): `libro_grep`, `libro_ver`, `decidir --porque
<i,i>` (rechaza sin `base` medida), `afirmar --verificador <cmd> --espera <exit==0|sha==…>`,
`pendiente`, `resolver`, `leccion` (rechaza forma negativa: el self-conditioning entra por ahí).

Una línea por ciclo:

```
⛓ c41 COMMIT TX-0041 ok · P 9f3c1a · trz 6/6 · art 12/12 · Q 3/3 · crit 4/7 · 1,4 s · maq 4,1 % · ctx 3,0k→11,8k
⛓ c42 ABORT G3: A-004 canal.py sha e77a01b3→b91c4402 · re-leo y reintento
⛓ c43 ANCHO (G2 5/6) · ciclos_anchos 1/3 · no destruyo
```

### Módulos

**NUEVOS:** `cognia/tx/{libro,bandas,commit,verificador,claves,tools,driver}.py` + comandos en `cli.py`
+ `tests/test_tx_*.py`.

**REUSO verificado en el repo:** `harness/interceptor.py` (`antes`/`despues`/`ruta_destino`),
`estado/canal.py` (las 11 huérfanas: `anotar_restriccion/decision/pendiente`, `sembrar_trazadores`,
`comprobar_trazadores`, `conservacion`, `_presente`, `_cobertura`, `serializar/guardar/cargar`),
`estado/presupuesto_progreso.py`, `harness/limites.py` (hoy **huérfano total**, ya trae
`LimiteExcedido`), `harness/contexto_vivo.registrar_uso` (hoy **cero llamadores**; se cablea en
`loop.py:1077`, donde ya se lee `resp.usage.prompt_tokens` y se tira), `harness/checkpoints.py`,
`harness/oraculo.py`, `agents/goal_contract.py`, `flujos/examen.py`, `inmune/anticuerpos.py`,
`autopsia/causal.py`, `search/evidencia.verificar_cita`, `agent/rlm.ContextoVivo`,
`agent/tools.delegar_subtarea`, `agent/workflows.criticar` (sólo comparativo).

**PARCHES a `agent/horizonte.py`:** `_TECHO_CICLOS = 3` → techo por presupuesto (`limites`);
`estado_tarea.resumen_para_prompt` (1.200 chars, sin canal) → `bandas.proyectar`; `GoalContract` con
`cwd = workspace`.

**APAGADO con `COGNIA_TX=1`, con registro en el LIBRO:** `memory/memory_compressor.py` (clustering que
BORRA los originales = resumen-de-resumen), `memory/forgetting.py` (decay sobre restricciones =
governance decay), `memory/long_term_consolidator.py` (**promueve a hecho por repetición ≥3**),
`loop._recortar_mensajes` (truncado destructivo a 200 chars). `/compactar` (`cli.py:9532`) hoy sólo
hace `_console.clear()` y repinta: se renombra en la ayuda a «limpiar pantalla» para que nadie crea
que comprime.

---

## 10. Tabla de decisiones

| DECISIÓN | ALTERNATIVA DESCARTADA | POR QUÉ (con el dato) |
|---|---|---|
| Esqueleto = **commit 2PC con la compuerta ANTES de destruir** | Compuerta al arrancar el ciclo nuevo (ledger `gate.py`, grafo `gate_presencia`) | La pérdida medida fue **24→2 en UN paso** y luego punto fijo byte a byte: falla la **transferencia**, no el almacén. Comprobar después de destruir deja como única salida abortar; comprobar antes deja **MODO ANCHO**, que es el brazo que midió **recall 1,000** |
| Almacén = **JSONL append-only con cadena `prev`-sha** | SQLite con 8 tablas + FTS5 (grafo) | <10 MB y ~6.000 filas a 500 ciclos: `SELECT` y fold cuestan lo mismo (~0,15 s). SQLite añade bloqueo —el propio diseño lo exhibe: `sqlite3.OperationalError: database is locked`— y pierde la detección de corrupción por cadena. Kill: si proyectar >1 % del ciclo, se añade índice SQLite **derivado** |
| Compresión = **fold determinista, 0 tokens de LLM** | Compactación con LLM | **16,49 s medidos** por compactación = 25–33 % de un ciclo. El fold cuesta **5–150 ms** |
| Banda P **verbatim, entera, sin selección; HARD_STOP si no cabe** | Selección por relevancia / resumen de la cabecera | recall **1,000** verbatim, **0,526** seleccionando (9 de 24 nunca cargadas), **0,083** en cascada. Recortar restricciones es peor que no hacer nada |
| **Control negativo del verificador** como requisito de ascenso (G7) | Confiar en que un verificador que pasa verifica algo | *«El test que pasa por el motivo EQUIVOCADO»*: cinco instrumentos aprobaron algo roto en una noche. Coste: 1 ejecución por verificador nuevo ≈ **36 s en 500 ciclos** |
| Contradicción por **clave canónica de vocabulario cerrado** (`GROUP BY`) | Solape de tokens ≥0,6 + léxico de negación (ledger C3) | Determinista y en microsegundos frente a una heurística léxica; *un parámetro configurable siempre se falsifica* (7 agujeros, cada parche abrió el siguiente) |
| Recuperación por **`libro_grep` bajo demanda, regex/ID exacto** | BM25/FTS5 como vía por defecto (grafo) | Selección desde almacén midió **0,526**. El fallo de grep es ruidoso (`0 hits` en el envelope); el de BM25 devuelve un conjunto plausible y equivocado = vacío silencioso |
| **Sólo la igualdad exacta vota** en la compuerta | `canal.conservacion()` difuso (`UMBRAL_COBERTURA=0.6`) como gate | Una paráfrasis puntúa «presente» con el ID perdido. El difuso se calcula, se muestra y **no vota**; los trazadores tienen ID **no inferible**, así que «presente» no se confunde con «reconstruible» |
| **Crítico = código que EJECUTA**; ningún LLM concede `verificado` | Crítico LLM puntuador | 0,517 / 0,523 = azar. «Crítico y riguroso» rechaza **58/60 correctas**; neutro **aprueba 41/43 errores**. El adjetivo mueve la detección **21×**. Sólo el que ejecuta subió (0,681) |
| K2 comparativo **condicionado a E3** | Adoptar el crítico LLM comparativo por defecto | El absoluto ya está medido en 0,52; el comparativo es la incógnita. **≤0,58 con n=103 ⇒ se borra** |
| **`conf = f(origen)`, techo 0,30 para lo dicho, sin ascenso por repetición** | Confianza declarada por el modelo; consolidación por frecuencia ≥3 | La emitiría el mismo modelo cuyo juicio está en el azar ⇒ **hechos falsos con etiqueta creíble**. `long_term_consolidator` asciende una invención repetida 3 veces a permanente |
| **Provenance escrita por `interceptor.despues()`** | Que el modelo rellene `tool`/`args`/`exit`/`sha` | Elimina la superficie de mentira en vez de detectarla. El modelo no tiene esos campos |
| Reset por **T1 8 acciones ∨ T2 2 errores ∨ T3 18k tok ∨ T4 criterio sellado** | Reset por reloj; reset por ciclo | H(0,5) ≈ 8 turnos en Gemma3-27B. Compactar **por saturación** = 19,8 min/día contra **137 min/día** por ciclo. **T2 es el disparador que más importa**: la contaminación es el motivo real (85 %→55 %) |
| **MODO ANCHO acotado: ≤3 seguidos, ≤10 % de los ciclos** | MODO ANCHO sin techo (proceso) | Pasados ~20 ciclos anchos el contexto llega a 0,8·n_ctx y entra `loop._recortar_mensajes`: **truncado in-place a 200 chars, sin resumen y sin recuperabilidad**. El brazo ancho no es caro, es que **degrada en silencio** |
| **Q con umbral 3/3 y consecuencia barata** (recitación → ancho, nunca matar) | Q como gate que para la tarea | Asimetría: un falso negativo cuesta cientos de ciclos silenciosos, un falso positivo cuesta ~3 s. Y el decode de Q **es** la recitación que mide +4 % en RULER: la prueba y la mitigación son el mismo turno |
| **Render generacional** (§4.3) | Render por recencia (los tres diseños) | El corte de caché es **distancia absoluta ~512 tokens**: 95 % de prefijo común reusa (516 proc.), **90 % no** (8.039). Sin la regla, cada reset paga 3.050 tok = **1,08 s**; con ella, **0,10–0,25 s** en 24 de cada 25 |
| `--ctx-size 65536 --parallel 2` (32k/slot) | `--ctx-size 200192 --parallel 1` (hoy) · `32768 --parallel 2` (proceso) | Hoy **regala 5,2 GB** de KV para una ventana que este diseño no usa. La propuesta de proceso da 16k/slot y **contradice el requisito de ~32k**. 65536/2 = **~8.996 MiB, libera 4,2 GB** |
| Delta de `nvidia-smi` contra la fórmula, **>3 % ⇒ no arranca** | Fiarse de `--ctx-size` | En `ctx=16384` pidió 1 792 MiB y la VRAM subió 2 582: **desbordó a RAM compartida sin un solo error**, con CUDA reportando «14987 MiB free» |
| **2 contextos calientes de trabajo + 1 cabecera** | «4 contextos calientes» (ledger) | Lo caliente es el contexto **vivo** (~12k tok = 384 MiB), no la proyección. 2×384 + 96 = 864 MiB < 1 GiB; 3 = 1,15 GiB y el acierto **cae a cero de golpe** (3×8k → 0/3; 5×2k → 0/5) |
| Subagentes **secuenciales**, retorno en **eventos**, prompt = sufijo del prefijo del padre | Paralelos; retorno de 600 chars de prosa | +90,2 % se compra con **15× tokens** (80 % de la varianza) y aquí hay 1 slot. Cambiar de agente cuesta **10,68 s vs 0,28 s**; como sufijo baja a ~0,3 s. Los 600 chars **eran** el resumen-de-resumen |
| **Criterio por ciclo < 5 s**; los caros sólo si cambió un artefacto crítico, ≤1 de cada 3 ciclos | Contrato completo en cada commit (proceso) | Con un `pytest` de 40 s el overhead salta al **31 %** y el diseño se cae |
| **G6 ciclo mudo** (2 ciclos sin evento medido ⇒ corte) bajo mutación permanente | Confiar en LOOP-A/B/C | Un ciclo de pura prosa **no tiene firma** que repetir: proyección idéntica → respuesta idéntica → punto fijo determinista y silencioso. Y el propio ledger avisa de que un bug de conteo desactiva su única defensa: por eso va **bajo `/tx mutar`** |
| **`tasa_de_abort == 0` durante 50 ciclos = AVERÍA**, no salud | Interpretar el verde como salud | *«Cinco instrumentos aprobaron algo roto en una noche; ninguno falló.»* Un gate que nunca rechazó nada no está probado |
| **E0 brazo nulo primero** (proyección = sólo P + T) | Empezar por el sistema completo | La referencia de un selector es el **azar**, nunca s1. Si el sistema no bate a re-emitir el contrato verbatim, **toda la maquinaria sobra** |

---

## 11. Evaluación experimental (pregunta 18)

Doctrina vinculante del repo: brazos **intercalados**, netos **apareados intra-corrida** (la varianza
entre corridas es **±34 pts**), **n≥6** por brazo, **brazo nulo obligatorio**, gate e2e flaky ~50 %
(fallos concentrados = regresión), `finish_reason`/`usage` mirados **antes** de atribuir nada al modelo.

| # | Pregunta | Diseño | KILL pre-registrado |
|---|---|---|---|
| **E0** | ¿la maquinaria aporta algo sobre re-emitir el contrato verbatim? | proyección = **sólo P + T**, resto vacío; mismas 12 tareas, intercaladas | **Corre PRIMERO.** Si el sistema completo ≈ E0, se entrega E0 y se tira el resto |
| **E1** | ¿el gate detecta corrupción? | `/tx mutar` cada 25 ciclos: borra 1 restricción, cambia 1 dígito de trazador, falsea 1 sha | **tasa de detección = 1,000.** <1,000 ⇒ el gate está roto |
| **E2** | ¿el control negativo caza verificadores tramposos? | 40 verificadores emitidos por el modelo + **5 triviales inyectados a propósito (control positivo)** | ≥15 % suspenden. **Los 5 inyectados deben suspender los 5**: sin control positivo un 0 % es ininterpretable |
| **E3** | ¿existe K2? | 60 correctas / 43 erróneas ya en `exp/`; absoluto / comparativo / azar | absoluto ya = 0,52. **comparativo ≤0,58 ⇒ K2 se borra** |
| **E4** | ¿cuántas acciones por ciclo aquí? | barrido 4/8/16/32, n≥6, intercalado | el 8 viene de un paper sobre Gemma3-27B: **es el número más prestado de todo el diseño** |
| **E5** | ¿el sistema gana al brazo ancho? | 12 tareas × 2 brazos intercalados. A = ventana ancha con el `_recortar_mensajes` de hoy. B = TX. Primaria: criterios sellados y **re-verificados en limpio** por hora | **Predicción honesta: B pierde por debajo de 30 min.** Si B no gana por encima de 4 h, **el diseño muere** |
| **E6** | ¿el render generacional paga? | tokens procesados que reporta llama.cpp en el reset, con y sin la regla | predicción 0,25 s vs 1,08 s. Si el ahorro <2×, se quita la regla y se aceptan los 1,08 s |

**Instrumentación permanente en `/tx estado`:** `tasa_de_abort`, `ciclos_anchos`, `q_fallidas`,
`huerfanas_pct`, `poder_discriminante`, `stale_detectados`, `ratio_maquinaria`, `hechos_recortados`.
**Un cero perpetuo en cualquiera es sospechoso, no sano.**

---

## 12. Las 18 preguntas — qué mecanismo gana

| # | Pregunta | Mecanismo (y de quién viene) |
|---|---|---|
| 1 | Qué es sólido | Destruir el contexto **por higiene** (self-conditioning 85→55 %, no lo arregla escalar) y por el **muro** del ciclo ~20; la jerarquía **por persistencia**; el canal de estado explícito (recall 0,07→1,00); subagentes secuenciales aislados |
| 2 | Qué fallará | Todo lo justificado por VRAM (**0 MiB**); toda selección de restricciones (0,526); el crítico LLM absoluto (0,517); la confianza autodeclarada; la compresión con LLM (16,49 s); el resumen encadenado (0,083 en un paso) |
| 3 | Tras cientos/miles de ciclos | LIBRO <10 MB a 500 ciclos, proyección **constante** en 3.050 tok. Lo que crece y rompe: banda P (§13.1) y saturación de F/A hacia el ciclo ~120 (§13.2) |
| 4 | Evitar degradación de memoria | **Teorema, no disciplina**: `proyectar()` es función pura de un ledger append-only; no existe la operación resumen→resumen. Verificado recomputando el fold entero y comparando sha en cada reset |
| 5 | Alucinaciones persistentes | `dicha` **no puede entrar** en P/D/F/A: vive en X y muere en el reset. Techo 0,30 sin ascenso por repetición. G3 re-lee el disco en cada commit: un `leida` cuyo sha cambió pasa a `stale` y, si no se re-lee, `invalidate`. **No sobrevive 2 commits** |
| 6 | Que el crítico no valide errores | En la ruta crítica no hay juicio: sha256, exit codes, substring literal, `GROUP BY`, igualdad de bytes. **G7: ningún verificador concede nada sin haber suspendido su control negativo.** K2 sólo comparativo y sólo si E3 lo aprueba |
| 7 | Loops infinitos | Contador `firma → n` visible en banda N + LOOP-A/B/C/D mecánicos + veto en `interceptor.antes` + anticuerpo sintetizado + `presupuesto_progreso.veredicto()` + **G6 ciclo mudo** |
| 8 | Pérdida del objetivo | G1 (P byte-congelada) + G2 (trazadores 6/6) + Q (recitación obligatoria) + **acciones huérfanas >40 % ⇒ DERIVA** + G5 monotonía del contrato. Se **bloquea la acción**, no se refuerza el recordatorio: la adherencia medida es **plana en 0,75** a 0,4k/32k/128k |
| 9 | Cuándo resetear | T1 8 acciones ∨ T2 2 errores ∨ T3 18k tok ∨ T4 criterio sellado, **∧** G1..G7 en verde. Si la compuerta no abre: **MODO ANCHO acotado**. Nunca por reloj |
| 10 | Cuánto guarda un snapshot | Un snapshot es un **manifiesto**: `{TX, sha_libro, sha_proyección, índice de checkpoint}` ≈ 200 B, más el blob de la proyección (12 KB, deduplicado). LIBRO 4,5 KB/ciclo. **<10 MB a 500 ciclos** |
| 11 | Estructura de la memoria | 8 bandas por persistencia `P T N D F A E Q` + `X` que muere, sobre 15 tipos de evento con 4 estados epistémicos y 3 relaciones |
| 12 | Provenance y confianza | 5 tipos de `prov`, cada uno con re-verificador **puro**; las 6 columnas de origen las escribe `interceptor.despues()`; `conf = base × examen × frescura`, **recalculable desde disco**. `/libro auditar <i>` imprime la cadena hasta eventos medidos |
| 13 | Coordinar agentes | Secuenciales; prompt = **sufijo del prefijo del padre** (caché 24×); retorno en **eventos**, no prosa; un solo escritor; contexto destruido al volver; sus filas entran como `hipotesis` |
| 14 | Minimizar VRAM | **El reset no la toca: 0 MiB.** Se minimiza en el arranque: `--ctx-size 65536 --parallel 2` ⇒ 13,2 → **9,0 GB**. Los 4,2 GB liberados **compran el crítico de otra familia** |
| 15 | Minimizar tokens de compresión/recuperación | Compresión: **0 tokens de LLM**, 5–150 ms. Rehidratación: 3.050 tok = **0,25 s** (generacional) a 1,08 s. Recuperación: `libro_grep` bajo demanda, <300 tok. **Maquinaria total ≤7 % del ciclo** |
| 16 | Estado corrupto | Cadena `prev` rota = detectable ⇒ reproyectar el prefijo válido más largo. `/libro fsck --reparar`: `verificado` sin `prov` ⇒ a `hipotesis`; verificador con `examen_ok=0` que concedió ascensos ⇒ **ascensos revocados**; `prov` huérfana **se conserva** (es evidencia); DB ilegible ⇒ banda P se reconstruye de `.cabecera.txt` (**doble soporte a propósito**) |
| 17 | Rollback | `proyectar(libro.leer(hasta_tx))` — **exacto, 5 ms, no destructivo, idempotente** — + `checkpoints.restaurar_hasta(m)` para los ficheros + **re-verificación obligatoria** de lo restaurado + el propio rollback queda como evento. Pendientes resueltos por eventos invalidados **se reabren** |
| 18 | Evaluación | E0–E6 con brazo nulo primero, KILL pre-registrado, mutación permanente del gate (§11) |

---

## 13. Comparación honesta con el estado del arte

| Familia | Qué tomo | Qué rechazo, con el dato |
|---|---|---|
| **Context compression** | Nada de la variante aprendida | 16,49 s por compactación; recall 0,526 seleccionando. Aquí «comprimir» es **proyectar**: elegir filas ya escritas |
| **Summarization memory** | Nada | Es el antipatrón central: −39 % single→multi-turn con **+112 % de no-fiabilidad**; cascada 24→2 en un paso |
| **Recurrent memory (RMT/Titans)** | El **teorema**: un estado pequeño de tamaño fijo sostiene millones de tokens | El sustrato: los 11,1M de RMT son **GPT-2 fine-tuneado en BABILong**; no hay checkpoint de 27B instruido. Aquí el estado recurrente es **texto inspeccionable** |
| **External memory (MemGPT/Letta)** | Disco como verdad, ventana como caché | Que el modelo gestione su memoria con confianza autodeclarada. Decide **qué leer**, nunca **qué es verdad** |
| **RAG** | `libro_grep` bajo demanda | Embeddings: el corpus tiene vocabulario cerrado y la búsqueda es exacta. Y un encoder más no cabe cómodo en 16 GB |
| **Episodic memory** | La tabla `prov` **es** memoria episódica: cada acción con su huella y su `ts` | La promoción por repetición ≥3: **la frecuencia no es evidencia** |
| **Hierarchical memory** | La jerarquía **por persistencia** — es lo que pidió el dueño y es correcto | La jerarquía por compresión sucesiva y el decay temporal sobre restricciones (*governance decay*) |
| **Agentic workflows** | Subagentes secuenciales con contexto sellado y retorno tipado; un solo escritor | Paralelos: 15× tokens, 1 slot, caché invalidada (10,68 s vs 0,28) |
| **Reflection** | `leccion` en forma imperativa positiva, con `base` medida | La reflexión libre: Huang ICLR'24 + Kamoi TACL'24 + el 0,517 medido aquí |
| **Verifier models** | **El que ejecuta** — única variante que subió (0,681) — **más el examen del propio verificador** | El puntuador absoluto del mismo modelo: azar, y el adjetivo del prompt mueve la detección 21× |
| **State-space** | La contabilidad honesta del KV: el 9B es híbrido, **8 capas de atención de 33**, y por eso el KV cuesta 32 KiB/tok | Nada que añadir: es sustrato, no diseño |
| **Zep / validez temporal** | **Invalidar en vez de reescribir.** Es la pieza que hace *inejecutable* el resumen-de-resumen | Sus cifras: LoCoMo usa 16k–26k tok (cabe entero en la ventana) y están disputadas (75,14 vs 65,99; 84 → **58,44** en su propio repo) |
| **Sleep-time compute** | Con el slot 1 ocioso durante un `pytest`: pre-computar la proyección siguiente y **precalentar el prefijo** (swap caliente **59 ms vs 2.840, 48×**) | — |
| **Anthropic compact + re-read** | Compactar y **releer del disco** (git log, progress file, lista JSON pass/fail) | Nada: es el mismo patrón, aquí formalizado como transacción |

**Qué ya tiene nombre propio (nada de esto es mío):** WAL, two-phase commit, event sourcing, CQRS,
content-addressed storage, validez bi-temporal (Zep/Graphiti), memoria externa (MemGPT),
orquestador-trabajador sellado, verificador ejecutante, recitación (+4 % RULER), sleep-time compute, y
**el propio ciclo de lobotomía, que ya existe en este repo**: `agent/horizonte.py:ciclos_con_contrato`,
opt-in `COGNIA_HORIZONTE=1`, activado en `cli.py:13069`.

**Qué es novedoso de verdad — cinco cosas, y son pequeñas:**

1. **El reset como 2PC con un test de conservación como compuerta.** No he encontrado a nadie que
   publique «no destruyas hasta que el sucesor demuestre que conserva». Todo el mundo compacta y reza.
2. **Trazadores como canarios del commit**: needle-in-a-haystack aplicado a la transacción, con IDs
   **no inferibles**, de modo que «presente» no pueda confundirse con «reconstruible».
3. **Provenance escrita por el harness, nunca por el modelo.** Los sistemas de memoria con provenance
   (A-MEM, Zep, HippoRAG) hacen que el LLM rellene la atribución. Aquí **elimina la superficie de
   mentira en vez de detectarla**.
4. **Control negativo del verificador como requisito de ascenso.** La literatura examina la respuesta;
   nadie examina el verificador.
5. **La mutación del gate como instrumentación permanente**: un commit que nunca ha rechazado nada se
   declara **averiado**, no sano.

**La combinación más potente** (es un producto, no una suma — quitar cualquier factor lo rompe):

> *cabecera permanente verbatim que nunca se comprime* **×** *libro append-only con provenance de
> máquina* **×** *proyección determinista con render generacional* **×** *verificador que ejecuta y que
> ha suspendido su propio control negativo* **×** *reset disparado por contaminación y **gateado** por
> conservación, con MODO ANCHO acotado como salida* **×** *2 slots de 32k sobre una copia de pesos*.

Sin la primera vuelve el 0,526. Sin la segunda, la mentira. Sin la tercera, cada reset cuesta 4× más.
Sin la cuarta, el ascenso es teatro. Sin la quinta, la pérdida es invisible. Sin la sexta no hay dónde
correr el crítico. **Y la pieza que más aporta por sí sola está medida: re-emitir el contrato verbatim
— 400 tokens, 0,17 s de prefill, recall 1,000. Todo lo demás existe para proteger eso.**

---

## 14. Cómo me rompo — cinco modos, tres sin resolver

Heredo los modos de fallo declarados por los tres arquitectos. Tres de ellos **sólo los hago visibles;
no los resuelvo**, y esa visibilidad es la entrega honesta.

**14.1 — Osificación de la banda P** (de ledger MF1 y grafo MF2). Las restricciones no caducan **por
diseño** (el decay sobre governance es un antipatrón demostrado). Con un extractor que deriva reglas de
`CLAUDE.md` y un dueño que teclea `/libro restringir`, 7 restricciones se vuelven 45 y a ~60 salta el
HARD_STOP. Y la salida obvia —filtrar por ámbito— **reintroduce la selección que midió 0,526**.
*Lo que añado:* la **única** vía automática de alivio es un `amend` disparado por el **contrato** (un
criterio satisfecho puede retirar la restricción que lo guardaba) — mecánica y estrecha, nunca poda
por el modelo. Alarma a partir de 1.200 tok de cabecera.
**Sin resolver:** un agente que corre 500 ciclos sin supervisión **necesita un ritual de poda humano**,
y eso contradice «trabajar días sin supervisión». Lo hago visible en vez de esconderlo.

**14.2 — F y A empiezan a seleccionar hacia el ciclo ~120** (de proceso MF1). A ~15 hechos/ciclo con
topes de 750/540 tokens, el proyector empieza a recortar. **G1, G2, G5 y G6 siguen en verde**, porque
Q se saca de P y T, que son eternos. El agente re-deriva lo que ya sabía: vuelve a leer el mismo
fichero, vuelve a descartar la misma vía.
*Lo que añado:* el render generacional expulsa por generaciones (no por filas sueltas), **Q se muestrea
preferentemente de las generaciones MÁS ANTIGUAS**, y `/tx bandas` reporta `hechos_recortados`.
**Riesgo residual:** eso deja a Q como único detector, y Q depende de que el proyector elija bien a
quién preguntar — **el detector comparte el sesgo del sistema que vigila.**

**14.3 — Decisiones erróneas que envenenan por la puerta de atrás** (de ledger MF3). Excluir la traza
de errores no excluye la **conclusión** errónea, que es la parte que el modelo trata como premisa.
*Lo que añado:* una `decision` sólo se proyecta mientras al menos un evento de su `base` siga vigente y
no `stale`; si su base se invalida, cae sola.
**Sin resolver:** eso garantiza que *existió* una medición, no que la conclusión **se siga** de ella.
Puedo garantizar la procedencia de los hechos y **no puedo garantizar la validez de los razonamientos
que los conectan**.

**14.4 — Inflación de `verificado` trivial** (de grafo MF1). El control negativo caza al verificador
que pasa con la evidencia destruida, **no al que pasa por un motivo trivialmente cierto**:
`test -f almacen.py` suspende correctamente y sin embargo no verifica nada de lo que la fila afirma.
*Lo que añado:* el centinela `poder_discriminante` en rojo por debajo de 0,25 a los 100 ciclos.
**Parcial:** la mitigación conocida es una heurística léxica, y las heurísticas léxicas se falsifican.

**14.5 — `leida` que miente porque el mundo cambió** (de proceso MF3). 400 artefactos × 500 commits =
200.000 lecturas completas: hay que muestrear por `mtime + size`, y en cuanto se muestrea, un artefacto
no crítico puede cambiar sin mover ninguno de los dos.
*Lo que añado:* sha completo cuando `mtime` **o** `size` se muevan, 100 % de sha en los
`critico:true` en cada commit, **barrido completo cada 25 ciclos** (~0,4 s) y postcondiciones sobre una
**copia limpia del workspace** en el cierre.
**Riesgo residual:** entre dos barridos caben ~37 minutos de trabajo apoyado en un hecho falso **bien
etiquetado**. Y si lo que cambió es una **dependencia** (un import, un JSON de config), su propio sha
no se mueve y no lo veo en absoluto. La verificación final sobre copia limpia **descubre** el desastre;
no lo previene.

---

*Todo número de VRAM, prefill, caché, recall y latencia procede de `medicion_kv.md` y `falsacion.md`.
Los tres números importados de la literatura están marcados: H(0,5) ≈ 8 turnos, self-conditioning
85/70/55 %, +4 % de RULER por recitación. Los derivados por mí (ratio de maquinaria, presupuesto de
contextos calientes, coste del render generacional) están marcados como derivados y cada uno tiene su
experimento. Ninguna cifra de este documento es una estimación silenciosa.*

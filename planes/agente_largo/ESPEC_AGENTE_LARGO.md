# ESPECIFICACIÓN FINAL — AGENTE DE HORIZONTE LARGO EN COGNIA

**Nombre del subsistema:** `TX` (la transacción de reset) sobre `LIBRO` (el almacén).
**Fecha:** 2026-08-19 · **Opt-in:** `COGNIA_TX=1` (apagado por defecto).
**Entradas:** `medicion_kv.md`, `inventario_cognia.md`, `estado_del_arte.md`, `falsacion.md`,
`diseno_ledger.md`, `diseno_grafo.md`, `diseno_proceso.md`, `ataques.md`, `arquitectura.md`.
**Regla de lectura:** todo número lleva etiqueta. `[M]` = medido en esta máquina. `[L]` = literatura,
con cita. `[D]` = derivado por mí, y cada uno tiene su experimento en §15. **No hay estimaciones
silenciosas.** Si no lleva etiqueta, es una decisión de diseño, no un dato.

---

## 0. VEREDICTO EN 10 LÍNEAS

1. **La premisa de VRAM es falsa y se cae entera.** El KV se reserva completo al cargar el modelo:
   13.168 MiB con 2.944 tokens → **13.155 MiB con 187.874 tokens**, 626 muestras, amplitud 21 MiB
   (0,16 %), y el consumo *baja* `[M]`. **La self-lobotomy ahorra 0 MiB.** Prohibido justificar un
   solo componente de este diseño por VRAM. El multiagente tampoco ahorra: 0 MiB, y además cuesta
   (cambiar de agente invalida la caché: 10,68 s contra 0,28 s) `[M]`.
2. **La lobotomía se sostiene, pero por otra razón: higiene y el muro, no el reloj ni la memoria.**
   Con Qwen3-32B la precisión en el turno 100 cae 85 % → 70 % → 55 % según el porcentaje de errores
   propios en el historial, y escalar el modelo no lo mitiga `[L, arXiv:2509.09677]`. Además, sin
   reset el contexto de Cognia llega hacia el ciclo ~20 a `0,8·n_ctx` y entra `loop._recortar_mensajes`,
   que **trunca in-place a 200 chars sin resumen y sin recuperabilidad**. Ése es el techo real del
   brazo ancho, no el coste.
3. **"Ventana corta" es falso en esta máquina.** El backend sirve hoy 200.192 tokens y la ventana
   eficaz medida en otro modelo fue ~150k de 200k. El argumento "hay que comprimir porque no cabe"
   es circular: cabe. Lo que no aguanta es la *contaminación*.
4. **La compresión acumulativa que el dueño quiere evitar no existe en Cognia y no hay que
   desmontarla: hay que no construirla.** `/compactar` sólo llama `_console.clear()`. Lo único real
   es el truncado a 200 chars. Bien: no hay resumidor encadenado que retirar.
5. **Toda selección de restricciones pierde, y pierde en silencio.** Verbatim en ventana a 111.406
   tokens = recall **1,000**; selección desde almacén inmutable = **0,526** (9 de 24 nunca cargadas);
   cascada de resúmenes = **0,083**, con **24 → 2 restricciones en UN paso** y después punto fijo byte
   a byte `[M]`. La cabecera permanente se re-emite entera, verbatim, o el sistema se planta.
6. **El agente crítico separado, entendido como "otro LLM que opina", está muerto.** Exactitud
   balanceada 0,517 y 0,523 = azar; "crítico y riguroso" detecta 43/43 erróneas pero **rechaza 58/60
   correctas**; framing neutro **aprueba 41/43 errores reales**; el adjetivo del prompt mueve la
   detección **21×** `[M]`. Sobrevive sólo el crítico que **ejecuta** (0,681, a 38× de coste) `[M]`.
7. **"Provenance y confianza" tal como el dueño la pidió produce lo contrario de lo que busca:**
   si la confianza la emite el mismo modelo cuyo juicio está en el azar, el resultado son hechos
   falsos con etiqueta creíble. La confianza aquí es **función pura del origen**, escrita por
   `harness/interceptor.py`, y **el modelo no tiene esos campos**.
8. **"Charla descartable" es falso.** Los comandos fallidos son la única señal no correlacionada que
   existe. Lo que muere es la **traza cruda**; lo que viaja es la lección destilada mecánicamente y un
   **contador `firma → n`**. Se conserva el conocimiento, se tira la contaminación.
9. **Lo que hay que cambiar respecto a la idea original:** el reset deja de ser "comprimir y
   arrancar limpio" y pasa a ser un **commit de dos fases con la compuerta ANTES de destruir**, cuyo
   modo de fallo es **no resetear** (MODO ANCHO), que es el brazo que midió 1,000 — no abortar la
   tarea. Comprimir no es resumir: es **proyectar** un ledger append-only con una función pura y **0
   tokens de LLM** (5–150 ms contra los 16,49 s medidos de una compactación con LLM `[M]`).
10. **Lo que este encargo NO puede darse por hecho, dicho ahora:** (a) *días sin supervisión* no es
    alcanzable — la banda permanente se osifica y necesita un ritual de poda humano (§16.1); (b) se
    puede garantizar la **procedencia de un hecho**, **no la validez del razonamiento** que lo conecta
    con una conclusión (§16.3) — ése es el agujero por donde entra la alucinación persistente en los
    tres diseños evaluados, con tres nombres distintos; (c) el instrumento de Cognia hoy **no mide
    exit codes** (`ok` es una regex sobre 120 caracteres) y hasta arreglarlo la frase "la provenance
    la escribe la máquina" es mentira (§14.1, P0-1).

---

## 1. ARQUITECTURA

### 1.1 Los seis componentes

| # | Componente | Fichero | Responsabilidad | Lo que NO hace |
|---|---|---|---|---|
| 1 | **LIBRO** | `cognia/tx/libro.py` → `~/.cognia/tareas/<id>/libro.jsonl` | Almacén append-only, un evento JSON por línea, cadena `prev`-sha. Único sitio donde hay verdad. | No borra, no actualiza, no resume. No existe `delete` ni `update`. |
| 2 | **PROYECTOR** | `cognia/tx/bandas.py` | `proyectar(eventos) -> texto`. **Función pura**: mismo libro → misma salida byte a byte. Es todo el "compresor". | No llama al LLM, no llama a la red, no lee más disco que el LIBRO. **Nunca lee una proyección para escribir otra.** |
| 3 | **INTERCEPTOR** | `cognia/harness/interceptor.py` (existe) | Enchufe único de toda llamada a tool. Escribe la provenance: `tool`, `args_sha`, `cwd`, `exit_code`, `salida_sha`, `salida_bytes`, `ruta_destino`. | No juzga. No deja que el modelo rellene un solo campo de provenance. |
| 4 | **COMMIT** | `cognia/tx/commit.py` | Protocolo 2PC del reset: PREPARE (compuerta G1..G7, contexto viejo **vivo**) → COMMIT (destruir + Q1..Q3) → HECHO / ABORT / ANCHO. | No pregunta a ningún LLM si el estado "parece bien". La única llamada al modelo es una prueba de lectura corregida por igualdad exacta. |
| 5 | **VERIFICADOR** | `cognia/tx/verificador.py` | Registra verificadores (comando + expectativa), les corre el **control negativo** antes de que puedan conceder nada, los re-ejecuta y mantiene `examen_ok`, `cuarentena`, `poder_discriminante`. | No opina. Su salida es un exit code o un sha. |
| 6 | **DRIVER** | `cognia/tx/driver.py` | El bucle: siembra, dispara, llama al commit, aplica MODO ANCHO, corta. Parchea `agent/horizonte.py`. | No mantiene estado propio: todo lo que sabe lo re-lee del LIBRO. |

Piezas reusadas tal cual (ya existen y están testeadas en el repo): `estado/canal.py` (11 funciones
hoy huérfanas), `estado/presupuesto_progreso.py`, `harness/limites.py` (huérfano total, ya trae
`LimiteExcedido`), `harness/contexto_vivo.registrar_uso` (0 llamadores hoy),
`harness/checkpoints.py`, `harness/oraculo.py`, `agents/goal_contract.py`, `flujos/examen.py`,
`inmune/anticuerpos.py`, `autopsia/causal.py`, `search/evidencia.verificar_cita`,
`agent/rlm.ContextoVivo`, `agent/tools.delegar_subtarea`, `agent/workflows.criticar`.

Piezas **apagadas** bajo `COGNIA_TX=1`, con el apagado registrado en el LIBRO:
`memory/memory_compressor.py` (clustering que borra los originales = resumen-de-resumen),
`memory/forgetting.py` (decay temporal sobre restricciones = *governance decay*),
`memory/long_term_consolidator.py` (**asciende a hecho permanente por repetición ≥3**;
la frecuencia no es evidencia), `loop._recortar_mensajes` (truncado destructivo a 200 chars).

### 1.2 Diagrama

```
   TECLADO ──/tx ──/libro──►┌──────────────────────────────────────────────┐
                            │ DRIVER   cognia/tx/driver.py                 │
                            │ siembra · dispara · commit · ancho · corta   │
                            └───────────────┬──────────────────────────────┘
                                            │ UN SOLO ESCRITOR
  ┌─────────────────────────────────────────▼────────────────────────────────┐
  │ LIBRO   ~/.cognia/tareas/<id>/libro.jsonl                                │
  │ append-only · cadena prev-sha · 16 tipos · 6 ops · NO existe delete      │
  │ provenance ESCRITA POR LA MÁQUINA · conf = f(origen), nunca del modelo   │
  └────┬────────────────────────────────────────────────────▲────────────────┘
       │ proyectar()  PURA · sin LLM · sin red · 5–150 ms   │ append + fsync
       ▼                                                    │
  ┌──────────────────────────────┐          ┌───────────────┴────────────────┐
  │ PROYECCIÓN   3.550 tok tope  │          │ INTERCEPTOR harness/interceptor│
  │ P T N D F A │ E Q            │          │ antes()/despues() = ENCHUFE    │
  │ render GENERACIONAL (§5.2):  │          │ ÚNICO. exit real, sha de disco,│
  │ prefijo byte-estable         │          │ ruta_destino(). El modelo NO   │
  └────┬─────────────────────────┘          │ toca un campo de provenance    │
       │ = system + user[0] del ciclo       └───────────────▲────────────────┘
       ▼                                                    │ toda tool
  ┌────────────────────────────────────────────────────────┴─────────────────┐
  │ VENTANA VIVA   llama-server :8080 · slot 0 · n_ctx_slot 32.768 · CACHÉ    │
  │ crece 3,5k → ~12k tok en ≤8 acciones. Es una CACHÉ del LIBRO: desechable  │
  └────┬─────────────────────────────────────────────────────────────────────┘
       │ dispara  T1 (8 acciones) ∨ T2 (2 errores) ∨ T3 (0,55·n_ctx) ∨ T4 (criterio)
       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ COMMIT 2PC   cognia/tx/commit.py                                         │
  │  PREPARE   — el contexto viejo SIGUE VIVO —                    ~50 ms    │
  │    G1 sha(banda P) == sha_P0             igualdad de BYTES               │
  │    G2 trazadores en la RESPUESTA nueva   (no en la proyección: §6.3)     │
  │    G3 sha de artefactos                  críticos 100 %, resto mtime+size│
  │    G4 0 contradicciones vivas            GROUP BY clave, vocab. cerrado  │
  │    G5 monotonía del contrato             GoalContract, proceso, cwd=ws   │
  │    G6 el ciclo NO fue mudo               ≥1 evento medido                │
  │    G7 ningún `verificado` sin examen     examen_ok=1 (control negativo)  │
  │    fallo → robar topes (≤2) → MODO ANCHO (≤3 seg.) → HARD_STOP           │
  │  COMMIT                                                                  │
  │    destruir ventana → Q1..Q3 en la sesión NUEVA · igualdad normalizada   │
  │    Q<3/3 → recitación verbatim + reintento → MODO ANCHO. NUNCA mata      │
  └────┬─────────────────────────────────────────────────────────────────────┘
       │ slot 1 (--parallel 2): crítico COMPARATIVO / oráculo / precalentado
       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ ROLLBACK  proyectar(libro.leer(hasta_tx))  exacto · 5 ms · no destructivo │
  │          + checkpoints.restaurar_hasta(m) + árbol de sha del workspace    │
  │ AUTOPSIA  autopsia/causal.atribuir  →  inmune/anticuerpos.sintetizar()    │
  └──────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Flujo de información (los cinco caminos, y no hay más)

1. **Humano → LIBRO.** `/tx iniciar`, `/libro restringir`, `/libro retractar`. `origen=usuario`,
   `conf=1,00`. Es la única vía por la que entra algo en la banda P después del ciclo 0.
2. **Mundo → LIBRO.** Toda tool pasa por `interceptor.despues()`, que emite `fichero` / `comando` /
   `verificacion` con `origen=medido`. El modelo no participa.
3. **Modelo → LIBRO.** Sólo por tools tipadas (`afirmar`, `decidir`, `leccion`, `pendiente`), y sólo
   con `origen=modelo`, `conf ≤ 0,30`, sin ruta de ascenso por repetición.
4. **LIBRO → Ventana.** `proyectar()`, una vez por ciclo, en el commit. **Durante el ciclo, nada se
   reescribe en la ventana**; lo que falte se pide con `libro_grep` y llega como turno nuevo al final.
5. **LIBRO → LIBRO.** `proyectar` **nunca** es entrada de nada que escriba. La única transformación
   libro→libro es `invalidate`/`supersede`, que añade, no reescribe.

### 1.4 Los tres invariantes (si uno se rompe, el diseño se cae)

- **I1 — La ventana es una caché.** Destruirla es seguro si y sólo si es reconstruible. El commit
  *es* la prueba de reconstruibilidad, hecha **antes** de destruir.
- **I2 — `proyectar()` es función pura del LIBRO.** No existe la operación resumen→resumen. Esto
  convierte "no hay compresión acumulativa" en **teorema estructural**, no en disciplina. Se verifica
  recomputando el fold entero y comparando sha en cada reset (coste: 5–150 ms).
- **I3 — El modelo no tiene los campos de provenance.** No hay superficie de mentira que detectar,
  porque no existe. Un `add` a P/D/F/A sin `prov` re-comprobable **se rechaza y vuelve al modelo como
  error de tool**.

---

## 2. CICLO DE VIDA DE UNA TAREA LARGA

### 2.1 FASE 0 — SIEMBRA (una vez, ~20 s)

```
/tx iniciar "<objetivo>" --criterio "<cmd>" --restriccion "<texto>" --pasos 8 --horas 12
```

1. `libro.append` del `objetivo` verbatim, de cada `restriccion` verbatim, y de la
   **definición-de-hecho** (qué cuenta como "hecho" en esta tarea). `origen=usuario`, `conf=1,00`.
2. Extracción **mecánica** de restricciones de `CLAUDE.md` (regla → `origen=derivado`, `conf=1,00`),
   sin LLM: patrones fijos, y cada una queda auditable con `/libro auditar`.
3. `GoalContract.from_spec(...)` con los 4 tipos existentes (`file_exists`, `text_in_file`,
   `command_succeeds`, `text_present`). **CRITERIOS CONGELADOS.** Cada criterio se ejecuta una vez
   para medir su `coste_ms`.
4. **Si no hay ningún criterio verificable, `/tx iniciar` SE PARA y lo pide.** Hoy `horizonte` corre
   un ciclo mudo cuando no hay criterios derivables; eso es peor que parar.
5. **Si ningún criterio cuesta < 5 s, se pide un criterio barato** (regla §9.5). Sin él, G5 come el
   31 % del ciclo `[D]`.
6. `canal.sembrar_trazadores(estado, k=6, semilla=<task_id>)` → banda T. IDs aleatorios **no
   inferibles**. Se marcan con prefijo `TRZ-` para que el detector de violaciones (C4) los ignore:
   un trazador **no es una restricción real** y no puede disparar un corte.
7. `sha_P0 = sha256(render_banda_P())`. Es la constante del resto de la tarea.
8. `checkpoints.nueva_sesion()` + **árbol de sha del workspace** (§8.3, corrige el agujero A14).
9. `/tx vram --verificar`: delta `nvidia-smi` contra la fórmula. **>3 % ⇒ no arranca** (§11.2).

### 2.2 FASE k — UN CICLO (~90 s de pared `[D]`)

```
t=0,00  REHIDRATAR: history = [system, proyeccion]      prefill 3.550 tok  →  1,22 s  [M/D]
t=1,22  Q1..Q3: la sesión nueva responde 3 preguntas cuya respuesta literal está
        en el LIBRO. Corrección por igualdad exacta normalizada.       ~1,3 s  [M]
        (este decode NO es puro coste: es la recitación que mide +4 % en RULER [L])
t=2,52  ≤8 acciones. Cada una:
          interceptor.antes()   → veto de anticuerpos, marca HUERFANA, ruta_destino
          run_tool              → exit REAL (P0-1)
          interceptor.despues() → evento(s) al LIBRO + fsync
        El contexto crece ~1,1k tok/paso. Append puro: sólo cuesta lo añadido [M].
t≈85    DISPARADOR (§9.1) → COMMIT
```

### 2.3 Qué ocurre exactamente en un reset

```
--- PREPARE ------------------------------------- el contexto viejo SIGUE VIVO ---
p0  quiesce: se espera a que termine la tool en vuelo. Ninguna en el aire.
p1  flush: toda observación pendiente → libro.append() + fsync.
p2  libro.append({t:"tx", op:"prepare", ciclo:k, sha_libro:H, ckpt:m}) + fsync
p3  proy = bandas.proyectar(libro)        # PURA, 5–150 ms, 0 tokens de LLM
p4  gates G1,G3,G4,G5,G6,G7               # ~50 ms, ninguno llama al LLM
p5  canal.conservacion(estado, proy) -> recall difuso   # SE CALCULA, SE MUESTRA,
                                                        # y NO VOTA (§6.4)
    GATE = G1 ∧ G3 ∧ G4 ∧ G5 ∧ G6 ∧ G7   # booleano puro
    si falla -> escalera de aborto (§9.3). NO SE DESTRUYE NADA.
--- COMMIT -------------------------------------------------------------------
c1  libro.append({t:"tx", op:"commit", ciclo:k, sha_proy:S, tx:"TX-0041"}) + fsync
c2  DESTRUIR: history = [system, proy]
      · muere: toda la banda X (prosa, razonamiento, trazas crudas de error)
      · muere: la caché KV del slot (no se libera ni un MiB de VRAM: 0 [M])
      · sobrevive: nada de la ventana. TODO viene del LIBRO.
c3  Q1..Q3 en la sesión NUEVA  →  G2 (trazadores) se mide AQUÍ, sobre la respuesta
c4  <3/3 -> recitación verbatim + reintento -> MODO ANCHO. NUNCA mata la tarea.
--- HECHO --------------------------------------------------------------------
    el ciclo k+1 sigue en esa misma ventana. La proyección no se toca más
    durante el ciclo (regla de caché, §5.4).
```

**Tabla del reset — qué pasa con cada cosa:**

| Cosa | En el reset |
|---|---|
| Objetivo, restricciones, definición-de-hecho, criterios | **Re-emitidos VERBATIM, byte a byte.** `sha(P) == sha_P0` es G1 |
| Trazadores | Re-emitidos verbatim; comprobados **en la respuesta del modelo**, no en la proyección |
| Lecciones de fallo | Destiladas mecánicamente a imperativo positivo + contador `firma → n` |
| Traza cruda de error, razonamiento, prosa | **Destruida.** Es la que produce self-conditioning `[L]` |
| Hechos, decisiones, artefactos | Re-proyectados desde el LIBRO por generaciones (§5.2) |
| Estado / "SOLO FALTA" | **Recomputado de disco**, nunca arrastrado |
| Contexto de un subagente | Ya estaba destruido al volver; sólo quedaron sus eventos |
| VRAM | **Sin cambio. 0 MiB** `[M]` |

### 2.4 FASE Ω — CIERRE

Triple confirmación mecánica, sin juez (§9.2). Informe. `libro.append({t:"tx", op:"cerrar"})`.

---

## 3. FORMATO DE MEMORIA

### 3.1 Ficheros

```
~/.cognia/tareas/<task_id>/libro.jsonl      append-only, un evento por línea (fuente de verdad)
~/.cognia/tareas/<task_id>/cabecera.txt     banda P renderizada. DOBLE SOPORTE a propósito (§8.4)
~/.cognia/tareas/<task_id>/fold.json        checkpoint del fold cada 1.000 eventos (derivado)
~/.cognia/tareas/<task_id>/proy/TX-0041.txt proyección emitida, para auditoría y diff
~/.cognia/tareas/<task_id>/arbol/<tx>.json  sha de todos los ficheros del workspace (§8.3)
~/.cognia/tareas/<task_id>/cierre.json      veredicto final
```

Convive con `estado_tarea.dir_tareas()`, que ya usa esa ruta.

### 3.2 JSON Schema del evento (draft 2020-12) — esto es normativo

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "evento del LIBRO",
  "type": "object",
  "additionalProperties": false,
  "required": ["n", "ts", "ciclo", "t", "op", "id", "banda", "quien", "origen", "conf", "refs", "texto", "prov", "sha", "prev"],
  "properties": {
    "n":      {"type": "integer", "minimum": 1, "description": "ordinal monótono; dirección estable para refs, rollback y auditoría"},
    "ts":     {"type": "number", "description": "epoch del reloj DEL PROCESO EMISOR, nunca de una caché"},
    "ciclo":  {"type": "integer", "minimum": 0},
    "t":      {"enum": ["objetivo","restriccion","definicion","criterio","trazador",
                        "fichero","comando","verificador","verificacion",
                        "hecho","decision","leccion","pendiente","afirmacion",
                        "contradiccion","tx"]},
    "op":     {"enum": ["add","supersede","amend","invalidate","resolve","stale"],
               "description": "NO existe update ni delete"},
    "id":     {"type": "string", "pattern": "^(P|T|N|D|F|A|E|V|C|TX)-[0-9A-Fa-f]{3,8}$"},
    "banda":  {"enum": ["P","T","N","D","F","A","E","Q","X"]},
    "quien":  {"enum": ["usuario","harness","ejecutor","critico","sub"]},
    "origen": {"enum": ["usuario","medido","citado","derivado","modelo"]},
    "conf":   {"type": "number", "minimum": 0, "maximum": 1,
               "description": "DERIVADO de origen por función pura. Un LLM NUNCA lo emite"},
    "refs":   {"type": "array", "items": {"type": "integer"},
               "description": "n de los eventos de los que depende. Vacío = raíz"},
    "clave":  {"type": "string",
               "pattern": "^(archivo|cmd|test|err|cfg|regla|dec|nota):.+",
               "description": "vocabulario CERRADO, lo emite el interceptor salvo dec:/nota:"},
    "valor":  {"type": ["string","number","boolean","null"],
               "description": "valor canónico de la clave: sha, exit code, presente/ausente"},
    "texto":  {"type": "string", "maxLength": 400},
    "estado": {"enum": ["hipotesis","verificado","sospechoso","invalidado"], "default": "hipotesis"},
    "prov": {
      "type": "object",
      "required": ["tipo"],
      "oneOf": [
        {"properties": {"tipo": {"const": "dada"},
                        "cita": {"type": "string"}, "ref": {"type": "string"}},
         "required": ["tipo","cita","ref"]},
        {"properties": {"tipo": {"const": "leida"},
                        "ruta": {"type": "string"}, "linea": {"type": "integer"},
                        "cita": {"type": "string"}, "sha_fuente": {"type": "string"}},
         "required": ["tipo","ruta","cita","sha_fuente"]},
        {"properties": {"tipo": {"const": "ejecutada"},
                        "cmd": {"type": "string"}, "args_sha": {"type": "string"},
                        "cwd": {"type": "string"}, "exit_code": {"type": "integer"},
                        "salida_sha": {"type": "string"}, "salida_bytes": {"type": "integer"},
                        "cola": {"type": "string", "maxLength": 160}},
         "required": ["tipo","cmd","cwd","exit_code","salida_sha"]},
        {"properties": {"tipo": {"const": "derivada"},
                        "fn": {"type": "string"}, "base": {"type": "array", "items": {"type": "string"}}},
         "required": ["tipo","fn","base"]},
        {"properties": {"tipo": {"const": "dicha"}},
         "required": ["tipo"],
         "description": "lo dijo el modelo. NO PUEDE entrar en P/D/F/A. Vive en X y muere en el reset"}
      ]
    },
    "coste_ms":        {"type": "integer", "description": "sólo t=criterio: medido en su PRIMERA ejecución (regla §9.5)"},
    "critico":         {"type": "boolean", "description": "sólo banda A: el artefacto sostiene un criterio ⇒ sha completo en cada commit"},
    "examen_ok":       {"enum": [0, 1], "description": "sólo t=verificador: 1 si SUSPENDIÓ su control negativo (G7)"},
    "examen_detalle":  {"type": "string", "description": "sólo t=verificador: qué se destruyó y qué exit dio"},
    "cuarentena":      {"enum": [0, 1], "description": "sólo t=verificador: 1 ⇒ conf=0 y todos sus ascensos revocados"},
    "firma":           {"type": "string", "description": "sólo t=leccion: clave del contador anti-loop"},
    "n_veces":         {"type": "integer", "description": "sólo t=leccion: contador firma→n. NO es evidencia y NO asciende nada"},
    "requiere_humano": {"type": "boolean", "description": "sólo t=pendiente: true ⇒ salida BLOQUEADO (§9.2)"},
    "sha":  {"type": "string", "pattern": "^[0-9a-f]{14}$",
             "description": "sha256[:14] de {t,op,id,banda,clave,valor,texto,prov} canonicalizado. Content-addressed: dedup e idempotencia del append"},
    "prev": {"type": ["string","null"], "pattern": "^[0-9a-f]{14}$",
             "description": "sha del evento anterior. Romper la cadena es DETECTABLE"}
  },
  "allOf": [
    {"if": {"properties": {"banda": {"enum": ["P","T","D","F","A"]}}},
     "then": {"not": {"properties": {"prov": {"properties": {"tipo": {"const": "dicha"}}}}}}},
    {"if": {"properties": {"origen": {"const": "modelo"}}},
     "then": {"properties": {"conf": {"maximum": 0.30}}}}
  ]
}
```

Las dos cláusulas de `allOf` son el corazón anti-alucinación y son **validables con un test**:
lo `dicho` no puede tocar banda persistente, y lo dicho por el modelo tiene techo 0,30.

### 3.3 Tabla de confianza — función pura, `conf = f(origen)`

| `origen` | Cómo se produce | `conf` base | Re-verificador puro | ¿Asciende? |
|---|---|---|---|---|
| `usuario` | tecleado por el dueño | **1,00** | `cita in texto_tarea` | — |
| `medido` | exit code real de un proceso, sha256 de disco, `stat` | **1,00** | re-ejecutar / re-hashear | — |
| `citado` | substring **literal** presente en la fuente nombrada | **0,90** | `search/evidencia.verificar_cita` + `sha_fuente == sha_actual` | — |
| `derivado` | salida de una función determinista nombrada, con `base` | **mín(base)** | re-llamar `fn(base)` y comparar | — |
| `modelo` | lo dijo el LLM | **0,30 (techo duro)** | **ninguno** | **NO por repetición. JAMÁS.** |

`conf_efectiva = conf_base × ex × fr`, con
`ex` = 1,0 si `examen_ok=1` · 0,5 si `examen_ok=0` · **0,0 si `cuarentena=1`**;
`fr` = 1,0 (<20 ciclos) · 0,7 (20–60) · 0,4 (>60, y la fila pasa a `sospechoso`).
**Banda P: `conf = 1,00` siempre, sin decay.** El decay temporal sobre restricciones es *governance
decay*: el antipatrón exacto de `memory/forgetting.py`.

### 3.4 Vocabulario CERRADO de claves (lo emite el interceptor, no el modelo)

| Prefijo | Lo emite | Ejemplo | Valor canónico |
|---|---|---|---|
| `archivo:` | interceptor | `archivo:cognia/estado/canal.py` | sha256[:14] |
| `cmd:` | interceptor | `cmd:pytest -q tests/estado` | exit code (entero) |
| `test:` | interceptor | `test:tests/test_canal.py` | `exit==0` |
| `err:` | interceptor (firma normalizada) | `err:AssertionError:render_orden` | `presente`/`ausente` |
| `cfg:` | interceptor | `cfg:llama.n_ctx_slot` | número |
| `regla:` | dueño | `regla:venv` | `si`/`no` |
| `dec:` | modelo | `dec:jsonl_no_pickle` | etiqueta corta |
| `nota:` | modelo, libre | `nota:quiza_el_wal_bloquea` | `?` |

Contradicción = `GROUP BY clave HAVING COUNT(DISTINCT valor) > 1` entre filas **vigentes** y
**`verificado`**. Determinista, microsegundos, cero LLM. `dec:` y `nota:` **están excluidos de la
detección por clave** — punto ciego declarado, no oculto (§7.6).

### 3.5 Ejemplo REAL relleno, uno por tipo (tarea real de este repo, ciclo 7)

```jsonl
{"n":1,"ts":1755600001.02,"ciclo":0,"t":"objetivo","op":"add","id":"P-000","banda":"P","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"texto":"Cablear el canal de estado: las 11 funciones huerfanas de cognia/estado/canal.py deben tener llamador real y persistir entre ciclos.","prov":{"tipo":"dada","cita":"cablear el canal de estado","ref":"tarea#0"},"sha":"a01f3c9d7e2b41","prev":null}
{"n":2,"ts":1755600001.03,"ciclo":0,"t":"restriccion","op":"add","id":"P-001","banda":"P","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"clave":"regla:venv","valor":"si","texto":"Usar SIEMPRE venv312\\Scripts\\python.exe, nunca el python global.","prov":{"tipo":"dada","cita":"venv312","ref":"CLAUDE.md#12"},"sha":"5b7e0a41c9d3f8","prev":"a01f3c9d7e2b41"}
{"n":3,"ts":1755600001.04,"ciclo":0,"t":"restriccion","op":"add","id":"P-002","banda":"P","quien":"harness","origen":"derivado","conf":1.0,"refs":[1],"clave":"regla:backend_8080","valor":"si","texto":"NUNCA reiniciar el backend :8080 (es el cerebro de Cognia y sirve a exp.py).","prov":{"tipo":"derivada","fn":"reglas_de_claude_md","base":["CLAUDE.md#41"]},"sha":"c3f8102aa7be55","prev":"5b7e0a41c9d3f8"}
{"n":4,"ts":1755600001.05,"ciclo":0,"t":"definicion","op":"add","id":"P-003","banda":"P","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"texto":"DEFINICION DE HECHO: una funcion esta cableada si pytest tests/estado -q pasa Y grep muestra un llamador fuera de tests/.","prov":{"tipo":"dada","cita":"llamador real","ref":"tarea#0"},"sha":"91ce4470bb2a08","prev":"c3f8102aa7be55"}
{"n":6,"ts":1755600001.07,"ciclo":0,"t":"criterio","op":"add","id":"P-C1","banda":"P","quien":"usuario","origen":"usuario","conf":1.0,"refs":[],"clave":"cmd:pytest tests/estado -q","valor":0,"texto":"criterio C1","prov":{"tipo":"dada","cita":"--criterio","ref":"cli#0"},"coste_ms":2412,"sha":"1c90045ab7ee31","prev":"91ce4470bb2a08"}
{"n":9,"ts":1755600001.11,"ciclo":0,"t":"trazador","op":"add","id":"T-4A9C31","banda":"T","quien":"harness","origen":"derivado","conf":1.0,"refs":[],"texto":"TRZ-4A9C31: el umbral acordado es 612","prov":{"tipo":"derivada","fn":"canal.sembrar_trazadores","base":["semilla:19"]},"sha":"0d2b8fa1c37e90","prev":"..."}
{"n":812,"ts":1755607412.31,"ciclo":7,"t":"fichero","op":"add","id":"A-004","banda":"A","quien":"harness","origen":"medido","conf":1.0,"refs":[],"clave":"archivo:cognia/estado/canal.py","valor":"e77a01b3c4d980","texto":"canal.py editado (22417 B)","prov":{"tipo":"ejecutada","cmd":"editar_archivo","args_sha":"77c1a0","cwd":"C:/Users/usuario/Desktop/cognia_v2","exit_code":0,"salida_sha":"3b91ff","salida_bytes":22417},"critico":true,"estado":"verificado","sha":"88f0a3b1e0c229","prev":"..."}
{"n":813,"ts":1755607419.88,"ciclo":7,"t":"comando","op":"add","id":"E-0813","banda":"E","quien":"harness","origen":"medido","conf":1.0,"refs":[812],"clave":"cmd:pytest tests/estado -q","valor":1,"texto":"pytest tests/estado -q","prov":{"tipo":"ejecutada","cmd":"venv312\\Scripts\\python.exe -m pytest tests/estado -q","args_sha":"9f21ab","cwd":"C:/Users/usuario/Desktop/cognia_v2","exit_code":1,"salida_sha":"c0ffee","salida_bytes":4188,"cola":"tests/test_canal_persist.py:41: AssertionError: assert 'R3' in render(estado)"},"sha":"9f2a1440cb7712","prev":"..."}
{"n":814,"ts":1755607419.89,"ciclo":7,"t":"verificacion","op":"add","id":"V-C1","banda":"E","quien":"harness","origen":"derivado","conf":1.0,"refs":[813,6],"clave":"test:C1","valor":false,"texto":"criterio C1 FAIL","prov":{"tipo":"derivada","fn":"goal_contract.check","base":["n:813","n:6"]},"sha":"5d70bb1e4a0c92","prev":"..."}
{"n":820,"ts":1755607425.10,"ciclo":7,"t":"verificador","op":"add","id":"V-031","banda":"E","quien":"harness","origen":"medido","conf":1.0,"refs":[6],"clave":"cmd:pytest tests/estado -q","valor":"registrado","texto":"verificador de C1","prov":{"tipo":"ejecutada","cmd":"venv312\\Scripts\\python.exe -m pytest tests/estado -q","args_sha":"9f21ab","cwd":"<copia limpia>","exit_code":4,"salida_sha":"aa01bb","salida_bytes":210},"examen_ok":1,"examen_detalle":"control negativo: con tests/estado renombrado -> exit=4 SUSPENDE. OK","cuarentena":0,"sha":"aa77b1e0c40d3f","prev":"..."}
{"n":827,"ts":1755607431.40,"ciclo":7,"t":"decision","op":"add","id":"D-011","banda":"D","quien":"ejecutor","origen":"modelo","conf":0.3,"refs":[812,813],"clave":"dec:jsonl_no_pickle","valor":"jsonl","texto":"Serializar el canal en JSON lines y no en pickle: el fichero tiene que ser diffeable.","prov":{"tipo":"derivada","fn":"decidir","base":["A-004","E-0813"]},"estado":"hipotesis","sha":"e0a3f19c227b41","prev":"..."}
{"n":828,"ts":1755607433.02,"ciclo":7,"t":"afirmacion","op":"add","id":"X-0828","banda":"X","quien":"ejecutor","origen":"modelo","conf":0.3,"refs":[],"texto":"render() ya respeta el orden _ORDEN, asi que R3 deberia salir primero.","prov":{"tipo":"dicha"},"estado":"hipotesis","sha":"b21c8890ff4a12","prev":"..."}
{"n":831,"ts":1755607440.77,"ciclo":7,"t":"hecho","op":"add","id":"F-0119","banda":"F","quien":"ejecutor","origen":"citado","conf":0.9,"refs":[812],"clave":"archivo:cognia/estado/canal.py","valor":"e77a01b3c4d980","texto":"conservacion() devuelve recall_restricciones y recall_trazadores por separado.","prov":{"tipo":"leida","ruta":"cognia/estado/canal.py","linea":444,"cita":"\"recall_restricciones\": _r(vivos_r, len(restr))","sha_fuente":"e77a01b3c4d980"},"estado":"verificado","sha":"b4470ce9182daf","prev":"..."}
{"n":835,"ts":1755607452.03,"ciclo":7,"t":"leccion","op":"add","id":"N-006","banda":"N","quien":"harness","origen":"derivado","conf":1.0,"refs":[813],"texto":"Dar la ruta explicita a pytest: 'pytest -k canal' desde la raiz recoge 0 tests.","prov":{"tipo":"derivada","fn":"destilar_fallo","base":["n:813"]},"firma":"cmd:pytest -k canal","n_veces":2,"sha":"2fa8b310cc47e1","prev":"..."}
{"n":840,"ts":1755607460.55,"ciclo":7,"t":"pendiente","op":"add","id":"E-P1","banda":"E","quien":"ejecutor","origen":"modelo","conf":0.3,"refs":[],"texto":"falta llamador de conservacion() fuera de tests/","prov":{"tipo":"dicha"},"requiere_humano":false,"sha":"77aa01bc9e2d40","prev":"..."}
{"n":903,"ts":1755607980.11,"ciclo":8,"t":"contradiccion","op":"add","id":"C-002","banda":"E","quien":"harness","origen":"medido","conf":1.0,"refs":[812],"clave":"archivo:cognia/estado/canal.py","valor":"1a5f7d9042bb01","texto":"sha registrado e77a01b3c4d980, sha en disco 1a5f7d9042bb01. Editado FUERA del agente.","prov":{"tipo":"ejecutada","cmd":"sha256","args_sha":"11aa22","cwd":"C:/Users/usuario/Desktop/cognia_v2","exit_code":0,"salida_sha":"1a5f7d","salida_bytes":64},"sha":"4ee901bb37c0a1","prev":"..."}
{"n":904,"ts":1755607981.00,"ciclo":8,"t":"tx","op":"add","id":"TX-0008","banda":"E","quien":"harness","origen":"medido","conf":1.0,"refs":[903],"texto":"ABORT G3: A-004 sha cambio. escalera->re-leer y reintentar.","prov":{"tipo":"derivada","fn":"commit.prepare","base":["n:903"]},"sha":"cc10ab4471f2e0","prev":"..."}
{"n":905,"ts":1755607985.40,"ciclo":8,"t":"afirmacion","op":"invalidate","id":"X-0828","banda":"X","quien":"harness","origen":"derivado","conf":1.0,"refs":[828,814],"texto":"afirmacion sin verificacion tras 2 ciclos; V-C1 la contradice.","prov":{"tipo":"derivada","fn":"caducar_afirmaciones","base":["n:828","n:814"]},"sha":"cc10ab4471f2e1","prev":"..."}
```

### 3.6 Las nueve bandas, por PERSISTENCIA (la jerarquía que pidió el dueño)

| Banda | Contenido | Ops | Tope tok | Cómo se re-emite |
|---|---|---|---|---|
| **P** permanente | objetivo, restricciones, definición-de-hecho, criterios congelados | `add` (ciclo 0), `amend` (**sólo** humano o contrato) | **900** | **VERBATIM, entera, byte-idéntica. Sin selección JAMÁS** |
| **T** trazadores | 6 canarios con ID aleatorio no inferible | `add` (ciclo 0) | **120** | verbatim |
| **N** negativo | contador `firma → n, exit` + ≤6 lecciones **imperativas positivas** + cola 160 chars del **último** error | `add`, `supersede` | **300** | topes duros |
| **D** decisiones | ≤20 vivas, cada una con `base` a eventos **vigentes** | `add`, `supersede` | **600** | **cae sola si su base se invalida** |
| **F** hechos | ≤25 vigentes, con estado epistémico y confianza | `add`, `invalidate`, `stale` | **750** | render generacional |
| **A** artefactos | ruta + sha256 + última verificación + `critico:bool` | `add`, `stale` | **540** | críticos primero |
| **E** estado | posición + "SOLO FALTA" + contradicciones vivas (**sin tope**) | derivada de disco | **250** | recomputada en el commit |
| **Q** control | 3 preguntas con respuesta literal en el LIBRO | derivada | **90** | al final (recitación) |
| **X** charla | prosa, razonamiento, trazas crudas de error, `afirmacion` | — | **0** | **MUERE EN EL RESET** |

**Total: 3.550 ± 90 tokens.**

> **Corrección al documento de arquitectura, dicha en voz alta:** `arquitectura.md` §4.1 declara
> "3.050 ± 90" pero sus bandas suman **3.550**. Adopto 3.550 y recalculo el prefill del peor caso con
> el ajuste medido `t(n) = 0,33876·n + 1,377e-6·n² ms` `[M]`: **1,22 s**, no 1,08 s. La maquinaria
> pasa de 2,6 s a **2,72 s** y el ratio del peor caso de 4,9 % a **5,2 %** — sigue bajo el 7 %.

**Orden `P T N D F A E Q`**: lo inmutable delante (caché de prefijo), lo volátil al final (el corte
de caché es **distancia absoluta ~512 tokens** `[M]`), y la recitación en la última posición
(U-shape `[L]`; +4 % en RULER por recitar la evidencia antes de resolver `[L]`).

**"Charla descartable" corregido:** muere la **traza cruda** (banda X); viaja la **lección destilada
mecánicamente** (`comando + exit + cola 160 chars` → una línea en imperativo positivo) y el
**contador de firmas**. Conserva la señal anti-loop —la única no correlacionada que existe— y elimina
la traza de errores que produce self-conditioning `[L]`.

### 3.7 Estados epistémicos y transiciones (4 estados, 3 relaciones)

```
                 verificador con examen_ok=1 y exit esperado
   hipotesis ───────────────────────────────────────────────► verificado
       ▲                                                          │
       │ verificador entra en cuarentena                          │ re-verificación falla
       │ (control negativo suspendido)                            │ ó >60 ciclos sin re-verificar
       │                                                          ▼
       └──────────────────────── sospechoso ◄─── contradicción por clave (ambas caen)
                                     │
                                     │ evidencia destruida / superada / retractada
                                     ▼
                                invalidado   (NO se borra: se marca en su sitio)
```

Relaciones: `deriva_de` (refs), `invalida` (op `invalidate`), `contradice` (misma `clave`, distinto
`valor`). `satisface`, `veta` y `requiere` son derivables del contrato y de los anticuerpos: no se
almacenan.

---

## 4. PROTOCOLO ENTRE AGENTES

### 4.1 Reglas duras (las cinco)

1. **Subagentes SECUENCIALES, nunca en paralelo** sobre el mismo backend. El +90,2 % de Anthropic se
   compra con **15× tokens**, y el uso de tokens explica el **80 % de la varianza** `[L]`; con 1 slot
   eso se paga en tiempo de pared. Y cambiar de agente invalida la caché: **10,68 s vs 0,28 s** `[M]`.
2. **El prompt del subagente es un SUFIJO del prefijo del padre**: `[system][banda P][banda T] +
   <misión>`. Como P y T son byte-idénticas, la caché se reusa (cabecera 16k + cola distinta:
   **242 ms vs 5.830, 24×** `[M]`) y los 10,68 s bajan a ~0,3 s `[D]`.
   **Las restricciones NUNCA se filtran por ámbito**: filtrarlas es la selección que midió 0,526 `[M]`.
3. **El subagente NO devuelve prosa. Devuelve eventos de LIBRO tipados**, con la `prov` que el
   interceptor grabó durante *su* ejecución. Hoy `agent/tools.delegar_subtarea` devuelve 600 chars
   lossy: **eso era exactamente el resumen-de-resumen** que este diseño existe para eliminar.
4. **Un solo escritor**: sólo el proceso padre hace `append`. Es lo único en lo que Anthropic y
   Cognition coinciden.
5. **Su contexto se destruye al volver** y no queda rastro suyo en la ventana del padre.

### 4.2 Quién puede escribir qué — matriz normativa

| `quien` | P | T | N | D | F | A | E | X | Puede poner `estado=verificado` |
|---|---|---|---|---|---|---|---|---|---|
| `usuario` (dueño) | **add/amend** | — | — | — | — | — | resolver | — | sí (`origen=usuario`) |
| `harness` (interceptor, gates) | add (derivada de CLAUDE.md) | add (ciclo 0) | add/supersede | invalidate | add/invalidate/stale | add/stale | add | — | **sí, y es el único que lo hace por defecto** |
| `ejecutor` (el modelo) | **NO** | **NO** | vía `leccion` | vía `decidir` (`hipotesis`) | vía `afirmar` (`hipotesis`) | **NO** | vía `pendiente` | libre | **NO** |
| `critico` | **NO** | **NO** | add | **NO** | invalidate | **NO** | add | — | **NO** (§6) |
| `sub` (subagente) | **NO** | **NO** | add | add (`hipotesis`) | add (`hipotesis`) | **NO** | add | — | **NO**, salvo sus eventos de `autor=interceptor` |

### 4.3 Mensajes

**Misión (padre → subagente)** — se materializa como sufijo del prompt, no como fichero:

```json
{"tipo":"mision","tx":"TX-0041","rol":"lector",
 "objetivo":"localizar todos los llamadores de canal.conservacion fuera de tests/",
 "criterio_de_hecho":"una lista de rutas:linea, cada una verificable con grep",
 "tope":{"pasos":6,"segundos":180},
 "tools_permitidas":["ctx_grep","leer_archivo","ejecutar"],
 "prohibido":["escribir_archivo","editar_archivo","borrar_archivo"]}
```

**Retorno (subagente → padre)** — **eventos, no prosa**:

```json
{"tipo":"retorno","tx":"TX-0041","pasos":4,"segundos":37,
 "eventos":[
   {"t":"hecho","banda":"F","clave":"archivo:cognia/agent/loop.py","valor":"c41d0e77aa1290",
    "texto":"loop.py:1077 lee resp.usage.prompt_tokens y lo descarta",
    "prov":{"tipo":"leida","ruta":"cognia/agent/loop.py","linea":1077,
            "cita":"resp.usage.prompt_tokens","sha_fuente":"c41d0e77aa1290"},
    "estado":"hipotesis"}],
 "sin_resultado":false,
 "envelope":{"tools_llamadas":9,"errores":1,"vetos":0}}
```

**Regla del vacío ruidoso:** si el subagente no encuentra nada, devuelve `"sin_resultado": true` con
`eventos: []`. **"Falló" y "no había nada" piden decisiones opuestas** y el envelope las distingue.
Un retorno sin `envelope` se rechaza.

**Regla de ascenso:** todos los eventos de un subagente entran como `hipotesis`, **aunque él los
declare verificados**, salvo los que llevan `quien=harness` porque los escribió *su* interceptor.
Un subagente no asciende nada por su cuenta.

### 4.4 El presupuesto de contextos calientes: **2 de trabajo + 1 cabecera**

Medido: la caché aguanta `min(4 estados, ~1 GiB)` y **el acierto cae a cero de golpe**, no degrada
(4×2k → 4/4; **5×2k → 0/5**; 3×4k → 3/3; 2×8k → 2/2; **3×8k → 0/3**) `[M]`.
Lo que se mantiene caliente **no es la proyección**: es el **contexto vivo** del ciclo, que crece a
~12k tok = 384 MiB. Dos = 768 MiB, más una cabecera precalentada de 3,5k = 114 MiB → **882 MiB, cabe**.
Un tercer agente vivo simultáneo = 1,15 GiB y **tira los tres**. `--cache-ram` por encima de 1024 es
RAM de host, no VRAM, y es la palanca barata — **pero hay que medirla antes de contarla** (E7).

---

## 5. COMPRESIÓN Y RECUPERACIÓN

### 5.1 El algoritmo (esto es todo el "compresor": 0 tokens de LLM)

```python
def proyectar(eventos: list[dict], topes: dict[str,int]) -> str:
    """PURA. Sin LLM, sin red, sin más disco que el LIBRO. 5-150 ms."""
    # 1. FOLD: un solo paso por el libro, O(n)
    vivos, invalidados, firmas = {}, set(), {}
    for e in eventos:
        if e["op"] in ("invalidate", "supersede"):
            invalidados.add(e["id"]); 
        if e["op"] == "stale":
            vivos[e["id"]]["estado"] = "sospechoso"; continue
        if e["t"] == "comando":
            f = e["clave"]; firmas[f] = firmas.get(f, 0) + 1     # senal negativa comprimida
        if e["op"] in ("add", "amend", "supersede"):
            vivos[e["id"]] = e
    # 2. PODA POR DEPENDENCIA: una decision cae sola si su base murio
    for d in [v for v in vivos.values() if v["t"] == "decision"]:
        if any(b in invalidados for b in d["prov"].get("base", [])):
            invalidados.add(d["id"])
    # 3. RENDER POR BANDA, en orden monotono de n (NUNCA por recencia)
    out = []
    for banda in ("P","T","N","D","F","A","E","Q"):
        filas = [v for v in vivos.values() if v["banda"] == banda]
        filas.sort(key=lambda v: v["n"])                          # regla generacional
        out.append(render_banda(banda, filas, invalidados, topes[banda]))
    return "\n".join(out)
```

- **La banda P NO pasa por `topes`.** Si no cabe: **HARD_STOP**, nunca recorte (§9.4).
- El fold es idempotente y determinista: mismo libro → misma salida byte a byte (**I2**).
- Se verifica en cada reset recomputando el fold completo y comparando sha contra `fold.json`.

### 5.2 REGLA DE RENDER GENERACIONAL (sin ella el reset cuesta ~4× más)

El corte de la caché de llama.cpp no es un porcentaje, es **distancia absoluta ~512 tokens**:
95 % de prefijo común reusa (516 procesados de 8k), **90 % no** (8.039) `[M]`. Insertar una línea
**en mitad** de 16k cuesta 5.826 ms contra 242 `[M]`. Por tanto:

1. Cada banda se emite en **orden monótono de `n`**, nunca por recencia.
2. Una fila invalidada **no se quita: se marca en su sitio** con `†` hasta que su generación se cierre.
3. Cada banda se parte en **generaciones de 25 filas**. Las generaciones cerradas son **congeladas y
   byte-idénticas para siempre**. Sólo cambia la generación abierta.
4. La expulsión ocurre **a granularidad de generación**: se colapsa la más vieja a
   `… 94 hechos mas antiguos -> /libro grep`. Eso paga un prefill completo, **una vez cada ~25 expulsiones**.

| Escenario | Prefill del reset | Frecuencia |
|---|---|---|
| Render generacional, prefijo caliente | **0,12–0,28 s** `[D]` | ~24 de cada 25 resets |
| Expulsión de generación (prefill completo, 3.550 tok) | **~1,22 s** `[M/D]` | 1 de cada ~25 |
| Sin la regla | **~1,22 s** | **todos** |

**Se decide con E6, no por fe.** Si el ahorro medido es <2×, se quita la regla y se aceptan los 1,22 s.

### 5.3 Presupuesto de tokens, partida por partida

| Partida | Tokens | Segundos | Origen |
|---|---|---|---|
| Compresión (proyectar) | **0 tokens de LLM** | 0,005–0,150 | `[M]` fold en Python |
| Rehidratación, caso normal (prefijo caliente) | 3.550 (300–700 nuevos) | **0,12–0,28** | `[D]` §5.2 |
| Rehidratación, peor caso | 3.550 | **1,22** | `[M]` ajuste `t(n)` |
| Q1..Q3 (decode ~80 tok) | 80 | **1,30** | `[M]` 55–65 tok/s |
| Gates G1,G3,G4,G6,G7 | 0 | **0,05** | `[D]` hashing + `GROUP BY` |
| G5 contrato (criterio barato) | 0 | **≤0,30** | regla §9.5 |
| 2 × `fsync` | 0 | 0,004 | `[M]` NVMe |
| **MAQUINARIA TOTAL (peor caso)** | **80 tok de decode** | **≈ 2,72 s** | |
| Recuperación bajo demanda (`libro_grep`) | ~150–300/llamada, ~2/ciclo | ~0,2 | `[D]` |
| Trabajo útil del ciclo | ~2.400 tok decode + tools | **50–80** | `[D]` 8×300 tok @60 tok/s |

**Ratio de maquinaria = 2,72 / (2,72 + 50) = 5,2 % (peor) · 3,4 % (mejor)** `[D]`.
**Objetivo ≤7 %. Alarma dura al 15 %. Se muestra en cada línea de `/tx estado`.**
**Un cero perpetuo es sospechoso, no sano.**

**El contraste que importa:** compactar con un LLM cuesta **16,49 s** `[M]` = 25–33 % de un ciclo,
**6× esta maquinaria entera**. A 500 ciclos: maquinaria ≈ **23 min** sobre ~12 h de trabajo `[D]`.

### 5.4 Regla de caché: durante un ciclo NADA se reescribe en la ventana

Medido: append puro sólo cuesta lo añadido (+500→514, +1.500→1.506, +3.000→3.018) `[M]`.
Por tanto: las observaciones van al LIBRO (disco). Si el agente necesita algo que no está en la
proyección, lo pide con `libro_grep` y **llega como turno nuevo al final**. **Cero invalidaciones de
caché por ciclo.** Es la versión ejecutable de *"memoria al principio e inmutable; lo que cambia, al
final"*, y es la razón de que la banda E se recompute **sólo en el commit**.

### 5.5 Recuperación: lo que no cabe vuelve bajo demanda

| Tool | Uso | Coste | Fallo |
|---|---|---|---|
| `libro_grep <regex> [--banda B] [--ciclo n]` | "¿qué decidí sobre pickle?" | 10–40 líneas, <300 tok | **RUIDOSO**: `0 hits` va en el envelope |
| `libro_ver <n> [--contexto k]` | el evento, sus vecinos y su cadena de `refs` | <200 tok | ruidoso |
| `libro_auditar <n>` | cadena de provenance hasta eventos medidos, con confianzas | <250 tok | ruidoso |

Reusa `agent/rlm.ContextoVivo` + `_ctx_grep`, que ya sostiene corpus de 300M tokens a coste
constante `[M, proyecto]`.

**BM25/FTS5 NO es la vía por defecto.** La selección desde almacén inmutable midió **0,526** con
**9 de 24 nunca cargadas** `[M]`: su fallo devuelve un conjunto plausible y equivocado — vacío
silencioso otra vez. Queda **opt-in detrás de E-recuperación**.

### 5.6 Sleep-time compute — con la corrección que lo hace viable

`[L, arXiv:2504.13171]`: ~5× menos cómputo test-time a igual precisión. Con el slot 1 libre mientras
corre un `pytest` de 40 s, la condición se cumple. **Pero el ataque A12 es real:** precalentar en el
slot 0 destruye la caché que se quiere calentar (+10,6 s/ciclo `[D]`). Corrección normativa:

- El precalentado va **SIEMPRE al slot 1**, nunca al slot 0.
- Sólo se precalienta el **prefijo estable** (`P T N` + generaciones cerradas), nunca la proyección
  completa (que aún no existe: el ciclo no ha terminado).
- Sólo se dispara si hay ≥15 s de tool en vuelo y el slot 1 está ocioso.
- **Si E7 no mide un ahorro ≥2× en el reset siguiente, se apaga.** Swap caliente medido: **59 ms vs
  2.840 (48×)** `[M]` — es la única razón por la que merece intentarlo.

---

## 6. AGENTE CRÍTICO

### 6.1 La decisión, con el dato que la fuerza

`falsacion.md` H3: exactitud balanceada **0,517 y 0,523** = azar. Prompt "crítico y riguroso":
detecta 43/43 erróneas **y rechaza 58/60 correctas**. Prompt neutro: **aprueba 41/43 errores reales**.
**El adjetivo del prompt mueve la detección 21×** `[M]`. La literatura coincide: la crítica emerge
sólo con escala y falla justo donde el modelo está más incierto; ≤13B sólo ganan con verificador
fuerte; self-preference bias de −38 % a +90 % `[L]`.

> **El crítico principal de este sistema no es un LLM. Es código que ejecuta.**
> **En la ruta crítica del commit no hay ni una llamada de juicio.**

### 6.2 Qué ve exactamente cada capa, con qué presupuesto, y qué puede vetar

| Capa | Qué es | Qué VE | Presupuesto | Qué puede VETAR | Qué NO puede |
|---|---|---|---|---|---|
| **K0 — Gates del commit** | 7 comparaciones mecánicas: sha256, exit codes, substring literal, `GROUP BY`, igualdad de bytes | El LIBRO y el disco. **No ve prosa** | **~50 ms + ≤300 ms de G5** | El **reset** (fuerza MODO ANCHO) | Matar la tarea (sólo la escalera §9.3 puede) |
| **K1 — Control negativo** | El verificador tiene que **SUSPENDER** con la evidencia destruida | Una copia del workspace con el fichero renombrado/truncado/la línea borrada/el campo a `null`/la cita retirada | **1 ejecución por verificador NUEVO** ≈ 36 s en 500 ciclos `[D]` | El **ascenso** a `verificado` de todo lo que conceda ese verificador | Opinar sobre el contenido |
| **K2 — Comparativo A vs B** | `agent/workflows.criticar` en slot 1, **sólo** con dos candidatos, **nunca** "¿está bien esto?" | Banda P verbatim + los dos candidatos. **NADA de la traza del ejecutor** | ~2 s, ≤1/ciclo | Nada. **Emite un `pendiente`**, no una decisión | Conceder `verificado` |
| **K3 — Oráculo de otra familia** | `harness/oraculo.py`, transporte inyectado | Banda P + la pregunta | **Máx. 5 consultas por tarea** | Nada. Su salida entra como **`pendiente`** | Conceder `verificado`. Si no hay oráculo: `sin_oraculo` y la fila **se queda `sospechoso`** — nunca asciende por defecto |
| **Q1..Q3** | Prueba de **lectura**, no de juicio: 3 preguntas cuya respuesta es una cadena literal del LIBRO | La proyección nueva | ~1,3 s (decode 80 tok) | El commit (→ recitación → MODO ANCHO) | **Matar la tarea. NUNCA.** |

### 6.3 Cómo se evita que el crítico apruebe errores — la asimetría, explícita

1. **Ningún LLM concede `verificado`.** El ascenso lo concede un **exit code** o un **sha**, nunca una
   opinión. Es una restricción de esquema (§3.2, `allOf`), testeable.
2. **G7: ningún verificador puede conceder nada antes de haber suspendido su control negativo.**
   Ataca de frente *"el test que pasa por el motivo EQUIVOCADO"*: cinco instrumentos aprobaron algo
   roto en una noche y ninguno falló. Coste: ~36 s en toda la corrida `[D]`.
3. **`poder_discriminante`** = |verificadores que han fallado alguna vez| / |verificadores|.
   Un verificador que en 500 ciclos nunca falló es sospechoso de ser trivial. **Alarma en rojo por
   debajo de 0,25.**
   **Corrección al diseño de grafo, dicha en voz alta:** su centinela contaba el fallo del control
   negativo como "fallo", y el control negativo **está diseñado para fallar siempre** — el termómetro
   marcaba 1,00 el 100 % del tiempo. Aquí `poder_discriminante` cuenta **sólo fallos en ejecución
   real**, nunca los del examen. Es un test unitario del MVP.
4. **Asimetría de consecuencias, declarada:** un falso negativo de Q (dice OK y la memoria se perdió)
   cuesta cientos de ciclos de degradación silenciosa; un falso positivo cuesta un ciclo en MODO
   ANCHO (~+3 s). Por tanto **umbral estricto 3/3 y consecuencia barata**.
5. **K2 existe si y sólo si E3 lo aprueba.** El absoluto ya está medido en 0,52; si el comparativo no
   supera **0,58 con n=103**, **se borra el componente**.
6. **`tasa_de_abort == 0` durante 50 ciclos es AVERÍA DEL GATE, no salud.** `/tx mutar` corrompe la
   proyección a propósito cada 25 ciclos y **exige** detección 1,000 (§15, E1).

### 6.4 El fuzzy se calcula, se muestra y NO VOTA

`canal._presente()` usa cobertura de tokens con `UMBRAL_COBERTURA = 0.6` (`canal.py:73,117`).
**Una paráfrasis puntúa "presente" con el ID perdido.** Por tanto:

> **El gate sólo admite igualdad de bytes, igualdad de ID exacto, o exit code.**
> `canal.conservacion()` se calcula, se registra y se muestra en `/tx estado`, y **no vota**.
> Si el fuzzy da 0,92 y los exactos pasan → commit, y se anota la discrepancia.
> Si el fuzzy pasa y un exacto falla → **aborta**.

### 6.5 G2 no se mide contra la proyección (corrección del ataque A13)

`canal.comprobar_trazadores(estado, texto)` cuenta IDs en un texto, y su premisa es *"lo escribió un
resumidor LLM"*. Aplicarlo a `proy_nueva` —salida de una función pura que **acaba de escribir la
banda T verbatim**— pregunta "¿está en el texto lo que acabo de escribir en el texto?": da 6/6 en el
ciclo 1 y en el 500 y no aporta información.

> **Normativo: G2 se mide sobre la PRIMERA RESPUESTA DE LA SESIÓN NUEVA (el turno de Q), nunca sobre
> la proyección.** Eso sí mide algo: si el modelo *leyó*.
> La comprobación de la proyección se degrada a un **assert de integridad del proyector** (banda T
> presente y byte-idéntica), que es lo que realmente es.

---

## 7. ANTI-ALUCINACIÓN

### 7.1 No es un detector: es una imposibilidad estructural

**El modelo no tiene ninguna tool que escriba un hecho verificado.** Tres capas:

- **Estructural (I3).** Sin `prov` re-comprobable, no hay evento en banda persistente. El `add` se
  rechaza y vuelve al modelo como error de tool.
- **Derivada.** `conf = f(origen)`, nunca del LLM. La confianza autodeclarada produciría **hechos
  falsos con etiqueta creíble**, que es peor que no etiquetar `[M]`.
- **Ejecutada.** Lo que decide un ascenso es un exit code o un sha.

### 7.2 La escalera de ascenso (y por qué la repetición no está en ella)

```
afirmacion (banda X, prov="dicha", conf 0,30)
   │  NO puede subir de banda. NUNCA. Ni repitiendose 3 veces, ni 300.
   │  Caduca a los 2 ciclos si nada la verifica -> op:invalidate.
   ▼
hecho (banda F, prov leida/ejecutada/derivada, estado=hipotesis)
   │  requiere: cita literal + sha_fuente, o exit real, o fn+base
   │  el verificador que lo va a ascender tiene que tener examen_ok=1 (G7)
   ▼
hecho verificado (estado=verificado, conf = base x ex x fr)
   │  se re-verifica: sha en cada commit (criticos), barrido completo cada 25 ciclos
   ▼
sospechoso  (sha cambio / >60 ciclos / contradiccion por clave)  ->  invalidado
```

**La frecuencia NO es evidencia.** `memory/long_term_consolidator.py` asciende a hecho permanente por
repetición ≥3: un agente que repite una invención tres veces la asciende. **Ese módulo se apaga bajo
`COGNIA_TX=1`** y su apagado queda registrado en el LIBRO.

### 7.3 Alucinación persistente: no sobrevive dos commits

**Definición operativa:** un hecho `leida` cuyo fichero cambió, o un `verificado` cuyo verificador ya
no pasa. Mecanismo:

1. G3 re-lee el disco en **cada commit**: `mtime`/`size` movidos → sha256 completo. Los
   `critico:true` se leen **enteros siempre**.
2. Mismatch → `op:stale` → la fila pasa a `sospechoso` y **su `conf` cae a 0,4·base**.
3. Si no se re-verifica en el ciclo siguiente → `op:invalidate` → **desaparece de la proyección**.
4. Toda `decision` cuya `base` contenga un invalidado **cae sola**, sin que nadie opine (§5.1, paso 2).
5. **Barrido completo de artefactos cada 25 ciclos** (~0,4 s `[D]`) y **postcondiciones sobre una
   copia limpia del workspace en el cierre** (`flujos/examen.verificar_postcondiciones`).

### 7.4 `sin_huella` — el caso "el modelo cree que escribió"

Toda afirmación con clave `archivo:` / `cmd:` / `test:` / `err:` que **no tenga una fila de
provenance del interceptor con esa herramienta y ese destino en los últimos 3 ciclos** se marca
`sospechoso` con motivo `sin_huella`, **aunque su verificador pase**. Se mide contra el disco, no
contra el relato.

### 7.5 Aislamiento de lo sospechoso

- Una fila `sospechoso` **se proyecta marcada** (`?`) con su motivo, nunca se oculta: el vacío
  silencioso es el fallo típico de este sistema.
- Un verificador con `cuarentena=1` **revoca todos los ascensos que concedió** (`/libro fsck` lo hace
  en bloque) y las filas vuelven a `hipotesis`.
- `err:verificador_nulo:<id>` entra en banda N como lección imperativa.

### 7.6 Detección de contradicciones

| Regla | Detecta | Mecanismo | Reacción |
|---|---|---|---|
| **C1** | sha registrado ≠ sha en disco | G3 | `stale` + línea "RE-LEE antes de escribir" en la proyección |
| **C2** | dos `verificacion` del mismo criterio con `ok` distinto **sin `fichero` entre medias** | fold | 1ª–2ª: marca `flaky`; **3ª: contradicción**. *Un test flaky es un bug del instrumento, no del agente* |
| **C3** | dos filas vigentes y `verificado` con **misma `clave` y distinto `valor`** | `GROUP BY clave HAVING COUNT(DISTINCT valor)>1` | ambas a `sospechoso`, **re-ejecución inmediata de sus dos verificadores**. Si pasan las dos: bug del verificador, **ambas a cuarentena** y aviso al dueño |
| **C4** | una `restriccion` con ámbito de ruta y un `fichero` sobre esa ruta | interceptor | **VIOLACIÓN: corte inmediato.** Los `TRZ-` están **excluidos** (§2.1.6) |
| **C5** | `resuelto` sin `verificacion` posterior que lo respalde | fold | re-abre el pendiente |
| **C6** | ciclo con 0 eventos medidos | G6 | 2 seguidos → **corte duro** |
| **C7** | Q < 3/3 | commit | recitación → MODO ANCHO |

**Las contradicciones vivas van en la proyección SIN TOPE y BLOQUEAN el cierre de la tarea.**
Cada contradicción cerrada dispara `inmune/anticuerpos.sintetizar()` — porque *una lección en prosa
no impide nada*.

**Punto ciego declarado:** `dec:` y `nota:` están **fuera** de la detección por clave. Para prosa se
puede *detectar* solape+negación, pero **no se auto-resuelve con un LLM** (está en el azar para eso):
se marca y se muestra en `/tx estado`. Es el mismo agujero que §16.3.

---

## 8. SNAPSHOTS, ROLLBACK Y ESTADO CORRUPTO

### 8.1 Cuánto guarda un snapshot (pregunta 10)

**Un snapshot no guarda información: guarda una dirección.** Todo está en el LIBRO, y **cada evento
es un punto restaurable** — no hay "momento de snapshot" que pueda perder nada.

```json
{"tx":"TX-0041","n":1187,"sha_libro":"7c1a0e44bb9032","sha_proy":"9f3c1a4e0b77d2",
 "ckpt_ficheros":214,"arbol_workspace":"arbol/TX-0041.json","ts":1755607981.0}
```

| Cosa | Tamaño | A 500 ciclos |
|---|---|---|
| Manifiesto TX | ~200 B | 100 KB |
| LIBRO | ~4,5 KB/ciclo `[D]` | **2,3 MB** |
| Blob de proyección (12 KB, deduplicado por contenido) | 12 KB | ~2 MB reales |
| Árbol de sha del workspace (400 ficheros × 80 B) | 32 KB | 16 MB → **sólo cada 25 ciclos = 640 KB** |
| **Total** | | **< 10 MB** |

**No hay ninguna razón para borrar nada**, y eso es exactamente lo que hace posible el rollback exacto.

### 8.2 Rollback (pregunta 17)

```
/tx rollback TX-0038 "la refactorizacion del ciclo 39 rompio C2"
```

1. **`proyectar(libro.leer(hasta_tx=TX-0038))`** — exacto, **~5 ms**, **no destructivo**, idempotente.
   No es "volver a un resumen más viejo" (eso sería resumen-de-resumen hacia atrás): es reproyectar
   un prefijo del mismo ledger.
2. **Ficheros:** `harness/checkpoints.restaurar_hasta(m)` **+ el árbol de sha** (§8.3).
3. **Re-verificación OBLIGATORIA** de todo lo restaurado: se re-ejecutan los verificadores de las
   filas que vuelven. Un rollback que no re-verifica es un rollback que miente.
4. **Nada se borra.** Se emite un evento `tx/op:rollback` con `hasta_tx`, culpable y anticuerpo. Los
   eventos de la rama abortada siguen ahí, auditables, marcados.
5. **Pendientes resueltos por eventos invalidados se re-abren** automáticamente.
6. **Visible:** los ciclos siguientes leen `LIBRO: 12 eventos retractados en c39`. Nunca un rollback
   silencioso.
7. `autopsia/causal.atribuir(trayectoria)` (replay contrafactual, precision@1 = 1,000 `[M, proyecto]`)
   da el paso culpable → `inmune/anticuerpos.sintetizar()` planta el veto ejecutable en
   `interceptor.antes`.

### 8.3 El árbol de sha del workspace — corrige el agujero A14

`harness/checkpoints.py` **sólo ve 4 tools** (`escribir_archivo`, `editar_archivo`, `apendar_archivo`,
`borrar_archivo`, vía `interceptor._ESCRIBEN`). **Todo lo que escribe `ejecutar` es invisible:** un
`black`/`ruff --fix` que reformatea 60 ficheros, un build, un `git checkout`, `.pytest_cache`.
Además `_MAX_BYTES_VERSIONADO = 2 MB` y `_MAX_SESIONES = 20` (checkpoints.py:86,89): en 500 ciclos
**los checkpoints viejos se podan**. Un rollback restauraría la mitad del mundo **y diría que cuadra**.

**Normativo:**

- Antes de cada llamada a `ejecutar` cuyo comando **no** esté en una lista blanca de sólo-lectura
  (`grep`, `dir`, `type`, `git status`, `git diff`, `nvidia-smi`, `pytest --collect-only`), se toma un
  **árbol de sha** del workspace: `{ruta: (sha256[:14], size, mtime)}` para todo lo no ignorado por
  `.gitignore`. Coste medido en el MVP; predicción **<0,4 s para ~400 ficheros** `[D]`, y se cachea
  por `mtime+size` (sólo se re-hashea lo movido).
- El árbol se guarda **cada 25 ciclos** completo y **como delta** el resto.
- **`/tx rollback` compara el árbol actual contra el del TX destino y REPORTA lo que no puede
  restaurar**, en vez de decir OK. Si hay ficheros fuera del alcance de `checkpoints`, el rollback
  se declara **PARCIAL** y lo dice, con la lista.
- **Un rollback PARCIAL nunca se marca como éxito** y no permite reanudar sin confirmación humana.

### 8.4 Estado corrupto (pregunta 16)

| Corrupción | Detección | Recuperación |
|---|---|---|
| Línea JSONL truncada (corte de luz, disco lleno) | el parseo falla al cargar | trunca a la última línea válida, emite `contradiccion`, sigue. **Lo dice, no lo esconde** |
| Cadena `prev` rota | el sha no casa | **dos escritores concurrentes**: aborta y avisa (el lock debería impedirlo). Reproyecta el **prefijo válido más largo** |
| `fold.json` desincronizado | re-fold completo + comparación de sha **en cada reset** (I2) | descarta el fold y recomputa. Coste: 0,15 s |
| Disco desincronizado con el LIBRO | G3 / C1 | `stale` → re-lectura forzada |
| DB ilegible entera | el arranque falla | **la banda P se reconstruye de `cabecera.txt`** — doble soporte a propósito. Se pierde el historial, **no el contrato** |
| `verificado` sin `prov` re-comprobable | `/libro fsck` | vuelve a `hipotesis` |
| Verificador con `examen_ok=0` que concedió ascensos | `/libro fsck` | **todos sus ascensos revocados** |
| `prov` huérfana (sin fila que la use) | `/libro fsck` | **se conserva: es evidencia**, no basura |
| LIBRO envenenado (una decisión mala contaminó 30 ciclos) | `autopsia/causal.atribuir` sobre el LIBRO, que es exactamente la traza que ese módulo necesita | rollback al ciclo culpable + anticuerpo |

```
/libro fsck [--reparar]
  cadena prev .......... 1187/1187 OK
  esquema .............. 1187/1187 OK
  verificado sin prov .. 0
  verificadores nulos .. 1  (V-017, 4 ascensos revocados)   [--reparar los revoca]
  prov huerfanas ....... 12 (se conservan)
  cabecera.txt vs P .... sha 9f3c1a4e0b77d2 == 9f3c1a4e0b77d2  OK
```

---

## 9. CONDICIONES: RESETEAR, TERMINAR, ABORTAR, PEDIR AL HUMANO

### 9.1 Cuándo resetear: **disparador ∧ compuerta**

**Disparadores (cualquiera):**

| ID | Condición | Por qué |
|---|---|---|
| **T1** | `acciones_en_ciclo ≥ 8` | H(0,5) ≈ 8 turnos en Gemma3-27B, 15 en Qwen3-32B `[L]`. El 9B es menor: **8 es techo, no meta**. Se calibra con E4 |
| **T2** | `errores_consecutivos ≥ 2` | **El disparador que más importa.** La contaminación es el motivo real (85 %→70 %→55 % `[L]`). Resetear pronto, no tarde |
| **T3** | `contexto_vivo.ocupacion ≥ 0,55 · n_ctx_slot` | **Saturación, no reloj.** Compactar por saturación = 19,8 min/día; por ciclo = **137 min/día** `[M]` |
| **T4** | acaba de satisfacerse un criterio congelado | frontera natural limpia: consolidar la victoria |

**Nunca por reloj de pared.**

**Compuertas (TODAS obligatorias para destruir):** G1..G7 en verde (§1.2), más `p0` (ninguna tool en
vuelo) y `p1` (WAL vacío).

> **Si el disparador salta y la compuerta no abre: NO se resetea.** Se sigue en MODO ANCHO.
> **Resetear es opcional; commitear no lo es** — el LIBRO se escribe siempre, resetee o no.

### 9.2 Cuándo terminar — **triple confirmación mecánica, sin juez**

| Salida | Condición |
|---|---|
| **ÉXITO** | (a) `GoalContract.check()` = **todos** los criterios congelados; **y** (b) G3 al 100 % sobre **todos** los artefactos, re-leídos de disco; **y** (c) `flujos/examen.verificar_postcondiciones` en verde sobre una **copia limpia del workspace**; **y** (d) **0 contradicciones vivas**. Tres confirmaciones independientes + el bloqueo de contradicciones |
| **FALLO-PRESUPUESTO** | `harness/limites.LimiteExcedido` en cualquier eje (segundos / tokens / pasos / USD). Excepción tipada, **ya implementada y hoy huérfana** |
| **FALLO-ESTANCADO** | LOOP-D (`presupuesto_progreso.veredicto()` = agotado) o LOOP-A repetido |
| **FALLO-LOOP** | LOOP-A tres veces, o G6 (ciclo mudo) dos ciclos seguidos |
| **BLOQUEADO** | un `pendiente` con `requiere_humano=true` |

### 9.3 Cuándo abortar el reset — la escalera de 3 escalones

```
GATE falla
 └─1─ robar topes: se sube el tope de la banda culpable robando de N y de A
      (las de menor persistencia), se re-proyecta, se re-prueba.   MÁX 2 intentos
 └─2─ MODO ANCHO: se cancela el reset, se sigue en la MISMA ventana.
      Es una SALIDA LEGÍTIMA, no un parche: es el brazo que midió recall 1,000 [M].
      Acotado: ≤3 ciclos anchos CONSECUTIVOS y ≤10 % de los ciclos de la tarea.
      Por qué acotado: pasados ~20 ciclos anchos el contexto llega a 0,8·n_ctx
      y entra loop._recortar_mensajes -> truncado in-place a 200 chars, sin
      resumen y sin recuperabilidad. El brazo ancho no es caro: DEGRADA EN SILENCIO.
 └─3─ HARD_STOP: se para y se pide al humano PARTIR LA TAREA o RETIRAR RESTRICCIONES.
      ANTES QUE TRUNCAR LA BANDA P. Prefiero un agente que se planta a uno que
      olvida en silencio.
```

`ciclos_anchos` es **métrica de salud visible**, no un contador oculto.

### 9.4 Cuándo pedir al humano (las 5 puertas)

1. **`/tx iniciar` sin criterio verificable** → para y lo pide. (Hoy `horizonte` corre un ciclo mudo.)
2. **`/tx iniciar` sin criterio < 5 s** → para y lo pide (§9.5).
3. **HARD_STOP por banda P que no cabe** (>900 tok) → poda humana o partir la tarea.
4. **`pendiente` con `requiere_humano=true`**: credencial ausente, decisión de producto, permiso.
   **Se para y se pregunta**, no se queman 400 ciclos adivinando.
5. **Contradicción cuyos dos verificadores pasan** (bug del verificador) o **rollback PARCIAL**.

### 9.5 La regla del criterio barato (cierra el único agujero grande del ratio)

Si el criterio por ciclo es un `pytest -q` de 40 s, G5 sube el overhead al **31 %** `[D]` y el diseño
se cae. Peor: `agent/tools._shell` tiene `timeout: int = 30` por defecto y **tope duro 600 s**
(tools.py:1656, 1732), y la suite de este repo son **6.909 tests / 12 min**: hoy es **inejecutable**
como criterio por las dos vías.

- `coste_ms` de cada criterio **se mide en su primera ejecución** y se guarda en el LIBRO.
- El criterio **por ciclo** debe costar **< 5 s**. Si no existe ninguno, `/tx iniciar` lo pide.
- Los criterios **caros** corren **sólo si G3 detectó cambio en un artefacto `critico:true`**, **como
  máximo 1 de cada 3 ciclos**, y **siempre en el cierre**. Si nada cambió, el resultado anterior vale
  por construcción: mismos bytes → mismo exit.
- **Siempre en proceso nuevo con `cwd = workspace`**: `GoalContract` resuelve rutas contra el CWD del
  proceso, que es un bug identificado en el inventario.
- Un criterio que exceda su timeout **no cuenta como FAIL**: cuenta como `flaky` de instrumento (C2)
  y **no dispara rollback**.

---

## 10. LOOPS Y ERRORES

### 10.1 Cinco detectores, todos mecánicos. **Ninguno pregunta a un LLM si "parece un bucle".**

| ID | Detector | Umbral | Acción |
|---|---|---|---|
| **LOOP-A** | `sha256(conjunto ordenado de (tool, ruta_destino))` del ciclo **+** conjunto de criterios satisfechos | misma firma **2 ciclos seguidos** sin criterio nuevo | línea en banda N + **prohibición** de repetir ese conjunto; 3ª vez → `FALLO-LOOP` |
| **LOOP-B** | misma `(tool, ruta_destino, sha(args))` con **mismo sha de salida** | 3 veces en un ciclo | `anticuerpos` genera el veto **en caliente**; la 4ª llamada devuelve el veto como error de tool |
| **LOOP-C** | oscilación: el sha de un fichero alterna A→B→A entre ciclos | 1 oscilación completa | se **congela** el fichero (anticuerpo) y se abre un `pendiente` para el humano |
| **LOOP-D** | `estado/presupuesto_progreso.coste_sin_avance()` | > 3× la mediana de coste por avance verificado | `veredicto()` = agotado → `FALLO-ESTANCADO` |
| **G6 / C6** | **ciclo mudo**: 0 eventos medidos | 2 ciclos seguidos | **corte duro** |

**Por qué G6 es imprescindible y por qué va bajo mutación:** un ciclo de pura prosa **no tiene firma
que repetir**. Proyección idéntica → respuesta idéntica → **punto fijo determinista y silencioso**:
LOOP-A/B/C no lo ven. Y un bug de conteo en G6 desactiva la única defensa contra él, así que G6 entra
**bajo `/tx mutar`** (§15, E1). Ésa es la síntesis: la defensa de un diseño, vigilada por el
instrumento de otro.

### 10.2 Pérdida del objetivo — se BLOQUEA la acción, no se refuerza el recordatorio

La adherencia conductual medida es **plana**: 0,750 / 0,708 / 0,750 a 0,4k / 32k / 128k tokens `[M]`.
**El 25 % de incumplimiento no lo causa la profundidad**, luego recordar más fuerte no lo arregla.

**Detector de acción huérfana**, en `interceptor.antes` (que ya es el enchufe único):
`ruta_destino(name, args)` se compara contra el conjunto de rutas/entidades derivable de los
**criterios congelados + los `pendientes` abiertos**. Sin correspondencia → la llamada se marca
`HUERFANA`: **se deja pasar y se cuenta**.

- `huerfanas / total > 0,40` en un ciclo → **DERIVA**: se aborta el ciclo, se resetea con **recitación
  de los criterios como primer turno**, y queda registrado.
- La banda P es byte-congelada (G1), así que el objetivo **declarado** no puede derivar por
  construcción. Lo que se vigila es la **conducta**.
- Segundo detector: **monotonía del contrato** (G5). Retroceso = deriva por definición.

### 10.3 Taxonomía de errores y qué se hace con cada uno

| Clase | Ejemplo | Qué se guarda | Qué se destruye |
|---|---|---|---|
| **Error de herramienta** | exit ≠ 0 | `comando` con exit real + cola 160 chars + `firma → n` | la traza cruda completa (banda X) |
| **Error bloqueado por el sentinel** | `BLOQUEADO por Sentinel` | evento con `exit_code = null` y `origen = medido` **prohibido** → `origen = derivado`, `conf` de la fuente. **NUNCA `exit 0`** | — |
| **Timeout** | 30 s / 600 s | `flaky` de instrumento (C2), **no** FAIL | — |
| **Excepción del propio TX** | disco lleno al hacer `append` | **`LibroCaido`, excepción tipada, PARA EL CICLO Y LO DICE** | — |
| **Flaky del gate** | test que alterna sin cambio de fichero | 1ª–2ª `flaky`, 3ª contradicción | — |

**Normativo (corrige el ataque A9):** la escritura del LIBRO **no vive dentro del
`except Exception: pass` del interceptor** (11 ocurrencias hoy, contrato "degrada a no hacer nada").
Eso es correcto para hooks y offloading; para el LIBRO convierte cada fallo de disco en un **vacío
silencioso — apagaría la memoria entera sin emitir un error**. `tx/libro.append` tiene su **propio
canal con envelope** y lanza `LibroCaido`.

---

## 11. VRAM Y TOKENS: LA ESTRATEGIA REAL

### 11.1 Lo que NO ahorra (dicho primero)

- **El reset ahorra 0 MiB de VRAM.** 13.168 @2.944 tok → **13.155 @187.874 tok**; 626 muestras,
  amplitud 21 MiB (0,16 %), y el consumo **baja** `[M]`. El KV se reserva entero al cargar:
  `CUDA0 KV buffer size = 1792.00 MiB` a los **0,793 s**, antes de `listening on` `[M]`.
- **El multiagente ahorra 0 MiB y además cuesta**: 10,68 s vs 0,28 s por invalidación de caché `[M]`.
- **El argumento del reloj está inflado en los tres diseños previos.** El append puro sólo cuesta lo
  añadido (+3.000 → 3.018 procesados) `[M]`: una sesión que sólo crece paga el delta, no el total.
  Lo que sí se paga entero es **cada invalidación de caché**, y ese coste **escala con el tamaño**:
  a 64k una invalidación cuesta 27,3 s; a 12k, ~4,4 s `[M]`. El reset convierte un peor caso de 27 s
  en uno de 4 s. Ésa es la ganancia real de reloj, y es secundaria frente a la higiene.

### 11.2 Lo que sí se decide: la configuración de arranque

```
llama-server -m Huihui-Qwythos-9B-...-Q4_K.gguf --ctx-size 65536 --parallel 2 --cache-ram 1024
```

| Partida | MiB | Origen |
|---|---|---|
| Pesos | 5.357,9 | `[M]` |
| KV: 65.536 tok × 32 KiB/tok (f16) | 2.048 | fórmula validada **6/6** `[M]` |
| Estado SSM: 50,25 × 2 slots | 100,5 | `[M]` |
| Overhead (compute buffers) | ~1.490 | cuadre real `[M]` |
| **Total** | **~8.996** de 16.311 | **libera 4,2 GB** |

**Dos slots de 32.768 tokens sobre UNA sola copia de pesos**, cada uno con su caché (no se desalojan
entre sí). **Slot 0 = ejecutor. Slot 1 = crítico comparativo / oráculo / precalentado.**

**La aritmética usa 8 capas de ATENCIÓN de 33 bloques.** Los modelos son híbridos `qwen35`
(24 SSM + 8 atención + 1 NextN ignorado). **Contar `n_layer=33` se equivoca 4×** `[M]`.
Fórmula: `bytes/token = capas_ATENCIÓN × n_head_kv × (k_len+v_len) × bytes_elem`.
9B: **32 KiB/tok f16**, 17 KiB q8_0 `[M]`. 27B: 64 KiB f16.

**KV en f16, no q8_0.** Ahorraría ~960 MiB más, pero **nadie ha medido calidad con q8_0 en este
proyecto** y toda esta arquitectura depende de que el modelo lea sus propias restricciones sin
degradarse. Queda como experimento (E7), no se adopta a ciegas.

**Compuerta obligatoria** — en `ctx=16384` llama.cpp pidió 1.792 MiB y la VRAM subió 2.582:
**desbordó a RAM compartida de Windows sin emitir un solo error**, con CUDA reportando
"14987 MiB free" `[M]`.

```
/tx vram --verificar
  esperado (formula) 8.996 MiB · medido (nvidia-smi) 8.981 MiB · delta 0,17 %   OK
```

> **|delta| > 3 % ⇒ el CLI SE NIEGA A ARRANCAR el modo largo.**

**Los 4,2 GB liberados no son un ahorro: son una COMPRA.** Compran el crítico de otra familia, que es
lo que el estado del arte exige (≤13B sólo ganan con verificador fuerte; self-preference bias de
−38 % a +90 % `[L]`) y lo que la lección propia ya dijo: *Cognia era mono-familia (Qwen); el primer
modelo de otra familia destapó 3 fallos silenciosos*.

### 11.3 Tokens: el resumen de una tarea de 500 ciclos

| Partida | Valor | Origen |
|---|---|---|
| Compresión | **0 tokens de LLM**, ~2,5 s de CPU en total | `[M]` |
| Rehidratación | 500 × 3.550 = **1,78 M tokens de prefill** | `[D]` |
| — con render generacional | ~500 × 500 nuevos = **0,25 M**, ≈ **2,0 min** | `[D]`, se decide con E6 |
| — sin la regla (peor caso) | **10,2 min** | `[M]` `t(n)` |
| Q1..Q3 | 500 × 80 tok de decode = **10,8 min** | `[M]` 55–65 tok/s |
| `libro_grep` bajo demanda | ~2/ciclo × 200 tok = 200k tok ≈ **1,3 min** | `[D]` |
| **Subsistema de memoria completo** | **≈ 14–23 min sobre ~12 h** = **1,9–3,2 %** | `[D]` |

---

## 12. LAS 18 RESPUESTAS

| # | Pregunta | Respuesta y dónde está implementada |
|---|---|---|
| **1** | Qué es sólido | Destruir el contexto **por higiene** (self-conditioning 85→55 %, no lo arregla escalar `[L]`) y por **el muro del ciclo ~20** (`_recortar_mensajes`); la jerarquía **por persistencia**; el canal de estado explícito (recall 0,07 → 1,00 `[M]`); subagentes secuenciales con contexto sellado. **§2, §3.6, §4** |
| **2** | Qué fallará | **Todo lo justificado por VRAM** (0 MiB `[M]`); **toda selección de restricciones** (0,526 `[M]`); el **crítico LLM absoluto** (0,517 `[M]`); la **confianza autodeclarada**; la **compresión con LLM** (16,49 s `[M]`); el **resumen encadenado** (24→2 en un paso `[M]`); **"ventana corta"** (sirve 200.192 tok); **"charla descartable"**. **§0** |
| **3** | Tras cientos/miles de ciclos | LIBRO **<10 MB a 500 ciclos**; proyección **constante en 3.550 tok** por construcción. Lo que crece y rompe: **banda P** (§16.1) y **saturación de F/A hacia el ciclo ~120** (§16.2). **§8.1, §16** |
| **4** | Evitar degradación de memoria | **Teorema, no disciplina** (I2): `proyectar()` es función pura de un ledger append-only; **no existe la operación resumen→resumen**. Se verifica recomputando el fold y comparando sha en cada reset. **§1.4, §5.1** |
| **5** | Alucinaciones persistentes | `dicha` **no puede entrar** en P/D/F/A (restricción de esquema, testeable): vive en X y muere en el reset. Techo 0,30 **sin ascenso por repetición**. G3 re-lee el disco en cada commit: un `leida` cuyo sha cambió pasa a `stale` y, si no se re-lee, `invalidate`. **No sobrevive 2 commits.** **§3.2, §7.2, §7.3** |
| **6** | Que el crítico no valide errores | En la ruta crítica **no hay juicio**: sha256, exit codes, substring literal, `GROUP BY`, igualdad de bytes. **G7: ningún verificador concede nada sin haber SUSPENDIDO su control negativo.** K2 sólo comparativo y sólo si E3 lo aprueba. `poder_discriminante` < 0,25 = alarma. **§6** |
| **7** | Loops infinitos | Contador `firma → n` en banda N + **LOOP-A/B/C/D mecánicos** + veto ejecutable en `interceptor.antes` + anticuerpo sintetizado + `presupuesto_progreso.veredicto()` + **G6 ciclo mudo bajo mutación**. **§10.1** |
| **8** | Pérdida del objetivo | G1 (P byte-congelada) + G2 (trazadores **en la respuesta**) + Q (recitación obligatoria) + **acciones huérfanas > 40 % ⇒ DERIVA** + G5 monotonía. **Se BLOQUEA la acción**, no se refuerza el recordatorio: la adherencia es **plana en 0,75** `[M]`. **§10.2** |
| **9** | Cuándo resetear | **T1** 8 acciones ∨ **T2** 2 errores ∨ **T3** 0,55·n_ctx ∨ **T4** criterio sellado, **∧ G1..G7 en verde**. Si la compuerta no abre: **MODO ANCHO acotado**. **Nunca por reloj.** **§9.1** |
| **10** | Cuánto guarda un snapshot | Un snapshot es un **manifiesto de ~200 B**: `{tx, n, sha_libro, sha_proy, ckpt, arbol}`. No guarda información: guarda una **dirección**. LIBRO 4,5 KB/ciclo. **<10 MB a 500 ciclos.** **§8.1** |
| **11** | Estructura de la memoria | **9 bandas por persistencia** `P T N D F A E Q` + `X` que muere, sobre **16 tipos de evento**, **6 ops**, **4 estados epistémicos**, **3 relaciones**, **vocabulario de claves cerrado**. **§3** |
| **12** | Provenance y confianza | **5 tipos de `prov`, cada uno con re-verificador PURO**; las 6 columnas de origen las escribe `interceptor.despues()`; `conf = base × examen × frescura`, **recalculable desde disco**; `/libro auditar <n>` imprime la cadena hasta eventos medidos. **El modelo no tiene esos campos.** **§3.3, §7** |
| **13** | Coordinar agentes | **Secuenciales**; prompt = **sufijo del prefijo del padre** (caché 24× `[M]`); retorno en **eventos, no prosa**; **un solo escritor**; contexto destruido al volver; sus filas entran como `hipotesis`; **2 contextos calientes + 1 cabecera**. **§4** |
| **14** | Minimizar VRAM | **El reset no la toca: 0 MiB.** Se minimiza **en el arranque**: `--ctx-size 65536 --parallel 2` ⇒ 13,2 → **9,0 GB**. Compuerta `nvidia-smi` vs fórmula, **>3 % no arranca**. Los 4,2 GB **compran el crítico de otra familia**. **§11** |
| **15** | Minimizar tokens de compresión/recuperación | Compresión: **0 tokens de LLM**, 5–150 ms. Rehidratación: 3.550 tok = **0,12–0,28 s** (generacional) a 1,22 s. Recuperación: `libro_grep` bajo demanda, <300 tok, **fallo ruidoso**. **Maquinaria ≤7 % del ciclo, medida y mostrada.** **§5.3** |
| **16** | Estado corrupto | Cadena `prev` rota = **detectable** ⇒ reproyectar el prefijo válido más largo. `/libro fsck --reparar`. DB ilegible ⇒ **banda P se reconstruye de `cabecera.txt`** (doble soporte a propósito). `prov` huérfana **se conserva: es evidencia**. **§8.4** |
| **17** | Rollback | `proyectar(libro.leer(hasta_tx))` — **exacto, 5 ms, no destructivo, idempotente** — + `checkpoints.restaurar_hasta(m)` **+ árbol de sha del workspace** + **re-verificación obligatoria**. Un rollback que no puede restaurar todo se declara **PARCIAL** y lo dice. **§8.2, §8.3** |
| **18** | Evaluación experimental | **E0 (brazo nulo) primero**, KILL pre-registrado, brazos intercalados, netos apareados, n≥6, mutación permanente del gate. **§15** |

---

## 13. COMPARACIÓN HONESTA CON EL ESTADO DEL ARTE

| TÉCNICA | QUÉ ES | ¿LO TIENE MI DISEÑO? | QUÉ APORTA DE NUEVO |
|---|---|---|---|
| **Context compression** (LLMLingua, aprendida) | Reducir tokens del prompt con un modelo | **Parcial, sin LLM.** Aquí "comprimir" = **proyectar**: elegir filas ya escritas | Que el compresor sea **una función pura**: 5–150 ms contra 16,49 s `[M]`, y **0 tokens**. La compresión deja de ser una decisión y pasa a ser un fold |
| **Summarization memory** (resumen encadenado) | Resumir el historial y resumir el resumen | **NO. Es el antipatrón central** | Nada que aportar: se **prohíbe estructuralmente**. −39 % single→multi-turn con **+112 % de no-fiabilidad** `[L]`; cascada **24→2 en un paso** `[M]` |
| **Recurrent memory** (RMT, Titans) | Estado recurrente pequeño de tamaño fijo | **El teorema sí, el sustrato no** | El estado recurrente es **texto inspeccionable y auditable**, no vectores. Los 11,1M de RMT son GPT-2 fine-tuneado en BABILong: **no hay checkpoint de 27B instruido** `[L]` |
| **External memory** (MemGPT / Letta) | Disco como verdad, ventana como caché; el modelo gestiona su memoria | **Sí, con un recorte duro** | El modelo decide **qué leer**, **nunca qué es verdad**. En MemGPT el LLM escribe su propia memoria; aquí el esquema se lo impide |
| **RAG** (embeddings + vector store) | Recuperar por similitud semántica | **NO por defecto** (opt-in) | `libro_grep` por regex/ID exacto: **su fallo es ruidoso** (`0 hits` en el envelope). BM25/embeddings devuelven un conjunto plausible y equivocado = vacío silencioso; midió **0,526** `[M]` |
| **Episodic memory** | Recuerdo de episodios con contexto temporal | **Sí: la `prov` ES memoria episódica** | Cada acción con su huella medida (`tool`, `args_sha`, `cwd`, `exit`, `salida_sha`) y su `ts` del reloj del emisor. **Sin promoción por repetición**: la frecuencia no es evidencia |
| **Hierarchical memory** | Niveles de memoria por importancia o por compresión | **Sí, por PERSISTENCIA** (lo que pidió el dueño, y es correcto) | La jerarquía es **por quién puede escribir y con qué op**, no por cuánto se comprime. Y **sin decay temporal sobre restricciones**: eso es *governance decay* |
| **Agentic workflows** (orquestador-trabajador) | Subagentes con contextos aislados | **Sí, secuenciales** | Retorno **tipado en eventos con provenance de máquina**, no 600 chars de prosa (que **eran** el resumen-de-resumen). Prompt como **sufijo del prefijo del padre**: 24× de caché `[M]` |
| **Reflection** (Reflexion, self-refine) | El agente escribe lecciones de sus fallos | **Sí, muy recortado** | `leccion` en **forma imperativa positiva obligatoria** (la forma negativa se rechaza: por ahí entra el self-conditioning) + `base` medida + contador `firma → n`. La reflexión libre está falsada `[L]` y medida en 0,517 aquí `[M]` |
| **Verifier models** | Un modelo que juzga la salida de otro | **Sólo el que EJECUTA** | **El control negativo del verificador**: antes de conceder un `verificado`, el verificador tiene que **suspender** con la evidencia destruida. La literatura examina la respuesta; **nadie examina el verificador** |
| **State-space / híbridos** | Atención lineal, estado constante | **Como sustrato, no como diseño** | La contabilidad honesta: el 9B es híbrido `qwen35`, **8 capas de atención de 33**, KV = 32 KiB/tok. Contar 33 se equivoca **4×** `[M]` |
| **Validez temporal** (Zep / Graphiti) | Un hecho no se reescribe: se invalida y se añade el nuevo | **Sí, adoptado** | Es **la pieza que hace inejecutable** el resumen-de-resumen. Sus **cifras** no valen (LoCoMo usa 16k–26k tok: cabe entero en la ventana; y están disputadas: 75,14 vs 65,99, y 84 → **58,44** en su propio repo) `[L]` |
| **Sleep-time compute** | Pre-computar en tiempo ocioso | **Sí, condicionado a E7** | Precalentar **en el slot 1** (no en el 0, que destruiría la caché que calienta) sólo el **prefijo estable**. Swap caliente **59 ms vs 2.840, 48×** `[M]` |
| **Compact + re-read** (harness de agentes de Anthropic) | Compactar y luego **releer del disco** (git log, progress file, lista JSON pass/fail) | **Sí: es el mismo patrón** | Aquí formalizado como **transacción con compuerta**, no como convención. Y con la compuerta **antes** de destruir |
| **Two-phase commit / WAL / event sourcing / CQRS** | Transacciones de bases de datos | **Sí, es el esqueleto** | Aplicarlo al **contexto de un LLM**: la ventana como caché, el LIBRO como WAL, `proyectar()` como la vista materializada de CQRS |

### 13.1 Qué es GENUINAMENTE novedoso, qué ya tiene nombre propio, y cuál es la combinación

**Ya tiene nombre propio (nada de esto es mío):** WAL, two-phase commit, event sourcing, CQRS,
content-addressed storage, validez bi-temporal (Zep/Graphiti), memoria externa (MemGPT),
orquestador-trabajador sellado, verificador ejecutante, recitación de evidencia (+4 % RULER),
sleep-time compute, needle-in-a-haystack. **Y el propio ciclo de lobotomía, que YA EXISTE EN ESTE
REPO**: `cognia/agent/horizonte.py:ciclos_con_contrato`, opt-in `COGNIA_HORIZONTE=1`, activado en
`cli.py`. El dueño no está pidiendo algo que no tiene: está pidiendo que lo que tiene deje de perder
cosas en silencio.

**Genuinamente novedoso — cinco cosas, y son pequeñas:**

1. **El reset como 2PC con un test de conservación como compuerta.** No he encontrado a nadie que
   publique *"no destruyas hasta que el sucesor demuestre que conserva"*. Todo el mundo compacta y
   reza. La diferencia no es estética: pone el modo de fallo en **no resetear** (el brazo que midió
   1,000) en vez de en **abortar la tarea**.
2. **Trazadores como canarios del commit**, con IDs **no inferibles**, comprobados **en la respuesta
   de la sesión nueva**: needle-in-a-haystack aplicado a la transacción, de modo que "presente" no se
   pueda confundir con "reconstruible".
3. **Provenance escrita por el harness, nunca por el modelo.** A-MEM, Zep y HippoRAG hacen que el LLM
   rellene la atribución. Aquí se **elimina la superficie de mentira en vez de detectarla**.
4. **Control negativo del verificador como requisito de ascenso.** La literatura examina la
   respuesta; nadie examina el verificador.
5. **La mutación del gate como instrumentación permanente**: un commit que nunca ha rechazado nada se
   declara **averiado, no sano**.

**La combinación más potente** — es un **producto**, no una suma: quitar cualquier factor lo rompe.

> *cabecera permanente verbatim que nunca se comprime* **×** *libro append-only con provenance de
> máquina* **×** *proyección determinista con render generacional* **×** *verificador que ejecuta y
> que ha suspendido su propio control negativo* **×** *reset disparado por contaminación y GATEADO
> por conservación, con MODO ANCHO acotado como salida* **×** *2 slots de 32k sobre una copia de
> pesos*.

Sin la primera vuelve el 0,526. Sin la segunda, la mentira. Sin la tercera, cada reset cuesta 4× más.
Sin la cuarta, el ascenso es teatro. Sin la quinta, la pérdida es invisible. Sin la sexta no hay
dónde correr el crítico.

**Y la pieza que más aporta por sí sola está medida: re-emitir el contrato verbatim — 400 tokens,
0,17 s de prefill, recall 1,000. Todo lo demás existe para proteger eso.** Por eso E0 corre primero
y por eso puede matar al resto del diseño.

---

## 14. MVP Y AVANZADO

### 14.1 P0 — PRERREQUISITOS. Sin esto, todo lo demás es teatro (~1,5 h)

| # | Qué | Dónde | Por qué es bloqueante |
|---|---|---|---|
| **P0-1** | **`run_tool` tiene que devolver el `returncode` real** | `agent/tools.py:470` (`ok = not re.search(r"\bERROR\b", out.split("\n",1)[0][:120])`) y `_shell` (`tools.py:1656`) | Hoy un `pytest` con **exit 1** llega como `ok=True` (no contiene `ERROR` en los 120 primeros chars), y un comando **BLOQUEADO por el sentinel** (`sentinel.py:196-214`) llega como `ok=True` **sin haberse ejecutado nunca**. Con eso, un criterio pasa a PASS y el sistema **capitaliza una victoria inexistente**. Mientras esto no se arregle, `origen=medido`, `conf=1,00` y `prov.tipo=ejecutada` son **etiquetas creíbles sobre datos inventados** — el fallo exacto que este diseño dice prevenir. **Implementación:** `_shell` escribe `ctx["_exit"] = r.returncode`; el sentinel escribe `ctx["_exit"] = None`; `run_tool` pasa `exit_code=ctx.pop("_exit", None)` a `interceptor.despues`. **`None` ≠ 0**: sin exit real, `origen` **no puede ser** `medido`. Test: un comando bloqueado NO produce `exit 0` |
| **P0-2** | **La escritura del LIBRO fuera del `except Exception: pass`** | `harness/interceptor.py` (11 `except Exception: pass`; contrato "degrada a no hacer nada") | Disco lleno = **memoria apagada en silencio**, y el fallo típico de este sistema es el vacío silencioso. `tx/libro.append` con envelope propio y `LibroCaido` tipada que **para el ciclo y lo dice** |
| **P0-3** | **Criterio barato + `cwd = workspace`** | `agents/goal_contract.py` | `_shell` tiene `timeout=30` por defecto y tope 600 s; la suite del repo son 6.909 tests / 12 min: **inejecutable como criterio**. Y `GoalContract` resuelve rutas contra el CWD del proceso |
| **P0-4** | **G2 sobre la respuesta, no sobre la proyección** | `estado/canal.py:507` | Comprobar trazadores contra la salida de una función pura que acaba de escribirlos **es una tautología**: 6/6 en el ciclo 1 y en el 500, información cero |

### 14.2 MVP — construible en UNA sesión de trabajo (~6,5 h)

**Bloque M1 — sustrato (2 h).** `cognia/tx/libro.py` + `cognia/tx/bandas.py` + `cognia/tx/claves.py`.

- `libro.append(evento) -> n` con validación de esquema (§3.2), `prev`-sha, `fsync`, `LibroCaido`.
- `libro.leer(hasta_tx=None) -> list[dict]`, `libro.fsck()`.
- `bandas.proyectar(eventos, topes) -> str` — el fold de §5.1, **sin** render generacional todavía.
- `claves.canonica(tool, args, out) -> (clave, valor)` con el vocabulario cerrado de §3.4.
- Tests: `tests/test_tx_libro.py` (cadena rota se detecta; `dicha` en banda P se rechaza; `conf>0.30`
  con `origen=modelo` se rechaza), `tests/test_tx_bandas.py` (**proyectar es puro: 100 llamadas, mismo
  sha**; una decisión cae cuando su base se invalida).

**Bloque M2 — commit 2PC (2 h).** `cognia/tx/commit.py` + `cognia/tx/gates.py`.

- MVP incluye **G1** (sha de P), **G2** (trazadores en la respuesta de Q), **G3** (sha de artefactos),
  **G5** (monotonía con `GoalContract`, `cwd=workspace`, criterio barato), **G6** (ciclo mudo).
- **G4** (contradicciones por clave) entra si sobra tiempo: es un `GROUP BY`, ~20 min.
- **G7** (control negativo) → AVANZADO.
- Escalera de aborto completa: robar topes → MODO ANCHO (≤3 seguidos, ≤10 %) → HARD_STOP.
- Q1..Q3 generadas del LIBRO + corrección por igualdad exacta normalizada.
- Tests: `tests/test_tx_commit.py` — **un commit con la banda P corrompida DEBE abortar**; MODO ANCHO
  no destruye; Q<3/3 no mata la tarea.

**Bloque M3 — CLI y driver (1,5 h).** `cognia/tx/driver.py`, `cognia/tx/tools.py`, comandos en `cli.py`.

```
/tx iniciar "<objetivo>" --criterio "<cmd>" --restriccion "<txt>" --pasos 8 --horas 12
/tx estado         panel: bandas, gates, salud, ratio de maquinaria
/tx probar         corre G1..G6 AHORA contra el contexto vivo, sin resetear
/tx commit         fuerza un commit ya e imprime la tabla de gates
/tx ancho          fuerza MODO ANCHO un ciclo
/tx bandas         tokens por banda y qué se está cayendo por el tope
/tx mutar          corrompe la proyección a propósito y EXIGE que el gate aborte
/tx vram --verificar

/libro 20                      últimos 20 eventos
/libro ver 812 --contexto 3    el evento, sus vecinos, su cadena de refs
/libro grep "pickle" --banda F
/libro auditar 815             cadena de provenance hasta eventos medidos
/libro restringir "..."        añade restricción (origen=usuario, conf 1,00)
/libro retractar 816 "motivo"  invalida sin borrar
/libro fsck [--reparar]
/libro exportar                JSONL completo para auditoría externa
```

Tools que ve el agente (patrón `rlm.register(tool)`): `libro_grep`, `libro_ver`,
`decidir --porque <n,n>` (**rechaza sin `base` medida**), `afirmar --verificador <cmd> --espera
<exit==0|sha==...>`, `pendiente`, `resolver`, `leccion` (**rechaza forma negativa**).

Una línea por ciclo, en el REPL:

```
[TX] c41 COMMIT TX-0041 ok · P 9f3c1a · trz 6/6 · art 12/12 · Q 3/3 · crit 4/7 · 1,4 s · maq 4,1 % · ctx 3,5k->11,8k
[TX] c42 ABORT G3: A-004 canal.py sha e77a01b3 -> b91c4402 · re-leo y reintento
[TX] c43 ANCHO (G2 5/6) · ciclos_anchos 1/3 · no destruyo
```

**Bloque M4 — E0 y E1 (1 h).** El brazo nulo y la mutación del gate. `planes/agente_largo/exp/e0.py`,
`e1.py`. Sin esto el MVP no se puede defender.

**Lo que se puede teclear el DÍA 1, en orden:**

```
set COGNIA_TX=1
venv312\Scripts\python.exe -m pytest tests/test_tx_libro.py tests/test_tx_bandas.py tests/test_tx_commit.py -q
venv312\Scripts\python.exe -m cognia
  /tx vram --verificar
  /tx iniciar "cablear el canal de estado al bucle" --criterio "venv312\Scripts\python.exe -m pytest tests/estado -q" --restriccion "no tocar loop.py fuera de bucle_nativo" --pasos 8 --horas 4
  /tx probar
  /tx mutar          <- TIENE que abortar. Si no aborta, el gate esta roto y se para aqui.
  /tx estado
  /libro 20
  /libro auditar 12
```

**Definición-de-hecho del MVP (mecánica, no opinable):**
(a) `/tx mutar` aborta **3 de 3 veces** con las 3 mutaciones (restricción borrada, dígito de trazador
cambiado, sha falseado); (b) una tarea de 20 ciclos termina con `sha(P) == sha_P0`; (c) `ratio de
maquinaria` medido y mostrado, **< 15 %**; (d) `proyectar()` es pura: 100 llamadas, mismo sha;
(e) un `pytest` con exit 1 **NO** produce un evento `origen=medido, exit_code=0`.

### 14.3 AVANZADO — lo que viene después, en orden de valor

| Fase | Qué | Coste | Condición para construirlo |
|---|---|---|---|
| **A1** | **G7 control negativo** (`tx/verificador.py` + `flujos/examen.py`) y `poder_discriminante` | ~3 h | Siempre. Es la pieza epistémica clave, y cuesta 36 s en 500 ciclos `[D]` |
| **A2** | **Render generacional** (§5.2) | ~2 h | **Sólo si E6 mide ahorro ≥2×** |
| **A3** | **Árbol de sha del workspace + rollback honesto** (§8.3) | ~3 h | Antes de la primera tarea que use `ejecutar` para modificar ficheros en masa |
| **A4** | **`--parallel 2` + slot 1** (crítico comparativo / oráculo) | ~2 h | Tras validar `/tx vram --verificar` con delta <3 % |
| **A5** | **K2 comparativo** | ~1 h | **Sólo si E3 > 0,58 con n=103. Si no, se borra el componente** |
| **A6** | **K3 oráculo de otra familia** | ~4 h | Tras A4 (necesita los 4,2 GB liberados) |
| **A7** | **Subagentes con retorno en eventos** (§4) | ~4 h | Tras A1: sus filas entran como `hipotesis` y necesitan la escalera de ascenso |
| **A8** | **Sleep-time / precalentado en slot 1** | ~2 h | **Sólo si E7 mide ahorro ≥2×**. Si no, se apaga |
| **A9** | **Anticuerpos en caliente + autopsia causal en el rollback** | ~3 h | Tras A3 |
| **A10** | Índice SQLite **derivado** del JSONL (nunca fuente de verdad) | ~2 h | **Sólo si E-fold mide `proyectar()` por encima del 1 % del ciclo** |

---

## 15. PLAN EXPERIMENTAL

### 15.1 Doctrina vinculante (lecciones del repo, no negociables)

- **Brazos INTERCALADOS** y netos **apareados intra-corrida**: la varianza *entre* corridas es
  **±34 pts**.
- **n ≥ 6 por brazo.** El gate e2e es flaky ~50 %: **fallos concentrados = regresión**; fallos
  dispersos = instrumento.
- **Métrica primaria declarada ANTES**, y **el azar como referencia**, nunca s1.
- **Brazo nulo obligatorio**, y aquí es el brazo nulo **de la arquitectura entera**, no de un componente.
- `finish_reason` y `usage` se miran **antes** de atribuir nada al modelo.
- **Un flaky es un bug del instrumento** hasta que se demuestre lo contrario (regla C2).
- **Reproducir antes de contarlo como fallo del modelo.**

### 15.2 Métrica PRIMARIA, declarada ahora

> **Criterios congelados sellados y RE-VERIFICADOS EN LIMPIO, por hora de pared.**

"En limpio" = sobre una copia del workspace, en proceso nuevo, con `cwd = workspace`, con el
verificador que **suspendió su control negativo**. El árbitro es código, no un juez.

**Secundarias (todas instrumentadas de forma permanente en `/tx estado`):**

| Métrica | Definición operativa | Objetivo |
|---|---|---|
| `recall_restricciones@N` | fracción de restricciones de P **literalmente presentes** (ID exacto) en la respuesta del modelo tras N ciclos | **1,000** |
| `alucinacion_persistente` | `verificado` cuyo re-verificador falla en el barrido limpio del cierre / total de `verificado` | **0** |
| `ciclos_hasta_deriva` | primer ciclo con `huerfanas > 0,40` o retroceso de contrato | > 100 |
| `ratio_maquinaria` | (proyectar + gates + rehidratar + Q) / tiempo de pared del ciclo | **≤7 %**, alarma 15 % |
| `tokens_maquinaria` | tokens de LLM gastados en comprimir + recuperar | **80/ciclo** (sólo el decode de Q) |
| `tasa_de_abort` | commits abortados / commits intentados | **>0**. Un **0 perpetuo es AVERÍA**, no salud |
| `ciclos_anchos` | resets cancelados | ≤10 % |
| `q_fallidas`, `poder_discriminante`, `stale_detectados`, `huerfanas_pct`, `hechos_recortados` | — | ninguno perpetuamente en cero |

### 15.3 Los seis brazos (intercalados)

| Brazo | Qué es | Papel |
|---|---|---|
| **B0 · SIN MEMORIA** | sesión limpia cada 8 acciones, sólo el objetivo en una línea | **el AZAR.** La referencia de todo |
| **B1 · RESUMEN SIMPLE** | reset + resumen del historial hecho por el LLM (el antipatrón que el dueño quiere evitar) | mide **cuánto daño hace** lo que se está reemplazando. Coste conocido: 16,49 s/compactación `[M]` |
| **B2 · ANCHO** | ventana ancha, sin reset, con el `_recortar_mensajes` de hoy | el **status quo** de Cognia |
| **B3 · HORIZONTE** | lo que ya existe: `COGNIA_HORIZONTE=1`, delta determinista de 1.200 chars | el **estado actual del repo** |
| **B4 · CONTRATO VERBATIM** | reset + re-emitir **sólo P + T verbatim**, resto vacío. Sin LIBRO, sin gates, sin Q | **EL BRAZO A BATIR.** Midió recall 1,000 y cuesta 0 % de maquinaria |
| **B5 · TX COMPLETO** | esta especificación | el candidato |

### 15.4 El banco: 12 tareas, 6 cotidianas y 6 complejas

**Cotidianas humanas** (largas, con restricciones duras, verificables sin ser código):

| # | Tarea | Criterio barato (<5 s) | Criterio caro (cierre) |
|---|---|---|---|
| H1 | Ordenar `Descargas/` (≈2.000 ficheros) en carpetas por tipo y año, sin borrar nada, sin mover lo que esté abierto | `dir /b Descargas\*.* \| find /c` == 0 | script que verifica que el conteo total de ficheros es idéntico al inicial |
| H2 | Extraer una tabla de 40 PDFs a un CSV con 6 columnas y sin filas vacías | `python -c "csv rows>0"` | validador de esquema + 5 filas comprobadas a mano contra el PDF |
| H3 | Renombrar y etiquetar 300 fotos por fecha EXIF, sin perder ninguna | conteo de ficheros | hash-set de contenidos idéntico al inicial |
| H4 | Presupuesto mensual desde 3 extractos bancarios, cuadrando totales al céntimo | suma de columnas | reconciliación contra el saldo final de cada extracto |
| H5 | Inventario de la casa a partir de fotos + notas, con 40 ítems y ninguna invención | `jsonschema` del inventario | **cada ítem con una `prov` que apunte a una foto concreta** (mide alucinación directamente) |
| H6 | Plan de viaje de 5 días con 6 restricciones duras (presupuesto, horarios, una persona con movilidad reducida) | validador de restricciones | las 6 restricciones comprobadas ítem a ítem |

**Complejas** (del propio proyecto, con suite de tests real):

| # | Tarea | Criterio barato | Criterio caro |
|---|---|---|---|
| C1 | Cablear las 11 funciones huérfanas de `estado/canal.py` con llamador real y persistencia | `pytest tests/estado -q` (2,4 s) | suite completa |
| C2 | Cablear `harness/contexto_vivo.registrar_uso` en `loop.py` y `harness/limites.py` en el bucle | `pytest tests/test_contexto_vivo.py -q` | suite completa |
| C3 | Subir cobertura de `cognia/tx/` de 0 % a >85 % | `pytest tests/test_tx_*.py -q` | `coverage report --fail-under=85` |
| C4 | Migrar `memory/` fuera de los 3 antipatrones sin romper importadores | `pytest tests/test_memory -q` | suite completa + import en venv limpio |
| C5 | Un juego jugable con AGF de una sola orden | gate de píxeles | ejecutable que arranca y responde a input |
| C6 | Portar `planes/agente_largo/exp/` a un subcomando `/tx exp` | `pytest tests/test_tx_exp.py -q` | los 7 experimentos corren de una orden |

**Duración:** cada tarea se corre a **4 horas de pared** (≈160 ciclos `[D]`). Es el punto donde la
predicción honesta dice que TX debería ganar; por debajo de 30 min **predigo que TX pierde** (paga
maquinaria sin haber acumulado degradación en el rival).

### 15.5 Los experimentos, con KILL pre-registrado

| # | Pregunta | Diseño | Métrica | **KILL** |
|---|---|---|---|---|
| **E0** | ¿la maquinaria aporta algo sobre re-emitir el contrato verbatim? | **B4 vs B5**, 12 tareas × 4 h, intercaladas, apareadas, n≥6 | criterios sellados y re-verificados/hora | **CORRE PRIMERO.** Si B5 ≈ B4 (diferencia apareada no significativa), **se entrega B4 y se tira todo lo demás** |
| **E1** | ¿el gate detecta corrupción? | `/tx mutar` cada 25 ciclos: borrar 1 restricción · cambiar 1 dígito de trazador · falsear 1 sha · **inyectar un ciclo mudo** | tasa de detección | **debe ser 1,000.** <1,000 ⇒ el gate está roto y el diseño no se despliega |
| **E2** | ¿el control negativo caza verificadores tramposos? | 40 verificadores emitidos por el modelo **+ 5 triviales inyectados a propósito (control positivo)** | % que suspende | **los 5 inyectados deben suspender los 5.** Sin control positivo, un 0 % es ininterpretable. Si <10 % del resto suspende, G7 aporta poco y se abarata |
| **E3** | ¿existe K2? | 60 correctas / 43 erróneas ya recogidas en `exp/`; brazos: azar · absoluto · comparativo · ejecutable | exactitud balanceada | absoluto ya = **0,52** `[M]`. **Comparativo ≤0,58 ⇒ K2 SE BORRA** |
| **E4** | ¿cuántas acciones por ciclo **aquí**? | barrido 4/8/16/32, n≥6, intercalado, sobre C1–C3 | criterios/hora | el **8** viene de un paper sobre Gemma3-27B: es **el número más prestado de todo el diseño**. Si el óptimo local es 4 o 16, se cambia T1 |
| **E5** | ¿TX gana al brazo ancho **y al horizonte de hoy**? | B2 · B3 · B5, 12 tareas × 4 h, intercaladas | primaria | **Predicción honesta: B5 pierde por debajo de 30 min.** Si B5 no gana por encima de 4 h, **el diseño muere** |
| **E6** | ¿el render generacional paga? | tokens procesados que reporta llama.cpp en el reset, con y sin la regla | ms de prefill del reset | predicción 0,25 s vs 1,22 s. **Ahorro <2× ⇒ se quita la regla** y se aceptan los 1,22 s |
| **E7** | ¿precalentar en slot 1 paga? ¿y q8_0? | (a) reset con/sin precalentado; (b) `--cache-ram` 1024 vs 4096; (c) KV f16 vs q8_0 sobre el banco de restricciones | (a,b) ms de reset; (c) `recall_restricciones` | (a) **<2× ⇒ se apaga**; (c) **q8_0 con recall <1,000 ⇒ prohibido** |
| **E-fold** | ¿`proyectar()` escala? | fold sobre libros sintéticos de 1k/5k/20k/50k eventos | ms | **>1 % del ciclo ⇒ se añade índice SQLite derivado** (A10) |

### 15.6 Calendario y coste

- **E1, E2, E3, E-fold**: una tarde. No necesitan corridas largas. **E3 decide si K2 existe.**
- **E0**: 12 tareas × 2 brazos × 4 h = **96 h de pared**, intercaladas → ~4 días con la máquina
  dedicada. **Es el experimento caro y es el primero, porque puede cancelar los demás.**
- **E5**: sólo si E0 sobrevive. Otras 144 h (3 brazos).
- **E4, E6, E7**: barridos cortos, se pueden solapar con E0 usando el slot 1.

### 15.7 Lo que NO demuestra este plan (dicho ahora)

- **No mide días sin supervisión.** Mide 4 h. La osificación de la banda P (§16.1) aparece a partir de
  ~60 restricciones, que en tareas de 4 h no se alcanza. **Extrapolar de 4 h a 3 días es una
  suposición, y la marco como tal.**
- **No mide la validez de los razonamientos** (§16.3): mide que la evidencia existía, no que la
  conclusión se siga de ella.
- **El banco de tareas cotidianas lo escribo yo**, y *el techo es del diseñador de exámenes*: si mis
  criterios son fáciles, todos los brazos los pasan y E0 sale plano por construcción. Mitigación:
  cada tarea cotidiana lleva **un criterio que un agente sin memoria NO puede pasar** (H5 y H6 están
  diseñadas exactamente para eso), y se verifica que **B0 falla** en ellas antes de contar nada.

---

## 16. LO QUE NO RESUELVO — cinco modos de fallo, tres sin resolver

**16.1 · Osificación de la banda P.** Las restricciones no caducan **por diseño** (el decay sobre
governance es un antipatrón demostrado). Con un extractor que deriva reglas de `CLAUDE.md` y un dueño
que teclea `/libro restringir`, 7 restricciones se vuelven 45, y a ~60 salta el HARD_STOP. La salida
obvia —filtrar por ámbito— **reintroduce la selección que midió 0,526**.
*Lo que añado:* la **única** vía automática de alivio es un `amend` disparado por el **contrato** (un
criterio satisfecho puede retirar la restricción que lo guardaba) — mecánica y estrecha, nunca poda
por el modelo. Alarma a partir de 700 tok de cabecera.
**SIN RESOLVER: un agente que corre 500 ciclos sin supervisión necesita un ritual de poda humano, y
eso contradice "trabajar días sin supervisión".** Lo hago visible en vez de esconderlo.

**16.2 · F y A empiezan a SELECCIONAR hacia el ciclo ~120.** A ~15 hechos/ciclo con topes de 750/540
tokens, el proyector empieza a recortar. **G1, G2, G5 y G6 siguen en verde**, porque Q se saca de P y
T, que son eternos. El agente re-deriva lo que ya sabía.
*Lo que añado:* expulsión **por generaciones** (no por filas sueltas), **Q se muestrea
preferentemente de las generaciones MÁS ANTIGUAS**, y `/tx bandas` reporta `hechos_recortados`.
**RIESGO RESIDUAL: eso deja a Q como único detector, y Q depende de que el proyector elija bien a
quién preguntar — el detector comparte el sesgo del sistema que vigila.**

**16.3 · Decisiones erróneas que envenenan por la puerta de atrás.** Excluir la traza de errores no
excluye la **conclusión** errónea, que es la parte que el modelo trata como premisa. Éste es el
agujero que mata a los tres diseños evaluados con tres nombres distintos: **la provenance verifica el
origen del fragmento, nunca la proposición que dice sostener.**
*Lo que añado:* una `decision` sólo se proyecta mientras al menos un evento de su `base` siga vigente
y no `stale`; si su base se invalida, **cae sola**.
**SIN RESOLVER: eso garantiza que EXISTIÓ una medición, no que la conclusión SE SIGA de ella. Puedo
garantizar la procedencia de los hechos y no puedo garantizar la validez de los razonamientos que los
conectan.**

**16.4 · Inflación de `verificado` trivial.** El control negativo caza al verificador que pasa con la
evidencia destruida, **no al que pasa por un motivo trivialmente cierto**: `test -f almacen.py`
suspende correctamente y aun así no verifica nada de lo que la fila afirma.
*Lo que añado:* `poder_discriminante` en rojo por debajo de 0,25 a los 100 ciclos, contando **sólo
fallos en ejecución real**, nunca los del examen.
**PARCIAL: la mitigación conocida es una heurística léxica, y las heurísticas léxicas se falsifican.**

**16.5 · `leida` que miente porque el mundo cambió.** 400 artefactos × 500 commits = 200.000 lecturas
completas: hay que muestrear por `mtime + size`, y en cuanto se muestrea, un artefacto no crítico
puede cambiar sin mover ninguno de los dos.
*Lo que añado:* sha completo cuando `mtime` **o** `size` se muevan, 100 % de sha en los
`critico:true` en cada commit, **barrido completo cada 25 ciclos** (~0,4 s `[D]`), y postcondiciones
sobre una **copia limpia del workspace** en el cierre.
**RIESGO RESIDUAL: entre dos barridos caben ~37 minutos de trabajo apoyado en un hecho falso bien
etiquetado. Y si lo que cambió es una DEPENDENCIA (un import, un JSON de config), su propio sha no se
mueve y no lo veo en absoluto. La verificación final sobre copia limpia DESCUBRE el desastre; no lo
previene.**

---

*Especificación final, 2026-08-19. Todo número de VRAM, prefill, caché, recall y latencia procede de
`medicion_kv.md` o `falsacion.md` y va marcado `[M]`. Los tres números importados de la literatura van
marcados `[L]`: H(0,5) ≈ 8 turnos (arXiv:2509.09677), self-conditioning 85/70/55 % (idem), +4 % de
RULER por recitación (arXiv:2510.05381). Lo derivado por mí va marcado `[D]` y cada uno tiene su
experimento en §15. Las líneas de código citadas llevan fichero y número y fueron leídas hoy.
Ninguna cifra de este documento es una estimación silenciosa.*

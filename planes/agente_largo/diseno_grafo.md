# Diseño: MEMORIA ESTRUCTURADA CON PROVENANCE (lente 3)

**Tesis:** el problema no es el tamaño de la ventana, es la EPISTEMOLOGÍA. Un agente que corre 500 ciclos
no falla por olvidar: falla porque **no distingue lo que comprobó de lo que se inventó**, y ese error se
acumula con interés compuesto. El diseño no comprime memoria: la **tipa, la sella con provenance escrita
por la máquina, y sólo asciende a "hecho" lo que un verificador re-ejecutable confirma — verificador que
antes tuvo que aprobar un control negativo.**

Este documento acepta como axiomas los cuatro informes previos (`medicion_kv.md`, `inventario_cognia.md`,
`estado_del_arte.md`, `falsacion.md`) y NO re-litiga sus veredictos. En particular acepta que:

- La lobotomía **no ahorra un solo MiB de VRAM** (H1 REFUTADA). Ahorra **segundos** (2,8 s vs 27,3 s).
- El recall de restricciones desde almacén inmutable con selección es **0,526**; dejándolas literalmente
  en la ventana a 111k tokens es **1,000**. **Por tanto: la banda permanente NO se recupera por
  relevancia. Se re-emite verbatim, siempre, entera.** Ésta es la concesión que salva mi propio diseño:
  la recuperación selectiva se aplica **sólo** a las bandas de baja persistencia.
- Un crítico LLM de la misma familia está en el azar (0,517 / 0,523) y el adjetivo del prompt mueve la
  detección 21×. **Por tanto el crítico de este diseño no puntúa: EJECUTA.**
- El fallo típico es el **vacío silencioso**, no la excepción.

---

## 1. Los siete tipos y las cuatro bandas

Cada dato vive en **una fila inmutable** de una tabla, con **tipo**, **estado epistémico**, **provenance**
y **confianza calculada**. Las filas **nunca se reescriben**: un cambio es una fila nueva con una arista
`invalida` a la anterior (validez temporal, estilo Graphiti/Zep). Ésta es la defensa estructural contra el
resumen-de-resumen: **no hay ninguna operación en el sistema que lea una fila y escriba una versión
degradada encima.** La cascada medida en H4 (24→2 restricciones en un paso) es literalmente inejecutable
aquí porque no existe la operación que la causa.

| Banda | Tipos | Persistencia | Cómo llega al prompt | Tokens |
|---|---|---|---|---|
| **P — permanente** | `objetivo`, `restriccion`, `criterio` | Nunca caduca, nunca decae, nunca se comprime | **Verbatim, entera, al principio, byte-idéntica entre ciclos** | 700–1.100 |
| **D — decisiones** | `decision` | Sólo se invalida con una decisión nueva explícita | Verbatim las vigentes (append-only, tope 30) | ≤1.200 |
| **H — hechos** | `hecho`, `resultado`, `error` | Caduca por re-verificación fallida | **Recuperación selectiva BM25** + fijados por arista | ≤900 |
| **V — volátil** | `hipotesis`, `plan`, `pendiente`, `charla` | Muere con el ciclo | Al FINAL del prompt, es lo único que cambia | ≤600 |

**Orden del prompt: P, D, H (inmutables dentro del ciclo) → V (mutable).** No es estética: la medición dice
que cambiar algo *por dentro* del prefijo cuesta el prefill entero (5.826 ms) y que el corte de reuso es
**distancia absoluta ~512 tokens** desde el final. Todo lo que muta va detrás de todo lo que no muta.

**Contra el U-shape:** el prólogo va delante (para el cache) y se compensa con **recitación obligatoria**:
la primera acción de cada ciclo es emitir `RECITO: <ids de restricción que aplican a este ciclo>`. Es el
truco medido de +4% en RULER y a la vez el gate de deriva de objetivo (§8).

---

## 2. Esquema real (SQLite)

Fichero: `.cognia/memoria/<task_id>.db`. Ocho tablas. **Todas append-only salvo `ciclo`.**

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── 1. LA FILA. Inmutable. Nunca UPDATE de `texto`, `tipo`, `clave` ni `prov_id`.
CREATE TABLE fila (
  id            INTEGER PRIMARY KEY,
  tipo          TEXT NOT NULL CHECK (tipo IN
                  ('objetivo','restriccion','criterio','decision',
                   'hecho','resultado','error','hipotesis','plan','pendiente')),
  banda         TEXT NOT NULL CHECK (banda IN ('P','D','H','V')),
  clave         TEXT NOT NULL,          -- vocabulario CERRADO, ver §5
  valor         TEXT NOT NULL,          -- el valor canónico para contradicción (sha, exit, num, 'si'/'no')
  texto         TEXT NOT NULL,          -- la frase que se re-emite al prompt
  estado        TEXT NOT NULL DEFAULT 'hipotesis'
                  CHECK (estado IN ('hipotesis','sospechoso','verificado','refutado','invalidado')),
  confianza     REAL NOT NULL DEFAULT 0.0,   -- CALCULADA, nunca emitida por el modelo
  prov_id       INTEGER REFERENCES prov(id),  -- NULL sólo para 'hipotesis' y banda P sembrada por el dueño
  ciclo_alta    INTEGER NOT NULL,
  ciclo_baja    INTEGER,                -- NULL = vigente
  autor         TEXT NOT NULL CHECK (autor IN ('dueno','interceptor','modelo','subagente','verificador')),
  tokens        INTEGER NOT NULL,       -- coste medido de re-emitir `texto`
  ts            REAL NOT NULL
);
CREATE INDEX ix_fila_vig   ON fila(banda, estado, ciclo_baja);
CREATE INDEX ix_fila_clave ON fila(clave, ciclo_baja);
CREATE INDEX ix_fila_ciclo ON fila(ciclo_alta);

-- ── 2. PROVENANCE. La escribe el INTERCEPTOR, jamás el modelo. Ver §6.
CREATE TABLE prov (
  id            INTEGER PRIMARY KEY,
  ciclo         INTEGER NOT NULL,
  paso          INTEGER NOT NULL,
  tool          TEXT NOT NULL,          -- nombre real del registry de Cognia
  args_sha      TEXT NOT NULL,          -- sha256 de los args normalizados
  args_corto    TEXT NOT NULL,          -- primeros 200 chars, para que un humano lo lea
  cwd           TEXT NOT NULL,
  exit_code     INTEGER,
  salida_sha    TEXT NOT NULL,          -- sha256 de la salida COMPLETA
  salida_bytes  INTEGER NOT NULL,
  salida_ruta   TEXT,                   -- offloading: dónde está la salida entera
  agente        TEXT NOT NULL,          -- 'raiz' | 'sub:<id>'
  ts            REAL NOT NULL
);
CREATE INDEX ix_prov_ciclo ON prov(ciclo, paso);

-- ── 3. VERIFICADOR: cómo se re-comprueba una fila. SIN esto no hay ascenso.
CREATE TABLE verificador (
  id            INTEGER PRIMARY KEY,
  fila_id       INTEGER NOT NULL REFERENCES fila(id),
  clase         TEXT NOT NULL CHECK (clase IN ('cmd','fichero_sha','fichero_regex','json_path','http','cita')),
  comando       TEXT NOT NULL,          -- p.ej. 'venv312\\Scripts\\python.exe -m pytest -q tests/test_x.py'
  espera        TEXT NOT NULL,          -- exit==0 | sha==<hex> | regex:<pat> | jsonpath:<expr>==<val>
  coste_ms      INTEGER,                -- medido en la 1ª ejecución
  examen_ok     INTEGER NOT NULL DEFAULT 0,   -- 1 sólo si SUSPENDIÓ el control negativo. Ver §7
  examen_detalle TEXT,
  cuarentena    INTEGER NOT NULL DEFAULT 0,
  ts            REAL NOT NULL
);

-- ── 4. Cada EJECUCIÓN del verificador. Append-only: es el historial de salud del hecho.
CREATE TABLE verificacion (
  id            INTEGER PRIMARY KEY,
  verificador_id INTEGER NOT NULL REFERENCES verificador(id),
  ciclo         INTEGER NOT NULL,
  ok            INTEGER NOT NULL,
  salida_sha    TEXT NOT NULL,
  ms            INTEGER NOT NULL,
  ts            REAL NOT NULL
);
CREATE INDEX ix_ver_v ON verificacion(verificador_id, ciclo);

-- ── 5. ARISTAS. El "grafo" es esto: 6 relaciones, cerradas.
CREATE TABLE arista (
  src           INTEGER NOT NULL REFERENCES fila(id),
  dst           INTEGER NOT NULL REFERENCES fila(id),
  rel           TEXT NOT NULL CHECK (rel IN
                  ('deriva_de','invalida','contradice','satisface','veta','requiere')),
  ciclo         INTEGER NOT NULL,
  autor         TEXT NOT NULL,
  PRIMARY KEY (src, dst, rel)
);
CREATE INDEX ix_ar_dst ON arista(dst, rel);

-- ── 6. Libro de ciclos. La ÚNICA tabla con UPDATE.
CREATE TABLE ciclo (
  n             INTEGER PRIMARY KEY,
  inicio        REAL, fin REAL,
  acciones      INTEGER DEFAULT 0,
  tokens_prompt INTEGER DEFAULT 0,
  tokens_salida INTEGER DEFAULT 0,
  motivo_reset  TEXT,                   -- acciones|saturacion|sello|cascada|limite
  gate_presencia REAL,                  -- fracción de restricciones LITERALMENTE presentes al arrancar
  filas_nuevas  INTEGER DEFAULT 0,
  ascensos      INTEGER DEFAULT 0,
  degradaciones INTEGER DEFAULT 0,
  contrato_ok   INTEGER
);

-- ── 7. SNAPSHOT = MANIFIESTO, no copia. Ver §12.
CREATE TABLE snapshot (
  ciclo         INTEGER PRIMARY KEY,
  max_fila_id   INTEGER NOT NULL,
  vigentes_sha  TEXT NOT NULL,          -- sha256 de la lista ordenada de ids vigentes
  ckpt_disco    TEXT,                   -- id de harness/checkpoints.py
  cabecera_sha  TEXT NOT NULL,          -- sha256 del prólogo verbatim de ese ciclo
  ts            REAL NOT NULL
);

-- ── 8. Recuperación. FTS5 sobre la banda H (y sólo esa).
CREATE VIRTUAL TABLE fila_fts USING fts5(
  texto, clave, content='fila', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
```

**Sin embeddings.** Justificación medida: el corpus tras 500 ciclos son ~6.000 filas de ≤200 chars sobre un
proyecto con vocabulario cerrado (rutas, nombres de test, mensajes de error). BM25 sobre eso no pierde
contra un vector de 256 dims por hash — y un embedding real costaría cargar un modelo más en 16 GB de VRAM
que ya están al 81%. **Si BM25 falla, el plan B es `memory/hierarchical.py` (hash 256-d, CPU, ya existe),
no un encoder nuevo.** Se mide antes de adoptarlo (§16, E4).

### Ejemplos reales rellenados

```
fila#1  tipo=restriccion banda=P clave='regla:venv'
        valor='si' estado=verificado confianza=1.00 autor=dueno prov_id=NULL ciclo_alta=0 tokens=19
        texto='SIEMPRE usar venv312\Scripts\python.exe. Nunca `python` a secas.'

fila#2  tipo=restriccion banda=P clave='regla:backend_8080'
        valor='si' estado=verificado confianza=1.00 autor=dueno tokens=24
        texto='NO reiniciar llama-server en :8080: es el cerebro de Cognia y sirve a otros procesos.'

fila#47 tipo=hecho banda=H clave='test:tests/test_canal.py'
        valor='exit==0' estado=verificado confianza=0.94 autor=interceptor prov_id=203 ciclo_alta=12 tokens=17
        texto='tests/test_canal.py pasa: 31 passed en 2,4 s.'
   prov#203 tool=ejecutar_comando
            args_sha=9f2c…a1 args_corto='venv312\Scripts\python.exe -m pytest -q tests/test_canal.py'
            cwd=C:\Users\usuario\Desktop\cognia_v2 exit_code=0
            salida_sha=b41e…7d salida_bytes=1834 agente=raiz ciclo=12 paso=4
   verificador#31 fila_id=47 clase=cmd examen_ok=1 coste_ms=2412
            comando='venv312\Scripts\python.exe -m pytest -q tests/test_canal.py' espera='exit==0'
            examen_detalle='control negativo: con tests/test_canal.py renombrado -> exit=4 (SUSPENDE). OK.'
   verificacion#88  ciclo=12 ok=1 ms=2412
   verificacion#140 ciclo=31 ok=1 ms=2380      <- re-verificación programada

fila#51 tipo=error banda=H clave='err:ModuleNotFoundError:cognia.memoria_ep'
        valor='presente' estado=verificado confianza=0.90 autor=interceptor prov_id=209 ciclo_alta=13 tokens=22
        texto='Importar cognia.memoria_ep desde el CWD del repo falla si no hay __init__.py. Fix: crearlo.'
   arista(51 -> 47, 'deriva_de')

fila#63 tipo=decision banda=D clave='dec:sin_embeddings'
        valor='bm25' estado=verificado confianza=0.80 autor=modelo ciclo_alta=14 tokens=26
        texto='DECISION c14: recuperacion por BM25/FTS5, no embeddings. Motivo: VRAM al 81%.'

fila#77 tipo=hipotesis banda=V clave='nota:quiza_el_wal_bloquea'
        valor='?' estado=hipotesis confianza=0.10 autor=modelo ciclo_alta=15 tokens=14
        -> muere al terminar el ciclo 15 salvo que se le adjunte un verificador y ascienda.
```

---

## 3. Confianza: fórmula, no opinión

`falsacion.md` mata la confianza auto-declarada: la emite el mismo modelo cuyo juicio es azar. Aquí la
confianza es **determinista y recalculable desde el disco**:

```
c(f) = base[estado] * ex(f) * fr(f) * (1 - 0.25*contradicciones_vivas(f))

base = {verificado:1.00, sospechoso:0.45, hipotesis:0.15, refutado:0.0, invalidado:0.0}
ex(f)= 1.0 si el verificador tiene examen_ok=1 ; 0.5 si examen_ok=0 ; 0.0 si cuarentena=1
fr(f)= frescura = 1.0 si se re-verificó en los últimos 20 ciclos
                  0.7 entre 20 y 60 ciclos
                  0.4 a más de 60  (y la fila pasa a 'sospechoso')
Banda P: c=1.00 SIEMPRE. No hay decay de governance (antipatrón `memory/forgetting.py`).
```

`confianza` es una columna materializada por conveniencia de lectura, pero `almacen.recalcular(id)` la
reconstruye desde `verificacion` + `arista` + `verificador`. **Si el número no se puede reconstruir, es
un bug, no un dato.**

---

## 4. Protocolo de ASCENSO y DEGRADACIÓN

**Nada asciende por decir que sí. Sólo por ejecutar.**

```
hipotesis --[verificador con examen_ok=1 y verificacion.ok=1]--> verificado
hipotesis --[verificacion.ok=0]--------------------------------> refutado
verificado --[re-verificacion.ok=0]-----------------------------> sospechoso  (NO refutado: puede ser el entorno)
sospechoso --[2ª re-verificacion.ok=0]--------------------------> refutado + arista(nueva, vieja, 'invalida')
sospechoso --[re-verificacion.ok=1]-----------------------------> verificado
verificado --[contradice a otra verificada, misma clave]--------> AMBAS a sospechoso, re-verificación forzada
cualquiera --[>60 ciclos sin re-verificar]----------------------> sospechoso (frescura)
```

Reglas duras:
1. **`autor='modelo'` no puede crear filas con `estado='verificado'`.** Constraint en `almacen.insertar()`.
   El modelo emite `hipotesis` + una propuesta de verificador. El ascenso lo hace el proceso.
2. **`autor='interceptor'` puede crear `verificado` directamente** para hechos cuya provenance ES la
   verificación: sha de un fichero, exit code de un comando, bytes escritos. No hay juicio de por medio.
3. **La banda P nunca degrada.** Sólo el dueño la retira, con `/memoria retirar <id> "motivo"`.
4. **Re-verificación programada**: al arrancar cada ciclo se re-ejecutan los verificadores de las ≤3 filas
   `verificado` más antiguas sin re-verificar cuyo `coste_ms` sume <1.500 ms. Presupuesto duro: **1,5 s por
   ciclo**, ~5% de un ciclo de 30 s. Si no cabe, se marca frescura degradada y se sigue: **no se bloquea
   nunca por re-verificación**, pero la degradación se ve en `/memoria`.

---

## 5. Detección de contradicciones — tres mecanismos, cero LLM

**(a) Colisión de clave canónica.** El vocabulario de `clave` es **cerrado** y lo genera el interceptor,
no el modelo:

| Prefijo | Lo emite | Ejemplo | Valor canónico |
|---|---|---|---|
| `archivo:` | interceptor, tras escribir/leer | `archivo:cognia/estado/canal.py` | sha256 |
| `cmd:` | interceptor | `cmd:pytest -q tests/` | exit code |
| `test:` | interceptor | `test:tests/test_canal.py` | `exit==0` |
| `err:` | interceptor (firma normalizada) | `err:ModuleNotFoundError:cognia.memoria_ep` | presente/ausente |
| `cfg:` | interceptor | `cfg:llama.n_ctx` | número |
| `regla:` | dueño | `regla:venv` | si/no |
| `dec:` | modelo | `dec:sin_embeddings` | etiqueta corta |
| `nota:` | modelo, libre | `nota:quiza_el_wal_bloquea` | `?` |

Dos filas **vigentes**, **`verificado`**, con **misma `clave`** y **`valor` distinto** ⇒ contradicción,
detectada por un `SELECT ... GROUP BY clave HAVING COUNT(DISTINCT valor)>1`, sin modelo, en microsegundos.
Se crea `arista(a,b,'contradice')`, ambas caen a `sospechoso` y se **encolan sus dos verificadores para
re-ejecución inmediata**. Gana el que pasa; si pasan los dos, es un bug del verificador y ambos van a
cuarentena con aviso al dueño.

**(b) Divergencia de re-ejecución.** El mismo verificador da `salida_sha` distinto entre ciclos con el
mismo `args_sha` ⇒ el mundo cambió bajo el agente. La fila cae a `sospechoso` y se emite una fila
`error` con clave `cmd:...` para que el ciclo siguiente lo vea.

**(c) Prosa: se DETECTA, no se resuelve.** Para `nota:` y `dec:` se corre FTS5 (BM25 > umbral) + un léxico
de negación de 40 entradas (`no `, `nunca`, `sin `, `falla`, `deja de`, …). Si dos filas de alto solape
difieren en polaridad ⇒ se marcan `sospechoso` y se **muestran al dueño** en `/memoria contradicciones`.
**No se auto-resuelven con un LLM: el LLM está en el azar para eso.** Declaro esto como punto ciego
consciente y lo mido (§16, E5).

---

## 6. Anti-alucinación: el modelo NO ESCRIBE PROVENANCE

Éste es el corazón del diseño y la respuesta directa a "¿qué pasa cuando el modelo miente al rellenar los
campos de provenance?".

**Respuesta: no puede, porque no tiene esos campos.** No existe ninguna tool con la que el modelo emita
`tool`, `args_sha`, `exit_code`, `salida_sha` o `cwd`. Esas seis columnas las escribe
**`harness/interceptor.py:despues()`** — el enchufe único ya existente por el que pasa *toda* llamada a
herramienta de Cognia — leyendo lo que realmente ocurrió. El modelo sólo puede emitir dos cosas:

```
AFIRMO clave=<del vocabulario cerrado> valor=<x> texto="<frase>" verificador="<comando>" espera=<exit==0|sha==…>
DECIDO clave=dec:<slug> texto="<frase>"
```

`AFIRMO` entra **siempre** como `hipotesis`. El ascenso es un proceso externo. Quedan **tres superficies de
mentira**, y cada una tiene contramedida:

1. **Mentir en `texto`** ("los tests pasan") con un verificador que sí pasa por otro motivo.
   → Contramedida: **control negativo del verificador (§7)**.
2. **Escribir un verificador tramposo** (`echo ok`, `exit 0`, `test -d .`).
   → Contramedida: **control negativo**, que es exactamente el caso que lo caza.
3. **Inventar una `clave` fuera de vocabulario** para escapar de la detección de contradicciones.
   → Contramedida: `almacen.insertar()` rechaza prefijos no listados; lo libre cae a `nota:` y `nota:`
   **está excluido de contradicción por clave** — punto ciego declarado, no oculto.

Además, todo `AFIRMO` cuya `clave` empiece por `archivo:`, `cmd:`, `test:` o `err:` se **contrasta contra
`prov`**: si en los últimos 3 ciclos no existe ninguna fila de `prov` con esa herramienta y ese destino,
la afirmación se marca `sospechoso` con motivo `sin_huella` **aunque su verificador pase**. Es el caso
"el modelo cree que escribió" que `estado/canal.py:anotar_fichero` ya mide midiendo el disco.

**Reutilizo tal cual:** `search/evidencia.verificar_cita` (literal, sin juez) para `clase='cita'`;
`estado/canal.anotar_fichero` / `anotar_comando` / `anotar_verificacion` como fuente de las filas de `prov`
del ciclo en curso; `harness/offloading` para `salida_ruta`.

---

## 7. El AGENTE CRÍTICO: un ejecutor, no un juez

`falsacion.md` H3 es concluyente: crítico LLM de la misma familia = azar, y el adjetivo del prompt mueve la
detección 21×. **Mi crítico no emite juicios.** Tiene tres capas, en orden de coste creciente:

**C1 — Control negativo del verificador (`flujos/examen.py`, reusado).** Cuando aparece un verificador
NUEVO, antes de que pueda conceder un solo `verificado`, se corre en un workspace copia con la evidencia
**mutada o retirada**:

| clase | Mutación del control negativo |
|---|---|
| `cmd` / `test` | renombrar el fichero destino / revertir el último diff |
| `fichero_sha` | truncar el fichero a 0 bytes |
| `fichero_regex` | borrar la línea que casa el patrón |
| `json_path` | poner el campo a `null` |
| `cita` | quitar el fragmento citado de la fuente |

**Si el verificador SIGUE pasando con la evidencia destruida, es nulo:** `examen_ok=0`, `cuarentena=1`,
la fila vuelve a `hipotesis`, y se emite una fila `error` con clave `err:verificador_nulo:<id>`. Esto es la
doctrina que ya vive en el repo ("nada se activa por haber salido bien") aplicada al ascenso epistémico.
Coste: **una ejecución extra por verificador nuevo, no por chequeo**. Con ~15 verificadores nuevos en 500
ciclos y coste medio 2,4 s ⇒ **36 s en toda la corrida**.

**C2 — Crítico COMPARATIVO A vs B (`agent/workflows.criticar`, reusado con restricción).** Sólo se invoca
cuando hay **dos candidatos** (dos parches, dos hipótesis contradictorias) y **nunca en modo absoluto**
("¿está bien esto?"). Es la única variante que el estado del arte deja viva a esta escala. Corre en el
**slot 1** (§14) con la cabecera P verbatim y NADA de la traza del ejecutor.

**C3 — Oráculo de otra familia (`harness/oraculo.py`, reusado; hoy es una tool que el bucle nunca invoca).**
Se dispara sólo con **presupuesto**: máximo 5 consultas por tarea, y sólo cuando C1 no aplica (afirmación
no verificable mecánicamente) y hay contradicción viva. `oraculo.consultar()` ya acepta transporte
inyectado: se le enchufa un modelo de otra familia si el dueño levanta uno; si no hay ninguno, **devuelve
`sin_oraculo` y la fila se queda `sospechoso` — nunca asciende por defecto.** Vacío ruidoso, no silencioso.

**Lo que NO hago:** ningún LLM aprueba un `verificado`. Ni el 9B, ni el 27B, ni con prompt "crítico y
riguroso" (que rechazó 58/60 correctas).

---

## 8. Pérdida del objetivo: dos gates mecánicos

**Gate A — `gate_presencia` (al ARRANCAR cada ciclo).** Se cuenta cuántas filas `restriccion` vigentes
están **literalmente presentes** en el prompt que se va a enviar, usando `estado/canal.py:_presente()` /
`_cobertura()` que ya existen y ya están testeados. Si `< 1.00`, **el ciclo no arranca**: se reconstruye la
cabecera y se reintenta; al segundo fallo se para la tarea con `ERROR: cabecera incompleta`. Esto ataca
directamente el "0 de 5 restricciones sobreviven sin canal y nadie emite un error".

**Gate B — acciones huérfanas (al CERRAR cada ciclo).** Cada `prov` del ciclo se enlaza (o no) a un
`criterio` vía `arista(prov→criterio,'satisface')`, resuelto por solape de rutas/nombres, no por LLM. Si
**>50% de las acciones de 2 ciclos consecutivos** no tocan nada relacionado con ningún criterio vigente ⇒
`DERIVA` en `/largo estado`, se fuerza recitación explícita y se recorta el ciclo siguiente a 4 acciones.
Al tercero, se para y se pregunta al dueño.

**Sello:** `agents/goal_contract.GoalContract.check()` sobre evidencia de disco con criterios CONGELADOS —
ya lo hace `agent/horizonte.py`. Se corrige su bug conocido: resolver rutas contra el **workspace**, no
contra el CWD del proceso.

---

## 9. Loops infinitos: tres detectores

1. **Progreso** — `estado/presupuesto_progreso.py` (ya ON). `pasos_sin_avance() >= 6` ⇒ fin de ciclo con
   `motivo_reset='sin_progreso'`. `veredicto()` ya distingue "no avanza" de "avanza caro".
2. **Firma de acción** — `sha256(tool + args_normalizados)` repetida ≥3 veces en una ventana de 20 pasos ⇒
   **veto en `interceptor.antes()`** con mensaje `ya lo intentaste 3 veces con este resultado: <prov ids>`,
   y `inmune/anticuerpos.sintetizar()` (que ya existe, con precision@1=1.000 vía `autopsia/causal.py`)
   convierte el bucle en un anticuerpo ejecutable que veta esa acción en ciclos futuros.
3. **Esterilidad epistémica** — 3 ciclos consecutivos con `ascensos = 0` en la tabla `ciclo` ⇒ el agente
   está trabajando y no está aprendiendo nada verificable. Se escala: cambio de estrategia forzado
   (se inyecta la fila `plan` con `AGOTADO: <criterio>; prueba otra vía`) y, al 5º, parada con pregunta.

Y el techo duro: `harness/limites.py` (hoy **huérfano total**) se cablea de verdad — ejes pasos/segundos/
tokens/USD con `LimiteExcedido` tipada. `/largo` lo fija por defecto a 6 h y 4M tokens.

---

## 10. Cuándo se resetea el contexto (condiciones de RESET)

**Nunca por reloj.** Cinco disparadores, el primero que ocurra:

| # | Condición | Umbral | Evidencia |
|---|---|---|---|
| R1 | **Acciones del ciclo** | **8** | H(0.5)≈8 turnos para Gemma3-27B, ≈15 para Qwen3-32B (arXiv:2509.09677) |
| R2 | **Saturación** | `prompt_tokens ≥ 0,60 × n_ctx_slot` | H5: por saturación 19,8 min/día vs 137 por ciclo |
| R3 | **Sello de criterio** | `GoalContract.check()` pasa uno nuevo | corte limpio, el mejor momento para lobotomizar |
| R4 | **Cascada de error** | 2 fallos consecutivos con la misma firma | self-conditioning: 85%→70% con 25% de errores en la traza |
| R5 | **Límite** | `LimiteExcedido` | `harness/limites.py` |

**Qué sobrevive al reset:** la base SQLite entera (está en disco) y **la cabecera P+D verbatim**.
**Qué muere:** los mensajes, la traza de errores crudos, todas las filas de banda V no ascendidas.
Ésta es la parte no negociable del estado del arte: **la traza de errores no viaja; viaja la fila `error`
tipada con su firma y su anticuerpo.** El error se conserva como *conocimiento*, no como *contaminación*.

---

## 11. Compresión: NO EXISTE. Hay proyección.

**No hay ningún resumidor en este diseño.** La palabra "compresión" se sustituye por **proyección**: elegir
qué filas ya existentes entran al prompt del ciclo siguiente. Nada se reescribe, luego nada se degrada.

```
def proyectar(ciclo, tarea_actual, tope=3600):
    P = todas las 'restriccion'/'objetivo'/'criterio' vigentes, VERBATIM, orden por id  # sin selección
    D = últimas 30 'decision' vigentes, VERBATIM
    H = fijadas ∪ bm25(tarea_actual, k=12)  # ← la ÚNICA selección del sistema
        fijadas = filas con arista 'requiere'/'veta' hacia un pendiente vivo
        filtro: estado IN ('verificado','sospechoso') AND ciclo_baja IS NULL
        cada fila se emite con su marca: [V]erificado / [S]ospechoso + confianza a 2 decimales
    V = plan actual + pendientes vivos  (al FINAL)
    envelope = f"MEMORIA: {len(P)}P {len(D)}D {len(H)}H de {total} filas; consulta='{q}'; 0-hits={n0}"
```

El `envelope` es obligatorio y va en el prompt. **Cero resultados es una línea explícita, jamás una
cadena vacía** — lección "un fallo que devuelve None es invisible".

**Sleep-time compute (arXiv:2504.13171, ~5× menos cómputo test-time):** con 1 slot ocioso mientras corre
una herramienta lenta (pytest de 40 s), `proyectar()` **pre-computa** la banda H del ciclo siguiente y
**pre-calienta el prefijo** enviando la cabecera con `max_tokens=1`. Medido: cabecera 16k + cola distinta
= 242 ms vs 5.830 (**24×**). Como la cabecera P+D es byte-idéntica entre ciclos, el reset **no paga
prefill de cabecera**: sólo la cola nueva.

---

## 12. Snapshots y rollback

**Un snapshot es un manifiesto, no una copia.** Como toda fila es inmutable y tiene `ciclo_alta`, el estado
en el ciclo K se reconstruye con `WHERE ciclo_alta<=K AND (ciclo_baja IS NULL OR ciclo_baja>K)`. El
snapshot sólo graba `max_fila_id`, el sha de la lista de vigentes y el sha de la cabecera.

**Coste: ~180 bytes por ciclo. 500 ciclos = 90 KB.** La base entera tras 500 ciclos: ~6.000 filas × 400 B
+ prov + verificaciones ≈ **4 MB**.

**Rollback a K** (`/memoria rollback 137`):
1. `INSERT` de una fila `decision` con `texto='ROLLBACK a c137: <motivo>'` — **el rollback también es
   append-only y queda en el historial**.
2. `UPDATE fila SET ciclo_baja=<actual> WHERE ciclo_alta>137` — no se borra nada, se marca no-vigente.
   `/memoria ver <id>` sigue mostrando las filas revertidas con el motivo.
3. Restaurar el disco con `harness/checkpoints.py` usando `snapshot.ckpt_disco`.
4. Verificar: `snapshot.vigentes_sha` recalculado debe cuadrar; si no, se aborta y se avisa.
5. **Re-verificar** los verificadores de las filas restauradas: el disco cambió, sus hechos pueden no valer.

**Recuperación de estado corrupto** (`/memoria fsck`): cinco chequeos con reparación explícita —
(a) filas `verificado` sin `prov_id` ni `verificador` ⇒ a `hipotesis`; (b) `prov` huérfana ⇒ se conserva
(es evidencia); (c) `verificador` con `examen_ok=0` que concedió ascensos ⇒ todos sus ascensos revocados;
(d) contradicciones vivas sin arista ⇒ se crean; (e) DB ilegible ⇒ se reconstruye la banda P desde
`.cognia/memoria/<task_id>.cabecera.txt`, un fichero de texto plano que se reescribe cada vez que cambia P.
**La banda P tiene doble soporte a propósito: es lo único cuya pérdida no es recuperable.**

---

## 13. Multiagente: contexto sellado, retorno TIPADO

Un solo escritor (la raíz). Los sub-agentes son **secuenciales** (el +90,2% de Anthropic cuesta 15× tokens
y aquí hay 1 slot; el cambio de agente además invalida el cache: 10,68 s vs 0,28 s medidos).

**Contrato de sub-agente** (`agent/tools.delegar_subtarea`, reusado con el retorno cambiado):
- **Entra:** cabecera P verbatim (idéntica, para que el prefijo siga cacheado) + su subtarea + ≤5 filas H
  fijadas. **Nada de la traza del padre.**
- **Sale:** NO 600 chars de prosa. Sale un **JSONL de filas tipadas**, cada una con la `prov` que el
  interceptor grabó durante *su* ejecución (mismo proceso, misma tabla, `agente='sub:<id>'`).
- **Su contexto se destruye.** Sus filas sobreviven porque llevan provenance de máquina.
- **Sus filas entran como `hipotesis`** aunque él las declare verificadas, salvo las de `autor=interceptor`.
  Un sub-agente no puede ascender nada por su cuenta: el ascenso lo hace el proceso raíz re-ejecutando.

Formato exacto del retorno:
```jsonl
{"tipo":"hecho","clave":"archivo:cognia/memoria_ep/almacen.py","valor":"3f9c…","texto":"almacen.py creado, 214 líneas","prov":812}
{"tipo":"error","clave":"err:sqlite3.OperationalError:database is locked","valor":"presente","texto":"WAL + 2 procesos: hay que cerrar la conexión del CLI antes","prov":815}
{"tipo":"hipotesis","clave":"nota:falta_indice","valor":"?","texto":"la consulta por clave podría necesitar índice","verificador":"venv312\\Scripts\\python.exe -m pytest -q tests/test_almacen.py -k indice","espera":"exit==0"}
```

---

## 14. VRAM y los números del ciclo

**La lobotomía NO se justifica por VRAM. Se justifica por tiempo y por desinfección.** Repetido aquí
porque es la mentira más cómoda del proyecto.

Configuración recomendada, con la fórmula validada 6/6 (`capas_ATENCIÓN=8` para el 9B, no 33):

| Config | KV | SSM | Pesos | Overhead | **Total** | Libre de 16.311 |
|---|---|---|---|---|---|---|
| Hoy: `--ctx 200192 --parallel 1` | 6.256 | 50 | 5.358 | ~1.490 | **13.155** | 3.156 |
| **Propuesta: `--ctx 65536 --parallel 2`** | **2.048** | 100 | 5.358 | ~1.490 | **~8.996** | **~7.315** |

Dos slots de **32.768** tokens sobre **una sola copia de pesos**, cada uno con su cache (no se desalojan
entre sí). **Slot 0 = ejecutor. Slot 1 = crítico C2 / re-verificación / pre-calentado.** Libera ~4,2 GB
para un VLM o el oráculo.

**KV en f16, no q8_0.** El q8_0 ahorraría 960 MiB más, pero **nadie ha medido la calidad con q8_0 en este
proyecto** y este diseño depende de que el modelo lea sus propias restricciones sin degradarse. Se declara
como experimento pendiente, no se adopta a ciegas.

**Regla de despliegue obligatoria:** todo cambio de `--ctx-size` se valida con delta de `nvidia-smi` contra
la fórmula **antes de correr nada**. Windows desbordó a RAM compartida sin emitir un solo error (pidió
1.792 MiB y subió 2.582). Un script `planes/agente_largo/exp/verifica_vram.py` que falla si el delta se
desvía >5% es parte de la entrega.

### Presupuesto de tokens y tiempo

| Concepto | Tokens | Segundos (a 2.620 tok/s prefill / 60 tok/s decode) |
|---|---|---|
| Banda P (objetivo + 24 restricciones + 6 criterios) | **~900** | 0,34 (y **0,00 con cache caliente**) |
| Banda D (30 decisiones) | ~1.100 | 0,42 |
| Banda H (12 hechos + envelope) | ~700 | 0,27 |
| Banda V (plan + 5 pendientes) | ~500 | 0,19 |
| **Semilla del ciclo** | **~3.200** | **1,22 s en frío, ~0,25 s con prefijo cacheado** |
| 8 acciones × (salida de tool ~600 tok, append puro) | ~4.800 | ~1,83 (append reusa: medido +3.000→3.018) |
| 8 respuestas × ~150 tok de decode | 1.200 | **20,0 s** ← el coste dominante |
| Emisiones AFIRMO/DECIDO (4 × ~55 tok) | ~220 | 3,7 |
| Re-verificación programada | 0 | ≤1,5 |
| **CICLO COMPLETO (sin tiempo de herramienta)** | **~9.400** | **~27 s** |

**Sobrecarga de mi propio diseño: ~220 tokens de emisión + ~700 de banda H = 920 de 9.400 = 9,8%.**
Es el precio honesto. Lo que compra: que el 90% restante no esté contaminado.

- Reset cada **8 acciones** ⇒ ~27 s/ciclo + tiempo real de herramientas.
- **500 ciclos ≈ 4,7 M tokens ≈ 3,75 h de LLM** + herramientas. Encaja en "horas o días".
- Arrastrar 64k en vez de resetear: prefill 27,30 s **por llamada** ⇒ ×9,6. Ahí está el ahorro real.
- Base de datos tras 500 ciclos: **~4 MB**. Cabecera P en texto plano: ~4 KB.

---

## 15. Ciclo de vida de una tarea

```
/largo "Cablear el canal de estado al bucle y dejarlo verde"
  │
  ├─ c0  SIEMBRA: el dueño (o `agent/intent.py`) fija objetivo, restricciones y criterios.
  │      → filas banda P, autor='dueno', estado='verificado', confianza=1.00, INMUTABLES.
  │      → snapshot(0). Se escribe .cabecera.txt.
  │
  ├─ cN  ARRANQUE:  gate_presencia == 1.00  (si no, no arranca)
  │      PROYECCIÓN: P+D verbatim | H por BM25 | V al final     [~3.200 tok]
  │      RECITACIÓN: 'RECITO: r1,r2,r7'  (obligatoria, 1ª emisión)
  │      ≤8 ACCIONES: cada tool → interceptor.despues() → fila `prov`
  │                   + fila `hecho`/`error` autor='interceptor' estado='verificado'
  │                   el modelo emite AFIRMO/DECIDO → filas `hipotesis`/`decision`
  │      ASCENSO:    verificadores nuevos → control negativo → ejecución → verificado|refutado
  │      CONTRADICCIONES: SELECT por clave → aristas → re-verificación
  │      SELLO:      GoalContract.check() sobre disco, criterios congelados
  │      CIERRE:     gate B (huérfanas), snapshot(N), UPDATE ciclo
  │      RESET:      R1..R5 → contexto DESTRUIDO
  │
  └─ FIN: (a) todos los criterios sellados y re-verificados en el mismo ciclo; o
          (b) 5 ciclos con ascensos=0 (esterilidad); o
          (c) LimiteExcedido; o (d) el dueño para.
          → `/largo informe` imprime: criterios sellados, filas verificadas, refutadas,
            contradicciones abiertas, verificadores en cuarentena, coste real.
```

**El fin de tarea exige re-verificación en el ciclo final.** Sellar con hechos verificados hace 200 ciclos
no cuenta: se re-ejecutan **todos** los verificadores de las filas que satisfacen criterios. Es el único
momento donde el presupuesto de re-verificación no está capado.

---

## 16. Cómo se teclea (CLI de Cognia)

Registro en `cli.py` junto a `/estado` (línea ~2088) y `/compactar` (~2035). Dos familias:

```
/largo "<objetivo>"              arranca la tarea larga (crea task_id, siembra banda P interactivamente)
/largo estado                    ciclo actual, gate_presencia, ascensos/ciclo, deriva, presupuesto
/largo parar                     corte limpio con snapshot
/largo informe                   el cierre completo

/memoria                         panel: filas por tipo/estado, tokens de cabecera, contradicciones vivas
/memoria ver 47                  la fila + su prov + sus verificadores + el historial de verificaciones
/memoria buscar "canal estado"   lo que devolvería la proyección de la banda H, con el envelope
/memoria contradicciones         pares con arista 'contradice', ambos textos lado a lado
/memoria examen                  re-corre el control negativo de TODOS los verificadores
/memoria fsck                    los 5 chequeos de §12, con --reparar
/memoria snapshot                fuerza snapshot manual
/memoria rollback 137            con diff de qué filas dejan de estar vigentes, pide confirmación
/memoria retirar 12 "obsoleta"   ÚNICA vía para quitar una restricción de banda P. Sólo el dueño.
/memoria exportar                JSONL de todo, para auditoría externa
```

Lo que ve el usuario en `/memoria`:

```
 MEMORIA — task 20260819-canal  ciclo 137/∞
 ┌ BANDA P (verbatim, siempre)          24 filas    892 tok   gate_presencia 1.00 ✓
 ├ BANDA D (decisiones vigentes)        30 de 41   1.104 tok
 ├ BANDA H (hechos)      verificado 218 | sospechoso 11 | refutado 34
 └ BANDA V                              muere al cerrar el ciclo
 verificadores  61 activos | 3 en CUARENTENA (examen negativo suspendido)
 contradicciones VIVAS  2   → /memoria contradicciones
 ascensos últimos 5 ciclos  4, 2, 0, 3, 1     esterilidad: no
 DB 3,7 MB · re-verificación media 1,2 s/ciclo · sobrecarga 9,4% de tokens
```

### Módulos reales

**Reuso tal cual:** `harness/interceptor.py` (antes/despues — el enchufe único), `estado/canal.py` (las 11
funciones huérfanas: `anotar_restriccion`, `anotar_decision`, `_presente`, `_cobertura`, `conservacion`,
`sembrar_trazadores`, `comprobar_trazadores`, `serializar/guardar/cargar`), `estado/presupuesto_progreso.py`,
`agent/horizonte.py` (subiendo `_TECHO_CICLOS=3` a configurable y arreglando la resolución de rutas),
`agent/estado_tarea.py`, `agents/goal_contract.py`, `flujos/examen.py` (control negativo),
`inmune/anticuerpos.py` + `autopsia/causal.py` (loops), `harness/oraculo.py` (C3),
`harness/limites.py` + `harness/contexto_vivo.registrar_uso` (hoy con **cero llamadores**: se cablean en
`loop.py:1077`, donde ya se lee `resp.usage.prompt_tokens` y se tira), `harness/checkpoints.py`,
`agent/workflows.criticar` (sólo comparativo), `search/evidencia.verificar_cita`, `agent/rlm.ContextoVivo`
(corpus externo para salidas gigantes), `agent/tools.delegar_subtarea`.

**Creo:** `cognia/memoria_ep/{esquema,almacen,provenance,ascenso,contradicciones,recuperacion,cabecera,snapshot,fsck}.py`
+ `cognia/agent/largo.py` (driver) + comandos de CLI + `tests/test_memoria_ep_*.py`.

**NO uso (antipatrones activos):** `memory/memory_compressor.py` (clustering que BORRA originales),
`memory/forgetting.py` (decay temporal sobre restricciones), `memory/long_term_consolidator.py`
(**promueve a hecho por repetición ≥3**: es exactamente la máquina de convertir alucinaciones en verdades
permanentes que este diseño existe para impedir).

---

## 17. Evaluación experimental (pregunta 18)

Pre-registro, doctrina del repo: brazos **intercalados**, netos **apareados intra-corrida**, **n≥6**,
**brazo nulo** obligatorio, `--parallel 2` fijo, mismo modelo, misma semilla de tareas.

**Métrica primaria:** criterios de `GoalContract` sellados **y re-verificados en el ciclo final**, por hora
de pared. **Brazo nulo:** recuperación **aleatoria** de la banda H (no "sin memoria": el nulo es el azar).

| Exp | Pregunta | Brazos | n | Predicción falsable |
|---|---|---|---|---|
| **E1** | ¿La cabecera verbatim vale? | verbatim / seleccionada por BM25 / nula | 8×3 | recall de restricciones 1,00 vs ~0,53 vs ~0,08 (replica H4) |
| **E2** | ¿El control negativo caza verificadores tramposos? | con examen / sin examen | 40 verificadores | ≥15% de los verificadores emitidos por el modelo suspenden |
| **E3** | ¿El append-only evita la deriva? | append-only / reescritura del estado | 6×2, 200 ciclos | reescritura pierde ≥50% de restricciones en <20 ciclos |
| **E4** | ¿BM25 basta o hacen falta embeddings? | fts5 / hash-256 / azar | 200 consultas etiquetadas | si fts5 − azar < +0,15 de recall@12, el diseño de recuperación está roto |
| **E5** | ¿Cuántas contradicciones quedan en `nota:`? | auditoría manual de 100 pares | 100 | mide el punto ciego declarado en §5c |
| **E6** | ¿Reset por acciones o por saturación? | R1=8 / R1=16 / sólo R2 | 6×3 | R1=8 gana en sellos/hora (H≈8 turnos) |
| **E7** | ¿C2 comparativo bate al azar? | A-vs-B / absoluto / azar | 60 pares | absoluto ≈ 0,50; comparativo > 0,60 o C2 se retira |

**E2 y E7 son los que deciden si este diseño existe.** Si el control negativo no suspende a nadie, el
ascenso es teatro. Si el crítico comparativo está en el azar, C2 se borra y quedan sólo C1 y C3.

---

## 18. Las 18 preguntas, respondidas con mecanismo

| # | Pregunta | Mecanismo |
|---|---|---|
| 1 | Qué es sólido | Destruir el contexto (desinfección de self-conditioning: 85→70→55%), tipar por persistencia, sub-agentes secuenciales aislados, canal de estado explícito (recall 0,07→1,00) |
| 2 | Qué fallará | Todo lo justificado por VRAM (0 MiB de ahorro); la selección por relevancia de restricciones (0,526); el crítico LLM absoluto (0,52 = azar); la confianza auto-declarada; la compresión por ciclo (137 min/día) |
| 3 | Tras cientos/miles de ciclos | 4 MB de DB, 9.400 tok/ciclo constantes. Lo que crece: banda P (§20 modo 2), filas `nota:` fuera de detección, verificadores baratos |
| 4 | Evitar degradación de memoria | **No existe la operación que degrada**: filas inmutables, append-only, invalidación temporal, cero resumidores. La banda P se re-emite verbatim |
| 5 | Alucinaciones persistentes | Nada asciende sin verificador re-ejecutable; re-verificación programada 1,5 s/ciclo; frescura degrada a `sospechoso` a los 60 ciclos; `sin_huella` contra la tabla `prov` |
| 6 | Que el crítico no valide errores | El crítico **no valida**: ejecuta (C1 control negativo). C2 sólo comparativo A-vs-B. C3 otra familia con presupuesto. Ningún LLM concede `verificado` |
| 7 | Loops | `pasos_sin_avance≥6` + firma de acción repetida ×3 con veto en `interceptor.antes` + anticuerpo sintetizado + esterilidad epistémica (3 ciclos con 0 ascensos) |
| 8 | Pérdida de objetivo | `gate_presencia==1.00` al arrancar (aborta si no) + recitación obligatoria + gate de acciones huérfanas >50% en 2 ciclos |
| 9 | Cuándo resetear | R1 8 acciones / R2 saturación 0,60 / R3 sello / R4 cascada de error / R5 límite. **Nunca por reloj** |
| 10 | Cuánto guarda un snapshot | **~180 bytes**: es un manifiesto (`max_fila_id` + sha de vigentes + sha de cabecera + id de checkpoint). El estado se reconstruye por `ciclo_alta/ciclo_baja` |
| 11 | Estructura de memoria | 4 bandas × 10 tipos × 5 estados epistémicos, en 8 tablas SQLite con FTS5. §2 |
| 12 | Provenance y confianza | Provenance la escribe `interceptor.despues()` desde la llamada real — **el modelo no tiene esos campos**. Confianza = fórmula determinista recalculable, §3 |
| 13 | Coordinar agentes | Secuenciales, un escritor, cabecera P idéntica (cache), retorno **JSONL tipado** con prov de máquina, contexto destruido, entran como `hipotesis` |
| 14 | Minimizar VRAM | `--ctx 65536 --parallel 2` ⇒ ~9,0 GB (de 13,2), 2 slots de 32k sobre una copia de pesos. Validación obligatoria con delta de `nvidia-smi` |
| 15 | Minimizar tokens | Semilla 3.200 tok; cabecera byte-idéntica ⇒ prefill ~0 con cache (24× medido); emisión del modelo 220 tok/ciclo; sobrecarga total 9,8% |
| 16 | Estado corrupto | `/memoria fsck` con 5 chequeos y `--reparar`; banda P con doble soporte (DB + `.cabecera.txt`); `prov` huérfana se conserva (es evidencia) |
| 17 | Rollback | `UPDATE ciclo_baja` (no borra) + checkpoint de disco + **re-verificación obligatoria** de lo restaurado + fila `decision` que registra el propio rollback |
| 18 | Evaluación | 7 experimentos pre-registrados, brazo nulo = azar, métrica = criterios sellados y re-verificados por hora. §17 |

---

## 19. Comparación honesta con el estado del arte

| Familia | Qué tomo | Qué rechazo y por qué |
|---|---|---|
| **Context compression** | Nada. | La proyección no comprime: **selecciona filas ya escritas**. Comprimir la banda P bajó el recall a 0,526 |
| **Summarization memory** | Nada. | Es el antipatrón central: `−39%` single→multi-turn con `+112%` de no-fiabilidad (Laban 2025) |
| **Recurrent memory (RMT/Titans)** | El **teorema**: un estado pequeño y de tamaño fijo sostiene millones de tokens. | El sustrato: no hay checkpoint de 27B instruido; los 11,1M de RMT son GPT-2 fine-tuneado. Mi sustrato es texto **inspeccionable** |
| **External memory (MemGPT/Letta)** | El ciclo lobotomía + almacén externo. | Que el modelo gestione su propia memoria con confianza auto-declarada |
| **RAG** | BM25/FTS5 para la banda H, con envelope. | Aplicarlo a objetivo/restricciones: ahí RAG **es el bug** (0,526 vs 1,000) |
| **Episodic memory** | La tabla `prov` **es** memoria episódica: cada acción con su huella. | El decay temporal (`memory/forgetting.py`) sobre governance |
| **Hierarchical memory** | La jerarquía **por persistencia**, no por tiempo ni por importancia. | La consolidación por frecuencia (`long_term_consolidator`: ≥3 repeticiones ⇒ hecho permanente) |
| **Agentic workflows** | Sub-agentes secuenciales con contexto sellado y retorno tipado. | Paralelos: 15× tokens, 1 slot, y cambiar de agente invalida el cache (10,68 s vs 0,28) |
| **Reflection** | Nada en modo "reflexiona y mejora". | Huang ICLR'24 / Kamoi TACL'24: la auto-corrección sin señal externa degrada |
| **Verifier models** | **Todo el núcleo**: el verificador que ejecuta es la única variante que sube (0,681). | El verificador-LLM que puntúa (0,517 = azar) |
| **State-space** | La contabilidad honesta del KV (los modelos son híbridos: 8 capas de atención de 33) | — |
| **Zep/Graphiti** | **Validez bi-temporal**: un hecho no se reescribe, se invalida. Es mi `ciclo_baja` + `arista('invalida')` | Sus cifras (LoCoMo cabe en la ventana; 84%→58,44% en su propio repo) |
| **Sleep-time compute** | Pre-computar la proyección y **pre-calentar el prefijo** con el slot ocioso (24× medido) | — |

**Qué es NOVEDOSO de verdad** (no lo he encontrado con nombre propio en el estado del arte):
1. **Provenance escrita por el harness, nunca por el modelo.** Los sistemas de memoria con provenance
   (A-MEM, Zep, HippoRAG) hacen que el LLM rellene la atribución. Aquí las seis columnas de origen las
   escribe el interceptor desde la llamada real. **Elimina la superficie de mentira en vez de detectarla.**
2. **Control negativo del verificador como requisito de ascenso.** Un verificador tiene que *suspender*
   con la evidencia destruida antes de poder conceder un solo `verificado`. Nadie en la literatura de
   memoria examina el verificador; se examina la respuesta.
3. **Vocabulario de claves cerrado emitido por la capa de herramientas**, que convierte la detección de
   contradicciones en un `GROUP BY` determinista en vez de una tarea de NLI.

**Qué ya tiene nombre:** bi-temporalidad (Zep), tipado + almacén externo (MemGPT/A-MEM), BM25 (RAG),
orquestador-trabajador sellado (Anthropic), verificador ejecutante (process/outcome verifiers), recitación
(+4% RULER), sleep-time compute, y el propio ciclo de lobotomía (que **ya existe en este repo**:
`agent/horizonte.py:ciclos_con_contrato`, opt-in `COGNIA_HORIZONTE=1`).

**La combinación más potente:** *cabecera permanente verbatim que nunca se comprime* **×** *almacén
append-only con provenance de máquina* **×** *verificador ejecutante examinado por control negativo*
**×** *recuperación selectiva limitada a la banda de baja persistencia* **×** *reset por acciones y
saturación sobre 2 slots de 32k*. Quitar cualquiera de los cinco rompe el conjunto: sin la primera vuelve
el 0,526; sin la segunda vuelve la cascada; sin la tercera el ascenso es teatro; sin la cuarta el ciclo
cuesta 27,3 s de prefill; sin la quinta no hay dónde correr el crítico.

---

## 20. CÓMO ME ROMPO — 3 modos de fallo tras 500 ciclos

### Modo 1 — Inflación de `verificado` barato (el más probable)

El control negativo caza al verificador que pasa con la evidencia destruida, **pero no al que pasa por un
motivo trivialmente cierto**. `test -f cognia/memoria_ep/almacen.py` suspende el control negativo
correctamente (si borro el fichero, falla) y sin embargo no verifica *nada* de lo que la fila afirma
("almacen.py implementa el ascenso"). Tras 500 ciclos habrá ~200 filas `verificado` cuyo verificador
comprueba existencia y cuyo `texto` afirma comportamiento. **La banda H se llena de verdades irrelevantes
y el agente cree que ha avanzado.** Es la versión epistémica del "contar bien no es medir lo que importa"
(24/24 títulos distintos, once del mismo tema inventado, gate en PASS).

- **Centinela:** `poder_discriminante = |{verificadores que han fallado alguna vez en su historia}| /
  |verificadores|`. Un verificador que en 500 ciclos nunca falló y nunca cambió es sospechoso de ser trivial.
- **Alarma:** si `poder_discriminante < 0,25` a los 100 ciclos, `/memoria` lo pinta en rojo.
- **Mitigación parcial:** exigir que `clase='cmd'` sea la única que concede `verificado` a filas cuyo texto
  contenga verbos de comportamiento. Es una heurística léxica, y las heurísticas léxicas se falsifican.
  **No tengo solución completa para esto y es el agujero real del diseño.**

### Modo 2 — Osificación de la banda P

La banda P no decae **por diseño** (governance decay es un antipatrón demostrado). Consecuencia inevitable:
crece monótonamente. 24 restricciones = 892 tokens; 200 restricciones = ~7.400 tokens, y entonces
(a) la cabecera deja de caber cómoda en un slot de 32k junto al trabajo, (b) el gate de presencia empieza a
fallar por truncado, (c) **restricciones obsoletas vetan acciones válidas** y el agente se queda paralizado
sin poder explicar por qué. La única vía de retirada es `/memoria retirar`, que exige al dueño —
o sea, **el sistema depende de un humano cada ~100 ciclos y eso contradice "trabajar días sin supervisión"**.

- **Centinela:** tokens de cabecera > 1.200 ⇒ el ciclo arranca igual pero `/largo estado` pide revisión.
- **Lo que NO hago:** dejar que el modelo pode restricciones. Es exactamente la cascada 24→2 de H4.
- **Honestidad:** este modo es un límite duro. Un agente que corre 500 ciclos sin supervisión y acumula
  reglas **necesita** un ritual de poda humano, y mi diseño lo hace visible en vez de esconderlo.

### Modo 3 — Deriva de claves y contradicción invisible

Tras 500 ciclos, la mayoría del conocimiento no mecánico vive en `nota:` — precisamente la clase **excluida
de la detección de contradicciones por clave** (§5c). Dos hechos incompatibles pueden coexistir, ambos
`verificado` por verificadores distintos y ambos correctos *en su momento*: "el backend sirve Qwythos-9B"
(c12) y "el backend sirve Qwen3.8-27B" (c380), con claves `nota:modelo_backend` y `cfg:llama.model` que
nunca colisionan porque el modelo eligió prefijos distintos. La proyección BM25 puede traer **las dos** al
mismo prompt y el agente razonará sobre un mundo inconsistente sin que nada emita un error — el **vacío
silencioso**, otra vez, ahora con forma de contradicción no detectada.

- **Centinela:** `ratio_nota = filas('nota:') / filas(banda H)`. Si supera 0,40, la detección de
  contradicciones está ciega para la mayoría del corpus.
- **Segundo centinela:** en cada proyección, contar pares de filas traídas juntas con solape BM25 > 0,7 y
  polaridad opuesta ⇒ emitirlo en el `envelope` como `⚠ 2 pares en tensión`.
- **Lo que falta:** un NLI local barato resolvería esto, y no lo pongo porque el único juez disponible es
  del mismo modelo que está en el azar. **Prefiero declarar el punto ciego que taparlo con un juez que
  aprueba trabajo roto.**

---

*Diseñado contra los cuatro informes de `planes/agente_largo/`. Todo número de VRAM, prefill, cache y
recall proviene de `medicion_kv.md` y `falsacion.md`; ningún número de este documento es una estimación
silenciosa — los derivados están marcados como tales.*

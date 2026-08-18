# PREREG — ¿El modo RLM hace SINTESIS, o solo LOCALIZA?

Fecha de escritura: **2026-08-18**, ANTES de correr ningun brazo con GPU.
Resultados medidos despues, en la seccion 8 (el diseno de arriba no se toco).
Banco: `scripts/banco_rlm_sintesis.py` · Tests del banco: `tests/test_banco_rlm_sintesis.py` (20 passed)
Semilla: `20260818`. Todo el corpus, las preguntas y las verdades son deterministas.

---

## 0. La pregunta y por que hay que hacerla

Todo lo que este repo tiene MEDIDO del modo RLM es **localizacion de aguja
literal**: `scripts/e2e_rlm_smoke.py` y `scripts/rlm_escala.py` esconden un token
hex de 8 caracteres en un pajar y preguntan por el. Eso mide BUSCAR.

El objetivo del dueño es *"que el chat principal sea de 1M"*, y la via elegida es
el RLM (contexto por herramientas en vez de por ventana: 9-24 s contra los ~34
min de prefill del millon nativo). Pero un chat de 1M que solo sabe encontrar una
cadena literal no es un chat de 1M: es un buscador. La pregunta abierta es
**SINTESIS**: contar sobre muchos documentos, comparar dos, y cruzar hilos entre
documentos distintos. El propio docstring de `cognia/agent/rlm.py:27-29` declara
ese limite. Este banco lo cierra.

---

## 1. El corpus (identico en las tres celdas)

90 **INFORMES** con 7 campos comparables (`Planta, Turno, Operador, Estado,
Temperatura, Incidencias, Firma`) + `Lote auditado`, y 60 bloques
**AUDITORIA** (`Lote revisado / Auditor responsable / Sede`). Bloques
**barajados e intercalados** con relleno, para que ni la primacia ni la recencia
regalen una familia entera. Las auditorias NO van en el orden de los informes: si
lo estuvieran, el "cruce" se resolveria por posicion.

Tres decisiones que hacen falsable el banco:

- **La verdad se calcula de los DATOS, nunca del texto.** Si se leyera del corpus
  renderizado, un bug del renderizador se volveria verdad y el banco aprobaria al
  instrumento roto. Un test cruza las dos: `test_conteo_del_texto_igual_al_de_los_datos`.
- **El relleno es disjunto de todo valor de campo y no tiene digitos**, verificado
  con `assert` al generar y con test. Un relleno que dijera "FALLA" cambiaria los
  conteos en silencio.
- **Los conteos verdaderos viven en [2,12]** (pesos desiguales a proposito). Asi,
  fallar significa "no sabe agregar" y no "no sabe contar hasta 40".

### Las tres celdas — mismas 90 preguntas, mismas respuestas, solo cambia el relleno

| celda | relleno | corpus | que ve el brazo tonto (ventana 16.384) |
|---|---|---|---|
| **CABE** | 0 | 29.498 chars (~10.600 tokens; el corpus v1 de 31.988 chars midio **11.503 tokens** con `/tokenize`) | **100%** |
| **APENAS** | 14.314 (autocalibrado a la ventana) | 44.037 chars | **89,5%** |
| **NO_CABE** | 2.000.000 | 2.029.678 chars | **1,9%** |

Corpus **v2** (ver enmiendas). 90 informes + 60 bloques de auditoria.

---

## 2. Las 6 familias de preguntas (15 cada una, N = 90)

Ninguna es "encontra la aguja": ninguna respuesta esta escrita literalmente en el
corpus.

| tipo | familia | que exige | respuesta |
|---|---|---|---|
| `contar_simple` | CONTAR | cuantos informes tienen Campo=valor | entero 0..90 |
| `contar_conjuncion` | CONTAR | cuantos cumplen DOS campos **en el mismo informe** | entero 0..90 |
| `comparar_campo` | COMPARAR | cual es el UNICO de los 7 campos en que difieren los informes A y B | nombre de campo (7) |
| `comparar_ndif` | COMPARAR | en CUANTOS de los 7 campos difieren A y B | entero 1..7 |
| `cruzar_auditor` | CRUZAR | informe → su lote → bloque AUDITORIA de ese lote → auditor | nombre (8) |
| `cruzar_contar` | CRUZAR | cuantos informes de la Planta P tienen su lote auditado por Q | entero 0..90 |

### LA TRAMPA DEL GREP, DECLARADA POR ADELANTADO

`ctx_grep` imprime literalmente `"RESULTADO ctx_grep: N de TOTAL matches"`
(`cognia/agent/rlm.py:963`). O sea que **un conteo de una sola linea lo resuelve
la HERRAMIENTA, no el modelo**. Por eso las familias estan partidas:

- `contar_simple` **es grepeable** de un patron → es el **diagnostico**, no el merito.
- `contar_conjuncion`, `cruzar_auditor` y `cruzar_contar` **no lo son**: exigen
  asociar dos lineas dentro del mismo bloque o encadenar dos bloques distintos.

**Regla de lectura preregistrada:** si el RLM gana en `contar_simple` y no en
`contar_conjuncion`, el veredicto es *"cuenta la herramienta, no el modelo"* y
sigue siendo LOCALIZACION.

---

## 3. Los brazos

| brazo | GPU | que es |
|---|---|---|
| `oraculo` | no | el calificador sobre la verdad. **Compuerta**: si no da 90/90 el banco no mide nada y la corrida se anula. |
| `azar_uniforme` | no | sortea del espacio de respuestas que la pregunta DECLARA ("responde con un entero entre 0 y 90"). |
| `azar_marginal` | no | sortea de la distribucion empirica de respuestas de su MISMO tipo, **leave-one-out**: el adivinador que conoce el banco pero no ha leido el corpus. **Es la referencia preregistrada, la dificil.** |
| `techo_tonto` | no | el oraculo aplicado SOLO a los bloques completos que caben en la ventana del brazo tonto. |
| `tonto` | si | "meter todo lo que quepa en la ventana": UNA llamada, corpus truncado por la cabeza, pregunta al final, `temperature=0`. |
| `rlm` | si | `correr_rlm` sobre el corpus entero, sampling de produccion. |

Notas de diseño que son parte del contrato:

- **La pregunta va AL FINAL en el brazo tonto** para que el prefijo sea identico
  entre preguntas y el cache de prompt de llama-server lo reuse. Sin eso el brazo
  costaria 90 prefills gigantes y seria incorrible. Es tambien lo que hace un chat
  real.
  **PERO el cache exige el slot EN EXCLUSIVA.** Verificado el 2026-08-18 durante
  el piloto: con la corrida de 200k ocupando el mismo slot, `/slots` reportaba
  `n_prompt_tokens: 11635` con `n_prompt_tokens_cache: 3` — cero reuso, porque
  cada peticion ajena pisa el cache. **El banco hay que correrlo con el slot
  libre**, o el brazo tonto cuesta 90 prefills completos en vez de uno.
- **Al tonto se le da su mejor tiro** (greedy, `temperature=0`), al RLM su sampling
  de produccion. La asimetria es a favor del rival, a proposito.
- **Un fallo de formato se cuenta APARTE** (`sin_formato`). Un fallo del
  instrumento no es un fallo del modelo hasta que se demuestre.

---

## 4. HALLAZGO PREVIO A LA GPU: el brazo tonto se DERRUMBA, no se degrada

Medido sin gastar un token (`techo_tonto` sobre la celda NO_CABE, oraculo aplicado
a lo visible):

| corpus visible | techo del tonto | por tipo (simple/conj/campo/ndif/auditor/cruzcont) |
|---|---|---|
| 1,9% (celda NO_CABE) | **0/90 (0,0%)** | 0/0/0/0/0/0 |
| 10% | **0/90 (0,0%)** | 0/0/0/0/0/0 |
| 25% | **4/90 (4,4%)** | 0/1/1/0/2/0 |
| 50% | **15/90 (16,7%)** | 0/1/2/5/6/1 |
| 75% | 37/90 (41,1%) | 5/3/6/11/8/4 |
| 89,5% (celda APENAS) | 53/90 (58,9%) | 6/5/10/12/11/9 |
| 95% | 73/90 (81,1%) | 11/10/12/14/13/13 |
| 100% (celda CABE) | **90/90 (100%)** | 15/15/15/15/15/15 |

**Y no es un artefacto de truncar por la cabeza.** Los bloques se **barajan antes
de renderizar**, asi que quedarse con el primer X% del corpus equivale a una
muestra aleatoria uniforme de bloques. Un brazo tonto "mas listo" que muestreara
a lo largo del corpus tendria el MISMO techo. La curva es del truncado, no del
extremo elegido.

**Consecuencia que cambia el diseño, y hay que decirla en voz alta:** con la mitad
del corpus el techo del camino tonto (16,7%) ya esta **al nivel del azar marginal
(16,2%)** — o sea que un lector PERFECTO de media ventana no le gana a adivinar.
La sintesis no tolera truncado: contar exige verlo todo. Por lo tanto:

- En **NO_CABE**, ganarle al brazo tonto **no prueba nada** (su techo es 0/90). Ahi
  el unico rival legitimo es el AZAR.
- El brazo tonto solo es un rival de verdad en **CABE** (techo 90/90) y en
  **APENAS** (techo 48/90). **CABE es la celda decisiva del punto 3 del encargo:
  si ahi el camino tonto empata o gana, el RLM no esta aportando.**

---

## 5. POTENCIA — calculada ANTES, con N = 90

Metrica primaria: **exactitud** (aciertos / 90). Como cada item tiene su propia
probabilidad de azar, la suma es una Poisson-binomial: la distribucion nula se
obtiene por simulacion (B = 200.000) en vez de asumir una binomial.

| referencia | tasa del azar | p95 del nulo | **MDE** (alpha .05 una cola, poder .80) |
|---|---|---|---|
| `azar_uniforme` | 7,4% | 11/90 | **16,7%** de exactitud |
| `azar_marginal` | 16,2% | 20/90 | **27,8%** de exactitud |

Por familia (n = 30 cada una, **secundario**):

| familia | azar marginal | MDE |
|---|---|---|
| CONTAR | 9,6% | 26,7% |
| COMPARAR | 19,1% | 40,0% |
| CRUZAR | 15,8% | 36,7% |

**Lectura honesta de la potencia.** Con N=90 el banco distingue "≥27,8%" de "azar"
pero **NO** distingue 20% de 15%. Por familia la resolucion es aun mas gruesa
(hasta 40 puntos). Se acepta a proposito, porque el umbral de UTILIDAD (abajo)
esta en 60% y el de KILL en 30%: **el diseño ve exactamente la diferencia que
tiene que decidir.** Subir a N=120 solo bajaria el MDE agregado de 25,6% a 25,8%…
(sic: no baja) y el de uniforme de 16,7% a 15,0% — medido en el barrido de
potencia; no compensa el doble de GPU.

Por familia con n=30 el MDE va de 27% (CONTAR) a 40% (COMPARAR): **las
conclusiones por familia solo soportan "claramente por encima del azar" contra
"no distinguible", nunca un ranking fino entre familias.**

**Lo que este diseño NO puede hacer:** afirmar "no hay efecto" cuando el RLM caiga
entre el azar y el MDE. Ese caso se reporta como **"no distinguible del azar con
este N"**, nunca como "no funciona". (Cicatriz del repo: *la potencia se calcula
antes de matar una via*.)

---

## 6. Analisis preregistrado

1. **Primario (¿sintetiza?)** — RLM en la celda **NO_CABE** contra `azar_marginal`,
   una cola, alpha 0,05, p-valor exacto = P(nulo ≥ observado) sobre la simulacion.
2. **Secundario A (¿aporta sobre el camino tonto?)** — RLM vs TONTO en la celda
   **CABE**, **McNemar exacto pareado**, dos colas, alpha 0,05. Pareado porque los
   dos brazos contestan las MISMAS 90 preguntas.
3. **Secundario B (atribucion)** — TONTO en CABE es el **techo del MODELO** con
   informacion perfecta. Si el tonto en CABE tambien fracasa, el limite es del
   modelo y no del RLM, y hay que decirlo asi.
4. **Descriptivo** — por familia y por tipo; `cerca` (error de ±1 en conteos);
   segundos y tokens por pregunta; `sin_formato`.

### Umbrales de VEREDICTO (fijados antes de ver un numero)

Sobre la exactitud agregada del RLM en la celda **NO_CABE**:

- **≥ 60%** → *"el RLM hace sintesis"*. Se puede vender como comprension de corpus grande.
- **30% – 60%** → *"sintesis PARCIAL"*. Se documenta por familia y la ayuda del comando
  dice **que familias** funcionan y cuales no.
- **< 30%**, o **no significativo contra `azar_marginal`** → **KILL de la etiqueta
  "comprension"**: el modo se etiqueta **LOCALIZACION** en el docstring de
  `rlm.py`, en la ayuda de `/rlm` en `cli.py` y en el informe del medidor.

### KILL y VOID explicitos

- **VOID (corrida anulada, no es un resultado):** el `oraculo` no da 90/90; o
  `sin_formato` > 20% en cualquier brazo (eso es el instrumento, no el modelo:
  se arregla el extractor y se re-corre); o el medidor reporta
  `ventana_pico_raiz >= n_ctx` (el corpus se colo en la ventana por la puerta de
  atras y el brazo RLM dejo de ser RLM); o **cualquier item `invalido`**
  (ver abajo).
- **UN RECHAZO NO ES UN CERO.** Si `correr_rlm` devuelve `ok=False` con 0 pasos
  (backend sin tool-calling, ruta ilegible, corpus vacio) el item se marca
  **INVALIDO** y no entra en el denominador. Puntuarlo 0 convertiria una averia
  del instrumento en la conclusion "el RLM no sintetiza" — el falso negativo que
  este banco existe para evitar. Si el PRIMER item sale invalido, el brazo
  **aborta** en vez de anotar 90 ceros.
- **KILL de "el RLM cuenta":** gana en `contar_simple` y no en
  `contar_conjuncion` → lo hizo el contador de `ctx_grep`.
- **KILL de "el RLM aporta":** en la celda CABE, McNemar no rechaza y el tonto
  iguala o supera al RLM. Entonces el valor del RLM es solo de RELOJ y ALCANCE,
  no de calidad, y asi hay que escribirlo.
- **Brazo envenenado → re-baselinear:** si se descubre un bug en un brazo, se
  enmienda este prereg por escrito y se re-corre **TODO**, no solo el brazo roto.

---

## 7. BLOQUEO VERIFICADO: el brazo RLM no puede correr contra el backend de hoy

El modo RLM se toca **solo** con tool-calling nativo. El server que atiende
`:8080` ahora mismo **no parsea tools**, asi que `correr_rlm` devuelve un texto
de ERROR por pregunta sin tocar el corpus. Medido con la sonda **forzada** (sin
cache):

```
venv312\Scripts\python.exe -m cognia.agent.capacidad http://127.0.0.1:8080 --forzar
{ "soporta_tools": false,
  "motivo": "respondio sin tool_calls (finish_reason=stop): el server no parsea
             tools — ¿le falta --jinja, o el modelo no las soporta?",
  "modelo": "qwen2.5-coder-14b-instruct-q4_k_m-00001-of-00002.gguf",
  "latencia_s": 20.93 }
```

Y `/props` + `/slots` de `:8080`: `n_ctx = 16384`, un solo slot,
`is_processing: true`. **Antes de correr el banco hay que levantar un backend
con `--jinja` (la flota: `scripts/servir_flota.py`, cerebro Qwythos).** El banco
lo comprueba solo en el prevuelo y sale con exit 3 en vez de puntuar ceros.

Este bloqueo es la razon por la que el brazo RLM queda pendiente: **no es la GPU
ocupada, es el backend equivocado.** Los dos se resuelven con la misma accion.

## 7bis. Comandos EXACTOS para cerrarlo

La GPU esta ocupada hasta cerca de las 05:00 del 2026-08-18 (`:8080`, un solo
slot, `qwen2.5-coder-14b-instruct-q4_k_m`, **n_ctx = 16.384** — verificado con
`/props` y `/slots`, `is_processing: true`).

**Lo que YA esta hecho** (seccion 8): brazos gratis en las tres celdas, y el
brazo TONTO completo (N=90) en CABE y en APENAS.

**Paso 1 — el que decide, y es BARATO.** Repetir la celda CABE con el cerebro
real (Qwythos-9B servido con `--jinja`), solo el brazo tonto. Es UNA prefill de
~10.600 tokens mas 90 decodificaciones cortas: con el slot libre el 14b lo hizo
en **menos de 3 minutos**. Si Qwythos tampoco pasa del azar aca, el brazo RLM no
hace falta correrlo para saber el veredicto.

```
cd C:\Users\usuario\Desktop\cognia_v2
PYTHONUTF8=1 venv312\Scripts\python.exe scripts\banco_rlm_sintesis.py ^
  --celda cabe --brazos tonto --salida sintesis_cabe_qwythos.json
```

**Paso 2 — el brazo RLM**, solo si el paso 1 muestra sintesis. Necesita el server
con tool-calling (el banco lo verifica en el prevuelo y sale con exit 3 si no lo
hay).

```
REM celda NO_CABE: el regimen operativo del RLM
PYTHONUTF8=1 venv312\Scripts\python.exe scripts\banco_rlm_sintesis.py ^
  --celda no_cabe --brazos todos --salida sintesis_nocabe.json

REM celda CABE: RLM contra el camino tonto, pareado (McNemar)
PYTHONUTF8=1 venv312\Scripts\python.exe scripts\banco_rlm_sintesis.py ^
  --celda cabe --brazos todos --salida sintesis_cabe.json

REM celda APENAS: la unica zona intermedia donde el tonto sigue vivo
PYTHONUTF8=1 venv312\Scripts\python.exe scripts\banco_rlm_sintesis.py ^
  --celda apenas --brazos todos --ventana 16384 --salida sintesis_apenas.json
```

Piloto barato antes de comprometer la noche (2 por familia = 12 preguntas):

```
PYTHONUTF8=1 venv312\Scripts\python.exe scripts\banco_rlm_sintesis.py ^
  --celda cabe --brazos todos --muestra 2
```

Los brazos gratis (oraculo, los dos azares, el techo del tonto y la potencia) no
necesitan backend y ya estan corridos:

```
PYTHONUTF8=1 venv312\Scripts\python.exe scripts\banco_rlm_sintesis.py ^
  --celda no_cabe --brazos gratis --ventana 16384
```

---

## 8. RESULTADOS (se va llenando; el prereg de arriba NO se toca)

### 8.1 Brazos GRATIS — CERRADOS

`oraculo` **90/90 (100%)** en las tres celdas: el banco es respondible, la
compuerta pasa. `azar_uniforme` **7,4%**, `azar_marginal` **16,2%**. La curva del
techo del brazo tonto esta en la seccion 4.

### 8.2 Brazo TONTO — CERRADO en CABE y APENAS (N=90 cada uno)

Backend: `qwen2.5-coder-14b-instruct-q4_k_m`, ventana 16.384, `temperature=0`,
corpus v2, slot exclusivo. `sin_formato`: 0/90 (CABE) y 2/90 (APENAS) — muy por
debajo del 20% que anularia la corrida, o sea que el extractor no esta
inventando fallos.

| celda | info que ve | **techo** | **tonto** | vs `azar_uniforme` | vs `azar_marginal` |
|---|---|---|---|---|---|
| **CABE** | 100% | 90/90 | **14/90 = 15,6%** [9,5–24,4] | p = **0,0047** | p = **0,62** |
| **APENAS** | 89,5% | 61/90 (67,8%) | **18/90 = 20,0%** [13,0–29,4] | p = **0,0001** | p = **0,18** |

Por tipo (CABE): simple **5**/15 · conjuncion **2**/15 · comparar_campo **0**/15 ·
comparar_ndif **3**/15 · cruzar_auditor **2**/15 · cruzar_contar **2**/15.

**EL RESULTADO, SIN ADORNO: el camino tonto NO hace sintesis.** Con el corpus
ENTERO dentro de su ventana y un techo de informacion del 100%, saca 15,6% —
**indistinguible del adivinador marginal (16,2%, p=0,62)**. Le gana al azar
uniforme, si, pero eso solo dice que sus respuestas caen en el rango plausible,
no que sean correctas: `cerca` (±1 en los conteos) es **35/90**, o sea que acierta
el orden de magnitud y falla el numero.

Y el modo de fallo de `comparar_campo` es el mas elocuente: **0/15**, contestando
`RESPUESTA: Lote auditado` — un campo que en el corpus v2 es IDENTICO en los dos
informes y que la pregunta ni siquiera lista. **Reproducido a mano** con una
llamada suelta, y ademas con las DOS redacciones de la pregunta (la v1 no
mencionaba la palabra "lote" y daba lo mismo 5/5): no es la redaccion, es que el
modelo no compara — emite una respuesta fija.

### 8.3 Brazo RLM — PENDIENTE (bloqueado por el backend, no por el reloj)

Ver seccion 7. Requiere un server con tool-calling nativo (`--jinja`).

### 8.4 Lo que esto ya implica para el objetivo "el chat es de 1M"

El techo del MODELO con informacion perfecta esta al nivel del azar. Por lo tanto
**el RLM no puede superarlo por mejor que sea su navegacion**: no se puede
sintetizar mejor de lo que el cerebro sabe sintetizar. Antes de gastar GPU en el
brazo RLM conviene repetir la celda CABE con **Qwythos-9B** (el cerebro real; el
14b de hoy es un modelo de CODIGO y no el que atiende el chat). Dos desenlaces:

- Si Qwythos tampoco pasa del azar en CABE → el cuello es el MODELO, el modo RLM
  queda etiquetado **LOCALIZACION** y el objetivo de 1M hay que replantearlo como
  "1M para buscar", no "1M para entender".
- Si Qwythos si sintetiza en CABE → entonces y solo entonces el brazo RLM en
  NO_CABE mide algo interesante: cuanto de esa capacidad sobrevive cuando el
  corpus deja de caber.

---

## 9. Enmiendas

*(Toda enmienda va aca, fechada, con el motivo. Cambiar el diseño despues de ver
los numeros y no anotarlo es como se fabrica un resultado.)*

- **2026-08-18** — `CHARS_POR_TOKEN` bajado de 3,4 a 2,78 tras medir con
  `/tokenize` (31.988 chars = 11.503 tokens). Solo afecta la estimacion inicial
  del corte; el corte real se mide.
- **2026-08-18** — El relleno se reparte al azar entre los huecos en vez de una
  tanda por hueco. Con 181 bloques, la version vieja imponia un piso de ~22.000
  chars de relleno y hacia inalcanzable el corpus de la celda APENAS (pedia
  43.812 chars y salian 55.842 → 70,6% de visibilidad en vez de 90%). La celda
  CABE (relleno 0) **no cambia**: el piloto ya corrido sigue siendo valido.
- **2026-08-18** — Se añade la celda **APENAS** despues de calcular el techo del
  brazo tonto y descubrir que en NO_CABE su techo es 0/90. El cambio es del
  DISEÑO y se hizo **antes** de correr ningun brazo con GPU sobre las 90
  preguntas.

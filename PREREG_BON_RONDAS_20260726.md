# PRE-REGISTRO — Best-of-N verificado en el lazo + rondas que rematan

**Escrito el 2026-07-26 a las 13:1x, ANTES de implementar y de correr nada.**
Existe para que los umbrales no se elijan después de ver los resultados
(mismo espíritu que PREREG_FP_CONTRATO_20260725.md).

## Contexto medido que motiva esto

- Serie b2 de la config final (runs 4-8): **3, 4, 5, 5, 4 / 6** (media 4.2,
  mínimo 3) contra baseline 2/6. Falta la réplica 6 (run9, en curso al
  escribir esto; su número se suma a la serie ANTES de cualquier comparación).
- Las tareas que fallan ROTAN entre corridas (memoria_4x4 10/10 en run8 y
  falla en otras): el cuello es la VARIANZA de la generación inicial.
- Los fallos quedan a 1-2 checks del pase (contador 9/14, calculadora 7/10 en
  run8) con el tope fijo de 3 rondas: la reparación progresa y se corta.

## Experimento A — Best-of-N verificado DENTRO del lazo

**Mecanismo:** hasta k=3 candidatos iniciales, generados SECUENCIALMENTE: el
juez ejecutable juzga el candidato 1; si aprueba, no se genera nada más (coste
0 extra en el caso bueno). Si falla, se genera y juzga el 2, luego el 3. Se
entra al lazo de reparación con el primer APROBADO o, si ninguno aprueba, con
el de más checks_ok. Sin contrato posible, BoN se desactiva solo (elegir sin
juez sería elegir por opinión).

**Medición:** b2 completo (6 tareas), n≥3 réplicas, config idéntica a la final
salvo `--candidatos 3`. Se mide pass/6 por corrida Y segundos por tarea (cada
candidato extra son ~60-90 s de GPU; el coste se reporta junto al pass).

**Criterio (decidido AHORA):**

| veredicto | condición |
|---|---|
| **PASA** | media ≥ 5/6 en n≥3 réplicas y ninguna corrida < 4/6 |
| **GRIS** | media en [4.5, 5) — mejora real pero no cierra el gate; se combina con reparación |
| **KILL** | media ≤ la media de la serie config-final (con run9 incluido), o coste medio > 2× sin subir la media |

## Experimento B — rondas de reparación que rematan (A/B contra tope fijo)

**Mecanismo:** el tope de rondas sigue en 3, pero si checks_ok del juez CRECIÓ
estrictamente entre la ronda anterior y esta (progreso real, no espiral), se
permite seguir hasta 5. El disyuntor sigue rigiendo: síntoma idéntico dos
veces corta igual que hoy.

**Medición:** b2 completo, n≥3 réplicas, config final + `--rondas-progreso 5`
(sin BoN, para no confundir atribución).

**Criterio (decidido AHORA):**

| veredicto | condición |
|---|---|
| **PASA** | media > media de la serie config-final (run9 incluido) y mínimo ≥ 4/6 |
| **GRIS** | media mejora pero mínimo < 4 — ayuda pero no estabiliza |
| **KILL** | media ≤ la de la serie config-final |

## Caveats declarados antes de correr (revisión adversarial 2026-07-26)

- **El contrato queda anclado al DOM del candidato en cuyo turno se generó**
  (normalmente el 1º): los candidatos siguientes se juzgan contra selectores
  que pueden no usar. Mitigado porque las 6 tareas de b2 fijan los selectores
  como OBLIGATORIOS en el enunciado; sigue siendo un sesgo conocido a favor
  del candidato que fabricó el contrato. Si BoN da GRIS/KILL, esta es la
  primera causa a inspeccionar antes de descartar la vía.
- **El APROBADO del BoN corta el lazo sin re-juzgar** (post-revisión): el
  caso bueno paga 0 extra de verdad. El juez externo de b2 sigue siendo el
  árbitro final del pass/6, así que un falso APROBADO interno no infla el
  número reportado.
- El reintento de contrato se paga sobre el MISMO candidato 1 (no cuesta una
  generación); si ambos intentos fallan, el lazo corre sin juez — igual que
  hoy — y la corrida queda contada en la telemetría de sellos.

## ENMIENDA (2026-07-26 ~14:15, ANTES de re-correr nada)

La réplica 1 del brazo BoN se DETUVO y sus números se descartan: las 4
reparaciones murieron por un bug ortogonal al BoN — el prompt de reparar_web
manda a gpt-oss a una espiral de razonamiento de 22-53k chars que consume los
12.000 tokens sin emitir contenido (probe_reparacion_budget.py: 6/6 sondas
`finish=length` contenido 0; la "Reasoning: low" del system NO lo evita 3/3;
`chat_template_kwargs.reasoning_effort=low` lo cierra 2/2 con la página
completa en ~3.000 tokens). Con ese bug activo, el brazo BoN medía "BoN +
reparación rota", no BoN.

Cambia el diseño de la medición, no los umbrales:

- reparar_web queda arreglado (effort=low + timeout 400 + un reintento) y
  generar_contrato validado contra pasos malformados (el `dict.strip()` que
  dejó a tareas_todo sin juez 5 rondas).
- **Se agrega un brazo BASELINE post-fix** (config final + fixes, sin BoN ni
  rondas): n≥3. La serie pre-fix (3,4,5,5,4,6) ya no es comparable — el fix
  de reparación beneficia a todos los brazos.
- Los criterios de A y B se evalúan contra la MEDIA del baseline post-fix
  (mismos umbrales: PASA si media ≥ 5/6 y ninguna corrida < 4; KILL si
  media ≤ baseline post-fix).

## SEGUNDA ENMIENDA (2026-07-26 ~16:00, tras cerrar basefix y bonfix, ANTES de implementar el brazo C)

Resultados ya cerrados de los dos primeros brazos post-fix:

- **basefix: 3, 4, 3 (media 3.33)** — POR DEBAJO de la serie pre-fix (4.5).
  El fix de reparación (effort=low) eliminó las muertes pero abarató la
  reparación: el corte dominante pasó a ser disyuntor D6 (síntoma idéntico
  tras reparar) — 6 de 8 fallos. Reparar necesita pensamiento; low lo
  completa pero no lo profundiza.
- **bonfix: 3, 4, 2 (media 3.0) → KILL del BoN k=3 EN ESTE RÉGIMEN** (media ≤
  baseline, coste ~2×). Mecanismo visto en la meta: a temperature 0.2 los 3
  candidatos son casi clones (checks_ok 9,9,9 / 7,7,7) — 0 de 16 tareas
  tuvieron un candidato aprobado en fase BoN. El KILL es del par
  (BoN, temp 0.2, reparación plana), no de la idea BoN: queda pendiente
  re-probarla con candidatos 2..k a temperatura alta cuando la reparación
  esté resuelta.

**Brazo C pre-registrado — ESCALADA de esfuerzo en reparación:** la primera
reparación de cada tarea va a effort=low; a partir de la ronda 2, si
checks_ok NO creció respecto de la ronda anterior, la reparación escala a
esfuerzo default (sin kwarg) con max_tokens 24000 y timeout 400 — presupuesto
que cubre la cola de espirales observada (22-53k chars ≈ 5-13k tokens) y deja
sitio a la respuesta. Config: candidatos=1, sin rondas-progreso, n=3.

| veredicto brazo C | condición |
|---|---|
| **PASA** | media > 3.33 (baseline post-fix) y mínimo ≥ 4 |
| **GRIS** | media > 3.33 con mínimo < 4 |
| **KILL** | media ≤ 3.33 |

Si C pasa, la config candidata de producción es "escalada" y el resto de la
noche (banco brutal) corre con ella.

**Brazo rondasfix ABORTADO en la réplica 1 (n=1, se descarta):** el lanzador
crea un proceso nuevo por réplica y las réplicas 2-3 habrían cargado el
código de escalada recién editado — condiciones mezcladas dentro del brazo.
Además su condición de disparo (checks_ok creciendo) casi no ocurre con
reparación plana: el experimento B se re-plantea SOBRE la escalada si C pasa
(la extensión de rondas solo tiene sentido cuando las reparaciones progresan).

## TERCERA ENMIENDA (2026-07-26 ~17:00, tras cerrar el brazo C, ANTES de correr el D)

- **escalada: 3, 3, 4 (media 3.33) → KILL** (empata al baseline post-fix; la
  reparación profunda tampoco levanta el número).
- La sonda de contratos (probe_contrato_effort.py) REFUTÓ la hipótesis del
  contrato débil: con effort=low salen 3/3 válidos e igual de ricos (8 pasos,
  cubren las reglas); con default salen 2/3 MALFORMADOS. O sea: pre-fix, sin
  validación, los contratos malformados reventaban el juez cada ronda, el
  lazo cortaba por opinión en ronda 1 y entregaba la PRIMERA GENERACIÓN
  intacta — cuyo pass@1 (~75%) coincide con la media pre-fix (4.5/6 = 75%).
  Post-fix el juez interno corre de verdad, bloquea esos cortes, y el lazo
  repara... y las series dicen que reparar RESTA (~3.3/6 = 55%).

**Brazo D pre-registrado — PRIMERA GENERACIÓN (max_rondas=1):** el lazo
genera, el juez juzga una vez, no se repara nada (config: candidatos=1,
`--max-rondas 1`), n=3. Falsa o confirma: "el lazo de reparación actual
resta valor frente a entregar la primera generación".

| lectura brazo D | condición |
|---|---|
| **el lazo RESTA** | media D > 3.33 (el baseline con reparación) |
| **el lazo aporta** | media D < 3.33 |
| **empate** | media D ≈ 3.33 (±0.33) — la reparación es ruido neto |

Si D > baseline: la conclusión de la noche es que el cuello real es la
CALIDAD DEL CONTRATO INTERNO como señal de reparación (aprueba lo que el
externo reprueba y sus contraejemplos desvían), y el siguiente trabajo es
mejorar el contrato (más aserciones, CodeRM-style), no la mecánica de rondas.

## CUARTA ENMIENDA (2026-07-26 ~17:20, tras cerrar el brazo D, ANTES de implementar el E)

- **primgen (primera generación, max_rondas=1): 5, 2, 5 (media 4.0, ~65
  s/tarea)** > baseline con reparación (3.33). La lectura pre-registrada se
  cumple: **el lazo de reparación actual resta valor**.
- Tasa de "sin verificar" en producción (unidad 4, primera medición): **9 de
  79 construcciones = 11.4%** (8 de 9 por fallo del pensador/backend, 1 con
  contrato pero sin veredicto de harness).

**Brazo E pre-registrado — ENTREGA BEST-OF-SO-FAR:** el lazo conserva la
versión con MÁS checks_ok del juez entre todas las rondas y entrega ESA, no
la última. La reparación deja de poder empeorar la entrega (en términos del
juez interno); si nunca mejora, se entrega la primera generación juzgada.
Config: candidatos=1, max_rondas=3, n=3.

| veredicto brazo E | condición |
|---|---|
| **PASA** | media ≥ 4.5 y mínimo ≥ 4 (recupera el nivel pre-fix con juez activo) |
| **GRIS** | media > 4.0 (supera a primgen: la reparación vuelve a aportar) |
| **KILL** | media ≤ 4.0 — la política de producción pasa a max_rondas=1 hasta mejorar el contrato interno |

## QUINTA ENMIENDA (2026-07-26 ~18:40 — primgen a n=6 REVIERTE el veredicto del brazo D)

Serie primgen completa (n=6): **5, 2, 5, 2, 3, 2 — media 3.17, mínimo 2**.
El 4.0 de n=3 era suerte: con n=6 la primera generación queda ≤ baseline con
reparación (3.33) y MUY por debajo de la serie pre-fix (4.5, n=6). La regla
[[gate-e2e-flaky]] otra vez: ningún veredicto con n=3 en este banco.

**Lectura final con las únicas dos series robustas (n=6):**

| config | serie | media |
|---|---|---|
| pre-fix (reparación a esfuerzo default) | 3,4,5,5,4,6 | **4.5** |
| primgen (sin reparar) | 5,2,5,2,3,2 | **3.17** |

**Reparar APORTA (+1.33 tareas) cuando va a esfuerzo default.** Lo que restó
esta noche fue la reparación BARATA (effort=low) que introduje con el fix de
las espirales: completa siempre pero arregla poco (D6 por todas partes). Los
brazos n=3 (baseline 3.33 / BoN 3.0 / escalada 3.33 / bestsofar 2.33) son
todos del régimen barato y ninguno es concluyente por sí solo, pero apilan en
la misma dirección.

**Política final de la noche (restauración + fixes buenos):**
- MAX_RONDAS_DEFECTO vuelve a 3 (revierte la 4ta enmienda, que se decidió
  con el n=3 engañoso).
- reparar_web vuelve a esfuerzo DEFAULT (12000 tokens) y conserva timeout
  400 + UN reintento (estrictamente más completions que pre-fix, misma
  calidad). La escalada `profundo` se retira (su brazo no PASÓ).
- El contrato conserva effort=low (3/3 válidos e igual de ricos contra 2/3
  malformados del default — probe_contrato_effort.py) y la validación de
  pasos.
- Verificación de cierre: n=3 de la config restaurada (esperable ~4+; el
  n=6 queda para otra noche).

## CIERRE (2026-07-26 ~21:15 — restaurada a n=6 y la lectura final)

restaurada (la receta pre-fix + fixes buenos), n=6: **2, 5, 3, 2, 3, 5 —
media 3.33**. NO reproduce el 4.5 pre-fix. Las tres series n=6 del banco:

| serie (n=6) | valores | media |
|---|---|---|
| config final pre-fix (noche 25/26) | 3,4,5,5,4,6 | 4.5 |
| primgen (sin reparar, esta noche) | 5,2,5,2,3,2 | 3.17 |
| restaurada (esta noche) | 2,5,3,2,3,5 | 3.33 |

**Lectura final, la que queda:** con sd≈1.3 por réplica, ni siquiera las
medias de n=6 separan (Δ4.5−3.33 ≈ 1.5σ), y las dos series de ESTA noche
(3.17 vs 3.33) son indistinguibles. Ninguna intervención de la noche (BoN,
escalada, primgen, best-of-so-far, effort de reparación, restauración)
demostró efecto sobre el pass/6 con la potencia disponible. El 4.5 de
anoche pudo ser una tirada alta, deriva entre noches (estado del server,
caché de prompts), o real — este diseño no lo distingue. Lo que SÍ queda
en pie: el gate original (toda serie ≥ 3 contra el baseline 2/6), y los
hallazgos MECÁNICOS reproducidos (espiral de razonamiento y su fix por
template, "Reasoning: low" en system inerte 3/3, contratos malformados 2/3
con esfuerzo default vs 0/3 con low, clones a temp 0.2 en BoN 0/16, tasa
sin-verificar 11.4%).

**Regla de diseño para el próximo A/B de este banco (la lección cara):**
n≥6 POR BRAZO e INTERCALADO a nivel tarea dentro de la misma corrida
(A,B,A,B...), nunca brazos secuenciales en bloques — el drift entre bloques
es del tamaño del efecto buscado. Y el banco de 6 tareas fáciles se queda
corto: con techo 6 y ruido ±1.5, un efecto de +1 tarea necesita ~n=12; el
banco brutal (efectos esperables mayores) es mejor instrumento.

## SEXTA ENMIENDA (2026-07-27 ~22:15 — el envoltorio queda acusado; brazo F pre-registrado)

Confound de deriva CERRADO (b2_confound_envoltorio.py): muestras DIRECTAS de
esta misma noche, mismo server, mismo juez → **9/12 = 75%**, clavado en el
pass@1 histórico. No hay deriva del modelo. La brecha contra el 17% del
sistema (2/12) es del CAMINO DEL SISTEMA: **el envoltorio del lazo destruye
~58 puntos de capacidad ya pagada en tareas composicionales.**

**Brazo F — IDEA PELADA en el lazo:** el sospechoso principal es el adorno
de la idea (`idea_build += ". TARGET LOOK, match it: {brief}"`): en tareas
composicionales con selectores OBLIGATORIOS, el brief estético compite con
los requisitos duros. Se agrega `COGNIA_IDEA_PELADA=1` (el lazo construye
con la idea tal cual; el brief sigue existiendo para árbitro/sprites) y se
corre el banco brutal ×3 con la config restaurada.

| lectura brazo F | condición |
|---|---|
| **el adorno es el culpable** | pelada ≥ 6/12 (recupera la mayor parte del gap) |
| **culpable parcial** | pelada 4-5/12 — hay más ladrones en el camino |
| **el adorno queda absuelto** | pelada ≤ 3/12 — buscar en el resto (componentes REQUIRED, parser, temperatura) |

## SÉPTIMA ENMIENDA (2026-07-27 ~22:30 — el adorno queda absuelto; triangulación)

Brazo F (idea pelada, lazo completo): **0/4, 0/4** en las dos primeras
réplicas (la 3ª corre) — quitar el TARGET LOOK no recupera nada. El adorno
queda absuelto. Quedan dos sospechosos entre el 75% directo y el ~8-17% del
sistema: (a) el envoltorio de `generate_program` (checklist de componentes
REQUIRED, system prompt), y (b) el LAZO mismo (reparaciones que degradan la
página en tareas composicionales, entregando la última versión).

**Brazo G — TRIANGULA (pelada + max_rondas=1):** primera generación por el
camino del sistema, sin adorno y sin reparación. n=3 (12 tareas).

| lectura brazo G | condición |
|---|---|
| **el ladrón es el LAZO de reparación** | triangula ≥ 7/12 (~recupera el directo) |
| **reparto** | 4-6/12 — ambos roban |
| **el ladrón es generate_program** | ≤ 3/12 — el camino de generación del sistema pierde contra _call_llm directo |

## OCTAVA ENMIENDA (2026-07-27 ~23:15 — el ladrón identificado con mecanismo; brazo H)

Brazo G (triangula: pelada + max_rondas=1): **0/4, 1/4, 1/4 = 2/12** — igual
que el sistema completo. El lazo de reparación queda ABSUELTO en el brutal;
el ladrón es el camino de generación de `generate_program`. Mecanismo
encontrado leyendo el prompt: `_build_prompt_web` inyecta reglas de
DASHBOARD — "All data simulated (Math.random, setInterval)", "must ANIMATE
on its own, no user click needed", "at least 3 sections (chart + table)" —
que CONTRADICEN los contratos interactivos. Los productos fallidos se
titulan "Contador Automático con Gráfico y Tabla". La sonda directa (75%)
manda la idea sin esas reglas.

**Fix aplicado (con tests): `_idea_interactiva()`** — ideas con
OBLIGATORIO/click/botón/tecla/juego reciben reglas que respetan el contrato
(comportamiento exacto, sin animación autónoma, sin datos aleatorios,
estado inicial literal, selectores reproducidos tal cual); los dashboards
conservan sus reglas de siempre.

**Brazo H — brutal con el prompt arreglado** (config restaurada, sin flags),
n=3:

| lectura brazo H | condición |
|---|---|
| **ladrón confirmado y cobrado** | ≥ 6/12 (recupera la mayor parte de los 58 pts) |
| **cobro parcial** | 3-5/12 |
| **el fix no cobra** | ≤ 2/12 — el mecanismo era otro (volver a triangular con el prompt real registrado) |

## NOVENA ENMIENDA (2026-07-27 ~05:50, sesión diurna — sondas del prompt para
## los ~25 pts restantes; escrita ANTES de generar nada)

Estado heredado: crudo 75% (9/12), sistema-con-fix 50% (12/24, serie
2,1,1,2,3,3). Análisis ESTÁTICO de esta mañana (cero GPU) sobre el camino de
generación del sistema (`generate_program(forced_idea=...)`), tres sospechosos
concretos además del troceo ya nombrado:

1. **Troceo REQUIRED** (`_componentes_de_idea` parte por comas): MUTILA las
   enumeraciones que el contrato verifica — "data-precio 100" (pierde 50,25),
   "data-stock 2" (pierde 3,1), "con data-col todo" (pierde doing,done),
   "data-ref A1" (pierde A2..C3). La checklist le miente al modelo.
2. **extra_hint aleatorio de COMPLEXITY_HINTS**: hints de PYTHON ("Keep it
   simple, under 60 lines", "ASCII art", "__main__") inyectados como regla
   en ideas web composicionales.
3. **PROVEN PATTERNS**: a carrito_stock le inyecta el patrón `grafico_svg`
   (dashboard por la puerta de atrás que `_idea_interactiva` no cierra);
   kanban/buscaminas reciben `tabla_estados`.

Además queda vivo (d) el formato Title/Description + `_parse_response`, y
(e) la reparación en composicionales (absuelta PRE-fix por triangulación,
no re-aislada POST-fix).

**Sonda I (REVISADA tras la revisión de 2 agentes con contexto fresco,
2026-07-27 ~06:15, ANTES de generar nada; el diseño original de ~05:50 tenía
3 fallas mayores: fallback silencioso de `_call_llm` a otros backends, hint
re-sorteado por brazo sin semilla, y un brazo `sinhintpat` que cambiaba tres
cosas a la vez sin aislar el envoltorio base) — ESCALERA ANIDADA de 4 brazos
DIRECTOS (sin lazo), intercalados a nivel tarea con orden rotado por celda,
banco brutal, n=3 por brazo (12 gen/brazo), temp 0.2,
`_preguntar_constructor` contra :8080 SIN fallback:**

| brazo | prompt | el par adyacente aísla |
|---|---|---|
| `crudo` | la idea pelada (control de deriva CONCURRENTE) | — |
| `base` | `_build_prompt_web` sin REQUIRED, sin extra_hint, sin patrones (líneas huérfanas limpiadas) | reglas fijas + formato |
| `basereq` | `base` + bloque REQUIRED troceado | el troceo |
| `full` | `basereq` + hint de COMPLEXITY_HINTS (semilla determinista por celda) + PROVEN PATTERNS | el PAR hint+patrones |

Declarado: `full` reproduce el prompt del sistema DE HOY (store de patrones
vivo); hint+patrones van JUNTOS — si ese peldaño roba, el desempate exige
otra sonda antes de tocar código. El HTML sale de la MISMA cadena para todos
los brazos (`_parse_response` → fence de rescate); `parse_estricto_ok` por
celda acota solo el coste de PARSEO del formato (N/A en `crudo`), no su
coste de calidad. El held-out corre sobre aprobados (mide FP, no FN).

**Lecturas pre-registradas:**

- **Primaria (apareada):** pares discordantes por celda (tarea, rep) entre
  brazos ADYACENTES de la escalera — estilo McNemar; con 12 celdas
  apareadas es más legible que la resta de totales.
- Secundaria: aprobados/12 por brazo. TODAS las restas usan el `crudo`
  concurrente de esta corrida; el 9/12 histórico es solo sanidad.
- Sanidad automática (en el script): si el `crudo` ya no puede superar
  5/12, ABORTAR (exit 3) y sondar finish_reason/usage antes de leer nada.
- El peldaño cuya remoción concentre los discordantes (≥3 celdas netas) es
  el sospechoso dominante; reparto = culpa repartida (fix a los dos).
- Si `full` ≈ `crudo` en la apareada: el prompt queda **no acusado A ESTA
  POTENCIA** (no "absuelto": con n=12 hay ~25% de falsa absolución aun con
  gap real de 3) → siguiente sonda: el LAZO (sistema completo vs
  max_rondas=1, intercalados, con un brazo que pueda re-acusar al prompt).
  Refuerzo independiente ya medido (cruce en disco, fixprompt n=24): el
  sello interno del lazo está al nivel del AZAR contra el examen del banco
  (FP 3/6, FN 9/18) — el lazo repara contra una señal casi no correlacionada.
- Todo veredicto de esta sonda con n=12/brazo es DIRECCIONAL: el fix que
  salga se confirma con la serie del sistema completo (b2_banco_brutal,
  n≥6, contra la referencia 12/24 post-fix — misma vara que anoche).

**Qué NO se toca hasta ver la sonda:** ningún cambio a generator.py ni al
lazo. El fix se implementa DESPUÉS de la atribución, con test de regresión.

## RESULTADO de la Sonda I (2026-07-27 ~06:50) y DÉCIMA ENMIENDA (escrita
## ANTES de implementar el fix y de correr el A/B de confirmación)

Sonda I completa (48/48 celdas, sin deriva — parada automática no disparó):

| brazo | aprobados | held-out ok | parse estricto | discordantes apareados |
|---|---|---|---|---|
| crudo | **11/12** | 11/12 | N/A | — |
| base | 10/12 | 9/12 | 12/12 | crudo gana 2 (hoja r1,r2) / base gana 1 |
| basereq | 8/12 | 7/12 | 12/12 | base gana 4 / basereq gana 2 |
| full | 8/12 | 8/12 | 11/12 | empate 2/2 con basereq |

**Lecturas (direccionales, n=12/brazo):**

1. El crudo CONCURRENTE dio 92% (histórico 75%): la deriva entre noches es
   ~2 celdas — toda comparación entre noches queda invalidada como vara.
2. **El troceo REQUIRED es el peldaño más caro (−2 netos, 4 vs 2)**. No
   llega al umbral ≥3 de "dominante": culpa repartida con las reglas base.
3. **Reglas base: −1 neto con MECANISMO cazado**: "Format numbers for
   humans (toLocaleString)" produce `8,00` donde el contrato exige `8`
   (hoja_calculo r1 y r2, falla crítica idéntica). Misma clase que las
   reglas dashboard de la octava enmienda: regla de calidad para
   dashboards = veneno para contratos exactos.
4. hint aleatorio + patrones: 0 neto — SIN CARGO (no se tocan).
5. El formato Title/Description NO roba por parseo (parse estricto 35/36).
6. full directo 8/12 (67%) > sistema con lazo 12/24 (50%, anoche): el
   resto del gap apunta al LAZO, coherente con el hallazgo independiente
   de hoy (sello interno al azar: FP 32-50%, FN 50%, n=196).

**Fix pre-registrado (gated por env `COGNIA_PROMPT_FIX2` para poder
intercalar):** (a) `_componentes_de_idea` trocea por FRASES, no por comas
(las enumeraciones quedan enteras); (b) en ideas interactivas la regla de
formato de números se invierte: "muestra los valores EXACTAMENTE como la
idea/estado lo dictan, sin separadores ni decimales no pedidos". No se toca
nada más (hint/patrones sin cargo; formato sin cargo).

**A/B de confirmación — sistema COMPLETO (lazo real), banco brutal,
brazos INTERCALADOS a nivel tarea en la misma corrida (fix2 OFF / fix2 ON,
orden rotado por celda), réplicas hasta agotar la ventana (objetivo n=6
por brazo = 48 corridas de lazo; si el aterrizaje corta antes, se reporta
el n alcanzado como PARCIAL y la corrida queda reanudable):**

| veredicto | condición (sobre los pares apareados por celda) |
|---|---|
| **el fix cobra** | ON gana ≥3 celdas netas sobre OFF en el apareado |
| **cobro dudoso** | ON gana 1-2 netas — más réplicas antes de adoptar |
| **no cobra** | neto ≤ 0 — revertir el gate y volver a la sonda |

La referencia 12/24 de anoche NO entra en el veredicto (deriva medida);
solo el OFF concurrente. El A/B hereda el contrato interno CLÁSICO (el
amplio está en su propio prereg y NO se mezcla en esta serie).

## RESULTADO del A/B fix2 (2026-07-27 ~09:55 — cerrado COMPLETO, 6 réplicas)

**ON 12/24 (50%) vs OFF 17/24 (71%); apareado: ON gana 5, OFF gana 10,
NETO ON = −5 → veredicto pre-registrado: EL FIX NO COBRA.** El gate queda
como está (fix2 env-gated, OFF por defecto — producción intacta).

Dos lecturas que valen más que el fix:

1. **La atribución de la sonda directa NO transfirió al lazo.** En directo,
   quitar REQUIRED/formato recuperaba celdas; dentro del lazo, el troceo
   por frases + números exactos EMPEORA (carrito pierde 5 de 6 pares con
   ON). Mecanismo candidato VERIFICADO a nivel prompt (~10:00, sin GPU,
   con idea_build real): con fix2 ON el troceo por frases absorbe el
   adorno `. TARGET LOOK, match it: {brief}` (el `..` no se parte) y el
   brief estético ENTERO entra como "REQUIRED component 9" — la checklist
   convierte la estética en requisito duro; con OFF el troceo por comas
   lo fragmentaba y solo quedaba un residuo de dos palabras. La sonda
   directa corría SIN adorno (idea pelada): por eso su atribución no
   transfirió al lazo. Si el fix se re-intenta, tiene que trocear la idea
   ORIGINAL (no idea_build con el adorno) — y re-pasar el A/B intercalado
   desde cero.
2. **La deriva entre noches es del SISTEMA entero, no solo del crudo: OFF
   (código idéntico a anoche) pasó de 12/24 (50%) a 17/24 (71%).** Una
   serie de un solo brazo esta mañana habría dicho "el fix no cambia nada"
   (12/24 vs 12/24 histórico) cuando el concurrente dice −5. El intercalado
   es lo único que salvó el veredicto. Referencias históricas: solo sanidad.

## UNDÉCIMA ENMIENDA (2026-07-27 ~20:05, sesión nocturna — fix2 v3: trocear
## la idea ORIGINAL; escrita ANTES de implementar y de correr)

El mecanismo del fracaso del A/B anterior quedó verificado sin GPU (décima
enmienda, lectura 1): el troceo por frases absorbía el adorno `. TARGET
LOOK, match it: {brief}` entero como "REQUIRED component" — la checklist
convertía la estética en requisito duro. La sonda directa corría con la
idea pelada y no podía verlo.

**Fix v3 (mismo gate `COGNIA_PROMPT_FIX2`, sin flag nuevo):** el troceo por
frases CORTA el adorno TARGET LOOK antes de partir — trocea la idea
ORIGINAL, como manda la décima enmienda. Sin flag, nada cambia (el troceo
por comas de producción fragmentaba el brief y solo entraba un residuo).
Test de regresión: con flag y una idea adornada, ningún componente contiene
texto del brief.

**A/B de confirmación DESDE CERO** (la corrida de la mañana no vale: su ON
era el v2 defectuoso): mismo diseño de la décima enmienda — sistema
COMPLETO, banco brutal, brazos OFF/ON intercalados a nivel tarea con orden
rotado por celda, salida en directorio propio (la corrida previa no se
pisa). Objetivo n=6/brazo; las réplicas corren hasta el aterrizaje
(~21:50): si corta antes, se reporta el n alcanzado como PARCIAL
direccional y la corrida queda reanudable con --reanudar.

| veredicto (pares apareados por celda) | condición |
|---|---|
| el fix cobra | ON gana ≥3 celdas netas |
| cobro dudoso | ON gana 1-2 netas — más réplicas antes de adoptar |
| no cobra | neto ≤ 0 — revertir el gate y volver a la sonda |

Declarado: ambos brazos heredan por igual el descarte de contratos vacuos
(commit 8006037, entrado hoy ANTES de esta enmienda) y el contrato interno
CLÁSICO. El OFF concurrente es la única vara; el 17/24 de la mañana es solo
sanidad ([[gate-e2e-flaky]]: deriva sistémica medida de ~21 pts en 12 h).

### RESULTADO del A/B v3 (2026-07-27 ~20:05, COMPLETO, 24 pares)

**ON 13/24 vs OFF 17/24; apareado: ON gana 4 (buscaminas r6, carrito r2,
hoja r3, kanban r5), OFF gana 8 (buscaminas r1,r2,r5; carrito r4,r6; hoja
r5; kanban r1,r3) — NETO ON = −4 → veredicto pre-registrado: NO COBRA.**
El gate queda OFF (producción intacta); fix2 v3 permanece en el código,
env-gated, para futuras sondas.

Lectura honesta: es la SEGUNDA vez que la atribución de la sonda directa
(troceo por comas cuesta −2 en directo) no transfiere al lazo — ahora
incluso con el adorno TARGET LOOK cortado (el mecanismo que explicaba el
fracaso del v2). Con OFF 17/24 = 71% y sd binomial ~9%, el −4 neto sobre 12
discordantes es compatible tanto con daño real del troceo por frases dentro
del lazo como con una interacción prompt×lazo que la sonda directa no
captura. La vía "arreglar el troceo" queda AGOTADA por esta noche (dos A/B
completos n=6 en contra); el REQUIRED troceado solo vuelve a tocarse si una
sonda futura sondea el prompt DEL LAZO (con adorno, con checklist, con
system prompt) y no el directo. Los ~25 pts del gap sistema-vs-crudo siguen
sin dueño confirmado a nivel lazo.

## Qué NO decide esto

- A y B se miden POR SEPARADO. Si ambos dan señal, una corrida combinada es
  exploratoria (se reporta como tal, no como confirmación).
- n=3 por brazo es poco contra la varianza conocida del gate (~50% flaky);
  un GRIS aquí significa "más réplicas", no "adoptar".
- La tasa de "sin verificar" (contador nuevo de telemetría) se REPORTA sobre
  las corridas de esta noche; no tiene umbral pre-registrado — es la primera
  medición.

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

## Qué NO decide esto

- A y B se miden POR SEPARADO. Si ambos dan señal, una corrida combinada es
  exploratoria (se reporta como tal, no como confirmación).
- n=3 por brazo es poco contra la varianza conocida del gate (~50% flaky);
  un GRIS aquí significa "más réplicas", no "adoptar".
- La tasa de "sin verificar" (contador nuevo de telemetría) se REPORTA sobre
  las corridas de esta noche; no tiene umbral pre-registrado — es la primera
  medición.

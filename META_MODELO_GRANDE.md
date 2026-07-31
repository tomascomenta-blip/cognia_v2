# META — igualar a un modelo grande desde 16 GB

Escrito el 2026-07-25 con los datos de las Fases A/B/C de esta sesión. Todo lo
que hay aquí es falsable: si el número no sale, la vía se mata.

---

## Por qué la vía anterior estaba agotada, con el dato

El plan hasta hoy era **ruteo entre modelos**: muchos expertos pequeños y un
router que elige bien. Medido con juez ejecutable sobre 6 tareas:

| | |
|---|---|
| Techo del pool con **ruteo perfecto** (oráculo sobre 4 modelos) | **6/6** |
| Mejor modelo **solo** (gpt-oss-20b) | **6/6** |
| **Ganancia del ruteo perfecto** | **+0** |

Un oráculo que *siempre* acierta al elegir modelo no consigue ni una tarea más
que correr solo el mejor. **La capacidad no se suma: se rutea, y el techo es
`max()`.** Ese es el resultado más sólido de la sesión y no se discute.

### CORRECCIÓN al párrafo de arriba (2026-07-25, tras revisar la literatura)

**Ese `+0` está medido sobre un set SATURADO** (el mejor modelo hace 6/6). Un
oráculo de ruteo sobre un set que el mejor ya aprueba **no puede mostrar
ganancia por construcción**. No es evidencia de que no haya margen: es evidencia
de que ese banco no podía medirlo.

Lo que sí está respaldado por medición externa es la *dirección*: el
**Co-Failure Ceiling** ([arXiv:2606.27288](https://arxiv.org/abs/2606.27288), 67
modelos) da un techo formal `precisión ≤ 1 − β`, con β = 0.079 en código
evaluado por ejecución, y concluye que *"combinar modelos rara vez supera al
mejor individual sin una señal de ruteo a nivel de query"*. Y **Self-MoA**
([arXiv:2502.00674](https://arxiv.org/abs/2502.00674)) muestra que agregar 6
propuestas del **mejor modelo solo** supera a mezclar modelos distintos
(AlpacaEval 65.7 vs 59.1).

**El `+0` hay que volver a medirlo sobre el banco duro.** Hasta entonces es una
observación, no un resultado.

## El giro que sí sobrevive: no rutear, AGRUPAR

La literatura separa dos cosas que yo había juntado:

- **Elegir** entre modelos (¿cuál uso para esta tarea?) → +0, y encima requiere
  saber cuál antes de generar.
- **Agrupar** candidatos de varios modelos y **filtrar por ejecución** → sí gana.
  El *Barrel of Monkeys* de CodeMonkeys
  ([arXiv:2501.14723](https://arxiv.org/abs/2501.14723)) juntó sus candidatos con
  los del top-4 del leaderboard y su selector ejecutable dio **66.2 % contra
  62.8 % del mejor miembro aislado**.

> **La flota vale como fuente de DIVERSIDAD DE ERRORES (ρ bajo), no como menú a
> elegir.** Es un uso distinto del mismo hardware, y es el que la evidencia
> respalda.

## Por qué eso NO cierra la puerta

Ese oráculo era sobre **modelos**. Y era un oráculo *hipotético*: en producción
no se sabe cuál elegir.

Desde hoy existe `cognia/program_creator/juez_ejecutable.py`: abre el producto en
Chromium real, interactúa y comprueba un contrato pre-escrito. Eso habilita un
oráculo distinto — sobre **muestras del mismo modelo** — y con una propiedad que
el otro no tenía: **es realizable**. No hay que adivinar cuál muestra sirve; se
ejecuta y se comprueba.

> Elegir entre modelos: +0, y encima hipotético.
> Elegir entre muestras verificadas: por medir, y **cobrable**.

La apuesta central es que **compute × verificador ≈ capacidad**, y que eso es
lo que sustituye al conocimiento paramétrico que no cabe en 16 GB.

---

## El banco: sin cabecera no hay progreso medible

El set de 6 tareas está **saturado** (gpt-oss-20b: 6/6). No sirve para medir
avance hacia un modelo grande.

`scripts/b1_tareas_duras.json` — 8 tareas nuevas. Lo que las hace duras no es la
longitud sino la **composición**: 3-5 requisitos que *interactúan*, más lógica
algorítmica real. Un modelo puede acertar cada requisito por separado y fallar el
contrato.

`undo_redo` (la rama rehacible se invalida) · `descuento_tramos` (descuento
marginal, bordes de tramo) · `form_cruzado` (tres reglas simultáneas) ·
`tabla_compuesta` (filtro+orden+paginación combinados) · `precedencia`
(2+3*4=14, no 20) · `tres_en_raya` (ganador y bloqueo posterior) ·
`temporizador` (pausa, reanudación, doble-start sin acelerar) · `serpiente`
(crecimiento y no-inversión 180°).

---

## LA META

### El horizonte, MEDIDO (2026-07-25)

Faltaba el número que importa. Un contexto **fresco** recibió solo los 8
enunciados —sin ver los contratos— y escribió 8 páginas de una sola pasada:

| referencia | banco duro |
|---|---|
| **FRONTIER, single-shot** | **8/8** |
| gpt-oss-20b, mayoría de n=3 | **8/8** |
| gpt-oss-20b, **pass@1** | **≈83 %** (20 de 24 muestras) |

**En este banco, el 20B con 3 muestras iguala al frontier de una pasada.** Es la
primera evidencia propia de que compute sustituye a parámetros aquí.

*Caveat declarado:* la referencia frontier la produjo un subagente de la misma
familia de modelos que diseñó las tareas. Contexto fresco y sin acceso a los
contratos, pero una referencia de otro proveedor sería más limpia.

**Objetivo:** que la máquina de 16 GB entregue **8/8** en el banco duro, con
producto **entregable** (no oráculo: el sistema tiene que poder elegir la
muestra buena, y con el juez puede).

**Dónde está la cabecera real:** ni el frontier ni el 20B-mayoría discriminan ya
(8/8 los dos). El hueco medible son **los 17 puntos entre el pass@1 del 20B
(83 %) y el 100 %**. Ahí es donde best-of-N y reparación con contraejemplo
tienen que demostrar lo suyo.

**Y la comparación honesta es a ISO-CÓMPUTO, no a iso-muestra.** Un 20B genera
3-5× más rápido que un frontier: por segundo de pared compra más intentos, y
attempts × verificador = capacidad. Esa es la asimetría que se explota.

**Marcador de parámetros:** Laguna XS 2.1 (33B-A3B, 20 GB, el mayor que cabe).
**Sus números previos quedan ANULADOS**: se midieron con `num_ctx` 4096, y es un
modelo de razonamiento que agotaba el contexto pensando
(`finish_reason='length'` con **0 caracteres** y 3.881 tokens). Se re-mide con
`laguna-16k`.

**Criterio de éxito de la vía (pre-registrado):**

| | |
|---|---|
| PASA | pass@8 verificado ≥ **+25 puntos** sobre pass@1, y ≥ el single-shot de Laguna XS |
| GRIS | ganancia entre +10 y +25 → sirve, pero no sustituye parámetros; se combina |
| KILL | ganancia < +10, **o** ≥3 de 8 tareas con 0 aciertos en 8 muestras |

El criterio de KILL es el importante: **si una tarea no sale NUNCA en 8
muestras, el muestreo no la compra.** Eso sí sería un techo de capacidad real, y
sería el único argumento honesto para necesitar más conocimiento en los pesos.

---

## Plan por pasos pequeños, cada uno con su número

1. **Línea base dura.** El banco de 8 con los modelos del pool, n=3. Sin esto no
   hay contra qué comparar. *Sale: pass@1 por modelo.*
2. **Curva pass@k.** `scripts/bon_verificado.py` con n=8 sobre el mejor modelo.
   *Sale: dónde satura y qué tareas son imposibles.*
3. **Marcador Laguna XS.** El mismo banco, single-shot. *Sale: cuánto compra
   tener 33B en los pesos.*
4. **Refinamiento guiado por traza.** El juez no solo dice fallido: dice **qué
   check falló y con qué valores**. Devolverle esa traza al modelo es feedback
   externo verificable, no auto-crítica (Huang et al. ICLR 2024 muestra que
   auto-corregirse *sin* verificador externo empeora; con él, es otra cosa).
   *Sale: pass@1 tras k rondas de reparación guiada vs best-of-N con el mismo
   compute — cuál rinde más por segundo.*
5. **Lo que salga de la investigación de métodos**, priorizado por
   ganancia/esfuerzo.

## Lo que NO se va a hacer, y por qué

- **Perseguir Laguna S 2.1 (118B).** Q4 = ~75 GB contra 47 GB de VRAM+RAM. No
  entra ni sumando todo. Ya está descartado con números.
- **Entrenar un modelo base.** Fuera de alcance en una 5060 Ti.
- **Otro gate decidido por apariencia.** La adopción de UIGEN-X-8B se decidió
  con el árbitro VLM sobre capturas; con juez ejecutable saca 3/6, la mitad que
  gpt-oss-20b. Todo gate visual queda invalidado hasta rehacerse.

## Resultados

_(se rellena a medida que salen; nada de esto se toca retroactivamente)_

| Paso | Estado | Número |
|---|---|---|
| 1. Línea base dura | HECHO (banco brutal, n=6) | gpt-oss pass@1 75%, Laguna 50% |
| 2. Curva pass@k | parcial | pass@6 gpt-oss = 100% (4/4 tareas) |
| 3. Marcador Laguna XS | HECHO | 50% pass@1; peor que el 20B |
| 4. Refinamiento guiado | pendiente | — |
| 5. Re-medir el oráculo de ruteo en banco NO saturado | HECHO 2026-07-26 (sobre los n=6 del brutal, 2 modelos) | +0 a nivel tarea (pensar 4/4 solo). A nivel muestra parecía +4.2%, pero corregido por los FP del held-out la ventaja de Laguna en kanban era hackeo: **+0 exacto también por muestra**. Caveats: solo 2 modelos, y pensar satura la mayoría — sigue sin ser el banco ideal para rutear |
| **FP del contrato (held-out, 48 productos)** | **HECHO 2026-07-25** | **gpt-oss 0% (0/18) — sus números se sostienen; Laguna 25% (3/12) — techos. PREREG_FP_CONTRATO_20260725.md** |
| Confound "no devolvió HTML" (≈14%) | HECHO 2026-07-25 | era num_ctx 4096: control positivo reproduce (2/3 length), config actual 0 muertes; scripts/b1_confound_repro.py |
| **A/B nocturno 26/27: BoN, escalada, primera generación, best-of-so-far (PREREG_BON_RONDAS_20260726.md, 5 enmiendas)** | **HECHO 2026-07-26/27** | **El resultado que manda (únicas series n=6 contra n=6): reparación a esfuerzo default 4.5/6 contra primera-generación-sin-reparar 3.17/6 (5,2,5,2,3,2) — REPARAR APORTA +1.33 tareas cuando la reparación PIENSA.** Todas las variantes con reparación BARATA (effort=low) quedaron ~1 tarea por debajo (n=3 c/u): baseline 3.33; BoN k=3 3.0 (KILL: a temp 0.2 los candidatos son clones — checks_ok 9,9,9 — y 0/16 tareas con candidato aprobado en fase BoN; coste 2.2×); escalada 3.33 (KILL); best-of-so-far 2.33 (KILL). Config final restaurada: rondas=3 + reparación a esfuerzo default + timeout 400 + un reintento + contrato a effort=low (3/3 válidos vs 2/3 malformados con default, misma riqueza) + validación de pasos. **Dos trampas de proceso que casi firman conclusiones falsas la misma noche:** primgen a n=3 daba 4.0 y a n=6 dio 3.17 (gate-e2e-flaky: ningún veredicto con n=3 aquí); y el "4.5 pre-fix era primera generación con juez saboteado" se cayó al medir el control. Sigue abierto y REAL: el contrato generado es más débil que el held-out (aprueba contadores que el examen externo reprueba) → mejorar el contrato interno (CodeRM, prioridad #3) sigue siendo el siguiente trabajo. Fixes con medición propia: espiral de razonamiento en reparar_web (chat_template_kwargs.reasoning_effort; la línea "Reasoning: low" del system NO hace nada, 3/3 sondas), validación de pasos, telemetría de sellos (**tasa "sin verificar": 9/79 = 11.4%**, 8/9 por fallo del pensador). **CIERRE con restaurada a n=6 (2,5,3,2,3,5 = 3.33): la restauración NO reproduce el 4.5, y con sd≈1.3/réplica NINGUNA config de la noche separa del ruido — el 4.5 pudo ser tirada alta o deriva entre noches. Queda en pie el gate original (toda serie ≥3 vs baseline 2/6) y los hallazgos mecánicos. Regla para el próximo A/B: n≥6 POR BRAZO, INTERCALADO a nivel tarea, y mejor sobre el banco brutal (efectos mayores) — este banco fácil con techo 6 y ruido ±1.5 necesita ~n=12 para ver +1 tarea.** Series en resultados_{basefix,bonfix,escalada,primgen,bestsofar,restaurada}*.json |
| **Banco BRUTAL por el SISTEMA REAL: primera medición, caza del ladrón y fix medido** | HECHO 2026-07-27 (enmiendas 6-8 del prereg) | **Sistema sin fix: 2/12 = 17%. Modelo CRUDO, misma noche, mismo juez: 9/12 = 75% (sin deriva — b2_confound_envoltorio.py). Cadena de aislamiento pre-registrada:** adorno TARGET LOOK absuelto (pelada 0/12), lazo de reparación absuelto (triangulación pelada+max_rondas=1: 2/12), **ladrón con mecanismo: las reglas DASHBOARD de _build_prompt_web ("must ANIMATE on its own", "data simulated with Math.random", "3 sections chart+table") contradicen los contratos interactivos** — los fallidos se titulaban "Contador Automático con Gráfico". **Fix `_idea_interactiva()` (reglas condicionales, commit 1a50bbc): 2,1,1,2,3,3 = 12/24 (50%) por contrato, 11/24 (46%) con held-out limpio — TRIPLICA el 17% y recupera ~33 de los 58 pts.** Quedan ~25 pts hasta el crudo: siguientes sospechosos, el resto del prompt (componentes REQUIRED troceados por comas, formato Title/Description) y la reparación en composicionales. Las fallas restantes siguen ajustadas (16-22 de ~20-28 checks). scripts/b2_banco_brutal.py |
| **Sesión diurna 27: sonda de ESCALERA + dos KILL honestos + deriva sistémica** | HECHO 2026-07-27 (enmiendas 9-10 + PREREG_CONTRATO_AMPLIO) | **(1) Atribución del prompt por escalera anidada (48 gen intercaladas, control concurrente, lectura apareada): crudo 11/12, base 10/12, basereq 8/12, full 8/12 — troceo REQUIRED −2 netas (mutila enumeraciones), regla de formato de números −1 ("8,00" vs "8"); hint/patrones y formato Title/Description SIN CARGO. (2) El fix (troceo por frases + números exactos, env-gated) NO COBRA en el lazo: A/B intercalado completo n=6/brazo, ON 12/24 vs OFF 17/24, neto −5 — el troceo por frases tragaba el brief TARGET LOOK entero como REQUIRED (la sonda directa corría sin adorno: sondear siempre el prompt QUE EL LAZO ARMA). (3) DERIVA SISTÉMICA cuantificada: crudo 75%→92% y sistema completo 50%→71% en 12 h con código idéntico — series de un solo brazo quedan invalidadas como veredicto; control concurrente SIEMPRE. (4) Contrato interno AL NIVEL DEL AZAR (FP 32-50%, FN ~50%, n=196 en disco) y el modo AMPLIO (CodeRM, 10-16 pasos) da GRIS: FP 0 pero aprueba 1/24 donde el banco aprueba 19/24 (FN 46→75%) — el cuello es la CORRECCIÓN de las aserciones, no la cantidad. scripts/b2_sonda_prompt.py, b2_ab_fix2.py, b2_ab_contrato.py** |
| **Sesión nocturna 27: la señal tocó techo y EL LAZO RESTA — max_rondas=1 adoptado** | HECHO 2026-07-27/28 (PREREG_SENAL_CONTRATO_20260727.md, 5 enmiendas) | **(1) Causa raíz del FN del contrato medida POR TIPO (48 contratos re-ejecutados sub-acción a sub-acción, tabla de PRIMERA CULPA): la aserción de texto sobre un input es ruido puro (55/55 FN — `escribir` no estaba documentada en la plantilla, 0/48 la usan) y 7/24 clásicos aprobaban por VACUIDAD (0 críticos) — el descarte de vacuos entró a producción. (2) El modo `corregido` (escribir+Tab, .value, criticidad) dio KILL DOS veces — incluso con la métrica limpia post-vacuidad (aciertos 10/24 vs 9/24, ambos FN 14/19): el contrato autogenerado desde idea+inventario tiene TECHO en composicionales; dirección viva: held-outs a mano + validar aserciones contra el enunciado. (3) fix2 v3 (troceo cortando el adorno) NO COBRA (neto −4; v2 −5): vía agotada. (4) LA GRANDE: A/B intercalado lazo (rondas=3) vs primera generación (rondas=1) — brutal: 16/24 vs 19/24, neto −3; fácil: 26/36 vs 33/36, neto −7, semaforo pierde 6/6 con reparación. Las rondas DEGRADAN páginas que nacieron mejor (4 de 5 discordantes con menos checks tras reparar). ADOPTADO max_rondas=1 (override COGNIA_MAX_RONDAS); el "reparar aporta +1.33" del 26/07 venía de bloques entre noches, el diseño inválido. Ambos brazos rinden 67-92% — la brecha sistema-vs-crudo del 17% no reaparece. scripts/b2_fn_por_tipo.py, b2_ab_lazo.py** |
| **GAP sistema-vs-crudo con control concurrente (primera vez)** | HECHO 2026-07-28 (SEXTA enmienda; PARCIAL 23/24 pares, 0 infra) | **sistema 15/23 (65%) vs crudo 19/23 (83%), neto crudo +4 con reparto en 4 tareas → el envoltorio AÚN roba, pero la brecha pasó de ~58 pts a ~17 con los fixes de la semana (dashboard condicional, descarte de vacuos, rondas=1). Siguiente sonda: el prompt DEL LAZO completo. Infra: el read-timeout por chunk no acota goteo lento de tokens (celda >45 min) — presupuesto por celda pendiente. scripts/b2_ab_gap.py** |
| **Sesión matinal 28: tercer clavo de la señal + el adorno era ruido** | HECHO 2026-07-28 (enmiendas 7ª-9ª del PREREG_SENAL) | **(1) Modo `validado` (filtro de aserciones contra el enunciado): KILL — el filtro cortó 30 pasos en 24/24 contratos y el FN no se movió (15/19 ambos; aciertos 9 vs 8/24): el pensador conserva sus propias invenciones. TRES KILL convergentes (corregido ×2, validado) fijan que EL TECHO ES DEL PENSADOR como QA: no más prompt-engineering del contrato autogenerado — held-outs A MANO por tarea o un modelo más fuerte para ese rol. (2) El adorno TARGET LOOK: tres series n=6 intercaladas (+3, 0, −5; total −2 en ~70 pares) → VÍA CERRADA, ruido — la 1ª sola habría adoptado "pelada" y la 3ª sola lo contrario; la lectura por total pre-fijada impidió ambas. scripts/b2_ab_fix2.py --var, modo validado en juez_ejecutable** |
| **Nocturna 28→29 — BoN de réplicas independientes + señal real ALCANZA EL NIVEL 8/8** | HECHO 2026-07-28 (PREREG_BON_HELDOUT, 24/24 ensayos, 0 infra, 96 muestras) | **Techo pass@4 = 24/24 (100%) sobre control 17/24 (71%), neto +7; el selector held-out (sin ver el contrato original) capturó TODO el margen (B=A, pérdida 0). Juez estricto = original ∧ held-out. La diversidad viene de REHACER el pipeline por muestra (no de temperatura: 0.9 pierde selectores; y no contradice el KILL del 26, que era de clones dentro del lazo). CONCLUSIÓN DE INVERSIÓN pre-registrada: el cuello del goal NO es el constructor — es FABRICAR SEÑAL para tareas nuevas. De paso: 4 FP más del contrato original (kanban 1, buscaminas 3). scripts/b2_bon_heldout.py** |
| **Nocturna 28→29 — QA-fuerte: DOBLE KILL, el CUARTO clavo del contrato autogenerado** | HECHO 2026-07-28/29 (PREREG_QA_FUERTE; control de deriva gpt-oss el mismo día: 8/24, FN 15/19) | **Nemotron-14B: KILL DE APTITUD (0/6 en piloto de futilidad pre-registrado — ahorró el bloque de 2 h; degenera en bucle a 0.2, sin críticos a 0.6). coder-14b: emisión perfecta (6/6 piloto, 5-8 s/contrato) pero aciertos 10/24, FN 14/19, FP 0/5 → KILL, indistinguible de gpt-oss. Dos familias, mismo perfil de FN ⇒ la enfermedad es el MARCO (contrato ciego desde idea+inventario), no el pensador: vía drop-in CERRADA, no probar un tercer modelo con este prompt. Señal para tareas nuevas = OTRO marco (consenso conductual entre muestras del BoN / ejecución en el bucle). Plomería que quedó: extractor con raw_decode + corte de <think>, knob COGNIA_TEMP_CONTRATO. scripts/b2_piloto_qa.py** |
| **Held-outs A MANO del banco FÁCIL, validados ×2 + fix de presupuesto en imaginar_vision** | HECHO 2026-07-28 | **Suite de 6 tareas (consecuencias lógicas, selectores obligatorios) contra 72 páginas guardadas: 0 errores, 0 desacuerdos — dos veces (antes y después de ascender 3 sondas a críticas y blindar clicks contra botones disabled). TODO el banco tiene ya juez estricto de señal real. Y mockup.imaginar_vision: max_tokens 400→2500 + reasoning_effort low (7º caso de presupuesto-de-pensamiento; la visión degradaba a idea cruda en toda corrida endurecida) — verificado e2e: degradado=False en 1.6 s. b1_contratos_heldout_facil.json, b1_validar_heldout_facil.py** |
| **Nocturna 28→29 — consenso cruzado (1ª variante del marco nuevo): KILL en el umbral** | HECHO 2026-07-29 (PREREG_CONSENSO; 255/255 votos, 0 crasheos) | **Los contratos ciegos como RANKERS intra-ensayo (votos de contratos ajenos, solo checks del contrato — los universales compartían instrumento con `estricto`, cazado en revisión): neto B' = +2 → KILL de la variante ([−2,+2]). El offset pre-declarado es severo (39/255 votos aprueban: condenan casi todo). Secundaria honesta: asimetría 2-0 (rescata carrito r1 y hoja r3, NUNCA elige peor que s1) — selector débil, no dañino; baseline anotado para iterar el marco (votos solo sobre selectores OBLIGATORIOS / mayoría-de-fracción), sin adopción. scripts/b2_consenso_selector.py** |
| **Nocturna 28→29 (2ª sesión) — consenso cruzado iteración 2: MODERADA, y cierre de la vía de votos** | HECHO 2026-07-28 (PREREG_CONSENSO2; anclas 255/255 = 100%, baseline +2 exacto) | **V1 solo-selectores-obligatorios +3, V3 combo +3 (asimetría 3-0), V2 mayoría-de-fracción +2 (KILL) — ninguna llega al umbral de vida +5.** La revisión (3 agentes) cazó 2 BLOQUEA pre-corrida (clasificador any-match sin discriminación; clave anidada `pasos` invisible). Partidas por conjuncto: el +3 no es reconstrucción del instrumento. **Mecanismo: los inventos del contrato ciego viven en los VALORES de los checks, no en los selectores (palanca 7%). Regla pre-fijada: no más variantes de votos — la próxima vía de señal es EJECUCIÓN EN EL BUCLE.** scripts/b2_consenso2.py |
| **BoN K=4 + selector CABLEADO como modo del sistema** | HECHO 2026-07-28 (commits 826fc39, 392dfbb; gate de confirmación corriendo esa noche) | bon.py de producción: K réplicas independientes + selector externo, env-gated (COGNIA_BON_K, COGNIA_BON_SELECTOR), default intacto; sin selector degrada ruidosamente a 1 réplica. Extras de la unidad: presupuesto de PARED por celda (cognia/presupuesto_pared.py) y volcado pasivo del prompt DEL LAZO (COGNIA_DUMP_PROMPTS) para la sonda del ladrón de ~17 pts. Resultado del gate: fila siguiente. |
| **Gate de confirmación del modo BoN: CONFIRMADO (neto B = +8)** | HECHO 2026-07-29 (PREREG_BON_GATE + 3 enmiendas; v1 abortada por infra, v2 completa) | **Control s1 12/20 (60%) → modo BoN 20/20 (100%): el cableado rescata LOS OCHO fallos del control, pierde 0; pérdida del selector C = 0.** La v1 se descartó ENTERA por infra sistémica cazada a 5 ensayos: las builds nuevas de llama-server parten ctx entre 4 slots por defecto (8192/4 = 2048/petición → HTTP 500 al 50% de los prompts con la visión viva; hasta las "exitosas" generaban con context-shift silencioso). Fix ops: --parallel 1 explícito + chequeo ejecutable de slots en el arranque. Coste del no-fallback: 5% de muestras. 96 prompts del lazo capturados con outcome para la sonda del ladrón. |
| **Matinal 29 — SONDA DEL LADRÓN fase 1: el TEXTO del prompt del lazo roba (neto −7)** | HECHO 2026-07-29 (PREREG_SONDA_LAZO + 3 enmiendas; 24 pares, 0 infra) | **Replay ÍNTEGRO del prompt capturado del lazo 11/24 (46%) vs idea pelada 18/24 (75%), juez estricto, ambos brazos por el MISMO camino de backend — la única diferencia era el TEXTO. C gana en las 4 tareas; original-only −6 (misma rama). El fork descarta el FLUJO como ladrón principal: el robo del envoltorio (~17-29 pts histórico) vive en el TEXTO.** Bonus mecánico: 2ª clase de cuelgue cazada EN corrida — página generada con JS ocupado bloquea page.evaluate (595 s de CPU medidos) → el juzgado lleva presupuesto de pared propio (300 s) y el cuelgue es reprobado legítimo (propiedad de la página). sin_html 2-0 contra el texto del lazo (la espiral también es del texto). Fase 2 el mismo día: fila siguiente. scripts/b2_sonda_lazo.py |
| **Matinal 29 — fase 2: EL TROCEO REQUIRED ES EL LADRÓN PRINCIPAL (neto +6)** | HECHO 2026-07-29 (PREREG_ABLACION_TEXTO + 1 enmienda; 24 pares, 0 infra) | **L-sin-troceo 17/24 (71%) vs L íntegro 11/24 (46%), apareados sobre el MISMO prompt capturado: quitar las 11 líneas del troceo recupera casi todo el gap hasta el crudo (18/24). Buscaminas +5 con mecanismo legible (su enumeración "celdas 6, 12 y 18" partida en componentes rotos). Original-only +5, misma rama.** FASE 3: fix `COGNIA_SIN_TROCEO` implementado env-gated en _build_prompt_web (idéntico a la cirugía; default intacto; test 3/3) — **el A/B de confirmación EN el lazo (n≥6/brazo, ~2.5-4 h GPU) es LO PRIMERO de la próxima sesión.** scripts/b2_ablacion_texto.py |
| **Matinal 29 — ejecución en el bucle it.1: piloto de APTITUD PASADO; el bloque decide** | PILOTO HECHO 2026-07-29 (PREREG_EJECUCION_BUCLE + 1 enmienda) | Sondear-observar-juzgar emite y ejecuta (7/8 páginas con sondas ejecutadas, no degenerado → SIGUE). Direccional del piloto (n=8, NO decide): marco 2/7 con FN 5/6 — perfil aún tipo-ciego; control ciego concurrente 3/8. **El bloque de 24 páginas (~1 h GPU) queda para la próxima sesión**; si el FN no baja del ciego, la iteración 2 ataca el JUICIO (no el sondeo). scripts/b2_ejecucion_bucle.py |
| **CABECERA NUEVA: 3 tareas discriminan de 9 escritas — y el techo que se alcanzó primero es el del DISEÑADOR** | HECHO 2026-07-30 (PREREG_CABECERA_NUEVA; 2 tandas + re-calibración, 36 muestras) | **Cabecera final: carrito_cupones 3/4, ascensor 3/4, turnos_capacidad 2/4 — el mínimo exacto que el criterio pre-registrado exigía (≥3).** Las otras **6 salieron 4/4 a la primera**: editor_undo_buscar (undo atómico de un reemplazo masivo), calendario_conflictos (solapamientos con el borde que toca), parser_parentesis (paréntesis ANIDADOS con precedencia), presupuesto_reparto (un cambio que rompe el invariante REVIERTE), carrito_packs (el precio depende del mínimo entre dos cantidades) e inventario_reservas. **Ninguna cayó en 0/4: cero evidencia de techo de capacidad.** La hipótesis que guió la 2ª tanda ("las que discriminan exigen un invariante global re-evaluado") quedó DESCARTADA por sus propios casos puros. **Conclusión: no sé diseñar una tarea web verificable por ejecución que este sistema no resuelva — el techo que se alcanzó primero no es el del sistema, es el del diseñador de exámenes.** Medir progreso exige cambiar de DOMINIO o de tipo de VERIFICACIÓN, no subir dificultad dentro del mismo molde. Límite de la cabecera: con 3 tareas sirve para ver cambios grandes, no diferencias finas. Dos correcciones honestas del camino: 2 tareas "difíciles" lo eran por ambigüedad MÍA (no exigían estado inicial vacío; corregidas, subieron a 4/4), y b2_bon_heldout no tenía presupuesto de pared en el juzgado (una página con JS bloqueante colgó la corrida 13 min, chromium a 719 s de CPU — segunda vez del mismo fallo). |
| **EL BANCO DURO SE SATURÓ — hace falta cabecera nueva** | MEDIDO 2026-07-30 (64 muestras del goal, juez triple) | **pass@1 = 92% (59/64); 5 de 8 tareas al 100%** (descuento, form_cruzado, temporizador, tres_en_raya, undo_redo); la única que discrimina es tabla_compuesta (62%). META registraba pass@1 ≈83% y definía la cabecera como "los 17 puntos hasta el 100%": hoy quedan 8, concentrados en una tarea. **Es el mismo diagnóstico que esta META hizo del banco de 6 ("SATURADO, no sirve para medir avance") y la misma consecuencia: sin cabecera no hay progreso medible.** El 8/8 del goal sigue válido y replicado, pero mide un banco que el sistema actual ya domina. Cabecera nueva en construcción con criterio de admisión PRE-REGISTRADO (entra la tarea con pass@1 entre 1/4 y 3/4): PREREG_CABECERA_NUEVA_20260730.md, scripts/b1_tareas_cabecera.json |
| **El held-out del duro, ENDURECIDO: el 8/8 sobrevive al examen que muerde** | HECHO 2026-07-30 (64 páginas congeladas, cero GPU) | El caveat "el held-out no discrepa del original" se atacó escribiendo un SEGUNDO held-out para romper. **Causa encontrada del v1 (y era mía): repetía casos que el original ya probaba** — en `precedencia`, ambos contenían literalmente `7-2*3=1`. El v2 ataca solo huecos (que la tabla ORDENE y que el 2º click INVIERTA; que C LIMPIE; la DIAGONAL; reset MIENTRAS corre; coherencia largo↔celdas; bordes 0/50/100 y 7/8 chars, 120/121). **Resultado: original 59/64, v1 60/64, v2 62/64 y v2 CAZA 0** — ni un fallo que el original deje pasar; los 3 casos inversos son los que v2 deliberadamente no repite (es COMPLEMENTARIO, no más laxo). **Re-medición con juez TRIPLE: r1 y r2 dan control 7/8, MODO 8/8, techo 8/8 — idéntico.** Límite que permanece: los tres exámenes miden lo mismo en el fondo (Playwright sobre los selectores del enunciado) y los escribió la misma mano. |
| **PASO PREVIO DEL ADAPTADOR HECHO: el corpus pasa de 4 a 21 enunciados, y el "condena sanos" REPLICA en los 17 nuevos** | HECHO 2026-07-30 (PREREG_ADAPTADOR_ANTIINVENCION; 8.4 min de GPU + 87 juicios sin GPU) | El bloqueante del adaptador no era la GPU sino tener **solo 4 enunciados** con contrato. Se levantó generando el contrato interno sobre las **páginas YA congeladas** (`generar_contrato` solo necesita enunciado + DOM): **100 páginas → 87 contratos (87%) en 8.4 min → 17 enunciados nuevos, todos cubiertos.** El leave-one-task-out pasa de 4 grupos a **21**. **Línea base medida en los nuevos (`b2_j_ampliado.py`): ACUSA_SANOS 88.2% en el duro y 93.5% en la cabecera** — por enunciado, `descuento_tramos`/`form_cruzado`/`undo_redo`/`tabla_compuesta` reprueban el **100%** de sus sanas, y en la cabecera **8 de 9 enunciados están al 100%**. **El perfil "condena sanos" no era del banco brutal: es del contrato interno en general, y replica en 17 enunciados nunca medidos.** *Advertencia declarada:* los J de +11.8/+6.5 están **inflados por la ausencia de rotas** (3 y 2), así que el número que se sostiene es ACUSA_SANOS, no el J — leerlos al revés sería el mismo error de una-tasa-suelta que costó el KILL de la poda. **Y EL DATASET, CONSTRUIDO LA MISMA NOCHE (cero GPU): 582 ejemplos etiquetados sobre 17 enunciados, leave-one-task-out de 17 grupos.** La etiqueta débil ("el check falla en TODAS las páginas sanas de su enunciado ⇒ candidato a valor inventado") sobre la diagonal daba solo 152 checks con **501 descartados por n<2**; con la **matriz cruzada** (cada contrato contra las demás páginas de su enunciado, 418 celdas en 40.3 min, 0 chromium huérfanos) pasa a **653 evaluables y 0 descartados**: **275 INVENTADO (42.1%) · 307 CORRECTO (47.0%) · 71 mixtos**, y 262 candidatos reales tras quitar los 13 con firma de ruido de API. **ESE 42.1% EXPLICA MECÁNICAMENTE EL ACUSA_SANOS:** con un AND sobre críticos y 4 de cada 10 checks fallando siempre contra sanas, casi ninguna página sana puede aprobar — el 88-94% deja de ser un misterio y pasa a ser su consecuencia aritmética. Consecuencia: la función objetivo del adaptador es **bajar ACUSA_SANOS sin subir DEJA_PASAR**, y su gate debe evaluarse donde haya rotas (brutal o gate del BoN), no en el duro. El 13% de contratos fallidos **no es un bug**: son el descarte de vacuos ya en producción y el fallo de emisión del pensador — con tasa **mayor que el 11.4% histórico y concentrada en las tareas más complejas** (`tabla_compuesta` 4/8, `temporizador` 5/8): el pensador falla más al escribir el examen cuanto más difícil es la tarea. |
| **AUDITORÍA: la premisa del adaptador NO se sostiene — el fallo #1 del contrato es `texto` sobre un `<input>` (41%), no inventar valores** | HECHO 2026-07-30 (PREREG_ADAPTADOR_ANTIINVENCION; `b2_taxonomia_checks.py`, cero GPU) | Antes de entrenar nada se auditó la etiqueta débil: a mano una muestra de 45 y después **estructuralmente los 582 checks** (sin juicio subjetivo, solo lo que dice el JSON del paso). **De los 275 que fallan en TODAS las páginas sanas: 113 (41.1%) son una aserción de `texto` sobre un `<input>` —que NO PUEDE pasar jamás porque `innerText` de un campo es vacío, dé igual el valor—, 124 (45.1%) tienen un literal que *podría* estar inventado, 8 usan un `#id` que el enunciado no declara y 10 no aseertan nada.** Y el lado bueno está igual de contaminado: **114 de 307 "CORRECTO-candidato" (37.1%) son solo ACCIONES sin aserción** (pasan siempre porque no comprueban nada) más 11 vacuos (`contiene: ""`). **Conclusión: la etiqueta no separa inventado de anclado, separa "falla siempre" de "pasa siempre", y ambos lados están dominados por artefactos** — entrenar con ella habría dado un detector de `texto`-sobre-`input` disfrazado de detector de invenciones. Ni el 45.1% restante está demostrado: `CON_VALOR` es "tiene un literal", no "inventado", y la muestra a mano sugiere que la mayoría **sí están anclados** (`540.00` y `14` salen literalmente del enunciado) y fallan por la SECUENCIA — el caso más claro, `editor_undo_buscar`, exige que **tras el undo** el texto sea el **ya reemplazado**: pide lo contrario del enunciado, que es un **error de razonamiento**, no un valor inventado. **Y encaja con un KILL previo: el modo `corregido` (usar `js .value` en vez de `texto`) es exactamente el arreglo de esos 113 y murió dos veces** — ahora se entiende por qué: arregla el 41% pero debajo quedan errores de secuencia que ningún cambio de forma toca. **La auditoría costó una tarde sin GPU y evitó entrenar contra el modo de fallo equivocado.** |
| **EL BoN SÍ SELECCIONA (p=0.0001) — pero el 8/8 del GOAL no es lo que lo demuestra** | HECHO 2026-07-30 (`scripts/b2_bon_vs_azar.py`, cero GPU, 10.000 réplicas del nulo) | Salió persiguiendo un hallazgo lateral del medoide: **el azar tiende a batir al control s1** (direccional, no significativo — ver la fila del medoide), así que el BoN podía estar cobrando por *no usar s1* en vez de por seleccionar. **REPLICADO EN DOS CORPUS:** en `b2_bon_heldout` el azar esperado es 18.50/24, el control 17/24 y el **selector 24/24**, con **P(azar acierte los 24) = 2.3e-4** → **+5.50 sobre el azar**; en el gate, **+5.82 con P = 0.0001**. Dos corpus independientes, mismo margen (~+5.5 a +5.8) y misma p (~1e-4). Se separaron las tres referencias: **CONTROL (s1) · AZAR · BoN**. | | | **(1) La sospecha queda DESCARTADA con margen y es evidencia nueva: en el GATE (`b2_bon_gate_v2`, n=19, banco NO saturado) control 12/19, azar 13.18/19, BoN 19/19 → +5.82 sobre el azar, P(azar ≥ BoN) = 0.0001.** El azar también evita s1 y se queda en 69%; el selector llega al 100%. Primera validación del mecanismo del BoN contra la referencia correcta. **(2) Pero en el banco DURO el azar saca 7.26/8 (r1) y 7.49/8 (r2), con P(azar ≥ 8/8) = 0.376 y 0.558: más de una de cada tres veces elegir a ciegas también da 8/8.** El 8/8 del goal **se sostiene como ENTREGA, no como prueba del mecanismo** — la prueba está en el gate. Cuarta vía que confirma la saturación del duro: **no sirve para medir selectores**; hay que medirlos donde el azar no sature (en el gate hay 31 puntos de recorrido entre azar y techo). *Caveat declarado:* el ground truth del gate incluye `aprobado_sel`, el examen que el propio selector usa, así que el 19/19 absoluto está inflado — la comparación BoN vs AZAR sí es válida (mismo ground truth para ambos), pero medir el acierto absoluto exige un tercer examen independiente. |
| **10ª vía — MEDOIDE del consenso conductual: KILL con réplica (+4 → +0) — y el brazo nulo REINTERPRETA todas las variantes de consenso** | HECHO 2026-07-30 (PREREG_MEDOIDE; 24/24 ensayos, 0 infra, cero GPU) | **control 17/24 · MEDOIDE 21/24 · techo 24/24 · neto apareado +4 (RESCATA 4, ESTROPEA 0)** — duplica la ganancia del consenso por mayoría (+2) y confirma su mecanismo (resuelve justo los ensayos que no formaban mayoría). Pero el umbral era neto ≥+5 **y** superar el p95 del brazo nulo, y no cumple ninguno: **NULO media 18.46/24, p95 = 21/24, P(azar ≥ medoide) = 0.100.** **EL HALLAZGO QUE VALE MÁS QUE EL VEREDICTO: el azar es un rival duro** — con techo 24/24 hay tantas muestras buenas por ensayo que elegir a ciegas da 18.46/24, por encima del control (17/24). *Corrección que me hice al comprobarlo (20.000 réplicas): la dirección es consistente en los 3 conjuntos (neto del azar +1.50 / +1.16 / +2.70) pero **NO es significativa** — P(el azar no bate al control) = 0.265 / 0.335 / 0.162. Decir "sistemáticamente" era pasarse; lo honesto es que **s1 no es mejor que una muestra cualquiera, y que sea peor es direccional, no demostrado**.* **Lo que SÍ se sostiene y es lo que importa: el neto del azar contra el control tiene media +1.2 a +2.7 y p95 de +4 a +6, así que un "+2" o un "+3" está DENTRO de la banda del azar** — el "+2 moderada" del consenso por mayoría y el "+3" de los votos **no se distinguen del ruido**, y la referencia correcta de un selector es el AZAR, no la primera muestra. **RÉPLICA PRE-REGISTRADA Y CORRIDA el mismo día sobre `b2_bon_gate_v2` (24 ensayos más, mismas tareas ⇒ sondas existentes, cero GPU): el +4 NO reproduce — neto +0 (rescata 1, ESTROPEA 1, la primera vez que una variante de consenso estropea algo), y el azar lo bate en el 85% de los sorteos.** Con el nulo APAREADO (corrección de mi propio cálculo, que mezclaba ensayos sin s1 y favorecía al azar): original +4 vs azar +1.49 (P=0.101), réplica +0 vs +1.16 (P=0.855), agregado +4 vs +2.70 (P=0.359) — **no supera el p95 en ninguno. KILL, y con él cae la familia entera de consenso**: el medoide era la mejor variante medida y no aguanta una réplica. Se descartó replicar sobre el banco DURO **antes** de gastar, por saturado. Instrumentación: lo que faltaba era **guardar la trayectoria en vez de su hash** (`sha1[:12]` solo dice igual/distinto; sin distancia no hay medoide) — segundo caso del día del mismo patrón. |
| **9ª vía — PODA DE CHECKS por fallo unánime: KILL ANTES DE CORRER, y el contrato interno está EN EL AZAR EXACTO** | HECHO 2026-07-30 (PREREG_PODA_CHECKS; revisión adversarial + **reproducción independiente mía**) | **La poda es MONÓTONA por construcción** — quitar checks nunca convierte APROBADO en REPROBADO, así que ACUSA_SANOS solo baja y DEJA_PASAR solo sube con probabilidad 1, haya señal o no: **el umbral no medía si la poda acierta sino cuánto poda.** Medido: poda 270/702 checks (38%), ACUSA_SANOS 81.9→11.9, DEJA_PASAR 6.5→80.6 y **Youden J 11.7→7.4 (EMPEORA)**. **Brazo nulo** podando el mismo número AL AZAR: J medio 8.6 [p5 2.9, p95 14.6] → **la poda real cae en el percentil 34**: no compra discriminación, compra agresividad. **Y el hallazgo mayor, con su corrección incluida: el contrato interno en su configuración VIVA (la diagonal, vía `sello_lazo`) da J = −1.1 en `b2_bon_heldout`… pero medido sobre TODOS los corpus congelados (427 muestras, 10 tareas, `scripts/b2_j_contrato_interno.py`) el número real es J = +12.2, con rango −9.7 a +32.8.** El −1.1 era el peor de diez corpus: decir "está en el azar exacto" era sobre-generalizar y se corrige aquí. **Lo que el dato amplio SÍ fija es más útil: el modo de fallo dominante NO es aprobar basura sino CONDENAR SANOS — aprueba solo el 17.7% de las páginas que el juez a mano aprueba y deja pasar el 5.5% de las rotas. Es un examen brutalmente severo, no ciego.** **Consecuencia que manda: una transformación que solo relaja no añade información** — reparte el J que ya había, y aquí lo repartió peor que el azar; cualquier vía que quiera cobrar tiene que atacar la GENERACIÓN del contrato (por qué condena tanto), no reponderar sus checks a posteriori. Regla que queda escrita: la primaria de un examen es **Youden J apareado**, nunca una tasa sola, porque toda transformación que solo relaja o solo endurece mueve las dos tasas a la vez y cruza cualquier umbral de una sola. **Deuda de instrumentación saldada (coste cero):** los runners tiraban el contrato autogenerado (0 de 255 votos tenían la diagonal); ahora se persiste `contrato_interno.json` + el detalle POR CHECK del juez. |
| **8ª vía de señal — VERIFICACIÓN METAMÓRFICA: KILL, y el mecanismo explica las OCHO** | HECHO 2026-07-30 (PREREG_METAMORFICO; 158 páginas, 0 infra, **cero GPU**) | **KILL disparado en el lado de CALIBRACIÓN, donde el prereg me permitía ajustar: ningún umbral cruza los dos listones** (bajo → ACUSA_SANOS 43.1%; alto → DEJA_PASAR 50.0%; en el duro ACUSA_SANOS 31.6% y 28.6%). **El número que manda: 0 pares inversos instanciados en 158 páginas congeladas** — R1/R3/R4 no se instanciaron NI UNA VEZ y el catálogo se redujo a R0. **Mecanismo: para saber qué acción deshace a cuál hay que LEER EL ENUNCIADO.** Los dos caminos están cerrados: por léxico, cobertura 0 (y donde el léxico sin podar sí encontraba par eran calculadoras donde `+`/`−` se CONCATENAN, `expr += val` — correrlo así habría firmado un KILL FALSO de la idea cuando moría el descubridor); por efecto medido, es CIRCULAR (si el par se define como "el que devuelve el estado inicial", R1 no puede fallar). Y R0 **no es señal nueva**: es el check `interactivo` que el juez de referencia ya tiene, con DEJA_PASAR 50% — detecta páginas MUERTAS, no INCORRECTAS. **CONCLUSIÓN QUE UNIFICA LAS 8 VÍAS: una verificación que no lee la especificación puede detectar INACTIVIDAD, pero no INCORRECCIÓN.** Alcance declarado: tareas web con este catálogo y descubridor; no cierra el testing metamórfico en dominios donde la relación la da la matemática del problema. La revisión adversarial a 3 lentes cazó **13 BLOQUEA antes de gastar**, incluidos las etiquetas FP/FN invertidas respecto a la línea base del repo y un umbral de fase 2 que un selector ALEATORIO cruzaba el 21% de las veces. scripts/b2_metamorfico.py, b2_metamorfico_analisis.py, b2_metamorfico_selector.py |
| **EL GOAL: MODO 8/8 en el banco DURO, REPLICADO (2 de 2 corridas)** | HECHO 2026-07-30 (PREREG_GOAL_DURO; 64 muestras en 2 corridas, 0 sin HTML) | **r1 y r2 idénticas: control (s1) 7/8 · MODO 8/8 · techo pass@4 8/8 · pérdida del selector 0 · 0 fallos por TECHO y 0 por SELECCIÓN.** La estructura se reproduce exacta: la misma tarea es la única que el control falla (tabla_compuesta, rescatada por el selector en ambas). **El goal de esta META está ALCANZADO Y REPLICADO.** Lo que sigue abierto, con la misma claridad: (a) la ganancia del BoN es **+1 tarea** en ambas corridas — el sistema sin BoN ya da 7/8; (b) **el held-out del duro no discrepó del original en 64 páginas** (en el brutal cazó 4 FP), así que este 8/8 se apoya en un examen menos exigente de lo que su etiqueta sugiere — endurecerlos y re-medir es trabajo pendiente; (c) **sigue sin haber señal para tareas NUEVAS**: el selector es un examen escrito A MANO por tarea, y las 7 vías autogeneradas siguen muertas o moderadas. El goal medido es "8/8 en un banco preparado", no "8/8 en lo que le eches". |
| **(fila previa) EL GOAL, primera medición: corrida 1** | HECHO 2026-07-30 (PREREG_GOAL_DURO; 32 muestras, 0 sin HTML) | **Control (s1) 7/8 · MODO (BoN K=4 + selector held-out) 8/8 · techo pass@4 8/8 · pérdida del selector 0.** Ninguna tarea falla por TECHO ⇒ **el criterio de KILL de esta misma META ("si una tarea no sale NUNCA en 8 muestras, el muestreo no la compra") no se dispara en ninguna de las 8.** El selector rescató la única que el control fallaba (tabla_compuesta → s2). **La brecha que lo impedía y que nadie había nombrado: el banco DURO —el del goal— no tenía held-outs a mano** (brutal y fácil sí), así que no había juez estricto ni selector con señal real; se escribieron los 8 desde el enunciado y se validaron (0 desacuerdos, 0 checks que fallen siempre, cobertura 4/4). **TRES CAVEATS que impiden declararlo estable:** (1) n=1 réplica = FOTO, no tasa, con ±34 pts de varianza medida entre corridas; (2) **la ganancia del BoN es +1 tarea, no siete** — el control ya daba 7/8, coherente con el pass@1 ≈83% ya registrado; (3) **el held-out NO demostró independencia aquí: 0 desacuerdos con el original en 32 páginas** (en el brutal cazó 4 FP), así que el "juez estricto" fue de facto el contrato original. scripts/b2_goal_duro.py, b1_contratos_heldout_duras.json |
| **Tarde-noche 29 — fase 3: el fix del troceo NO cobra en el lazo (neto −4) y la vía se cierra** | HECHO 2026-07-29 (PREREG_SIN_TROCEO_LAZO + 1 enmienda; 24 pares, 0 infra) | **A/B del lazo completo con el instrumento congelado (b2_ab_fix2 --var): ON 15/24 vs OFF 19/24, neto −4; estricto post-hoc −6. El troceo AYUDA dentro del lazo.** Tercer caso del patrón "la sonda directa cobra, el lazo lo mata" (v2 −5, v3 −4, quitar −4) — esta vez con la sonda más fuerte posible. La sonda de la discrepancia (PREREG_DISCREPANCIA_TROCEO, etapas A+B + diff) da **H-material (+1: el +6 no reproduce sobre prompts frescos)** SIN mecanismo identificado: el diff estructural muestra material fresco casi idéntico al del gate (largo 6106 vs 5972, feromona 1649 vs 1454, brief 430 vs 437). `COGNIA_SIN_TROCEO` queda env-gated APAGADO. |
| **Tarde-noche 29 — VALIDEZ DEL INSTRUMENTO: el replay representa al lazo (neto −1), y la varianza entre corridas es ±34 pts** | HECHO 2026-07-29 (PREREG_LAZO_VS_REPLAY + 1 enmienda con 4 BLOQUEA; 24 pares apareados por celda, 0 infra) | **Apareado perfecto (mismo prompt, misma celda, mismo minuto): LAZO 14/24 (58%) vs REPLAY 15/24 (62%) — indistinguibles; co-primaria sin fallbacks también −1; parseo neto 0 (la candidata #1 enterrada, confirmada offline en 107/107 crudos).** El replay queda validado: las fases 1-2 se sostienen. **Y el número de la noche: concordancia lazo↔replay 13/24 = 54% — el prompt fija la TASA, no el destino;** el mismo lazo midió 92/79/58% en la misma tarde. Consecuencia declarada: solo los netos APAREADOS intra-corrida son evidencia; comparar niveles entre corridas (incluida mi H-material) es de segundo orden. Memoria: varianza-entre-corridas. |
| **Tarde-noche 29 — marco ejecución-en-el-bucle: KILL de it.1 y CORRECCIÓN del mecanismo por auditoría** | HECHO 2026-07-29 (bloque 24, PREREG_EJECUCION_BUCLE) | **it.1: aciertos 6/23 (≤11 = KILL), FN 17/19, FP 0/4, control ciego concurrente 6/24.** La auditoría pre-declarada de los 21 dictámenes INCORRECTO **refutó mi primera lectura**: el juicio CITA REGLAS REALES del enunciado, no inventa. Falla el INSTRUMENTO — sondas que declaran "añadir dos veces" y ejecutan un click, y un snapshot ciego al `disabled` que la regla exige. **it.2 (C1 snapshot con estado, C2 repeticiones verificadas, C3 NO_CONCLUYENTE obligatorio) corriendo; su humo sobre las mismas 8 páginas dio aciertos 2/7→4/7 y FN 5/6→2/6.** |
| **Juez ejecutable EN el lazo de producción** | **HECHO 2026-07-26 (mecanismo verificado e2e)** | El lazo entrega por sello del juez, no por nota del VLM; contraejemplos → reparar_web. Caso real medido: ronda 1 FALLIDO (4 contraejemplos) → ronda 2 reparado → APROBADO por juez. Para llegar hubo que arreglar 4 bugs de plomería en cascada, todos "presupuesto de tokens que no contaba el razonamiento" (commits 463a6eb, 776f445, d7e1419) |
| b2 (sistema real, 6 tareas) | **GATE CERRADO 2026-07-26, n=6: 3, 4, 5, 5, 4, 6 /6 (media 4.5, mediana 4.5, mínimo 3; 27/36 = 75% de tareas)** vs baseline 2/6 | **VEREDICTO formal (regla gate-e2e-flaky, n=6 alcanzado): la mejora SE DECLARA.** Las 6 réplicas superan al baseline (mínimo 3/6 > 2/6); los fallos están DISPERSOS (las tareas que fallan rotan corrida a corrida: contador y calculadora caen en run8 y aprueban en run9), que es la firma de ruido de generación, no de regresión concentrada. Run9 fue la primera corrida 6/6, con las 6 tareas por el lazo entero. El cuello restante es la varianza de la generación inicial + reparación que no siempre remata en ≤3 rondas → PREREG_BON_RONDAS_20260726.md. JSONs en b2_sistema_real/resultados_run{4..9}_configfinal.json |

---

## Prioridades tras revisar la literatura (2026-07-25)

Ordenadas por ganancia esperada / esfuerzo. Cada una con su número publicado.

**#1 — Reparación con contraejemplo — SUSPENDIDA POR EVIDENCIA PROPIA
(2026-07-28): dos A/B intercalados n=6 (brutal neto −3, fácil neto −7)
muestran que EN ESTE SISTEMA las rondas restan — reparan guiadas por un
sello al nivel del azar y degradan páginas sanas. max_rondas=1 adoptado.
La literatura de abajo sigue siendo válida EN SU CONDICIÓN: TDDev/self-repair
ganan con un verificador FIABLE; la nuestra no lo es todavía. La prioridad
pasa a ser la SEÑAL (held-outs a mano, validación de aserciones) y la
reparación vuelve el día que el contrato interno supere al azar contra el
banco. ACTUALIZACIÓN 2026-07-28: la señal-con-held-out ya demostró que paga
— BoN K=4 la convierte en 24/24 (fila de la nocturna 28→29) — y la vía
"contrato ciego" quedó cerrada con 4 KILL (2 plantillas, 1 filtro, 2
modelos): lo que falta es un MARCO nuevo de señal para tareas no vistas
(consenso conductual entre muestras / ejecución en el bucle).** Texto original: tope 3-4 rondas. `scripts/reparar_contraejemplo.py`
En **este dominio exacto** (web + Playwright), TDDev midió **+34,5 a +48,0
puntos** en acc@5 ([arXiv:2605.17242](https://arxiv.org/html/2605.17242));
self-repair a escala 8B da +16 a +30 pp en MBPP
([arXiv:2604.10508](https://arxiv.org/abs/2604.10508)). Es la apuesta más alta.
**La sutileza que casi todos hacen mal:** hay que pasar el **contraejemplo del
verificador**, no la traza ni el código roto ni una auto-crítica. Un estudio
preregistrado con **control placebo** sobre modelos chicos congelados
([arXiv:2606.31511](https://arxiv.org/abs/2606.31511)) encontró que el código
fallido y la traza de ejecución **empatan con un placebo sin contenido**. Lo
único con señal real son contrafactuales ejecutables externos — que es
literalmente lo que `juez_ejecutable` ya produce (`visibles('.tile')=16,
esperaba 0`). La pieza estaba construida por accidente afortunado.

**#2 — Best-of-N con pool HETEROGÉNEO y selección ejecutable, N pequeño (4-8).**
S* hizo que un **7B superara a un 32B en +10,1 pp** en LiveCodeBench
([arXiv:2502.14382](https://arxiv.org/html/2502.14382v1)). Aquí es donde la
flota aporta: como diversidad de errores, no como menú.

**#3 — Escalar el VERIFICADOR — CORREGIDO 2026-07-27: escalar es CORRECCIÓN,
no cantidad.** El A/B del contrato amplio (PREREG_CONTRATO_AMPLIO_20260727)
mató la lectura ingenua de CodeRM en este dominio: 10-16 pasos eliminan los
FP pero disparan el FN a 75% (aprueba 1/24 donde el banco aprueba 19/24).
Los dos exámenes autogenerados rechazan en masa páginas sanas: la palanca
es validar cada aserción contra el enunciado y podar los tipos de paso que
acusan sanos, no pedir más pasos.
CodeRM: pasar de 1 a 16 aserciones da +5 a +8 pp
([arXiv:2501.01054](https://arxiv.org/pdf/2501.01054)), y **los modelos chicos se
benefician más**. Pero el efecto real es mayor, porque **la tasa de falsos
positivos del contrato ES el techo de todo lo demás**: con FP > 0 hay un límite
que ningún presupuesto de cómputo cruza
([arXiv:2411.17501](https://arxiv.org/abs/2411.17501)).

**#4 — Dos A/B baratos con prior fuerte.** (a) *Thinking OFF* para el rol
CONSTRUCTOR: el CoT explícito **degrada el seguimiento de instrucciones
constreñidas en 15 de 15 modelos** ([arXiv:2505.11423](https://arxiv.org/abs/2505.11423)),
y generar contra un contrato es exactamente eso. (b) Tope de tokens de
pensamiento en ~6K: −50 % de cómputo por −6 % de precisión
([arXiv:2604.10739](https://arxiv.org/html/2604.10739v1)).

**#5 — RLVR / Step-GRPO con la recompensa ejecutable.** Es la única de la lista
que **crea** capacidad en vez de extraerla: WebGen-Agent llevó a
Qwen2.5-Coder-7B de **12,4 % a 45,4 %**
([arXiv:2509.22644](https://arxiv.org/html/2509.22644v1)). Alto esfuerzo, va
última. Aviso: medir **pass@k**, no pass@1 — RLVR agudiza la distribución, no la
expande ([arXiv:2504.13837](https://arxiv.org/abs/2504.13837)), y si el pipeline
final es best-of-N se opera en k grande, donde el modelo base puede ganar.

## Lo que la literatura MATA (no gastar tiempo aquí)

- **Auto-crítica sin señal externa.** CommonSenseQA 75,8 → 38,1
  ([arXiv:2310.01798](https://arxiv.org/abs/2310.01798)); la revisión TACL no
  halló **ningún** caso exitoso ([arXiv:2406.01297](https://arxiv.org/abs/2406.01297)).
- **Pedirle al modelo que escriba la crítica** teniendo ya un pass/fail: el
  re-prompting simple captura casi todo el beneficio
  ([arXiv:2402.08115](https://arxiv.org/abs/2402.08115)).
- **Debate multi-agente homogéneo:** pierde contra self-consistency al mismo
  coste ([arXiv:2502.08788](https://arxiv.org/abs/2502.08788)).
- **Mixture-of-Agents con modelos de calidad desigual:** el modelo flojo
  arrastra al conjunto ([arXiv:2502.00674](https://arxiv.org/abs/2502.00674)).
- **Construir un PRM.** DeepSeek-R1 los abandonó por reward hacking
  ([arXiv:2501.12948](https://arxiv.org/abs/2501.12948)). Un verificador
  ejecutable es lo que un PRM aproxima mal.
- **Más tokens de pensamiento:** inverse scaling medido; R1-32B pico a 12K y
  **peor** a 16K ([arXiv:2604.10739](https://arxiv.org/html/2604.10739v1)).
- **Repo-map por grafo/PageRank:** ripgrep sin índice **38,61 % EM vs 19,44 %**
  de GraphCoder, a 1/80 de latencia
  ([arXiv:2601.23254](https://arxiv.org/html/2601.23254v2)). Afecta al trío del
  agente-dev de la 4.1.0.

## El riesgo que hay que instrumentar DESDE EL DÍA UNO

**Un verificador imperfecto es un generador de fallos silenciosos** — que es
exactamente el modo de fallo característico de este proyecto, con otra cara.

SpecBench ([arXiv:2605.21384](https://arxiv.org/abs/2605.21384)) identifica que
el reward hacking **no lo causa la mala cobertura de tests, sino la brecha entre
dificultad de la tarea y capacidad del modelo** — y que **los modelos chicos
hackean más**. Este proyecto está justo en ese régimen: va a producir páginas
que pasan el contrato y son basura.

**Contramedida obligatoria:** una suite **held-out** por tarea (aserciones que el
modelo nunca ve) desde el principio, no como refinamiento posterior. Y medir el
poder discriminativo del contrato sin ground truth con LOAUC/ACES
([arXiv:2604.03922](https://arxiv.org/pdf/2604.03922)).

## El límite honesto, con número

Con tasa de falsos positivos > 0 hay un **techo duro que ningún presupuesto de
cómputo cruza**, y *"ninguna cantidad de inference scaling de un modelo débil le
permite igualar la precisión single-sample de un modelo suficientemente fuerte"*
([arXiv:2411.17501](https://arxiv.org/abs/2411.17501), Princeton). A razón
coste-beneficio 4, el **N óptimo es ≤ 5**.

Y el único resultado publicado de "modelo abierto + test-time scaling alcanza
frontier" (oro en IOI, [arXiv:2510.14232](https://arxiv.org/abs/2510.14232)) usó
**gpt-oss-120b y ~14.600 millones de tokens**, quedó **16 % por debajo** del
frontier, y **probaron el 20b: rindió peor**. Eso acota lo que es razonable
esperar aquí.

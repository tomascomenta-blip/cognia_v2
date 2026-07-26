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
| **Juez ejecutable EN el lazo de producción** | **HECHO 2026-07-26 (mecanismo verificado e2e)** | El lazo entrega por sello del juez, no por nota del VLM; contraejemplos → reparar_web. Caso real medido: ronda 1 FALLIDO (4 contraejemplos) → ronda 2 reparado → APROBADO por juez. Para llegar hubo que arreglar 4 bugs de plomería en cascada, todos "presupuesto de tokens que no contaba el razonamiento" (commits 463a6eb, 776f445, d7e1419) |
| b2 (sistema real, 6 tareas) | config final replicada n=4: **3/6, 4/6, 5/6, 5/6 (media 4.25)** vs baseline 2/6 | En la config final las 6 tareas corren el lazo entero (antes 5/6 caían al camino corto). n=4 < 6: la mejora es consistente pero por la regla gate-e2e-flaky no se declara cerrada; las tareas que fallan VARÍAN corrida a corrida (memoria 10/10 en una y falla en otra) — el cuello es varianza de generación + reparación que no siempre remata en ≤3 rondas, no una tarea imposible. JSONs preservados en b2_sistema_real/resultados_run*.json |

---

## Prioridades tras revisar la literatura (2026-07-25)

Ordenadas por ganancia esperada / esfuerzo. Cada una con su número publicado.

**#1 — Reparación con contraejemplo, tope 3-4 rondas.** `scripts/reparar_contraejemplo.py`
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

**#3 — Escalar el VERIFICADOR y medir su tasa de falsos positivos.**
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

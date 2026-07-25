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

**Objetivo:** que la máquina de 16 GB entregue **8/8** en el banco duro, con
producto **entregable** (no oráculo: el sistema tiene que poder elegir la
muestra buena, y con el juez puede).

**Marcador intermedio, medible hoy:** igualar o superar a **Laguna XS 2.1**
(33B-A3B, 20 GB, el modelo más grande que cabe en esta máquina) corriendo en
una sola pasada. Si un 20B + best-of-N verificado iguala a un 33B single-shot,
la tesis "compute sustituye a parámetros" queda demostrada **en esta máquina y
en este dominio**.

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
| 1. Línea base dura | pendiente | — |
| 2. Curva pass@k | pendiente | — |
| 3. Marcador Laguna XS | corriendo (banco fácil) | — |
| 4. Refinamiento guiado | pendiente | — |

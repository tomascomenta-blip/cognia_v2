# PREREG — Adaptador anti-invención (DISEÑO; no se entrena todavía, y por qué)

**Fecha:** 2026-07-30 ~17:20, sesión tarde-noche 30→31. **Diseño y condición
de vida escritos antes de gastar un minuto de GPU.** No se entrena en esta
sesión: el bloqueante está identificado y no es el cómputo.

## El problema, cuantificado hoy

El contrato interno —el examen que el sistema se escribe a sí mismo— tiene
este perfil, medido sobre **427 muestras y 10 tareas** de todos los corpus
congelados (`scripts/b2_j_contrato_interno.py`):

| | |
|---|---|
| aprueba de las páginas **SANAS** | **17.7%** |
| aprueba de las páginas **ROTAS** | 5.5% |
| **Youden J** | **+12.2** (rango por corpus: −9.7 a +32.8) |

**El modo de fallo dominante no es aprobar basura: es CONDENAR SANOS.** Ocho
de cada diez páginas que el juez a mano aprueba, el contrato interno las
reprueba. Y el mecanismo ya está medido por check: los inventos viven en los
**VALORES** de los checks, no en los selectores (93% de los checks ya usan
selectores obligatorios; la palanca de la superficie fue del 7%). Un check que
exige `contiene: "5"` cuando el enunciado nunca fijó un 5 **no lo acierta
ninguna implementación correcta**.

## Por qué un ADAPTADOR y no más prompt

La vía "arreglarlo pidiéndoselo mejor" está **cerrada con 4 KILL
pre-registrados**: `corregido` ×2, `validado` (el filtro cortó 30 pasos y el
FN no se movió) y QA-fuerte con **dos modelos distintos** (Nemotron 0/6 de
aptitud; coder-14b con FN 14/19, idéntico a gpt-oss). Dos familias con el
mismo perfil ⇒ **la enfermedad es el MARCO, no el pensador**.

Y la vía "arreglarlo por post-proceso" quedó cerrada **hoy**: la poda de
checks es monótona por construcción y reparte el J que ya había — cayó en el
percentil 34 del azar (PREREG_PODA_CHECKS).

Queda una sola palanca no probada sobre esta función: **cambiar los pesos que
generan el contrato**. Ataca la misma función que los 4 KILL, pero por una vía
genuinamente distinta, así que **esos KILL no la cierran**.

## Por qué NO se entrena esta noche — el bloqueante, con números

| | |
|---|---|
| contratos generados en disco | **318** |
| …pero de cuántos ENUNCIADOS distintos | **4** (buscaminas, carrito_stock, hoja_calculo, kanban) |
| enunciados con contrato GOLD a mano | 27 (45 contando held-outs) |
| pares "enunciado → contrato bueno" | **27**: irrisorio |

Un adaptador entrenado sobre 4 enunciados **memoriza 4 tareas**. Y el split
honesto tiene que ser **por enunciado** (leave-one-task-out), o sea 4 grupos:
cualquier AUC que saliera de ahí sería indistinguible de memorización. **El
bloqueante no es la GPU** — la infra existe y es barata: `train_minicpm_lora.py`
entrenó un LoRA de 1B en **11 minutos** (0.67 s/paso, VRAM 7 GB, bs=2 +
gradient-checkpointing; con bs=4 desbordaba a shared memory y no cerraba una
época en 2.5 h).

## PASO PREVIO OBLIGATORIO (lo primero que debe correr, ~1-1.5 h de GPU)

**Generar contratos internos para las 23 tareas restantes** de
`b1_tareas.json` (6), `b1_tareas_duras.json` (8), `b1_tareas_cabecera.json`
(5) y `b1_tareas_cabecera2.json` (4), a 3-4 muestras cada una. Referencia de
coste: el A/B de 24 contratos tardó ~40 min.

Sin esto no hay held-out por enunciado y **ningún número del adaptador vale**.
Con esto se obtienen además dos cosas gratis: la línea base de J **por
enunciado** sobre 27 tareas (hoy solo se tiene sobre 10) y el dataset a nivel
check ampliable a ~2286 ejemplos.

Nota: ese paso ya es más barato que ayer — desde hoy los runners **persisten
el contrato autogenerado y el detalle por check** (deuda saldada en
PREREG_PODA_CHECKS), así que no hay que volver a tirar esa información.

## Qué se entrenaría, exactamente

**Un clasificador binario por CHECK**, no un reescritor. Entrada: el enunciado
+ el check literal. Salida: `ANCLADO` (el valor está fijado por el enunciado)
o `INVENTADO`. Se usa como **filtro de descarte** antes de que el contrato
juzgue.

Se elige clasificador y no seq2seq por una razón de datos, no de gusto: **no
existe ni un solo par alineado check-a-check** entre contrato generado y
contrato gold (los gold están por tarea, con nombres libres y otra
granularidad), y producir ese alineamiento no es trivial. El clasificador sí
tiene datos con el paso previo hecho.

**Sobre qué modelo:** el PENSADOR (el rol que genera el contrato).
**NUNCA sobre el CONSTRUCTOR** — el BoN vive de la diversidad de muestras que
un fine-tuning agudizaría, y ahí el efecto medido de RLVR es exactamente ese:
agudiza la distribución en vez de expandirla, y el pipeline final opera en k
grande, donde el modelo base puede ganar.

## Etiquetas: la que hay, y por qué NO basta

Etiqueta **débil**, derivable hoy sin GPU: un check que **falla en todas las
páginas sanas del mismo enunciado** es candidato a inventado. Ya calculada:
**548 checks con n≥2 → 186 inventado-candidato / 346 correcto-candidato / 16
mixtos**, con 168 de los 186 marcados `oblig=True`.

**Pero esa etiqueta confunde tres cosas**, y hay que separarlas antes de
entrenar con ella:

1. **valor inventado** (lo que queremos),
2. **check correcto que las referencias no cubren**,
3. **ruido puro de API** — `texto` sobre un `<input>` falla **24/24** porque
   `innerText` de un campo es siempre vacío. Eso no es invención de ninguna
   clase.

Sin separarlas, el adaptador aprendería a descartar el tipo (3), que ya está
resuelto en producción por otra vía. **Hace falta un pase de auditoría a
mano** que marque, por check, "el valor está FIJADO por el enunciado" vs
"inventado". Es acotado: los checks con literal sobre 4 rúbricas de una página
cada una, arrancando por los 548 ya ejecutados para tener la matriz de acuerdo
entre etiqueta débil y auditada.

## Condición de VIDA (pre-registrada, y es lo que impide autoengañarse)

Todo medido con **leave-one-task-out: entrenar en N−1 enunciados, evaluar en
el que nunca vio.** Nada de splits por muestra.

| métrica | umbral |
|---|---|
| **primaria** | **Youden J del contrato interno** (no una tasa suelta), apareado, en enunciados NO VISTOS |
| **VIVE** | ΔJ ≥ **+15 pts** sobre el contrato sin filtrar, y el intervalo bootstrap apareado excluye 0 |
| GRIS | ΔJ +5 a +15 |
| **KILL** | ΔJ ≤ +5, **o** el filtro no supera a un brazo nulo que descarte el mismo número de checks al azar |

**El brazo nulo es obligatorio** y no negociable: la lección de hoy es que un
filtro que solo descarta mueve las dos tasas a la vez y cruza cualquier umbral
de una sola. Si el adaptador no separa de "descartar al azar la misma
cantidad", no ha aprendido nada.

## Riesgos declarados antes de gastar

1. **El precedente dice que a lo mejor no hace falta entrenar.** Dos gates
   pre-registrados de este repo terminaron en "no entrenes": el árbitro visual
   zero-shot pasó su gate, y en PSeInt el traductor determinista de 28 reglas
   se comió la clase de error que el LoRA venía a arreglar. **Antes de gastar
   GPU hay que comprobar que el baseline sin adaptador falla** en la métrica
   exacta del gate.
2. **Un gate puede fallar por poco y dejar un adapter muerto.** Ya pasó: el
   LoRA de respuestas largas dio ×1.9 contra un umbral de ×2.0 y no se cableó
   a nada; hay 90 MB en disco que no sirven.
3. **El corpus lo diseñó la misma familia de modelos que lo resuelve** (caveat
   heredado de META, sigue vigente).

## Orden de ejecución, si se retoma

1. Generar contratos para las 23 tareas restantes (~1-1.5 h GPU).
2. Re-medir J por enunciado sobre 27 tareas (cero GPU) → **si el baseline no
   falla, no se entrena** (riesgo 1).
3. Auditoría de etiquetas sobre los checks con literal.
4. Entrenar el clasificador con leave-one-task-out (~11 min por fold para 1B).
5. Gate con brazo nulo.

## RESULTADO

*(no se corre en esta sesión; esto es diseño + condición de vida)*

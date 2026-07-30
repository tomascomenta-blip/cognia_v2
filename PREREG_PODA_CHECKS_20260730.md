# PREREG — Poda de checks por FALLO UNÁNIME sobre las muestras del BoN

**Fecha:** 2026-07-30 ~17:05, sesión tarde-noche 30→31. **Escrito ANTES de
mirar un solo dato de la poda.** Cero GPU: todo lo que hace falta ya está en
disco.

## La idea, en una frase

Un check que exige un valor **que el enunciado no fija** no lo acierta
ninguna implementación: **falla en TODAS las muestras**. Un check correcto
falla solo en las malas. Así que *"falla en las K muestras"* es una señal de
que el problema está en el CHECK, no en las páginas — y es autogenerada, sin
examen a mano y sin LLM decidiendo.

## Por qué esto NO viola la regla pre-fijada de "no más variantes de votos"

Tras `consenso2` quedó escrito: *"no más variantes de votos — la próxima vía
de señal es EJECUCIÓN EN EL BUCLE"*. Esa regla mataba una familia concreta:
**contratos ajenos votando sobre muestras**, cuya palanca se agotó porque
operaba sobre los SELECTORES (medido: 93% de los checks ya eran de selector
obligatorio, palanca 7%).

Esto es otra cosa y ataca el otro lado del mismo hallazgo:

- no hay contratos ajenos: cada contrato se poda **a sí mismo**;
- no se vota qué muestra es buena: se decide **qué CHECK sobra**;
- y opera sobre los **VALORES**, que es exactamente donde el repo MIDIÓ que
  viven los inventos.

Si el resultado es un KILL, se firma con la misma tinta.

## El dato que lo motiva (medido, no supuesto)

Del reconocimiento de esta tarde sobre lo que ya hay en disco:

| | |
|---|---|
| checks únicos con ≥2 páginas sanas | **548** |
| **fallan en TODAS las páginas sanas** (candidato inventado) | **186** |
| pasan en todas (candidato correcto) | 346 |
| mixtos | 16 |
| de los 186, con selector legítimo (`oblig=True`) | **168** |

Es decir: **el 34% de los checks del contrato autogenerado falla contra
páginas que el juez a mano aprueba**, y en el 90% de esos casos el selector
era correcto — la invención está en el VALOR. Eso es la premisa de la semana,
por fin cuantificada por check y no por agregado.

## Qué se construye

`scripts/b2_poda_checks.py`. Sobre las corridas ya congeladas, sin generar
nada nuevo:

1. Para cada ensayo (tarea × réplica) con K muestras y el contrato generado
   de cada una, se recupera la matriz **check × muestra** ya ejecutada.
2. Se marca **PODADO** todo check que falle en las K muestras del ensayo.
3. Se recomputa el veredicto del contrato **sin** los checks podados.
4. Se compara el contrato CRUDO contra el PODADO como juez y como selector.

**No se ejecuta nada nuevo en Playwright si la matriz ya está en disco**; si
falta, se re-ejecuta por replay (cero GPU, es lo que ya hace
`b2_fn_por_tipo.py`).

## Los dos modos de fallo de esta idea, nombrados ANTES de medir

**(a) CO-FAILURE.** Si las K muestras comparten el mismo fallo, el check
CORRECTO que lo detecta falla en las K y se poda: el contrato deja de ver
justo el fallo que compartían. Esto sube DEJA_PASAR. Es el riesgo principal
y hay una medición previa que lo acota: el consenso conductual encontró
co-failure en **3 de 24 ensayos**.

**(b) VACUIDAD.** Podar demasiado deja un contrato que aprueba cualquier
cosa — el pecado que ya costó un descarte en producción (7/24 contratos
aprobaban con 0 críticos). Regla pre-fijada: **si tras podar quedan 0 checks
críticos, el ensayo es NO_CONCLUYENTE**, nunca APROBADO. Y se reporta
siempre cuántos checks se podaron y cuántos ensayos quedaron vacíos.

## Métricas y umbrales (PRE-REGISTRADOS)

Ground truth: `estricto` (contrato original ∧ held-out a mano) de
`b2_bon_heldout` — **96 muestras, 72 sanas / 24 rotas**, el único corpus del
repo con ambas clases bien pobladas.

Etiquetas del repo, no las invertidas:

| métrica | definición |
|---|---|
| **ACUSA_SANOS** | muestras GT-sanas que el contrato reprueba |
| **DEJA_PASAR** | muestras GT-rotas que el contrato aprueba |

| brazo | qué es |
|---|---|
| **CRUDO** | el contrato autogenerado tal cual (la línea base viva del sistema) |
| **PODADO** | el mismo contrato sin los checks de fallo unánime |

La comparación es **APAREADA sobre las mismas muestras**, que es la única
evidencia admisible aquí (±34 pts de varianza entre corridas ya medida).

| resultado | veredicto |
|---|---|
| ACUSA_SANOS baja ≥15 pts **y** DEJA_PASAR no sube más de 5 pts | **VIVE** |
| ACUSA_SANOS baja ≥15 pts pero DEJA_PASAR sube 6-15 pts | **GRIS**: se reporta el intercambio y se decide por su uso como selector |
| ACUSA_SANOS baja <15 pts | **KILL**: la poda no arregla lo que venía a arreglar |
| **DEJA_PASAR sube >15 pts** | **KILL**: la poda ciega el examen (co-failure domina) |

Secundarias obligatorias: nº de checks podados (total y por ensayo), ensayos
que quedan sin críticos, y la matriz de acuerdo entre "podado por fallo
unánime" y la etiqueta débil del reconocimiento (186/346/16).

**Y una co-primaria como SELECTOR**, que es para lo que serviría de verdad:
sobre los mismos ensayos, cuántas veces el contrato podado elige una muestra
estricta donde el crudo no (RESCATA) y cuántas al revés (ESTROPEA).

## Lo que este diseño NO puede demostrar

- **La poda no puede inventar señal que no esté en las muestras.** Si las K
  son todas malas, ningún criterio interno lo va a saber.
- El corpus son **4 enunciados** (buscaminas, carrito_stock, hoja_calculo,
  kanban). Un resultado aquí no generaliza a tareas nuevas por sí solo: es
  una condición necesaria barata, no una demostración.
- La etiqueta débil del reconocimiento **confunde tres cosas**: valor
  inventado, check correcto que las referencias no cubren, y **ruido puro de
  API** (`texto` sobre un `<input>` falla 24/24 porque `innerText` de un
  campo es siempre vacío). La poda se llevará por delante los tres. Eso está
  bien para el rendimiento, pero **impide leer el resultado como "se podaron
  los inventos"**: se leerá como "se podaron los checks que ninguna página
  sana pasa", que es lo que literalmente hace.

## RESULTADO

*(se rellena después; nada de esto se toca retroactivamente)*

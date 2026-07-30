# PREREG — Ejecución en el bucle, iteración 2: arreglar el INSTRUMENTO

**Fecha:** 2026-07-29 ~20:30, sesión tarde-noche 29. **Escrito ANTES de
implementar y ANTES de correr.** Itera sobre el KILL de la iteración 1
(PREREG_EJECUCION_BUCLE_20260729, RESULTADO: 6/23, FN 17/19) usando la
auditoría de dictámenes crudos que ese prereg dejó pre-declarada — y que
REFUTÓ mi primera lectura del mecanismo.

## Lo que la auditoría estableció (datos, no intuición)

Los 21 dictámenes INCORRECTO auditados **citan reglas REALES del
enunciado**; el juicio no inventa. Falla la EVIDENCIA que recibe:

1. La sonda no ejecuta la secuencia que declara (una sonda titulada
   "añadir el mismo producto dos veces" ejecutó UN click; el juez condenó
   "sigue 1 en lugar de 2").
2. El snapshot es ciego al estado que la regla exige (`disabled` se
   "verificó" con un selector CSS inválido y con el texto del botón).
3. El juicio no advierte que la evidencia no cubre la regla (debió decir
   NO_CONCLUYENTE, dijo INCORRECTO).

**Los tres son del INSTRUMENTO, no del pensador.** Eso distingue esta
iteración de los 4 KILL del contrato ciego (que eran de prompt) y es la
razón pre-declarada para pagar una vuelta más en vez de cerrar la vía.

## Los tres cambios (y nada más — sin tocar el aislamiento ni el corpus)

- **C1 — snapshot con estado:** por elemento observado se añaden
  `disabled`, `className` y `dataset` (además de n / texto / value /
  checked). Es lo que las reglas del banco exigen comprobar.
- **C2 — repeticiones declaradas y verificadas:** el prompt de sondeo pide
  que cada sonda declare `veces` por acción cuando la regla lo necesita
  (llegar a un tope, acumular); el harness **expande** esas repeticiones
  al ejecutar y las refleja en el transcript ("click ×3"). Si una sonda
  declara una regla de acumulación con una sola acción, el transcript lo
  muestra explícito.
- **C3 — NO_CONCLUYENTE obligatorio:** el prompt de juicio exige que, si
  las acciones ejecutadas no ejercitan la regla citada, el dictamen sea
  NO_CONCLUYENTE y no INCORRECTO. Se refuerza con la lista de acciones ya
  presente en el transcript.

Todo lo demás IDÉNTICO a la it.1: mismo corpus (24 páginas, 19/5), mismo
control ciego concurrente, mismo aislamiento (idea + inventario para
sondear; idea + observaciones para juzgar), misma regla de veredicto
(REPRUEBA ⇔ ≥1 INCORRECTO), mismos presupuestos.

## Umbrales (fijados ahora; los MISMOS de la it.1, sin relajar)

| lectura | veredicto |
|---|---|
| aciertos ≥ 16/24 **y** FP ≤ 1/5 | **VIVA**: validación obligatoria (96 muestras del BoN + banco fácil) antes de declarar o cablear |
| aciertos 12–15/24 | GRIS: el instrumento mejoró pero no basta; se reporta el desglose FN por causa |
| aciertos ≤ 11/24 | **KILL DEFINITIVO de la vía "ejecución en el bucle"** — con el instrumento arreglado y el juicio citando reglas reales, un fallo aquí dice que el marco no da señal, y la vía se cierra como se cerró el contrato ciego |

- Control ciego concurrente fuera de 6–12/24 ⇒ lectura direccional.
- Comparación con la it.1 (6/23) es la referencia interna: el mismo
  corpus, el mismo día. Una mejora <+3 aciertos no se considera señal del
  arreglo (ruido del juez + varianza de generación de sondas).
- Secundarias: FN/19, FP/5, nº de dictámenes NO_CONCLUYENTE (debe SUBIR
  si C3 funciona), nº de sondas con repeticiones declaradas (C2), y
  cuántos FN de la it.1 se convierten en aciertos.

## Piloto

No hay piloto de aptitud: la aptitud ya está demostrada (it.1 ejecutó
sondas en 7/8 y 23/24). Se corre el bloque directo.

## Presupuesto

24 páginas × (2 llamadas LLM + Playwright + contrato de control) ≈ **60-80
min**. Corre DESPUÉS del experimento de validez del instrumento
(lazo-vs-replay) si el reloj lo permite.

## Revisión

1 agente adversarial de los tres cambios (que no alteren el aislamiento ni
la comparabilidad con la it.1) ANTES de correr. Enmiendas con fecha aquí.

# BORRADOR de prereg — Rescate de la espiral de contenido-vacío (P4)

**Estado: BORRADOR, 2026-07-29 (sesión matinal). Sin umbrales cerrados ni
revisión; NO corre hasta convertirse en PREREG con fecha.** Prioridad 4 del
dueño en esta sesión; la GPU la consumieron fase 1 + fase 2 de la sonda.

## El fenómeno (medido)

~5-8% de las generaciones del lazo con gpt-oss mueren en espiral de
razonamiento: el pensamiento consume ÍNTEGRO el presupuesto (finish=length,
22-53k chars de razonamiento) y el contenido sale vacío. En el BoN mata
muestras enteras (s4 nunca fue elegida en el gate; 12/96 muestras del
experimento llegaron por el fallback); en el modo cableado sin fallback es
~5% de muestras perdidas. Prior fuerte
([[presupuesto-tokens-razonamiento]]): reasoning_effort=low cierra la
espiral 2/2 en las sondas de reparar_web (~3000 tokens, 25 s) y la línea
"Reasoning: low" del system NO hace nada (3/3).

## La palanca propuesta

En el camino de generación del lazo (donde hoy una respuesta vacía degrada
al siguiente fallback): UN reintento inmediato del MISMO prompt con
`reasoning_effort="low"` cuando la respuesta llega vacía ("" con server
sano). Env-gated (`COGNIA_RESCATE_ESPIRAL=1`), default OFF.

## Diseño de medición (dos opciones, decidir en el prereg final)

- **Opción A (A/B clásico):** el evento es raro (5-8%) → para ~6 eventos
  por brazo hacen falta ~100 generaciones/brazo. Caro (~5 h GPU). Solo
  tiene sentido colgado de otra corrida grande.
- **Opción B (sombra instrumentada, recomendada):** encender el modo en
  las corridas nocturnas normales con telemetría propia: contador de
  espirales detectadas, reintentos disparados, rescates exitosos (contenido
  no vacío que parsea), segundos extra. Sin brazo control: la métrica es
  condicional al evento (¿qué fracción de espirales rescata el reintento?)
  y el prior 2/2 la hace creíble. Adopción si rescate ≥ 60% sobre ≥8
  eventos y coste cero en celdas sin espiral (el reintento solo dispara
  con "" — verificar que no dispara con respuestas sanas).

## Riesgos a cerrar en el prereg final

- El reintento a effort=low puede producir páginas PEORES (menos
  pensamiento): medir estricto de las rescatadas contra la tasa base del
  brazo, no solo "no vacío".
- Doble espiral (el reintento también muere): cap a UN reintento, contado.
- Interacción con presupuesto de pared: el reintento vive dentro del mismo
  presupuesto de celda.

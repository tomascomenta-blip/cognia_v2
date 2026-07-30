# PREREG — Consenso CONDUCTUAL sin contrato: ¿la mayoría entre muestras es señal?

**Fecha:** 2026-07-29 ~23:00, sesión tarde-noche 29→30. **Escrito ANTES de
implementar y ANTES de correr.** Séptima vía de señal para tareas nuevas,
y **genuinamente distinta de las seis muertas** — la diferencia está
declarada abajo porque la regla pre-fijada del dueño ("no más variantes de
votos") obliga a justificarla.

## Por qué esta vía es distinta de todo lo que ya murió

| vía muerta | qué votaba/decidía | por qué esta NO es eso |
|---|---|---|
| Contrato ciego ×4 KILL | aserciones con VALORES esperados escritos por el pensador | aquí **no hay aserciones ni valores esperados** |
| Consenso de contratos ajenos ×2 vueltas | contratos de las hermanas como rankers | aquí **no hay contratos**, ni propios ni ajenos |
| Ejecución en el bucle ×2 iteraciones | el pensador DICTAMINA sobre lo observado | aquí **no hay LLM en el lazo de decisión**: decide el harness por mayoría |

Lo que se compara es **comportamiento observado contra comportamiento
observado**: se ejecuta la MISMA secuencia de acciones en las K muestras
del ensayo y se elige la que se comporta como la mayoría.

## Por qué es plausible AHORA (y no antes)

Las dos mediciones de hoy la habilitan:
1. **El juez es determinista** (0/24 no unánimes, checks idénticos): dos
   páginas que se comportan igual dan la misma firma; la firma es señal,
   no ruido de instrumento.
2. **La dispersión es del GENERADOR** (54% de reproducibilidad por celda):
   las K muestras difieren de verdad, así que hay una mayoría que formar.

Riesgo principal, declarado: **co-failure** — si 3 de 4 muestras comparten
el mismo bug, la mayoría bendice el bug (Co-Failure Ceiling, β=0.079 en
código evaluado por ejecución, ya citado en META). Es exactamente lo que
la medición decide.

## Diseño (datos CONGELADOS, cero generación de páginas)

- Corpus: las **96 muestras de b2_bon_heldout** (24 ensayos × 4), con
  `estricto` congelado (72 True / 24 False) y sus HTML en disco. Es el
  mismo corpus donde el selector held-out capturó +7 (el techo a batir).
- **Sondeo por TAREA (no por página):** una única secuencia de acciones
  por tarea, generada por el pensador a partir del ENUNCIADO y de los
  selectores que el propio enunciado declara obligatorios — sin ver
  ninguna página, sin inventario de DOM. 4 llamadas LLM en total. Se
  guarda cruda y se congela ANTES de ejecutar nada.
- **Firma conductual:** en cada muestra se ejecuta la secuencia y se
  registra, tras cada paso, el estado de los selectores observados
  (n, texto/valor, disabled, clases — el snapshot de la it.2). La firma
  es la tupla ordenada de esos estados.
- **Selección por mayoría:** dentro de cada ensayo se agrupan las 4
  firmas; gana el grupo más grande; dentro del grupo, la `s` menor.
  Empate entre grupos del mismo tamaño → `s` menor global (equivale al
  control, para no regalar señal).
- Resultado del elegido = su `estricto` CONGELADO. Control = s1. Neto =
  gana − pierde en discordantes.

## Métricas y umbrales (fijados ahora; mismos que el consenso de contratos)

| neto sobre 24 ensayos | veredicto |
|---|---|
| ≥ +5 | **VÍA VIVA**: primera señal autogenerada útil; validación obligatoria (banco fácil + prereg aparte) antes de declarar o cablear |
| +3..+4 | moderada: se reporta, sin adopción (misma marca que el consenso de contratos: +3) |
| ≤ +2 | **KILL** — y con él, el consenso entre muestras queda cerrado en TODAS sus formas (con contrato y sin él) |

- Techo de referencia: el selector held-out capturó **+7** sobre este
  mismo corpus; el margen disponible es ése.
- **Ancla de validez pre-declarada:** la secuencia debe ejecutarse con al
  menos una acción efectiva en ≥3 de las 4 muestras en ≥18 de los 24
  ensayos. Si no, la medición es direccional (el instrumento no aplica al
  corpus).
- Secundarias: nº de ensayos donde las 4 firmas son distintas (sin
  mayoría); nº donde la mayoría contiene una muestra reprobada
  (co-failure explícito); coincidencia con el selector held-out; tamaño
  medio del grupo mayoritario.

## Presupuesto

4 llamadas LLM (~2 min) + 96 ejecuciones Playwright (~25-40 min) ≈ **45
min**. Cero generación de páginas.

## Revisión

1 agente adversarial (diseño + implementación) ANTES de ejecutar las 96,
con encargo explícito de auditar (a) que la secuencia por tarea no
codifique conocimiento del outcome, (b) que la firma no sea trivialmente
idéntica ni trivialmente única, (c) el manejo de empates. Enmiendas aquí.

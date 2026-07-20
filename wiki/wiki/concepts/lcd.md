---
title: LCD — creador de escenas AI-nativo
type: concept
tags: [lcd, escenas, imagenes, oraculo, tools]
updated: 2026-07-16
---

# LCD (creador de escenas)

→ [[index]]

## Que es

`cognia/lcd/` — biblioteca de herramientas AI-NATIVAS (para IA, no para
humanos) de creacion de escenas/imagenes: scene.py, planner.py,
renderer.py (PNG real), arbiter.py, physics.py, animation.py. Las tools
del agente viven en `cognia/lcd/tools_lcd.py`: `escena_crear`,
`escena_editar`, `escena_consultar`, `render_aprox` — todas con ORACULO
determinista cero-LLM. Empaquetado en el wheel (viaja a PyPI).

## Arbitro por etapa

`arbiter.py` — atribucion de fallo POR ETAPA con oraculo: 24/24 = 100%
culpas balanceadas, vs 31% del arbitro-LLM del paper (colapsaba a
"culpar al codigo"). AG-ARB falso el arbitro del paper (2026-07-03).

## Uso real

El 3B elige `escena_crear` con few-shot (e2e real); el planner-LLM rutea
lenguaje natural a las tools. `/crear` (programas) es otro sistema
([[entities/agente]] + program_creator).

## Links

- [[entities/agente]]

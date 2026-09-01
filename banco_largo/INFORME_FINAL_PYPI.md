# Banco de tareas largas -- comparacion

Ronda A: r1_baseline (10 tareas)   Ronda B: r5_pypi_limpio (10 tareas)   Comparables: 10

| Metrica | r1_baseline | r5_pypi_limpio |
|---|---|---|
| tareas evaluadas | 10 | 10 |
| tareas completadas | 2 | 2 |
| tareas parciales | 0 | 0 |
| tareas truncadas | 10 | 10 |
| productos funcionales (func>=0,8) | 2 | 2 |
| productos incompletos | 1 | 2 |
| productos muertos (func=0) | 7 | 6 |
| tests superados / totales | 36 / 106 | 50 / 108 |
| tasa de tests | 0.340 | 0.463 |
| nota global media | 0.417 | 0.508 |
|   A completitud | 0.633 | 0.817 |
|   B funcionalidad | 0.250 | 0.270 |
|   C calidad | 0.862 | 0.873 |
|   D robustez | 0.300 | 0.400 |
|   E integridad | 0.200 | 0.400 |
|   F entregabilidad | 0.426 | 0.487 |
|   G verificacion propia | 0.682 | 0.727 |
|   H regresiones | 0.200 | 0.300 |
| errores en tool calls | 9 | 17 |
| errores recuperados | 1 | 1 |
| duracion media (s) | 475.93 | 441.69 |
| tokens medios por tarea | 120312.7 | 275067.0 |
| pasos medios | 8.600 | 16.700 |
| tool calls medias | 10.000 | 16.800 |
| el agente dijo 'completo' | 0 | 2 |

## Detalle ronda A

| Tarea | d | veredicto | global | A | B | trunc | pasos | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| ark-supervivencia | 5 | truncado | 0.09 | 0.0 | 0.0 | presupuesto_pared,tope_salida | 3 | 43824 | 480 |
| herramienta-diff | 4 | truncado | 0.11 | 0.0 | 0.0 | presupuesto_pared,tope_salida | 4 | 48876 | 480 |
| juego-tower-defense | 4 | truncado | 0.68 | 1.0 | 0.5 | presupuesto_pared,tope_salida | 7 | 98151 | 480 |
| multi-componente | 5 | truncado | 0.20 | 0.3333 | 0.0 | presupuesto_pared,tope_salida | 7 | 90859 | 480 |
| node-cli-generador | 3 | completado | 0.97 | 1.0 | 1.0 | tope_salida,bucle_detectado | 15 | 196840 | 475 |
| py-cli-tareas | 3 | truncado | 0.24 | 0.6667 | 0.0 | presupuesto_pared,tope_salida | 2 | 25530 | 480 |
| py-compilador | 5 | truncado | 0.18 | 0.3333 | 0.0 | presupuesto_pared,tope_salida | 9 | 98737 | 480 |
| py-servidor-api | 4 | truncado | 0.35 | 1.0 | 0.0 | estancamiento,tope_salida,estancado_sin_progreso | 13 | 216020 | 443 |
| web-dashboard | 3 | truncado | 0.37 | 1.0 | 0.0 | presupuesto_pared,tope_salida | 10 | 136225 | 480 |
| web-kanban | 4 | completado | 0.96 | 1.0 | 1.0 | presupuesto_pared,tope_salida | 16 | 248065 | 480 |

## Detalle ronda B

| Tarea | d | veredicto | global | A | B | trunc | pasos | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| ark-supervivencia | 5 | truncado | 0.68 | 1.0 | 0.2 | presupuesto_pared | 14 | 250477 | 480 |
| herramienta-diff | 4 | truncado | 0.22 | 0.5 | 0.0 | presupuesto_pared | 11 | 164152 | 480 |
| juego-tower-defense | 4 | truncado | 0.70 | 1.0 | 0.5 | estancamiento,estancado_sin_progreso | 26 | 504246 | 402 |
| multi-componente | 5 | truncado | 0.38 | 0.6667 | 0.0 | presupuesto_pared | 9 | 121714 | 480 |
| node-cli-generador | 3 | completado | 0.98 | 1.0 | 1.0 | estancamiento,tope_salida,estancado_sin_progreso | 26 | 341303 | 442 |
| py-cli-tareas | 3 | completado | 1.00 | 1.0 | 1.0 | estancamiento,estancado_sin_progreso | 25 | 561798 | 442 |
| py-compilador | 5 | truncado | 0.19 | 0.3333 | 0.0 | presupuesto_pared | 30 | 512178 | 480 |
| py-servidor-api | 4 | truncado | 0.31 | 1.0 | 0.0 | contexto,tool_call_cortado,tope_salida,error_backend | 4 | 22729 | 248 |
| web-dashboard | 3 | truncado | 0.27 | 0.6667 | 0.0 | presupuesto_pared,tope_salida | 9 | 108012 | 480 |
| web-kanban | 4 | truncado | 0.36 | 1.0 | 0.0 | estancamiento,presupuesto_pared | 13 | 164061 | 480 |
# Banco de tareas largas -- comparacion

Ronda A: r2_mejorado (10 tareas)   Ronda B: r3_pared (10 tareas)   Comparables: 10

| Metrica | r2_mejorado | r3_pared |
|---|---|---|
| tareas evaluadas | 10 | 10 |
| tareas completadas | 0 | 1 |
| tareas parciales | 0 | 0 |
| tareas truncadas | 10 | 10 |
| productos funcionales (func>=0,8) | 1 | 2 |
| productos incompletos | 4 | 3 |
| productos muertos (func=0) | 5 | 5 |
| tests superados / totales | 46 / 108 | 46 / 108 |
| tasa de tests | 0.426 | 0.426 |
| nota global media | 0.483 | 0.474 |
|   A completitud | 0.783 | 0.633 |
|   B funcionalidad | 0.284 | 0.334 |
|   C calidad | 0.877 | 0.845 |
|   D robustez | 0.300 | 0.300 |
|   E integridad | 0.200 | 0.400 |
|   F entregabilidad | 0.582 | 0.492 |
|   G verificacion propia | 0.731 | 0.720 |
|   H regresiones | 0.300 | 0.300 |
| errores en tool calls | 23 | 16 |
| errores recuperados | 1 | 1 |
| duracion media (s) | 457.95 | 403.42 |
| tokens medios por tarea | 257767.2 | 243161.2 |
| pasos medios | 15.700 | 15.500 |
| tool calls medias | 16.000 | 14.200 |
| el agente dijo 'completo' | 0 | 0 |

## Detalle ronda A

| Tarea | d | veredicto | global | A | B | trunc | pasos | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| ark-supervivencia | 5 | truncado | 0.21 | 0.3333 | 0.0 | contexto,tool_call_cortado,tope_salida,error_backend | 7 | 42541 | 316 |
| herramienta-diff | 4 | truncado | 0.20 | 0.5 | 0.0 | presupuesto_pared | 4 | 39691 | 480 |
| juego-tower-defense | 4 | truncado | 0.61 | 1.0 | 0.25 | presupuesto_pared | 14 | 198092 | 480 |
| multi-componente | 5 | truncado | 0.35 | 1.0 | 0.0 | presupuesto_pared | 9 | 120693 | 480 |
| node-cli-generador | 3 | truncado | 0.90 | 1.0 | 0.7143 | estancamiento,estancado_sin_progreso | 41 | 796667 | 441 |
| py-cli-tareas | 3 | truncado | 0.84 | 0.6667 | 0.8889 | estancamiento,estancado_sin_progreso | 22 | 389847 | 461 |
| py-compilador | 5 | truncado | 0.20 | 0.3333 | 0.0 | estancamiento,presupuesto_pared | 18 | 240931 | 480 |
| py-servidor-api | 4 | truncado | 0.38 | 1.0 | 0.0 | estancamiento,presupuesto_pared | 15 | 281056 | 480 |
| web-dashboard | 3 | truncado | 0.65 | 1.0 | 0.7333 | estancamiento,presupuesto_pared | 20 | 391016 | 480 |
| web-kanban | 4 | truncado | 0.49 | 1.0 | 0.25 | presupuesto_pared | 7 | 77138 | 480 |

## Detalle ronda B

| Tarea | d | veredicto | global | A | B | trunc | pasos | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| ark-supervivencia | 5 | truncado | 0.27 | 0.6667 | 0.0 | contexto,presupuesto_pared | 11 | 185007 | 480 |
| herramienta-diff | 4 | truncado | 0.07 | 0.0 | 0.0 | contexto,tool_call_cortado,tope_salida,error_backend | 4 | 23525 | 296 |
| juego-tower-defense | 4 | truncado | 0.69 | 1.0 | 0.5 | presupuesto_pared | 18 | 310529 | 478 |
| multi-componente | 5 | truncado | 0.35 | 0.6667 | 0.2222 | presupuesto_pared | 13 | 192938 | 480 |
| node-cli-generador | 3 | completado | 0.98 | 1.0 | 1.0 | estancamiento,estancado_sin_progreso | 35 | 562178 | 414 |
| py-cli-tareas | 3 | truncado | 0.84 | 0.6667 | 0.8889 | estancamiento,estancado_sin_progreso | 22 | 381814 | 297 |
| py-compilador | 5 | truncado | 0.25 | 0.6667 | 0.0 | presupuesto_pared | 12 | 139511 | 480 |
| py-servidor-api | 4 | truncado | 0.46 | 1.0 | 0.0 | contexto,tool_call_cortado,tope_salida,error_backend | 5 | 30295 | 287 |
| web-dashboard | 3 | truncado | 0.71 | 0.6667 | 0.7333 | estancamiento,presupuesto_pared | 30 | 565889 | 480 |
| web-kanban | 4 | truncado | 0.11 | 0.0 | 0.0 | contexto,tool_call_cortado,tope_salida,error_backend | 5 | 39926 | 339 |
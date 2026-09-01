# Banco de tareas largas -- comparacion

Ronda A: r1_baseline (10 tareas)   Ronda B: r2_mejorado (10 tareas)   Comparables: 10

| Metrica | r1_baseline | r2_mejorado |
|---|---|---|
| tareas evaluadas | 10 | 10 |
| tareas completadas | 2 | 0 |
| tareas parciales | 0 | 0 |
| tareas truncadas | 10 | 10 |
| productos funcionales (func>=0,8) | 2 | 1 |
| productos incompletos | 1 | 4 |
| productos muertos (func=0) | 7 | 5 |
| tests superados / totales | 36 / 106 | 46 / 108 |
| tasa de tests | 0.340 | 0.426 |
| nota global media | 0.417 | 0.483 |
|   A completitud | 0.633 | 0.783 |
|   B funcionalidad | 0.250 | 0.284 |
|   C calidad | 0.862 | 0.877 |
|   D robustez | 0.300 | 0.300 |
|   E integridad | 0.200 | 0.200 |
|   F entregabilidad | 0.426 | 0.582 |
|   G verificacion propia | 0.682 | 0.731 |
|   H regresiones | 0.200 | 0.300 |
| errores en tool calls | 9 | 23 |
| errores recuperados | 1 | 1 |
| duracion media (s) | 475.93 | 457.95 |
| tokens medios por tarea | 120312.7 | 257767.2 |
| pasos medios | 8.600 | 15.700 |
| tool calls medias | 10.000 | 16.000 |
| el agente dijo 'completo' | 0 | 0 |

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
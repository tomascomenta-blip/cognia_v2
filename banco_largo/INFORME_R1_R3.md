# Banco de tareas largas -- comparacion

Ronda A: r1_baseline (10 tareas)   Ronda B: r3_pared (10 tareas)   Comparables: 10

| Metrica | r1_baseline | r3_pared |
|---|---|---|
| tareas evaluadas | 10 | 10 |
| tareas completadas | 2 | 1 |
| tareas parciales | 0 | 0 |
| tareas truncadas | 10 | 10 |
| productos funcionales (func>=0,8) | 2 | 2 |
| productos incompletos | 1 | 3 |
| productos muertos (func=0) | 7 | 5 |
| tests superados / totales | 36 / 106 | 46 / 108 |
| tasa de tests | 0.340 | 0.426 |
| nota global media | 0.417 | 0.474 |
|   A completitud | 0.633 | 0.633 |
|   B funcionalidad | 0.250 | 0.334 |
|   C calidad | 0.862 | 0.845 |
|   D robustez | 0.300 | 0.300 |
|   E integridad | 0.200 | 0.400 |
|   F entregabilidad | 0.426 | 0.492 |
|   G verificacion propia | 0.682 | 0.720 |
|   H regresiones | 0.200 | 0.300 |
| errores en tool calls | 9 | 16 |
| errores recuperados | 1 | 1 |
| duracion media (s) | 475.93 | 403.42 |
| tokens medios por tarea | 120312.7 | 243161.2 |
| pasos medios | 8.600 | 15.500 |
| tool calls medias | 10.000 | 14.200 |
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
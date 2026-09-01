# Banco de tareas largas -- comparacion

Ronda A: r1_baseline (10 tareas)   Ronda B: r4_pypi (9 tareas)   Comparables: 9

| Metrica | r1_baseline | r4_pypi |
|---|---|---|
| tareas evaluadas | 9 | 9 |
| tareas completadas | 2 | 0 |
| tareas parciales | 0 | 0 |
| tareas truncadas | 9 | 9 |
| productos funcionales (func>=0,8) | 2 | 0 |
| productos incompletos | 1 | 2 |
| productos muertos (func=0) | 6 | 7 |
| tests superados / totales | 35 / 95 | 32 / 97 |
| tasa de tests | 0.368 | 0.330 |
| nota global media | 0.443 | 0.418 |
|   A completitud | 0.667 | 0.852 |
|   B funcionalidad | 0.278 | 0.100 |
|   C calidad | 0.877 | 0.840 |
|   D robustez | 0.333 | 0.413 |
|   E integridad | 0.222 | 0.222 |
|   F entregabilidad | 0.462 | 0.362 |
|   G verificacion propia | 0.672 | 0.631 |
|   H regresiones | 0.222 | 0.000 |
| errores en tool calls | 9 | 15 |
| errores recuperados | 1 | 0 |
| duracion media (s) | 475.467 | 439.078 |
| tokens medios por tarea | 122710.0 | 219438.556 |
| pasos medios | 8.556 | 12.778 |
| tool calls medias | 10.111 | 12.333 |
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
| ark-supervivencia | 5 | truncado | 0.69 | 1.0 | 0.4 | contexto,presupuesto_pared | 15 | 266786 | 480 |
| herramienta-diff | 4 | truncado | 0.22 | 0.5 | 0.0 | estancamiento,presupuesto_pared | 12 | 196533 | 480 |
| juego-tower-defense | 4 | truncado | 0.64 | 1.0 | 0.5 | estancamiento,presupuesto_pared,estancado_sin_progreso | 32 | 624807 | 480 |
| multi-componente | 5 | truncado | 0.50 | 0.6667 | 0.0 | presupuesto_pared | 11 | 152121 | 480 |
| node-cli-generador | 3 | truncado | 0.25 | 0.5 | 0.0 | estancamiento | 0 | 0 | 137 |
| py-cli-tareas | 3 | truncado | 0.38 | 1.0 | 0.0 | estancamiento,estancado_sin_progreso | 21 | 385539 | 453 |
| py-servidor-api | 4 | truncado | 0.36 | 1.0 | 0.0 | presupuesto_pared,tope_salida | 4 | 52377 | 480 |
| web-dashboard | 3 | truncado | 0.36 | 1.0 | 0.0 | presupuesto_pared,tope_salida | 9 | 119627 | 480 |
| web-kanban | 4 | truncado | 0.36 | 1.0 | 0.0 | presupuesto_pared | 11 | 177157 | 480 |
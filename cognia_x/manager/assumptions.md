# assumptions.md — supuestos explícitos de Cognia-X

> Cada supuesto tiene estado {no-verificado, apoyado, refutado}. Un supuesto no es un hecho
> hasta que la evidencia lo apoya. Hacerlos explícitos permite atacarlos.

| id | Supuesto | Estado | Nota / evidencia |
|----|----------|--------|------------------|
| A-001 | La inferencia autoregresiva en CPU es **memory-bandwidth-bound**, no compute-bound. | no-verificado | A medir (exp003). Reordena qué optimizaciones importan (cuantización > FLOPs). |
| A-002 | El contexto largo (L grande) es un caso de uso relevante para el objetivo. | no-verificado | Si solo importara L pequeño, el coste O(L²) sería tolerable y exp001 perdería fuerza. |
| A-003 | Un mezclador sub-cuadrático **puro** puede igualar la calidad de la atención. | **refutado (parcial)** | exp002: el lineal puro NO iguala el recall (acotado por estado d²); full ~1.0. Un **híbrido** podría (H-MEZ-4, a probar). |
| A-004 | La asíntota predice el coste real en CPU. | **refutado (parcial)** | exp001: el SSM O(L) en bucle Python pierde contra el lineal O(L·d²) vectorizado. El factor constante manda. |
| A-005 | float32 es representativo; los hallazgos de coste se mantienen en int8/int4. | no-verificado | A verificar al estudiar cuantización (dimensión CPU-bottleneck). |
| A-006 | Se puede aprender localmente y fusionar conocimiento sin reentrenar la base ni olvidar. | no-verificado | Núcleo de la prioridad #2; a investigar (model merging / LoRA / replay). |
| A-007 | torch-cpu/numpy en `venv312` bastan para todos los experimentos del lab. | apoyado | exp001 corrió sin fricción; ambos disponibles. |

> Supuestos adicionales del ciclo-1 (workflow) se añadirán/actualizarán aquí.

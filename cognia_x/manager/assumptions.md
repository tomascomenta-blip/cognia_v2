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

## Ciclo-1 (workflow) — supuestos con estado

| id | Supuesto | Estado | Nota |
|----|----------|--------|------|
| A-008 | Decode batch=1 en CPU es memory-bandwidth-bound; tok/s ~ banda/bytes-leídos-por-token. | **apoyado (medido en i3-10110U)** | vault/Gotchas: spec decode 5× más lento (draft compite por banda), 3 hilos > 4, techo ~8 tok/s 3B Q4_K_M. Cornerstone confirmado en el target + exp004. |
| A-009 | SWA (Gemma-3 5:1, W~1024) reduce KV de O(L) a ~O(W) sin degradar perplejidad material. | apoyado | H-SEQ-3 holds=true (producción). |
| A-010 | Ratio recurrente:atención óptimo en 3:1–4:1; 6:1 es el borde que degrada recall. | apoyado | arXiv:2507.06457. |
| A-011 | BLT/patching por entropía no recupera overhead a 1-3B (gana solo a 7B+). | apoyado | H-REP-2. |
| A-012 | FedAvg ingenuo de A,B por separado es matemáticamente inexacto (crece con heterog./DP). | apoyado | H-CF-2; bug real en `federated_store.py`. |
| A-013 | RAG document-level ≥ fine-tune para hechos nuevos, cero olvido, < coste que kNN-LM/token. | apoyado | H-CF-3. |
| A-014 | Un ternario b1.58 nativo bate a un Q4 denso de **calidad comparable** sin pérdida. | **refutado** | H-BIT-1; los 2-6× son kernel-vs-kernel; BitNet pierde ~12% MMLU. |
| A-015 | T-MAC condiciona su ventaja a que las LUTs quepan en **L2**. | **refutado** | el mecanismo real es registros/L1 (H-LUT-1). |
| A-016 | kNN-LM por-token es viable en el CPU objetivo (búsqueda ANN por token). | **refutado** | retrieval memory-bound; document-level sí, por-token no. |
| A-017 | El gate de auto-mejora de Cognia es held-out (señal de rollback fiable). | **refutado** | evaluador CIRCULAR sobre la misma DB que se auto-escribe (H-SELF-2). |
| A-018 | El ahorro de banda de SSM/SWA se materializa con los kernels CPU ACTUALES de llama.cpp. | no-verificado | soporte inmaduro; riesgo de diseño. |
| A-019 | Las constantes numéricas (<30% hilos, ≥30% tok/s a 8K, break-even patching) se cumplen en ESTE CPU. | no-verificado | E1-E5 las confirman antes de comprometer diseño. |

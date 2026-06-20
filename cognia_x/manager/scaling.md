# scaling.md — escalabilidad de Cognia-X (medida, no asumida)

> §6 de la directiva: **todo componente nuevo documenta su escalabilidad o NO se acepta.** Este
> archivo consolida las constantes de escala MEDIDAS en el target (i3-10110U, ~2c/4t, sin GPU,
> memory-bandwidth-bound) y la disciplina de complejidad. Fuentes: `experiments.md`, `decision_log.md`,
> `hypotheses.md`. Append-only.

## Presupuesto físico del lab (la restricción que todo debe respetar)
- CPU 2 cores / 4 threads, sin CUDA. Decode batch=1 **memory-bandwidth-bound**, no compute-bound.
- Métrica maestra (**D-006**): **bytes movidos por token**, NO FLOPs. Una optimización que no baja
  bytes/token movidos no acelera el decode en este hardware.
- Hilos saturan a ~2 (exp004: 1→2 +11%, 3-4 peores). `torch.set_num_threads(3)` es el punto práctico.

## Constantes de escala medidas (tier-5, reproducibles con seed fijo)
| Eje | Resultado medido | Experimento | Implicación de escala |
|-----|------------------|-------------|------------------------|
| Mezcla de secuencia | lineal O(L) gana 3.5→70× a la atención full (L 128→4096); memoria full O(L²) | exp001 | el cuello cuadrático es real; el lineal escala plano en L |
| Recall del estado fijo | capacidad ~d²/32 (satura); cota EFECTIVA entrenada ≪ d² (~0.18) | exp002, exp009/010 | el estado fijo NO escala el recall con la carga → hace falta atención (D-007/D-CEIL-1) |
| Coste del híbrido | 3/24 capas full = ~12-15% del coste de full puro a L=8192 | exp005 | el híbrido escala ~como el lineal en L, con recall de atención |
| Ancho de banda | float32 ~2.2× float64 (bytes/peso); GB/s plano memory-bound | exp004 | bajar bytes/peso (cuantizar) es el lever de velocidad |
| lm_head O(V) | = 1 bloque transformer a V≈26k; head 1-10% del modelo a vocab ≤64k tied | exp006 | vocab moderado (~32-64k) es el punto dulce; 128-256k infla softmax |
| Precisión entera | int8 naïve 8-10× MÁS LENTO que float32 sin kernels | exp007 | baja precisión ahorra MEMORIA (4×), no cómputo automático; exige T-MAC/bitnet.cpp |

## Disciplina de complejidad (enforzada en el engine y los experimentos)
- Cada `cycleNN_*.py` y cada `expNNN/run.py` declara su presupuesto: tiempo O(·), espacio O(·),
  comportamiento CPU, multi-dispositivo. Ejemplo: el Investigation Engine es O(1) por registro escrito
  (append JSONL) y O(n) en `verify_no_loss` sobre su store; I/O-bound, store JSON portable y fusionable.
- exp011 (CYCLE 24) hizo explícito que el feature-map Taylor lleva la feature por token de O(dh) a
  O(dh²/2) y el estado recurrente a (dh²/2)² — por eso se acota a dh chico (d=24). El costo de escala
  de un kernel rico es real y se mide, no se asume.

## Pendiente (F-SCALE)
- *¿Qué se vuelve lento al crecer y por qué?* Medir, no asumir, por subsistema. Especializar módulos;
  reorganizar el conocimiento; evitar cómputo redundante (p.ej. el cache de índices de Taylor, CYCLE 24).
- Objetivo experimental de la directiva: arquitecturas donde **aumentar capacidad no degrade la
  velocidad proporcionalmente** (el híbrido es la primera apuesta medida; falta el stack entrenado real).

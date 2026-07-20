# contradictions.md — registro y clasificación de contradicciones de Cognia-X

> Principio de la directiva: una contradicción aparente NO se descarta — se REGISTRA y se clasifica.
> Taxonomía: **A** física real · **B** matemática real · **C** tecnológica actual · **D** suposición
> heredada · **E** hipótesis insuficientemente explorada · **F** alucinación conceptual.
> Manejo: A/B documentar+aproximar; C superar/buscar alternativa; **D atacar agresivamente**; E diseñar
> experimento; F eliminar y documentar por qué. Una "imposibilidad" solo vale si nombra cota + fuente.
> Append-only.

## C-01 — "Eficiencia (lineal O(L)) vs Recall (atención)" — RESUELTA (Tipo E → diseño)
- **Contradicción:** prioridad #1 (eficiencia) pide mezcla lineal O(L); el recall exacto pide atención
  O(L²). Chocan.
- **Clasificación:** Tipo E (hipótesis explorable), no contradicción real.
- **Resolución:** el **híbrido** (mayoría lineal + minoría atención) captura ambos — coste ~12-15% del
  full (exp005) con recall recuperado (exp006/CYCLE 6: lineal satura a np=8, el híbrido recupera).
  D-007/D-CEIL-1. El conflicto de prioridades se resolvió con evidencia, no arbitrariamente.

## C-02 — "El recall lineal está acotado por d² (cota informacional)" — Tipo D parcialmente refutada
- **Contradicción:** la teoría dice capacidad ~d² (pigeonhole, real/Tipo B); el experimento entrenado
  satura MUY por debajo (~0.18 ≪ d², exp009).
- **Clasificación:** la cota d² es **Tipo B real** (informacional); pero "el plateau entrenado = d²" es
  **Tipo D (suposición heredada)** — la cota EFECTIVA la pone la optimización/feature-map, no la teoría.
- **Estado:** atacándola (D se ataca agresivamente). exp010 REFUTÓ que sea el ANCHO (16× estado →
  +0.000). exp011/CYCLE 24 ataca la FORMA del kernel (Taylor) y la INIT (mimetic). Apoyo de literatura:
  Okpekpe & Orvieto 2025 (arXiv:2508.19029): gran parte de la brecha de recall es de OPTIMIZACIÓN.
  → ver `hypotheses.md` H-CEIL-1/2/3(/4) y `ceiling` del engine (real vs asumido).

## C-03 — "Baja precisión = más rápido" — RESUELTA (Tipo C)
- **Contradicción:** int8/ternario debería ser más rápido por mover menos bytes; medido, int8 naïve es
  8-10× MÁS LENTO (exp007).
- **Clasificación:** Tipo C (restricción tecnológica): falta de kernels enteros (BLAS no acelera int8).
- **Resolución/superación:** el ahorro de baja precisión es de MEMORIA (4×), no de cómputo automático;
  la velocidad exige kernels especializados (T-MAC, bitnet.cpp). D-009 (Q4 base; ternario solo I+D).

## C-04 — "FedAvg de LoRA promedia bien" — RESUELTA como Tipo B (inexacto, no subóptimo)
- **Contradicción:** promediar A y B por separado parece equivalente a promediar el producto.
- **Clasificación:** Tipo B (matemática real): avg(A)·avg(B) ≠ avg(A·B). INEXACTO por construcción.
- **Resolución:** exp003 (error 0→66%, crece con heterogeneidad). Agregar delta-W reconstruidas
  (FedEx-LoRA), no A/B sueltos. D-011 — bug accionable en `coordinator/federated_store.py` de Cognia.

## C-05 — "HYDRA como atención en la red" — RESUELTA como Tipo A/C (inviable) → reinterpretada
- **Contradicción:** querer HYDRA como mecanismo de atención distribuido en la red.
- **Clasificación:** Tipo A/C: el modelo es pre-cuantizado INT4 + pre-shardeado; atención distribuida
  síncrona en WAN es inviable (banda/latencia). Restricción dura del repo.
- **Reinterpretación (no se descarta el valor):** HYDRA como **análogo a nivel de SISTEMA** — enrutador
  de contexto/memoria de 3 bandas (LOCAL/MEDIA/GLOBAL) sobre el routing existente. Ver `long_context.md`.

## Backlog de "imposibles" a investigar (no descartar sin cota nombrada)
- Contexto extremadamente largo sin degradar velocidad (F-LONGCTX): ¿qué hay que recordar de verdad?
- Respuestas extremadamente largas manteniendo coherencia/objetivos (generación no estrictamente secuencial).
- Aumentar capacidad sin degradar velocidad proporcionalmente (F-SCALE) — objetivo experimental abierto.

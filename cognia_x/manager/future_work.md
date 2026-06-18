# future_work.md — direcciones futuras de Cognia-X

> Cola de ideas e investigaciones. No es compromiso; es memoria de lo que vale la pena explorar.

## Experimentos cercanos (E1-E5 del ciclo-1, priorizados por impacto/coste)
- ✅ **exp001** coste de mezcla; ✅ **exp002** capacidad de recall (corridos).
- **exp003 = E3** (P0, **siguiente**) — demostrar que el FedAvg ingenuo de LoRA es inexacto:
  ‖avg(B@A) − avg(B)·avg(A)‖_F > 0 y crece con la heterogeneidad. numpy puro, 100% CPU, definitivo.
  Valida H-CF-2; impacto directo en `coordinator/federated_store.py` de Cognia.
- **exp004 = E1** (P0) — roofline CPU: tok/s de un GGUF en Q8/Q4/Q2 variando hilos 1-4; confirmar
  bandwidth-bound (aplanamiento por hilos <30%, tok/s ∝ 1/bytes-por-peso). Requiere llama.cpp.
- **exp005 = E2** (P1) — SWA vs atención full: tok/s(L) 256→32K + RAM de KV-cache + ΔPPL. Valida
  H-SEQ-3. Requiere un GGUF con sliding-window (Gemma-3 / Mistral-SWA).
- **E4** — RAG document-level vs LoRA vs kNN-LM/token para 100 hechos nuevos (valida H-CF-3).
- **E5** — peso real de embedding+lm_head en el GGUF y ahorro de cuantizarlos (valida H-REP-4).

## Direcciones de arquitectura (a confirmar con evidencia)
- Mezcla de secuencia híbrida (mayoría lineal + pocas capas de atención para recall exacto).
- Representación sin tabla de embeddings gigante (byte-level / parches por entropía).
- Aprendizaje continuo por fusión de adapters (model merging) con control de olvido.
- Cómputo entero/ternario como primitiva base en vez de matmul densa float.

## Metodología
- Automatizar el "evidence ledger" (script que valida que cada hipótesis tenga predicción +
  evidencia + experimento antes de marcarla apoyada).
- Suite de micro-benchmarks reproducibles como gate de regresión de eficiencia.

> Se ampliará con los `open_questions` del ciclo-1 (workflow).

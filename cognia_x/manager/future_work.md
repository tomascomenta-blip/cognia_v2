# future_work.md — direcciones futuras de Cognia-X

> Cola de ideas e investigaciones. No es compromiso; es memoria de lo que vale la pena explorar.

## Experimentos cercanos
- **exp002** — calidad de mezcladores: recall asociativo / copia (induction heads) full vs lineal
  vs SSM. Contrapeso obligatorio a exp001.
- **exp003** — perfil roofline en CPU: ¿memory-bandwidth-bound o compute-bound? (valida A-001).
  Medir bytes movidos vs FLOPs en una capa típica con torch-cpu.
- **exp004** — coste de cuantización: int8/int4/ternario vs float32 en CPU (tiempo + calidad),
  validar si los hallazgos de coste se mantienen (A-005).
- **exp005** — representación de entrada: byte/char vs tokenización BPE — tamaño de tabla de
  embeddings, ancho de banda, robustez (dimensión "representación").

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

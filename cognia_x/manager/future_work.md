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

## [2026-06-19] Frontier siguiente: Nivel 2 — "INVESTIGAR por sí misma" (tras CYCLE 8/10)
El aprendizaje continuo Nivel 1 está validado (CYCLE 8: aprende sin olvidar, gate por-dominio + replay;
CYCLE 10: loop como proceso sobre una secuencia). Lo que falta para "investigar sola":
- **Nivel 2 — verificar-antes-de-aprender** (anti-colapso): la IA propone/genera; solo aprende lo
  que pasa un verificador chequeable contra la realidad (código→sandbox+oracle, `cognia_v3/core/
  sandbox_tester.py`; texto→redundancia en ≥2 fuentes reales + filtro de degeneración KL/gzip).
  Ledger de procedencia (origin∈{real,syn}, generación g≤1, cuota ≤15% sintético). Examinador
  SIEMPRE 100% real (invariante). exp009_collapse_guard: 2 brazos (colapso vs guard) — ver workflow.
- **Robustez del gate:** multi-seed (calibrar k·σ, eps), held-out rotativo + committee (anti-Goodhart),
  canarios de sub-distribución (acentos/dígitos), snapshot del optimizer para loops largos.
- **Mecanismos anti-olvido restantes:** Fisher/EWC-light (leer exp_avg_sq de Adam) y adapters LoRA
  con tronco congelado (olvido imposible por construcción). Congelar-tronco ya da -25% (CYCLE 9).
- **Resolver el learned=False a base-fuerte:** aprender una obra del mismo idioma no transfiere
  cross-book; probar dominios genuinamente nuevos (otro idioma, código) o examinador intra-dominio.

## [2026-06-19] Tras PILAR 5 (Razonamiento, CYCLE 12-17): el frontier real
El mecanismo de meta-razonamiento (probar cadenas, quedarse con la que el verificador real aprueba,
elegir por tipo/texto, componer, bajo ruido/OOD, en escala graduada) está validado SOBRE SOLVERS
sintéticos. Lo que falta para que sea razonamiento "de verdad":
- **Envolver el LM real (no solvers de juguete).** Hoy las "cadenas" son procedimientos hand-coded.
  El paso honesto: que las cadenas sean prompts/estrategias del char-LM (o del backend GGUF) sobre
  una tarea que el modelo SÍ pueda intentar, y que el router aprenda cuál funciona. El char-LM (779k,
  byte-level) NO hace aritmética de enunciados → o se sube de escala el modelo, o se elige una tarea
  donde un modelo chico tenga señal (p.ej. transformaciones de texto verificables).
- **Verificador real, no oráculo perfecto.** El "preguntar al usuario" usa hoy el ground-truth como
  oráculo. Reemplazar por (a) verificadores chequeables (código→sandbox, hechos→≥2 fuentes) y (b) un
  usuario simulado ruidoso/caro real (CYCLE 13 ya modeló el ruido; falta el costo asimétrico).
- **Paráfrasis natural, no plantillas.** CYCLE 17 usó plantillas+sinónimos; el NB bag-of-words es
  frágil a paráfrasis genuina. Encoder aprendido (no keyword) o el propio LM como clasificador de tipo.
- **Componer cadenas de largo >2 y descubrir sub-metas** (planificación), no solo secuencias fijas.

# FLEET-30 — Diseño del roster (mandato del dueño 2026-07-11, corrida hasta 05:30)

Mandato: flota de **30 modelos/expertos** en el MoM; mezcla elegida por el
manager entre (A) modelos base open-weight, (B) adapters QLoRA por tarea,
(C) expertos entrenados desde cero, más el loop de deliberación entre modelos
y el análogo interno de "loop transformer". North Star: **IA increíblemente
buena para programación** en el i3 (11.8GB RAM, CPU 2 cores).

Contabilidad HONESTA: cada miembro lista su ESTADO real. Un miembro no
"existe" hasta que su gate pasa; los PLANEADOS tienen gate pre-definido y
entran solo si lo pasan (patrón del programa: 5 líneas de fine-tune se
cerraron con medición — acá ninguna se revive sin diagnóstico de formato).

Infra: `node/fleet_registry.py` (N modelos, lazy, RAM budget, evicción LRU,
manifest `fleet30.json`) + los 3 servers históricos intactos. Puertos nuevos
8093+. RAM: frecuentes ≤4B; los 7B SIEMPRE lazy-usar-cerrar (patrón :8092).

## A. Modelos base open-weight (17)

| # | key | modelo (cuant) | rol | estado 2026-07-12 |
|---|-----|----------------|-----|--------|
| 1 | (3b) | Qwen2.5-Coder-3B-Instruct Q4_K_M | agente principal :8088 | **DEPLOYED** |
| 2 | (7b) | Qwen2.5-Coder-7B-Instruct Q4_K_M | capacidad código duro :8092 lazy | **DEPLOYED** |
| 3 | (portero) | Qwen2.5-0.5B-Instruct Q8_0 + LoRA | turnos triviales :8090 | **DEPLOYED** |
| 4 | nextcoder7b | NextCoder-7B Q4_K_M (MIT) | REPAIR de código (HumanEvalFix 81.1 vs 73.8); participante mesa redonda | descargando |
| 5 | qwen3_4b | Qwen3-4B-Instruct-2507 Q4_K_M | agente v2 candidato + tool-calling (BFCL 61.9) | descargando |
| 6 | coder15b | Qwen2.5-Coder-1.5B base Q8_0 | FIM rápido + candidatos BoN baratos | descargando |
| 7 | vibethinker15b | VibeThinker-1.5B Q4_K_M (MIT) | matemática (AIME25 74.4) | descargando |
| 8 | qwen35_4b | Qwen3.5-4B Q4_K_M | código top (LCB 55.8) | descargando; **GATED smoke b9391** |
| 9 | lfm25_12b | LFM2.5-1.2B Q4_K_M | generalista rápido (IFEval 86.2) | descargando; GATED smoke |
| 10 | qwen3_embed | Qwen3-Embedding-0.6B Q8_0 | embedder RAG código+texto | descargando |
| 11 | bge_reranker | bge-reranker-v2-m3 Q8_0 | reranker RAG | PLANEADO (descarga corta) |
| 12 | qwen3_4b_think | Qwen3-4B-Thinking-2507 Q4_K_M | razonamiento duro lazy | PLANEADO |
| 13 | arctic_sql_7b | Arctic-Text2SQL-R1-7B Q4_K_M | SQL (BIRD 68.9) lazy | PLANEADO |
| 14 | mellum4b | Mellum-4b-sft-all Q4_K_M | FIM focal (JetBrains) | PLANEADO |
| 15 | xlam2_3b | xLAM-2-3b-fc-r Q4_K_M | FC multi-turn (BFCL 65.7) | PLANEADO; ⚠ CC-BY-NC = solo fleet personal, NUNCA en el paquete PyPI |
| 16 | hammer21_15b | Hammer2.1-1.5b Q8_0 | FC barato (base Apache) | PLANEADO |
| 17 | coder05b_base | Qwen2.5-Coder-0.5B base Q8_0 | FIM tiny / draft | PLANEADO |

## B. Adapters LoRA/QLoRA por tarea (9) — cada uno cuenta como experto

Regla vigente (5 negativas medidas): se entrena SOLO gap de FORMATO/hábito
con oráculo determinista; diagnóstico por clases ANTES de gastar GPU.

| # | key | base | tarea | estado |
|---|-----|------|-------|--------|
| 18 | accion | 3B | tool-calling formato ACCION + identidad | **DEPLOYED** (G2A 99.3) |
| 19 | portero_id | 0.5B | identidad del portero | **DEPLOYED** (G3 90) |
| 20 | id_qwen3_4b | qwen3_4b | identidad Cognia del 4B (G3: contesta como Qwen sin él) | **KERNEL ESTA NOCHE** (K1, gate G3≥90 + G1 sin regresión) |
| 21 | accion_4b | qwen3_4b | formato ACCION en el 4B | PLANEADO (solo si #20 pasa; gate G2A) |
| 22 | commit_msgs | coder15b | mensaje de commit desde diff (formato convencional) | PLANEADO (dataset del git history, verificado por parser) |
| 23 | docstrings | coder15b | docstring Google-style (oráculo: firma vs args documentados) | PLANEADO (diag primero) |
| 24 | testfirst | 3B | asserts test-first válidos (yield-band) | PLANEADO (diag primero) |
| 25 | sql_formato | coder15b | SQL válido ejecutable (oráculo: sqlite) | PLANEADO (diag: ¿formato o capacidad?) |
| 26 | fim_estilo | coder15b | FIM estilo repo del usuario | PLANEADO (diag primero) |

## C. Expertos desde cero (tiny, linaje cognia-x) (4)

| # | key | qué | estado |
|---|-----|-----|--------|
| 27 | xh_tiny_es | 110M banded español (XHUNDRED; G1 1.2888 ✓, G4 0.85 ✓, G3 ✗) | ENTRENADO, experimental |
| 28 | xh_loop | **loop transformer interno**: 3 capas × 4 vueltas weight-tied (XARCH midió: calidad ≈12L con 1/4 de params) + halting adaptativo (exp137: +31% ahorro, POSITIVO en toy) | **KERNEL ESTA NOCHE** (K2; gates pre-registrados abajo) |
| 29 | tiny_router | clasificador de especialidad→experto (para el router del fleet) | PLANEADO |
| 30 | tiny_error_clf | clasificador de error_type→estrategia de repair | PLANEADO |

## Límite físico declarado (análogo del "loop transformer" en los grandes)

Loopear ARQUITECTÓNICAMENTE los modelos GGUF pre-cuantizados es INVIABLE
(misma clase que la regla HYDRA de CLAUDE.md: no se puede reescribir la
profundidad de un modelo pre-entrenado servido por llama.cpp). El análogo
honesto a nivel de sistema, YA cableado esta noche: **mesa redonda**
(`cognia/agent/deliberation.py`) — los modelos se pasan candidato +
traceback real del sandbox y reparan por turnos (keep-best, oráculo duro,
early-exit). El loop transformer LITERAL va donde sí es posible: el tiny
desde cero (#28), con pesos compartidos entre vueltas de profundidad.

## Gates de esta noche (congelados antes de correr)

- **K1 id_qwen3_4b**: G3 identidad ≥90% con adapter, G1 sin regresión
  (McNemar pareado, mismas suites congeladas del portero). Falla → 1 ajuste
  → falla → línea cerrada y documentada.
- **K2 xh_loop**: (a) corre y converge sin NaN en ≤30 min T4; (b) bpb wiki
  ≤1.45 (banda de falsación de XHUNDRED) con ~1/4 de params del backbone
  12L; (c) G4 cloze ≥55% (65% era del 12L completo; el loop tiene 1/4 de
  params → umbral pre-ajustado ANTES de correr, no después); (d) reporte
  honesto tok/s (XARCH: el loop NO ahorra cómputo, compra params).
- **Mesa redonda (PREREG_DELIBERACION.md)**: recovered ≥3 con tests OCULTOS
  sobre las duras que la cascada actual falla → default ON; si no, opt-in.
- **Smoke transversal** modelos nuevos: carga en b9391 + genera + tok/s
  medido + RAM real; cualquier arch que no cargue queda GATED documentado.

## Riesgos declarados

- Licencias: xLAM-2 (CC-BY-NC) y Qwen2.5-Coder-3B-base (research) NO son
  empaquetables; el manifest del producto los excluye por default.
- tok/s de los 4B: extrapolado ~6 tok/s (NO medido aún); si el smoke da
  peor, el rol "agente v2" se cae y quedan como especialistas lazy.
- 30 miembros ≠ 30 servers: el registry mantiene pocos residentes (budget
  3GB extra) y evicta LRU; los 7B jamás coexisten entre sí.

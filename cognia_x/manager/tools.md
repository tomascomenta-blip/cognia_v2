# tools.md — herramientas/instrumentos construidos por Cognia-X

> §AUTO-MEJORA de la directiva: crear herramientas cuando haya limitaciones; evaluarlas, compararlas,
> medir (velocidad, precisión, consumo, reutilización, mantenibilidad), descartar las inferiores,
> mantener historial, permitir reversión. Este archivo es el inventario vivo. Append-only.

## El Investigation Engine — `cognia_x/research/` (la herramienta MÁS importante)
El método de investigación como CÓDIGO EJECUTABLE Y TESTEADO (no narrativa). Componentes:
- `schema.py` — vocabulario plano (Source/Hypothesis/Decision/AnalogyRecord/CeilingRecord/ScalabilityNote).
- `ledger.py` — `EvidenceLedger`: rechaza decisión importante solo-opinión (`OpinionOnlyError`).
- `hypotheses.py` — `HypothesisRegistry`: gate DoD compartido (`PrematureVerdictError`) para
  apoyada/refutada/mixta (predicción + ≥1 a favor + ≥1 en contra + veredicto adversarial + experimento).
- `analogy.py` — `extract_principles`: exige 7 etapas / ≥3 soluciones (`IncompleteAnalogyError`).
- `ceiling.py` — `CeilingTracker`: clasifica `real|asumido` + tipo de bloqueo; expone el backlog de asumidos.
- `record.py` — `PermanentRecord`: journaling append-only + `verify_no_loss()` ("pérdida = fallo").
- `cli.py` — `status|verify|ceilings|assumed` para inspeccionar sin REPL.
- `cycles/cycleNN_*.py` — cada ciclo de investigación poblando el store POR las compuertas (22,23,24...).
- **Test:** `tests/test_research_engine.py`. **Reversión:** stores aislados por ciclo, gitignoreados.

## Banco de experimentos — `cognia_x/experiments/exp001..exp011`
Micro-benchmarks reproducibles (seed fijo, `venv312`, presupuesto acotado declarado). Cada uno cierra
una hipótesis con números propios (tier-5). Inventario en `experiments.md`. Gate de regresión de
eficiencia: re-correr un expNNN debe dar el mismo número clave.

## Modelo + tareas — `cognia_x/model/hybrid.py`, `cognia_x/train/`
- `HybridLM`: backbone híbrido (LinearAttention estado-fijo + SlidingWindowAttention + SwiGLU + RMSNorm
  + RoPE + lm_head atado). Levers de investigación: `linear_feature_mult` (ancho, exp010),
  `linear_feature_map` (elu|taylor, exp011), `mimetic_init` (exp011) — todos default-OFF (no rompen lo previo).
- `train/recall_task.py`: tarea MQAR de recall asociativo (control positivo válido tras CYCLE 6).
- `train/charlm.py` + `run_overnight.py`: byte-LM sobre texto local con deadline + checkpoints.
- **Test:** `tests/test_recall_and_rope.py`, `tests/test_cycle24_kernel_init.py`.

## Solvers de razonamiento — `cognia_x/reason/`
Cadenas/router de meta-razonamiento + verificador no-circular (PILAR 5). Ver `reasoning.md`.

## Disciplina de evolución de herramientas
- Una herramienta nueva entra solo si resuelve una limitación real y trae su test. La inferior se
  descarta pero su historial NO se borra (append-only / `verify_no_loss`).
- Mejora medida concreta (CYCLE 24): cache de índices del feature-map Taylor → evita recomputar
  `triu_indices` por forward (cómputo redundante); la identidad sigue exacta (test) y bajó el wall-time.

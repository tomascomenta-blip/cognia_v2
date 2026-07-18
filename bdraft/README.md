# bdraft — Cognia-BDraft (block-diffusion draft model)

Laboratorio de entrenamiento del draft de difusión de bloques estilo
DFlash/DSpark (~110M parámetros entrenables, target Qwen2.5-7B-Instruct).
Diseño canónico: `planes/DSPARK_GEMMA_DRAFT_MODEL.md` (secciones 2.2, 2.3, 3).

**Corre SOLO en la máquina de entrenamiento.** Regla dura del repo: sin
PyTorch en nodos. Por eso este paquete NO se empaqueta a PyPI (no está en
`[tool.setuptools.packages.find] include` de `pyproject.toml`).

## Qué hay

- `model.py` — `BDraftConfig` + `BDraft`: núcleo de 6 capas bidireccionales
  (d=1024) con inyección K/V del contexto del target, embedding/LM head
  compartidos-congelados, mask embedding y cabeza de confianza (DSpark).
- `data.py` — ratio de enmascaramiento t ~ U(0,1), armado de batches
  contexto+canvas, dataset sintético determinista (motivos periódicos).
- `train.py` — chunked cross-entropy (nunca materializa `[N, 152K]`),
  pesos exponenciales por posición (DFlash), loop AdamW, modo `--mini`.
- `gates.py` — umbrales pre-registrados de la sección 3 del doc como
  constantes con nombre + funciones G2/G3/G4.

## Modo mini (smoke run en CPU, <5 min)

```
.\venv312\Scripts\python.exe -m bdraft.train --mini --steps 100
```

Usa `BDraftConfig.mini()` + dataset sintético; la loss debe bajar de forma
clara (el test de overfit exige final < 50% de la inicial en 200 steps).

Tests: `.\venv312\Scripts\python.exe -m pytest tests/test_bdraft_train.py
tests/test_bdraft_model.py -q` (todo CPU, `PYTHONUTF8=1`).

## Gates ANTES de entrenar de verdad

Pre-registrados en el doc sección 3; en orden: **G0** (toolchain: torch
cu128+ ve sm_120, forward del 7B NF4 + draft esqueleto corre en WSL2),
**G1** (baselines B0/B1 en llama.cpp), **G2** (techo teórico con draft SIN
entrenar: `techo = 8·T_tok_base/T_ciclo ≥ 1.5`, si no KILL), **G3** (señal
temprana al 10% del presupuesto: top-1 ≥ 30% y τ ≥ 1.5). G4/G5 aplican al
final de v0. Umbrales: `bdraft/gates.py`.

## Entrenamiento real

Requiere **torch cu128+ bajo WSL2** (RTX 5060 Ti, Blackwell sm_120 — gate
G0 del doc): target Qwen2.5-7B NF4 en el loop con hidden states on-the-fly,
datos regenerados por el target. NO está implementado en este módulo todavía;
`train.py` sin `--mini` sale con ese mensaje.

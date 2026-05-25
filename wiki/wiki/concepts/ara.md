---
title: ARA — Adaptive Rank Amplification
type: concept
tags: [ara, lora, rank, expansion, orthogonal, numpy]
updated: 2026-05-24
---

# ARA — Adaptive Rank Amplification

→ [[index]]

## Qué es

Expande el rank del adapter LoRA cuando detecta saturación en el training loss. Las nuevas dimensiones son ortogonales al espacio actual — no destruyen lo aprendido.

## Archivo fuente

`node/rank_expansion.py`

## Detección de saturación

```python
def is_saturated(loss_history: List[float]) -> bool:
    # Plateau: variance de últimas N_PLATEAU épocas < VAR_RATIO_MAX * mean
    # Non-trivial: mean > MIN_LOSS_EXPAND (hay gap real de capacidad)
    _N_PLATEAU     = 5
    _VAR_RATIO_MAX = 0.02   # < 2% de varianza relativa
    _MIN_LOSS_EXPAND = 0.05
```

## Expansión ortogonal

1. Genera vectores aleatorios en R^hidden_dim
2. Proyecta fuera del espacio actual (componente A-space)
3. QR-ortonormaliza el resultado
4. Añade `n_new` filas ortogonales a A

## Límites

```python
MAX_RANK = 8   # doble del default r=4 — hard cap
```

`federated_store.py` usa el mismo cap (`_RANK_MAX=8`).

## Cuándo se llama

`LoRATrainer.train()` llama `is_saturated()` al final del loop. Si True y rank < MAX_RANK, llama `expand_lora_weights()`.

## Links

- [[concepts/elc]]
- [[entities/local_adapter]]
- [[entities/federated_store]]

---
title: local_adapter — ELC LoRA adapter por usuario
type: entity
tags: [elc, lora, numpy, personalization, sleep]
updated: 2026-05-24
---

# local_adapter (ELC)

→ [[index]]

## Qué hace

Implementa el Episodic LoRA Cascade (ELC). Adapters LoRA entrenados desde memoria episódica durante el sleep cycle. Se aplican en las proyecciones K/V del shard para personalizar inferencia sin modificar pesos INT4 base.

## Archivo fuente

`node/local_adapter.py`

## Arquitectura del adapter

```python
A: (rank=4, hidden_dim=2048)   # shared initializer para K y V
B_k: (kv_proj_out=256, rank=4) # delta K
B_v: (kv_proj_out=256, rank=4) # delta V

delta_k(x) = x @ A.T @ B_k.T  # (seq, kv_proj_out)
delta_v(x) = x @ A.T @ B_v.T
```

## Restricción FIJA

`kv_proj_out=256` — resultado de `n_kv_heads=2 * head_dim=128`. **No cambiar.**

## Clases

| Clase | Rol |
|---|---|
| `LoRAWeights` | Dataclass con A, B y método `delta(x)` |
| `LoRAAdapter` | Aplica el delta en el forward pass del shard |
| `LoRATrainer` | Entrena con triplet margin loss sobre surrogate hidden states; llama a ARA si satura |

## Training

- Surrogate hidden states: vectores episódicos (dim=384) proyectados a hidden_dim via matriz aleatoria fija por usuario
- Triplet margin loss: acerca episodios del mismo label, separa diferentes
- `_MARGIN=0.5`, `_LR=1e-3`, `_EPOCHS=30`

## Storage

`cognia/memory/adapter_store.py` — LRU: máx 5 adapters en memoria, máx 50MB en disco.

## Links

- [[concepts/elc]]
- [[concepts/ara]]
- [[entities/federated_store]]
- [[synthesis/memory_pipeline]]

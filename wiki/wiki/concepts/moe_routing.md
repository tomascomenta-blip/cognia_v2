---
title: MoE Routing — 16 expertos, top_k=2
type: concept
tags: [moe, routing, logos, techne, rhetor, experts]
updated: 2026-07-16
---

# MoE Routing

→ [[index]]


## Estado (2026-07-16)

Este MoE es del path shards y NO corre en el producto. El 'mixture' real de
hoy es la colonia multi-modelo GGUF (3B/7B/4B/0.5B): [[concepts/colonia]].
## Diseño

Mixture-of-Experts con 16 expertos distribuidos en 3 dominios. Cada token activa los top_k=2 expertos más relevantes.

```python
MICRO_MOE_NUM_EXPERTS      = 16
MICRO_MOE_TOP_K            = 2
MICRO_MOE_INTERMEDIATE_DIM = 4096

DOMAIN_EXPERT_CLUSTERS = {
    "logos":  [0..4],    # 5 expertos — razonamiento
    "techne": [5..9],    # 5 expertos — código/técnico
    "rhetor": [10..15],  # 6 expertos — escritura
}
```

## Routing decision

`GlobalRouter` (`shattering/router.py`) decide el dominio antes de la inferencia. La decisión usa:
1. Keywords heurísticos (tabla de ~80 terms por dominio)
2. Similitud coseno sobre embeddings 384-dim (all-MiniLM-L6-v2 o n-gram fallback)

## Restricción

Máximo 16 expertos — límite de RAM en Android (≤1.5GB). No escalar más.

## Temperatura por dominio

| Dominio | Temperatura |
|---|---|
| LOGOS | 0.3 |
| TECHNE | 0.15 |
| RHETOR | 0.7 |

## Links

- [[entities/router]]
- [[entities/orchestrator]]
- [[sources/model_constants]]

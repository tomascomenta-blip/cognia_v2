---
title: GlobalRouter — MoE router LOGOS/TECHNE/RHETOR
type: entity
tags: [router, moe, logos, techne, rhetor, embedding]
updated: 2026-07-16
---

# GlobalRouter

→ [[index]]


## Estado (2026-07-16)

Este router LOGOS/TECHNE/RHETOR pertenece al path shards y NO es el ruteo
del producto: hoy rutean [[entities/hybrid_router]] (dificultad),
[[entities/fleet_registry]] (expertos LoRA + 4B por turno) y classify_turn
del [[entities/portero_05b]]. DOMAIN_EXPERT_CLUSTERS/MICRO_MOE_* viven en
shattering/model_constants.py (los consume moe_layer.py), no en router.py.
## Qué hace

Decide qué sub-modelo usar para un query. Combina heurísticas de keywords con similitud coseno sobre embeddings 384-dim (SentenceTransformer all-MiniLM-L6-v2 o fallback n-gram). Default a LOGOS para queries genéricos o ambiguos.

## Archivo fuente

`shattering/router.py`

## Dominios

| Sub-modelo | Dominio | Keywords clave |
|---|---|---|
| TECHNE | Código, algoritmos, ingeniería | code, function, bug, sql, docker, llm... |
| RHETOR | Escritura, estilo, edición | write, essay, draft, translate, poem... |
| LOGOS | Razonamiento, conocimiento, resto | (default) |

## MoE — Expertos por dominio

```python
DOMAIN_EXPERT_CLUSTERS = {
    "logos":  list(range(0,  5)),   # 5 expertos
    "techne": list(range(5,  10)),  # 5 expertos
    "rhetor": list(range(10, 16)),  # 6 expertos
}
MICRO_MOE_TOP_K = 2
```

## Output

```python
@dataclass
class RouteDecision:
    sub_model:  str    # "logos" | "techne" | "rhetor"
    confidence: float
    scores:     Dict[str, int]  # keyword hits por dominio
    reason:     str
```

## Links

- [[concepts/moe_routing]]
- [[entities/orchestrator]]

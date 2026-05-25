---
title: RST — Recursive Summarization Tree
type: concept
tags: [rst, context, summarization, recursive, long-context]
updated: 2026-05-24
---

# RST — Recursive Shared Transformer

→ [[index]]

## Qué es

Mecanismo de compresión de contexto largo. Cada pass recursivo inyecta un vector de contexto en el hidden state antes del forward pass, y lo actualiza con el output:

```
Injection:  h = h + alpha * context_vec
Update:     context_vec = LayerNorm(linear(h_output))
```

## Parámetros

```python
DEFAULT_RST_PASSES  = 1      # K=1 deshabilita RST (compat hacia atrás); K=2 modo calidad
RST_ALPHA_INIT      = 0.1    # escala de inyección — pequeño para near-identity al inicio
```

`alpha` inicializado pequeño para estabilidad en inicialización (evitar training instability).

## Archivo fuente

`shattering/recursive_context.py`

## Estado — DEUDA ACTIVA

K=2, alpha=0.1 **no validados** — MEDIO riesgo. Los parámetros existen y el código funciona, pero no hay evidencia de que los valores sean óptimos.

## Cuándo usar

Solo cuando el contexto excede la ventana de atención. Para contextos normales, usar [[concepts/lpc]] que es exacto y sin overhead.

## Simulation mode

En modo simulación no se cargan matrices de peso. Solo corre la aritmética de inyección/update — RAM negligible.

## Links

- [[comparisons/lpc_vs_rst]]
- [[concepts/lpc]]
- [[sources/orchestrator_src]]

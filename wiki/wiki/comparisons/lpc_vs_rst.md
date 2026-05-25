---
title: LPC vs RST — gestión de contexto largo
type: comparison
tags: [lpc, rst, kv-cache, context, performance]
updated: 2026-05-24
---

# LPC vs RST

→ [[index]]

| | LPC (Local Prefix Cache) | RST (Recursive Summarization Tree) |
|---|---|---|
| Opera sobre | KV tensors | Texto |
| Exactitud | Exacta (lossless) | Aproximada (lossy) |
| Velocidad | Rápido (skip matemático) | Lento (llama al modelo) |
| Cuándo usar | Conversaciones normales | Contextos muy largos (>N tokens) |
| Estado | Phase 21.1 DONE (cross-turn) | K=2, alpha=0.1, no validado |
| Implementación | `orchestrator.py`, `mla.py` | `recursive_context.py` |

## Cuándo preferir LPC

Siempre que el contexto quepa en memoria. Es exacto y sin overhead de generación.

## Cuándo considerar RST

Solo cuando el contexto excede la ventana de atención. RST comprime pero pierde información — K=2, alpha=0.1 son parámetros no validados (deuda activa).

## Links

- [[concepts/lpc]]
- [[concepts/rst]]

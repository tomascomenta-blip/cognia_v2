---
title: Speculative Decoding — draft + verify para acelerar generación
type: concept
tags: [speculative, decoding, performance, draft, lm_head]
updated: 2026-05-24
---

# Speculative Decoding

→ [[index]]

## Qué es

Técnica para acelerar generación: un modelo draft rápido propone K tokens, el modelo principal verifica todos en un solo forward pass. Si el draft es correcto, se ganan K tokens por el costo de uno.

## Por qué existe en Cognia

El `lm_head` chunked (~37 matmuls/token) es el cuello de botella principal. Speculative decoding compensa esto — cada verificación batch amortiza el costo del lm_head.

## Estado actual

- Implementado como compensación al lm_head chunked
- Kernels Numba JIT para INT4/RMSNorm/SiLU listos en `node/qwen2_ops.py` pero bloqueados por Python 3.14

## Draft model

Un draft model centralizado viola privacidad (ver FUERA DE ALCANCE). El draft debe ser local o usar PSW (ver RESEARCH.md).

## Rendimiento actual vs objetivo

| | Valor |
|---|---|
| Actual | ~0.1 tok/s |
| Objetivo Phase 21 | 3-6 tok/s |

## Links

- [[concepts/int4_nibble]]
- [[sources/qwen2_ops]]
- [[synthesis/inference_pipeline]]

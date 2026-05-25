---
title: INT4 nibble-packed — cuantización sin PyTorch
type: concept
tags: [int4, quantization, numpy, performance]
updated: 2026-05-24
---

# INT4 nibble-packed

→ [[index]]

## Qué es

Cuantización de 4 bits donde dos valores INT4 se empacan en un byte (nibble). Todo el pipeline es **numpy puro — sin PyTorch**.

## Por qué numpy puro

- Nodos pueden ser Android (≤1.5GB RAM) o máquinas sin GPU
- PyTorch pesa demasiado para el caso móvil
- Permite control exacto del layout de memoria

## Dequantización

`node/qwen2_ops.py` implementa la dequantización INT4→FP32 en numpy. El `lm_head` se aplica en chunks (~37 matmuls/token) para evitar OOM de 1.16 GiB al dequantizar todo junto.

## Restricción importante

**Layer promotion INT4→FP32 en caliente está fuera de alcance** — rompería el grafo numpy. Si se necesita precisión distinta, usar un modelo separado.

## Aceleración pendiente

Kernels Numba JIT para INT4/RMSNorm/SiLU están listos en `node/qwen2_ops.py` pero bloqueados por Python 3.14. Requiere Python ≤3.12 o esperar soporte numba para 3.14.

## Links

- [[concepts/sharding]]
- [[concepts/speculative_decoding]]
- [[sources/qwen2_ops]]
- [[entities/shard_engine]]

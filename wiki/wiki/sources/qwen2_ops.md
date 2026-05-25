---
title: qwen2_ops.py — operadores numpy para Qwen2
type: source
tags: [numpy, int4, rmsnorm, silu, rope, lm_head, numba]
updated: 2026-05-24
---

# qwen2_ops.py

→ [[index]]

## Qué contiene

`node/qwen2_ops.py` — todos los operadores de la forward pass sin PyTorch.

## Clases principales

| Clase | Descripción |
|---|---|
| `INT4Weights` | Pesos nibble-packed con dequantize-on-demand matmul |
| `RealTransformerLayer` | Decoder layer completo: RMSNorm, RoPE, GQA (SWA_WINDOW), SwiGLU |

## Operaciones implementadas

- `RMSNorm` — normalización
- `RoPE` — rotary position embedding (theta=1M)
- `SwiGLU` — gate_proj * SiLU(up_proj) antes de down_proj
- `lm_head` chunked — ~37 matmuls/token para evitar OOM de 1.16 GiB

## Restricción crítica

**Solo numpy — sin PyTorch.** Esto es mandatorio para compatibilidad con nodos móviles (Android).

## Aceleración en 3 tiers

```
Tier-1: Numba JIT (Python <=3.12) — BLOQUEADO por Python 3.14
Tier-2: C kernels via ctypes (.dll/.so) o cffi — cualquier Python
Tier-3: numpy puro (fallback)
```

Los kernels C están en `node/fast_kernels.c` y `node/build_fast_kernels.py`. Se compilan en el primer import si no existe el .dll/.so.

## Bottleneck actual

lm_head chunked es el cuello de botella principal (~0.1 tok/s). Speculative decoding compensa. Con Numba/C kernels: objetivo 3-6 tok/s.

## Links

- [[concepts/int4_nibble]]
- [[concepts/speculative_decoding]]
- [[concepts/rope]]
- [[entities/shard_engine]]

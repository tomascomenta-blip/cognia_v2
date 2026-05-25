---
title: RoPE — Rotary Position Embedding
type: concept
tags: [rope, position-embedding, attention, qwen2]
updated: 2026-05-24
---

# RoPE — Rotary Position Embedding

→ [[index]]

## Qué es

Encoding de posición que rota los vectores Q y K en el espacio complejo según la posición del token. Preserva información relativa de posición en el producto escalar de atención.

## Implementación en Cognia

`node/qwen2_ops.py` — parte de `RealTransformerLayer`.

Parámetro clave de Qwen2.5-3B:
```python
"rope_theta": 1_000_000.0  # en model_constants.py QWEN25_CODER_3B
```

## Por qué theta=1M

Qwen2.5 usa theta=1M (vs 10K de Llama original) para soportar contextos más largos. Este valor viene del `config.json` de HuggingFace y está hardcodeado en `model_constants.py`.

## Integración con MLA

RoPE se aplica a Q y K antes de comprimirlos en el latente MLA. La integración está en `shattering/mla.py` — fue uno de los fixes críticos (antes había atención bidireccional sin RoPE).

## Links

- [[entities/mla_module]]
- [[sources/qwen2_ops]]
- [[sources/model_constants]]

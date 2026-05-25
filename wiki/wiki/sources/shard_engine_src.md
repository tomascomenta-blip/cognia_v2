---
title: shard_engine.py — motor de ejecución de shard
type: source
tags: [shard, wire-protocol, npz, inference, int4]
updated: 2026-05-24
---

# shard_engine.py

→ [[index]]

## Archivo

`node/shard_engine.py`

## Responsabilidades

1. Carga el shard `.npz` desde `SHARD_WEIGHTS_DIR`
2. Decodifica el wire protocol (12-byte header big-endian)
3. Ejecuta el forward pass de sus capas (delegando a `qwen2_ops.RealTransformerLayer`)
4. Emite hidden states al siguiente shard o logits si es el último

## Wire protocol

Ver [[entities/shard_engine]] para el detalle completo del protocolo.

## KV-cache

Acepta `PTYPE_CLEAR_CACHE` para evictar la sesión de MLA KV-cache. Método `clear_cache(session_id)`.

## Integración con MLA

`patch_shard_engine_mla(engine)` reemplaza la atención de cada capa con `MLAModule`. El `session_id` viaja por todos los `forward()`.

## Links

- [[entities/shard_engine]]
- [[entities/mla_module]]
- [[sources/qwen2_ops]]

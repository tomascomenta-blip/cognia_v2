---
title: LPC — Local Prefix Cache
type: concept
tags: [lpc, kv-cache, performance, inference]
updated: 2026-05-24
---

# LPC — Local Prefix Cache

→ [[index]]

## Qué es

KV-cache cross-turn: evita re-procesar el prefijo de la conversación en cada turno. Se identifica con `lpc_session_id` en `infer()`.

## Estado

- **Phase 21.1 DONE** — cross-turn (saltar prefijo entre turnos)
- **Phase 21.2 pendiente** — intra-turn (cache dentro del mismo turno)

## Implementación

- `shattering/orchestrator.py` — campo `lpc_session_id` en `infer()`
- `shattering/mla.py` — skip-prefix logic

## Por qué importa

Sin LPC, cada token nuevo re-procesa toda la secuencia desde el inicio. Con LPC el prefijo ya cacheado se salta — reducción directa de FLOPs por turno.

## Relación con RST

LPC y RST son complementarios. LPC opera a nivel de KV tensors (rápido, exacto). RST opera a nivel de texto resumido (lento, lossy). Usar LPC para conversaciones normales; RST solo para contextos muy largos.

Ver [[comparisons/lpc_vs_rst]].

## Links

- [[comparisons/lpc_vs_rst]]
- [[entities/orchestrator]]
- [[entities/mla_module]]
- [[synthesis/inference_pipeline]]

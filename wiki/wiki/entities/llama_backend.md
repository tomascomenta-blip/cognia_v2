---
title: Llama Backend — inferencia GGUF local (:8088)
type: entity
tags: [llama.cpp, gguf, llama-server, b9391, inferencia]
updated: 2026-07-16
---

# Llama Backend

→ [[index]]

## Que es

`node/llama_backend.py` — la ruta de inferencia PRIMARIA del producto.
Prioridad: (1) llama-cpp-python in-process, (2) subprocess `llama-server`
(REST OpenAI-compatible, :8088), (3) None → fallback a shards numpy
([[entities/shard_engine]]). NUNCA lanza excepcion: toda funcion publica
devuelve None en fallo y el resto de Cognia sigue.

## Pin del binario

`llama-server` pineado a **b9391** (7fb1e70b5): b9414 tiene regresion de
~37% en decode CPU medida en el i3 (5.2 vs 8.2 tok/s). No actualizar sin
re-correr el A/B con server real. Threads=3 en el i3; Q4_K_M > Q4_0;
techo del hardware ~8-9 tok/s.

## Resolucion del modelo

`LLAMA_GGUF_PATH` (via `~/.cognia/config.env`, aplicado por
`apply_config()` en TODOS los entry points desde 3.9.1) → deteccion en
`SHARD_WEIGHTS_DIR` → descubrimiento automatico en `~/.cognia/models/*`
(el GGUF mas grande fuera del portero). Los servers bindean 127.0.0.1
(defense-in-depth, 3.8.8).

## Puertos del sistema

```
:8000  cognia server (FastAPI app/main.py)
:8001  coordinator del swarm
:8088  llama-server 3B fleet (LoRA hot-swap accion/portero)
:8090  portero 0.5B
:8092  heavy code 7B
:8093+ fleet30 registry
:8765  desktop API (Electron)
:8766  oficina dashboard
```

## Links

- [[concepts/install_model]]
- [[entities/fleet_registry]]
- [[comparisons/ollama_vs_shards]]

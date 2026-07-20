---
title: llama.cpp vs shards vs Ollama — prioridad real del backend
type: comparison
tags: [llama.cpp, gguf, shards, ollama, backend, prioridad]
updated: 2026-07-16
---

# llama.cpp vs shards vs Ollama

→ [[index]]

## Prioridad real (node/llama_backend.py + orchestrator.infer)

```
1. llama-cpp-python  in-process (si esta instalado)
2. llama-server      subprocess :8088, GGUF Q4_K_M, b9391 pineado  <- PRODUCCION
3. shards numpy      fallback distribuido/local (INT4, sin PyTorch)
4. Ollama            fallback legacy (language_engine._call_ollama y
                     _ollama_infer del orchestrator; respeta OLLAMA_URL)
```

| Eje | llama.cpp+GGUF | shards numpy | Ollama |
|---|---|---|---|
| Rol | camino DEFAULT del producto | capa swarm/fallback | legacy opcional |
| Velocidad (i3) | ~8 tok/s (3B) | ~0.1 tok/s | depende del host |
| Instalacion | cognia install-model | install-weights | externa (manual) |
| Multi-modelo | fleet + portero + 7B | LOGOS/TECHNE/RHETOR | un modelo |
| Aprendizaje | LoRA hot-swap (adapters.json) | ELC/FedAvg | no |

## Historia

La version anterior comparaba solo "Ollama vs shards" con un arbol
coverage→decision que ya no describe el producto: desde 3.8.x el chat y
el agente van por el backend GGUF, y desde 2026-07-16 /crear, el
researcher y las hipotesis tambien (Ollama quedo como fallback honesto).

## Links

- [[entities/llama_backend]]
- [[concepts/install_model]]
- [[concepts/sharding]]

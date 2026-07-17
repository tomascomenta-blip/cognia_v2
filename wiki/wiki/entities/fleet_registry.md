---
title: Fleet Registry — N modelos GGUF con presupuesto de RAM
type: entity
tags: [fleet, registry, gguf, lora, ram, lru]
updated: 2026-07-16
---

# Fleet Registry

→ [[index]]

## Que es

Dos piezas complementarias:

1. `node/fleet_registry.py` — registry N-modelos del FLEET-30: generaliza
   el patron heavy_code (singleton lazy + falla cacheada + kill-switch) a
   N modelos declarados en un manifest JSON, con presupuesto de RAM
   (`COGNIA_FLEET_RAM_GB`, default 3.0) y eviccion LRU. Los 3 servers
   historicos NO pasan por aca (3B :8088, portero :8090, 7B :8092).
   Manifest: env `COGNIA_FLEET30_MANIFEST` → `~/.cognia/models/fleet30.json`
   → `<repo>/shattering/manifests/fleet30.json`. Kill-switch
   `COGNIA_FLEET30=0`.

2. `cognia/agent/fleet_router.py` — router de expertos LoRA del 3B
   (adapters.json junto al GGUF). Reglas LEXICAS deterministas, NO
   matching semantico difuso (leccion medida de skills: umbral 0.35
   matcheaba cualquier cosa en espanol). Default None = base pura: el
   fleet nunca rinde menos que la base. Experto hoy: `accion`
   (tool-calling formato ACCION + identidad; G2A 95.2%, G3 20/20; NUNCA
   para chat general — regresiona G1 -8pp).

## Quien usa el router

- `_run_agent_task` (cli.py): experto "accion" para toda tarea de agente
- fast-path de chat: `expert_for_chat_turn()` por turno
- `/largo`: siempre base (None)

## Links

- [[entities/llama_backend]]
- [[entities/heavy_code_7b]]
- [[entities/portero_05b]]
- [[concepts/install_model]]

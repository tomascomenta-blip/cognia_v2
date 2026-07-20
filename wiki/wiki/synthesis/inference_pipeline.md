---
title: Inference Pipeline — flujo real de un turno (2026-07)
type: synthesis
tags: [pipeline, inferencia, hibrido, llama-server, colonia, puertos]
updated: 2026-07-16
---

# Inference Pipeline

→ [[index]]

## Flujo de PRODUCCION (cognia-ai 3.9.x)

```
REPL/CLI (cognia/cli.py)
  |- turno social/identidad  -> PORTERO 0.5B :8090   (classify_turn conservador)
  |- turno de razonamiento   -> razonador 4B (permiso del perfil hibrido)
  |- turno normal            -> 3B fleet :8088 (+experto LoRA por turno)
  |- /hacer <tarea>          -> hybrid_router.route_profile(task)
  |                             mono | agente | +colonia | +superorganismo
  |                             loop ReAct ACCION con tools reales
  |- generar_codigo          -> cascada REACTIVA (solo si lo barato fallo):
  |                             3B best-of-N -> 7B greedy :8092 ->
  |                             Qwen3.5-4B -> superorganismo (etapa 4)
  v
ShatteringOrchestrator.infer -> _try_load_llama -> LlamaBackend
  (llama-server b9391, bind 127.0.0.1, GGUF de ~/.cognia/models/)
```

Todo local; servers bindean 127.0.0.1. Puertos: ver [[entities/llama_backend]].

## Modo swarm (opcional, NO default)

Con `COGNIA_COORDINATOR_URL` seteada y nodos registrados:
relay WebSocket → cadena de shards INT4 numpy → lm_head en el ultimo
shard. Piezas: [[entities/coordinator]], [[entities/relay]],
[[entities/shard_engine]]. `COGNIA_DISABLE_SWARM=1` lo fuerza apagado.
Sin pesos reales el nodo REPORTA la descarga fallida (fix 2026-07-16:
antes simulaba en silencio).

## Links

- [[concepts/ruteo_hibrido]]
- [[concepts/colonia]]
- [[entities/hybrid_router]]
- [[entities/llama_backend]]

# Cognia Wiki — Index

**Topic:** Cognia — IA cognitiva local (llama.cpp + GGUF) con ruteo hibrido por dificultad, agente con herramientas, colonia multi-modelo y memoria episodica. La capa swarm (sharding numpy + coordinator + federated learning) es opcional/legacy.

> Use this index to navigate. Every page links back here.
> Actualizado 2026-07-16: el producto (cognia-ai 3.9.x en PyPI) corre 100% local
> via [[entities/llama_backend]]; el swarm NO es el camino de inferencia default.

---

## Sistema actual (2026-07) — el producto

| Page | One-line |
|---|---|
| [[entities/llama_backend]] | Backend REAL: llama.cpp/llama-server b9391 + GGUF (:8088) + mapa de puertos |
| [[concepts/install_model]] | Instalacion portable: ~/.cognia + config.env + apply_config en todos los entry points |
| [[entities/hybrid_router]] | Perfil de corrida por dificultad de TAREA (cero LLM) + /esfuerzo |
| [[concepts/ruteo_hibrido]] | Permiso (ex-ante) vs gasto (reactivo) — el eje del sistema hibrido |
| [[concepts/effort_levels]] | /esfuerzo v2: knobs de modalidad por nivel (colonia, superorganismo, pasos) |
| [[entities/agente]] | Loop ReAct /hacer con formato ACCION + presupuesto dinamico de pasos |
| [[concepts/colonia]] | Cascada reactiva multi-modelo: 3B BoN → 7B → q35 4B → superorganismo |
| [[entities/heavy_code_7b]] | Especialista de capacidad 7B (:8092), lazy-usar-cerrar, +20pp codigo duro |
| [[entities/superorganismo]] | Etapa 4: colonia por pedazos (cartografia + hormigas + feromona) |
| [[entities/portero_05b]] | Portero 0.5B (:8090): turnos sociales/identidad a 4.3x |
| [[entities/fleet_registry]] | Registry N-modelos + router lexico de expertos LoRA (accion) |
| [[entities/oficina]] | Jefe→directores→trabajadores sobre el agente real (:8766) |
| [[concepts/model_router]] | Estimador calibrado de dificultad de codigo (base del eje hibrido) |
| [[concepts/stepwise]] | CoT dirigido por turno (G2R 60→82) + ruteo razonamiento→4B |
| [[concepts/skills_hermes]] | Skills con decay + HERMES self-tooling (crear_herramienta validada) |
| [[concepts/lcd]] | Creador de escenas AI-nativo (tools escena_* + render aproximado) |

## Memoria y cognicion (vigente en el producto)

| Page | One-line |
|---|---|
| [[entities/episodic_fast]] | AttentionSystem con RLock — memoria episodica de corto plazo |
| [[entities/memory_response_engine]] | MemoryContextBuilder — contexto + coverage score |
| [[concepts/sleep_consolidation]] | Pipeline de sueno — emotion wheel + consolidacion episodica |
| [[concepts/fatiga_cognitiva]] | Monitor de carga cognitiva (reset implementado) |
| [[sources/cognia_embedding]] | Embeddings semanticos para busqueda episodica |
| [[entities/cognia_desktop_api]] | FastAPI :8765 para Electron — API distinta de app/main.py (:8000) |

## Capa swarm (opcional / legacy — NO es el camino default)

| Page | One-line |
|---|---|
| [[entities/coordinator]] | Coordinator central del swarm — registra nodos, enruta, tokens |
| [[entities/shard_engine]] | Motor de ejecucion de un shard INT4 numpy en el nodo |
| [[entities/orchestrator]] | Orquesta shards + loop de generacion (hoy: llama.cpp PRIMERO) |
| [[entities/relay]] | WebSocket relay coordinador↔nodos — TTL, evict, clear_cache |
| [[entities/mla_module]] | Multi-head Latent Attention con causal mask y RoPE |
| [[entities/local_adapter]] | ELC — LoRA adapter por usuario, numpy puro |
| [[entities/federated_store]] | FedAvg SOLO sobre deltas LoRA — MIN_CONTRIBUTORS=2 |
| [[entities/router]] | Router LOGOS/TECHNE/RHETOR del path shards (no es el ruteo del producto) |
| [[entities/dynamic_precision]] | DynamicWeights INT4 con 4 tiers y PrecisionManager |
| [[concepts/sharding]] | Division del modelo en N shards distribuidos (fallback) |
| [[concepts/int4_nibble]] | INT4 nibble-packed numpy (cuantizacion del path shards) |
| [[concepts/lpc]] | KV-cache cross-turn del path shards (produccion: cache_prompt de llama-server) |
| [[concepts/elc]] | Personalizacion por usuario via LoRA local |
| [[concepts/federated_learning]] | FedAvg sobre deltas ELC — privacidad por diseno |
| [[concepts/speculative_decoding]] | Linea CERRADA: draft 0.37x / EAGLE3 0.464x; lever real = tamano |
| [[concepts/rst]] | Recursive Summarization Tree — K=2 (no validado) |
| [[concepts/moe_routing]] | MoE 16 expertos del path shards (el mixture real es [[concepts/colonia]]) |
| [[concepts/rope]] | RoPE en MLA — qwen2_ops.py |
| [[concepts/ara]] | Rank expansion ortogonal de LoRA, MAX_RANK=8 |

## Sources (archivos fuente)

| Page | One-line |
|---|---|
| [[sources/model_constants]] | Fuente unica de constantes de arquitectura — nunca hardcodear |
| [[sources/qwen2_ops]] | Ops numpy: RMSNorm, SiLU, RoPE, dequantize (4 tiers de aceleracion) |
| [[sources/shard_engine_src]] | Carga shard INT4, forward pass, hidden states |
| [[sources/orchestrator_src]] | infer(): llama.cpp primero, shard chain fallback |
| [[sources/relay_src]] | WebSocket TTL, mark_failed(), evict loop |

## Comparisons

| Page | One-line |
|---|---|
| [[comparisons/ollama_vs_shards]] | llama.cpp vs shards vs Ollama — prioridad real del backend |
| [[comparisons/lpc_vs_rst]] | LPC (KV-cache) vs RST (resumen recursivo) |
| [[comparisons/elc_vs_fedavg]] | ELC (local LoRA) vs FedAvg (agregacion global) |

## Synthesis

| Page | One-line |
|---|---|
| [[synthesis/inference_pipeline]] | Flujo real de un turno: REPL → hibrido → llama-server → colonia |
| [[synthesis/memory_pipeline]] | Flujo de memoria: episodica → consolidacion → (ELC/FedAvg solo swarm) |
| [[synthesis/security_model]] | Seguridad: bind 127.0.0.1, cifrado DB, auth, sandbox self-tooling |

## Log

→ [[log]]

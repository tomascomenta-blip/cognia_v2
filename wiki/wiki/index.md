# Cognia Wiki — Index

**Topic:** Cognia — Red de inferencia distribuida con federated learning, sharding numpy, memoria episódica y ELC

> Use this index to navigate. Every page links back here.

---

## Entities (sistemas y componentes concretos)

| Page | One-line |
|---|---|
| [[entities/coordinator]] | Coordinator central — registra nodos, enruta inferencia, gestiona tokens |
| [[entities/shard_engine]] | Motor de ejecución de un shard INT4 numpy en el nodo |
| [[entities/orchestrator]] | Orquesta la cadena de shards y el loop de generación token a token |
| [[entities/relay]] | WebSocket relay entre coordinador y nodos — TTL, evict, clear_cache |
| [[entities/mla_module]] | Multi-head Latent Attention con causal mask y RoPE |
| [[entities/local_adapter]] | ELC — LoRA adapter por usuario, numpy puro, kv_proj_out=256 fijo |
| [[entities/federated_store]] | FedAvg engine — agrega gradientes ELC entre nodos, MIN_CONTRIBUTORS=2 |
| [[entities/memory_response_engine]] | Stage 0 del pipeline — coverage score decide si Ollama articula o genera |
| [[entities/episodic_fast]] | AttentionSystem con RLock — memoria episódica de corto plazo |
| [[entities/router]] | MoE router — 16 expertos, top_k=2, asigna LOGOS/TECHNE/RHETOR |
| [[entities/dynamic_precision]] | DynamicWeights drop-in INT4 con 4 tiers y PrecisionManager |
| [[entities/cognia_desktop_api]] | FastAPI :8765 para Electron — API distinta de app/main.py (:8000) |

---

## Concepts (ideas y mecanismos)

| Page | One-line |
|---|---|
| [[concepts/sharding]] | Cómo se divide el modelo en N shards distribuidos |
| [[concepts/int4_nibble]] | Cuantización INT4 nibble-packed sin PyTorch — numpy puro |
| [[concepts/lpc]] | LPC — KV-cache cross-turn para evitar re-procesar prefijo |
| [[concepts/elc]] | ELC — personalización por usuario vía LoRA local sin exponer pesos |
| [[concepts/federated_learning]] | FedAvg sobre deltas ELC — privacidad por diseño |
| [[concepts/speculative_decoding]] | Draft + verify para acelerar generación — compensa lm_head chunked |
| [[concepts/rst]] | Recursive Summarization Tree — K=2, alpha=0.1 (no validado) |
| [[concepts/moe_routing]] | Mixture-of-Experts: LOGOS/TECHNE/RHETOR + top_k=2 |
| [[concepts/rope]] | Rotary Position Embedding en MLA — implementado en qwen2_ops.py |
| [[concepts/fatiga_cognitiva]] | Monitor de carga cognitiva — sin reset de estado (deuda activa) |
| [[concepts/sleep_consolidation]] | Pipeline de sueño — emotion wheel + consolidación episódica |
| [[concepts/ara]] | ARA — Rank expansion ortogonal de LoRA cuando se satura, MAX_RANK=8 |

---

## Sources (archivos fuente del repo)

| Page | One-line |
|---|---|
| [[sources/model_constants]] | Fuente única de verdad de arquitectura — nunca hardcodear |
| [[sources/qwen2_ops]] | Ops numpy: RMSNorm, SiLU, RoPE, dequantize, lm_head chunked |
| [[sources/shard_engine_src]] | Carga shard INT4, ejecuta forward pass, retorna hidden states |
| [[sources/orchestrator_src]] | Loop de generación — sampling, KV-cache, shard chain |
| [[sources/relay_src]] | WebSocket TTL, mark_failed(), evict loop |
| [[sources/cognia_embedding]] | Embeddings semánticos para búsqueda episódica |

---

## Comparisons

| Page | One-line |
|---|---|
| [[comparisons/lpc_vs_rst]] | LPC (KV-cache) vs RST (resumen recursivo) — cuándo usar cada uno |
| [[comparisons/elc_vs_fedavg]] | ELC (local LoRA) vs FedAvg (agregación global) |
| [[comparisons/ollama_vs_shards]] | Cuándo cae a Ollama vs cuándo usa shards propios |

---

## Synthesis

| Page | One-line |
|---|---|
| [[synthesis/inference_pipeline]] | Flujo completo de un token: relay → orchestrator → shards → lm_head |
| [[synthesis/memory_pipeline]] | Flujo de memoria: episódica → consolidación → ELC → FedAvg |
| [[synthesis/security_model]] | Modelo de seguridad: COORDINATOR_KEY, cifrado DB, auth relay |

---

## Log

→ [[log]]

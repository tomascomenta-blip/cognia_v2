---
title: Ollama vs Shards propios — cuándo usa cada uno
type: comparison
tags: [ollama, shards, inference, fallback]
updated: 2026-05-24
---

# Ollama vs Shards propios

→ [[index]]

## Árbol de decisión

```
memory_response_engine.py calcula coverage score
  ├─ Alto → articula desde memoria episódica vía Ollama
  └─ Bajo →
       ├─ _shards_available() == True → genera con shards propios (INT4 numpy)
       └─ _shards_available() == False → Ollama fallback
```

## Cuándo _shards_available() es True

- `SHARD_WEIGHTS_DIR` seteado en `.env`
- Directorio contiene shards + `tokenizer.json`
- Pesos descargados con `convert_hf_to_shards.py`

## Trade-offs

| | Shards propios | Ollama |
|---|---|---|
| Privacidad | Alta — corre local | Depende del endpoint |
| Velocidad | ~0.1 tok/s (sin JIT) | Variable |
| Dependencia | Solo numpy | Ollama instalado |
| Personalización | ELC integrado | No |

## Links

- [[synthesis/inference_pipeline]]
- [[entities/memory_response_engine]]
- [[entities/shard_engine]]

---
title: Cognia Public API
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
app_port: 7860
---

# Cognia Public API

API publica de inferencia distribuida Cognia con shattering architecture.

## Endpoints

- `GET /health` — verificar estado
- `GET /v1/status` — estado del shard y coordinator
- `POST /v1/keys/create` — crear API key (rate: 5/hora por IP)
- `POST /v1/generate` — generar texto (requiere Bearer token)

## Uso desde JavaScript

```javascript
// Crear API key
const keyResp = await fetch('https://YOUR-SPACE.hf.space/v1/keys/create', {
  method: 'POST'
});
const { api_key } = await keyResp.json();

// Generar texto
const resp = await fetch('https://YOUR-SPACE.hf.space/v1/generate', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${api_key}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ prompt: 'Explica la IA en una linea' })
});
const { text, tokens_per_second, source } = await resp.json();
```

## Secrets requeridos en HF Space

| Variable | Descripcion |
|---|---|
| COORDINATOR_KEY | Clave del coordinator Railway |
| HF_TOKEN | Token HuggingFace para descargar shard_0 |

## Keep-alive automatico

Ver `.github/workflows/keepalive_cognia_api.yml` — GitHub Actions cron cada 10 min.

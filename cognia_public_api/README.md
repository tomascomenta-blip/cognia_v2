---
title: Cognia API
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Cognia Public API

FastAPI service exposing Cognia inference via a Railway coordinator proxy,
deployable for free on Hugging Face Spaces.

## Deploy to Hugging Face Spaces (free, no credit card)

1. Create account at huggingface.co (free)
2. New Space → SDK: **Docker** → Hardware: **CPU basic** (free)
3. Upload all files in this directory (`app.py`, `key_store.py`, `inference_proxy.py`,
   `requirements.txt`, `Dockerfile`)
4. Set **Secrets** in Space settings:
   - `COORDINATOR_KEY` — your Railway coordinator key
   - `HF_TOKEN` — your HF token (needed to auto-download `shard_0.npz`)
5. The Space starts automatically. API is available at:
   `https://<username>-cognia-api.hf.space`

The admin API key is printed to the Space logs on first startup — copy it from there.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | none | Liveness check |
| GET | `/v1/status` | none | Shard and coordinator status |
| POST | `/v1/keys/create` | none (5/hour/IP) | Generate a new API key |
| POST | `/v1/generate` | Bearer key (60/min) | Run inference |

## Usage from web pages

```javascript
// 1. Create an API key (once)
const { api_key } = await fetch('https://YOUR-SPACE.hf.space/v1/keys/create', {
  method: 'POST'
}).then(r => r.json());

// 2. Generate text
const response = await fetch('https://YOUR-SPACE.hf.space/v1/generate', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${api_key}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ prompt: 'Hello Cognia!' })
});
const data = await response.json();
console.log(data.text);
```

## API key format

`cogn-` followed by 16 hex characters, e.g. `cogn-a3f7b2c1d9e4f5a6`.

## Local development

```bash
pip install -r requirements.txt
DATA_DIR=. uvicorn app:app --port 7860 --reload
```

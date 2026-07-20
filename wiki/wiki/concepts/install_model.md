---
title: Install Model — instalacion portable en ~/.cognia
type: concept
tags: [install, config.env, gguf, portable, wizard]
updated: 2026-07-16
---

# Install Model

→ [[index]]

## Que es

`cognia/model_install.py` (`cognia install-model`) — el camino DEFAULT de
una instalacion limpia: GGUF 3B Q4_K_M + llama-server b9391 pineado +
fleet de expertos LoRA + portero 0.5B. Reemplaza a los shards NPZ como
primer camino (el pipeline NPZ caia a un tokenizer de simulacion cuando
faltaba tokenizer.json — el bug "el modelo esta descargado pero Qwen no
funciona").

## Layout portable

```
~/.cognia/models/qwen-coder-3b-q4/   GGUF + adapters.json + LoRAs
~/.cognia/models/qwen-0.5b-portero/  portero (opt-out --skip-portero)
~/.cognia/bin/llama-b9391/           llama-server + dlls
~/.cognia/config.env                 LLAMA_GGUF_PATH, LLAMA_SERVER_PATH...
~/.cognia_config.json                estado del REPL (esfuerzo, modo)
```

`apply_config()` carga config.env al arrancar CUALQUIER entry point
(cognia, cognia-node, python -m cognia.cli|tui|doctor|oficina,
node.heavy_code, uvicorn app.main:app — cerrado en 3.9.1). Env vars del
sistema MANDAN sobre config.env (y se avisa cuando pisan un valor).
El wizard (`cognia init`) y install-model escriben config.env con MERGE
(no se pisan entre si).

## Robustez (3.9.1)

Chequeo de espacio en disco antes de descargar, timeout de red + limpieza
de descargas a medias, errores accionables sin traceback, flags con typo
abortan. Flags: `--skip-gguf --skip-server --skip-fleet --skip-portero
--with-heavy-code` (7B ~4.7 GB, opt-in).

## Regla operativa

NO setear env vars LLAMA_* estaticas de usuario/sistema: una LLAMA_LORA_PATH
global mata el hot-swap del fleet. Todo va por config.env.

## Links

- [[entities/llama_backend]]
- [[entities/portero_05b]]
- [[entities/heavy_code_7b]]

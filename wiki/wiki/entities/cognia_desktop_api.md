---
title: cognia_desktop_api — FastAPI para Electron
type: entity
tags: [desktop, electron, fastapi, api, evict]
updated: 2026-05-24
---

# cognia_desktop_api

→ [[index]]

## Qué hace

FastAPI en `:8765` para la app Electron. Es una API **distinta** de `app/main.py` (`:8000`). Spawneada por `cognia_desktop/main.js` al iniciar Electron.

## Archivo fuente

`cognia_desktop_api.py`

## Diferencia con app/main.py

| | cognia_desktop_api.py | app/main.py |
|---|---|---|
| Puerto | 8765 | 8000 |
| Consumidor | Electron (desktop) | Web browser / API externa |
| Spawneado por | cognia_desktop/main.js | uvicorn directo |

## Evict loop

Contiene el loop de evict para el relay (`clear_cache()`) — resuelve la deuda de que `clear_cache()` podía no llamarse al expirar sesión relay.

## Electron — restricciones de seguridad

- `contextIsolation:true`, `nodeIntegration:false`, `webSecurity:true`
- `preload.js` expone solo lo necesario vía `contextBridge`

## Setup wizard

Si `COGNIA_SETUP_DONE` no está en `.env`, `main.js` abre `cognia_desktop/renderer/setup.html`. El wizard registra el nodo y descarga el shard asignado vía `scripts/cognia_setup.py`.

## Links

- [[synthesis/security_model]]
- [[entities/relay]]

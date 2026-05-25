---
title: Modelo de seguridad de Cognia
type: synthesis
tags: [security, auth, encryption, relay, electron]
updated: 2026-05-24
---

# Modelo de seguridad

→ [[index]]

## Variables críticas

| Variable | Riesgo si falta |
|---|---|
| `COORDINATOR_KEY` | CRITICO — endpoints admin abiertos |
| `COGNIA_STRICT_AUTH=1` | ALTO — coordinator acepta inicio sin clave |
| `COGNIA_ENCRYPT_PASSPHRASE` | ALTO — DB en claro |
| `COGNIA_ADMIN_KEY` | ALTO — endpoints GDPR retornan 503 |

## Capas de seguridad

**Relay WebSocket** (`coordinator/relay.py`):
- Valida formato de `session_id`
- Valida bounds de `shard_index`
- TTL + evict loop en `cognia_desktop_api.py`
- `mark_failed()` crítico — no romper

**Endpoints:**
- SQL con `?` bind — no f-strings en queries
- HTML con `escape()` — no XSS
- Sin input de usuario en `subprocess/eval/exec`
- Rutas con `pathlib.is_relative_to`

**Electron:**
- `contextIsolation:true`, `nodeIntegration:false`, `webSecurity:true`
- `preload.js` expone solo lo necesario vía `contextBridge`

**DB:**
- `migrate_db_encrypt.py` — correr para cifrar; warning en `database.py init_db()` si no se hizo

**Key manager:**
- `security/key_manager.py` — leer completo antes de modificar; no loggea claves
- `validate_ollama_url()` antes de nueva conexión Ollama

## Código generado por IA

Sandbox antes de ejecutar. Sandbox sin acceso a red del host. Scraping tratado como hostil.

## Hallazgos

→ `SECURITY_AUDIT.md`. 🔴/🟠 bloquean la tarea. 🟡 documentar y continuar.

## Links

- [[entities/relay]]
- [[entities/coordinator]]

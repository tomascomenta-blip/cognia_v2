---
title: Modelo de seguridad de Cognia
type: synthesis
tags: [security, auth, encryption, relay, electron]
updated: 2026-07-16
---

# Modelo de seguridad

→ [[index]]


## Estado (2026-07-16)

Capas nuevas no listadas abajo: los servers de inferencia locales bindean
explicitamente 127.0.0.1 (llama-server :8088, portero :8090, 7B :8092;
release 3.8.8), fix CSP del desktop (localhost vs 127.0.0.1, 2026-07-15), y
el sandbox del self-tooling ([[concepts/skills_hermes]]: allowlist de
imports + timeout antes de registrar nada auto-generado).
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

# Cognia — Troubleshooting

## Diagnosis

Run `cognia doctor` first. It checks Python version, required packages, the
**GGUF backend** (llama-server + model, the real production stack), Ollama
(optional fallback), `~/.cognia/config.env`, database, and model shards.

---

## Common issues

### "Sin backend de inferencia" / respuestas sin modelo

**Cause:** El stack de inferencia no esta instalado o `config.env` no apunta a el.

**Fix:**
```bash
cognia install-model     # instala GGUF 3B + llama-server + portero a ~/.cognia/
cognia doctor            # verifica el backend
```

Si definiste env vars `LLAMA_*` en el sistema, MANDAN sobre `~/.cognia/config.env`
(el CLI avisa cuando una pisa un valor). En particular, una `LLAMA_LORA_PATH`
residual desactiva el fleet de expertos: borrala.

### CLI shows `[WARNING] module not available`

**Cause:** An optional module (fatigue monitor, planner, curiosity engine) is not installed.

**Fix:** These are optional. Cognia works without them. If you need the module, install its dependencies manually.

### Responses fall back to symbolic mode (legacy Ollama path)

**Cause:** Solo aplica si usas Ollama como fallback: no esta corriendo o falta el modelo.

**Fix:**
```bash
ollama serve                    # start Ollama
ollama pull llama3.2            # pull the required model
```

Check that `OLLAMA_URL` matches the Ollama address. El camino recomendado es
`cognia install-model` (no requiere Ollama).

### `database is locked` errors

**Cause:** Multiple Cognia processes writing to the same SQLite file.

**Fix:** Ensure only one process is running. The WAL journal mode handles concurrent reads but not concurrent writers.

### `SecurityError: KeyManager bloqueado`

**Cause:** The system is locked and requires a passphrase.

**Fix:** From the CLI:
```
Cognia v3> desbloquear <your-passphrase>
```

### Shard workers not connecting

**Cause:** Coordinator URL is wrong or the coordinator is not running.

**Fix:**
1. Verify `COGNIA_COORDINATOR_URL` in `.env`
2. Check coordinator logs: `python -m uvicorn coordinator.app:app --port 8001`
3. Run `cognia doctor` to check connectivity

### `COORDINATOR_KEY is not set` warning in coordinator logs

**Cause:** Admin endpoints are unprotected.

**Fix:** Set a random string in `.env`:
```
COORDINATOR_KEY=<random-32-char-string>
```

### SSE streaming stops mid-response

**Cause:** Electron renderer loses the EventSource connection.

**Fix:** This is a known limitation of the current artificial word-split streaming. Full token-by-token streaming is planned for Phase 7.3 (MLA).

### `Import error: sentence_transformers`

**Cause:** Package not installed.

**Fix:**
```bash
pip install sentence-transformers
```

### DB migration fails with `already encrypted`

**Cause:** `scripts/migrate_db_encrypt.py` is being run on already-encrypted rows.

**Fix:** This is safe — the script is idempotent and skips already-encrypted rows. Run with `--dry-run` to preview.

---

## Logs

Set `COGNIA_LOG_FILE=cognia.log` in `.env` to write logs to disk.

Log level can be configured by setting the `LOG_LEVEL` env var to `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

---

## Reporting issues

Include the output of `cognia doctor` in your report.

https://github.com/tomascomenta-blip/cognia_v2/issues

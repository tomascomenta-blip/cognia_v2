# Cognia — Troubleshooting

## Diagnosis

Run `python scripts/cognia_doctor.py` first. It checks Python version, required packages, Ollama, `.env`, database, and model shards.

---

## Common issues

### CLI shows `[WARNING] module not available`

**Cause:** An optional module (fatigue monitor, planner, curiosity engine) is not installed.

**Fix:** These are optional. Cognia works without them. If you need the module, install its dependencies manually.

### Responses fall back to symbolic mode

**Cause:** Ollama is not running or the model is not pulled.

**Fix:**
```bash
ollama serve                    # start Ollama
ollama pull llama3.2            # pull the required model
```

Check that `OLLAMA_URL` in `.env` matches the Ollama address.

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
3. Run `python scripts/cognia_doctor.py` to check connectivity

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

Include the output of `python scripts/cognia_doctor.py` in your report.

https://github.com/tomascomenta-blip/cognia_v2/issues

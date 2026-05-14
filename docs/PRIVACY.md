# Cognia — Privacy Policy

Last updated: 2026-05-06

## Summary

Cognia is local-first software. Your data stays on your device. No telemetry, no cloud sync, no data sold.

## What data Cognia stores

All data is stored locally in `cognia_memory.db` (SQLite):

- **Episodic memory**: text observations you provide, their embeddings, labels, and emotional scores.
- **Semantic memory**: learned concepts derived from your observations.
- **Knowledge graph**: factual relationships extracted from your inputs.
- **Chat history**: conversation turns (role, content, confidence, feedback).
- **User profile**: preference keys (style, active user ID, personal index).

No data is sent to any external server unless you explicitly configure a coordinator URL.

## Optional external connections

The following are **opt-in** and controlled by `.env`:

| Service | Variable | When active | Data sent |
|---------|----------|-------------|-----------|
| Ollama (local) | `OLLAMA_URL` | Default localhost | Prompts sent to local process only |
| Coordinator swarm | `COGNIA_COORDINATOR_URL` | Only if set | FP16 hidden states (not raw text) |
| HuggingFace | `HF_TOKEN` | Only to download model weights | Auth token only |

## Embeddings

Text is converted to 384-dimensional vectors using `sentence-transformers/all-MiniLM-L6-v2`. This model runs locally. Embeddings are stored in `cognia_memory.db` as JSON arrays.

## Column-level encryption

Sensitive columns (`observation`, `notes`) can be encrypted at rest using AES-256-GCM. Run `scripts/migrate_db_encrypt.py` with a passphrase to encrypt existing data. New data can be encrypted via `SecureEpisodicMemory`.

Without this migration, data is stored in plaintext in the SQLite file.

## Your rights

### Access your data

```
GET /api/user/data/export
X-Admin-Key: <your COGNIA_ADMIN_KEY>
```

Returns all non-forgotten episodic memory as JSON.

### Delete your data

```
DELETE /api/user/data
X-Admin-Key: <your COGNIA_ADMIN_KEY>
```

Marks all episodic memory as forgotten (soft delete). Irreversible via API.

**Single-user limitation:** Cognia does not support multiple isolated user accounts. The delete endpoint removes ALL stored memory with no per-user scoping. If you are running a shared instance, be aware that a single call to this endpoint affects all stored data.

To permanently delete all data: stop Cognia and delete `cognia_memory.db`.

## Data retention

Cognia's sleep consolidation cycle (`cognia dormir`) automatically:
- Weakens low-quality memories (`feedback_weight <= 0.45`)
- Purges very low-quality memories (`feedback_weight <= 0.30, confidence <= 0.40, access_count <= 2`)
- Decays memories not accessed in 14 days

You can trigger this manually at any time.

## Third-party dependencies

Cognia uses open-source libraries only. No analytics SDKs, no error tracking services, no advertising frameworks.

## Contact

Report privacy concerns at: https://github.com/tomascomenta-blip/cognia_v2/issues

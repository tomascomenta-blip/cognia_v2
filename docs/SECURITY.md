# Cognia — Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.8.x   | Yes       |
| < 0.8   | No        |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: anthuangod@gmail.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Affected component(s)
- Potential impact

You will receive a response within 72 hours. If the vulnerability is confirmed, a fix will be released within 14 days for critical issues.

## Security model

### Data at rest

- SQLite database (`cognia_memory.db`) is stored in plaintext by default.
- Column-level AES-256-GCM encryption is available for `episodic_memory.observation` and `episodic_memory.notes` via `scripts/migrate_db_encrypt.py`.
- Key derivation: PBKDF2-HMAC-SHA256 with 600,000 iterations (OWASP 2023 minimum).
- The encryption passphrase is never stored. Only a 32-byte random salt is persisted to disk.

### Network

- All Cognia components run locally by default.
- The coordinator (`coordinator/app.py`) can be deployed to a cloud host. When deployed, set `COORDINATOR_KEY` to protect admin endpoints.
- CORS is restricted to known local origins in the coordinator. Override via `COORDINATOR_ALLOWED_ORIGINS`.

### API security

- Rate limiting is applied to all public coordinator endpoints via `slowapi`.
- Admin endpoints require `X-Coordinator-Key` header matching `COORDINATOR_KEY`.
- FastAPI validation rejects malformed request bodies before they reach application logic.
- Error responses never expose stack traces or internal file paths.

### Dependency management

Run `python scripts/audit_deps.py` to check for known CVEs in installed packages.

In CI, `pip-audit` runs automatically on every push.

## Known limitations

1. **Plaintext DB by default**: Without running the encryption migration, all episodic memory is stored in plaintext. This is a deliberate default for ease of installation; encrypt using `scripts/migrate_db_encrypt.py` for sensitive deployments.

2. **No authentication on local API**: `app/main.py` (web API) has no authentication. It is intended for local use only. Do not expose port 8000 to the internet without adding authentication middleware.

3. **Ollama connection is unauthenticated**: Cognia talks to Ollama on localhost without authentication. This matches Ollama's own security model.

4. **Electron renderer has no CSP**: The Desktop app does not set a Content Security Policy. This is a known gap tracked for Phase 8.6.

## Dependency security

- No analytics or tracking SDKs are included.
- Dependencies are listed in `requirements.txt` with minimum version constraints.
- Run `pip-audit --requirement requirements.txt` to check for known vulnerabilities.

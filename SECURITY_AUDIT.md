# Security Audit — Cognia v3

Audited: 2026-05-15
Scope: data exfiltration risks in coordinator, app API, desktop API, relay, Electron shell.

---

## Findings

### F-01 — WebSocket relay has no authentication (CRITICAL) — PATCHED
**File:** `coordinator/relay.py:195`
**Vector:** Any process on the same network can connect to `/ws/relay/{session_id}/{shard_index}` without a token. If the attacker guesses a valid session_id (or brute-forces the 64-bit space), it can inject forged hidden states into the inference pipeline, capture the last-shard output, or cause denial of service by occupying a shard slot.
**Patch applied:** Session-id format validation (hex-only, 8-64 chars), shard_index bounds check (0 to n_shards-1), and slot-already-taken rejection.
**Residual risk:** The relay still has no cryptographic token per session. The session_id acts as a bearer secret (64-bit entropy). Acceptable for localhost/LAN deployments; for WAN deployments add a signed session token at creation time.

---

### F-02 — `/api/contribution/{node_id}` unauthenticated (HIGH) — PATCHED
**File:** `coordinator/app.py:611`
**Vector:** Any caller can enumerate any node_id to retrieve its ledger entry (tier, total params contributed, requests served). With a guessable or leaked node_id this leaks contributor metadata without auth.
**Patch applied:** Endpoint now requires admin key or the node's own contributor token when COORDINATOR_KEY is set.

---

### F-03 — `federated_contribute` reads full body before size check (HIGH) — PATCHED
**File:** `coordinator/app.py:656`
**Vector:** A contributor with a valid token could POST a several-hundred-MB body. The code called `await request.body()` before checking size, buffering the entire payload in RAM. An attacker with a valid token (or in keyless mode, anyone) could trigger an OOM crash.
**Patch applied:** Content-Length header is checked before reading. After reading, `len(body)` is checked again. Both checks enforce the 512 KB cap.

---

### F-04 — Desktop API CORS allows `file://` and `app://.` origins (HIGH) — PATCHED
**File:** `cognia_desktop_api.py:49`
**Vector:** Any local HTML file opened in the system browser, or a malicious browser extension, can make CORS-credentialed fetch requests to `http://localhost:8765` and read inference results or prompt routing decisions. The Electron renderer never needs CORS access (it goes IPC → ipcMain → HTTP in the main process), so these origins serve no legitimate purpose.
**Patch applied:** `allow_origins` reduced to `["http://localhost:8765", "http://127.0.0.1:8765"]`. `allow_methods` and `allow_headers` narrowed to what endpoints actually use.

---

### F-05 — No strict-mode guard when `COORDINATOR_KEY` is unset (HIGH) — PATCHED
**File:** `coordinator/app.py:101`
**Vector:** When `COORDINATOR_KEY=""`, `require_admin` is a no-op, silently making all admin endpoints public. The prior code only logged a warning. A misconfigured production deploy would silently expose admin APIs.
**Patch applied:** Added `COGNIA_STRICT_AUTH=1` env var. When set, the coordinator refuses to start without `COORDINATOR_KEY`. Warning message updated to list all affected endpoints.

---

### F-06 — `/api/shattering/route` unauthenticated prompt routing disclosure (MEDIUM) — PATCHED
**File:** `coordinator/app.py:429`
**Vector:** Any caller can submit arbitrary prompts and observe which sub-model they route to, plus keyword confidence scores. This leaks behavioral fingerprints of the routing model and can be used to probe decision boundaries.
**Patch applied:** Endpoint now requires admin key or contributor token when COORDINATOR_KEY is set. Rate limit added (30/minute).

---

### F-07 — Prompts in GET query parameters land in server logs (MEDIUM) — PATCHED
**File:** `cognia_desktop_api.py:103` (`/route`), `cognia_desktop_api.py:122` (`/infer-stream`)
**Vector:** User prompts passed as query strings appear in access logs, uvicorn stdout, and any log aggregation pipeline. On a shared machine this leaks conversation content.
**Patch applied:** `max_length=4096` enforced on both GET query params via Pydantic/FastAPI. POST `/infer` model now validates prompt length via `@field_validator`. No structural change to endpoints (changing GET to POST would break the EventSource SSE contract); the length cap limits log exposure surface.
**Residual risk:** Prompts still appear in access logs for GET endpoints. Full mitigation requires changing `/infer-stream` to a POST with SSE, which is a larger refactor.

---

## Not Exploitable (reviewed, low risk)

- `teacher_interface.py:334` — f-string in SQL `WHERE` clause, but called only with hardcoded literals `"accepted=1"` and `"accepted=0"`. Not reachable from user input.
- `cognia/memory/episodic.py:310` — f-string `WHERE` clause with constant `""` or `"WHERE forgotten = 0"`. Not user-controlled.
- `cognia_v3.py:637` — same pattern, constant condition string.
- `node/main.py` — COORDINATOR_URL is from env var only, not user input. No SSRF from user-controlled data.
- `cognia/cognia.py:_try_federated_sync` — COGNIA_COORDINATOR_URL validated indirectly (env var set by operator). COGNIA_CONTRIBUTOR_TOKEN not logged.
- `security/key_manager.py` — passphrase never logged (confirmed by grep). Key derivation uses PBKDF2 600k iterations. Fallback XOR mode documented as degraded.
- `cognia_desktop/main.js` — `contextIsolation:true`, `nodeIntegration:false`, `sandbox:true`. Electron config is correct.
- `coordinator/relay.py` — relay passes bytes without reading content, so no data exfiltration by the coordinator itself.

---

## Remaining Risks (not patched — require larger changes)

| ID | Description | Severity | Why not patched |
|----|-------------|----------|-----------------|
| R-01 | DB not encrypted by default (`migrate_db_encrypt.py` exists but not auto-run) | HIGH | Documented in CLAUDE.md deuda; requires passphrase UX change |
| R-02 | WebSocket relay has no per-session token (session_id is the only secret) | MEDIUM | Acceptable for LAN; WAN deploy should add signed token at session creation |
| R-03 | `/infer-stream` and `/route` prompts appear in access logs | MEDIUM | Full fix requires POST+SSE refactor; scope too large for this audit |
| R-04 | `COGNIA_ADMIN_KEY` empty → GDPR export endpoint returns 503, not a bypass | LOW | Current fail-safe behavior is correct |

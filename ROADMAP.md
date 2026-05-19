# Cognia v2/v3 — Structured Improvement Plan (ROADMAP)

> **Este archivo es la fuente de verdad para el desarrollo de Cognia.**
> Cualquier sesión de Claude Code debe leerlo antes de editar el codigo.
> Marca cada cambio como DONE al completarlo.

---

## Reglas de edicion para Claude Code

- **No crear abstracciones nuevas** sin pedido explícito del usuario.
- **No agregar comentarios** explicando QUE hace el código; solo WHY si no es obvio.
- **No manejo de errores para casos imposibles** — solo en boundaries (input de usuario, APIs externas).
- **No half-implementations** — si se empieza un cambio, se termina completo.
- **Windows CP1252**: todos los print() y strings del CLI deben usar ASCII puro (no emojis, no box-drawing chars, no em-dash —, no flechas →).
- **Tests primero** si el cambio afecta consolidación, VectorCache, o relay.
- Cada cambio tiene **archivos afectados listados** — no tocar otros archivos sin razón.

---

## Context

Cognia is a hybrid symbolic-neural cognitive AI with two major subsystems:
- **Cognia core** (`cognia/`): episodic/semantic memory, knowledge graph, 6-phase sleep consolidation, language engine (5-stage pipeline), FastAPI web layer.
- **Shattering architecture** (`shattering/`, `coordinator/`, `node/`): MoE-style distributed inference across LOGOS / TECHNE / RHETOR sub-models via a WebSocket relay swarm.

Three parallel deep-dive analyses identified **35+ issues** across stability, security, performance, and scalability.
This plan addresses them in strict priority order: crashes first, then security, then speed, then coverage, then scale.

---

## Phase 1 — Critical Stability [DONE - 2026-05-05]

**Goal:** Eliminate bugs that cause crashes or silent data corruption on any real workload.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 1.1 | `feedback_weight` column + schema migration runner | `cognia/database.py` | DONE |
| 1.2 | Ollama circuit breaker (5s timeout, opens after 3 fails, 60s cooldown) + 30s sleep budget | `cognia/reasoning/hypothesis.py`, `cognia/cognia.py`, `cognia/research_engine/researcher.py` | DONE |
| 1.3 | VectorCache `threading.RLock` on build/search/invalidate | `cognia/memory/episodic_fast.py` | DONE |
| 1.4 | Fragment eviction + insert in one lock (TOCTOU race fix) | `shattering/fragment_manager.py` | DONE |
| 1.5 | Background `_cleanup_loop()` purges expired relay sessions every 30s | `coordinator/relay.py`, `coordinator/app.py` | DONE |
| 1.6 | Delete `.tmp` on 4xx HTTP errors; preserve for 5xx/network errors | `node/downloader.py` | DONE |
| 1.7 | Router truncates input to first 2000 chars | `shattering/router.py` | DONE |

---

## Phase 2 — Security Hardening [DONE - 2026-05-05]

**Goal:** Eliminate attack surface on all locally-exposed HTTP services.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 2.1 | CORS restringido a localhost (configurable via COORDINATOR_ALLOWED_ORIGINS) | `cognia_desktop_api.py`, `coordinator/app.py` | DONE |
| 2.2 | `require_admin` en DELETE /node, GET /pending_sessions, POST /shattering/infer | `coordinator/app.py` | DONE |
| 2.3 | Rate limiting slowapi: 200/min register/heartbeat, 60/min session+route, 10/min infer | `coordinator/app.py`, `requirements.txt` | DONE |
| 2.4 | `cryptography>=41.0.0` en requirements; warning mejorado en key_manager | `requirements.txt`, `security/key_manager.py` | DONE |
| 2.5 | `.env.example` con todas las variables; `.env` en .gitignore | `.env.example` (new), `.gitignore` | DONE |

---

## Phase 3 — Performance [DONE - 2026-05-05]

**Goal:** Eliminate the main latency bottlenecks.

### Change 3.1 — VectorCache Batched Invalidation (Debounce)

**Affected Files:** `cognia/memory/episodic_fast.py`, `cognia/memory/episodic.py`

Replace per-store rebuild with a `_dirty` flag + 3-second debounce:
- `mark_dirty()` sets `_dirty = True` + records `_dirty_since`
- `search()`: if dirty AND debounce elapsed → rebuild; else search stale matrix
- `EpisodicMemory.store()` calls `cache.mark_dirty()` instead of `invalidate_cache()`

**Why:** 200 `store()` calls during sleep = 200 full rebuilds. With debounce: max 1 rebuild per 3s.

---

### Change 3.2 — Async Sleep Cycle (Non-Blocking)

**Affected Files:** `cognia/cognia.py`, `app/routes/chat.py`

- Rename `sleep()` → `_sleep_sync()`
- Add `async def sleep(self)` using `run_in_executor(None, self._sleep_sync)`
- Verify `_sleep_sync()` has zero `await` calls
- Add 90-second hard cap via elapsed-time checks at phase boundaries

**Why:** `sleep()` called from FastAPI routes blocks the uvicorn event loop during the entire 30-90s consolidation.

---

### Change 3.3 — O(N log N) Consolidation Similarity

**Affected Files:** `cognia/consolidation_engine.py`

In `_consolidate_batch()`: replace Python double-loop with matrix multiply:
```python
M = np.vstack(vectors)        # (N, D)
norms = np.linalg.norm(M, axis=1, keepdims=True); norms[norms==0] = 1
M /= norms
sim_matrix = M @ M.T          # (N, N) — BLAS-optimized
pairs = np.argwhere(sim_matrix > threshold)
# limit to top 500 pairs by similarity
```

**Why:** 200 episodes = 19,900 Python-loop iterations → BLAS matrix multiply is 10-50x faster.

---

### Change 3.4 — Model Config Cache TTL

**Affected Files:** `node/inference_pipeline.py`

In `_get_model_config()`: store `(cfg, time.monotonic())` tuple; re-fetch after 300s.
Add `invalidate_config_cache()` for callers that know the coordinator changed.

---

## Phase 4 — Test Coverage & CI [DONE - 2026-05-06]

**Goal:** Establish a test baseline for every critical subsystem.

### Change 4.1 — Shattering Test Suite

**Affected Files:** `tests/test_shattering.py` (new)

Tests to cover:
- `GlobalRouter.route()`: TECHNE for code, LOGOS for philosophy, RHETOR for essays, fallback for empty, no crash on 10k char input
- `ShatteringOrchestrator`: init with file path + app_id; infer() returns InferResult; simulation non-empty; route_only(); status()
- `FragmentManager`: load 2 sub-models; 3rd triggers LRU eviction; is_loaded(); evict()
- `MoELayer` (simulation=True): shape preserved, aux_loss in [0,3], routing_stats total == seq_len, reset_stats() zeroes, top_k=2 works
- `ManifestLoader`: loads all 5 JSON manifests; fragments_for_sub_model() correct count; ${ENV_VAR} resolved

---

### Change 4.2 — Consolidation Engine Test Suite

**Affected Files:** `tests/test_consolidation.py` (new)

Tests to cover:
- `init_db()` fresh: feedback_weight column exists
- `init_db()` on old DB missing column: migration adds it
- `_phase_purge()`: low-importance episodes marked forgotten
- `_phase_weaken()`: importance decreases
- `_phase_consolidate()`: near-identical episodes merged
- `run_full_cycle()` with Ollama mocked: no crash, returns dict
- `run_full_cycle()` empty DB: no crash

---

### Change 4.3 — GitHub Actions CI Pipeline

**Affected Files:** `.github/workflows/ci.yml` (new)

- Trigger: push + PR on `main`
- Matrix: Python 3.11, 3.12
- Steps: checkout → pip install -r requirements.txt → pytest tests/ -x --tb=short
- pip cache keyed on requirements.txt hash

---

## Phase 5 — Scalability & Feature Completeness [DONE - 2026-05-06]

### Change 5.1 — Router Keyword Table Expansion

**Affected Files:** `shattering/router.py`

**TECHNE additions:** `"model"`, `"training"`, `"neural"`, `"tensor"`, `"gpu"`, `"machine learning"`, `"deep learning"`, `"django"`, `"fastapi"`, `"react"`, `"vue"`, `"kubernetes"`, `"serverless"`, `"pandas"`, `"numpy"`, `"spark"`, `"postgresql"`, `"mongodb"`, `"llm"`, `"fine-tune"`, `"embedding"`

**RHETOR additions:** `"marketing"`, `"campaign"`, `"brand"`, `"pitch"`, `"copywriting"`, `"proposal"`, `"memo"`, `"screenplay"`, `"dialogue"`, `"documentation"`, `"manual"`, `"guide"`, `"tutorial"`, `"specification"`, `"redactar"`, `"propuesta"`, `"ensayo"`, `"borrador"`, `"introduccion"`

**LOGOS additions:** `"algebra"`, `"calculus"`, `"geometry"`, `"proof"`, `"physics"`, `"chemistry"`, `"biology"`, `"quantum"`, `"ethics"`, `"sociology"`, `"economics"`, `"estadistica"`, `"demostrar"`, `"analizar"`, `"explicar"`

Add `router_version = "1.1"` constant.

---

### Change 5.2 — Centralise Model Architecture Constants

**Affected Files:** `shattering/model_constants.py` (new), `shattering/fragment_manager.py`, `coordinator/registry.py`, `node/downloader.py`, `shattering/moe_layer.py`, `node/inference_pipeline.py`

New file:
```python
LLAMA_32_3B = {
    "total_layers": 28, "hidden_dim": 3072, "intermediate_dim": 8192,
    "n_shards": 4, "layers_per_shard": 7, "vocab_size": 32000,
    "size_per_shard_gb": 0.40, "params_b": 3.2
}
```

After refactor: grep for `3072` and `32000` should return zero results in the 5 affected files.

---

### Change 5.3 — Streaming Inference in Desktop App

**Affected Files:** `cognia_desktop_api.py`, `cognia_desktop/preload.js`, `cognia_desktop/renderer/app.js`, `cognia_desktop/main.js`, `requirements.txt`

- Add `sse-starlette>=1.6` to requirements.txt
- `GET /infer-stream?prompt=...` → EventSourceResponse; each event `{"token": "...", "done": false}`; final `{"done": true, "sub_model": ..., "latency_ms": ...}`
- `window.cognia.inferStream(prompt, onToken, onDone)` via EventSource in preload.js
- Replace `window.cognia.infer()` with inferStream in app.js — append each token as it arrives

---

### Change 5.4 — MoE Expert Load Imbalance Monitoring

**Affected Files:** `shattering/moe_layer.py`, `shattering/orchestrator.py`

Add `check_balance(warn_threshold=2.0) -> dict` to `MoELayer`:
- Computes `fraction / expected` per expert
- Logs WARNING if any expert > 2x expected load
- Returns `{"imbalance_ratios": {...}, "max_ratio": float}`

Call from `ShatteringOrchestrator.status()` → appears in `/status` automatically.

---

### Change 5.5 — Readiness Probes for Production Deployment

**Affected Files:** `coordinator/app.py`, `cognia_desktop_api.py`, `railway.toml`

- `GET /ready` (coordinator): SELECT 1 on registry DB + check cleanup_task running → 200 / 503
- `GET /ready` (desktop API): `_orch.status()` without exception → 200 / 503
- Update `railway.toml`: `healthcheckPath = "/ready"`
- Exclude `/ready` from rate limiting (Change 2.3)

---

## Phase 6 — Advanced Optimization [DONE - 2026-05-06]

### Change 6.1 — FAISS Approximate Nearest Neighbour

**Affected Files:** `cognia/memory/episodic_fast.py`, `requirements.txt`

In `VectorCache.build()`: after building `_matrix`, try `import faiss`; if available build `IndexFlatIP` + add all vectors. In `search()`: use `_faiss_index.search(query_vec, top_k)` if available.
Add `# faiss-cpu>=1.7.4  # optional: faster episodic search at scale` to requirements.txt.

---

### Change 6.2 — SHA256 Checksums Automation Script

**Affected Files:** `scripts/generate_manifest_checksums.py` (new)

Script `--manifest <path> --hf-token <token>`: downloads each shard, computes SHA256, patches manifest JSON in-place. Run once when publishing weights to HuggingFace. Until then, `"sha256": ""` is correct.

---

### Change 6.3 — Dockerfile + docker-compose

**Affected Files:** `Dockerfile` (new), `docker-compose.yml` (new), `.dockerignore` (new)

- Multi-stage Dockerfile: `python:3.12-slim`, exposes 8000
- docker-compose: `cognia`, `coordinator`, optional `ollama` services; mounts `./model_shards`
- .dockerignore: `__pycache__/`, `*.db`, `model_shards/`, `venv/`

---

### Change 6.4 — Prometheus Metrics

**Affected Files:** `app/main.py`, `coordinator/app.py`, `cognia/cognia.py`, `coordinator/relay.py`, `requirements.txt`

- Add `prometheus-fastapi-instrumentator>=6.1`
- Custom counters: `cognia_sleep_cycles_total`, `cognia_episodes_stored_total`, `cognia_ollama_errors_total`, `shattering_infer_requests_total{sub_model}`, `relay_sessions_active`
- Exclude `/metrics` from rate limiting

---

## Phase 7 -- SRDN: Sparse-Recursive Distillation Network [DONE - 2026-05-06]

**Goal:** Evolve the simulation-mode Shattering architecture into a trainable,
memory-efficient inference system: four structural improvements plus a self-distillation
pipeline that leverages the existing episodic memory and consolidation output.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 7.1 | Neural Precision Quantization (NPQ): INT8 for critical shards (0,3), ternary 1.58-bit for factual shards (1,2); pure numpy, no new ML deps | `shattering/moe_layer.py`, `shattering/fragment_manager.py`, `shattering/model_constants.py`, `shattering/quantization.py` (new) | DONE |
| 7.2 | Recursive Shared Transformers (RST): configurable K-pass recursion on existing shard chain with 3072-dim context vector injection and alpha=0.1 residual scale | `node/inference_pipeline.py`, `shattering/orchestrator.py`, `shattering/model_constants.py`, `shattering/recursive_context.py` (new) | DONE |
| 7.3 | Multi-Head Latent Attention (MLA): compressed KV cache d_c=512 replacing stateless attention; ShardEngine gains per-session _kv_cache dict | `node/shard_engine.py`, `node/inference_pipeline.py`, `shattering/mla.py` (new) | DONE |
| 7.4 | Micro-MoE: expand 3 experts to 16 (domain-clustered: logos 0-4, techne 5-9, rhetor 10-15), top_k=2, intermediate_dim=4096 per expert | `shattering/moe_layer.py`, `shattering/model_constants.py` | DONE |
| 7.5 | Distillation Pipeline: Ollama teacher + consolidation-episode gold data + feedback_weight-weighted loss (0.7 sequence_level + 0.3 consistency) | `shattering/distillation/__init__.py` (new), `shattering/distillation/data_generator.py` (new), `shattering/distillation/losses.py` (new), `shattering/distillation/trainer.py` (new) | DONE |

### Fase 7 -- Informacion faltante / Decisiones pendientes

1. n_heads, n_kv_heads, head_dim NOT in model_constants.py. MLA calculations assume
   Llama 3.2 standard values (n_heads=24, n_kv_heads=8, head_dim=128). Must be verified
   against the actual HF model config before implementing 7.3.

2. torch/transformers versions not pinned in requirements.txt. shard_engine.py uses
   torch.float16 and HuggingFace AutoModel -- exact versions matter for GQA support.
   Decision: pin torch>=2.1.0, transformers>=4.40.0 in requirements.txt when first needed.

3. 128 experts is not feasible within memory targets (Android <=1.5 GB, PC <=4 GB).
   Plan uses 16 experts as practical target. Scaling to 128 requires expert sharding
   with lazy per-cluster loading -- design deferred.

4. Ollama teacher limitation: attention transfer and hidden state alignment losses
   require internal model access not available from Ollama API (text output only).
   Full feature-level distillation deferred to a sub-phase with torch-accessible teacher.

5. Real weights do not exist. All 7.1-7.4 changes run on simulation-mode infrastructure
   and cannot be tested end-to-end until real shard.safetensors weights exist.

6. RST optimal hyperparameters (K passes, alpha scale) are empirical. Defaults K=2,
   alpha=0.1; actual optimal values require ablation once real weights are available.

7. MLA adds per-session state to ShardEngine (currently stateless). ShardEngine.clear_cache
   must be called on relay session expiry to prevent unbounded memory growth.

---

## Phase 8 -- Commercial Release [DONE - 2026-05-07]

**Goal:** Make Cognia installable, trustworthy, and ready for external users: one-command
setup, data privacy controls, encrypted storage by default, user-facing language throughout
the UI, and distributable installers with code signing.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 8.1 | Installer: one-command setup scripts for Windows and Linux/macOS + cognia doctor diagnostics command | `install.ps1` (new), `install.sh` (new), `scripts/cognia_doctor.py` (new), `cognia/cli.py` | DONE |
| 8.2 | UX Messages: replace all internal/technical strings in UI and backend with user-facing language; centralize in messages.py | `cognia/ux/__init__.py` (new), `cognia/ux/messages.py` (new), `cognia_desktop/renderer/app.js`, `cognia_desktop/renderer/index.html`, `cognia_desktop/main.js`, `cognia_desktop_api.py`, `node/shard_engine.py` | DONE |
| 8.3 | Security: encrypt cognia_memory.db by default; COORDINATOR_KEY mandatory; suppress raw exc in API error responses; add data export/delete endpoints; dependency audit script + CI check | `cognia/database.py`, `security/key_manager.py`, `scripts/migrate_db_encrypt.py` (new), `app/routes/user_data.py` (new), `app/main.py`, `cognia_desktop/renderer/index.html`, `cognia_desktop/renderer/app.js`, `scripts/audit_deps.py` (new), `coordinator/app.py`, `.github/workflows/ci.yml`, `requirements.txt` | DONE |
| 8.4 | Update mechanism: cognia update command + versioned migration runner for DB schema evolution | `scripts/cognia_update.py` (new), `cognia/migrations/__init__.py` (new), `cognia/migrations/runner.py` (new), `cognia/database.py` | DONE |
| 8.5 | Documentation: INSTALL.md, PRIVACY.md, TROUBLESHOOTING.md, SECURITY.md; updated README | `README.md`, `docs/INSTALL.md` (new), `docs/PRIVACY.md` (new), `docs/TROUBLESHOOTING.md` (new), `docs/SECURITY.md` (new) | DONE |
| 8.6 | Packaging: Electron signed installer via electron-builder; release build scripts; crash reporter suppression in packaged mode | `cognia_desktop/package.json`, `cognia_desktop/electron-builder.config.js` (new), `scripts/build_release.ps1` (new), `scripts/build_release.sh` (new), `cognia_desktop/renderer/app.js`, `cognia_desktop_api.py` | DONE |

### Fase 8 -- Decisiones pendientes (resolucion en fases 9-12)

1. keyring in headless: resolved — env var passphrase via COGNIA_ENCRYPT_PASSPHRASE.
2. Encryption migration strategy: resolved — separate migrate_db_encrypt.py, interactive.
3. HF model repos: out of scope; installers document this gap explicitly.
4. Code signing: deferred — electron-builder.config.js ready; certificates not purchased.
5. Auto-update: resolved in Phase 11 — electron-updater + GitHub Releases.
6. cognia doctor scope: resolved — checks Python, packages, Ollama, .env, DB, model_shards.
7. Multi-user isolation: resolved in Phase 12 — prominent warning added to endpoint + docs.
8. Production log level: resolved in Phase 12 — WARNING level when COGNIA_PACKAGED=1.

---

## Phase 9 -- Security Hardening (pre-public launch) [DONE - 2026-05-06]

**Goal:** Close exploitable attack surface before any public exposure.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 9.1 | SQL injection: emotion_filter parameterized | `cognia/memory/episodic.py` | DONE |
| 9.2 | XSS in Electron renderer: innerHTML → DOM API | `cognia_desktop/renderer/app.js` | DONE |
| 9.3 | CORS wildcard → explicit localhost origins | `app/main.py` | DONE |
| 9.4 | Prompt injection: structural delimiters in hypothesis generation | `cognia/reasoning/hypothesis.py` | DONE |
| 9.5 | Optional API key auth on web_app.py (X-Api-Key + COGNIA_WEB_API_KEY) | `web_app.py` | DONE |
| 9.6 | Feedback rate limiting + duplicate prevention (60s window, 10 calls) | `cognia/cognia.py` | DONE |
| 9.7 | SSRF: validate OLLAMA_URL to localhost only | `security/ollama_url.py` (new), `cognia/language_engine.py`, `shattering/orchestrator.py` | DONE |
| 9.T | Test suite: 20 new tests covering 9.1, 9.5, 9.6, 9.7 | `tests/test_phase9_security.py` (new) | DONE |

---

## Phase 10 -- Beta Onboarding [DONE - 2026-05-07]

**Goal:** First-time user experience: actionable errors, privacy consent, feedback channel.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 10.1 | Ollama detection: /ready returns {status, ollama, model} + actionable UI instructions | `cognia_desktop_api.py`, `cognia_desktop/main.js`, `cognia_desktop/renderer/app.js` | DONE |
| 10.2 | cognia_doctor: check_ollama_model() verifies model is downloaded | `scripts/cognia_doctor.py` | DONE |
| 10.3 | First-run privacy consent modal (localStorage gate) | `cognia_desktop/renderer/index.html`, `cognia_desktop/renderer/app.js`, `cognia_desktop/renderer/style.css` | DONE |
| 10.4 | In-app feedback button → GitHub Issues | `cognia_desktop/preload.js`, `cognia_desktop/main.js`, `cognia_desktop/renderer/index.html` | DONE |

---

## Phase 11 -- Beta Distribution [DONE - 2026-05-07]

**Goal:** Enable binary distribution and auto-updates via GitHub Releases.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 11.1 | Auto-update: electron-updater + GitHub Releases provider | `cognia_desktop/package.json`, `cognia_desktop/electron-builder.config.js`, `cognia_desktop/main.js`, `cognia_desktop/renderer/app.js` | DONE |
| 11.2 | Release CI: GitHub Actions builds Windows (.exe) and Linux (.AppImage) on tags v* | `.github/workflows/release.yml` (new) | DONE |
| 11.3 | Docs: download section with platform table in README and INSTALL.md | `README.md`, `docs/INSTALL.md` | DONE |

---

## Phase 12 -- Production Hardening [DONE - 2026-05-07]

**Goal:** Resolve all pending decisions from Phases 7-8; address MLA memory leak.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 12.1 | MLA KV-cache TTL eviction: evict_stale() in CompressedKVCache; call in ShatteringOrchestrator.status() | `shattering/mla.py`, `shattering/orchestrator.py` | DONE |
| 12.2 | Pin torch>=2.1.0 and transformers>=4.40.0 as optional deps in requirements.txt | `requirements.txt` | DONE |
| 12.3 | Production log level: root logger set to WARNING when COGNIA_PACKAGED=1 | `cognia_desktop_api.py` | DONE |
| 12.4 | Multi-user isolation: scope/warning fields in DELETE /user/data response + PRIVACY.md note | `app/routes/user_data.py`, `docs/PRIVACY.md` | DONE |
| 12.T | Test suite: 12 tests covering MLA eviction and user data endpoint | `tests/test_phase12.py` (new) | DONE |

---

## Phase 13 -- Real Distributed Inference (Qwen2.5-Coder-3B INT4) [DONE - 2026-05-07]

**Goal:** Replace the Llama 3.2-3B simulation with real distributed inference using
Qwen2.5-Coder-3B-Instruct. Weights are auto-sharded across devices, quantized to INT4
on each node, and the system returns articulated natural language via autoregressive
sampling from actual LM-head logits.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 13.1 | INT4 nibble-packed quantization (per-row symmetric, 50% smaller than INT8) | `shattering/quantization.py` | DONE |
| 13.2 | Qwen2.5-Coder-3B architecture constants (36 layers, GQA, vocab=151936, rope_theta=1M) | `shattering/model_constants.py` | DONE |
| 13.3 | Qwen2 numpy forward pass: RMSNorm, RoPE, GQA, SwiGLU; no PyTorch dependency | `node/qwen2_ops.py` (new), `node/shard_engine.py` | DONE |
| 13.4 | Inference pipeline: ChatML template, PTYPE_TOKENS/PTYPE_LOGITS protocol, Qwen EOS | `node/inference_pipeline.py` | DONE |
| 13.5 | Register Qwen model in coordinator and downloader catalogs | `coordinator/registry.py`, `node/downloader.py` | DONE |
| 13.6 | 4-shard manifest for Qwen2.5-Coder-3B-Instruct INT4 | `shattering/manifests/cognia_qwen.json` (new) | DONE |
| 13.7 | HF-to-shard converter: downloads + INT4-quantizes HF checkpoint → .npz shards | `scripts/convert_hf_to_shards.py` (new) | DONE |

**How to use:**

```
# 1. Download the model from HuggingFace (requires huggingface-cli or manual download)
huggingface-cli download Qwen/Qwen2.5-Coder-3B-Instruct --local-dir /path/to/qwen

# 2. Convert to INT4 shards (one time; ~300 MB per shard)
python scripts/convert_hf_to_shards.py \
    --hf-dir /path/to/qwen \
    --out-dir model_shards/qwen-coder-3b-q4

# 3. Point ShardEngine at the shard directory and start nodes
#    Each device runs node/main.py with its shard index
```

---

## Phase 14 — Federated Learning [DONE - 2026-05-11]

**Goal:** Enable the network to learn collectively without centralizing user data.
Each node contributes LoRA adapter updates; the coordinator runs FedAvg.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 14.1 | FederatedStore: FedAvg engine + SQLite BLOB storage; validation, LRU cap, weighted aggregation | `coordinator/federated_store.py` (new) | DONE |
| 14.2 | Three federated endpoints in coordinator: contribute, global, stats | `coordinator/app.py` | DONE |
| 14.3 | ELC sleep cycle: submit noisy adapter, download and cache global adapter | `cognia/cognia.py` | DONE |

**Design decisions:**
- FedAvg weight = tier's min_params_b (basic=0.5, standard=1.0, premium=3.0)
- Client-side Gaussian noise sigma=0.01 before submission (privacy, not formal DP)
- MIN_CONTRIBUTORS=2 before first aggregation (one node cannot define the global model)
- Federated mode is opt-in via env vars; absent vars = silent no-op during sleep
- No new dependencies: stdlib urllib.request for HTTP, numpy already required

---

## Phase 16 — Dynamic Quantization [DONE - 2026-05-11]

**Goal:** Weight matrices promote precision in RAM based on access frequency.
Frequently-used weights stay cached at FP32 (no dequant overhead); idle weights
return to INT4 (minimum RAM footprint).

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 16.1 | Threshold constants | `shattering/model_constants.py` | DONE |
| 16.2 | DynamicWeights + PrecisionManager | `shattering/dynamic_precision.py` (new) | DONE |
| 16.3 | ShardEngine wraps every INT4Weights; decay_precision() + precision_stats() | `node/shard_engine.py` | DONE |
| 16.4 | Orchestrator.decay_precision() delegates to all loaded engines | `shattering/orchestrator.py` | DONE |

**Design decisions:**
- DynamicWeights is a drop-in for INT4Weights (same .linear(x) signature) — RealTransformerLayer unchanged
- Tiers: INT4 (< 5 hits, no cache) → INT8 (5-14, int8+scale) → FP16 (15-29, float16) → FP32 (≥ 30, direct matmul)
- Auto-decay after 300s idle: counter resets on next linear() call (no background thread needed)
- Embedding table stays float32 (already dequantized at load time, not tracked)
- Thread-safe: RLock per DynamicWeights; matmul runs outside the lock to allow parallelism
- Sleep-cycle hook: call orchestrator.decay_precision() to force immediate cache drop

---

## Phase 15 — Emotion Wheel: procesamiento emocional nocturno [DONE - 2026-05-11]

**Goal:** Complete the sleep cycle with Plutchik-based emotional processing.
Analyzes accumulated episodic emotions, detects imbalances, and modulates importance.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 15.1 | EmotionWheelProcessor: Plutchik 8-primary distribution, imbalance detection, importance modulation | `cognia/memory/emotion_wheel.py` (new) | DONE |
| 15.2 | Integration as PASO 8 in _sleep_sync(); one-line summary in sleep output | `cognia/cognia.py` | DONE |

**Design decisions:**
- Weight per episode = abs(emotion_score) * importance (high-importance emotional episodes dominate)
- Modulation factors: 1.08 positive (reinforce), 0.92 negative (anti-rumination); clamped [0.1, 3.0]
- Dominance threshold: 15% minimum share to declare a dominant emotion
- Imbalance triggers: negative dominant >35% with opposite <10%; or joy+trust >70% combined
- No LLM calls, no new dependencies; runs bounded by LIMIT 500 + 24h window
- Failure is always silent (try/except around the entire block)

---

## Phase 17 — Contribution Economy: enforcement de tier y RPM [DONE - 2026-05-12]

**Goal:** Close the disk-contribution → tier → API-priority circuit. Data existed in
the ledger; this phase adds the enforcement gate so tiers actually restrict access.

| Change | Description | Files | Status |
|--------|-------------|-------|--------|
| 17.1 | SlidingWindowLimiter — sliding window 60s por node_id | `coordinator/rate_limiter.py` (new) | DONE |
| 17.2 | Standard tier includes Shattering sub-models in allowed_models | `coordinator/contributor.py` | DONE |
| 17.3 | allowed_models gate + per-node RPM check in shattering_infer | `coordinator/app.py` | DONE |

**Design decisions:**
- Tier progression: basic=qwen only (10 RPM), standard=all+shattering (30 RPM), premium=* (100 RPM)
- RPM limit keyed by node_id (not IP) — multiple nodes behind NAT get independent budgets
- slowapi IP limit stays as a hard DDoS backstop; per-node limit is the economic enforcement
- Admin role and anon mode (COORDINATOR_KEY unset) bypass both gates — dev/test unaffected
- No Redis dep: in-process deque per key, O(RPM) memory per node, trivial at expected scale

---

## Execution Order

| Phase | Focus | Status |
|-------|-------|--------|
| 1 — Stability | Crash fixes + race conditions | DONE |
| 2 — Security | CORS, auth, deps | DONE |
| 3 — Performance | Async sleep, cache debounce, O(N^2) fix | DONE |
| 4 — Tests + CI | Coverage for shattering + consolidation | DONE |
| 5 — Scalability | Router expansion, streaming, monitoring | DONE |
| 6 — Advanced | FAISS, Docker, Prometheus | DONE |
| 7 — SRDN | NPQ, RST, MLA, Micro-MoE, Distillation | DONE |
| 8 — Commercial Release | Installer, UX, Security, Docs, Packaging | DONE |
| 9 — Security Hardening | SQL injection, XSS, CORS, prompt injection, SSRF | DONE |
| 10 — Beta Onboarding | Ollama detection, privacy consent, feedback | DONE |
| 11 — Beta Distribution | Auto-update, release CI, download docs | DONE |
| 12 — Production Hardening | MLA TTL eviction, log level, multi-user warning, dep pinning | DONE |
| 13 — Real Distributed Inference | Qwen2.5-Coder-3B INT4, auto-sharding, articulated output | DONE |
| 14 — Federated Learning | FedAvg sobre LoRA adapters, endpoints en coordinador, privacidad cliente | DONE |
| 15 — Emotion Wheel | Plutchik nocturnal processing, imbalance detection, importance modulation | DONE |
| 16 — Dynamic Quantization | INT4/INT8/FP16/FP32 por frecuencia de acceso, auto-decay, PrecisionManager | DONE |
| 17 — Contribution Economy | allowed_models gate + RPM sliding window por node_id en shattering/infer | DONE |
| 18 — Sandbox real | AST analysis + runtime __import__ guard; elimina regex bypasseable | DONE |
| 19 — ARA | Adaptive Rank Amplification: saturacion detectada, expansion ortogonal, FedAvg variable-rank | DONE |
| 20 — Innovacion arquitectural | Routing semantico, LPC/Semantic Persistence, DUS scale-up, Fed Distillation | TODO |

---

## Phase 20 — Arquitectura Diferencial [TODO]

**Goal:** Reemplazar decisiones de diseno primitivas con mecanismos que diferencian a Cognia
de los LLMs convencionales, sin requerir PyTorch ni infraestructura nueva.

| Change | Description | Files | Status |
|---|---|---|---|
| 20.1 | Semantic router: reemplaza keyword matching en router.py con similitud coseno sobre embeddings del VectorCache; umbral configurable en model_constants.py | `shattering/router.py`, `shattering/model_constants.py`, `cognia/memory/episodic_fast.py` | TODO |
| 20.2 | Latent Persistence Cache (LPC): cachear el hidden state comprimido del ultimo shard por session_id; en requests subsiguientes inyectarlo como contexto residual en lugar de recalcular desde token 0 | `shattering/mla.py`, `node/shard_engine.py`, `shattering/orchestrator.py` | TODO |
| 20.3 | Depth Up-Scaling (DUS) para shards: fusionar dos shards adyacentes (interpolacion alpha de sus capas) para generar un shard de mayor profundidad sin reentrenamiento completo; util para nodos con mas RAM disponible | `scripts/scale_shards.py` (new), `shattering/model_constants.py` | TODO |
| 20.4 | Federated Knowledge Distillation: en lugar de promediar deltas LoRA crudos, el coordinador extrae representaciones semanticas de cada contribucion y agrega en espacio de embeddings antes de proyectar de vuelta a LoRA | `coordinator/federated_store.py`, `coordinator/app.py` | TODO |
| 20.5 | MLA correccion arquitectural: MLA_N_HEADS_ASSUMED y MLA_N_KV_HEADS_ASSUMED usan valores de Llama (24/8); deben actualizarse a Qwen2.5-3B (16/2) y MLA_D_C recalcularse como hidden_dim // n_kv_heads = 1024 | `shattering/model_constants.py`, `shattering/mla.py` | TODO |

## Critical Files Map

| Change | Primary Files |
|--------|--------------|
| 1.1 Schema migration | `cognia/database.py` |
| 1.2 Ollama circuit breaker | `cognia/reasoning/hypothesis.py`, `cognia/cognia.py` |
| 1.3 VectorCache lock | `cognia/memory/episodic_fast.py` |
| 1.4 Fragment eviction lock | `shattering/fragment_manager.py` |
| 1.5 Session cleanup | `coordinator/relay.py`, `coordinator/app.py` |
| 1.6 Downloader 4xx cleanup | `node/downloader.py` |
| 1.7 Router truncation | `shattering/router.py` |
| 2.1 CORS restrict | `cognia_desktop_api.py`, `coordinator/app.py` |
| 2.2 Admin auth | `coordinator/app.py` |
| 2.3 Rate limiting | `coordinator/app.py`, `requirements.txt` |
| 2.4 cryptography dep | `requirements.txt` |
| 2.5 .env.example | `.env.example` (new) |
| 3.1 Cache debounce | `cognia/memory/episodic_fast.py`, `cognia/memory/episodic.py` |
| 3.2 Async sleep | `cognia/cognia.py`, `app/routes/chat.py` |
| 3.3 O(N log N) consolidation | `cognia/consolidation_engine.py` |
| 3.4 Config TTL | `node/inference_pipeline.py` |
| 4.1 Shattering tests | `tests/test_shattering.py` (new) |
| 4.2 Consolidation tests | `tests/test_consolidation.py` (new) |
| 4.3 GitHub Actions | `.github/workflows/ci.yml` (new) |
| 5.1 Router expansion | `shattering/router.py` |
| 5.2 Model constants | `shattering/model_constants.py` (new) + 5 files |
| 5.3 Streaming | `cognia_desktop_api.py`, `cognia_desktop/*` |
| 5.4 MoE monitoring | `shattering/moe_layer.py`, `shattering/orchestrator.py` |
| 5.5 Readiness probes | `coordinator/app.py`, `cognia_desktop_api.py` |
| 6.1 FAISS | `cognia/memory/episodic_fast.py` |
| 6.2 Checksum script | `scripts/generate_manifest_checksums.py` (new) |
| 6.3 Docker | `Dockerfile`, `docker-compose.yml` (new) |
| 6.4 Prometheus | `app/main.py`, `coordinator/app.py`, `requirements.txt` |
| 7.1 NPQ | `shattering/quantization.py` (new), `shattering/moe_layer.py` |
| 7.2 RST | `node/inference_pipeline.py`, `shattering/recursive_context.py` (new) |
| 7.3 MLA | `shattering/mla.py` (new), `node/shard_engine.py` |
| 7.4 Micro-MoE | `shattering/moe_layer.py`, `shattering/model_constants.py` |
| 7.5 Distillation | `shattering/distillation/` (new package, 4 files) |
| 8.1 Installer | `install.ps1` (new), `install.sh` (new), `scripts/cognia_doctor.py` (new) |
| 8.2 UX Messages | `cognia/ux/messages.py` (new), `cognia_desktop/renderer/app.js`, `cognia_desktop/main.js` |
| 8.3 Security | `cognia/database.py`, `security/key_manager.py`, `app/routes/user_data.py` (new), `scripts/migrate_db_encrypt.py` (new) |
| 8.4 Update mechanism | `scripts/cognia_update.py` (new), `cognia/migrations/runner.py` (new), `cognia/database.py` |
| 8.5 Documentation | `docs/INSTALL.md` (new), `docs/PRIVACY.md` (new), `docs/TROUBLESHOOTING.md` (new), `docs/SECURITY.md` (new) |
| 8.6 Packaging | `cognia_desktop/electron-builder.config.js` (new), `scripts/build_release.ps1` (new), `scripts/build_release.sh` (new) |
| 9.1 SQL injection | `cognia/memory/episodic.py` |
| 9.2 XSS | `cognia_desktop/renderer/app.js` |
| 9.3 CORS | `app/main.py` |
| 9.4 Prompt injection | `cognia/reasoning/hypothesis.py` |
| 9.5 API key auth | `web_app.py` |
| 9.6 Feedback rate limit | `cognia/cognia.py` |
| 9.7 SSRF OLLAMA_URL | `security/ollama_url.py` (new), `cognia/language_engine.py` |
| 10.1 Ollama detection | `cognia_desktop_api.py`, `cognia_desktop/main.js`, `cognia_desktop/renderer/app.js` |
| 10.2 doctor model check | `scripts/cognia_doctor.py` |
| 10.3 Privacy consent | `cognia_desktop/renderer/index.html`, `cognia_desktop/renderer/app.js` |
| 10.4 Feedback button | `cognia_desktop/preload.js`, `cognia_desktop/main.js` |
| 11.1 Auto-update | `cognia_desktop/package.json`, `cognia_desktop/electron-builder.config.js` |
| 11.2 Release CI | `.github/workflows/release.yml` (new) |
| 11.3 Download docs | `README.md`, `docs/INSTALL.md` |
| 12.1 MLA TTL eviction | `shattering/mla.py`, `shattering/orchestrator.py` |
| 12.2 Dep pinning | `requirements.txt` |
| 12.3 Packaged log level | `cognia_desktop_api.py` |
| 12.4 Single-user warning | `app/routes/user_data.py`, `docs/PRIVACY.md` |
| 13.1 INT4 quantization | `shattering/quantization.py` |
| 13.2 Qwen constants | `shattering/model_constants.py` |
| 13.3 Qwen2 numpy engine | `node/qwen2_ops.py` (new), `node/shard_engine.py` |
| 13.4 Inference pipeline | `node/inference_pipeline.py` |
| 13.5 Registry + downloader | `coordinator/registry.py`, `node/downloader.py` |
| 13.6 Qwen manifest | `shattering/manifests/cognia_qwen.json` (new) |
| 13.7 HF conversion script | `scripts/convert_hf_to_shards.py` (new) |

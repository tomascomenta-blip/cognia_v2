# CLAUDE_NOTES.md -- Autonomous Session Log

## Session: 2026-05-21

### Context Read
- ROADMAP.md: Phases 1-19 DONE. Phase 20 TODO.
- CLAUDE.md DEUDA ACTIVA: 4 ALTO issues analyzed
- Files analyzed: orchestrator.py, inference_pipeline.py, relay.py, shard_engine.py,
  router.py, mla.py, coordinator/app.py, setup.html, setup.js

---

## Issues Found and Fixed (2026-05-21)

### [ALTO-1] Inferencia distribuida end-to-end sin texto -- FIXED
**File**: shattering/orchestrator.py -- _distributed_infer()

Root cause: _distributed_infer() sent a stub FP16 tensor WITHOUT the 12-byte wire
protocol header (PTYPE + shard_idx + dim0 + dim1), then immediately fell back to
local inference. np.array(ids, dtype=np.float16).tobytes() lacks the header, so
shard_engine.process_bytes() treats first byte as packet type and produces garbage.

DistributedInferencePipeline.generate() already implements the CORRECT token loop:
  1. GET /api/swarm/route -> route list
  2. POST /api/session/create -> session_id
  3. Token loop: _single_forward_pass() uses encode_tokens() properly,
     POSTs to /api/session/{id}/infer, receives PTYPE_LOGITS from last shard,
     samples next token
  4. Decode and return text

Fix: Replaced _distributed_infer() to delegate to DistributedInferencePipeline.generate()
with is_available() check, sub-model temperature + system prompt, and local fallback.

### [ALTO-2] clear_cache() not called proactively on session expiry -- FIXED
**File**: shattering/orchestrator.py -- infer() method and __init__

Root cause: _evict_mla_caches() only called from status() (demand-driven).
InferenceSession.SESSION_TIMEOUT=120s but KV cache eviction max_age=3600s.
Memory leak: entries accumulate for up to 1 hour after sessions expire.

Fix: Added _last_eviction field + proactive call at start of infer() every 90s
with max_age_seconds=150s (SESSION_TIMEOUT + 30s margin).

### [QUALITY] Router confidence overconfident with few hits -- FIXED
**File**: shattering/router.py -- route() method

Root cause: conf = scores[winner]/total gives 1.0 when 1 keyword matches.
Routing "model" -> techne at 100% confidence is misleading.

Fix: Evidence-damped formula:
  evidence_scale = min(1.0, total / 6.0)
  conf = ratio * (0.4 + 0.6 * evidence_scale)
Calibration: 1 hit->0.50, 3 hits->0.70, 6+ hits->1.00 max.
router_version bumped to "1.2".

---

## Issues Found and Fixed (2026-05-22)

### [ALTO-3] coordinator/app.py shattering_infer sends stub FP16 without wire header -- FIXED
**File**: coordinator/app.py -- /api/shattering/infer endpoint (lines ~554-563)

Root cause: `np.array(ids, dtype=np.float16).tobytes()` was sent as the initial
payload to shard 0 via the relay. This is neither PTYPE_TOKENS nor PTYPE_TEXT format.
shard_engine.process_bytes() sees byte 0 as the type byte and gets PTYPE_HIDDEN with
garbled dimensions, producing wrong output.

Fix:
1. Added PTYPE_TEXT = 3 to node/shard_engine.py wire protocol
2. Added encode_text(shard_index, prompt) -> bytes that produces proper 12-byte header + UTF-8 payload
3. Added _tokenize_text() and _load_tokenizer() to ShardEngine for lazy BPE tokenization
4. decode_wire() updated to decode PTYPE_TEXT as UTF-8 string
5. process_bytes() updated to handle PTYPE_TEXT: tokenize then process as PTYPE_TOKENS
6. coordinator/app.py now calls encode_text(0, req.prompt) instead of stub FP16
   Byte-level fallback if tokenizers lib unavailable (UTF-8 bytes as int32 IDs)

### [ALTO-4] MLAModule caches KV latents but never retrieves them -- FIXED
**File**: shattering/mla.py -- MLAModule.forward()

Root cause: The MLAModule stored `c_kv = hidden @ W_DKV` in `CompressedKVCache.put()`,
but on subsequent decode steps it recomputed K/V from the current input only -- never
calling `kv_cache.get()`. This means each decode step had no past context in the
attention computation, producing incoherent output when MLAModule is used.

Fix:
- forward() now retrieves c_kv_past from cache before computing current c_kv_new
- Concatenates: c_kv_full = concat([c_kv_past, c_kv_new], axis=0)
- K/V are expanded from c_kv_full (full past + current sequence)
- Q is computed from current input only (standard autoregressive decoding)
- RoPE applied at correct offsets: Q at [offset..offset+seq], K at [0..total]
- Causal mask: past tokens always visible; within prefill block, causal mask applied
- Simulation mode also properly accumulates (zero latents for lifecycle tests)
- Added CompressedKVCache.truncate() for speculative decoding rollback support

Note: RealTransformerLayer GQA KV-cache (qwen2_ops.py) was already working correctly
and IS connected to the local token loop via session_id flow. MLAModule is an optional
overlay that patch_shard_engine_mla() activates; not auto-activated (needs trained weights).

### [MEDIO] Semantic Router added -- Phase 20.1 (lightweight, no external deps)
**File**: shattering/router.py, shattering/model_constants.py

Implementation: _SemanticIndex class using character n-gram hash vectors (MD5-based).
- Each word -> 256-dim sparse hash vector (2-gram + 3-gram + full word)
- Domain centroids pre-computed from keyword lists at __init__
- Route blends: kw_dominant (ratio >= 0.60) -> keyword only; otherwise 0.55*sem + 0.45*kw
- Semantic active only when sem_max_score >= ROUTER_SEMANTIC_THRESHOLD (0.60)
- router_version bumped to "1.3"
- Constants ROUTER_SEMANTIC_THRESHOLD and ROUTER_SEMANTIC_BLEND in model_constants.py
- 8/8 test queries routed correctly

### [BAJO] FatigueMonitor.reset() added
**File**: cognia/fatiga_cognitiva.py

Added reset() method that clears all deques, resets fatigue score to 0, and
resets start_time. Call after sleep cycle or extended idle period.

### [QUALITY] Vectorized causal mask in RealTransformerLayer._attention()
**File**: node/qwen2_ops.py

Replaced O(seq) Python loop with vectorized numpy broadcast:
  q_idx = arange(seq).reshape(-1, 1)
  k_idx = arange(total).reshape(1, -1)
  future = (k_idx > past_len + q_idx).astype(float32) * -1e9

### [QUALITY] PTYPE_CLEAR_CACHE control frame for distributed KV cleanup
**Files**: node/shard_engine.py, coordinator/relay.py

Added PTYPE_CLEAR_CACHE = 4 wire protocol type:
- encode_clear_cache(shard_index, session_id) -> bytes
- ShardEngine.process_bytes() handles PTYPE_CLEAR_CACHE: calls clear_cache(session_id)
  and returns an ACK frame (empty PTYPE_CLEAR_CACHE header)
- ShardEngine.clear_cache() enhanced to also clear RealTransformerLayer._kv_cache entries
- relay.py _purge_expired_async() broadcasts PTYPE_CLEAR_CACHE to all connected shards
  before purging expired sessions (graceful distributed cache eviction)

---

## Phase 20 Analysis

### 20.1 Semantic Router -- DONE 2026-05-22
Implemented without sentence-transformers. Uses character n-gram MD5 hash vectors.
See _SemanticIndex in router.py.

### 20.2 LPC -- Latent Persistence Cache (TODO)
Complex. Cache last shard hidden state per session_id. Requires session_id
threading through generate() calls and cache invalidation policy.

### 20.3 DUS -- Depth Up-Scaling -- DONE (scripts/scale_shards.py exists)
Already implemented in scripts/scale_shards.py. See that file.

### 20.4 Federated Knowledge Distillation (DEFER)
Complex. Deferred to Phase 21+.

### 20.5 MLA constants -- NO CHANGE NEEDED
Verified: current values in model_constants.py are correct for Qwen2.5-Coder-3B.
MLA_D_C=512 is valid; ROADMAP formula h//n_kv=1024 is not standard practice.

---

## Files Modified This Session (2026-05-22)
- node/shard_engine.py: PTYPE_TEXT + PTYPE_CLEAR_CACHE + encode_text/encode_clear_cache + lazy tokenizer in ShardEngine + enhanced clear_cache()
- node/qwen2_ops.py: vectorized causal mask (O(seq) Python loop -> numpy broadcast)
- shattering/mla.py: MLAModule.forward() KV-cache retrieval fix + CompressedKVCache.truncate()
- shattering/router.py: _SemanticIndex class + semantic blend in GlobalRouter.route() + router_version 1.3
- shattering/model_constants.py: ROUTER_SEMANTIC_THRESHOLD, ROUTER_SEMANTIC_BLEND constants
- coordinator/app.py: /api/shattering/infer uses encode_text() instead of stub FP16
- coordinator/relay.py: _purge_expired_async() with PTYPE_CLEAR_CACHE broadcast
- cognia/fatiga_cognitiva.py: CognitiveFatigueMonitor.reset()

---

## Session: 2026-05-24

### Context Read
- CLAUDE_NOTES.md: previous session ended with Phase 21 "IN PROGRESS"
- ROADMAP.md: Phase 21 items: SWA O(512) [DONE], C kernels [DONE infra], benchmarks CI [TODO], intra-turn KV-cache [DONE]
- Key files analyzed: orchestrator.py, nano_draft.py, qwen2_ops.py, shard_engine.py, dynamic_precision.py, inference_pipeline.py, build_fast_kernels.py, fast_kernels.c

### Issues Found and Fixed (2026-05-24)

### [Phase 21] Benchmark script -- DONE
**File**: scripts/benchmark_inference.py (NEW)

Implements the "benchmarks CI" item from Phase 21. Covers:
- INT4 matmul kernel benchmark for all typical Qwen weight shapes (q_proj, gate, lm_head)
- Reports active backend: numba / c_kernel / numpy_chunked
- RMSNorm and SiLU primitive benchmarks
- Full shard-0 forward pass (--shards flag): cold prefill, hot decode, DynQuant tier stats
- KV-cache effectiveness measurement (with vs without session accumulation)
- Projects full-model tok/s estimate from shard-0 timing

Usage:
  python scripts/benchmark_inference.py          # kernel only (fast)
  python scripts/benchmark_inference.py --shards # full shard (requires SHARD_WEIGHTS_DIR)

### [PERF] NanoDraft: incremental KV-cache for speculative decoding -- DONE
**File**: node/nano_draft.py (COMPLETE REWRITE)

Root cause: The original NanoDraft._forward() re-processed the full context (32-64 tokens)
from scratch on every draft() call. Each step of the token loop calls draft(), so for 200
generated tokens, 200 full context passes were done (each O(seq * 2 layers)).

Additionally, draft tokens were generated with _forward_single() which processed each
token WITHOUT attending to previous draft tokens (no past KV), reducing acceptance rate.

Fix:
1. Added _ctx_kv: List[(K_raw, V_raw)] per layer — caches the context KV
2. Added _ctx_ids: tracks which context IDs are cached
3. _cached_prefix_len(ids): checks if current context extends the cache
4. _forward_incremental(x_in, kv_list, offset): processes new tokens only using past KV
5. _attn_kv(x, L, offset, kv_past): attention with past K/V; returns (output, K_full, V_full)
6. draft() now:
   - Detects how many context tokens are cached
   - Processes only new context tokens (incremental)
   - Generates N draft tokens with full KV accumulation (all previous draft tokens in attention)
   - Saves context KV; discards draft token KV (correct rollback behavior)
7. Added reset_cache() for when context diverges

Benefits:
  - Context processing: O(new_tokens) instead of O(seq) per draft() call
  - Draft generation: each draft token attends to ALL previous tokens (context + prior drafts)
    → improved acceptance rate → higher effective throughput with speculative decoding

### [CORRECT] LPC cross-turn persistence in streaming path -- DONE
**File**: shattering/orchestrator.py -- astream() and _shard_infer_stream()

Root cause: astream() → _shard_infer_stream() always created session_id = f"local_{time}"
(new session per call). Cross-turn KV-cache (LPC) was not used for the streaming path,
only for the non-streaming infer() path.

Fix:
1. astream(prompt, lpc_session_id=None) — accepts optional lpc_session_id
2. _shard_infer_stream(prompt, queue, loop, lpc_session_id=None) — uses LPC entry
3. If lpc_session_id provided: get_or_create LPC entry, use mla_session_id as session_id
4. If cached prefix exists: only process new tokens (skip already-cached prompt)
5. After streaming: calls self._lpc.update(lpc_session_id, len(all_ids) + tokens_generated)

This gives streaming callers the same cross-turn speed benefit as non-streaming infer().

---

## Files Modified This Session (2026-05-24)
- scripts/benchmark_inference.py: NEW — Phase 21 benchmark script
- node/nano_draft.py: Complete rewrite with incremental KV-cache
- shattering/orchestrator.py: astream() + _shard_infer_stream() with lpc_session_id support

## Priority Order for Next Session
1. Build C kernels -- run `python node/build_fast_kernels.py` with available compiler
   On Windows with Python 3.14 (no numba): need MSVC or MinGW. Check:
   - C:\msys64\mingw64\bin\gcc.exe
   - Visual Studio Build Tools
   Expected speedup: 5-20x for INT4 matmul vs numpy_chunked fallback
2. Run benchmark: `python scripts/benchmark_inference.py` to get baseline metrics
   Then `python scripts/benchmark_inference.py --shards` if SHARD_WEIGHTS_DIR is set
3. Phase 21 items remaining:
   - "intra-turn KV-cache validado" -- write a test that verifies KV-cache accumulates
     correctly during a multi-token generation (test in tests/test_attention_integration.py)
   - Consider marking Phase 21 DONE in ROADMAP.md once benchmark runs clean
4. AttentionSystem integration tests (MEDIO in DEUDA ACTIVA)
5. RST K=2 quality investigation -- ablation with K=1 vs K=2 on a real prompt
6. Consider adding pipeline initialization lock to prevent TOCTOU race in 
   _shard_infer_stream/_shard_infer when called concurrently

---

## Session: 2026-05-29

### Context Read
- CLAUDE_NOTES.md: previous session ended at Phase 21 benchmark + NanoDraft rewrite
- MANAGER_LOG.md (untracked): confirms large May-29 autonomous session already ran
  (23+ cycles: UI, tests for desktop_api/dynamic_precision/llama_backend, KV intra-turn,
  speculative decoding wired, FatigueMonitor.reset_state(), network status endpoint,
  chat history persistence). All 3 untracked test files confirmed passing.
- ROADMAP.md: Phases 1-28 DONE before this session started

### Issues Found and Fixed (2026-05-29)

### [ALTO] _shards_available() blind to unpacked shard_N/ directories -- FIXED
**File**: shattering/orchestrator.py -- _shards_available()

Root cause: After running `scripts/unpack_shards.py`, shards exist as directories
(shard_0/, shard_1/, etc.) containing individual .npy files. _shards_available()
only checked for shard_N.npz files, so it always returned False for unpacked shards,
forcing every inference to fall back to Ollama even when real weights were present.

Fix: Added _shard_present(idx) inner function that checks:
1. shard_N.npz exists and non-empty (original path)
2. shard_N/ directory exists and is non-empty (unpacked path)
Handles COGNIA_NODE_SHARD env var for single-shard nodes.

### [BUG] cognia_doctor.py crash when no manifest file found -- FIXED
**File**: scripts/cognia_doctor.py -- check_inference_speed()

Root cause: When no manifest file exists, the function passed manifest_path=None
to ShatteringOrchestrator() which raised ValueError, turning a [WARN] into a crash.

Fix: Early return `_warn("Inferencia", "No manifest found -- skip")` before
constructing the orchestrator when no candidate manifest file is found.

### [COVERAGE] CognitiveFatigueMonitor had zero test coverage -- FIXED
**File**: tests/test_fatiga_cognitiva.py (NEW, 41 tests)

Added comprehensive test suite covering:
- Construction (initial score/level/trend)
- start_cycle/end_cycle basics and counters
- Score bounds (never < 0, never > 100)
- Level thresholds (moderada/alta/critica via direct _fatigue_score injection)
- Trend detection (subiendo with increasing ops)
- get_adaptations() keys, normal mode, critica mode, idle reset trigger
- get_state() keys and cache_hit_rate bounds
- reset() and reset_state() behavior
- record_embedding_computed/cached counters
- should_propose_optimization() logic
- Thread safety (4 concurrent workers, 20 cycles each)
- Singleton pattern (get_fatigue_monitor returns same instance)
- _normalize() math (7 precision tests)

Note: Threshold tests use direct `m._fatigue_score = float(X)` injection because
organic score pumping via cycles only reaches ~15 pts max due to W_OPS=0.15 and
alpha=0.3 exponential smoothing -- not enough to cross THRESHOLD_MODERATE=30.

### [COVERAGE] Unpacked shard dir detection had no tests -- FIXED
**File**: tests/test_e2e_inference.py -- TestShardsAvailableLogic class

Added 4 tests:
- test_true_when_unpacked_directory_present: shard_0/ with .npy file -> True
- test_false_when_directory_exists_but_is_empty: empty shard_0/ -> False
- test_true_directory_preferred_over_missing_npz: shard_1/ with npy + COGNIA_NODE_SHARD=1 -> True
- test_false_when_no_shard_present: neither .npz nor dir -> False

### [ROADMAP] Phase 29 documented
**File**: ROADMAP.md

Added Phase 29 entry to execution order table and full section:
"Test Coverage + Shard Dir Fix" -- fatiga_cognitiva 41 tests, _shards_available dir fix,
new directory shard tests.

---

## Files Modified This Session (2026-05-29)
- shattering/orchestrator.py: _shards_available() now detects both .npz and shard_N/ dirs
- tests/test_e2e_inference.py: 4 new shard directory detection tests
- scripts/cognia_doctor.py: early return on missing manifest (no crash)
- ROADMAP.md: Phase 29 added
- tests/test_fatiga_cognitiva.py: NEW -- 41 tests for CognitiveFatigueMonitor

## Test Count
- Previous session: ~368 collected
- This session end: 467 collected (41 fatiga + 4 shard dir + previous untracked files)

## Priority Order for Next Session
1. Verify full test suite passes cleanly: `pytest tests/ -x --tb=short`
   -- Full run was started but session ended before results confirmed
2. Add tokens_generated field to InferResult for accurate tok/s measurement
   -- InferResult currently has only .text and .mode; tok/s in cognia_doctor
      estimated from word count (inaccurate for short responses)
3. Check if orchestrator.infer() returns early exit path for empty prompts
   -- No guard seen; empty string could cause dim-0 tensor issues in qwen2_ops
4. Benchmark baseline: `python scripts/benchmark_inference.py` to confirm 4.8 tok/s
   with fast_kernels_omp.dll still holds after recent changes
5. Phase 21 final validation: mark DONE in ROADMAP if benchmark passes clean

---

## Session: 2026-06-20  (BRANCH RECONCILIATION + LIVE DATA-LOSS FIX)

### Context discovered — TWO divergent development lines were reconciled
This working tree was a STALE local branch (10 commits of June bug-fixes based on
`1b3ae78`, May), while `origin/main` had advanced INDEPENDENTLY to a different line:
releases **3.3.0 -> 3.5.1 published to PyPI**, a tensor-parallel "v2" rework of the
shattering layer, UX onboarding, agent tooling, etc. The two lines shared the
ancestor `1b3ae78` and never merged. origin's CLAUDE_NOTES stops at 2026-05-29 and
NEVER received the June fix sessions (pool-deadlock, data-loss, MLA RoPE).

Push credentials now work (the wincredman blocker from prior sessions is gone).
Backup of the old local line kept at branch `backup/local-fixes-2026-06-20`.

### [CRITICAL - LIVE DATA-LOSS in shipped 3.x] Pooled writes never committed -- FIXED + PUSHED
origin/main (shipping in PyPI 3.3.0-3.5.1) had the SAME silent data-loss bug the
2026-06-16 local session found but which never reached origin: pooled writes did
`conn.execute(INSERT) -> conn.close()` with NO `conn.commit()`, and
`_PooledConnection.close()` releases with `commit=False`, so every write was rolled
back. `save()` returned True, nothing persisted (user_profile, style_engine,
personal_index, chat, memory modules). origin also LACKED the db_pool `__del__`
GC safety net -> the pool-leak-on-exception 10s/query degradation was also live.
Re-applied the full June fix-set onto origin (commit a9a6012):
  - conn.commit() on all pooled write paths.
  - try/finally close on every pooled DB op (semantic/episodic/episodic_fast/chat/graph).
  - db_pool __del__ GC net + gc_reclaimed counter + corrected docstring.
  - tests: test_persistence_commit, test_personal_index, test_db_pool_leak_on_error.
graph.py + memory modules applied cleanly (origin had not touched them since base);
chat.py + db_pool.py hand-merged against origin's newer versions.

### Other fixes brought onto origin/main this session (all pushed, all green)
- **22e22d6** fix(reports): progress_reporter datetime.utcnow() -> now(timezone.utc).
  Naive utcnow().timestamp() was interpreted as LOCAL time vs UTC-epoch DB columns
  -> the report time-window filter was off by the local UTC offset. (origin still had it.)
- **b96439c** fix(mla): RLock on CompressedKVCache (dict-changed-size-during-iteration race).
- **a761b90** fix(mla): q_offset = total_len - seq_len RoPE frame fix (uncached forward was
  position-variant) + truncate_kv negative-len guard + tests/test_mla_rope.py.
  (origin's shattering/mla.py was byte-identical to base 1b3ae78 -> still buggy; MLAModule
  is still referenced by node/shard_engine.py + shattering/__init__.py, so the fix matters.)
- **c6ca54c** test(isolation): test_public_api stops leaking sys.modules["app"] + sys.path.
- **b62b876** test(isolation): test_phase9_security restores web_app module state after reload.
  (origin had independently hardened the cli_goal_* tests, so those were SKIPPED.)
- **f1ad5a5** fix(compression): try/finally around the pooled UPDATE in compress_label
  (last write-path leak found by a full-tree audit).
- **2d9e04b** test(ratchet): tests/test_no_bare_sqlite_connect.py -- AST guard enforcing the
  CLAUDE.md no-bare-sqlite3.connect rule. Baseline of 33 files verified IDENTICAL on
  origin's tree (origin added none), so it dropped in unchanged.

### Audit performed (delegated, whole tree)
- Full-tree audit of EVERY pooled-write site on origin: **0 remaining data-loss bugs**
  after a9a6012 (every write commits). Only leak found was compression.py (fixed in f1ad5a5).
- Remaining low-value hygiene (NOT done, deliberate): ~15 read-only methods in chat.py +
  knowledge/reasoning modules close the pooled conn only on the success path (leak on a
  mid-query exception). The db_pool __del__ net reclaims them; no data loss. Use
  cognia/knowledge/graph.py (full try/finally) as the template if a sweep is desired.

### Verification
- Full fast suite on the integrated tree (origin/main + a9a6012..a761b90):
  **2449 passed, 1 skipped, 0 failed** (315s). Later commits (public_api/phase9/
  compression/ratchet) verified individually + combined (53 passed together, no pollution).

### State at session end
- origin/main is at **2d9e04b**, 8 commits ahead of the pre-session origin (fd6c189).
  ALL PUSHED. Working tree clean except this docs commit.
- Branch `backup/local-fixes-2026-06-20` holds the old pre-reconciliation local line.

### Priority Order for Next Session (origin/main line)
1. The origin 3.x line is now the source of truth. Future work builds on origin/main.
   ROADMAP.md in THIS tree is the OLD line's roadmap; origin's release line (3.x, PyPI,
   tensor-parallel v2) is tracked in its own commits/MANAGER_LOG -- reconcile ROADMAP if needed.
2. (Optional, low severity) try/finally sweep of the ~15 read-only pooled-conn methods
   (chat.py get_recent_turns/list_sessions/resolve_session_prefix/get_session_turns;
   knowledge/reasoning write fns that commit but lack finally). graph.py is the template.
3. (Optional) Migrate KNOWN_BARE_SQLITE files to db_pool one at a time; the ratchet test
   (2d9e04b) keeps the baseline honest (it only shrinks).
4. Review origin's NEW 3.x code (tensor-parallel v2, agent tooling, chat-offline INT4 path
   from 3.5.1) for correctness -- it has NOT been through the June bug-hunt sessions.
5. Re-run benchmark once a real shard/DB is present (still pending across sessions).

---

## Session: 2026-06-21  (CACHE CORRECTNESS BUG-HUNT on the un-audited 3.x code)

### Context / approach
Picked up priority #4 from the 2026-06-20 list: review origin's NEW 3.x code that
never went through a bug-hunt session. Started from the leak-audit (`/tmp/audit_leak.py`,
AST scan): re-confirmed the 2026-06-20 finding — **0 WRITE+NOCOMMIT data-loss paths
remain** (36 close-without-finally sites exist but the db_pool __del__ net reclaims
them; all WRITE paths commit). So the data layer is clean; moved to the un-audited
3.x cache/router modules where real logic bugs were likely. Found two live bugs.

NOTE on environment: there is NO `venv312/` in this checkout (CLAUDE.md references one
that isn't present here). The system `python` IS Python 3.12.10 with numpy 1.26.4 +
pytest 9.0.3 installed, so I used it directly. Verified tests run green.

### [BUG-1 — LIVE, severe] response_cache._search_ram KeyError on EVERY RAM hit -- FIXED
**File**: response_cache.py -- ResponseCache._search_ram()

Root cause: entries are keyed in the RAM OrderedDict as `f"{entry.timestamp}_{id(entry)}"`
(see _add_to_ram), but on a hit _search_ram called
`self._ram.move_to_end(id(best_entry).__str__())` — i.e. `str(id(entry))`, WITHOUT the
timestamp prefix. That key never exists in the dict, and `OrderedDict.move_to_end`
raises `KeyError` on a missing key. So every in-RAM cache hit raised KeyError.
`ResponseCache.get()` is called UNGUARDED from `LanguageEngine.process()`
(language_engine.py:224) — a warm semantic cache crashed the chat path instead of
serving the cached answer (and the two-layer RAM cache could never serve a RAM hit).

Fix: track the real dict key while scanning (`for key, entry in self._ram.items()`)
and `move_to_end(best_key)`. Reproduced the old KeyError + verified the fix.
Regression test: tests/test_response_cache_ram_hit.py (3 tests: no-raise+returns entry,
LRU recency refresh, recently-hit entry survives eviction).

### [BUG-2 — LIVE] model_router route() cache was LRU-in-name, FIFO-in-fact -- FIXED
**File**: model_router.py -- ModelRouter.route()

Root cause: the cache is documented as "Cache LRU real con OrderedDict (no FIFO)" with a
"FIX" comment claiming it fixed a 0%-hit-rate FIFO bug, but the cache-HIT path
(`if cache_key in self._cache: return self._cache[cache_key]`) returned WITHOUT
`move_to_end`, so recency was never refreshed and eviction degraded right back to FIFO —
evicting the just-used entry. Reproduced: re-accessing a key did not protect it; the 4th
insert evicted the most-recently-used entry instead of the true LRU.

Fix: `move_to_end(cache_key)` on the hit path before returning; simplified the dead
post-compute branch (a hit always returns early, so the tail key was always new).
Regression test added to tests/test_model_router_local_fallback.py
(test_route_cache_is_lru_not_fifo + test_route_cache_returns_same_decision_on_hit).

### [HYGIENE] model_router self-tests crashed on Windows cp1252 -- FIXED
`run_tests()` / `_test_*` printed emojis (🧪 ✅) — a CLAUDE.md ASCII-only violation that
raised UnicodeEncodeError on the default Windows console when running `python model_router.py`.
Replaced with `[OK]` / plain ASCII. Logic verified identical (all in-module tests pass).

### Files Modified This Session (2026-06-21)
- response_cache.py: _search_ram() uses the real dict key for the LRU touch (KeyError fix)
- model_router.py: route() refreshes LRU recency on cache hit; dead tail branch removed;
  emoji prints -> ASCII (cp1252-safe)
- tests/test_response_cache_ram_hit.py: NEW — 3 tests for the RAM-hit KeyError + LRU
- tests/test_model_router_local_fallback.py: +2 tests for the route() LRU behaviour

### Verification
- tests/test_response_cache_ram_hit.py -> 3 passed
- tests/test_model_router_local_fallback.py -> 4 passed (2 old + 2 new)
- tests/test_doctor_packaging.py -> 6 passed combined
- model_router.run_tests() -> all pass, no cp1252 crash
- Both bugs reproduced on the OLD code then verified fixed (KeyError / wrong-eviction).
- Full fast suite (tests/ --ignore=test_e2e_inference.py): see commit message / next session.

### Operational note — push credentials in non-interactive shells
The `wincredman` credential store fails with no tty (both Bash and PowerShell tools):
`git push` dies with "could not read Username for github.com". The 2026-06-20 note that
"push credentials now work" only holds for an interactive terminal. WORKAROUND that works
headless: `gh` is logged in (token scopes repo+workflow), so push via its credential
helper — `git -c credential.helper='!gh auth git-credential' push origin HEAD:main`.
(Local branch `integration/fixes-onto-origin` tracks `origin/main`; push HEAD:main.)

### Priority Order for Next Session
1. Continue the 3.x cache/agent audit. Other OrderedDict caches checked this session
   (cognia_embedding.py, cognia/memory/adapter_store.py, shattering/fragment_manager.py)
   correctly move_to_end on get — only response_cache + model_router were broken.
   Next: audit cognia/semantic_cache.py + cognia/reasoning/cache_warmer.py (call sites of
   ResponseCache) and the agent tooling (cognia/agents/*) for similar key/recency bugs.
2. (Still open) try/finally sweep of the ~17 read-only pooled-conn methods (graph.py template).
3. (Still open) Review tensor-parallel v2 cross-process path (tp_allreduce float add order /
   KV-cache-per-rank) — in-process golden path read this session and looks bit-exact-correct.
4. Re-run benchmark once a real shard/DB is present (still pending across sessions).

---

## Session: 2026-06-22  (CACHE-EFFECTIVENESS BUG-HUNT — persistent layers never hit)

### Context / approach
Picked up priority #1 from 2026-06-21: audit cognia/semantic_cache.py +
cognia/reasoning/cache_warmer.py + the agent tooling (cognia/agents/*) for the
same key/recency cache bugs found earlier. Environment unchanged: no venv312 in
this checkout; system `python` is 3.12.10 (numpy 1.26.4 + pytest), used directly.
Found a NEW class beyond LRU-recency: store-vs-search **basis/dimension mismatch**
that makes a cache's PERSISTENT layer silently never hit (every repeat query then
pays the full ~5s LLM path instead of <5ms cache). Found two LIVE instances, both
in the response-cache subsystem, both fixed + regression-tested.

### [BUG-1 — LIVE, severe] semantic_cache lookup compared vectors across drifted vocab -- FIXED + PUSHED (b511e02)
**File**: cognia/semantic_cache.py -- SemanticResponseCache.lookup()

Root cause: lookup() deserialized the persisted `tfidf_vector` blob (computed
against the vocab snapshot at store() time) and compared it against qvec built
from the CURRENT vocab. The TF-IDF vocab DRIFTS as questions are cached: it grows
toward the 2000-token cap and is re-sorted by frequency, so token->index mapping
changes on every store(). A stored vector therefore lives in a different basis
than qvec -> either dims differ (entry skipped -> MISS) or dims coincide but the
basis differs (cosine across mismatched axes -> garbage). Net: any entry cached
before the vocab last changed became unreachable. Reproduced: an exact-match query
turned MISS after 5 unrelated stores drifted the vocab. ResponseCache-style cache
is on the chat hot path (LanguageEngine).

Fix: recompute the candidate vector at lookup time from its stored tokens
(question_norm, already persisted) against the current vocab — same approach
thought_cache.py already uses (it stores question_tokens for exactly this reason).
Regression: tests/test_semantic_cache.py::test_hit_survives_vocab_drift.

### [BUG-2 — LIVE, severe] response_cache persisted only vector[:64] -- FIXED + PUSHED (cd950a8)
**File**: response_cache.py -- ResponseCache._persist_to_db()

Root cause: `_persist_to_db` stored `json.dumps(entry.vector[:64])` (first 64
dims) while `_search_db` compares the FULL query vector via `_cosine()`, which
returns 0.0 on any length mismatch. Embeddings today are 384-dim
(cognia.vectors.text_to_vector), so EVERY DB-layer comparison was a length
mismatch -> 0.0, and the persistent (SQLite) half of the two-layer cache NEVER
hit. The `64` was a magic number left from an older 64-dim embedding era. Net:
anything evicted from the 200-entry RAM layer, and every entry after a process
restart, was unrecoverable (and the DB path still scanned up to 100 rows per
lookup, all scoring 0.0). Reproduced: store -> fresh ResponseCache on same DB file
-> get() was a MISS before, a HIT after.

Fix: persist the full vector. Keeps the 0.88 threshold on the same basis as the
RAM layer (which compares full vectors). Regression:
tests/test_response_cache_ram_hit.py::test_db_layer_hits_with_full_dim_vector.

### [REFACTOR] semantic_cache.store() stopped computing the now-unused blob -- PUSHED (ab2fd1a)
**File**: cognia/semantic_cache.py -- store()

After BUG-1, lookup() never reads the tfidf_vector blob. store() was still doing a
full _rebuild_vocab + _tfidf_vector + _serialize on every call just to write a blob
nobody reads, AND it rebuilt the vocab BEFORE inserting the new row (lag-by-one:
the new question's tokens stayed invisible until a later store rebuilt again).
Simplified: store() now just marks the vocab dirty (next lookup rebuilds from all
rows incl. this one) and inserts an empty placeholder for the NOT NULL column.
Removed the now-dead _serialize/_deserialize helpers + unused `io` import.

### [HYGIENE] task_queue.save_subtasks dead, misleading rows comprehension -- PUSHED (a9047f9)
**File**: cognia/agents/task_queue.py

A `rows` list comprehension was built and discarded (the real insert loop below
recomputes everything). The dead block derived task_id incorrectly
(`st.description.split(":")[0]`), a trap for future maintainers. Removed it; live
loop (task_id = "_".join(st.id.split("_")[:-1])) verified: subtask task_id matches
parent task id.

### Audits performed (delegated, whole subsystems) — both came back CLEAN
- **agents + remaining OrderedDict caches** (cognia/agents/*, self_architect.py,
  cognia_v3.py, cognia_code.py, cognia/vectors.py, intent_predictor.py): NO
  LRU-recency / key-mismatch / write-without-commit bugs. task_queue._conn() DOES
  commit; supervisor stores/reads results under the same st.id key; the only
  "LRU dict" in self_architect.py is inside a pseudocode STRING the architect
  proposes (never executed). cache_warmer.py has no cache of its own (fire-and-
  forget); intent_predictor.py is stateless.
- **semantic-memory retrieval dim/basis** (episodic, episodic_fast, semantic,
  memory_compressor, conversation_memory, consolidation_engine x2, code_memory,
  cognia_v3, decision_gate, goal_and_pattern_engine): all consistent — store dim
  == query dim == 384, same basis. Root cause closed at source: VECTOR_DIM pinned
  to 384 (config.py:82, cognia_v3.py:82); scripts/migrate_vector_dim.py re-embeds
  legacy rows; episodic_fast.VectorCache rebuilds on dominant dim + skips off-dim
  rows. Two LATENT traps noted (not live): GoalManager.goal_aware_memory_boost is
  dead code with a stored-vs-passed cosine that would mismatch if ever wired to a
  different embedding source; AsyncEmbeddingQueue singleton's n-gram fallback dim
  is only safe because every call site passes 384 today.

### Verification
- Reproduced both bugs on the OLD code (MISS), verified fixed (HIT).
- Per-module suites green: test_semantic_cache.py 8 passed, test_response_cache_ram_hit.py
  4 passed; cache-area (-k semantic_cache/response_cache/thought/warmer) 38 passed.
- Full fast suite after commits 1-3: 2458 passed, 1 skipped, 0 failed (250s).
- Full fast suite AFTER all 4 commits (final gate): **2458 passed, 1 skipped, 0 failed** (200s).

### State at session end
- origin/main advanced by 4 commits: b511e02, cd950a8, a9047f9, ab2fd1a (all pushed
  via `git -c credential.helper='!gh auth git-credential' push origin HEAD:main`,
  the headless workaround — wincredman still fails with no tty).
- Local branch integration/fixes-onto-origin tracks origin/main.

### Priority Order for Next Session
1. The cache subsystem (response_cache, semantic_cache, thought_cache, model_router,
   embedding/adapter/fragment LRUs) is now fully audited + fixed. Memory retrieval
   and agents are clean. Next un-audited 3.x surface: the inference orchestration
   (shattering/orchestrator.py infer/astream, inference_pipeline, distributed path)
   and the agent EXECUTION loop (supervisor/daemon runtime behavior), not just the
   cache shapes.
2. (Optional cleanup) GoalManager.goal_aware_memory_boost is dead code — either wire
   it correctly (ensure mem["_vec"] uses the same embedding source as goal.vector) or
   delete it, to remove the latent dim-mismatch trap.
3. (Still open) try/finally sweep of the ~17 read-only pooled-conn methods (graph.py template).
4. (Still open) tensor-parallel v2 cross-process path: tp_allreduce.py read this
   session and is correct (commutative sum + NaN/inf screen; accept-order float
   non-determinism is acknowledged in the design, not a bug). The per-rank KV-cache
   path is still un-reviewed.
5. Re-run benchmark once a real shard/DB is present (still pending across sessions).

---

## Session: 2026-06-25  (INFERENCE ORCHESTRATION + AGENT EXECUTION-LOOP BUG-HUNT)

### Context / approach
Picked up priority #1 from 2026-06-22: audit the un-audited inference orchestration
(shattering/orchestrator.py infer/astream/LPC/speculative) and the agent EXECUTION
loop (supervisor/daemon RUNTIME behaviour), not just cache shapes. Env unchanged:
no venv312 in this checkout; system `python` is 3.12.10 (numpy 1.26.4 + pytest 9.0.3),
used directly. Delegated two parallel Explore audits (inference + agents), then
VERIFIED every key claim against the real code before touching anything (CLAUDE.md
rule 2). Several sub-agent "bugs" were FALSE on inspection and deliberately dropped
(see below). Fixed two real, fully-verified correctness bugs; one real-but-unverifiable
speculative-decoding bug is documented precisely for next session instead of shipped.

### [BUG-1 — LIVE, severe correctness] LPC reused KV-cache without verifying the prefix -- FIXED + PUSHED (85d5163)
**File**: shattering/orchestrator.py -- LatentPersistenceCache + _shard_infer_stream + _generate_local

Root cause: the Latent Persistence Cache (cross-turn KV-cache reuse, public API
`infer/astream(prompt, lpc_session_id=...)`) decided to skip the cached prefix purely
by comparing token COUNTS — `cached_n < len(all_ids)` — and reused the MLA KV-cache
for the first `cached_n` tokens WITHOUT ever checking that `all_ids[:cached_n]`
matched the previously-cached tokens. `_LPCEntry` only stored `token_count`, never the
token IDs, so the check was impossible. Any caller reusing an lpc_session_id with a
different (but longer) prompt — and even legitimate multi-turn chat whose template
boundary tokens differ — silently attended over a STALE prefix and corrupted output.
The designer's own `invalidate()` docstring documents the intended guard ("clear when
prompt is not an extension of cached prefix") but nothing enforced it. The e2e test
already reused one sid across two non-extension prompts ("Explain recursion."→"Give an
example."), exercising the buggy path (it only asserted no-crash, not correctness).

Fix: `_LPCEntry` now stores `prefix_ids` (full prompt+generated token IDs of the cached
turn); `update()` persists the IDs and derives token_count from len. New shared
`_lpc_plan()` helper validates `np.array_equal(all_ids[:cached_n], prefix)` before
reuse; on ANY mismatch (divergent / identical / shorter) it evicts the MLA session,
invalidates the entry and reprocesses the full prompt. Both LPC decision sites now call
the one helper (dedup bonus). Reproduced stale-prefix reuse on old logic, confirmed new
logic reprocesses-full on non-extension / skips only on real extension (explicit e2e
CHECK printed). Regression: tests/test_e2e_inference.py::TestLPCPlanPrefixValidation
(4 tests) + TestLatentPersistenceCache updated to the prefix-IDs signature.

### [BUG-2 — robustness] Agent executor left tasks dangling on any uncaught exception -- FIXED + PUSHED (24162ae)
**File**: cognia/agents/supervisor.py -- _Executor.run()

Root cause: `_Executor.run()` set PLANNING/EXECUTING then only reached a terminal state
(DONE/FAILED/ABORTED) on the happy path. Any uncaught exception (plan_task raising, a DB
error in update_status/save_subtasks, an unexpected tool/verify failure) propagated
straight out of `CogniaAgentRuntime.tick()`, which `AgentDaemon.tick()` calls with no
guard. Two consequences: the popped task was lost from the in-memory queue and stuck in
a non-terminal state (only recoverable on full process restart via _reload_pending),
AND the exception bubbled up and could take down the daemon/idle tick loop.

Fix: run() now wraps the real body (`_run()`) and on any exception marks the task FAILED
with `EXECUTOR_ERROR:<type>:<msg>` (the FAILED write itself guarded so the except path
can't raise). Honors the lifecycle contract and keeps the daemon alive across a bad task.
Verified end-to-end: monkeypatched plan_task to raise; tick() no longer propagates and
the task ends FAILED with the captured reason (explicit CHECK). Regression:
tests/test_phase23.py::test_executor_error_marks_failed_not_dangling.

### [BUG-3 — REAL but UNVERIFIABLE here, documented not shipped] Speculative KV-cache off-by-one on draft divergence
**File**: shattering/orchestrator.py -- _token_loop() (and the twin block in _shard_infer_stream ~lines 660-700)

Root cause (verified by reading qwen2_ops.truncate_kv/kv_len + the batch forward):
the batch verifies N_DRAFT draft candidates and the KV-cache grows by N_DRAFT (one slot
per candidate, positions kv_before..kv_before+N_DRAFT-1). On DIVERGENCE at position j
(`pred_j != candidates[j]`), `accepted = [c0..c_{j-1}, pred_j]`, k=j+1, and the code does
`truncate_kv(session_id, kv_before + k)` = kv_before+j+1 — which KEEPS the KV slot for
the REJECTED candidate c_j (position j) even though the committed token at that index is
pred_j. So position j holds the wrong token's KV (a phantom), making the KV sequence
length one longer than the committed token sequence from that point on → corrupts the
rest of the turn. Secondary: `prev_output = out_batch[k-1]` then uses c_j's logits (the
rejected token's output) as the seed for the next step.
  - The all-match+bonus case is accidentally correct: k=N_DRAFT+1 overshoots the actual
    length N_DRAFT, truncate clamps to a no-op, leaving the N_DRAFT valid slots. Only the
    DIVERGENCE branch is buggy.
Correct fix sketch: truncate to `kv_before + matched` (matched = # of as-is accepted
candidates, EXCLUDING the final correction/bonus), then reprocess the correction token
(accepted[-1] = current_ids) through a NORMAL single-token step so its KV + prev_output
are computed correctly, before continuing.
WHY NOT SHIPPED THIS SESSION: this path only activates with a real draft model
(nano_draft.npz) + loaded shards, NEITHER of which is present in this checkout, so it
CANNOT be verified end-to-end against the real model (CLAUDE.md rules 2 & 4). Shipping
an unverifiable change to a working perf path is the wrong trade. NEXT SESSION should
fix it WITH a deterministic reproducer: a fake engine implementing kv_len/truncate_kv +
a stub `_forward_through_swarm` that appends one KV slot per input token, asserting the
invariant `kv_len(session) == len(committed_tokens_forwarded)` after a forced-divergence
step (fails on current code, passes after the fix). That pins the bug at the KV-bookkeeping
layer where it lives, independent of model weights.

### [BUG-4 — functional, live feature] FS watcher analyzed each file only ONCE per session -- FIXED + PUSHED (ee1bd5a)
**File**: cognia/agents/daemon.py -- _fs_watch_loop()

Root cause: the loop tracked already-queued files in a PERMANENT set (`pending_tasks`)
cleared only on watcher shutdown. After a file was analyzed once,
`if path in pending_tasks: continue` suppressed EVERY later change to it for the rest
of the watcher's life. The watcher is wired live (cognia_idle.py:461
`start_fs_watcher(".")`), so the iterative save→analyze→save→analyze dev flow broke
after the first edit of any file.

Fix: replaced the permanent path-set with (path→mtime) dedup; the same file VERSION is
never re-queued but a later modification (new mtime) re-triggers. Extracted the decision
into a pure, thread-free helper `_changed_paths(current, previous, submitted)` for
deterministic testing. Startup stays quiet (unseen files not analyzed) and two rapid
edits within one poll window still collapse to one task (preserves
test_watcher_deduplicates_per_path). Verified with explicit CHECK (old=1 / new=2 analyses
for two separate-window edits). Regression: tests/test_phase25.py::TestChangedPaths (5).

### Sub-agent claims VERIFIED FALSE and deliberately dropped (don't re-chase)
- "temperature=0 → div-by-1e-8 overflow → NaN": FALSE. `_sample` does `flat -= flat.max()`
  BEFORE exp, so temp=0 degrades to a numerically-stable argmax. No overflow. Not a bug.
- "verifier ImportError skips the blocked-import scan → security bypass": MOOT. The real
  sandbox+allowlist is in code_executor; if code_executor isn't importable the
  `execute_python` tool isn't even registered (tool_registry.py:84) → the subtask fails
  with "Unknown tool". There is no path to execute generated code without code_executor.
- "silent distributed→local fallback masks swarm bugs": by DESIGN (resilience), logged at
  WARNING. Not a correctness bug.
- "uninitialized `vr` → NameError at supervisor.py:195": unreachable. MAX_SUBTASK_RETRIES=3
  guarantees the loop body sets `vr` at least once before that line; if verify() raises it
  propagates earlier (and is now caught by the new run() wrapper anyway).
- LOOP_DETECTOR in _run_subtask is effectively dead (key = md5(subtask.id:attempt) is
  unique per attempt, set is per-Executor) — REAL but harmless: range(MAX_SUBTASK_RETRIES)
  already bounds the loop, no infinite spin. Left as-is (low value); noted for cleanup.

### Verification
- Reproduced BUG-1 + BUG-2 on old logic, verified fixed (explicit end-to-end CHECK output).
- Targeted: test_e2e_inference.py (LPC) 10 passed; test_phase23.py 31 passed;
  affected set (phase23+phase24+self_improvement+e2e_inference+shattering) 164 passed, 7 skipped.
- Full fast suite (tests/ --ignore=test_e2e_inference.py): 2458 passed before this session.
  After LPC+agent-executor fixes: 2459 (+1 phase23 regression). FINAL gate after ALL THREE
  fixes (incl. FS watcher): **2464 passed, 1 skipped, 0 failed** (203s) — +5 from
  TestChangedPaths. The e2e_inference LPC tests are excluded from this command but pass
  under the targeted run (TestLPCPlanPrefixValidation + updated TestLatentPersistenceCache).

### State at session end
- Four commits on local branch integration/fixes-onto-origin: 85d5163 (LPC),
  24162ae (agent executor finalize), ee1bd5a (FS watcher re-trigger), + docs.
- Push protocol unchanged (wincredman fails headless):
  `git -c credential.helper='!gh auth git-credential' push origin HEAD:main`.

### Priority Order for Next Session
1. **Fix BUG-3 (speculative KV off-by-one on divergence)** using the deterministic
   fake-engine reproducer described above. Highest-value un-fixed correctness bug found.
2. Continue the inference-runtime audit not yet covered: the DISTRIBUTED token loop
   (node/inference_pipeline.py _single_forward_pass / session create / route) and the
   per-rank KV-cache of tensor-parallel v2 (still un-reviewed). Verify wire-protocol
   PTYPE_LOGITS shape handling on the real relay if a multi-node setup is available.
3. (Optional) wire or delete GoalManager.goal_aware_memory_boost (dead, latent dim trap).
4. (Optional) try/finally sweep of the ~17 read-only pooled-conn methods (graph.py template).
5. Re-run benchmark once a real shard/DB is present (still pending across sessions).

---

## Session: 2026-06-26  (BUG-3 FIXED + BUG-5 discovered: speculative decoding is effectively DEAD)

### Context / approach
Picked up priority #1 from 2026-06-25: fix BUG-3 (speculative KV off-by-one on draft
divergence) with the deterministic fake-engine reproducer the prior session designed.
Env unchanged: NO venv312 in this checkout; system `python` is 3.12.10 (numpy 1.26.4 +
pytest 9.0.3), used directly. Read the FULL KV path before touching anything
(orchestrator `_token_loop`/`_shard_infer_stream` → `_forward_through_swarm` →
`ShardEngine.process` → `RealTransformerLayer._attention`/`truncate_kv`/`kv_len`, and
`nano_draft.draft`) to confirm the exact KV bookkeeping (one slot appended per token
forwarded). Fixed BUG-3 (verified, pushed). While tracing the loop to build the test I
found BUG-5 — a much bigger PERF issue: the spec path almost never executes — and proved
it deterministically. BUG-5 is documented (not shipped) because enabling it risks
sampling correctness and the real speed payoff can't be measured without the model.

### [BUG-3 — LIVE correctness, FIXED + PUSHED (0d4d057)] Speculative KV off-by-one on divergence
**File**: shattering/orchestrator.py — `_spec_resolve` (NEW helper) + `_token_loop` + `_shard_infer_stream`

Root cause (exactly as the 2026-06-25 note predicted): the batch forwards N_DRAFT
candidates and the KV grows by N_DRAFT slots (one per candidate, positions
kv_before..kv_before+N-1). On a divergence at index j the committed token is the model's
correction `pred_j`, but slot kv_before+j holds the REJECTED candidate `c_j`. The loop
truncated to the *committed* length `kv_before + k` (k = j+1), KEEPING that phantom slot
→ KV one token longer than & mis-aligned with the committed sequence → corrupts the rest
of the turn. Worse, prev_output stayed non-None so the next iteration re-entered the spec
path WITHOUT ever forwarding the correction token (its KV never got built).

Fix: extracted a shared `_spec_resolve(candidates, out_batch, vocab_size, eos_set)`
helper returning `(accepted, matched, eos_hit)` where `matched` = candidates accepted
EXACTLY as drafted (= the only valid KV slots). Both loops now (a) `truncate_kv(sid,
kv_before + matched)` dropping every rejected/un-forwarded slot, (b) set `prev_output =
None` after the batch so the next iteration takes the NORMAL path and forwards the
trailing committed token (divergence correction OR the un-forwarded bonus), building its
KV + recomputing prev_output from real logits, (c) stop cleanly when the model predicts
EOS as the post-accept bonus. Invariant restored: `kv_len(session) == len(committed
tokens forwarded)`. The all-accept+bonus case was only *accidentally* correct before
(the `+k` overshoot clamps to a no-op and relied on a fragile d0 mismatch); now it is
explicit.

Verified (no real draft/shards needed — pinned at the KV-bookkeeping layer):
  - Deterministic fake-engine reproducer (tests/test_e2e_inference.py::
    TestSpeculativeKVAlignment): under OLD `+k` the rejected candidate (99) survives and
    the cache is one token too long; under `+matched` the cache stays exactly aligned.
  - `_spec_resolve` contract tests (TestSpecResolveContract: divergence / all-accept+bonus
    / EOS-bonus).
  - Real `_token_loop` run end-to-end with fake engine+draft+pipeline (+1 counter model):
    spec path active for 60 tokens, the phantom rejected candidate NEVER leaks into KV,
    cache length bounded (explicit CHECK).
  - Full fast suite: **2464 passed, 1 skipped, 0 failed** (259s) — no regression (new
    tests live in test_e2e_inference.py, run targeted: 9 passed incl. the 4 LPC tests).

### [BUG-5 — DISCOVERED, PROVEN, NOT shipped] Speculative decoding effectively never triggers
**File**: shattering/orchestrator.py — `_token_loop` / `_shard_infer_stream` spec guard

Root cause (off-by-one in the DRAFT CONTEXT, distinct from BUG-3's KV off-by-one):
after a normal step the last committed token `next_id` is un-forwarded; `prev_output`
predicts it, so `d0_expected = argmax(prev_output) = next_id`. But the draft context
`ctx = prompt[-32:] + generated_ids` INCLUDES `next_id`, so `draft(ctx)` predicts the
token AFTER `next_id` → `candidates[0] = token-after-next_id`. The entry guard
`if d0_expected == candidates[0]` is therefore almost never true (only on an immediate
token repeat, e.g. runs of spaces/newlines/`==`), so the batch never runs and the spec
path is skipped. Because every normal step leaves the next committed token un-forwarded,
the loop falls into normal steps and STAYS there. Net: the speculative-decoding feature
delivers ~zero benefit in normal generation.

PROOF (deterministic, model-free): ran the real `_token_loop` with a PERFECT draft (one
that returns the exact correct future tokens under a +1-counter model) + fake engine.
Result: **spec batch entered 0 times out of 40 generated tokens.** Even a perfect draft
never triggers it. (Repro lived in /tmp/spec_trigger.py — re-creatable from this note.)

WHY NOT SHIPPED: the correct fix makes the batch start with the un-forwarded committed
token as the anchor (`candidates = [current_ids[-1]] + draft(ctx)[:N-1]`, and accept only
the verified speculation, NOT re-appending the anchor — needs a `_spec_resolve` rework to
separate "anchor" from "newly committed"). That ENABLES a path that is currently dead, and
two things make it unsafe to ship blind here:
  1. **Sampling correctness.** The spec path verifies via argmax-matching, which is only
     exact for GREEDY decoding. The normal path SAMPLES (`_sample`, default temperature
     0.5 in `_token_loop`). Enabling spec under temperature>0 would silently bias accepted
     runs toward greedy — a behavior change, not a pure acceleration. Proper spec-under-
     sampling needs the modified rejection-sampling acceptance test, not argmax==.
  2. The real speed payoff (acceptance rate) is unmeasurable without nano_draft.npz +
     loaded shards, NEITHER present in this checkout (CLAUDE.md rules 2 & 4).
The greedy-EXACTNESS of a fix IS verifiable model-free (run greedy vs spec on the +1
fake model, assert identical token sequences). NEXT SESSION with the real model should:
fix the anchor offset, GATE spec to temperature≈0 (or implement rejection-sampling
acceptance), prove greedy-equivalence with the fake model, then measure acceptance rate
on a real prompt before enabling by default. NOTE: BUG-3's fix is still correct & needed
— it makes the spec path safe for the rare repeat-token case today and for whenever BUG-5
is fixed.

### Items checked and deliberately NOT actioned (with corrected reasoning)
- **GoalManager.goal_aware_memory_boost "latent dim trap" (prior #3): the trap is BENIGN.**
  The chain `goal_aware_boost (facade) → goal_aware_memory_boost` is fully dead (the facade
  is only named in a docstring at goal_and_pattern_engine.py:729, never invoked; no test
  references it). The prior note called it a dim-mismatch trap, but `_cosine` (line 911)
  already guards `len(a) != len(b)` → returns 0.0, so a mismatch yields a 0 boost, never a
  crash or garbage. Harmless dead code; deleting it is pure cosmetics (removes a documented
  "PASO 7" method) so I left it. Drop this from the priority list unless wiring it for real.

### Operational notes
- Push protocol unchanged (wincredman fails headless):
  `git -c credential.helper='!gh auth git-credential' push origin HEAD:main`.
- **site-packages shadow**: there is an INSTALLED copy of the `shattering` package at
  `...\AppData\Local\Python\pythoncore-3.12-64\Lib\site-packages\shattering\` that LACKS
  these fixes. It only shadows the repo when cwd is NOT the repo root (e.g. running a
  script from /tmp puts the script dir on sys.path[0]). pytest + any `python` run from the
  repo root correctly use the local repo (confirmed: `_spec_resolve` resolves to the repo
  file). Harmless for dev/tests, but a reminder that the repo — not the installed pkg — is
  the source of truth; the installed copy is stale.

### State at session end
- origin/main advanced by 1 commit: **0d4d057** (BUG-3 fix + tests), pushed & green.
- Local branch integration/fixes-onto-origin tracks origin/main. Working tree clean
  except this docs commit.

### Priority Order for Next Session
1. **Fix BUG-5 (spec path never triggers)** — highest-value PERF bug. Fix the draft-anchor
   offset, GATE to greedy (temp≈0) or add rejection-sampling acceptance, prove greedy-
   equivalence on the fake +1 model (model-free), then measure acceptance rate on a real
   prompt WITH nano_draft.npz + shards before enabling by default. BUG-3's `_spec_resolve`
   helper is the right place to add the anchor/newly-committed split.
2. Continue the inference-runtime audit not yet covered: the DISTRIBUTED token loop
   (node/inference_pipeline.py _single_forward_pass / session create / route) and the
   per-rank KV-cache of tensor-parallel v2 (still un-reviewed). Verify wire-protocol
   PTYPE_LOGITS shape handling on the real relay if a multi-node setup is available.
3. (Optional) try/finally sweep of the ~17 read-only pooled-conn methods (graph.py template).
4. Re-run benchmark once a real shard/DB is present (still pending across sessions).
5. (Dropped) GoalManager dead-code: benign, see above — only revisit if wiring it for real.

---

## Session: 2026-06-28  (BUG-5 FIXED: speculative decoding now triggers + is distribution-preserving)

### Context / approach
Picked up priority #1 from 2026-06-26: fix BUG-5 (the speculative path almost never
triggers, AND the draft-anchor offset). Env unchanged: NO venv312 in this checkout;
system `python` is 3.12.10 (numpy 1.26.4 + pytest 9.0.3), used directly. Read the FULL
spec path in both loops (`_token_loop`, `_shard_infer_stream`), `_sample`, `nano_draft.draft`
(confirmed deterministic argmax) before touching anything. Decided AGAINST the prior
note's fallback of "gate to greedy" because the production sub-model temps are 0.15–0.7
(`_TEMPERATURES`) — greedy-gating would leave the feature DEAD in practice. Implemented
the stronger fix: distribution-preserving speculative sampling, correct for ALL temps.

### [BUG-5 — FIXED + PUSHED (8bb4cc6)] Spec path never triggered; argmax-only verification
**File**: shattering/orchestrator.py — `_spec_resolve` (rewritten) + `_softmax_temp` (new)
  + `_token_loop` + `_shard_infer_stream` + class spec constants

Root cause (exactly as the 2026-06-26 note proved): after a normal step the committed-but-
un-forwarded token `next_id` is predicted by `prev_output` (so `d0_expected=argmax=next_id`),
but the draft context `ctx = prompt[-32:] + generated_ids` INCLUDES next_id, so
`draft(ctx)[0]` = the token AFTER next_id. The guard `d0_expected == candidates[0]` thus only
passed on an immediate repeat → the batch almost never ran. Proven model-free again here.

Fix (two parts):
1. **Anchor offset.** candidates[0] is now the ANCHOR = the un-forwarded committed token
   (`int(current_ids[-1])`); the draft proposes candidates[1..N-1] (`draft(ctx, n=N-1)`).
   The batch forwards the anchor (building its KV) + verifies the drafts. The path now
   triggers every primed step and CHAINS (the trailing token becomes the next anchor; no
   forced normal step — removed the `prev_output=None` reset). The old `d0_expected` guard
   is gone.
2. **Distribution-preserving speculative sampling.** `_spec_resolve` rewritten: because the
   draft is deterministic (argmax), its proposal q is a point mass, so the Leviathan/Chen
   acceptance test reduces to "accept draft d_i with prob p_i(d_i)" where
   `p_i = softmax(out_batch[i-1]/T)` is the TARGET dist; on rejection sample the correction
   from the residual p_i with d_i removed (renormalised) and stop; on full accept sample the
   bonus from p_N. New `_softmax_temp` mirrors `_sample`'s exact numerics, so committed tokens
   are distributed EXACTLY as the normal sampling path — for ANY temperature (T→0 = argmax =
   greedy). This makes spec correct for the production temps, not just greedy.
   `_spec_resolve` now returns NEW tokens EXCLUDING the anchor and `matched = 1 + accepted
   drafts`; BUG-3's KV invariant (`kv_len == committed-forwarded length`) is preserved.
3. **Adaptive guard** (new, protects the unmeasurable perf path): after `_SPEC_WARMUP`(=8)
   attempts, if the mean accepted-draft count < `_SPEC_MIN_MEAN_ACCEPT`(=1.0) the loop
   disables spec for the rest of the turn → a weak draft can't regress a wide batch into a
   per-token cost. Constants on the class (`_SPEC_N_DRAFT`/`_SPEC_WARMUP`/`_SPEC_MIN_MEAN_ACCEPT`).

Verified (no real draft/shards needed — pinned at the loop+KV layer):
  - `_spec_resolve` contract (anchor excluded; matched excludes correction/bonus; immediate
    divergence keeps only the anchor slot) — TestSpecResolveContract (4).
  - **Distribution preservation**: 40k-trial empirical dist of the first committed token
    matches `softmax(target/T)` within atol 0.01; greedy reduces to argmax —
    TestSpecResolveSampling (2).
  - **KV alignment**: fixed `+matched` keeps `kv == committed[:-1]`; old policy keeps a
    phantom — TestSpeculativeKVAlignment (2).
  - **Greedy equivalence + trigger**: the REAL `_token_loop` with a +1 fake model + perfect
    draft TRIGGERS the spec batch (draft consulted, commits >1/iter) and is token-for-token
    identical to plain greedy; a weak draft disables after exactly `_SPEC_WARMUP` attempts
    and the output stays the correct greedy sequence — TestSpecGreedyEquivalence (2).
  - test_e2e_inference.py: 61 passed, 7 skipped. Fast suite (excl. e2e):
    **2464 passed, 1 skipped, 0 failed** (264s) — no regression (new tests live in
    test_e2e_inference.py, excluded from that command; run targeted above).

WHAT IS STILL UNMEASURED: the real acceptance RATE / speed payoff needs `nano_draft.npz` +
loaded shards (absent here). The path stays dormant without that artifact; CORRECTNESS is
proven model-free, PERF is left to measure on real weights. The adaptive guard makes
enabling-by-default safe even if a real draft turns out weak.

### State at session end
- origin/main advanced by 1 commit: **8bb4cc6** (BUG-5 fix + tests), pushed & green.
- Push protocol unchanged (wincredman fails headless):
  `git -c credential.helper='!gh auth git-credential' push origin HEAD:main`.
- Local branch integration/fixes-onto-origin tracks origin/main.

### Priority Order for Next Session
1. **Measure spec acceptance rate + speed on real weights** (the one thing this session
   couldn't): with `nano_draft.npz` + loaded shards, run a real prompt, log `[SpecLoop]`
   matched/tok-s, confirm a net speedup (and that the adaptive guard doesn't false-trip on a
   genuinely-good draft). Tune `_SPEC_N_DRAFT`/`_SPEC_MIN_MEAN_ACCEPT` if needed.
2. Continue the inference-runtime audit not yet covered: the DISTRIBUTED token loop
   (node/inference_pipeline.py `_single_forward_pass` / session create / route) and the
   per-rank KV-cache of tensor-parallel v2 (still un-reviewed). Verify PTYPE_LOGITS shape
   handling on the real relay if a multi-node setup is available.
3. (Optional) try/finally sweep of the ~17 read-only pooled-conn methods (graph.py template).
4. (Dropped) GoalManager dead-code: benign — only revisit if wiring it for real.

---

## Session: 2026-06-30  (SWA PREFILL CORRUPTION — severe long-prompt bug, fixed in BOTH engine copies)

### Context / approach
Priority #1 from 2026-06-28 (measure spec acceptance on real weights) is BLOCKED —
no `nano_draft.npz`/shards in this checkout. Took priority #2 instead (audit the
un-reviewed inference paths: distributed token loop + tensor-parallel v2 per-rank
KV). Env unchanged: NO venv312; system `python` is 3.12.10 (numpy 1.26.4 +
pytest 9.0.3), used from the repo root (so the repo — not the stale site-packages
`shattering` shadow — is imported; verified via `__file__`). Read the full
attention path (`node/qwen2_ops.py` `_attention`/`_attention_normed`, the TP
partition path `shattering/tensor_parallel.py`, `shard_engine.process`/KV methods,
`node/inference_pipeline.py`). The TP per-rank KV path turned out already CORRECT
and TESTED (test_tp_generate_distributed asserts greedy-equivalence to reference);
the real bug was one layer deeper, in the Sliding-Window-Attention block shared by
every inference path. Found it, proved it model-free, fixed it, propagated to the
shipped public copy, then bounded its cost.

### [SWA-BUG — LIVE, SEVERE correctness, FIXED + PUSHED (c9e66d0, 2521be0)] SWA prefill corrupted every non-last position
**Files**: node/qwen2_ops.py — `_attention` + `_attention_normed`;
  cognia_public_api/cognia_inference/qwen2_ops.py (vendored copy) — same two methods.

Root cause: SWA (Phase 21.2, `SWA_WINDOW=512`) bounded long-context cost by
truncating K/V to the global last-W keys `K[-SWA_WINDOW:]`. That window is correct
ONLY for the decode step (seq == 1, where the single query IS the last token). For a
multi-token prefill (seq > 1) with `total > SWA_WINDOW`, the SAME global truncation
gave EVERY earlier query a window ending at the LAST token instead of at its own
position: those queries saw only future keys, the causal mask zeroed every score,
and softmax collapsed to a uniform average — garbage. The corruption propagates
through the layer stack (early/mid positions feed the last position's attention in
the next layer) and reaches the final-position logits, so ANY prompt longer than
512 tokens (a few hundred lines of code + the ChatML system prompt easily exceeds
512) produced wrong next-token predictions. This is the PRODUCTION hot path: this
checkout ships `fast_kernels_omp.dll` → `_CLIB_FUSED` is True → `forward()` runs
`_attention_normed` (the fused variant), which had the identical bug. The real model
(Qwen2.5-Coder-3B) has `use_sliding_window:false` — SWA is a Cognia-added approx, so
this was never matching the reference for >512 contexts AND was mathematically wrong.

Fix: keep the O(W) last-window truncation ONLY for the decode step (seq == 1,
exactly correct, byte-identical to before). For a multi-token batch (seq > 1) keep
the K/V and apply a per-query BANDED sliding-window causal mask:
  `masked = (k_abs > q_abs) | (k_abs <= q_abs - SWA_WINDOW)`
Every query keeps at least its own slot → no row is ever fully masked. Behavior is
byte-identical for the decode path and for short prefills (total <= W); only the
buggy `seq>1 & total>W` case changes. Both `_attention` and `_attention_normed`
fixed in node/ AND in the shipped public copy.

Verified (model-free — pinned at the attention layer, no real shards needed):
  - Oracle = position-consistency of causal attention: a one-shot prefill MUST equal
    feeding the same tokens one-at-a-time (the seq==1 path, correct in old & new
    code). OLD code diverged at every position but the last (up to 0.56 abs); FIXED
    matches the incremental oracle to ~3e-8 for both methods.
  - END-TO-END 4-layer stack on the FUSED production path (`_attention_normed`,
    window=8, 20-token prompt): OLD final-position hidden diverged from the oracle by
    7.8e-2 (corrupts the next-token prediction); FIXED matches to 1.2e-7. This proves
    the bug reached the output logits, not just early positions.
  - New suite tests/test_swa_attention.py (6 tests: prefill>W & prefill<=W for both
    methods, batch-after-long-past, decode-still-truncates). Full fast suite:
    **2470 passed, 1 skipped, 0 failed** (was 2464 — +6).

### [SWA-PERF — FIXED + PUSHED (da17549)] Bound the multi-token batch to reachable keys
Follow-up: the seq>1 branch attended over FULL K/V (O(seq*total)) — wasteful for a
small batch over a long cached past (a speculative-decoding verify batch of ~5
tokens after 1000+ generated tokens scored against the WHOLE context) and a memory
risk for long continuation prefills. The union of all per-query windows in one call
is `[past_len - W + 1, total)`; lower keys are masked for EVERY query anyway, so
slicing K/V to `key_lo = max(0, past_len - SWA_WINDOW + 1)` is NUMERICALLY EXACT
while bounding attn_total to <= seq + W - 1. A spec batch now scores ~W keys, not
the whole context; a pure prefill (past_len=0) is unchanged (key_lo=0); decode
(seq==1) untouched. Verified numerically identical to full-K (3e-8 vs oracle;
attn_total 11 vs 34 full on a 4-tok batch over 30-tok past). Applied to both methods
in both files. Full suite stayed 2470 passed.

### [DRIFT — FIXED + PUSHED (cbe3585)] Vendored public engine had silently drifted
`cognia_public_api/cognia_inference/qwen2_ops.py` is a HAND-MAINTAINED copy of
node/qwen2_ops.py shipped as the public/HF-Space package (README_HF.md,
local_runner.py with a numpy fallback that DOES use it). It carried the SWA bug
untouched AND lacked the truncate_kv negative-len guard. Synced both; the two files
now differ ONLY in their 3 import lines (`shattering.*` vs `cognia_inference.*`), so
any future logic divergence is immediately visible in a plain `diff`. RECOMMEND a
future session generate/import this copy from node/ instead of hand-maintaining it.

### Items checked and deliberately NOT actioned
- **Tensor-parallel v2 per-rank KV (prior priority #2): already CORRECT + tested.**
  partition_layer gives each rank a real RealTransformerLayer holding only its heads'
  KV under session_id (isolated per-rank dicts); test_tp_generate_distributed asserts
  the T=2/T=4 socket all-reduce run is greedy-IDENTICAL to the single-device
  reference. No bug. (The SWA fix also benefits the TP path since each rank's
  `_attention` shares the fixed block.)
- **Distributed token loop (node/inference_pipeline.py): in-process path reads clean.**
  The HTTP cross-process branch has a latent protocol-detection ambiguity
  (`result_bytes[0] in (0,1,2)` to pick decode_wire vs decode_hidden_state — legacy
  `>HHII` frames with shard_index<256 also start with byte 0), but in practice the
  relay returns PTYPE_LOGITS(2) so it resolves correctly; unverifiable without a real
  multi-node relay → not touched (CLAUDE.md rules 2 & 4).
- **MLA module**: does not use SWA_WINDOW → no SWA bug there.

### Verification summary
- Bug reproduced on OLD code (0.56 single-layer / 7.8e-2 end-to-end), verified fixed
  (~3e-8 / 1.2e-7) — both single-layer and through a 4-layer fused-path stack.
- tests/test_swa_attention.py: 6 passed. Targeted attention/tp/inference suites: 103
  passed, 7 skipped. Full fast suite (excl. e2e): 2470 passed, 1 skipped, 0 failed
  (309s), re-run after the key_lo refinement: still 2470/1/0.

### State at session end
- origin/main advanced by 4 commits: **c9e66d0** (SWA fix node/), **2521be0** (SWA
  fix public), **da17549** (key_lo bound, both), **cbe3585** (drift sync) — all pushed
  & green. Push protocol unchanged (wincredman fails headless):
  `git -c credential.helper='!gh auth git-credential' push origin HEAD:main`.
- Local branch integration/fixes-onto-origin tracks origin/main; working tree clean
  except this docs commit.

### Priority Order for Next Session
1. **Measure spec acceptance rate + speed on real weights** (still the one thing no
   session can do without `nano_draft.npz` + loaded shards). With them: run a real
   prompt > 512 tokens to CONFIRM the SWA fix produces coherent long-prompt output
   end-to-end against the real model (this session proved correctness model-free; a
   real-weights CHECK is the missing end-to-end gate), then log `[SpecLoop]`
   matched/tok-s for the spec path.
2. **(Optional optimization) memory-bounded long PREFILL.** The fix makes a single
   long prefill (past_len=0, seq>W) correct but O(seq^2) — fine for realistic prompts
   (public caps n_ctx=2048 ≈ 268MB transient; numpy is a slow fallback) but it would
   OOM on a 32k prefill. A chunked query-block banded prefill would restore O(seq*W)
   memory while staying correct. Only needed if very long numpy-path prefills become
   real; the key_lo bound already covers the continuation/spec-batch case.
3. **De-duplicate the vendored public engine** (generate cognia_inference/qwen2_ops.py
   from node/ or import it) so the SWA-style "fix one copy, miss the other" trap can't
   recur. The files are now identical apart from 3 import lines — a good moment.
4. Continue the un-audited DISTRIBUTED cross-process path (relay PTYPE_LOGITS shape +
   the protocol-detection ambiguity above) IF a multi-node setup becomes available.
5. (Optional) try/finally sweep of the ~17 read-only pooled-conn methods (graph.py template).

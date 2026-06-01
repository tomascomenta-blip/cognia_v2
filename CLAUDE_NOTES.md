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

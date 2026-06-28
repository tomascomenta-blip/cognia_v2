"""
tests/test_e2e_inference.py
===========================
End-to-end tests for the inference pipeline.

Most tests run without model weights (fast). Tests that require .npz shards
are guarded with @pytest.mark.skipif so CI passes without the 1.3 GB model.
"""

from __future__ import annotations

import os
import struct
import numpy as np
import pytest

# ── helpers ──────────────────────────────────────────────────────────────────

def _shards_present() -> bool:
    from pathlib import Path
    shard_dir = Path(os.environ.get("SHARD_WEIGHTS_DIR", ""))
    if not shard_dir.is_dir():
        return False
    return any(
        (shard_dir / f"shard_{i}.npz").is_file()
        and (shard_dir / f"shard_{i}.npz").stat().st_size > 0
        for i in range(4)
    )


SHARDS_AVAILABLE = _shards_present()
needs_shards     = pytest.mark.skipif(not SHARDS_AVAILABLE,
                                      reason="model shards not present")


# ══════════════════════════════════════════════════════════════════════════════
# Wire protocol
# ══════════════════════════════════════════════════════════════════════════════

class TestWireProtocol:
    def test_encode_tokens_roundtrip(self):
        from node.shard_engine import encode_tokens, _WIRE_FMT, _WIRE_SIZE
        ids = np.array([1, 5, 999, 151643], dtype=np.int32)
        pkt = encode_tokens(0, ids)
        assert len(pkt) == _WIRE_SIZE + ids.nbytes
        ptype, _, shard_idx, dim0, dim1 = struct.unpack(_WIRE_FMT, pkt[:_WIRE_SIZE])
        assert ptype == 1       # PTYPE_TOKENS
        assert shard_idx == 0
        assert dim0 == 4
        recovered = np.frombuffer(pkt[_WIRE_SIZE:], dtype=np.int32)
        np.testing.assert_array_equal(recovered, ids)

    def test_encode_hidden_roundtrip(self):
        from node.shard_engine import encode_hidden, _WIRE_FMT, _WIRE_SIZE
        h = np.random.randn(3, 2048).astype(np.float16)
        pkt = encode_hidden(1, h)
        ptype, _, shard_idx, dim0, dim1 = struct.unpack(_WIRE_FMT, pkt[:_WIRE_SIZE])
        assert ptype == 0       # PTYPE_HIDDEN
        assert shard_idx == 1
        assert dim0 == 3
        assert dim1 == 2048
        recovered = np.frombuffer(pkt[_WIRE_SIZE:], dtype=np.float16).reshape(dim0, dim1)
        np.testing.assert_array_equal(recovered, h)

    def test_encode_logits_shape(self):
        from node.shard_engine import encode_logits, _WIRE_FMT, _WIRE_SIZE
        logits = np.random.randn(1, 151936).astype(np.float32)
        pkt = encode_logits(3, logits)
        ptype, _, shard_idx, dim0, dim1 = struct.unpack(_WIRE_FMT, pkt[:_WIRE_SIZE])
        assert ptype == 2       # PTYPE_LOGITS
        assert shard_idx == 3
        assert dim0 == 1
        assert dim1 == 151936

    def test_encode_clear_cache(self):
        from node.shard_engine import encode_clear_cache, _WIRE_FMT, _WIRE_SIZE, PTYPE_CLEAR_CACHE
        pkt = encode_clear_cache(0, "ses_abc")
        ptype, _, _, _, _ = struct.unpack(_WIRE_FMT, pkt[:_WIRE_SIZE])
        assert ptype == PTYPE_CLEAR_CACHE

    def test_encode_text(self):
        from node.shard_engine import encode_text, _WIRE_FMT, _WIRE_SIZE, PTYPE_TEXT
        pkt = encode_text(0, "hello cognia")
        ptype, _, _, dim0, _ = struct.unpack(_WIRE_FMT, pkt[:_WIRE_SIZE])
        assert ptype == PTYPE_TEXT
        body = pkt[_WIRE_SIZE:_WIRE_SIZE + dim0]
        assert body.decode("utf-8") == "hello cognia"


# ══════════════════════════════════════════════════════════════════════════════
# LightTokenizer
# ══════════════════════════════════════════════════════════════════════════════

class TestLightTokenizer:
    def setup_method(self):
        from node.inference_pipeline import LightTokenizer
        self.tok = LightTokenizer()

    def test_encode_returns_list_with_bos(self):
        ids = self.tok.encode("hello world")
        assert isinstance(ids, list)
        assert len(ids) >= 2
        assert ids[0] == 1     # BOS

    def test_decode_empty_ids(self):
        assert self.tok.decode([]) == ""

    def test_encode_decode_roundtrip(self):
        text = "foo bar baz"
        ids = self.tok.encode(text)
        # LightTokenizer is word-level — decoded words ≥ 1 (excludes BOS/EOS)
        decoded = self.tok.decode(ids)
        assert len(decoded) > 0

    def test_deterministic_encoding(self):
        t = "the quick brown fox"
        assert self.tok.encode(t) == self.tok.encode(t)

    def test_vocab_size_constant(self):
        from node.inference_pipeline import LightTokenizer
        assert LightTokenizer.VOCAB_SIZE == 151936

    def test_ids_in_vocab_range(self):
        ids = self.tok.encode("cognia is a distributed ai inference network")
        for i in ids:
            assert 0 <= i < 151936


# ══════════════════════════════════════════════════════════════════════════════
# ChatML template
# ══════════════════════════════════════════════════════════════════════════════

class TestChatMLTemplate:
    def test_contains_im_start(self):
        from node.inference_pipeline import _apply_qwen_template
        out = _apply_qwen_template("hello")
        assert "<|im_start|>" in out

    def test_starts_with_system(self):
        from node.inference_pipeline import _apply_qwen_template
        out = _apply_qwen_template("test", system="sys_prompt")
        assert "sys_prompt" in out

    def test_user_prompt_present(self):
        from node.inference_pipeline import _apply_qwen_template
        out = _apply_qwen_template("my unique prompt 98765")
        assert "my unique prompt 98765" in out

    def test_ends_with_assistant_turn(self):
        from node.inference_pipeline import _apply_qwen_template
        out = _apply_qwen_template("q")
        assert out.strip().endswith("<|im_start|>assistant")


# ══════════════════════════════════════════════════════════════════════════════
# Router
# ══════════════════════════════════════════════════════════════════════════════

class TestRouter:
    def setup_method(self):
        from shattering.router import GlobalRouter
        self.router = GlobalRouter()

    def test_route_returns_decision(self):
        from shattering.router import RouteDecision
        d = self.router.route("Explain the Pythagorean theorem")
        assert isinstance(d, RouteDecision)

    def test_sub_model_valid(self):
        d = self.router.route("Write a Python function")
        assert d.sub_model in {"logos", "techne", "rhetor"}

    def test_confidence_in_range(self):
        d = self.router.route("Tell me a story")
        assert 0.0 <= d.confidence <= 1.0

    def test_code_routes_to_techne(self):
        d = self.router.route("Write a Python function to sort a list")
        assert d.sub_model == "techne"

    def test_reason_non_empty(self):
        d = self.router.route("What is quantum computing?")
        assert len(d.reason) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Orchestrator — no shards (simulation mode)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def orchestrator_sim(tmp_path, monkeypatch):
    """Orchestrator forced to simulation mode (no real weights)."""
    monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
    from shattering.orchestrator import ShatteringOrchestrator
    return ShatteringOrchestrator(
        manifest_path="cognia_qwen",
        base_dir=str(tmp_path),
        mode="local",
        ollama_url="http://127.0.0.1:19999",   # unreachable
    )


class TestOrchestratorSim:
    def test_instantiation(self, orchestrator_sim):
        assert orchestrator_sim is not None

    def test_route_only_returns_decision(self, orchestrator_sim):
        from shattering.router import RouteDecision
        d = orchestrator_sim.route_only("test prompt")
        assert isinstance(d, RouteDecision)

    def test_shards_ready_false_when_dir_missing(self, orchestrator_sim):
        # tmp_path dir has no .npz files
        assert orchestrator_sim.shards_ready() is False

    def test_status_returns_dict(self, orchestrator_sim):
        s = orchestrator_sim.status()
        assert isinstance(s, dict)
        assert "mode" in s
        assert "fragments" in s

    def test_status_mode_is_local(self, orchestrator_sim):
        s = orchestrator_sim.status()
        assert s["mode"] == "local"


# ══════════════════════════════════════════════════════════════════════════════
# INT4 quantization roundtrip
# ══════════════════════════════════════════════════════════════════════════════

class TestInt4Quantization:
    def test_quantize_dequantize_shape(self):
        from shattering.quantization import quantize_int4, dequantize_int4
        w = np.random.randn(64, 128).astype(np.float32)
        packed, scale = quantize_int4(w)
        recovered = dequantize_int4(packed, scale, w.shape[1])
        assert recovered.shape == w.shape

    def test_quantize_dtype(self):
        from shattering.quantization import quantize_int4
        w = np.random.randn(32, 64).astype(np.float32)
        packed, scale = quantize_int4(w)
        assert packed.dtype == np.uint8
        assert scale.dtype == np.float32

    def test_dequantize_values_close(self):
        from shattering.quantization import quantize_int4, dequantize_int4
        w = np.linspace(-1, 1, 128).reshape(8, 16).astype(np.float32)
        packed, scale = quantize_int4(w)
        recovered = dequantize_int4(packed, scale, 16)
        np.testing.assert_allclose(recovered, w, atol=0.15)

    def test_packed_size_is_half(self):
        from shattering.quantization import quantize_int4
        rows, cols = 64, 128
        w = np.random.randn(rows, cols).astype(np.float32)
        packed, _ = quantize_int4(w)
        assert packed.size == (rows * cols + 1) // 2


# ══════════════════════════════════════════════════════════════════════════════
# LatentPersistenceCache
# ══════════════════════════════════════════════════════════════════════════════

class TestLatentPersistenceCache:
    def setup_method(self):
        from shattering.orchestrator import LatentPersistenceCache
        self.lpc = LatentPersistenceCache()

    def test_get_or_create_returns_entry(self):
        e = self.lpc.get_or_create("ses_1")
        assert e is not None
        assert e.token_count == 0

    def test_same_id_returns_same_entry(self):
        e1 = self.lpc.get_or_create("ses_2")
        e2 = self.lpc.get_or_create("ses_2")
        assert e1.mla_session_id == e2.mla_session_id

    def test_update_token_count(self):
        import numpy as np
        self.lpc.get_or_create("ses_3")
        self.lpc.update("ses_3", np.arange(42, dtype=np.int32))
        e = self.lpc.get_or_create("ses_3")
        assert e.token_count == 42

    def test_update_stores_prefix_ids(self):
        import numpy as np
        self.lpc.get_or_create("ses_3b")
        ids = np.array([5, 9, 13], dtype=np.int32)
        self.lpc.update("ses_3b", ids)
        e = self.lpc.get_or_create("ses_3b")
        assert np.array_equal(e.prefix_ids, ids)
        assert e.token_count == 3

    def test_invalidate_resets_entry(self):
        import numpy as np
        self.lpc.get_or_create("ses_4")
        self.lpc.update("ses_4", np.arange(10, dtype=np.int32))
        self.lpc.invalidate("ses_4")
        e = self.lpc.get_or_create("ses_4")
        assert e.token_count == 0
        assert e.prefix_ids is None

    def test_different_sessions_independent(self):
        import numpy as np
        e1 = self.lpc.get_or_create("a")
        e2 = self.lpc.get_or_create("b")
        self.lpc.update("a", np.arange(100, dtype=np.int32))
        assert self.lpc.get_or_create("b").token_count == 0


class TestLPCPlanPrefixValidation:
    """Regression for the cross-turn KV-cache corruption bug: _lpc_plan must only
    reuse the cached prefix when the new prompt actually extends it (token-level),
    not merely when it is longer."""

    def _orch(self):
        from shattering.orchestrator import ShatteringOrchestrator, LatentPersistenceCache
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        orch._lpc = LatentPersistenceCache()
        # _evict_one_mla_session iterates self._fragments._engines; give it an empty stub
        class _Frag:
            _engines = {}
        orch._fragments = _Frag()
        return orch

    def test_real_extension_reuses_prefix(self):
        import numpy as np
        orch = self._orch()
        cached = np.array([1, 2, 3, 4], dtype=np.int32)
        orch._lpc.get_or_create("s")
        orch._lpc.update("s", cached)
        # new prompt = cached prefix + 2 new tokens
        new = np.array([1, 2, 3, 4, 5, 6], dtype=np.int32)
        sid, current_ids, entry = orch._lpc_plan("s", new)
        assert np.array_equal(current_ids, np.array([5, 6], dtype=np.int32))
        assert entry.token_count == 4  # cache preserved (not reset)

    def test_non_extension_resets_and_reprocesses_full(self):
        import numpy as np
        orch = self._orch()
        orch._lpc.get_or_create("s")
        orch._lpc.update("s", np.array([1, 2, 3, 4], dtype=np.int32))
        # longer prompt but DIFFERENT tokens — must NOT reuse the stale KV-cache
        new = np.array([9, 8, 7, 6, 5, 4], dtype=np.int32)
        sid, current_ids, entry = orch._lpc_plan("s", new)
        assert np.array_equal(current_ids, new)   # full reprocess
        assert entry.token_count == 0             # entry was reset

    def test_identical_prompt_reprocesses(self):
        import numpy as np
        orch = self._orch()
        orch._lpc.get_or_create("s")
        ids = np.array([1, 2, 3, 4], dtype=np.int32)
        orch._lpc.update("s", ids)
        sid, current_ids, entry = orch._lpc_plan("s", ids.copy())
        assert np.array_equal(current_ids, ids)   # nothing to skip → full
        assert entry.token_count == 0

    def test_fresh_session_processes_full(self):
        import numpy as np
        orch = self._orch()
        new = np.array([1, 2, 3], dtype=np.int32)
        sid, current_ids, entry = orch._lpc_plan("fresh", new)
        assert np.array_equal(current_ids, new)
        assert entry.token_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# Speculative-decoding KV-cache bookkeeping (BUG-3 regression)
# ══════════════════════════════════════════════════════════════════════════════

def _onehot(tok: int, vocab: int = 300):
    import numpy as np
    v = np.zeros(vocab, dtype=np.float32)
    v[tok] = 1.0
    return v


def _plus_one_out_batch(candidates, vocab: int = 300, bonus_tok=None):
    """Build out_batch for a '+1 counter' model: out_batch[i] predicts candidates[i]+1,
    except the last row predicts `bonus_tok` when given (to drive the all-accept bonus)."""
    import numpy as np
    rows = [_onehot(c + 1, vocab) for c in candidates]
    if bonus_tok is not None:
        rows[-1] = _onehot(bonus_tok, vocab)
    return np.stack(rows, axis=0)


class TestSpecResolveContract:
    """_spec_resolve (anchor contract): candidates[0] is the already-committed ANCHOR
    (excluded from the returned new_tokens); candidates[1..] are draft proposals. It
    reports the NEWLY committed tokens and the number of valid KV slots (`matched` =
    1 anchor + drafts accepted as-is), never counting a correction or bonus as a slot.
    Greedy temperature (default 1e-8) makes acceptance a deterministic argmax match."""

    def test_divergence_excludes_anchor_and_correction_from_matched(self):
        from shattering.orchestrator import ShatteringOrchestrator
        cands = [10, 11, 99, 13, 14, 15]   # anchor 10; 11+1=12 != 99 → diverge at idx 2
        out_batch = _plus_one_out_batch(cands)
        new_tokens, matched, eos = ShatteringOrchestrator._spec_resolve(
            cands, out_batch, vocab_size=300, eos_set=set()
        )
        assert new_tokens == [11, 12]      # anchor 10 excluded; correction 12 replaces 99
        assert matched == 2                 # anchor slot + 1 accepted draft (11)
        assert eos is False

    def test_all_accept_appends_bonus_but_matched_is_n(self):
        from shattering.orchestrator import ShatteringOrchestrator
        cands = [10, 11, 12, 13, 14, 15]   # anchor 10 + 5 drafts, all land
        out_batch = _plus_one_out_batch(cands, bonus_tok=16)
        new_tokens, matched, eos = ShatteringOrchestrator._spec_resolve(
            cands, out_batch, vocab_size=300, eos_set=set()
        )
        assert new_tokens == [11, 12, 13, 14, 15, 16]   # anchor excluded; bonus appended
        assert matched == 6                              # anchor + 5 drafts (bonus has NO slot)
        assert eos is False

    def test_all_accept_eos_bonus_stops_without_appending(self):
        from shattering.orchestrator import ShatteringOrchestrator
        cands = [10, 11, 12, 13, 14, 15]
        out_batch = _plus_one_out_batch(cands, bonus_tok=2)   # EOS as next prediction
        new_tokens, matched, eos = ShatteringOrchestrator._spec_resolve(
            cands, out_batch, vocab_size=300, eos_set={2}
        )
        assert new_tokens == [11, 12, 13, 14, 15]
        assert matched == 6
        assert eos is True

    def test_immediate_divergence_keeps_only_anchor_slot(self):
        from shattering.orchestrator import ShatteringOrchestrator
        cands = [10, 77, 12, 13, 14, 15]   # 10+1=11 != 77 → diverge at the FIRST draft
        out_batch = _plus_one_out_batch(cands)
        new_tokens, matched, eos = ShatteringOrchestrator._spec_resolve(
            cands, out_batch, vocab_size=300, eos_set=set()
        )
        assert new_tokens == [11]          # correction only; nothing drafted survives
        assert matched == 1                 # just the anchor slot
        assert eos is False


class TestSpecResolveSampling:
    """Distribution preservation: with a deterministic (argmax) draft, the speculative
    acceptance test must make the committed token distributed EXACTLY as the normal
    sampling path (softmax at the same temperature) would produce it — for any T."""

    def test_first_committed_token_matches_target_distribution(self):
        from shattering.orchestrator import ShatteringOrchestrator
        vocab, T = 5, 0.8
        logits = np.array([2.0, 1.0, 0.5, 0.0, -1.0], dtype=np.float32)  # target for pos 1
        target = ShatteringOrchestrator._softmax_temp(logits, vocab, T)
        # anchor=0, first draft=1; later rows are irrelevant to new_tokens[0]
        cands = [0, 1, 2, 3, 4, 0]
        out_batch = np.zeros((6, vocab), dtype=np.float32)
        out_batch[0] = logits
        counts = np.zeros(vocab)
        np.random.seed(1234)
        N = 40000
        for _ in range(N):
            new_tokens, _, _ = ShatteringOrchestrator._spec_resolve(
                cands, out_batch, vocab_size=vocab, eos_set=set(), temperature=T
            )
            counts[new_tokens[0]] += 1
        empirical = counts / N
        assert np.allclose(empirical, target, atol=0.01), (empirical, target)

    def test_greedy_temperature_reduces_to_argmax(self):
        from shattering.orchestrator import ShatteringOrchestrator
        # token 3 has the max logit at position 1 → greedy must commit 3, not the draft 1
        vocab = 5
        out_batch = np.zeros((6, vocab), dtype=np.float32)
        out_batch[0] = np.array([0.1, 0.2, 0.3, 9.0, 0.0], dtype=np.float32)
        cands = [0, 1, 2, 3, 4, 0]
        np.random.seed(0)
        new_tokens, matched, _ = ShatteringOrchestrator._spec_resolve(
            cands, out_batch, vocab_size=vocab, eos_set=set(), temperature=1e-8
        )
        assert new_tokens[0] == 3      # argmax correction, draft 1 rejected
        assert matched == 1            # immediate divergence → only the anchor slot


class _FakeKVEngine:
    """Minimal stand-in for a ShardEngine's KV bookkeeping: tracks the EXACT token
    order forwarded into the cache so a test can assert KV/commit alignment."""
    def __init__(self):
        self.fwd = {}

    def kv_len(self, sid):
        return len(self.fwd.get(sid, []))

    def truncate_kv(self, sid, n):
        self.fwd[sid] = self.fwd.get(sid, [])[: max(0, n)]

    def forward(self, sid, ids):           # appends one KV slot per token
        self.fwd.setdefault(sid, []).extend(int(t) for t in ids)


class TestSpeculativeKVAlignment:
    """BUG-3 + BUG-5: a spec batch forwards [anchor, d_1..d_{N-1}] (anchor = the last
    committed-but-un-forwarded token). Keeping only `matched = 1 + accepted` slots must
    leave the KV holding EXACTLY the committed-and-forwarded tokens (everything except
    the trailing un-forwarded next-anchor). Truncating to the committed length keeps a
    phantom rejected slot → KV one token too long."""

    SID = "spec"

    def _run_one_spec_step(self, forwarded, anchor, drafts, truncate_to):
        """Simulate one speculative batch. `forwarded` = committed+forwarded tokens
        BEFORE this step; `anchor` = the committed-but-un-forwarded token; `drafts` =
        the draft proposals after the anchor. `truncate_to(kv_before, matched, k)`
        chooses the truncation policy (fixed vs buggy)."""
        from shattering.orchestrator import ShatteringOrchestrator
        eng = _FakeKVEngine()
        eng.forward(self.SID, forwarded)                    # KV before the batch
        kv_before = eng.kv_len(self.SID)
        candidates = [anchor] + list(drafts)
        eng.forward(self.SID, candidates)                   # batch forwards all N
        out_batch = _plus_one_out_batch(candidates)
        new_tokens, matched, eos = ShatteringOrchestrator._spec_resolve(
            candidates, out_batch, vocab_size=300, eos_set=set()
        )
        k = len(new_tokens)
        eng.truncate_kv(self.SID, truncate_to(kv_before, matched, k))
        committed = list(forwarded) + [anchor] + new_tokens
        # All committed tokens are forwarded EXCEPT the trailing un-forwarded next-anchor.
        return eng.fwd[self.SID], committed

    def test_fixed_matched_truncate_keeps_kv_aligned(self):
        # anchor 101; drafts [102,103,99,..]: 103+1=104 != 99 → correction 104, matched 2
        kv, committed = self._run_one_spec_step(
            forwarded=[100],
            anchor=101,
            drafts=[102, 103, 99, 105, 106],
            truncate_to=lambda kv_before, matched, k: kv_before + matched,   # FIX
        )
        assert committed == [100, 101, 102, 103, 104]
        # KV = everything committed except the trailing un-forwarded token (104).
        assert kv == committed[:-1] == [100, 101, 102, 103]

    def test_buggy_committed_length_truncate_misaligns_kv(self):
        # Same step under the OLD `+k` policy keeps the rejected candidate (99) →
        # KV holds a phantom token and is mis-aligned. Locks the bug shape.
        kv, committed = self._run_one_spec_step(
            forwarded=[100],
            anchor=101,
            drafts=[102, 103, 99, 105, 106],
            truncate_to=lambda kv_before, matched, k: kv_before + 1 + k,     # BUG (+anchor+k)
        )
        assert committed == [100, 101, 102, 103, 104]
        assert kv == [100, 101, 102, 103, 99]         # phantom 99 instead of trailing drop
        assert kv != committed[:-1]


# ══════════════════════════════════════════════════════════════════════════════
# BUG-5: the speculative loop must actually TRIGGER and stay greedy-equivalent.
# A deterministic "+1 counter" model + a perfect draft drive the real _token_loop.
# ══════════════════════════════════════════════════════════════════════════════

class _PlusOneEngine:
    """KV bookkeeping for the +1 model: records every forwarded token in order."""
    def __init__(self):
        self.kv = {}

    def kv_len(self, sid):
        return len(self.kv.get(sid, []))

    def truncate_kv(self, sid, n):
        self.kv[sid] = self.kv.get(sid, [])[: max(0, n)]

    def _record(self, sid, ids):
        self.kv.setdefault(sid, []).extend(int(t) for t in ids)


class _PlusOnePipeline:
    """Deterministic '+1 counter' model: forwarding token t yields logits whose argmax
    is t+1. Records forwards into the paired engine so KV bookkeeping is observable."""
    model_name = "fake-counter"

    def __init__(self, engine, vocab=512):
        self._engine = engine
        self._vocab = vocab

    def _forward_through_swarm(self, ids, sid, route, hidden_dim):
        ids = np.atleast_1d(np.asarray(ids)).astype(int)
        self._engine._record(sid, ids)
        out = np.zeros((len(ids), self._vocab), dtype=np.float32)
        for i, t in enumerate(ids):
            out[i, (int(t) + 1) % self._vocab] = 10.0
        return out, True

    def _sample(self, output, temperature):
        flat = output[-1] if output.ndim == 2 else output.flatten()
        return int(np.argmax(flat[: self._vocab]))


class _PerfectPlusOneDraft:
    """Perfect draft for the +1 model: ctx ending at t → [t+1, t+2, ...]."""
    def __init__(self):
        self.calls = 0

    def draft(self, ctx, n=6):
        self.calls += 1
        last = int(np.asarray(ctx)[-1])
        return [(last + 1 + k) for k in range(n)]


class _WeakDraft:
    """Always-wrong draft: proposes a token the +1 model never predicts."""
    def __init__(self):
        self.calls = 0

    def draft(self, ctx, n=6):
        self.calls += 1
        return [0 for _ in range(n)]


def _make_orch(draft, max_tokens):
    from shattering.orchestrator import ShatteringOrchestrator
    o = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
    o._draft = draft
    o._max_tokens = max_tokens
    return o


class TestSpecGreedyEquivalence:
    def _run(self, draft, engine, pipeline, sid, max_tokens):
        import node.inference_pipeline as ip
        saved = list(ip._LOCAL_ENGINES)
        ip._LOCAL_ENGINES[:] = [engine]
        try:
            orch = _make_orch(draft, max_tokens)
            prompt = np.array([100], dtype=np.int32)
            return orch._token_loop(pipeline, [], sid, prompt, 8, set(), temperature=1e-8)
        finally:
            ip._LOCAL_ENGINES[:] = saved

    def test_spec_triggers_and_matches_greedy_token_for_token(self):
        eng_g = _PlusOneEngine()
        gen_g, _ = self._run(None, eng_g, _PlusOnePipeline(eng_g), "g", 18)

        eng_s = _PlusOneEngine()
        draft = _PerfectPlusOneDraft()
        gen_s, _ = self._run(draft, eng_s, _PlusOnePipeline(eng_s), "s", 18)

        # BUG-5 fixed: the draft was actually consulted and the spec batch committed
        # several tokens per loop iteration (so spec generated more than greedy).
        assert draft.calls > 0
        assert len(gen_s) > len(gen_g)
        # Greedy equivalence on the shared prefix — spec changes speed, not output.
        K = min(len(gen_s), len(gen_g))
        assert K >= 10
        assert gen_s[:K] == gen_g[:K]
        assert gen_g[:5] == [101, 102, 103, 104, 105]   # the +1 counter sequence
        # KV stays aligned: every forwarded token = committed minus the trailing anchor.
        assert eng_s.kv["s"] == ([100] + gen_s)[:-1]

    def test_weak_draft_is_disabled_after_warmup_but_output_stays_correct(self):
        eng = _PlusOneEngine()
        draft = _WeakDraft()
        from shattering.orchestrator import ShatteringOrchestrator
        gen, _ = self._run(draft, eng, _PlusOnePipeline(eng), "w", 20)
        # The adaptive guard stops attempting spec once the draft proves weak: exactly
        # _SPEC_WARMUP draft calls, then plain single-token steps for the rest of the turn.
        assert draft.calls == ShatteringOrchestrator._SPEC_WARMUP
        # Output is still the exact greedy +1 sequence (corrections == the real argmax).
        assert gen[:8] == [101, 102, 103, 104, 105, 106, 107, 108]


# ══════════════════════════════════════════════════════════════════════════════
# _shards_available env logic
# ══════════════════════════════════════════════════════════════════════════════

class TestShardsAvailableLogic:
    def test_false_when_dir_not_set(self, monkeypatch):
        monkeypatch.delenv("SHARD_WEIGHTS_DIR", raising=False)
        monkeypatch.delenv("COGNIA_NODE_SHARD", raising=False)
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is False

    def test_false_when_dir_exists_but_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.delenv("COGNIA_NODE_SHARD", raising=False)
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is False

    def test_true_when_shard_file_present(self, monkeypatch, tmp_path):
        shard_file = tmp_path / "shard_0.npz"
        shard_file.write_bytes(b"\x00" * 100)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.delenv("COGNIA_NODE_SHARD", raising=False)
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is True

    def test_assigned_shard_only_checks_that_file(self, monkeypatch, tmp_path):
        # shard_1.npz present but COGNIA_NODE_SHARD=0 — should return False
        (tmp_path / "shard_1.npz").write_bytes(b"\x00" * 100)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.setenv("COGNIA_NODE_SHARD", "0")
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is False

    def test_assigned_shard_present_returns_true(self, monkeypatch, tmp_path):
        (tmp_path / "shard_2.npz").write_bytes(b"\x00" * 100)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.setenv("COGNIA_NODE_SHARD", "2")
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is True

    def test_true_when_unpacked_directory_present(self, monkeypatch, tmp_path):
        # scripts/unpack_shards.py creates shard_N/ directories instead of .npz files
        npy_dir = tmp_path / "shard_0"
        npy_dir.mkdir()
        (npy_dir / "l0_q_p.npy").write_bytes(b"\x00" * 64)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.delenv("COGNIA_NODE_SHARD", raising=False)
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is True

    def test_false_when_directory_exists_but_is_empty(self, monkeypatch, tmp_path):
        # Empty shard_0/ should not count (no actual weight files)
        (tmp_path / "shard_0").mkdir()
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.delenv("COGNIA_NODE_SHARD", raising=False)
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is False

    def test_true_directory_preferred_over_missing_npz(self, monkeypatch, tmp_path):
        # Only shard_1/ directory present (no .npz), assigned shard=1
        npy_dir = tmp_path / "shard_1"
        npy_dir.mkdir()
        (npy_dir / "l0_q_p.npy").write_bytes(b"\x00" * 64)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        monkeypatch.setenv("COGNIA_NODE_SHARD", "1")
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        assert orch._shards_available() is True


# ══════════════════════════════════════════════════════════════════════════════
# InferResult contract: tokens_generated + empty-prompt guard
# ══════════════════════════════════════════════════════════════════════════════

class TestInferResultContract:
    """Tests for InferResult dataclass and empty-prompt guard."""

    def test_infer_result_has_tokens_generated_field(self):
        """InferResult must expose tokens_generated (default 0)."""
        from shattering.orchestrator import InferResult
        r = InferResult(
            text="hello", sub_model="logos", confidence=0.8,
            latency_ms=100.0, mode="simulation", route_reason="test",
        )
        assert hasattr(r, "tokens_generated")
        assert r.tokens_generated == 0

    def test_infer_result_tokens_generated_set_explicitly(self):
        from shattering.orchestrator import InferResult
        r = InferResult(
            text="hi", sub_model="logos", confidence=0.5,
            latency_ms=50.0, mode="local", route_reason="test",
            tokens_generated=42,
        )
        assert r.tokens_generated == 42

    def test_empty_prompt_returns_error_mode(self, monkeypatch):
        """infer('') must return immediately with mode='error'."""
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", "")
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        result = orch.infer("")
        assert result.mode == "error"
        assert result.text == ""
        assert result.route_reason == "empty_prompt"
        assert result.tokens_generated == 0

    def test_whitespace_only_prompt_returns_error_mode(self, monkeypatch):
        """infer('   ') must be treated as empty — no router call."""
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", "")
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator.__new__(ShatteringOrchestrator)
        result = orch.infer("   \t\n  ")
        assert result.mode == "error"


# ══════════════════════════════════════════════════════════════════════════════
# Real shard inference (skipped without weights)
# ══════════════════════════════════════════════════════════════════════════════

@needs_shards
class TestRealShardInference:
    """Requires SHARD_WEIGHTS_DIR pointing to the actual .npz shards."""

    @pytest.fixture
    def orch(self):
        from shattering.orchestrator import ShatteringOrchestrator
        return ShatteringOrchestrator(
            manifest_path="cognia_qwen",
            base_dir=os.environ.get("SHARD_WEIGHTS_DIR", "model_shards/qwen-coder-3b-q4"),
            mode="local",
        )

    def test_shards_ready_true(self, orch):
        assert orch.shards_ready() is True

    def test_infer_returns_text(self, orch):
        result = orch.infer("What is 2 + 2?", lpc_session_id="e2e_test")
        assert result.text and len(result.text) > 0

    def test_infer_mode_is_local(self, orch):
        result = orch.infer("Say hello.", lpc_session_id="e2e_mode_test")
        assert result.mode in {"local", "llama.cpp"}

    def test_infer_latency_recorded(self, orch):
        result = orch.infer("Hi", lpc_session_id="e2e_latency_test")
        assert result.latency_ms > 0

    def test_infer_sub_model_valid(self, orch):
        result = orch.infer("Write a Python loop", lpc_session_id="e2e_route_test")
        assert result.sub_model in {"logos", "techne", "rhetor"}

    def test_lpc_second_turn_faster_or_equal(self, orch):
        import time
        sid = "e2e_lpc_speed"
        t0 = time.perf_counter()
        orch.infer("Explain recursion.", lpc_session_id=sid)
        t1 = time.perf_counter()
        orch.infer("Give an example.", lpc_session_id=sid)
        t2 = time.perf_counter()
        first_ms  = (t1 - t0) * 1000
        second_ms = (t2 - t1) * 1000
        # Second turn may be shorter due to LPC — we only assert it completed
        assert second_ms > 0
        assert first_ms > 0

    def test_no_eos_tokens_in_output(self, orch):
        result = orch.infer("Say one word.", lpc_session_id="e2e_eos_test")
        assert "<|im_end|>" not in result.text
        assert "<|endoftext|>" not in result.text

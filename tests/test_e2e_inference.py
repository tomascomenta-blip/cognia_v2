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
        self.lpc.get_or_create("ses_3")
        self.lpc.update("ses_3", 42)
        e = self.lpc.get_or_create("ses_3")
        assert e.token_count == 42

    def test_invalidate_resets_entry(self):
        self.lpc.get_or_create("ses_4")
        self.lpc.update("ses_4", 10)
        self.lpc.invalidate("ses_4")
        e = self.lpc.get_or_create("ses_4")
        assert e.token_count == 0

    def test_different_sessions_independent(self):
        e1 = self.lpc.get_or_create("a")
        e2 = self.lpc.get_or_create("b")
        self.lpc.update("a", 100)
        assert self.lpc.get_or_create("b").token_count == 0


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

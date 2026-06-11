"""
tests/test_llama_backend.py
Tests for node/llama_backend.py — LlamaBackend public facade.

All tests use mocking; llama.cpp is optional and not required in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backend(impl):
    """Return a LlamaBackend wrapping a mock impl."""
    from node.llama_backend import LlamaBackend
    return LlamaBackend(impl)


# ---------------------------------------------------------------------------
# try_load: returns None when no GGUF found
# ---------------------------------------------------------------------------

class TestTryLoadNoGguf:
    def test_returns_none_when_no_gguf(self):
        """try_load returns None immediately if _find_gguf returns None."""
        from node.llama_backend import LlamaBackend
        with patch("node.llama_backend._find_gguf", return_value=None):
            result = LlamaBackend.try_load()
        assert result is None


# ---------------------------------------------------------------------------
# try_load: returns None when GGUF exists but no runtime available
# ---------------------------------------------------------------------------

class TestTryLoadNoRuntime:
    def test_returns_none_when_neither_backend_available(self, tmp_path):
        """try_load returns None when GGUF found but both backends unavailable."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend
        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=False),
            patch("node.llama_backend._LlamaServerBackend.available", return_value=False),
        ):
            result = LlamaBackend.try_load()
        assert result is None

    def test_returns_none_when_cpp_init_raises_and_server_unavailable(self, tmp_path):
        """try_load returns None when llama-cpp-python is present but init errors and server absent."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend
        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=True),
            patch("node.llama_backend._LlamaCppBackend.__init__", side_effect=RuntimeError("boom")),
            patch("node.llama_backend._LlamaServerBackend.available", return_value=False),
        ):
            result = LlamaBackend.try_load()
        assert result is None

    def test_returns_none_when_server_init_raises(self, tmp_path):
        """try_load returns None when llama-server binary exists but server startup fails."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend
        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=False),
            patch("node.llama_backend._LlamaServerBackend.available", return_value=True),
            patch("node.llama_backend._LlamaServerBackend.__init__", side_effect=FileNotFoundError("no binary")),
        ):
            result = LlamaBackend.try_load()
        assert result is None


# ---------------------------------------------------------------------------
# try_load: returns LlamaBackend when a backend succeeds
# ---------------------------------------------------------------------------

class TestTryLoadSuccess:
    def test_returns_backend_via_cpp_python(self, tmp_path):
        """try_load returns a LlamaBackend wrapping _LlamaCppBackend when available."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend, _LlamaCppBackend
        mock_impl = MagicMock(spec=_LlamaCppBackend)

        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=True),
            patch("node.llama_backend._LlamaCppBackend.__init__", return_value=None),
            patch.object(LlamaBackend, "__init__", lambda self, impl: setattr(self, "_impl", impl) or None),
        ):
            # Patch the class so instantiation returns our mock
            with patch("node.llama_backend._LlamaCppBackend", return_value=mock_impl) as MockCpp:
                MockCpp.available.return_value = True
                result = LlamaBackend.try_load()
        assert result is not None
        assert isinstance(result, LlamaBackend)

    def test_returns_backend_via_server(self, tmp_path):
        """try_load returns a LlamaBackend wrapping _LlamaServerBackend when cpp unavailable."""
        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()

        from node.llama_backend import LlamaBackend, _LlamaServerBackend
        mock_impl = MagicMock(spec=_LlamaServerBackend)

        with (
            patch("node.llama_backend._find_gguf", return_value=fake_gguf),
            patch("node.llama_backend._LlamaCppBackend.available", return_value=False),
        ):
            with patch("node.llama_backend._LlamaServerBackend") as MockServer:
                MockServer.available.return_value = True
                MockServer.return_value = mock_impl
                result = LlamaBackend.try_load()

        assert result is not None
        assert isinstance(result, LlamaBackend)


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_generate_returns_string_on_success(self):
        """generate() returns a string when impl.generate succeeds."""
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "Hello world"

        backend = _make_backend(mock_impl)
        result = backend.generate("Say hi", max_tokens=16, temperature=0.5)

        assert result == "Hello world"
        mock_impl.generate.assert_called_once_with("Say hi", 16, 0.5)

    def test_generate_returns_none_on_impl_exception(self):
        """generate() returns None when impl.generate raises (impl handles internally)."""
        mock_impl = MagicMock()
        mock_impl.generate.return_value = None  # impl already swallows and returns None

        backend = _make_backend(mock_impl)
        result = backend.generate("trigger error")

        assert result is None

    def test_generate_passes_default_params(self):
        """generate() passes correct defaults when called without kwargs."""
        mock_impl = MagicMock()
        mock_impl.generate.return_value = "ok"

        backend = _make_backend(mock_impl)
        backend.generate("prompt")

        mock_impl.generate.assert_called_once_with("prompt", 256, 0.7)


# ---------------------------------------------------------------------------
# generate_long()
# ---------------------------------------------------------------------------

class _FakeLongImpl:
    """Scripted impl: each round pops (text, tokens, stop_reason)."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.last_tokens_predicted: Optional[int] = None
        self.last_stop_reason: Optional[str] = None
        self.prompts: list = []

    def generate(self, prompt, max_tokens=256, temperature=0.7):
        self.prompts.append((prompt, max_tokens))
        if not self._rounds:
            return None
        text, toks, reason = self._rounds.pop(0)
        self.last_tokens_predicted = toks
        self.last_stop_reason = reason
        return text


class TestGenerateLong:
    def test_continues_on_limit_until_eos(self):
        """Rounds cut by 'limit' are continued with prompt + accumulated text."""
        impl = _FakeLongImpl([
            ("AAA ", 100, "limit"),
            ("BBB ", 100, "limit"),
            ("CCC.", 50,  "eos"),
        ])
        backend = _make_backend(impl)
        result = backend.generate_long("P: ", max_total_tokens=1000, chunk_tokens=100)

        assert result["text"] == "AAA BBB CCC."
        assert result["total_tokens"] == 250
        assert result["stop_reason"] == "eos"
        assert result["rounds"] == 3
        # Continuation prompt must carry the accumulated text (KV prefix reuse)
        assert impl.prompts[1][0] == "P: AAA "
        assert impl.prompts[2][0] == "P: AAA BBB "

    def test_stops_at_max_total_tokens(self):
        """Loop never exceeds max_total_tokens; last chunk asks the remainder."""
        impl = _FakeLongImpl([
            ("X" * 40, 100, "limit"),
            ("Y" * 40, 100, "limit"),
            ("Z" * 20, 50,  "limit"),
        ])
        backend = _make_backend(impl)
        result = backend.generate_long("P", max_total_tokens=250, chunk_tokens=100)

        assert result["total_tokens"] == 250
        assert result["rounds"] == 3
        assert result["stop_reason"] == "limit"
        # Third round must only ask the 50 remaining tokens
        assert impl.prompts[2][1] == 50

    def test_natural_stop_first_round(self):
        """eos on the first round -> single round, no continuation."""
        impl = _FakeLongImpl([("Hola.", 12, "eos")])
        backend = _make_backend(impl)
        result = backend.generate_long("P", max_total_tokens=5000, chunk_tokens=2048)

        assert result == {"text": "Hola.", "total_tokens": 12,
                          "stop_reason": "eos", "rounds": 1}

    def test_returns_none_when_first_round_fails(self):
        """First generate() returning None -> None (same contract as generate)."""
        impl = _FakeLongImpl([])   # no scripted rounds -> generate returns None
        backend = _make_backend(impl)
        assert backend.generate_long("P") is None

    def test_partial_result_on_mid_loop_failure(self):
        """Failure after a successful round -> partial text with stop_reason error."""
        impl = _FakeLongImpl([("AAA", 100, "limit")])
        backend = _make_backend(impl)
        result = backend.generate_long("P", max_total_tokens=1000, chunk_tokens=100)

        assert result["text"] == "AAA"
        assert result["stop_reason"] == "error"
        assert result["rounds"] == 1

    def test_on_chunk_callback_invoked_per_round(self):
        calls = []
        impl = _FakeLongImpl([
            ("A", 100, "limit"),
            ("B", 60,  "eos"),
        ])
        backend = _make_backend(impl)
        backend.generate_long("P", max_total_tokens=500, chunk_tokens=100,
                              on_chunk=lambda r, ct, tt, sr: calls.append((r, ct, tt, sr)))

        assert calls == [(1, 100, 100, "limit"), (2, 60, 160, "eos")]


# ---------------------------------------------------------------------------
# stream_generate()
# ---------------------------------------------------------------------------

class TestStreamGenerate:
    def test_stream_generate_yields_tokens_from_impl(self):
        """stream_generate yields tokens when impl has stream_generate."""
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter(["Hello", " ", "world"])

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi", max_tokens=8, temperature=0.3))

        assert tokens == ["Hello", " ", "world"]
        mock_impl.stream_generate.assert_called_once_with("hi", 8, 0.3)

    def test_stream_generate_falls_back_to_generate_when_no_stream(self):
        """stream_generate yields single result when impl lacks stream_generate."""
        mock_impl = MagicMock(spec=["generate"])  # no stream_generate attr
        mock_impl.generate.return_value = "full response"

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi"))

        assert tokens == ["full response"]

    def test_stream_generate_yields_nothing_when_generate_returns_none(self):
        """stream_generate yields nothing when impl.generate returns None."""
        mock_impl = MagicMock(spec=["generate"])
        mock_impl.generate.return_value = None

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi"))

        assert tokens == []

    def test_stream_generate_empty_from_impl(self):
        """stream_generate yields nothing when impl.stream_generate is exhausted immediately."""
        mock_impl = MagicMock()
        mock_impl.stream_generate.return_value = iter([])

        backend = _make_backend(mock_impl)
        tokens = list(backend.stream_generate("hi"))

        assert tokens == []


# ---------------------------------------------------------------------------
# stream_chat()
# ---------------------------------------------------------------------------

class TestStreamChat:
    def test_stream_chat_yields_tokens_from_impl(self):
        """stream_chat delegates to impl.stream_chat when available."""
        mock_impl = MagicMock()
        mock_impl.stream_chat.return_value = iter(["A", "B"])

        backend = _make_backend(mock_impl)
        messages = [{"role": "user", "content": "Hello"}]
        tokens = list(backend.stream_chat(messages, max_tokens=64, temperature=0.5))

        assert tokens == ["A", "B"]
        mock_impl.stream_chat.assert_called_once_with(messages, 64, 0.5)

    def test_stream_chat_falls_back_to_stream_generate_when_no_method(self):
        """stream_chat falls back to stream_generate when impl lacks stream_chat."""
        mock_impl = MagicMock(spec=["generate"])
        mock_impl.generate.return_value = "fallback"

        backend = _make_backend(mock_impl)
        messages = [{"role": "user", "content": "hi"}]
        tokens = list(backend.stream_chat(messages))

        assert tokens == ["fallback"]


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

class TestStop:
    def test_stop_calls_impl_stop_when_available(self):
        mock_impl = MagicMock()
        backend = _make_backend(mock_impl)
        backend.stop()
        mock_impl.stop.assert_called_once()

    def test_stop_is_noop_when_impl_lacks_stop(self):
        mock_impl = MagicMock(spec=["generate"])
        backend = _make_backend(mock_impl)
        backend.stop()  # must not raise


# ---------------------------------------------------------------------------
# _stop_reason()
# ---------------------------------------------------------------------------

class TestStopReason:
    """Dicts mirror REAL b9391 /completion responses captured on 2026-06-10."""

    def test_limit(self):
        """n_predict cap reached -> 'limit' (real b9391 response shape)."""
        from node.llama_backend import _stop_reason
        data = {"content": "The ocean", "stop": True, "stop_type": "limit",
                "stopping_word": "", "tokens_predicted": 8, "truncated": False}
        assert _stop_reason(data) == "limit"

    def test_eos(self):
        """Natural end (eos token) -> 'eos'."""
        from node.llama_backend import _stop_reason
        data = {"content": "Hi! How can I assist you today?", "stop": True,
                "stop_type": "eos", "stopping_word": "", "tokens_predicted": 10}
        assert _stop_reason(data) == "eos"

    def test_word(self):
        """Stop string hit -> 'word'."""
        from node.llama_backend import _stop_reason
        data = {"content": "done", "stop": True, "stop_type": "word",
                "stopping_word": "<|im_end|>", "tokens_predicted": 5}
        assert _stop_reason(data) == "word"

    def test_none_when_no_fields(self):
        """Empty/unknown dict -> None (e.g. mid-stream chunk)."""
        from node.llama_backend import _stop_reason
        assert _stop_reason({}) is None
        assert _stop_reason({"content": "tok", "stop": False}) is None
        assert _stop_reason({"stop_type": "none"}) is None

    def test_legacy_boolean_flags(self):
        """Older llama-server builds report stopped_* booleans."""
        from node.llama_backend import _stop_reason
        assert _stop_reason({"stopped_eos": True}) == "eos"
        assert _stop_reason({"stopped_limit": True}) == "limit"
        assert _stop_reason({"stopped_word": True}) == "word"

    def test_openai_chat_finish_reason(self):
        """/v1/chat/completions final chunk: finish_reason length/stop (real b9391 shape)."""
        from node.llama_backend import _stop_reason
        length_chunk = {"choices": [{"finish_reason": "length", "index": 0, "delta": {}}],
                        "object": "chat.completion.chunk",
                        "timings": {"predicted_n": 8}}
        stop_chunk = {"choices": [{"finish_reason": "stop", "index": 0, "delta": {}}],
                      "object": "chat.completion.chunk"}
        mid_chunk = {"choices": [{"finish_reason": None, "index": 0,
                                  "delta": {"content": "tok"}}]}
        assert _stop_reason(length_chunk) == "limit"
        assert _stop_reason(stop_chunk) == "eos"
        assert _stop_reason(mid_chunk) is None


# ---------------------------------------------------------------------------
# last_stop_reason facade property
# ---------------------------------------------------------------------------

class TestLastStopReason:
    def test_facade_exposes_impl_attribute(self):
        mock_impl = MagicMock()
        mock_impl.last_stop_reason = "limit"
        backend = _make_backend(mock_impl)
        assert backend.last_stop_reason == "limit"

    def test_facade_returns_none_when_impl_lacks_attribute(self):
        mock_impl = MagicMock(spec=["generate"])
        backend = _make_backend(mock_impl)
        assert backend.last_stop_reason is None


# ---------------------------------------------------------------------------
# _find_gguf()
# ---------------------------------------------------------------------------

class TestFindGguf:
    def test_returns_none_when_env_not_set_and_no_files(self, tmp_path, monkeypatch):
        """_find_gguf returns None when LLAMA_GGUF_PATH unset and shard dir has no gguf.

        We point SHARD_WEIGHTS_DIR to a subdirectory so the rglob on its parent
        only sees our controlled tree and does not escape into sibling pytest tmp dirs.
        """
        shard_dir = tmp_path / "shards" / "model"
        shard_dir.mkdir(parents=True)
        monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(shard_dir))

        from node.llama_backend import _find_gguf
        assert _find_gguf() is None

    def test_returns_path_from_env_var(self, tmp_path, monkeypatch):
        """_find_gguf returns the file pointed to by LLAMA_GGUF_PATH."""
        gguf = tmp_path / "my_model.gguf"
        gguf.touch()
        monkeypatch.setenv("LLAMA_GGUF_PATH", str(gguf))

        from node.llama_backend import _find_gguf
        result = _find_gguf()
        assert result == gguf

    def test_returns_none_when_env_path_missing(self, tmp_path, monkeypatch):
        """_find_gguf returns None (warning) when LLAMA_GGUF_PATH points to nonexistent file."""
        shard_dir = tmp_path / "shards" / "model"
        shard_dir.mkdir(parents=True)
        monkeypatch.setenv("LLAMA_GGUF_PATH", str(tmp_path / "ghost.gguf"))
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(shard_dir))

        from node.llama_backend import _find_gguf
        assert _find_gguf() is None

    def test_finds_candidate_in_shard_dir(self, tmp_path, monkeypatch):
        """_find_gguf finds a known candidate filename inside SHARD_WEIGHTS_DIR."""
        monkeypatch.delenv("LLAMA_GGUF_PATH", raising=False)
        monkeypatch.setenv("SHARD_WEIGHTS_DIR", str(tmp_path))
        candidate = tmp_path / "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf"
        candidate.touch()

        from node.llama_backend import _find_gguf
        result = _find_gguf()
        assert result == candidate

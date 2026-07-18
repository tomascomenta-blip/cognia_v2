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


# ---------------------------------------------------------------------------
# Machine-dependent tuning: _ctx_size() / _n_gpu_layers() / _n_threads() are
# env-overridable and read at CALL time (they were import-time constants).
# Regression 1: both were hardcoded (n_gpu_layers=0, calibrated for the
# i3-10110U Intel UHD iGPU), so a real CUDA GPU could not offload any layer.
# Regression 2: import-time reads meant cognia/perf_profiles.py could not
# switch CPU/GPU knobs at runtime without an importlib.reload.
# ---------------------------------------------------------------------------

class TestEnvTunables:
    def test_env_int_returns_default_when_unset(self, monkeypatch):
        """_env_int falls back to the default when the var is absent."""
        monkeypatch.delenv("LLAMA_N_GPU_LAYERS", raising=False)
        from node.llama_backend import _env_int
        assert _env_int("LLAMA_N_GPU_LAYERS", 0) == 0

    def test_env_int_reads_override(self, monkeypatch):
        """_env_int reads the value from the environment."""
        monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "99")
        from node.llama_backend import _env_int
        assert _env_int("LLAMA_N_GPU_LAYERS", 0) == 99

    def test_env_int_falls_back_on_garbage(self, monkeypatch):
        """A non-numeric value must not crash the import; the default wins."""
        monkeypatch.setenv("LLAMA_CTX_SIZE", "not-a-number")
        from node.llama_backend import _env_int
        assert _env_int("LLAMA_CTX_SIZE", 4096) == 4096

    def test_defaults_preserve_historical_behaviour(self, monkeypatch):
        """With no env vars set, the module keeps CPU-only 4096-ctx defaults."""
        monkeypatch.delenv("LLAMA_N_GPU_LAYERS", raising=False)
        monkeypatch.delenv("LLAMA_CTX_SIZE", raising=False)
        import node.llama_backend as lb
        assert lb._n_gpu_layers() == 0
        assert lb._ctx_size() == 4096

    def test_env_vars_drive_module_constants(self, monkeypatch):
        """Setting the env vars changes the values WITHOUT any module reload."""
        monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "99")
        monkeypatch.setenv("LLAMA_CTX_SIZE", "8192")
        import node.llama_backend as lb
        assert lb._n_gpu_layers() == 99
        assert lb._ctx_size() == 8192

    def test_n_threads_env_overrides_hardcoded_default(self, monkeypatch):
        """LLAMA_N_THREADS overrides the historical max(4, cpu_count) default."""
        import node.llama_backend as lb
        monkeypatch.delenv("LLAMA_N_THREADS", raising=False)
        assert lb._n_threads() == max(4, __import__("os").cpu_count() or 4)
        monkeypatch.setenv("LLAMA_N_THREADS", "6")
        assert lb._n_threads() == 6

    def test_server_backend_builds_cmd_with_env_tunables(self, tmp_path, monkeypatch):
        """_LlamaServerBackend reads ctx/gpu-layers/threads from env at init time."""
        monkeypatch.setenv("LLAMA_CTX_SIZE", "8192")
        monkeypatch.setenv("LLAMA_N_GPU_LAYERS", "99")
        monkeypatch.setenv("LLAMA_N_THREADS", "6")

        fake_gguf = tmp_path / "model.gguf"
        fake_gguf.touch()
        fake_bin = tmp_path / "llama-server.exe"
        fake_bin.touch()
        monkeypatch.setenv("LLAMA_SERVER_PATH", str(fake_bin))

        from node.llama_backend import _LlamaServerBackend
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(pid=1234)

        with (
            # 1st ping: no server yet; 2nd ping: "started"
            patch.object(_LlamaServerBackend, "_ping", MagicMock(side_effect=[False, True])),
            patch("node.llama_backend.subprocess.Popen", side_effect=fake_popen),
        ):
            _LlamaServerBackend(fake_gguf, port=18088)

        cmd = captured["cmd"]
        assert cmd[cmd.index("--ctx-size") + 1] == "8192"
        assert cmd[cmd.index("--n-gpu-layers") + 1] == "99"
        assert cmd[cmd.index("--threads") + 1] == "6"
        assert cmd[cmd.index("--threads-batch") + 1] == "6"

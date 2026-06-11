"""
node/llama_backend.py
=====================
Optional llama.cpp acceleration layer for local inference.

Priority order:
  1. llama-cpp-python (in-process, fastest)
  2. llama-server subprocess (pre-built binary, OpenAI-compatible REST API)
  3. Returns None → orchestrator falls back to numpy/C shard inference

This module NEVER raises — every public function returns None on failure so
the rest of Cognia keeps working unchanged.

Setup (run once when disk space is available):
  pip install llama-cpp-python          # Python 3.12 or lower
  # OR download llama-server binary from https://github.com/ggerganov/llama.cpp/releases
  # and place it in node/ or anywhere in PATH.

  Model (GGUF, ~2GB):
    huggingface-cli download bartowski/Qwen2.5-Coder-3B-Instruct-GGUF \
        --include "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf" \
        --local-dir model_shards/qwen-coder-3b-q4

  Then set in .env:
    LLAMA_GGUF_PATH=model_shards/qwen-coder-3b-q4/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf
    LLAMA_SERVER_PORT=8088   # optional, default 8088 (avoids clash with app :8000)

NOTE: node/llama-server.exe is pinned to b9391 (7fb1e70b5) — b9414 has a ~37% CPU
decode regression measured on i3-10110U (5.2 vs 8.2 tok/s). Do NOT update the binary
without re-running the A/B (real server, /completion, timings.predicted_per_second).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_PORT   = 8088
_SERVER_TIMEOUT = 30      # seconds to wait for llama-server to start
# 16384: GGUF n_ctx_train=32768; Qwen2.5-3B uses GQA (2 KV heads) so KV cache is
# ~36KB/token => ~590MB at 16k on a 12GB machine. Enables large file/repo prompts.
_CTX_SIZE       = 16384
_N_GPU_LAYERS   = 0       # CPU only; Intel UHD integrated GPU (Vulkan) is slower than CPU on i3-10110U (3.8 vs 8.8 tok/s)

# Q4_K_M listed first: measured on i3-10110U with llama-server b9391 it is faster
# AND higher quality than Q4_0 — decode 8.09 tok/s / prefill 29.3 tok/s (Q4_K_M)
# vs decode 7.58 / prefill 20.3 (Q4_0). Q3_K_S kept as a smaller fallback.
_GGUF_CANDIDATES = [
    "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q4_0.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q3_K_S.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q5_K_M.gguf",
    "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
]

_SERVER_BINARIES = [
    "llama-server",
    "llama-server.exe",
    "llama_server",
    "server",                          # older builds
    str(Path(__file__).parent / "llama-server.exe"),
    str(Path(__file__).parent / "llama-server"),
]


# ── Stop-reason mapping ───────────────────────────────────────────────────────

def _stop_reason(data: dict) -> Optional[str]:
    """Map a /completion response (or final SSE chunk) to 'eos'|'limit'|'word'|None.

    Verified empirically against the pinned b9391 binary (2026-06-10):
    /completion reports stop_type as a string ('eos'|'limit'|'word'|'none')
    plus stopping_word; the LAST streaming SSE chunk carries the same fields.
    /v1/chat/completions streaming instead puts finish_reason ('stop'|'length')
    in choices[0] of the last chunk before [DONE]. Older builds used
    stopped_eos/stopped_limit/stopped_word booleans — kept as fallback.
    """
    st = data.get("stop_type")
    if st in ("eos", "limit", "word"):
        return st
    # Older llama-server builds: boolean flags instead of stop_type
    if data.get("stopped_eos"):
        return "eos"
    if data.get("stopped_limit"):
        return "limit"
    if data.get("stopped_word"):
        return "word"
    # OpenAI-compatible /v1/chat/completions final chunk
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        fr = choices[0].get("finish_reason")
        if fr == "length":
            return "limit"
        if fr == "stop":
            return "eos"
    return None


# ── GGUF path resolution ──────────────────────────────────────────────────────

def _find_gguf() -> Optional[Path]:
    """Return path to GGUF model file, or None if not found."""
    # Explicit env var takes priority
    env_path = os.environ.get("LLAMA_GGUF_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        if p.is_file():
            return p
        logger.warning("[llama_backend] LLAMA_GGUF_PATH set but file not found: %s", p)

    # Search next to the existing NPZ shards
    shard_dir_raw = os.environ.get("SHARD_WEIGHTS_DIR", "model_shards/qwen-coder-3b-q4")
    shard_dir = Path(shard_dir_raw)
    if not shard_dir.is_absolute():
        shard_dir = Path(__file__).parent.parent / shard_dir

    for name in _GGUF_CANDIDATES:
        p = shard_dir / name
        if p.is_file():
            return p

    # Broader search one level up
    for p in shard_dir.parent.rglob("*.gguf"):
        return p

    return None


# ── Backend 1: llama-cpp-python (in-process) ─────────────────────────────────

class _LlamaCppBackend:
    """Thin wrapper around the llama-cpp-python package."""

    def __init__(self, gguf_path: Path) -> None:
        from llama_cpp import Llama  # imported lazily; raises ImportError if missing
        self._model = Llama(
            model_path     = str(gguf_path),
            n_ctx          = _CTX_SIZE,
            n_gpu_layers   = _N_GPU_LAYERS,
            verbose        = False,
        )
        logger.info("[llama_backend] llama-cpp-python loaded: %s", gguf_path.name)

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7) -> Optional[str]:
        try:
            result = self._model(
                prompt,
                max_tokens  = max_tokens,
                temperature = temperature,
                echo        = False,
            )
            return result["choices"][0]["text"]
        except Exception as exc:
            logger.warning("[llama_backend] llama-cpp-python generate failed: %s", exc)
            return None

    @staticmethod
    def available() -> bool:
        try:
            import llama_cpp  # noqa: F401
            return True
        except ImportError:
            return False


# ── Backend 2: llama-server subprocess (REST API) ────────────────────────────

class _LlamaServerBackend:
    """Manages a llama-server subprocess and calls it via its OpenAI-compatible API."""

    def __init__(self, gguf_path: Path, port: int = _DEFAULT_PORT) -> None:
        import urllib.request, json as _json

        self._port    = port
        self._base    = f"http://127.0.0.1:{port}"
        self._proc: Optional[subprocess.Popen] = None
        self._json    = _json
        self._urlreq  = urllib.request
        # Real token count from the last /completion response (None until first call)
        self.last_tokens_predicted: Optional[int] = None
        # Why the last generation stopped: 'eos'|'limit'|'word'|None (see _stop_reason)
        self.last_stop_reason: Optional[str] = None

        # Check if a server is already running on the port
        if self._ping():
            logger.info("[llama_backend] llama-server already running on :%d", port)
            return

        env_server = os.environ.get("LLAMA_SERVER_PATH", "").strip()
        binary = (
            (env_server if env_server and Path(env_server).is_file() else None)
            or shutil.which("llama-server")
            or shutil.which("llama_server")
        )
        if not binary:
            for candidate in _SERVER_BINARIES:
                if Path(candidate).is_file():
                    binary = candidate
                    break
        if not binary:
            raise FileNotFoundError("llama-server binary not found; set LLAMA_SERVER_PATH in .env")

        # Measured on i3-10110U (llama-server b9391, Q4_K_M): decode 8.09 tok/s @3t,
        # prefill 29.3 tok/s @3t vs 22.7 @4t — the 4th logical thread competes with
        # the OS and hurts BOTH phases, so decode AND batch use cpu_count-1.
        n_threads_decode = max(1, (os.cpu_count() or 4) - 1)
        n_threads_batch  = max(1, (os.cpu_count() or 4) - 1)
        cmd = [
            binary,
            "--model",    str(gguf_path),
            "--port",     str(port),
            "--ctx-size", str(_CTX_SIZE),
            "--n-gpu-layers", str(_N_GPU_LAYERS),
            "--threads",  str(n_threads_decode),
            "--threads-batch", str(n_threads_batch),
            "--cache-reuse", "256",
            "--prio",     "2",
            "--flash-attn", "on",
            "--log-disable",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for server to be ready
        deadline = time.time() + _SERVER_TIMEOUT
        while time.time() < deadline:
            if self._ping():
                logger.info("[llama_backend] llama-server started on :%d (pid=%d)",
                            port, self._proc.pid)
                return
            time.sleep(0.5)
        self._proc.kill()
        raise RuntimeError(f"llama-server did not start within {_SERVER_TIMEOUT}s")

    def _ping(self) -> bool:
        try:
            self._urlreq.urlopen(f"{self._base}/health", timeout=1)
            return True
        except Exception:
            return False

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7) -> Optional[str]:
        import urllib.error
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            # cache_prompt: avoid re-prefilling the full history every turn
            "cache_prompt": True,
        }).encode()
        # Proportional timeout: at the measured ~5.5 tok/s a fixed 120s killed any
        # generation past ~660 tokens (returned None silently). 0.6 s/token covers
        # the ~2 tok/s worst case with margin.
        timeout_s = max(120, 30 + int(max_tokens * 0.6))
        try:
            req = self._urlreq.Request(
                f"{self._base}/completion",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=timeout_s) as resp:
                data = self._json.loads(resp.read())
                # Real token count reported by llama-server (replaces len//4 estimates)
                self.last_tokens_predicted = data.get("tokens_predicted")
                self.last_stop_reason = _stop_reason(data)
                return data.get("content", "")
        except Exception as exc:
            logger.warning("[llama_backend] llama-server request failed: %s", exc)
            return None

    def stream_generate(self, prompt: str, max_tokens: int = 256,
                        temperature: float = 0.7):
        """Yield tokens one at a time using llama-server SSE /completion?stream=true."""
        import urllib.error
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            "stream":      True,
            # cache_prompt: avoid re-prefilling the full history every turn
            "cache_prompt": True,
        }).encode()
        # Proportional timeout: at the measured ~5.5 tok/s a fixed 120s killed any
        # generation past ~660 tokens. 0.6 s/token covers the ~2 tok/s worst case.
        timeout_s = max(120, 30 + int(max_tokens * 0.6))
        self.last_stop_reason = None
        try:
            req = self._urlreq.Request(
                f"{self._base}/completion",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=timeout_s) as resp:
                buf = b""
                while True:
                    chunk = resp.read(64)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if line.startswith(b"data:"):
                            try:
                                data = self._json.loads(line[5:].strip())
                                tok = data.get("content", "")
                                if tok:
                                    yield tok
                                if data.get("stop"):
                                    # Final SSE chunk carries the same fields as
                                    # the non-streaming response (verified on b9391)
                                    self.last_tokens_predicted = data.get("tokens_predicted")
                                    self.last_stop_reason = _stop_reason(data)
                                    return
                            except Exception:
                                pass
        except Exception as exc:
            logger.warning("[llama_backend] llama-server stream failed: %s", exc)

    def stream_chat(self, messages: list, max_tokens: int = 512,
                    temperature: float = 0.7):
        """Yield tokens using /v1/chat/completions (multi-turn, OpenAI-compatible)."""
        import urllib.error
        payload = self._json.dumps({
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "stream":      True,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            # cache_prompt: avoid re-prefilling the full history every turn
            "cache_prompt": True,
        }).encode()
        # Proportional timeout: at the measured ~5.5 tok/s a fixed 120s killed any
        # generation past ~660 tokens. 0.6 s/token covers the ~2 tok/s worst case.
        timeout_s = max(120, 30 + int(max_tokens * 0.6))
        self.last_stop_reason = None
        try:
            req = self._urlreq.Request(
                f"{self._base}/v1/chat/completions",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=timeout_s) as resp:
                buf = b""
                while True:
                    chunk = resp.read(64)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if line.startswith(b"data:"):
                            raw = line[5:].strip()
                            if raw == b"[DONE]":
                                return
                            try:
                                data = self._json.loads(raw)
                                choice = (data.get("choices") or [{}])[0]
                                tok = choice.get("delta", {}).get("content", "")
                                if tok:
                                    yield tok
                                # Last chunk before [DONE] carries finish_reason
                                # and timings.predicted_n (verified on b9391)
                                if choice.get("finish_reason"):
                                    self.last_stop_reason = _stop_reason(data)
                                    predicted = data.get("timings", {}).get("predicted_n")
                                    if predicted is not None:
                                        self.last_tokens_predicted = predicted
                            except Exception:
                                pass
        except Exception as exc:
            logger.warning("[llama_backend] stream_chat failed: %s", exc)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            logger.info("[llama_backend] llama-server stopped")

    @staticmethod
    def available() -> bool:
        env_path = os.environ.get("LLAMA_SERVER_PATH", "").strip()
        return bool(
            (env_path and Path(env_path).is_file())
            or shutil.which("llama-server")
            or shutil.which("llama_server")
            or any(Path(c).is_file() for c in _SERVER_BINARIES)
        )


# ── Public facade ─────────────────────────────────────────────────────────────

class LlamaBackend:
    """
    Unified llama.cpp backend. Tries llama-cpp-python first, then llama-server.
    Returns None from generate() if neither is available.

    Usage:
        backend = LlamaBackend.try_load()   # None if nothing available
        if backend:
            text = backend.generate(prompt)
    """

    def __init__(self, impl) -> None:
        self._impl = impl

    @property
    def last_tokens_predicted(self) -> Optional[int]:
        """Real token count from the last generate() call, or None if unknown."""
        return getattr(self._impl, "last_tokens_predicted", None)

    @property
    def last_stop_reason(self) -> Optional[str]:
        """Why the last generation stopped: 'eos'|'limit'|'word'|None (see _stop_reason)."""
        return getattr(self._impl, "last_stop_reason", None)

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7) -> Optional[str]:
        return self._impl.generate(prompt, max_tokens, temperature)

    def generate_long(self, prompt: str, max_total_tokens: int = None,
                      chunk_tokens: int = None, temperature: float = 0.7,
                      on_chunk=None) -> Optional[dict]:
        """
        Long-form generation via auto-continuation (FASE 1, target 5000 tokens).

        Generates chunk_tokens per round; while the round stops at the n_predict
        cap (last_stop_reason == 'limit') and the running total is below
        max_total_tokens, re-launches with prompt + accumulated text. Because
        every payload sends cache_prompt:true, llama-server re-uses the shared
        prefix KV-cache and each continuation only prefills the new tail.
        Stop strings are kept: an emitted <|im_end|> is a legitimate natural end.

        on_chunk: optional callback on_chunk(round, chunk_tokens, total_tokens,
        stop_reason) for progress reporting.

        Returns {"text", "total_tokens", "stop_reason", "rounds"}; None only if
        the FIRST round fails (same contract as generate()).
        """
        from shattering.model_constants import (
            GEN_CONTINUATION_CHUNK, GEN_LONG_MAX_TOKENS,
        )
        if max_total_tokens is None:
            max_total_tokens = GEN_LONG_MAX_TOKENS
        if chunk_tokens is None:
            chunk_tokens = GEN_CONTINUATION_CHUNK

        text_parts: list = []
        total_tokens = 0
        rounds       = 0
        stop_reason: Optional[str] = None

        while total_tokens < max_total_tokens:
            ask   = min(chunk_tokens, max_total_tokens - total_tokens)
            chunk = self.generate("".join([prompt] + text_parts),
                                  max_tokens=ask, temperature=temperature)
            if chunk is None:
                # Request failed; surface what we have (None if nothing yet)
                if not text_parts:
                    return None
                stop_reason = "error"
                break
            rounds += 1
            real = self.last_tokens_predicted
            chunk_toks = real if real is not None else max(1, len(chunk) // 4)
            total_tokens += chunk_toks
            text_parts.append(chunk)
            stop_reason = self.last_stop_reason
            if on_chunk is not None:
                try:
                    on_chunk(rounds, chunk_toks, total_tokens, stop_reason)
                except Exception:
                    pass
            if stop_reason != "limit":
                break   # eos/word (natural end) or unknown -> do not continue
            if not chunk:
                break   # no progress despite 'limit' -> avoid an infinite loop

        return {
            "text":         "".join(text_parts),
            "total_tokens": total_tokens,
            "stop_reason":  stop_reason,
            "rounds":       rounds,
        }

    def stream_generate(self, prompt: str, max_tokens: int = 256,
                        temperature: float = 0.7):
        """Yield tokens; falls back to non-streaming generate() if impl has no stream_generate."""
        if hasattr(self._impl, "stream_generate"):
            yield from self._impl.stream_generate(prompt, max_tokens, temperature)
        else:
            result = self._impl.generate(prompt, max_tokens, temperature)
            if result:
                yield result

    def stream_chat(self, messages: list, max_tokens: int = 512,
                    temperature: float = 0.7):
        """Yield tokens using multi-turn /v1/chat/completions."""
        if hasattr(self._impl, "stream_chat"):
            yield from self._impl.stream_chat(messages, max_tokens, temperature)
        else:
            # Flatten history to a single prompt as fallback
            text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            yield from self.stream_generate(text, max_tokens, temperature)

    def stop(self) -> None:
        if hasattr(self._impl, "stop"):
            self._impl.stop()

    @classmethod
    def try_load(cls) -> Optional["LlamaBackend"]:
        """
        Try to build a working backend. Returns None (silently) if:
        - No GGUF model found
        - Neither llama-cpp-python nor llama-server binary is available
        - Any initialisation error
        """
        gguf = _find_gguf()
        if gguf is None:
            return None   # no model → nothing to do

        # Try in-process Python bindings first
        if _LlamaCppBackend.available():
            try:
                return cls(_LlamaCppBackend(gguf))
            except Exception as exc:
                logger.debug("[llama_backend] llama-cpp-python init failed: %s", exc)

        # Try subprocess server
        if _LlamaServerBackend.available():
            port = int(os.environ.get("LLAMA_SERVER_PORT", _DEFAULT_PORT))
            try:
                return cls(_LlamaServerBackend(gguf, port))
            except Exception as exc:
                logger.debug("[llama_backend] llama-server init failed: %s", exc)

        logger.debug("[llama_backend] no backend available (GGUF found but no runtime)")
        return None

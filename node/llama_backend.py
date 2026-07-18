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


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to `default` if unset/garbage."""
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        logger.warning("[llama_backend] %s is not an int; using %d", name, default)
        return default


# All three are machine-dependent, so they are env-overridable with the historical
# defaults. Read at CALL time (not import time) so cognia/perf_profiles.py can switch
# CPU/GPU knobs at runtime and the next backend construction picks them up.
# LLAMA_N_GPU_LAYERS=0 (default) keeps the CPU-only behaviour measured on the i3-10110U,
# where the Intel UHD iGPU (Vulkan) was SLOWER than the CPU (3.8 vs 8.8 tok/s).
# On a machine with a real CUDA GPU set LLAMA_N_GPU_LAYERS=99 to offload every layer.

def _ctx_size() -> int:
    return _env_int("LLAMA_CTX_SIZE", 4096)


def _n_gpu_layers() -> int:
    return _env_int("LLAMA_N_GPU_LAYERS", 0)


def _n_threads() -> int:
    return _env_int("LLAMA_N_THREADS", max(4, os.cpu_count() or 4))


def _draft_gguf() -> Optional[Path]:
    """Draft GGUF for classic speculative decoding (cognia 'dspark' mode).

    Read at CALL time from LLAMA_DRAFT_GGUF_PATH (persisted/cleared by
    cognia/velocity.py, same pattern as the perf-profile knobs above).
    Returns the path only when the var points to an existing file;
    unset/empty/missing file -> None (no speculative flags added).
    """
    raw = os.environ.get("LLAMA_DRAFT_GGUF_PATH", "").strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p
    logger.warning("[llama_backend] LLAMA_DRAFT_GGUF_PATH set but file not found: %s", p)
    return None

# Q4_0 listed first: faster dequantization on CPU (~7.2 tok/s measured on i3-10110U, threads=4)
# Q3_K_S second: ~7.7 tok/s on same hw, slightly lower quality; swap top two to prefer quality
_GGUF_CANDIDATES = [
    "Qwen2.5-Coder-3B-Instruct-Q4_0.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q3_K_S.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
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
            n_ctx          = _ctx_size(),
            n_gpu_layers   = _n_gpu_layers(),
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

        n_threads = _n_threads()
        cmd = [
            binary,
            "--model",    str(gguf_path),
            "--port",     str(port),
            "--ctx-size", str(_ctx_size()),
            "--n-gpu-layers", str(_n_gpu_layers()),
            "--threads",  str(n_threads),
            "--threads-batch", str(n_threads),
            "--prio",     "2",
            "--flash-attn", "on",
            "--log-disable",
        ]
        # Speculative decoding (modo 'dspark' de cognia/velocity.py): draft
        # clasico 0.5B + corte por confianza. Medido 2026-07-18 (RTX 5060 Ti,
        # b10066, mediana de 3, n_predict=128, T=0): base 87.5 tok/s; con
        # draft coder-0.5b Q8_0: codigo 142.9 tok/s (1.63x), prosa chat 72.3
        # (0.83x). OJO b10066: sin --spec-type draft-simple, --model-draft es
        # un no-op SILENCIOSO (el server ni carga el draft); el 1.00x
        # historico en GPU era exactamente eso. --spec-draft-p-min 0.75 corta
        # los drafts condenados: prosa 56.0 -> 72.3 y codigo 139.7 -> 142.9.
        draft = _draft_gguf()
        if draft is not None:
            cmd += [
                "--model-draft",      str(draft),
                "--spec-type",        "draft-simple",
                "--gpu-layers-draft", str(_n_gpu_layers()),
                "--spec-draft-n-max", "8",
                "--spec-draft-n-min", "1",
                "--spec-draft-p-min", "0.75",
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
        }).encode()
        try:
            req = self._urlreq.Request(
                f"{self._base}/completion",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=120) as resp:
                data = self._json.loads(resp.read())
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
        }).encode()
        try:
            req = self._urlreq.Request(
                f"{self._base}/completion",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=120) as resp:
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
        }).encode()
        try:
            req = self._urlreq.Request(
                f"{self._base}/v1/chat/completions",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=120) as resp:
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
                                tok = (data.get("choices") or [{}])[0] \
                                          .get("delta", {}).get("content", "")
                                if tok:
                                    yield tok
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

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7) -> Optional[str]:
        return self._impl.generate(prompt, max_tokens, temperature)

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

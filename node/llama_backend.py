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
# 90s: la carga fria del GGUF de 1.9GB desde disco excede 30s (fallo el E2E del
# 2026-06-11 al primer intento); con el archivo en cache de disco carga en segundos.
_SERVER_TIMEOUT = 90      # seconds to wait for llama-server to start
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


# ── Sampling params ───────────────────────────────────────────────────────────

def _sampling_payload(top_p=None, top_k=None, min_p=None,
                      repeat_penalty=None, seed=None) -> dict:
    """Dict con SOLO los sampling params no-None, listo para mergear al payload.

    Nombres estandar de llama.cpp aceptados nativos por llama-server b9391 en
    /completion y /v1/chat/completions: top_p, top_k, min_p, repeat_penalty,
    seed. Si todos son None devuelve {} y el payload queda identico al actual
    (defaults del server intactos).
    """
    out = {}
    if top_p is not None:
        out["top_p"] = top_p
    if top_k is not None:
        out["top_k"] = top_k
    if min_p is not None:
        out["min_p"] = min_p
    if repeat_penalty is not None:
        out["repeat_penalty"] = repeat_penalty
    if seed is not None:
        out["seed"] = seed
    return out


# ── /props parsing ────────────────────────────────────────────────────────────

def _server_props_summary(data: dict) -> dict:
    """Parseo puro de la respuesta de GET /props de llama-server -> resumen.

    Campos observados en builds recientes (a verificar contra b9391):
    default_generation_settings.n_ctx (contexto por slot), model_path (GGUF
    cargado), build_info y total_slots a nivel raiz. Devuelve dict con claves
    fijas y None donde el campo no este, para que el caller loguee sin KeyError.
    """
    dgs = data.get("default_generation_settings") or {}
    return {
        "n_ctx":       dgs.get("n_ctx"),
        "model_path":  data.get("model_path"),
        "build_info":  data.get("build_info"),
        "total_slots": data.get("total_slots"),
    }


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


# ── LoRA adapter args ─────────────────────────────────────────────────────────

def _lora_args() -> list:
    """Args extra de adapter LoRA para el cmd de llama-server, o [].

    Si LLAMA_LORA_PATH apunta a un adapter GGUF existente (salida de
    convert_lora_to_gguf.py de llama.cpp; el b9391 pineado soporta --lora)
    devuelve ["--lora", path]. Seteada pero el archivo no existe -> warning y
    el server arranca SIN adapter. No seteada -> [] (cmd identico al actual).
    """
    env_path = os.environ.get("LLAMA_LORA_PATH", "").strip()
    if not env_path:
        return []
    p = Path(env_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    if p.is_file():
        logger.info("[llama_backend] LoRA adapter: %s", p)
        return ["--lora", str(p)]
    logger.warning("[llama_backend] LLAMA_LORA_PATH set but file not found: %s", p)
    return []


# ── Backend 1: llama-cpp-python (in-process) ─────────────────────────────────

class _LlamaCppBackend:
    """Thin wrapper around the llama-cpp-python package."""

    def __init__(self, gguf_path: Path) -> None:
        from llama_cpp import Llama  # imported lazily; raises ImportError if missing
        self._gguf_path = gguf_path   # expuesto via LlamaBackend.gguf_path (/modelo)
        self._model = Llama(
            model_path     = str(gguf_path),
            n_ctx          = _CTX_SIZE,
            n_gpu_layers   = _N_GPU_LAYERS,
            verbose        = False,
        )
        # Mirror _LlamaServerBackend: token count real + stop reason del ultimo
        # generate(), para que la auto-continuacion (generate_long) funcione tambien
        # in-process. Sin esto last_stop_reason era siempre None y el loop cortaba
        # tras la ronda 1 (None != 'limit').
        self.last_tokens_predicted: Optional[int] = None
        self.last_stop_reason: Optional[str] = None
        logger.info("[llama_backend] llama-cpp-python loaded: %s", gguf_path.name)

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None) -> Optional[str]:
        # cache_prompt se ignora: backend in-process, no hay KV-cache de server.
        # grammar se ignora: el binding exige un objeto LlamaGrammar, no el
        # string GBNF crudo que acepta llama-server (fuera de alcance aca).
        # llama-cpp-python soporta los 5 sampling kwargs nativos (min_p desde
        # 0.2.20). Un binding mas viejo levanta TypeError -> lo atrapa el
        # except de abajo (mismo contrato: None en fallo).
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        try:
            result = self._model(
                prompt,
                max_tokens  = max_tokens,
                temperature = temperature,
                echo        = False,
                # Mismos stop strings que el server backend: corta en fin de turno
                # ChatML en vez de seguir generando texto del siguiente turno.
                stop        = ["<|im_end|>", "<|endoftext|>"],
                **extra,
            )
            # Mismo contrato que el server backend: token count real + stop reason.
            # llama-cpp-python devuelve formato OpenAI (choices[0].finish_reason
            # 'length'|'stop' + usage.completion_tokens); _stop_reason ya lo mapea a
            # 'limit'|'eos', habilitando la continuacion de generate_long.
            self.last_tokens_predicted = (result.get("usage") or {}).get("completion_tokens")
            self.last_stop_reason = _stop_reason(result)
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
        self._gguf_path = gguf_path   # expuesto via LlamaBackend.gguf_path (/modelo)
        self._json    = _json
        self._urlreq  = urllib.request
        # Real token count from the last /completion response (None until first call)
        self.last_tokens_predicted: Optional[int] = None
        # Why the last generation stopped: 'eos'|'limit'|'word'|None (see _stop_reason)
        self.last_stop_reason: Optional[str] = None

        # Check if a server is already running on the port
        if self._ping():
            logger.info("[llama_backend] llama-server already running on :%d", port)
            # Server adoptado sin verificar flags: loguear su config real via
            # /props y avisar si el contexto no coincide con el esperado.
            self._check_adopted_server()
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
        # Adapter LoRA local opcional (env LLAMA_LORA_PATH -> ["--lora", path])
        cmd += _lora_args()
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

    def props(self) -> Optional[dict]:
        """GET /props del server (JSON crudo), o None si falla."""
        try:
            with self._urlreq.urlopen(f"{self._base}/props", timeout=5) as resp:
                return self._json.loads(resp.read())
        except Exception as exc:
            logger.debug("[llama_backend] GET /props failed: %s", exc)
            return None

    def _check_adopted_server(self) -> None:
        """Loguea la config real de un server preexistente; warn si n_ctx difiere.

        No falla duro: un server ajeno con otro contexto sigue siendo usable,
        pero el mismatch explica diferencias de calidad/velocidad en benchmarks.
        """
        data = self.props()
        if not data:
            logger.warning("[llama_backend] adopted server: /props unavailable, "
                           "cannot verify n_ctx/model")
            return
        summary = _server_props_summary(data)
        logger.info("[llama_backend] adopted server: n_ctx=%s model=%s",
                    summary["n_ctx"], summary["model_path"])
        if summary["n_ctx"] is not None and summary["n_ctx"] != _CTX_SIZE:
            logger.warning("[llama_backend] adopted server n_ctx=%s != expected "
                           "_CTX_SIZE=%d — results may differ from a self-started "
                           "server", summary["n_ctx"], _CTX_SIZE)

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None) -> Optional[str]:
        import urllib.error
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            # cache_prompt True (default): no re-prefilla el historial entero.
            # False: prefill completo — el KV-cache reusado cambia los logits
            # (experimento 2026-06-11), necesario para benchmarks deterministas.
            "cache_prompt": cache_prompt,
            # grammar: string GBNF que el server compila y usa para restringir
            # el sampling (campo nativo de /completion en b9391). Solo si se
            # pasa: sin grammar el payload queda identico al actual.
            **({"grammar": grammar} if grammar is not None else {}),
            # Sampling params: solo los no-None (defaults del server intactos)
            **_sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                repeat_penalty=repeat_penalty, seed=seed),
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
                        temperature: float = 0.7, top_p=None, top_k=None,
                        min_p=None, repeat_penalty=None, seed=None,
                        cache_prompt: bool = True, grammar: str = None):
        """Yield tokens one at a time using llama-server SSE /completion?stream=true."""
        import urllib.error
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            "stream":      True,
            # cache_prompt True (default): no re-prefilla el historial entero.
            # False: prefill completo (logits deterministas, ver generate()).
            "cache_prompt": cache_prompt,
            # grammar: string GBNF, solo si se pasa (ver generate())
            **({"grammar": grammar} if grammar is not None else {}),
            # Sampling params: solo los no-None (defaults del server intactos)
            **_sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                repeat_penalty=repeat_penalty, seed=seed),
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
                    temperature: float = 0.7, top_p=None, top_k=None,
                    min_p=None, repeat_penalty=None, seed=None,
                    cache_prompt: bool = True):
        """Yield tokens using /v1/chat/completions (multi-turn, OpenAI-compatible)."""
        import urllib.error
        payload = self._json.dumps({
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "stream":      True,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            # cache_prompt True (default): no re-prefilla el historial entero.
            # False: prefill completo (logits deterministas, ver generate()).
            "cache_prompt": cache_prompt,
            # Sampling params: solo los no-None. llama-server acepta los nombres
            # nativos (top_k/min_p/repeat_penalty/seed) tambien en el endpoint
            # OpenAI-compatible (extension propia de llama.cpp).
            **_sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                repeat_penalty=repeat_penalty, seed=seed),
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

    def stop(self) -> bool:
        """Para el llama-server propio. Devuelve True si el puerto quedo libre.

        Un server ADOPTADO (arrancado externamente, self._proc is None) no es
        nuestro proceso y no se puede matar limpio desde aca: si sigue
        respondiendo al health-check se devuelve False para que el caller
        (p.ej. /modelo) avise al usuario en vez de adoptar el modelo viejo.
        """
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            logger.info("[llama_backend] llama-server stopped")
        alive = self._ping()
        if alive and self._proc is None:
            logger.warning("[llama_backend] server adoptado sigue vivo en :%d "
                           "(proceso externo; no se puede parar desde aca)",
                           self._port)
        return not alive

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

    @property
    def gguf_path(self) -> Optional[Path]:
        """Ruta del GGUF con el que se construyo el impl, o None si no la expone."""
        return getattr(self._impl, "_gguf_path", None)

    def server_props(self) -> Optional[dict]:
        """JSON crudo de GET /props del impl server, o None (in-process no tiene)."""
        fn = getattr(self._impl, "props", None)
        return fn() if callable(fn) else None

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None) -> Optional[str]:
        # Sampling params: se reenvian SOLO si no son None, asi un impl viejo
        # sin esos kwargs sigue funcionando con la llamada posicional de siempre.
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        # cache_prompt: se reenvia SOLO cuando es False (el default True del
        # impl queda intacto y los impls viejos sin el kwarg siguen andando).
        if not cache_prompt:
            extra["cache_prompt"] = False
        # grammar (string GBNF): solo si se pasa, mismo criterio que arriba.
        if grammar is not None:
            extra["grammar"] = grammar
        return self._impl.generate(prompt, max_tokens, temperature, **extra)

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
                        temperature: float = 0.7, top_p=None, top_k=None,
                        min_p=None, repeat_penalty=None, seed=None,
                        cache_prompt: bool = True, grammar: str = None):
        """Yield tokens; falls back to non-streaming generate() if impl has no stream_generate."""
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        # cache_prompt: solo cuando es False (ver generate())
        if not cache_prompt:
            extra["cache_prompt"] = False
        # grammar (string GBNF): solo si se pasa (ver generate())
        if grammar is not None:
            extra["grammar"] = grammar
        if hasattr(self._impl, "stream_generate"):
            yield from self._impl.stream_generate(prompt, max_tokens, temperature, **extra)
        else:
            result = self._impl.generate(prompt, max_tokens, temperature, **extra)
            if result:
                yield result

    def stream_chat(self, messages: list, max_tokens: int = 512,
                    temperature: float = 0.7, top_p=None, top_k=None,
                    min_p=None, repeat_penalty=None, seed=None,
                    cache_prompt: bool = True):
        """Yield tokens using multi-turn /v1/chat/completions."""
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        # cache_prompt: solo cuando es False (ver generate())
        if not cache_prompt:
            extra["cache_prompt"] = False
        if hasattr(self._impl, "stream_chat"):
            yield from self._impl.stream_chat(messages, max_tokens, temperature, **extra)
        else:
            # Flatten history to a single prompt as fallback
            text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            yield from self.stream_generate(text, max_tokens, temperature, **extra)

    def stop(self) -> bool:
        """Para el server si el impl lo maneja. True si quedo parado (o no habia server).

        El impl in-process (llama-cpp-python) no tiene stop(): se devuelve True
        porque no hay puerto que liberar (el modelo viejo lo libera el GC).
        """
        if hasattr(self._impl, "stop"):
            return bool(self._impl.stop())
        return True

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

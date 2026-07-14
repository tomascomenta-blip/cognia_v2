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

import json
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
# 90s cubria el GGUF 3B de 1.9GB, pero el 7B (4.7GB) tarda >90s en carga fria en
# el i3 (falla "did not start within 90s", medido 2026-07-04). El wait es un
# poll a /health que CORTA apenas responde, asi que un timeout mas alto NO
# ralentiza un arranque rapido — solo tolera cargas lentas. Env-overridable.
_SERVER_TIMEOUT = int(os.environ.get("LLAMA_SERVER_TIMEOUT", "240"))  # seg
# 32768 = n_ctx_train del GGUF (nativo, sin RoPE OOD). Qwen2.5-3B usa GQA
# (2 KV heads) => KV cache ~36KB/token => ~1.2GB a 32k en una maquina de 12GB.
# Duplica el prefill plano y el presupuesto de outline/seccion en generacion
# larga. Env-overridable (bajar a 16384 si la RAM aprieta).
_CTX_SIZE       = int(os.environ.get("LLAMA_CTX_SIZE", "32768"))
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

def _fleet_manifest(gguf_path: Optional[Path]) -> list:
    """Manifiesto del fleet: adapters.json junto al GGUF, o [].

    Formato: {"adapters": [{"name": "accion", "file": "cognia3b_v1_f16.gguf"}]}
    "file" es relativo al dir del GGUF (o absoluto). Entradas con archivo
    inexistente se saltean con warning (el server arranca igual con el resto).
    El ORDEN de la lista define los ids que llama-server les asigna (0..n-1).
    """
    if gguf_path is None:
        return []
    manifest = Path(gguf_path).parent / "adapters.json"
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[llama_backend] adapters.json ilegible (%s); fleet OFF", exc)
        return []
    out = []
    for entry in data.get("adapters", []):
        name = (entry.get("name") or "").strip()
        file_ = (entry.get("file") or "").strip()
        if not name or not file_:
            logger.warning("[llama_backend] adapters.json: entrada sin name/file: %r", entry)
            continue
        p = Path(file_)
        if not p.is_absolute():
            p = Path(gguf_path).parent / p
        if not p.is_file():
            logger.warning("[llama_backend] adapters.json: no existe %s (salteado)", p)
            continue
        out.append({"name": name, "path": p})
    return out


def _lora_args(gguf_path: Optional[Path] = None) -> tuple:
    """(args extra de LoRA para el cmd de llama-server, nombres del fleet).

    Precedencia:
    1. LLAMA_LORA_PATH seteada -> UN adapter estatico aplicado (["--lora", p], [])
       — comportamiento historico, sin fleet.
    2. adapters.json junto al GGUF -> fleet: todos los adapters cargados con
       --lora-init-without-apply (scale 0.0 = base pura) y hot-swap por request
       via POST /lora-adapters (validado 2026-07-07: swap 2-41 ms, FLEET_DESIGN).
    3. Nada -> ([], []) (cmd identico al actual).
    """
    env_path = os.environ.get("LLAMA_LORA_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        if p.is_file():
            logger.info("[llama_backend] LoRA adapter (estatico): %s", p)
            return ["--lora", str(p)], []
        logger.warning("[llama_backend] LLAMA_LORA_PATH set but file not found: %s", p)
        return [], []
    fleet = _fleet_manifest(gguf_path)
    if not fleet:
        return [], []
    args = ["--lora-init-without-apply"]
    for a in fleet:
        args += ["--lora", str(a["path"])]
    logger.info("[llama_backend] fleet: %d adapter(s) cargados sin aplicar: %s",
                len(fleet), [a["name"] for a in fleet])
    return args, [a["name"] for a in fleet]


# ── Speculative decoding args ─────────────────────────────────────────────────

# Solo drafters de coste de banda ~0 (variantes ngram): escanean el contexto, sin
# modelo extra ni entrenamiento. Se PROHIBE 'draft-*' (draft model separado): en CPU
# bandwidth-bound compite por banda + nucleos y mide 0.37x en habla (exp021/cycle34).
_SPEC_NGRAM_ALLOWED = {"ngram-mod", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-cache"}


def _spec_args() -> list:
    """Args de speculative decoding para el cmd de llama-server, o [].

    Default 'ngram-mod': drafter n-gram que escanea el contexto y resulta BIT-IDENTICO
    a la salida normal a temp=0 (verificacion exacta); gana en texto repetitivo/codigo/
    RAG sin coste de modelo extra ni entrenamiento (exp021/cycle34: hasta 1.45x lossless
    en eco; ngram-mod nunca mas lento en lo medido). COGNIA_SPEC_TYPE=none lo desactiva.
    'draft-*' queda prohibido (en CPU bandwidth-bound un draft separado mide 0.37x).
    """
    spec = os.environ.get("COGNIA_SPEC_TYPE", "ngram-mod").strip()
    if spec in _SPEC_NGRAM_ALLOWED:
        return ["--spec-type", spec]
    if spec and spec != "none":
        logger.warning("[llama_backend] COGNIA_SPEC_TYPE=%r ignorado (solo variantes "
                       "ngram; draft-* prohibido en CPU); speculative OFF", spec)
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
                 cache_prompt: bool = True, grammar: str = None,
                 stop=None) -> Optional[str]:
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
                # ChatML; MERGE con los stops extra del caller (nunca reemplaza).
                stop        = ["<|im_end|>", "<|endoftext|>"] + list(stop or []),
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

    def __init__(self, gguf_path: Path, port: int = _DEFAULT_PORT,
                 lora_path: Optional[Path] = None,
                 ctx_size: Optional[int] = None) -> None:
        import urllib.request, json as _json

        self._port    = port
        self._base    = f"http://127.0.0.1:{port}"
        self._proc: Optional[subprocess.Popen] = None
        self._gguf_path = gguf_path   # expuesto via LlamaBackend.gguf_path (/modelo)
        # LoRA ESTATICA aplicada por parametro (portero 0.5B, PREREG_PORTERO_FASE2):
        # a diferencia de LLAMA_LORA_PATH (env global, envenenaria TODOS los
        # servers del proceso) esto es por-instancia. Excluye el fleet hot-swap.
        self._lora_path = Path(lora_path) if lora_path else None
        # ctx por instancia: el portero usa 4096 (turnos triviales; KV chico)
        # sin tocar el 32k del server principal.
        self._ctx_size = int(ctx_size) if ctx_size else _CTX_SIZE
        self._json    = _json
        self._urlreq  = urllib.request
        # Real token count from the last /completion response (None until first call)
        self.last_tokens_predicted: Optional[int] = None
        # Why the last generation stopped: 'eos'|'limit'|'word'|None (see _stop_reason)
        self.last_stop_reason: Optional[str] = None
        # HARNESS #1: telemetria de KV-cache (timings del ultimo /completion).
        self.last_timings: dict = {}
        self.last_prompt_n: Optional[int] = None
        self.last_prompt_ms: Optional[float] = None
        # Fleet de expertos LoRA (FLEET_DESIGN): nombres en orden de carga
        # (id de llama-server = indice), experto activo, y flag de swap
        # pendiente — tras un POST /lora-adapters el KV cache es invalido y la
        # PRIMERA request debe ir con cache_prompt=false (regla medida).
        self._fleet_names: list = []
        self._active_expert: Optional[str] = None
        self._lora_dirty: bool = False

        # Check if a server is already running on the port
        if self._ping():
            logger.info("[llama_backend] llama-server already running on :%d", port)
            # Server adoptado sin verificar flags: loguear su config real via
            # /props y avisar si el contexto no coincide con el esperado.
            self._check_adopted_server()
            if self._lora_path is not None:
                # Con LoRA estatica pedida NO se adopta un server que no la
                # tenga aplicada: serviria la base pelada como si fuera el
                # experto (identidad silenciosamente rota). Raise -> el caller
                # (speech_cascade) cae al 3B, que es el fallback seguro.
                self._check_adopted_static_lora()
            else:
                self._adopt_fleet()
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
            # --host 127.0.0.1: bind SOLO a localhost, explicito (no depender del
            # default del binario). Los servers de inferencia (fleet 8088, portero
            # 8090, heavy 8092) son INTERNOS — el cliente conecta a 127.0.0.1 (self.
            # _base). Sin esto, un binario que default-ee a 0.0.0.0 expondria el
            # modelo local a la LAN, en contra del core "IA local, privada".
            "--host",     "127.0.0.1",
            "--port",     str(port),
            "--ctx-size", str(self._ctx_size),
            "--n-gpu-layers", str(_N_GPU_LAYERS),
            "--threads",  str(n_threads_decode),
            "--threads-batch", str(n_threads_batch),
            "--cache-reuse", "256",
            # b9391 defaultea --cache-ram 8192 MiB *por server*: con 3-4
            # servers de la colonia coexistiendo en 12GB es swap/OOM latente
            # en sesiones largas (verificado contra --help del binario
            # pineado, 2026-07-12). Acotado; override LLAMA_CACHE_RAM_MIB.
            "--cache-ram", os.environ.get("LLAMA_CACHE_RAM_MIB", "1024"),
            "--prio",     "2",
            "--flash-attn", "on",
            "--log-disable",
        ]
        # Speculative decoding (exp021/cycle34): ngram-mod por defecto — bit-identico,
        # gratis, gana en texto repetitivo/codigo/RAG. COGNIA_SPEC_TYPE=none lo desactiva.
        cmd += _spec_args()
        if self._lora_path is not None:
            # LoRA estatica por parametro (portero): aplicada al arrancar
            # (scale 1.0), sin fleet ni hot-swap en este server.
            cmd += ["--lora", str(self._lora_path)]
            self._fleet_names = []
        else:
            # LoRA: estatico (LLAMA_LORA_PATH) o fleet (adapters.json junto al GGUF)
            lora_cmd, self._fleet_names = _lora_args(gguf_path)
            cmd += lora_cmd
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
                self._force_base_scales()
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
        if summary["n_ctx"] is not None and summary["n_ctx"] != self._ctx_size:
            logger.warning("[llama_backend] adopted server n_ctx=%s != expected "
                           "ctx_size=%d — results may differ from a self-started "
                           "server", summary["n_ctx"], self._ctx_size)

    def _check_adopted_static_lora(self) -> None:
        """Server adoptado cuando se pidio LoRA estatica: exigir que ESE server
        tenga la LoRA cargada con scale > 0. Si no se puede confirmar via
        GET /lora-adapters -> RuntimeError (el caller hace fallback; nunca
        servir la base pelada haciendose pasar por el experto)."""
        quiero = self._lora_path.name
        vivos = self.lora_adapters()
        ok = any(Path(a.get("path", "")).name == quiero
                 and float(a.get("scale", 0.0) or 0.0) > 0.0
                 for a in (vivos or []))
        if not ok:
            raise RuntimeError(
                f"server adoptado en :{self._port} sin la LoRA {quiero} aplicada "
                f"(adapters vivos: {[Path(a.get('path', '')).name for a in (vivos or [])]})")

    # ── Fleet de expertos LoRA (hot-swap POST /lora-adapters) ────────────────

    def _adopt_fleet(self) -> None:
        """Server adoptado: reconstruye el fleet matcheando el manifiesto local
        contra GET /lora-adapters por basename. Mismatch -> fleet OFF (warning);
        nunca asumir que un server ajeno cargo los adapters esperados."""
        if os.environ.get("LLAMA_LORA_PATH", "").strip():
            return  # modo estatico historico: sin fleet
        manifest = _fleet_manifest(self._gguf_path)
        if not manifest:
            return
        vivos = self.lora_adapters()
        if vivos is None:
            logger.warning("[llama_backend] server adoptado sin /lora-adapters; fleet OFF")
            return
        vivos_por_base = {Path(a.get("path", "")).name: a.get("id") for a in vivos}
        nombres = []
        for a in manifest:
            aid = vivos_por_base.get(a["path"].name)
            if aid is None or aid != len(nombres):
                logger.warning("[llama_backend] server adoptado no cargo el fleet del "
                               "manifiesto (falta %s o ids corridos); fleet OFF — "
                               "matar llama-server.exe y relanzar", a["path"].name)
                return
            nombres.append(a["name"])
        self._fleet_names = nombres
        logger.info("[llama_backend] fleet adoptado: %s", nombres)
        self._force_base_scales()

    def _force_base_scales(self) -> None:
        """Arranque del fleet: fuerza TODOS los scales a 0.0 (base pura).

        Medido 2026-07-08: aun con --lora-init-without-apply el b9391 reporta
        el adapter con scale 1.0 al arrancar — el estado inicial NO es base.
        Se postea explicito en vez de confiar en el flag."""
        if not self._fleet_names:
            return
        self._active_expert = "__arranque__"   # sentinela: fuerza el POST real
        if not self.activate_expert(None):
            logger.warning("[llama_backend] no se pudo forzar base al arrancar; "
                           "fleet OFF por seguridad")
            self._fleet_names = []
            self._active_expert = None

    def lora_adapters(self) -> Optional[list]:
        """GET /lora-adapters del server (lista cruda), o None si falla."""
        try:
            with self._urlreq.urlopen(f"{self._base}/lora-adapters", timeout=5) as resp:
                return self._json.loads(resp.read())
        except Exception as exc:
            logger.debug("[llama_backend] GET /lora-adapters failed: %s", exc)
            return None

    def activate_expert(self, name: Optional[str]) -> bool:
        """Activa el experto `name` (scale 1.0, resto 0.0) o None = base pura.

        Idempotente y barato: si ya esta activo no hace nada. Tras un swap real
        marca _lora_dirty para que la proxima request fuerce cache_prompt=false
        (el KV cache calculado con otros pesos efectivos es invalido y
        llama.cpp NO lo invalida solo — medido 2026-07-07, FLEET_DESIGN).
        Devuelve True si el experto pedido quedo activo (o ya lo estaba).
        """
        if not self._fleet_names:
            return name is None  # sin fleet, la base "esta activa" por definicion
        if name is not None and name not in self._fleet_names:
            logger.warning("[llama_backend] experto desconocido: %r (fleet: %s)",
                           name, self._fleet_names)
            return False
        if name == self._active_expert:
            return True
        scales = [{"id": i, "scale": 1.0 if n == name else 0.0}
                  for i, n in enumerate(self._fleet_names)]
        try:
            req = self._urlreq.Request(
                f"{self._base}/lora-adapters",
                data=self._json.dumps(scales).encode(),
                headers={"Content-Type": "application/json"},
            )
            self._urlreq.urlopen(req, timeout=10).read()
        except Exception as exc:
            logger.warning("[llama_backend] POST /lora-adapters failed: %s", exc)
            return False
        self._active_expert = name
        self._lora_dirty = True
        logger.info("[llama_backend] experto activo: %s", name or "(base)")
        return True

    def _consume_lora_dirty(self, cache_prompt: bool) -> bool:
        """cache_prompt efectivo: False forzado en la 1ra request post-swap.

        getattr defensivo: instancias parciales (tests de payload) o picklings
        viejos pueden no tener el atributo — sin fleet no hay swap que invalide.
        """
        if getattr(self, "_lora_dirty", False):
            self._lora_dirty = False
            return False
        return cache_prompt

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None,
                 stop=None) -> Optional[str]:
        import urllib.error
        cache_prompt = self._consume_lora_dirty(cache_prompt)
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            # MERGE (no reemplazo): siempre corta en fin-de-turno, y ademas en los
            # stops extra que pase el caller (p.ej. '\nACCION:' del agente).
            "stop":        ["<|im_end|>", "<|endoftext|>"] + list(stop or []),
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
                # HARNESS #1 (telemetria de KV-cache): timings del server.
                # prompt_n = tokens REALMENTE prefilleados este request; con el
                # cache sano, en un paso >1 del loop es chico (solo los tokens
                # nuevos). prompt_ms = costo del prefill (el recurso escaso en
                # CPU). last_prompt_n permite medir cache hit y el efecto ACI.
                tim = data.get("timings") or {}
                self.last_timings = tim
                self.last_prompt_n = tim.get("prompt_n")
                self.last_prompt_ms = tim.get("prompt_ms")
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
        cache_prompt = self._consume_lora_dirty(cache_prompt)
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
        cache_prompt = self._consume_lora_dirty(cache_prompt)
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

    @property
    def fleet_experts(self) -> list:
        """Nombres de expertos LoRA del fleet cargado, o [] (sin fleet)."""
        return list(getattr(self._impl, "_fleet_names", []) or [])

    @property
    def active_expert(self) -> Optional[str]:
        """Experto activo del fleet, o None (base pura / sin fleet)."""
        return getattr(self._impl, "_active_expert", None)

    def activate_expert(self, name: Optional[str]) -> bool:
        """Hot-swap del experto LoRA (None = base). False si el impl no soporta
        fleet (in-process) o el swap fallo. Ver _LlamaServerBackend.activate_expert."""
        fn = getattr(self._impl, "activate_expert", None)
        if not callable(fn):
            return name is None
        return fn(name)

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None,
                 stop=None) -> Optional[str]:
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
        # stop extra (p.ej. '\nACCION:' del loop del agente): solo si se pasa. El
        # impl lo MERGEA con los stops de fin-de-turno, nunca los reemplaza.
        if stop is not None:
            extra["stop"] = stop
        return self._impl.generate(prompt, max_tokens, temperature, **extra)

    def generate_long(self, prompt: str, max_total_tokens: int = None,
                      chunk_tokens: int = None, temperature: float = 0.7,
                      on_chunk=None, resume_text: str = None) -> Optional[dict]:
        """
        Long-form generation via auto-continuation (FASE 1, target 5000 tokens).

        Generates chunk_tokens per round; while the round stops at the n_predict
        cap (last_stop_reason == 'limit') and the running total is below
        max_total_tokens, re-launches with prompt + accumulated text. Because
        every payload sends cache_prompt:true, llama-server re-uses the shared
        prefix KV-cache and each continuation only prefills the new tail.
        Stop strings are kept: an emitted <|im_end|> is a legitimate natural end.

        Ctx guard: cuando prompt+acumulado se acerca a _CTX_SIZE el loop deja de
        reenviar el texto completo y manda prompt + la cola mas reciente, de modo
        que el prefill nunca desborda la ventana (el output sigue siendo completo).

        resume_text: cola YA ESCRITA de una corrida anterior (p.ej. /largo
        --continuar retomando desde un archivo). Se usa SOLO como contexto de
        re-anclaje (se antepone a lo acumulado en ESTA llamada antes de aplicar
        la guarda de ctx); NO se re-emite en el "text" devuelto -- el caller ya
        la tiene persistida. Default None = comportamiento actual (sin cola previa).

        on_chunk: optional callback on_chunk(round, chunk_tokens, total_tokens,
        stop_reason, chunk_text) for progress reporting AND escritura incremental
        (chunk_text es el texto crudo generado en esa ronda, para poder appendearlo
        a un archivo a medida que llega).

        Returns {"text", "total_tokens", "stop_reason", "rounds"}; None only if
        the FIRST round fails (same contract as generate()).
        """
        from shattering.model_constants import (
            GEN_CONTINUATION_CHUNK, GEN_LONG_MAX_TOKENS,
            GEN_CTX_GUARD_RATIO, GEN_CTX_MARGIN_TOKENS,
        )
        if max_total_tokens is None:
            max_total_tokens = GEN_LONG_MAX_TOKENS
        if chunk_tokens is None:
            chunk_tokens = GEN_CONTINUATION_CHUNK
        resume_text = resume_text or ""

        text_parts: list = []
        total_tokens = 0
        rounds       = 0
        stop_reason: Optional[str] = None

        # Techo de prefill: una fraccion del ctx, dejando sitio para el chunk a
        # generar. ~4 chars/token (mismo estimador que el fallback de abajo).
        prefill_cap = int(_CTX_SIZE * GEN_CTX_GUARD_RATIO)

        while total_tokens < max_total_tokens:
            ask   = min(chunk_tokens, max_total_tokens - total_tokens)
            # Guarda de ctx: si prompt+acumulado no entra bajo el techo, no reenviar
            # TODO -> mandar prompt + la cola mas reciente. text_parts conserva el
            # texto completo (la cola es solo input al modelo, no recorta el output).
            # resume_text (si hay) cuenta como acumulado YA ESCRITO -> va primero.
            budget = min(prefill_cap, _CTX_SIZE - ask - GEN_CTX_MARGIN_TOKENS)
            accumulated = resume_text + "".join(text_parts)
            if (len(prompt) + len(accumulated)) // 4 > budget:
                keep_tokens = max(0, budget - len(prompt) // 4)
                accumulated = accumulated[-(keep_tokens * 4):] if keep_tokens else ""
            chunk = self.generate(prompt + accumulated,
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
                    on_chunk(rounds, chunk_toks, total_tokens, stop_reason, chunk)
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

    @staticmethod
    def _append_to_user_turn(prompt: str, extra: str) -> str:
        """Agrega ``extra`` al TURNO DE USUARIO de un prompt ChatML.

        Bug real (medido 2026-07-04): generate_delegated/hierarchical hacian
        f'{prompt}\\n\\n{instruccion}', pero cuando el caller (el CLI) pasa un
        prompt YA templado que termina en '<|im_start|>assistant\\n', la
        instruccion caia DENTRO del turno del asistente -> el modelo creia que
        ya habia terminado y devolvia vacio (eos inmediato). Las sub-generaciones
        del outline/secciones salian de 1 token. Los tests con backends FALSOS no
        lo cazaron (usaban prompts crudos).

        Fix: si el prompt trae el marcador de apertura del asistente al final,
        insertar ``extra`` antes del cierre del turno de usuario (para que el
        modelo lo vea como parte del pedido). Si NO esta templado (prompt crudo),
        se appendea como antes -> compat total con los callers de test."""
        tail = "<|im_end|>\n<|im_start|>assistant\n"
        if prompt.endswith(tail):
            head = prompt[:-len(tail)]
            return f"{head}\n\n{extra}{tail}"
        return f"{prompt}\n\n{extra}"

    @staticmethod
    def _parse_outline(text: str, max_sections: int) -> list:
        """Extrae titulos de seccion de un outline LLM. Robusto al 3B (que a veces no
        respeta 'uno por linea'): (1) lineas numeradas/vinetas; (2) si hay <2 items,
        separa por marcadores numerados INLINE '(1.' / '2)'; (3) fallback a lineas no
        vacias. Capa cada titulo a 120 chars."""
        import re
        text = text or ""
        items = []
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^[\(\[]?(?:\d+[\.\)]|[-*•])\s*(.+)", line)
            if m and m.group(1).strip():
                items.append(m.group(1).strip())
        if len(items) < 2:
            # marcadores numerados en cualquier posicion (el 3B mete '(1. ...' inline)
            chunks = re.split(r"[\(\[]?\b\d+[\.\)]\s+", text)
            cand = [c.strip(" .)\n\t-") for c in chunks if len(c.strip()) > 2]
            if len(cand) >= 2:
                items = cand
        if not items:
            items = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return [it[:120] for it in items][:max_sections]

    def generate_hierarchical(self, prompt: str, target_tokens: int = None,
                              n_sections: int = None, temperature: float = 0.7,
                              on_section=None, on_outline=None) -> Optional[dict]:
        """
        Generacion larga JERARQUICA (FASE 7a): pide un outline de N secciones y genera
        cada seccion con un prompt FRESCO = prompt + outline + resumen corto de lo previo.
        El prefill por seccion es acotado (no crece con el texto total), asi la longitud
        total deja de estar limitada por el ctx de 16k -> generacion cuasi-infinita; el
        unico limite real pasa a ser el tiempo de pared (~8 tok/s).

        on_outline: callback opcional on_outline(sections) invocado UNA vez, apenas se
        parsea el esquema (antes de generar ninguna seccion) -- permite persistir el
        plan completo (p.ej. el sidecar de /largo --continuar) sin esperar a que termine
        la primera seccion.
        on_section: callback opcional on_section(idx, total, titulo, tokens, texto,
        stop_reason) por cada seccion COMPLETA (texto = el texto de esa seccion,
        stop_reason = el de su generate_long interno; para escritura incremental).
        Returns {"text","outline","sections","total_tokens","rounds"}; None si falla el
        outline o la primera seccion (mismo contrato de None que generate()).
        """
        from shattering.model_constants import (
            GEN_LONG_MAX_TOKENS, GEN_HIERARCHICAL_SECTIONS, GEN_SECTION_SUMMARY_CHARS,
        )
        if target_tokens is None:
            target_tokens = GEN_LONG_MAX_TOKENS
        if n_sections is None:
            n_sections = GEN_HIERARCHICAL_SECTIONS

        outline_prompt = self._append_to_user_turn(
            prompt,
            f"Primero, devuelve SOLO un esquema de exactamente {n_sections} secciones "
            f"para responder lo anterior: una por linea, numeradas (1., 2., ...), con un "
            f"titulo corto cada una. Sin texto adicional."
        )
        outline_text = self.generate(outline_prompt,
                                     max_tokens=max(128, n_sections * 32),
                                     temperature=temperature)
        if outline_text is None:
            return None
        sections = self._parse_outline(outline_text, n_sections) or [prompt]
        if on_outline is not None:
            try:
                on_outline(sections)
            except Exception:
                pass

        outline_block = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sections))
        per_section = max(256, target_tokens // max(1, len(sections)))
        parts: list = []
        total_tokens = 0
        rounds = 0
        prev_summary = ""

        for i, sec in enumerate(sections):
            sec_prompt = self._append_to_user_turn(
                prompt,
                f"Esquema:\n{outline_block}\n\n"
                + (f"Resumen de lo ya escrito: {prev_summary}\n\n" if prev_summary else "")
                + f"Escribe SOLO la seccion {i+1}: {sec}"
            )
            res = self.generate_long(sec_prompt, max_total_tokens=per_section,
                                     temperature=temperature)
            if res is None:
                if not parts:
                    return None
                break
            parts.append(f"## {sec}\n{res['text']}")
            total_tokens += res["total_tokens"]
            rounds += res["rounds"]
            # Resumen acotado -> mantiene chico el prefill de la siguiente seccion
            prev_summary = (sec + ": " + (res["text"] or "")[:GEN_SECTION_SUMMARY_CHARS]
                            ).replace("\n", " ")
            if on_section is not None:
                try:
                    on_section(i + 1, len(sections), sec, res["total_tokens"],
                              res["text"], res["stop_reason"])
                except Exception:
                    pass

        return {
            "text":         "\n\n".join(parts),
            "outline":      sections,
            "sections":     len(parts),
            "total_tokens": total_tokens,
            "rounds":       rounds,
        }

    def generate_delegated(self, prompt: str, target_tokens: int = None,
                           n_tasks: int = None, per_task_cap: int = None,
                           aggregate: bool = True, temperature: float = 0.7,
                           on_task=None, on_outline=None) -> Optional[dict]:
        """
        Generacion larga por DELEGACION (orchestrator-workers). Descompone en un outline
        de N subtareas (spec compartido) y genera cada una con un worker de CONTEXTO LIMPIO:
        el prompt de cada worker es prompt + outline + SOLO esa subtarea, SIN arrastrar el
        resumen de las previas (a diferencia de generate_hierarchical). Cada worker corre
        hasta per_task_cap (<= GEN_LONG_MAX_TOKENS), asi el output TOTAL = suma de subtareas
        y deja de estar acotado por el ctx de 16k.

        Si aggregate y hay >1 subtarea, una CABEZA final teje: recibe el outline + un extracto
        acotado de cada draft y escribe una introduccion unificadora (y marca inconsistencias
        si las nota). El cuerpo (drafts completos) se CONSERVA -> la cabeza ENMARCA, no
        reescribe (no entraria todo en la ventana). Honesto: los workers son ciegos entre si;
        la coherencia global la aporta el outline compartido + el frame de la cabeza, no una
        reescritura global.

        on_outline: callback opcional on_outline(tasks) invocado UNA vez, apenas se parsea
        el esquema (antes de correr ningun worker) -- persistir el plan completo temprano
        (p.ej. sidecar de /largo --continuar) sin esperar la primera subtarea.
        on_task: callback opcional on_task(idx, total, titulo, tokens, texto, stop_reason)
        por cada subtarea COMPLETA (texto = el texto de esa subtarea, stop_reason = el de
        su generate_long interno; para escritura incremental).

        Returns {"text","outline","sections","total_tokens","rounds","head"}; None si falla
        el outline o la primera subtarea (mismo contrato de None que generate()).
        """
        from shattering.model_constants import (
            GEN_LONG_MAX_TOKENS, GEN_HIERARCHICAL_SECTIONS, GEN_SECTION_SUMMARY_CHARS,
        )
        if n_tasks is None:
            n_tasks = GEN_HIERARCHICAL_SECTIONS
        if target_tokens is None:
            target_tokens = GEN_LONG_MAX_TOKENS
        if per_task_cap is None:
            per_task_cap = GEN_LONG_MAX_TOKENS

        outline_prompt = self._append_to_user_turn(
            prompt,
            f"Primero, devuelve SOLO un esquema de exactamente {n_tasks} secciones "
            f"para responder lo anterior: una por linea, numeradas (1., 2., ...), con un "
            f"titulo corto cada una. Sin texto adicional."
        )
        outline_text = self.generate(outline_prompt,
                                     max_tokens=max(128, n_tasks * 32),
                                     temperature=temperature)
        if outline_text is None:
            return None
        tasks = self._parse_outline(outline_text, n_tasks) or [prompt]
        if on_outline is not None:
            try:
                on_outline(tasks)
            except Exception:
                pass

        outline_block = "\n".join(f"{i+1}. {s}" for i, s in enumerate(tasks))
        per_task = min(per_task_cap, max(256, target_tokens // max(1, len(tasks))))
        parts: list = []
        drafts: list = []
        total_tokens = 0
        rounds = 0

        for i, sec in enumerate(tasks):
            # CAMBIO 1 vs generate_hierarchical: worker de CONTEXTO LIMPIO ->
            # NO se incluye prev_summary; cada subtarea arranca con el outline puro.
            sec_prompt = self._append_to_user_turn(
                prompt,
                f"Esquema:\n{outline_block}\n\n"
                f"Escribe SOLO la seccion {i+1}: {sec}. No repitas las otras secciones."
            )
            res = self.generate_long(sec_prompt, max_total_tokens=per_task,
                                     temperature=temperature)
            if res is None:
                if not parts:
                    return None
                break
            parts.append(f"## {sec}\n{res['text']}")
            drafts.append((sec, res["text"] or ""))
            total_tokens += res["total_tokens"]
            rounds += res["rounds"]
            if on_task is not None:
                try:
                    on_task(i + 1, len(tasks), sec, res["total_tokens"],
                           res["text"], res["stop_reason"])
                except Exception:
                    pass

        body = "\n\n".join(parts)
        head = ""
        # CAMBIO 2 vs generate_hierarchical: cabeza que teje (reemplaza el join crudo).
        if aggregate and len(drafts) > 1:
            excerpts = "\n".join(
                f"{i+1}. {t}: {(txt[:GEN_SECTION_SUMMARY_CHARS * 2]).strip()}"
                for i, (t, txt) in enumerate(drafts)
            ).replace("\n\n", " ")
            # Prompt POSITIVO (sin negaciones) + repeat_penalty: las negaciones
            # ("No repitas...") inducian un loop degenerado en el 3B ("No incluye...
            # No incluye...") y max_tokens alto le daba espacio para degenerar.
            head_prompt = self._append_to_user_turn(
                prompt,
                f"Un documento tiene estas secciones (extractos):\n{excerpts}\n\n"
                f"Escribe una introduccion breve de 2 a 4 frases que presente de que trata el "
                f"documento y como se conectan sus secciones."
            )
            head = self.generate(head_prompt, max_tokens=220, temperature=temperature,
                                 repeat_penalty=1.3) or ""

        text = (head.strip() + "\n\n" + body) if head.strip() else body
        return {
            "text":         text,
            "outline":      tasks,
            "sections":     len(parts),
            "total_tokens": total_tokens,
            "rounds":       rounds,
            "head":         head.strip(),
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

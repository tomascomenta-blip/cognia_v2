"""
shattering/orchestrator.py
==========================
ShatteringOrchestrator — coordinates GlobalRouter, FragmentManager,
and the shard inference pipeline into a single infer() call.

Modes:
  local       — load fragments in-process, run ShardEngine chain on device
  distributed — delegate to the Cognia Swarm Coordinator over HTTP
  auto        — try distributed if coordinator_url is set, else local
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from shattering.manifest import AppManifest, FragmentSpec, ManifestLoader
from shattering.fragment_manager import FragmentManager
from shattering.model_constants import (
    COGNIA_SYSTEM_PROMPT, DEFAULT_RST_PASSES, LPC_MAX_SESSIONS, LPC_TTL_SECONDS,
    QWEN25_CODER_3B,
)
from shattering.router import GlobalRouter, RouteDecision
from security.ollama_url import validate_ollama_url

# Derivados de la fuente unica (regla del repo: sin constantes de modelo
# hardcodeadas fuera de model_constants).
_QWEN_EOS_SET = {QWEN25_CODER_3B["bos_token_id"], QWEN25_CODER_3B["eos_token_id"]}
_QWEN_VOCAB   = QWEN25_CODER_3B["vocab_size"]

logger = logging.getLogger(__name__)


# ── Latent Persistence Cache (Phase 20.2) ────────────────────────────────────

import threading as _threading
from dataclasses import dataclass as _dataclass

@_dataclass
class _LPCEntry:
    mla_session_id: str   # internal key used in MLA KV-cache
    token_count:    int   # tokens already cached (prompt prefix length)
    last_access:    float # monotonic time


class LatentPersistenceCache:
    """
    Maps an external session identifier (e.g. user+conversation ID) to a
    persistent MLA KV-cache session.  On each turn only the NEW tokens
    (beyond the previously cached prefix) are processed by the shard chain;
    the MLA KV-cache provides attention context for the cached prefix.

    Eviction: sessions idle for LPC_TTL_SECONDS are cleared from both this
    cache and from all loaded ShardEngine MLA caches.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, _LPCEntry] = {}
        self._lock = _threading.Lock()

    def get_or_create(self, lpc_session_id: str) -> _LPCEntry:
        """Return existing entry or create a new one."""
        with self._lock:
            entry = self._entries.get(lpc_session_id)
            if entry is None:
                entry = _LPCEntry(
                    mla_session_id = f"lpc_{lpc_session_id}",
                    token_count    = 0,
                    last_access    = time.monotonic(),
                )
                self._entries[lpc_session_id] = entry
                self._enforce_limit()
            else:
                entry.last_access = time.monotonic()
            return entry

    def update(self, lpc_session_id: str, new_token_count: int) -> None:
        with self._lock:
            entry = self._entries.get(lpc_session_id)
            if entry is not None:
                entry.token_count  = new_token_count
                entry.last_access  = time.monotonic()

    def invalidate(self, lpc_session_id: str) -> None:
        """Clear a session (e.g. when prompt is not an extension of cached prefix)."""
        with self._lock:
            self._entries.pop(lpc_session_id, None)

    def evict_stale(self, mla_evict_fn=None) -> int:
        """Evict sessions idle beyond LPC_TTL_SECONDS. Calls mla_evict_fn(mla_session_id) if set."""
        now = time.monotonic()
        with self._lock:
            stale = [
                (sid, e.mla_session_id)
                for sid, e in self._entries.items()
                if now - e.last_access > LPC_TTL_SECONDS
            ]
            for sid, mla_sid in stale:
                del self._entries[sid]
                if mla_evict_fn is not None:
                    mla_evict_fn(mla_sid)
        return len(stale)

    def _enforce_limit(self) -> None:
        """Evict oldest entry when over LPC_MAX_SESSIONS. Must be called with lock held."""
        if len(self._entries) > LPC_MAX_SESSIONS:
            oldest = min(self._entries.items(), key=lambda kv: kv[1].last_access)
            del self._entries[oldest[0]]


@dataclass
class InferResult:
    text:             str
    sub_model:        str
    confidence:       float
    latency_ms:       float
    mode:             str   # "local" | "distributed" | "simulation"
    route_reason:     str
    tokens_generated: int = 0


class ShatteringOrchestrator:
    """
    End-to-end Shattering inference coordinator.

    Usage (local, simulation):
        orch = ShatteringOrchestrator(
            manifest_path="shattering/manifests/cognia_desktop.json"
        )
        result = orch.infer("Explain recursion")
        print(result.text)

    Usage (distributed):
        orch = ShatteringOrchestrator(
            manifest_path="shattering/manifests/cognia_desktop.json",
            coordinator_url="https://cognia-coordinator.railway.app",
            mode="distributed",
        )
    """

    def __init__(
        self,
        manifest_path: Optional[str] = None,
        manifest: Optional[AppManifest] = None,
        base_dir: str = "model_shards",
        coordinator_url: Optional[str] = None,
        mode: str = "auto",           # "auto" | "local" | "distributed"
        max_new_tokens: int = 768,
        n_recursive_passes: int = DEFAULT_RST_PASSES,
        ollama_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ):
        if manifest:
            self._manifest = manifest
        elif manifest_path:
            p = Path(manifest_path)
            if p.suffix == ".json" or p.exists():
                self._manifest = ManifestLoader.load_from_file(p)
            else:
                self._manifest = ManifestLoader.load(manifest_path)
        else:
            # Default (fix 2026-07-08): el manifest de escritorio EMPAQUETADO
            # junto al modulo (package-data shattering/manifests/*.json). Sin
            # esto, todo caller sin manifest_path — el CLI llama
            # Orchestrator(mode='local') pelado en 4 lugares — moria con
            # ValueError FUERA del repo (producto instalado, cwd arbitrario) y
            # /hacer degradaba a "(el agente no pudo iniciar el modelo)".
            default = Path(__file__).parent / "manifests" / "cognia_desktop.json"
            if not default.is_file():
                raise ValueError("Provide manifest or manifest_path")
            self._manifest = ManifestLoader.load_from_file(default)

        self._router       = GlobalRouter()
        self._fragments    = FragmentManager(base_dir=base_dir)
        self._coord_url    = coordinator_url.rstrip("/") if coordinator_url else None
        self._max_tokens   = max_new_tokens
        self._n_passes     = n_recursive_passes
        _raw_ollama = (
            ollama_url
            or os.environ.get("COGNIA_OLLAMA_URL", "")
            or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        )
        self._ollama_url = validate_ollama_url(_raw_ollama).rstrip("/") + "/api/generate"
        self._ollama_model = (
            ollama_model
            or os.environ.get("COGNIA_OLLAMA_MODEL", "llama3.2")
        )

        if mode == "auto":
            # Prefer local shard inference when weights are already present;
            # only fall back to distributed when no local shards exist.
            self._mode = "local" if self._shards_available() else (
                "distributed" if self._coord_url else "local"
            )
        else:
            self._mode = mode

        # Lazy-initialized state for real shard-weight inference
        self._pipeline    = None
        self._local_route = None

        # Speculative decoding draft model (lazy-loaded on first shard inference)
        self._draft = None

        # Optional llama.cpp acceleration layer (lazy-loaded on first local infer)
        self._llama: "Optional[object]" = None
        self._llama_checked: bool = False   # avoids repeated failed attempts

        # Proactive MLA eviction -- evict every 90s to match relay SESSION_TIMEOUT=120s
        self._last_eviction: float = 0.0

        # LPC: cross-turn KV-cache persistence (Phase 20.2)
        self._lpc = LatentPersistenceCache()

    # ── Public API ──────────────────────────────────────────────────────

    def infer(self, prompt: str, lpc_session_id: Optional[str] = None,
              max_tokens: Optional[int] = None,
              temperature: Optional[float] = None,
              stop: Optional[list] = None,
              repeat_penalty: Optional[float] = None,
              grammar: Optional[str] = None) -> InferResult:
        """
        Route the prompt, load the right sub-model, and return generated text.

        lpc_session_id: when provided, the MLA KV-cache is preserved across calls
                        for this session. Only tokens beyond the cached prefix are
                        processed by the shard chain, giving O(new_tokens) cost
                        instead of O(full_prompt) on subsequent turns.
        max_tokens:     per-call generation budget; None uses the constructor
                        default (self._max_tokens). Lets a caller request a long
                        answer without rebuilding the orchestrator.
        temperature:    per-call sampling temperature; None uses the routed
                        default (self._TEMPERATURES). Solo afecta el camino local;
                        el distribuido no expone temperatura por-llamada.
        """
        if not prompt or not prompt.strip():
            return InferResult(
                text             = "",
                sub_model        = "none",
                confidence       = 0.0,
                latency_ms       = 0.0,
                mode             = "error",
                route_reason     = "empty_prompt",
                tokens_generated = 0,
            )

        # Proactive eviction: every 90s, evict caches older than 150s (SESSION_TIMEOUT+30s)
        _now = time.time()
        if _now - self._last_eviction > 90.0:
            self._evict_mla_caches(max_age_seconds=150.0)
            self._lpc.evict_stale(mla_evict_fn=self._evict_one_mla_session)
            self._last_eviction = _now
        t0 = _now
        decision = self._router.route(prompt)
        logger.info(
            "[Orchestrator] sub_model=%s conf=%.2f — %s",
            decision.sub_model, decision.confidence, decision.reason,
        )

        if self._mode == "distributed" and self._coord_url:
            text, mode_used = self._distributed_infer(prompt, decision)
            tokens_generated = 0
        else:
            text, mode_used, tokens_generated = self._local_infer(
                prompt, decision, lpc_session_id=lpc_session_id,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                repeat_penalty=repeat_penalty,
                grammar=grammar,
            )

        return InferResult(
            text             = text,
            sub_model        = decision.sub_model,
            confidence       = decision.confidence,
            latency_ms       = round((time.time() - t0) * 1000, 1),
            mode             = mode_used,
            route_reason     = decision.reason,
            tokens_generated = tokens_generated,
        )

    async def ainfer(self, prompt: str, lpc_session_id: Optional[str] = None,
                     max_tokens: Optional[int] = None,
                     temperature: Optional[float] = None) -> InferResult:
        """Async wrapper — runs infer() in the default thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.infer, prompt, lpc_session_id, max_tokens, temperature
        )

    async def astream_chat(self, messages: list, max_tokens: Optional[int] = None):
        """
        Async generator for multi-turn chat — yields (token_text, None) per token.
        Uses /v1/chat/completions on llama-server so full conversation history is sent.
        Falls back to astream(last_user_message) if llama.cpp is unavailable.

        max_tokens: per-call generation budget; None uses self._max_tokens.
        """
        import asyncio as _asyncio

        _max_toks = max_tokens if max_tokens is not None else self._max_tokens
        self._try_load_llama()
        if self._llama is not None:
            loop = _asyncio.get_running_loop()
            queue: _asyncio.Queue = _asyncio.Queue()

            def _run_chat():
                try:
                    for tok in self._llama.stream_chat(messages, max_tokens=_max_toks):
                        loop.call_soon_threadsafe(queue.put_nowait, (tok, None))
                    loop.call_soon_threadsafe(queue.put_nowait, ("__done__", None))
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, ("__error__", str(exc)))

            loop.run_in_executor(None, _run_chat)
            while True:
                item = await queue.get()
                if item[0] == "__done__":
                    yield None, None
                    return
                if item[0] == "__error__":
                    logger.warning("[Orchestrator] stream_chat error: %s; falling back", item[1])
                    break
                yield item[0], None

        # Fallback: single-turn with the last user message
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        async for tok, final in self.astream(last_user, max_tokens=max_tokens):
            yield tok, final

    async def astream(self, prompt: str, lpc_session_id: Optional[str] = None,
                      max_tokens: Optional[int] = None):
        """
        Async generator — yields (token_text, None) per token, then (None, InferResult).
        Runs the CPU-bound token loop in a thread pool so the event loop stays free.

        lpc_session_id: when provided, MLA KV-cache is preserved across streaming calls
                        for this session (same cross-turn persistence as ainfer).
        max_tokens:     per-call generation budget; None uses self._max_tokens.
        """
        import asyncio as _asyncio

        _max_toks = max_tokens if max_tokens is not None else self._max_tokens
        # Fast path: llama.cpp streaming (server-side SSE, much better quality)
        self._try_load_llama()
        if self._llama is not None:
            from node.inference_pipeline import _apply_qwen_template
            system = COGNIA_SYSTEM_PROMPT
            formatted = _apply_qwen_template(prompt, system)
            loop = _asyncio.get_running_loop()
            queue: _asyncio.Queue = _asyncio.Queue()

            def _run_llama():
                try:
                    for tok in self._llama.stream_generate(formatted, max_tokens=_max_toks):
                        loop.call_soon_threadsafe(queue.put_nowait, (tok, None))
                    loop.call_soon_threadsafe(queue.put_nowait, ("__done__", None))
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, ("__error__", str(exc)))

            loop.run_in_executor(None, _run_llama)
            while True:
                item = await queue.get()
                if item[0] == "__done__":
                    yield None, None
                    return
                if item[0] == "__error__":
                    logger.warning("[Orchestrator] llama.cpp stream error: %s; falling back", item[1])
                    self._llama = None
                    break
                yield item[0], None
            else:
                return  # llama path completed cleanly

        _decision = self._router.route(prompt)
        _temperature = self._TEMPERATURES.get(_decision.sub_model, 0.5)

        loop  = _asyncio.get_running_loop()
        queue = _asyncio.Queue()

        def _run():
            try:
                result = self._shard_infer_stream(prompt, queue, loop,
                                                  lpc_session_id=lpc_session_id,
                                                  temperature=_temperature,
                                                  max_tokens=max_tokens)
                loop.call_soon_threadsafe(queue.put_nowait, ("__done__", result))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("__error__", str(exc)))

        loop.run_in_executor(None, _run)

        while True:
            item = await queue.get()
            if item[0] == "__done__":
                yield None, item[1]   # (None, InferResult)
                break
            if item[0] == "__error__":
                raise RuntimeError(item[1])
            yield item[0], None       # (token_text, None)

    def route_only(self, prompt: str) -> RouteDecision:
        """Return routing decision without running inference."""
        return self._router.route(prompt)

    def shards_ready(self) -> bool:
        """Public probe: True when all 4 Qwen .npz shard files are present."""
        return self._shards_available()

    def preload(self, sub_model: Optional[str] = None) -> None:
        """
        Pre-load fragment shards into memory before the first request.
        If sub_model is None, load all bundled fragments in the manifest.
        """
        if sub_model:
            specs = self._manifest.fragments_for_sub_model(sub_model)
            if specs:
                logger.info("[Orchestrator] preloading %s (%d shards)", sub_model, len(specs))
                self._fragments.load_all(specs)
        else:
            sub_models = {f.sub_model for f in self._manifest.bundled}
            for sm in sub_models:
                specs = self._manifest.fragments_for_sub_model(sm)
                logger.info("[Orchestrator] preloading %s (%d shards)", sm, len(specs))
                self._fragments.load_all(specs)

    def status(self) -> dict:
        from shattering.moe_layer import MoELayer
        sub_models = {f.sub_model for f in self._manifest.all_fragments()}
        result = {
            "manifest":  self._manifest.app_id,
            "mode":      self._mode,
            "fragments": self._fragments.status(),
            "bundles": {
                sm: [s.fragment_id for s in self._manifest.fragments_for_sub_model(sm)]
                for sm in sub_models
            },
        }
        # Include MoE load balance if any loaded engine has a MoE layer attached
        loaded = self._fragments._engines
        moe_balance: Dict[str, dict] = {}
        for key, engine in loaded.items():
            layers = getattr(engine, "_layers", [])
            for layer in layers:
                mlp = getattr(layer, "mlp", None)
                inner = getattr(mlp, "_moe", None) or mlp
                if isinstance(inner, MoELayer):
                    sm = key.split("/")[0]
                    moe_balance[sm] = inner.check_balance()
                    break
        if moe_balance:
            result["moe_balance"] = moe_balance
        # Evict stale MLA KV-cache entries from any loaded engine
        self._evict_mla_caches()
        return result

    def decay_precision(self, factor: float = 0.3) -> dict:
        """
        Decay dynamic-precision caches across all loaded ShardEngines.
        Reduces access counters by factor and drops caches for matrices that fall
        below their tier threshold. Safe to call during the sleep cycle.
        Returns {engine_key: stats} for all real-mode engines.
        """
        results = {}
        for key, engine in self._fragments._engines.items():
            if hasattr(engine, "decay_precision"):
                s = engine.decay_precision(factor)
                if s:
                    results[key] = s
        return results

    def _evict_mla_caches(self, max_age_seconds: float = 3600.0) -> None:
        """Evict stale per-session KV-cache entries from all loaded ShardEngines."""
        loaded = self._fragments._engines
        for engine in loaded.values():
            kv_cache = getattr(engine, "_kv_cache", None)
            if kv_cache is not None and hasattr(kv_cache, "evict_stale"):
                kv_cache.evict_stale(max_age_seconds)

    def _evict_one_mla_session(self, mla_session_id: str) -> None:
        """Clear a specific MLA session from all loaded ShardEngines."""
        for engine in self._fragments._engines.values():
            if hasattr(engine, "clear_cache"):
                engine.clear_cache(mla_session_id)

    # ── Local inference ─────────────────────────────────────────────────

    def _try_load_llama(self) -> None:
        """Attempt to load llama.cpp backend once; sets _llama_checked to avoid retries."""
        if self._llama_checked:
            return
        self._llama_checked = True
        try:
            from node.llama_backend import LlamaBackend
            self._llama = LlamaBackend.try_load()
            if self._llama:
                logger.info("[Orchestrator] llama.cpp backend active")
        except Exception as exc:
            logger.debug("[Orchestrator] llama.cpp backend unavailable: %s", exc)

    def reload_llama(self) -> "Optional[object]":
        """Recarga el backend llama.cpp (p.ej. tras cambiar LLAMA_GGUF_PATH).

        Para el server actual si lo hay, resetea el guard _llama_checked y
        re-dispara _try_load_llama(). Devuelve el backend nuevo o None si la
        carga fallo (mismo contrato que _llama tras _try_load_llama).
        """
        if self._llama is not None:
            try:
                self._llama.stop()
            except Exception:
                pass
        self._llama = None
        self._llama_checked = False
        self._try_load_llama()
        return self._llama

    def _local_infer(self, prompt: str, decision: RouteDecision,
                     lpc_session_id: Optional[str] = None,
                     temperature: Optional[float] = None,
                     max_tokens: Optional[int] = None,
                     stop: Optional[list] = None,
                     repeat_penalty: Optional[float] = None,
                     grammar: Optional[str] = None):
        """Returns (text, mode, tokens_generated). max_tokens=None uses self._max_tokens.
        repeat_penalty!=None desalienta la degeneracion (cola repetida) que a temp=0
        el 3B genera hasta el cap; el agente lo usa en el paso ReAct (ver cli.py)."""
        if temperature is None:
            temperature = self._TEMPERATURES.get(decision.sub_model, 0.5)
        _max_toks = max_tokens if max_tokens is not None else self._max_tokens
        # Fast path: llama.cpp if GGUF model and runtime are present
        self._try_load_llama()
        if self._llama is not None:
            from node.inference_pipeline import _apply_qwen_template
            system = COGNIA_SYSTEM_PROMPT
            formatted = _apply_qwen_template(prompt, system)
            result = self._llama.generate(formatted, max_tokens=_max_toks,
                                          temperature=temperature, stop=stop,
                                          repeat_penalty=repeat_penalty,
                                          grammar=grammar)
            if result is not None:
                # Prefer the real count reported by llama-server (tokens_predicted);
                # fall back to a len//4 estimate if the backend doesn't expose it
                real = getattr(self._llama, "last_tokens_predicted", None)
                toks = real if real is not None else max(1, len(result) // 4)
                return result, "llama.cpp", toks
            # llama.cpp failed mid-session — disable and fall through to numpy
            logger.warning("[Orchestrator] llama.cpp returned None, falling back to numpy")
            self._llama = None

        # If real Qwen .npz shards are present, run the full shard pipeline
        if self._shards_available():
            text, toks = self._shard_infer(prompt, lpc_session_id=lpc_session_id,
                                           temperature=temperature, max_tokens=max_tokens)
            return text, "local", toks

        sub_model = decision.sub_model
        specs     = self._manifest.fragments_for_sub_model(sub_model)

        # Fall back to any available bundle if this sub_model isn't bundled here
        if not specs:
            all_sub_models = {f.sub_model for f in self._manifest.bundled}
            for sm in all_sub_models:
                sm_specs = self._manifest.fragments_for_sub_model(sm)
                if sm_specs:
                    logger.warning(
                        "[Orchestrator] '%s' not in bundle, using '%s'",
                        sub_model, sm,
                    )
                    sub_model = sm
                    specs     = sm_specs
                    break

        if not specs:
            return f"[Simulation] No bundle configured for '{sub_model}'.", "simulation", 0

        engines = self._fragments.load_all(specs)
        if not engines:
            return f"[Simulation] No engines loaded for '{sub_model}'.", "simulation", 0

        has_real_weights = self._any_real_weights(specs)
        if not has_real_weights:
            text = self._ollama_infer(prompt, sub_model, n_passes=self._n_passes)
            return text, "simulation", 0

        text, toks = self._shard_infer(prompt, lpc_session_id=lpc_session_id,
                                       temperature=temperature, max_tokens=max_tokens)
        return text, "local", toks

    def _shards_available(self) -> bool:
        """
        True when at least one Qwen INT4 shard is present (either .npz file or unpacked
        shard_N/ directory created by scripts/unpack_shards.py).

        In swarm mode each node hosts exactly 1 shard (the one assigned by the
        coordinator). Requiring all 4 would always return False for swarm nodes.
        The assigned shard index is stored in COGNIA_NODE_SHARD; when unset,
        any shard_*.npz or shard_N/ present is accepted.
        """
        shard_dir = Path(os.environ.get("SHARD_WEIGHTS_DIR", ""))
        if not shard_dir.is_absolute():
            shard_dir = Path(__file__).parent.parent / shard_dir
        if not shard_dir.is_dir():
            return False

        def _shard_present(idx: int) -> bool:
            npz = shard_dir / f"shard_{idx}.npz"
            if npz.is_file() and npz.stat().st_size > 0:
                return True
            # Also accept unpacked directory form (scripts/unpack_shards.py)
            npy_dir = shard_dir / f"shard_{idx}"
            try:
                return npy_dir.is_dir() and any(npy_dir.iterdir())
            except OSError:
                return False

        assigned = os.environ.get("COGNIA_NODE_SHARD")
        if assigned is not None:
            try:
                return _shard_present(int(assigned))
            except (ValueError, OSError):
                return False
        return any(_shard_present(i) for i in range(4))

    def _try_load_draft(self, shard_dir: str) -> None:
        """Attempt to load the nano-draft model; silently skip if not built yet."""
        if self._draft is not None:
            return
        from pathlib import Path as _P
        draft_path = _P(shard_dir) / "nano_draft.npz"
        if not draft_path.is_file():
            return
        try:
            from node.nano_draft import NanoDraft
            self._draft = NanoDraft(str(draft_path))
            logger.info("[Orchestrator] nano-draft loaded from %s", draft_path)
        except Exception as exc:
            logger.warning("[Orchestrator] nano-draft load failed: %s", exc)

    def _shard_infer_stream(self, prompt: str, queue, loop,
                            lpc_session_id: Optional[str] = None,
                            temperature: float = 0.5,
                            max_tokens: Optional[int] = None) -> "InferResult":
        """
        Streaming token generation with speculative decoding when nano_draft.npz is present.
        Puts (token_text, None) into queue per token; returns InferResult when done.
        """
        import time as _time
        import numpy as np
        from node.inference_pipeline import _apply_qwen_template, _LOCAL_ENGINES

        if self._pipeline is None:
            pipeline, route = self._build_local_pipeline()
            self._pipeline = pipeline
            self._local_route = route
            _sd = Path(os.environ.get("SHARD_WEIGHTS_DIR", ""))
            if not _sd.is_absolute():
                _sd = Path(__file__).parent.parent / _sd
            self._try_load_draft(str(_sd))

        pipeline   = self._pipeline
        route      = self._local_route
        t0         = _time.perf_counter()
        is_qwen    = "qwen" in pipeline.model_name.lower()
        _QWEN_EOS  = _QWEN_EOS_SET
        system     = COGNIA_SYSTEM_PROMPT
        formatted  = _apply_qwen_template(prompt, system) if is_qwen else prompt
        vocab_size = _QWEN_VOCAB if is_qwen else 32000
        _N_DRAFT   = 6

        all_ids = np.array(pipeline._encode(formatted), dtype=np.int32)

        # LPC: reuse cross-turn KV-cache when lpc_session_id is provided
        lpc_entry = None
        if lpc_session_id is not None:
            lpc_entry  = self._lpc.get_or_create(lpc_session_id)
            session_id = lpc_entry.mla_session_id
            cached_n   = lpc_entry.token_count
            if cached_n > 0 and cached_n < len(all_ids):
                current_ids = all_ids[cached_n:]
                logger.info("[LPC/stream] session=%s: skipping %d cached tokens, processing %d new",
                            lpc_session_id, cached_n, len(current_ids))
            elif cached_n >= len(all_ids):
                self._evict_one_mla_session(lpc_entry.mla_session_id)
                self._lpc.invalidate(lpc_session_id)
                lpc_entry  = self._lpc.get_or_create(lpc_session_id)
                session_id = lpc_entry.mla_session_id
                current_ids = all_ids
            else:
                current_ids = all_ids
        else:
            session_id  = "intra_" + uuid.uuid4().hex[:8]
            current_ids = all_ids

        prompt_ids = current_ids.copy()
        hidden_dim       = pipeline._get_model_config().get("hidden_dim", 2048)
        eos_set          = _QWEN_EOS if is_qwen else {2}
        generated_ids    = []
        tokens_generated = 0
        t_loop           = _time.perf_counter()
        prev_output      = None   # output from previous forward pass (for spec d_0 verify)
        _prev_text_len   = 0      # cumulative decode length for streaming diff
        _budget          = max_tokens if max_tokens is not None else self._max_tokens

        for _ in range(_budget):
            # ── Speculative path ──────────────────────────────────────────
            if self._draft is not None and prev_output is not None:
                gen_arr = np.array(generated_ids, dtype=np.int32)
                ctx_for_draft = np.concatenate([prompt_ids[-32:], gen_arr]) \
                    if len(gen_arr) else prompt_ids[-64:]

                candidates = self._draft.draft(ctx_for_draft, n=_N_DRAFT)

                # Verify d_0 against previous step's output
                prev_flat    = prev_output[-1].flatten() if prev_output.ndim == 2 else prev_output.flatten()
                d0_expected  = int(np.argmax(prev_flat[:vocab_size]))

                if d0_expected != candidates[0]:
                    # Draft missed d_0 — fall through to normal single-token step
                    pass
                else:
                    # d_0 correct — run batch verification for d_1..d_{N-1}
                    kv_before = max((eng.kv_len(session_id) for eng in _LOCAL_ENGINES
                                     if hasattr(eng, "kv_len")), default=0)
                    batch_ids = np.array(candidates, dtype=np.int32)
                    out_batch, ok = pipeline._forward_through_swarm(
                        batch_ids, session_id, route, hidden_dim
                    )

                    if ok and out_batch.ndim == 2 and out_batch.shape[0] == _N_DRAFT:
                        accepted = [candidates[0]]
                        for i in range(1, _N_DRAFT):
                            pred = int(np.argmax(out_batch[i - 1].flatten()[:vocab_size]))
                            if pred == candidates[i]:
                                accepted.append(candidates[i])
                            else:
                                accepted.append(pred)
                                break

                        # Bonus token when all N accepted
                        if len(accepted) == _N_DRAFT:
                            bonus = int(np.argmax(out_batch[-1].flatten()[:vocab_size]))
                            if bonus not in eos_set:
                                accepted.append(bonus)

                        k = len(accepted)
                        # Truncate KV-cache to accepted length
                        for eng in _LOCAL_ENGINES:
                            if hasattr(eng, "truncate_kv"):
                                eng.truncate_kv(session_id, kv_before + k)

                        prev_output = out_batch[k - 1] if k <= _N_DRAFT else out_batch[-1]
                        tokens_generated += k
                        done = False
                        for tok_id in accepted:
                            if tok_id in eos_set:
                                done = True
                                break
                            generated_ids.append(tok_id)
                        # Decode cumulatively; emit only the new suffix
                        _full = pipeline._decode(generated_ids)
                        _new  = _full[_prev_text_len:]
                        _prev_text_len = len(_full)
                        if _new:
                            loop.call_soon_threadsafe(queue.put_nowait, (_new, None))
                        current_ids = np.array([accepted[-1]], dtype=np.int32)

                        if tokens_generated % 10 == 0:
                            elapsed = _time.perf_counter() - t_loop
                            rate    = tokens_generated / elapsed if elapsed > 0 else 0
                            logger.info("[SpecLoop] %d tokens, %.2f tok/s (accepted %d/%d drafts)",
                                        tokens_generated, rate, k, _N_DRAFT)
                        if done:
                            break
                        continue   # skip normal path below

            # ── Normal single-token path ──────────────────────────────────
            output, success = pipeline._forward_through_swarm(
                current_ids, session_id, route, hidden_dim
            )
            if not success:
                break
            next_id     = pipeline._sample(output, temperature=temperature)
            prev_output = output
            tokens_generated += 1

            if tokens_generated % 10 == 0:
                elapsed = _time.perf_counter() - t_loop
                rate    = tokens_generated / elapsed if elapsed > 0 else 0
                logger.info("[TokenLoop] %d tokens, %.2f tok/s", tokens_generated, rate)

            if next_id in eos_set:
                break
            generated_ids.append(next_id)
            # Decode cumulatively; emit only the new suffix so byte-level BPE
            # tokens that form partial UTF-8 sequences are never sent as empty strings.
            _full = pipeline._decode(generated_ids)
            _new  = _full[_prev_text_len:]
            _prev_text_len = len(_full)
            if _new:
                loop.call_soon_threadsafe(queue.put_nowait, (_new, None))
            current_ids = np.array([next_id], dtype=np.int32)

        text = pipeline._decode(generated_ids)

        # Update LPC so the next streaming call can skip the cached prefix
        if lpc_entry is not None and lpc_session_id is not None:
            self._lpc.update(lpc_session_id, len(all_ids) + tokens_generated)
        else:
            # Intra-turn session — evict immediately so MLA cache doesn't leak
            self._evict_one_mla_session(session_id)

        return InferResult(
            text             = text,
            sub_model        = "logos",
            confidence       = 0.0,
            latency_ms       = round((_time.perf_counter() - t0) * 1000, 1),
            mode             = "local",
            route_reason     = "shard_stream",
            tokens_generated = tokens_generated,
        )

    def _shard_infer(self, prompt: str, lpc_session_id: Optional[str] = None,
                     temperature: float = 0.5,
                     max_tokens: Optional[int] = None) -> tuple:
        """
        Run end-to-end inference via the real Qwen INT4 forward pass.

        Loads all 4 ShardEngines lazily on first call, registers them as
        local engines in inference_pipeline, then runs a local generate cycle
        that bypasses the coordinator HTTP calls entirely.

        Returns (text: str, tokens_generated: int).
        """
        if self._pipeline is None:
            pipeline, route = self._build_local_pipeline()
            self._pipeline = pipeline
            self._local_route = route
            _sd = Path(os.environ.get("SHARD_WEIGHTS_DIR", ""))
            if not _sd.is_absolute():
                _sd = Path(__file__).parent.parent / _sd
            self._try_load_draft(str(_sd))

        result = self._generate_local(
            prompt, self._pipeline, self._local_route,
            lpc_session_id=lpc_session_id, temperature=temperature,
            max_tokens=max_tokens,
        )
        if result.get("ok") and result.get("text"):
            return result["text"], result.get("tokens_generated", 0)

        error = result.get("error", "shard inference failed")
        logger.warning("[Orchestrator] shard inference returned error: %s", error)
        shard_dir = os.environ.get("SHARD_WEIGHTS_DIR", "")
        raise RuntimeError(
            f"Shard inference failed: {error}. "
            f"Shard dir: {shard_dir}. "
            f"If shards are corrupt, re-run the setup wizard to re-download them."
        )

    def _generate_local(self, prompt: str, pipeline, route: list,
                        lpc_session_id: Optional[str] = None,
                        temperature: float = 0.5,
                        max_tokens: Optional[int] = None) -> dict:
        """
        Drive the token-by-token generation loop locally, without any HTTP call.
        Delegates each forward pass to registered local ShardEngines.

        When lpc_session_id is provided, the MLA KV-cache for the cached prefix
        is reused from the previous turn and only NEW tokens are processed.
        """
        import time as _time
        import numpy as np
        from node.inference_pipeline import _apply_qwen_template

        t0        = _time.perf_counter()
        is_qwen   = "qwen" in pipeline.model_name.lower()
        _QWEN_EOS = _QWEN_EOS_SET
        system    = COGNIA_SYSTEM_PROMPT
        formatted = _apply_qwen_template(prompt, system) if is_qwen else prompt
        eos_set   = _QWEN_EOS if is_qwen else {2}
        hidden_dim = pipeline._get_model_config().get("hidden_dim", 2048)

        all_ids = np.array(pipeline._encode(formatted), dtype=np.int32)

        # ── LPC: decide session_id and which tokens to process ────────────
        if lpc_session_id is not None:
            lpc_entry  = self._lpc.get_or_create(lpc_session_id)
            session_id = lpc_entry.mla_session_id
            cached_n   = lpc_entry.token_count

            if cached_n > 0 and cached_n < len(all_ids):
                # Skip the cached prefix — only feed new tokens to the shard chain
                current_ids = all_ids[cached_n:]
                logger.info(
                    "[LPC] session=%s: skipping %d cached tokens, processing %d new",
                    lpc_session_id, cached_n, len(current_ids),
                )
            elif cached_n >= len(all_ids):
                # Prompt shrank (e.g. new conversation topic) — reset LPC entry
                logger.info("[LPC] session=%s: prompt shorter than cache, resetting", lpc_session_id)
                self._evict_one_mla_session(session_id)
                self._lpc.invalidate(lpc_session_id)
                lpc_entry  = self._lpc.get_or_create(lpc_session_id)
                session_id = lpc_entry.mla_session_id
                current_ids = all_ids
            else:
                current_ids = all_ids
        else:
            session_id  = "intra_" + uuid.uuid4().hex[:8]
            current_ids = all_ids
            lpc_entry   = None

        generated_ids, tokens_generated = self._token_loop(
            pipeline, route, session_id, current_ids, hidden_dim, eos_set,
            temperature=temperature, max_tokens=max_tokens,
        )

        # ── LPC: update cached token count ───────────────────────────────
        if lpc_entry is not None:
            self._lpc.update(lpc_session_id, len(all_ids) + tokens_generated)
        else:
            # Intra-turn session — evict immediately so MLA cache doesn't leak
            self._evict_one_mla_session(session_id)

        text = pipeline._decode(generated_ids)
        return {
            "ok":               True,
            "text":             text,
            "tokens_generated": tokens_generated,
            "latency_ms":       round((_time.perf_counter() - t0) * 1000, 1),
        }

    def _token_loop(self, pipeline, route: list, session_id: str,
                    current_ids, hidden_dim: int, eos_set: set,
                    temperature: float = 0.5,
                    max_tokens: Optional[int] = None):
        """Inner token generation loop with optional speculative decoding."""
        import numpy as np
        import time as _time
        from node.inference_pipeline import _LOCAL_ENGINES

        vocab_size       = _QWEN_VOCAB
        _N_DRAFT         = 6
        prompt_ids_local = current_ids.copy()  # save full prompt for draft context
        generated_ids    = []
        tokens_generated = 0
        t0               = _time.perf_counter()
        prev_output      = None
        _budget          = max_tokens if max_tokens is not None else self._max_tokens

        for _ in range(_budget):
            # Speculative path
            if self._draft is not None and prev_output is not None:
                gen_arr = np.array(generated_ids, dtype=np.int32)
                ctx = np.concatenate([prompt_ids_local[-32:], gen_arr]) \
                    if len(gen_arr) else prompt_ids_local[-64:]
                candidates  = self._draft.draft(ctx, n=_N_DRAFT)
                prev_flat   = prev_output[-1].flatten() if prev_output.ndim == 2 else prev_output.flatten()
                d0_expected = int(np.argmax(prev_flat[:vocab_size]))

                if d0_expected == candidates[0]:
                    kv_before = max((e.kv_len(session_id) for e in _LOCAL_ENGINES
                                     if hasattr(e, "kv_len")), default=0)
                    out_batch, ok = pipeline._forward_through_swarm(
                        np.array(candidates, dtype=np.int32), session_id, route, hidden_dim
                    )
                    if ok and out_batch.ndim == 2 and out_batch.shape[0] == _N_DRAFT:
                        accepted = [candidates[0]]
                        for i in range(1, _N_DRAFT):
                            pred = int(np.argmax(out_batch[i - 1].flatten()[:vocab_size]))
                            if pred == candidates[i]:
                                accepted.append(candidates[i])
                            else:
                                accepted.append(pred)
                                break
                        if len(accepted) == _N_DRAFT:
                            bonus = int(np.argmax(out_batch[-1].flatten()[:vocab_size]))
                            if bonus not in eos_set:
                                accepted.append(bonus)
                        k = len(accepted)
                        for eng in _LOCAL_ENGINES:
                            if hasattr(eng, "truncate_kv"):
                                eng.truncate_kv(session_id, kv_before + k)
                        prev_output      = out_batch[k - 1] if k <= _N_DRAFT else out_batch[-1]
                        tokens_generated += k
                        done = False
                        for tok_id in accepted:
                            if tok_id in eos_set:
                                done = True
                                break
                            generated_ids.append(tok_id)
                        current_ids = np.array([accepted[-1]], dtype=np.int32)
                        if tokens_generated % 10 == 0:
                            elapsed = _time.perf_counter() - t0
                            rate    = tokens_generated / elapsed if elapsed > 0 else 0
                            logger.info("[SpecLoop] %d tokens, %.2f tok/s (k=%d)", tokens_generated, rate, k)
                        if done:
                            break
                        continue

            # Normal single-token step
            output, success = pipeline._forward_through_swarm(
                current_ids, session_id, route, hidden_dim
            )
            if not success:
                break
            next_id     = pipeline._sample(output, temperature=temperature)
            prev_output = output
            tokens_generated += 1

            if tokens_generated % 10 == 0:
                elapsed = _time.perf_counter() - t0
                rate    = tokens_generated / elapsed if elapsed > 0 else 0
                logger.info("[TokenLoop] %d tokens, %.2f tok/s", tokens_generated, rate)

            if next_id in eos_set:
                break
            generated_ids.append(next_id)
            current_ids = np.array([next_id], dtype=np.int32)

        return generated_ids, tokens_generated

    def _build_local_pipeline(self):
        """
        Load available shard engines (1 in swarm mode, 4 in standalone mode),
        register them as local, and return (DistributedInferencePipeline, local_route).
        """
        from node.inference_pipeline import (
            DistributedInferencePipeline, register_local_engines,
        )
        from shattering.model_constants import QWEN25_CODER_3B

        _shard_dir_raw = Path(os.environ.get("SHARD_WEIGHTS_DIR", ""))
        if not _shard_dir_raw.is_absolute():
            _shard_dir_raw = Path(__file__).parent.parent / _shard_dir_raw
        shard_dir  = str(_shard_dir_raw)
        model_name = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")

        # Determine which shards are present locally
        assigned = os.environ.get("COGNIA_NODE_SHARD")
        if assigned is not None:
            try:
                shard_indices = [int(assigned)]
            except ValueError:
                shard_indices = list(range(QWEN25_CODER_3B["n_shards"]))
        else:
            shard_indices = [
                i for i in range(QWEN25_CODER_3B["n_shards"])
                if (Path(shard_dir) / f"shard_{i}.npz").is_file()
            ]

        engines = self._load_shard_engines(shard_dir, model_name, QWEN25_CODER_3B, shard_indices)
        register_local_engines(engines)

        pipeline    = DistributedInferencePipeline(coordinator_url="", model_name=model_name)
        local_route = [{"shard": idx, "node": "local"} for idx in shard_indices]
        logger.info("[Orchestrator] local pipeline ready (%d shards: %s)", len(shard_indices), shard_indices)
        return pipeline, local_route

    def _load_shard_engines(self, shard_dir: str, model_name: str, cfg: dict,
                             shard_indices: Optional[List[int]] = None) -> list:
        """Load the specified shard .npz files into ShardEngines, raising if any fails."""
        from node.shard_engine import ShardEngine, ShardConfig

        if shard_indices is None:
            shard_indices = list(range(cfg["n_shards"]))

        engines = []
        for i in shard_indices:
            shard_cfg = ShardConfig(
                model_name=model_name, shard_index=i,
                n_shards=cfg["n_shards"], total_layers=cfg["total_layers"],
                hidden_dim=cfg["hidden_dim"], intermediate_dim=cfg["intermediate_dim"],
                n_heads=cfg["n_heads"], n_kv_heads=cfg["n_kv_heads"],
                head_dim=cfg["head_dim"], rope_theta=cfg["rope_theta"],
                rms_norm_eps=cfg["rms_norm_eps"], vocab_size=cfg["vocab_size"],
                eos_token_id=cfg["eos_token_id"],
            )
            engine = ShardEngine(shard_cfg, weights_path=shard_dir)
            if engine.mode != "real":
                raise RuntimeError(
                    f"shard_{i}.npz could not be loaded in real mode from {shard_dir}. "
                    f"The file may be corrupt or incomplete. Re-run the setup wizard."
                )
            engines.append(engine)
            logger.info("[Orchestrator] loaded shard %d from %s", i, shard_dir)
        return engines

    def _any_real_weights(self, specs: List[FragmentSpec]) -> bool:
        import os
        for spec in specs:
            frag_dir = self._fragments.fragment_dir(spec)
            for name in ("shard.safetensors", "layers.safetensors"):
                if (frag_dir / name).exists() and os.path.getsize(frag_dir / name) > 0:
                    return True
        return False

    def _warmup_shard_engines(self, engines: list) -> None:
        # Diagnostic/warmup only — does not generate text. Real inference uses _shard_infer().
        try:
            import numpy as np
            from shattering.model_constants import QWEN25_CODER_3B
            hidden_dim = QWEN25_CODER_3B["hidden_dim"]
            hidden     = np.zeros((1, hidden_dim), dtype=np.float16)
            for engine in engines:
                out = engine.forward(hidden)
                if isinstance(out, tuple):
                    hidden = out[0]
                elif isinstance(out, dict):
                    hidden = out.get("hidden_state", hidden)
                elif hasattr(out, "shape"):
                    hidden = out
        except Exception as exc:
            logger.warning("[Orchestrator] warmup error: %s", exc)

    # ── Text generation backend ─────────────────────────────────────────

    _SYSTEM_PROMPTS: Dict[str, str] = {
        "logos": (
            "You are a rigorous analytical assistant. "
            "Reason carefully and accurately. Think step by step."
        ),
        "techne": (
            "You are a technical expert specializing in programming, engineering, "
            "and applied science. Provide precise, working solutions."
        ),
        "rhetor": (
            "You are a skilled writer and communicator. "
            "Prioritize clarity, flow, and appropriate tone for the context."
        ),
    }

    _TEMPERATURES: Dict[str, float] = {
        "logos":  0.3,
        "techne": 0.15,
        "rhetor": 0.7,
    }

    def _ollama_infer(self, prompt: str, sub_model: str, n_passes: int = 1) -> str:
        """
        Generate text via Ollama, parameterized by the routed sub-model domain.

        When n_passes >= 2 (RST quality mode): generates an initial response then
        self-refines it, simulating the iterative depth benefit of RST.
        """
        text = self._call_ollama_domain(prompt, sub_model)
        if not text:
            return self._unavailable_response(sub_model)

        if n_passes >= 2:
            refine_prompt = (
                f"Revise and improve the following response to be more precise "
                f"and complete. Return only the improved version.\n\n"
                f"Question: {prompt}\n\n"
                f"Previous response: {text}\n\n"
                f"Improved response:"
            )
            refined = self._call_ollama_domain(refine_prompt, sub_model)
            if refined:
                text = refined

        return text

    def _call_ollama_domain(self, prompt: str, sub_model: str) -> str:
        system = self._SYSTEM_PROMPTS.get(sub_model, "You are a helpful assistant.")
        temp   = self._TEMPERATURES.get(sub_model, 0.5)
        full   = f"{system}\n\n{prompt}"
        return self._call_ollama(full, temp)

    def _call_ollama(self, prompt: str, temperature: float) -> str:
        payload = json.dumps({
            "model":   self._ollama_model,
            "prompt":  prompt,
            "stream":  False,
            "options": {
                "temperature": temperature,
                "num_predict": self._max_tokens,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            self._ollama_url,
            data    = payload,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            return data.get("response", "").strip()
        except Exception as exc:
            logger.debug("[Orchestrator] Ollama call failed (%s): %s",
                         self._ollama_url, exc)
            return ""

    def _unavailable_response(self, sub_model: str) -> str:
        if self._shards_available():
            return f"[{sub_model.upper()}] Shard inference failed. Check logs for details."
        return (
            f"[{sub_model.upper()}] No inference backend available. "
            f"Instala el modelo local con: cognia install-model  "
            f"(o arranca Ollama: ollama serve && ollama pull "
            f"{self._ollama_model})"
        )

    # ── Distributed inference ───────────────────────────────────────────

    def _distributed_infer(self, prompt: str, decision: RouteDecision):
        """
        Full distributed token generation via DistributedInferencePipeline.

        Uses the pipeline's built-in token loop which:
          1. Gets route from coordinator (GET /api/swarm/route)
          2. Creates a relay session (POST /api/session/create)
          3. Runs an autoregressive loop: encodes token IDs as PTYPE_TOKENS,
             POSTs through the relay, receives PTYPE_LOGITS from the last shard,
             samples the next token, repeats
          4. Decodes and returns text

        Falls back to local inference if the coordinator or swarm is unavailable.
        """
        from node.inference_pipeline import DistributedInferencePipeline

        model_name = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")
        pipeline   = DistributedInferencePipeline(
            coordinator_url=self._coord_url,
            model_name=model_name,
        )

        if not pipeline.is_available():
            logger.warning("[Orchestrator] coordinator swarm not ready -- falling back to local")
            # _local_infer returns a 3-tuple (text, mode, tokens); this method's
            # contract is a 2-tuple (text, mode), so drop the token count.
            text, mode, _ = self._local_infer(prompt, decision)
            return text, mode

        sub_model   = decision.sub_model
        system      = self._SYSTEM_PROMPTS.get(sub_model, "You are a helpful assistant.")
        temperature = self._TEMPERATURES.get(sub_model, 0.5)

        result = pipeline.generate(
            prompt=prompt,
            max_tokens=self._max_tokens,
            temperature=temperature,
            system=system,
        )

        if result.get("ok") and result.get("text"):
            return result["text"], "distributed"

        logger.warning(
            "[Orchestrator] distributed generate failed (%s) -- falling back to local",
            result.get("error", "unknown"),
        )
        text, mode, _ = self._local_infer(prompt, decision)
        return text, mode

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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from shattering.manifest import AppManifest, FragmentSpec, ManifestLoader
from shattering.fragment_manager import FragmentManager
from shattering.model_constants import DEFAULT_RST_PASSES
from shattering.router import GlobalRouter, RouteDecision
from security.ollama_url import validate_ollama_url

logger = logging.getLogger(__name__)


@dataclass
class InferResult:
    text:         str
    sub_model:    str
    confidence:   float
    latency_ms:   float
    mode:         str   # "local" | "distributed" | "simulation"
    route_reason: str


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
        max_new_tokens: int = 256,
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
            raise ValueError("Provide manifest or manifest_path")

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

        # Proactive MLA eviction -- evict every 90s to match relay SESSION_TIMEOUT=120s
        self._last_eviction: float = 0.0

    # ── Public API ──────────────────────────────────────────────────────

    def infer(self, prompt: str) -> InferResult:
        """Route the prompt, load the right sub-model, and return generated text."""
        # Proactive eviction: every 90s, evict caches older than 150s (SESSION_TIMEOUT+30s)
        _now = time.time()
        if _now - self._last_eviction > 90.0:
            self._evict_mla_caches(max_age_seconds=150.0)
            self._last_eviction = _now
        t0 = _now
        decision = self._router.route(prompt)
        logger.info(
            "[Orchestrator] sub_model=%s conf=%.2f — %s",
            decision.sub_model, decision.confidence, decision.reason,
        )

        if self._mode == "distributed" and self._coord_url:
            text, mode_used = self._distributed_infer(prompt, decision)
        else:
            text, mode_used = self._local_infer(prompt, decision)

        return InferResult(
            text         = text,
            sub_model    = decision.sub_model,
            confidence   = decision.confidence,
            latency_ms   = round((time.time() - t0) * 1000, 1),
            mode         = mode_used,
            route_reason = decision.reason,
        )

    async def ainfer(self, prompt: str) -> InferResult:
        """Async wrapper — runs infer() in the default thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.infer, prompt)

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

    # ── Local inference ─────────────────────────────────────────────────

    def _local_infer(self, prompt: str, decision: RouteDecision):
        # If real Qwen .npz shards are present, run the full shard pipeline
        if self._shards_available():
            text = self._shard_infer(prompt)
            return text, "local"

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
            return f"[Simulation] No bundle configured for '{sub_model}'.", "simulation"

        engines = self._fragments.load_all(specs)
        if not engines:
            return f"[Simulation] No engines loaded for '{sub_model}'.", "simulation"

        has_real_weights = self._any_real_weights(specs)
        if not has_real_weights:
            text = self._ollama_infer(prompt, sub_model, n_passes=self._n_passes)
            return text, "simulation"

        text = self._shard_infer(prompt)
        return text, "local"

    def _shards_available(self) -> bool:
        """
        True when at least one Qwen INT4 .npz shard file exists and is non-empty.

        In swarm mode each node hosts exactly 1 shard (the one assigned by the
        coordinator). Requiring all 4 would always return False for swarm nodes.
        The assigned shard index is stored in COGNIA_NODE_SHARD; when unset,
        any shard_*.npz present is accepted.
        """
        shard_dir = Path(os.environ.get("SHARD_WEIGHTS_DIR", ""))
        if not shard_dir.is_dir():
            return False
        assigned = os.environ.get("COGNIA_NODE_SHARD")
        if assigned is not None:
            try:
                shard_file = shard_dir / f"shard_{int(assigned)}.npz"
                return shard_file.is_file() and shard_file.stat().st_size > 0
            except (ValueError, OSError):
                return False
        # No assignment — accept any present shard
        return any(
            (shard_dir / f"shard_{i}.npz").is_file()
            and (shard_dir / f"shard_{i}.npz").stat().st_size > 0
            for i in range(4)
        )

    def _shard_infer(self, prompt: str) -> str:
        """
        Run end-to-end inference via the real Qwen INT4 forward pass.

        Loads all 4 ShardEngines lazily on first call, registers them as
        local engines in inference_pipeline, then runs a local generate cycle
        that bypasses the coordinator HTTP calls entirely.
        Imported lazily to avoid circular imports.
        """
        if self._pipeline is None:
            pipeline, route = self._build_local_pipeline()
            self._pipeline = pipeline
            self._local_route = route

        result = self._generate_local(prompt, self._pipeline, self._local_route)
        if result.get("ok") and result.get("text"):
            return result["text"]

        error = result.get("error", "shard inference failed")
        logger.warning("[Orchestrator] shard inference returned error: %s", error)
        shard_dir = os.environ.get("SHARD_WEIGHTS_DIR", "")
        raise RuntimeError(
            f"Shard inference failed: {error}. "
            f"Shard dir: {shard_dir}. "
            f"If shards are corrupt, re-run the setup wizard to re-download them."
        )

    def _generate_local(self, prompt: str, pipeline, route: list) -> dict:
        """
        Drive the token-by-token generation loop locally, without any HTTP call.
        Delegates each forward pass to registered local ShardEngines.
        """
        import time as _time
        import numpy as np
        from node.inference_pipeline import _apply_qwen_template

        t0         = _time.perf_counter()
        is_qwen    = "qwen" in pipeline.model_name.lower()
        _QWEN_EOS  = {151643, 151645}
        system     = "Eres Cognia, un sistema de IA con memoria episodica y grafo de conocimiento."
        formatted  = _apply_qwen_template(prompt, system) if is_qwen else prompt
        session_id = "local"   # not used over the network

        current_ids = np.array(pipeline._encode(formatted), dtype=np.int32)
        hidden_dim  = pipeline._get_model_config().get("hidden_dim", 2048)
        eos_set     = _QWEN_EOS if is_qwen else {2}

        generated_ids, tokens_generated = self._token_loop(
            pipeline, route, session_id, current_ids, hidden_dim, eos_set
        )

        text = pipeline._decode(generated_ids)
        return {
            "ok":               True,
            "text":             text,
            "tokens_generated": tokens_generated,
            "latency_ms":       round((_time.perf_counter() - t0) * 1000, 1),
        }

    def _token_loop(self, pipeline, route: list, session_id: str,
                    current_ids, hidden_dim: int, eos_set: set):
        """Inner token generation loop. Returns (generated_ids, token_count)."""
        import numpy as np

        generated_ids    = []
        tokens_generated = 0

        for _ in range(self._max_tokens):
            output, success = pipeline._forward_through_swarm(
                current_ids, session_id, route, hidden_dim
            )
            if not success:
                break
            next_id = pipeline._sample(output, temperature=0.7)
            tokens_generated += 1
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

        shard_dir  = os.environ.get("SHARD_WEIGHTS_DIR", "")
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
            f"Run the setup wizard to download model shards, or start Ollama: "
            f"ollama serve && ollama pull {self._ollama_model}"
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
            return self._local_infer(prompt, decision)

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
        return self._local_infer(prompt, decision)

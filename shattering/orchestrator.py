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
            self._mode = "distributed" if self._coord_url else "local"
        else:
            self._mode = mode

    # ── Public API ──────────────────────────────────────────────────────

    def infer(self, prompt: str) -> InferResult:
        """Route the prompt, load the right sub-model, and return generated text."""
        t0 = time.time()
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

        text = self._run_shard_chain(prompt, engines, sub_model, self._n_passes)
        return text, "local"

    def _any_real_weights(self, specs: List[FragmentSpec]) -> bool:
        import os
        for spec in specs:
            frag_dir = self._fragments.fragment_dir(spec)
            for name in ("shard.safetensors", "layers.safetensors"):
                if (frag_dir / name).exists() and os.path.getsize(frag_dir / name) > 0:
                    return True
        return False

    def _run_shard_chain(self, prompt: str, engines: list, sub_model: str,
                          n_passes: int = 1) -> str:
        """
        Run real-weights shard chain, then generate text with Ollama.
        The shard chain exercises NPQ/RST/MLA/MoE routing; Ollama produces text.
        """
        try:
            import numpy as np
            from shattering.recursive_context import RecursiveContext

            ids        = list(prompt.encode("utf-8"))[:512]
            hidden_dim = 3072
            hidden     = np.zeros((len(ids), hidden_dim), dtype=np.float16)

            if n_passes <= 1:
                for engine in engines:
                    out = engine.forward(hidden)
                    if isinstance(out, tuple):
                        hidden = out[0]
                    elif isinstance(out, dict):
                        hidden = out.get("hidden_state", hidden)
                    elif hasattr(out, "shape"):
                        hidden = out
            else:
                ctx = RecursiveContext(hidden_dim=hidden_dim)
                ctx.reset()
                for _ in range(n_passes):
                    h = ctx.inject(hidden.astype(np.float32)).astype(np.float16)
                    for engine in engines:
                        out = engine.forward(h)
                        if isinstance(out, tuple):
                            h = out[0]
                        elif isinstance(out, dict):
                            h = out.get("hidden_state", h)
                        elif hasattr(out, "shape"):
                            h = out
                    ctx.update(h.astype(np.float32))
                    hidden = h

        except Exception as exc:
            logger.warning("[Orchestrator] shard chain computation error: %s", exc)

        # Shard chain computed routing and feature representations.
        # Generate actual text response via Ollama.
        return self._ollama_infer(prompt, sub_model, n_passes=n_passes)

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
        return (
            f"[{sub_model.upper()}] Ollama is not running or model "
            f"'{self._ollama_model}' is not pulled. "
            f"Run: ollama serve && ollama pull {self._ollama_model}"
        )

    # ── Distributed inference ───────────────────────────────────────────

    def _distributed_infer(self, prompt: str, decision: RouteDecision):
        """
        Create a coordinator session for the routed sub-model and infer over HTTP.
        Falls back to local if the coordinator is unreachable.
        """
        import urllib.request
        import urllib.error
        import numpy as np

        sub_model  = decision.sub_model
        model_name = f"{sub_model}-3.2-3b-q4"

        try:
            # 1. Create session
            payload = json.dumps({"model_name": model_name}).encode()
            req = urllib.request.Request(
                f"{self._coord_url}/api/session/create",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                session_data = json.loads(r.read())
            session_id = session_data["session_id"]

            # 2. Encode prompt as stub FP16 hidden state
            ids    = list(prompt.encode("utf-8"))[:128]
            hs_b64 = base64.b64encode(
                np.array(ids, dtype=np.float16).tobytes()
            ).decode()

            # 3. POST to infer
            payload = json.dumps({"hidden_state_b64": hs_b64}).encode()
            req = urllib.request.Request(
                f"{self._coord_url}/api/session/{session_id}/infer",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=70) as r:
                infer_data = json.loads(r.read())

            latency = infer_data.get("latency_ms", "?")
            return (
                f"[{sub_model.upper()} distributed — {latency}ms]",
                "distributed",
            )

        except (urllib.error.URLError, OSError) as exc:
            logger.warning(
                "[Orchestrator] coordinator unreachable (%s) — falling back to local", exc
            )
            return self._local_infer(prompt, decision)
        except Exception as exc:
            logger.warning("[Orchestrator] distributed infer error: %s", exc)
            return self._local_infer(prompt, decision)

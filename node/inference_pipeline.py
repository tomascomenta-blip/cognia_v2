"""
node/inference_pipeline.py
==========================
Pipeline de inferencia distribuida completo para Cognia.

Orquesta el ciclo token-a-token a través del swarm:
  1. Tokenizar prompt
  2. Pedir ruta al coordinador
  3. Crear sesión de relay
  4. Para cada token: enviar hidden state → recibir logits → samplear
  5. Decodificar y retornar texto

Modos:
  SWARM_REAL   — modelo real descargado, tokenizer HuggingFace
  SWARM_SIM    — simulación (pesos calibrados, tokenizer simple)
  UNAVAILABLE  — swarm no listo, el caller hace fallback a Ollama
"""

import asyncio
import base64
import logging
import os
import json
import time
import struct
import numpy as np
import urllib.request
import urllib.error
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


# COGNIA_DISABLE_SWARM: hard-off de la orquestacion online (version comercial
# local-only). Si esta seteado, la URL del coordinador se fuerza a "" AUNQUE las
# env vars de coordinador esten definidas -> ningun camino de generacion se rutea
# al swarm; todo corre con el modelo local. Inline (sin importar cognia) para no
# crear dependencia circular node<->cognia en el import de este modulo.
_SWARM_DISABLED = os.environ.get("COGNIA_DISABLE_SWARM", "").strip().lower() in (
    "1", "true", "yes", "on")
COORDINATOR_URL  = "" if _SWARM_DISABLED else (
    os.environ.get("COGNIA_COORDINATOR_URL", "")
    or os.environ.get("COORDINATOR_URL", "")
)
SWARM_MODEL      = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")
SWARM_TIMEOUT    = int(os.environ.get("SWARM_TIMEOUT_S", "30"))

# Qwen2 generation sentinel tokens (both <|im_end|> and <|endoftext|>)
_QWEN_EOS_TOKENS = {151643, 151645}
# Legacy Llama EOS for backward compat
_LLAMA_EOS_TOKEN = 2


def _apply_qwen_template(prompt: str,
                          system: str = "You are a helpful assistant.",
                          history: Optional[List[Dict[str, str]]] = None) -> str:
    """Wrap a user prompt in ChatML format for Qwen2 models.

    If ``history`` is given it must be a list of prior turns, each a dict
    ``{"role": "user"|"assistant", "content": str}``. Those turns are rendered
    as ChatML blocks BEFORE the current ``prompt`` so the model sees the prior
    conversation (multi-turn). Without ``history`` the output is the original
    single-turn template, so every existing caller is unaffected.

    Malformed turns (missing/unknown role, empty content) are skipped rather
    than raising, so a noisy ``_history`` buffer can be passed verbatim.
    """
    parts = [f"<|im_start|>system\n{system}<|im_end|>\n"]
    for turn in (history or []):
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant") or not content:
            continue
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    parts.append(f"<|im_start|>user\n{prompt}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


# ══════════════════════════════════════════════════════════════════════
# TOKENIZER LIVIANO (sin dependencias extra)
# ══════════════════════════════════════════════════════════════════════

class LightTokenizer:
    """
    Tokenizer palabra-a-BPE simplificado para simulación y fallback.
    En modo real se reemplaza por el tokenizer HuggingFace del modelo.

    Soporta:
      encode(text) → List[int]
      decode(ids)  → str
    """

    VOCAB_SIZE = 151936   # Qwen2 vocabulary size

    def __init__(self):
        self._cache: dict = {}
        self._rev:   dict = {}

    def _word_id(self, word: str) -> int:
        if word not in self._cache:
            # Hash determinístico al rango del vocabulario
            h = hash(word) % (self.VOCAB_SIZE - 4) + 4
            self._cache[word] = h
            self._rev[h]      = word
        return self._cache[word]

    def encode(self, text: str) -> list:
        tokens = [1]   # BOS
        for word in text.lower().split():
            tokens.append(self._word_id(word))
        return tokens

    def decode(self, ids: list) -> str:
        words = []
        for i in ids:
            if i in (0, 1, 2):
                continue
            words.append(self._rev.get(i, f"<{i}>"))
        return " ".join(words)


def _try_tokenizers_lib(shard_dir: str):
    """Load real BPE tokenizer from tokenizer.json in the shard directory."""
    try:
        from tokenizers import Tokenizer
        path = os.path.join(shard_dir, "tokenizer.json")
        if os.path.exists(path):
            tok = Tokenizer.from_file(path)
            logger.info("[Pipeline] Real BPE tokenizer loaded from %s", path)
            return tok
    except Exception as exc:
        logger.warning("[Pipeline] tokenizers lib failed: %s", exc)
    return None


def _try_hf_tokenizer(model_name: str):
    """Intenta cargar el tokenizer real de HuggingFace si está disponible."""
    try:
        from transformers import AutoTokenizer
        # Mapa modelo → nombre HuggingFace
        HF_MAP = {
            "llama-3.2-3b-q4":    "meta-llama/Llama-3.2-3B",
            "llama-3.1-8b-q4":    "meta-llama/Meta-Llama-3.1-8B",
            "qwen-coder-3b-q4":   "Qwen/Qwen2.5-Coder-3B-Instruct",
            "qwen2.5-coder-3b":   "Qwen/Qwen2.5-Coder-3B-Instruct",
        }
        hf_name = HF_MAP.get(model_name, model_name)
        tok = AutoTokenizer.from_pretrained(hf_name)
        return tok
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
# CLIENTE HTTP/WS PARA EL COORDINADOR
# ══════════════════════════════════════════════════════════════════════

def _http_get(url: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _http_post(url: str, body: dict, timeout: int = 5) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data,
                                   headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ══════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class DistributedInferencePipeline:
    """
    Orquesta la inferencia token-a-token a través del swarm.

    Uso:
        pipeline = DistributedInferencePipeline()
        result   = pipeline.generate("¿Qué es Python?", max_tokens=150)
        # result = {"ok": True, "text": "...", "tokens": 42, "latency_ms": 6300}
    """

    def __init__(self,
                 coordinator_url: str = COORDINATOR_URL,
                 model_name:      str = SWARM_MODEL):
        self.coordinator   = coordinator_url.rstrip("/")
        self.model_name    = model_name
        shard_dir          = os.environ.get("SHARD_WEIGHTS_DIR", "")
        self._tokenizer    = (
            _try_tokenizers_lib(shard_dir)
            or _try_hf_tokenizer(model_name)
            or LightTokenizer()
        )
        self._real_tokenizer = not isinstance(self._tokenizer, LightTokenizer)
        self._mode         = "real" if self._real_tokenizer else "simulation"
        self._model_cfg_cache: Optional[tuple] = None   # (cfg, fetch_time)

    # ── Verificar disponibilidad del swarm ────────────────────────────

    def is_available(self) -> bool:
        """True si el coordinador responde y el swarm está listo."""
        if not self.coordinator:
            return False
        try:
            status = _http_get(
                f"{self.coordinator}/api/swarm/status"
                f"?model_name={self.model_name}",
                timeout=3,
            )
            return status.get("ready", False)
        except Exception:
            return False

    def swarm_info(self) -> dict:
        """Estado resumido para mostrar en la UI."""
        try:
            return _http_get(
                f"{self.coordinator}/api/swarm/status"
                f"?model_name={self.model_name}",
                timeout=3,
            )
        except Exception as e:
            return {"ready": False, "error": str(e)}

    # ── Generación principal ──────────────────────────────────────────

    def generate(self, prompt: str, max_tokens: int = 200,
                 temperature: float = 0.7, system: str = None) -> dict:
        """
        Genera texto mediante inferencia distribuida en el swarm.

        Retorna:
            {ok, text, tokens_generated, latency_ms, nodes_used, mode}
        """
        t0 = time.perf_counter()

        # 1. Obtener ruta del coordinador
        try:
            route_resp = _http_get(
                f"{self.coordinator}/api/swarm/route"
                f"?model_name={self.model_name}",
                timeout=5,
            )
        except Exception as e:
            return {"ok": False, "error": f"Coordinador no responde: {e}"}

        if not route_resp.get("ok"):
            return {"ok": False,
                    "error": route_resp.get("error", "Swarm incompleto")}

        route    = route_resp["route"]
        n_shards = len(route)

        # 2. Crear sesión de relay
        try:
            session = _http_post(
                f"{self.coordinator}/api/session/create",
                {"model_name": self.model_name},
                timeout=5,
            )
            session_id = session["session_id"]
        except Exception as e:
            return {"ok": False, "error": f"No se pudo crear sesión: {e}"}

        # 3. Tokenizar con ChatML
        is_qwen = "qwen" in self.model_name.lower()
        if system:
            _system = system
        else:
            from shattering.model_constants import COGNIA_SYSTEM_PROMPT
            _system = COGNIA_SYSTEM_PROMPT
        formatted = _apply_qwen_template(prompt, _system) if is_qwen else prompt
        current_ids = np.array(self._encode(formatted), dtype=np.int32)

        # 4. Ciclo de generación token a token
        generated_ids  = []
        model_cfg      = self._get_model_config()
        hidden_dim     = model_cfg.get("hidden_dim", 2048)
        eos_set        = _QWEN_EOS_TOKENS if is_qwen else {_LLAMA_EOS_TOKEN}

        tokens_generated = 0
        for _ in range(max_tokens):
            output, success = self._forward_through_swarm(
                current_ids, session_id, route, hidden_dim
            )
            if not success:
                break

            next_id = self._sample(output, temperature)
            tokens_generated += 1

            # Feed generated token into AVP history so focus set stays warm
            try:
                from node.shard_engine import _vocab_pruner as _avp
                if _avp is not None:
                    _avp.update_history(next_id)
            except Exception:
                pass  # AVP is optional; never break generation

            if next_id in eos_set:
                break

            generated_ids.append(next_id)
            # Each subsequent step: only the new token (KV cache assumed on device)
            current_ids = np.array([next_id], dtype=np.int32)

        # 5. Decodificar
        text      = self._decode(generated_ids)
        latency   = (time.perf_counter() - t0) * 1000

        return {
            "ok":               True,
            "text":             text,
            "tokens_generated": tokens_generated,
            "latency_ms":       round(latency, 1),
            "nodes_used":       n_shards,
            "mode":             self._mode,
            "session_id":       session_id,
        }

    async def agenerate(self, prompt: str, max_tokens: int = 200,
                        temperature: float = 0.7, system: str = None) -> dict:
        """Async wrapper around generate(). Non-blocking for FastAPI/event-loop callers."""
        import functools
        loop = asyncio.get_running_loop()
        fn   = functools.partial(self.generate, prompt, max_tokens, temperature, system)
        return await loop.run_in_executor(None, fn)

    # ── Forward a través del swarm ────────────────────────────────────

    def _single_forward_pass(self, payload, session_id: str, route: list) -> tuple:
        """
        One complete pass through the shard chain.

        payload : np.ndarray int32 (token IDs) or float16 (hidden state)
        Returns  : (output_array, success)
        """
        try:
            from node.shard_engine import (
                encode_tokens, encode_hidden_state, decode_wire, decode_hidden_state,
                PTYPE_TOKENS,
            )

            # Encode payload — use new protocol for int32 token IDs
            if payload.dtype == np.int32:
                wire = encode_tokens(0, payload)
            else:
                wire = encode_hidden_state(0, len(route),
                                           payload.astype(np.float16))

            if _LOCAL_ENGINES:
                # Fast path: skip bytes serialization between local engines
                if payload.dtype == np.int32:
                    x = None
                    token_ids = payload
                else:
                    x = payload.astype(np.float32)
                    token_ids = None
                for engine in _LOCAL_ENGINES:
                    out, _ = engine.process(x, token_ids=token_ids, session_id=session_id)
                    # After first shard: hidden state passes through as float32
                    x = out.astype(np.float32) if out.dtype != np.float32 else out
                    token_ids = None
                return out, True

            if not self.coordinator:
                return payload, True

            hidden_b64 = base64.b64encode(wire).decode()
            resp       = _http_post(
                f"{self.coordinator}/api/session/{session_id}/infer",
                {"hidden_state_b64": hidden_b64},
                timeout=SWARM_TIMEOUT,
            )
            result_bytes = base64.b64decode(resp["hidden_state_b64"])
            if result_bytes[0] in (0, 1, 2):
                _, _, out = decode_wire(result_bytes)
            else:
                _, _, out = decode_hidden_state(result_bytes)
            return out, True

        except Exception as exc:
            logger.warning("[Pipeline] _single_forward_pass failed: %s", exc)
            return payload, False

    def _forward_through_swarm(self, hidden: np.ndarray,
                                session_id: str, route: list,
                                hidden_dim: int,
                                n_passes: int = 1) -> tuple:
        """
        Forward the hidden state through the distributed inference pipeline,
        optionally with RST recursive passes (n_passes > 1).

        Priority:
          1. Local engines (same process) — simulation and testing.
          2. HTTP relay via coordinator /api/session/{session_id}/infer.

        Returns (hidden_state_out, success).
        """
        if n_passes <= 1:
            return self._single_forward_pass(hidden, session_id, route)

        # RST: K-pass recursion with context vector injection
        from shattering.recursive_context import RecursiveContext
        ctx = RecursiveContext(hidden_dim=hidden_dim)
        ctx.reset()

        success = True
        for _ in range(n_passes):
            hidden           = ctx.inject(hidden)
            hidden, success  = self._single_forward_pass(hidden, session_id, route)
            if not success:
                break
            ctx.update(hidden)

        return hidden, success

    # ── Tokenizer helpers ─────────────────────────────────────────────

    def _encode(self, text: str) -> list:
        if self._real_tokenizer:
            # tokenizers lib: .encode() returns an Encoding with .ids
            enc = self._tokenizer.encode(text)
            return enc.ids if hasattr(enc, "ids") else list(enc)
        if hasattr(self._tokenizer, "encode"):
            # HuggingFace transformers fallback
            return self._tokenizer.encode(text, add_special_tokens=True)
        return self._tokenizer.encode(text)

    def _decode(self, ids: list) -> str:
        if self._real_tokenizer:
            return self._tokenizer.decode(ids)
        if hasattr(self._tokenizer, "decode") and self._mode == "real":
            return self._tokenizer.decode(ids, skip_special_tokens=True)
        return self._tokenizer.decode(ids)

    def _sample(self, output: np.ndarray, temperature: float) -> int:
        """
        Samples the next token from logits or (in simulation) from the hidden state.

        Real mode   : output is (seq, vocab_size) float32 logits; uses last position.
        Simulation  : output is (1, hidden_dim) float16 hidden state; sampled as proxy.
        """
        if output.ndim == 2 and output.shape[0] > 1:
            flat = output[-1].astype(np.float32)
        else:
            flat = output.flatten().astype(np.float32)
        vocab_size = self._get_model_config().get("vocab_size", 151936)
        if len(flat) > vocab_size:
            flat = flat[:vocab_size]
        elif len(flat) < vocab_size:
            flat = np.pad(flat, (0, vocab_size - len(flat)))
        flat  = flat / max(temperature, 1e-8)
        flat -= flat.max()
        probs = np.exp(flat); probs /= probs.sum()
        return int(np.random.choice(len(probs), p=probs))

    _CFG_TTL_S = 300  # re-fetch after 5 minutes

    def _get_model_config(self) -> dict:
        """Fetch model config from coordinator, cached with 5-minute TTL."""
        if self._model_cfg_cache is not None:
            cfg, fetched_at = self._model_cfg_cache
            if time.monotonic() - fetched_at < self._CFG_TTL_S:
                return cfg
        try:
            cfg = _http_get(
                f"{self.coordinator}/api/model/config"
                f"?model_name={self.model_name}",
                timeout=3,
            )
            self._model_cfg_cache = (cfg, time.monotonic())
            return cfg
        except Exception:
            is_qwen = "qwen" in self.model_name.lower()
            return {
                "hidden_dim": 2048 if is_qwen else 3072,
                "vocab_size": 151936 if is_qwen else 32000,
                "n_shards":   4,
            }

    def invalidate_config_cache(self) -> None:
        """Force a re-fetch of model config on next call."""
        self._model_cfg_cache = None


# Registro de engines locales para simulación sin red real
_LOCAL_ENGINES: list = []


def register_local_engines(engines: list):
    """
    Registra ShardEngines locales para simulación sin WebSockets.
    Útil para tests y desarrollo.
    """
    global _LOCAL_ENGINES
    _LOCAL_ENGINES = engines


# Singleton global del pipeline
_PIPELINE: Optional[DistributedInferencePipeline] = None


def get_pipeline(coordinator_url: str = COORDINATOR_URL,
                 model_name: str = SWARM_MODEL) -> DistributedInferencePipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = DistributedInferencePipeline(coordinator_url, model_name)
    return _PIPELINE

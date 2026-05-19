"""
cognia_desktop_api.py
=====================
Local FastAPI bridge for the Cognia Desktop Electron app.

Runs on http://localhost:8765 as a child process spawned by Electron.
The renderer fetches from this server; Electron never calls Python directly.

Start manually for dev:
    uvicorn cognia_desktop_api:app --port 8765 --reload
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path (this file lives in the repo root)
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from shattering.orchestrator import ShatteringOrchestrator

# In packaged Electron builds, suppress uvicorn's default exception handler
# so crash details are not exposed to the renderer process.
_PACKAGED = os.environ.get("COGNIA_PACKAGED", "0") == "1"

if _PACKAGED:
    import logging as _logging
    _logging.getLogger().setLevel(_logging.WARNING)

_MANIFEST = str(_ROOT / "shattering" / "manifests" / "cognia_desktop.json")
_COORDINATOR = os.environ.get("COGNIA_COORDINATOR_URL")

app = FastAPI(title="Cognia Desktop API", version="1.0.0")

# COGNIA_LAN_MODE=1 → bind to 0.0.0.0 and open CORS for LAN (mobile access).
# Default (Electron mode) → localhost only.
_LAN_MODE = os.environ.get("COGNIA_LAN_MODE", "0") == "1"
_CORS_ORIGINS = (
    os.environ.get("COGNIA_CORS_ORIGINS", "*").split(",")
    if _LAN_MODE
    else ["http://localhost:8765", "http://127.0.0.1:8765"]
)

_cors_kwargs: dict = dict(
    allow_origins=_CORS_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)
if _LAN_MODE:
    # Also permit 192.168.x.x LAN addresses that may not be in COGNIA_CORS_ORIGINS
    _cors_kwargs["allow_origin_regex"] = r"http://192\.168\.\d+\.\d+:\d+"

app.add_middleware(CORSMiddleware, **_cors_kwargs)

# Single orchestrator instance shared across requests
_orch = ShatteringOrchestrator(
    manifest_path=_MANIFEST,
    coordinator_url=_COORDINATOR,
    mode="auto",
)


# ── Pydantic models ────────────────────────────────────────────────────

from pydantic import field_validator

_MAX_PROMPT_CHARS = 4096  # guard against log flooding and excessive inference cost

class InferRequest(BaseModel):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def prompt_not_too_long(cls, v: str) -> str:
        if len(v) > _MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long (max {_MAX_PROMPT_CHARS} chars)")
        return v


class InferResponse(BaseModel):
    text:         str
    sub_model:    str
    confidence:   float
    latency_ms:   float
    mode:         str
    route_reason: str


class RouteResponse(BaseModel):
    sub_model:  str
    confidence: float
    scores:     dict
    reason:     str


# ── Endpoints ──────────────────────────────────────────────────────────

@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest):
    """Route the prompt to the best sub-model and return its response."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    result = await _orch.ainfer(req.prompt)
    return InferResponse(
        text         = result.text,
        sub_model    = result.sub_model,
        confidence   = result.confidence,
        latency_ms   = result.latency_ms,
        mode         = result.mode,
        route_reason = result.route_reason,
    )


@app.get("/route", response_model=RouteResponse)
def route(prompt: str = Query(..., description="Prompt to route", max_length=4096)):
    """Return routing decision without running inference."""
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    d = _orch.route_only(prompt)
    return RouteResponse(
        sub_model  = d.sub_model,
        confidence = d.confidence,
        scores     = d.scores,
        reason     = d.reason,
    )


@app.get("/status")
def status():
    """Return orchestrator + fragment status."""
    return _orch.status()


@app.get("/infer-stream")
async def infer_stream(prompt: str = Query(..., description="Prompt to infer", max_length=_MAX_PROMPT_CHARS)):
    """
    SSE streaming inference endpoint.
    Yields: {"token": "...", "done": false}  per word,
    then:   {"done": true, "sub_model": ..., "latency_ms": ..., "mode": ...}
    """
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    async def generator():
        result = await _orch.ainfer(prompt)
        words = result.text.split()
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield {"data": json.dumps({"token": token, "done": False})}
            await asyncio.sleep(0.02)
        yield {
            "data": json.dumps({
                "done":       True,
                "sub_model":  result.sub_model,
                "confidence": result.confidence,
                "latency_ms": result.latency_ms,
                "mode":       result.mode,
            })
        }

    return EventSourceResponse(generator())


@app.get("/ready")
async def ready():
    """
    Readiness probe: reports shard availability as the primary signal.

    Returns {"status": "ready"} when the Qwen .npz shards are present,
    regardless of Ollama. Falls back to checking Ollama only when shards
    are missing (legacy path still needed for users without shards).
    """
    if _orch.shards_ready():
        return {
            "status": "ready",
            "inference": "shards",
            "shards": "available",
        }

    # Shards not found — check Ollama as secondary option
    import urllib.request as _ur
    import json as _j
    ollama_ok = False
    model_ok  = False
    ollama_base = _orch._ollama_url.replace("/api/generate", "")
    try:
        with _ur.urlopen(f"{ollama_base}/api/tags", timeout=3) as r:
            data = _j.loads(r.read())
        model_name = _orch._ollama_model
        model_ok = any(
            m.get("name", "").split(":")[0] == model_name.split(":")[0]
            for m in data.get("models", [])
        )
        ollama_ok = True
    except Exception:
        pass

    if ollama_ok and model_ok:
        return {
            "status":     "ready",
            "inference":  "ollama",
            "ollama":     "running",
            "model":      "available",
            "model_name": _orch._ollama_model,
        }

    return {
        "status":     "setup_required",
        "reason":     "shards_missing",
        "inference":  "none",
        "shards":     "missing",
        "ollama":     "running" if ollama_ok else "missing",
        "model":      "available" if model_ok else "not_pulled",
        "model_name": _orch._ollama_model,
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    return {"service": "Cognia Desktop API", "version": "1.0.0"}


# ── Dev entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("COGNIA_DESKTOP_PORT", 8765))
    host = "0.0.0.0" if _LAN_MODE else "127.0.0.1"
    uvicorn.run("cognia_desktop_api:app", host=host, port=port, reload=False)

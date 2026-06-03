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

# Load .env from the repo root before any os.environ reads.
# Electron spawns this process without loading .env, so we do it here.
# Existing env vars (set by the OS or Electron) are never overridden.
def _load_dotenv(env_file: Path) -> None:
    if not env_file.is_file():
        return
    with env_file.open(encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            _key = _key.strip()
            _val = _val.strip().strip('"').strip("'")
            if _key and _key not in os.environ:
                os.environ[_key] = _val

_load_dotenv(_ROOT / ".env")

# If SHARD_WEIGHTS_DIR is set but points to a non-existent directory,
# fall back to the value from the project .env (dev workflow: shards in project tree).
def _fix_shard_dir_if_missing() -> None:
    current = os.environ.get("SHARD_WEIGHTS_DIR", "")
    if not current:
        return
    p = Path(current) if Path(current).is_absolute() else _ROOT / current
    if p.is_dir():
        return
    # Override with project .env value
    env_file = _ROOT / ".env"
    if not env_file.is_file():
        return
    with env_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == "SHARD_WEIGHTS_DIR":
                os.environ["SHARD_WEIGHTS_DIR"] = val.strip().strip('"').strip("'")
                break

_fix_shard_dir_if_missing()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import time as _time
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from shattering.orchestrator import ShatteringOrchestrator

# ITCS: Inference-Time Compute Scaling — zero-LLM complexity scorer
from cognia.reasoning.complexity_scorer import ComplexityScorer as _ComplexityScorer
_itcs_scorer = _ComplexityScorer()

# In packaged Electron builds, suppress uvicorn's default exception handler
# so crash details are not exposed to the renderer process.
_PACKAGED = os.environ.get("COGNIA_PACKAGED", "0") == "1"

import logging as _logging
if _PACKAGED:
    _logging.getLogger().setLevel(_logging.WARNING)
else:
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s %(message)s")

_MANIFEST = str(_ROOT / "shattering" / "manifests" / "cognia_desktop.json")
_COORDINATOR = os.environ.get("COGNIA_COORDINATOR_URL")

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    asyncio.create_task(_kv_evict_loop())
    yield

app = FastAPI(title="Cognia Desktop API", version="1.0.0", lifespan=_lifespan)

# COGNIA_LAN_MODE=1 → bind to 0.0.0.0 and open CORS for LAN (mobile access).
# Default (Electron mode) → localhost only.
_LAN_MODE = os.environ.get("COGNIA_LAN_MODE", "0") == "1"
_CORS_ORIGINS = (
    os.environ.get("COGNIA_CORS_ORIGINS", "*").split(",")
    if _LAN_MODE
    # Electron loadFile() sends Origin: null (file:// scheme); include it so
    # Chromium doesn't block EventSource responses from the renderer.
    else ["http://localhost:8765", "http://127.0.0.1:8765", "null"]
)

_cors_kwargs: dict = dict(
    allow_origins=_CORS_ORIGINS,
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Content-Type"],
)
if _LAN_MODE:
    # Also permit 192.168.x.x LAN addresses that may not be in COGNIA_CORS_ORIGINS
    _cors_kwargs["allow_origin_regex"] = r"http://192\.168\.\d+\.\d+:\d+"

app.add_middleware(CORSMiddleware, **_cors_kwargs)

_CHAT_DB = str(_ROOT / "cognia_desktop_chat.db")

def _init_chat_db() -> None:
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_history ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT NOT NULL,"
            "  role TEXT NOT NULL,"
            "  content TEXT NOT NULL,"
            "  ts INTEGER NOT NULL DEFAULT (strftime('%s','now'))"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id, id)"
        )

_init_chat_db()

# ── Semantic Response Cache ────────────────────────────────────────────
# Initialized after _CHAT_DB pool exists so it can share the same SQLite file.
from cognia.semantic_cache import SemanticResponseCache as _SRC
from storage.db_pool import get_pool as _get_pool

_sem_cache: _SRC = _SRC(db_pool=_get_pool(_CHAT_DB))

# Single orchestrator instance shared across requests
_orch = ShatteringOrchestrator(
    manifest_path=_MANIFEST,
    coordinator_url=_COORDINATOR,
    mode="auto",
    max_new_tokens=64,
)

# ── Conversational Intent Predictor / Cache Warmer (CIP) ──────────────
_cache_warmer = None

def _init_cache_warmer() -> None:
    """Initialize CacheWarmer singleton against the shared semantic cache."""
    global _cache_warmer
    try:
        from cognia.reasoning.cache_warmer import CacheWarmer
        _cache_warmer = CacheWarmer(_orch, _sem_cache)
        _api_logger.info("CIP: CacheWarmer initialized")
    except Exception as exc:
        _api_logger.warning("CIP: could not initialize CacheWarmer: %s", exc)

try:
    _init_cache_warmer()
except Exception:
    pass

async def _kv_evict_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            _orch._evict_mla_caches(max_age_seconds=120)
        except Exception:
            pass



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


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    prompt: str
    history: list[ChatMessage] = []

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

_api_logger = _logging.getLogger("cognia_desktop_api")

# ── Real-Time Factual Validation (RFV) ────────────────────────────────
_rfv_validator = None

def _init_rfv() -> None:
    """Initialize the FactualValidator singleton against the local KG DB."""
    global _rfv_validator
    try:
        from cognia.knowledge.graph import KnowledgeGraph
        from cognia.config import DB_PATH
        kg = KnowledgeGraph(DB_PATH)
        from cognia.reasoning.factual_validator import FactualValidator
        _rfv_validator = FactualValidator(kg)
        _api_logger.info("RFV: FactualValidator initialized")
    except Exception as exc:
        _api_logger.warning("RFV: could not initialize FactualValidator: %s", exc)

# Attempt initialization at startup (non-fatal if KG/DB not ready)
try:
    _init_rfv()
except Exception:
    pass


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest, response: "fastapi.Response" = None):
    """Route the prompt to the best sub-model and return its response."""
    from fastapi import Response as _Response
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    # ITCS: score query complexity and set pipeline budget before inference
    _complexity = _itcs_scorer.score(req.prompt)
    _api_logger.info(
        "ITCS score=%d budget=%s reasons=%s",
        _complexity.score, _complexity.budget, _complexity.reasons,
    )
    try:
        from cognia.language_engine import set_pipeline_budget as _spb
        _spb(_complexity.budget)
    except Exception:
        pass

    # Semantic cache lookup — safe fallback, never breaks inference
    try:
        _cached = _sem_cache.lookup(req.prompt)
        if _cached and len(_cached) > 20:
            _r = InferResponse(
                text         = _cached,
                sub_model    = "cache",
                confidence   = 1.0,
                latency_ms   = 0.0,
                mode         = "semantic_cache",
                route_reason = "SRC HIT",
            )
            # FastAPI doesn't pass Response here; headers set via custom response
            from fastapi.responses import JSONResponse
            return JSONResponse(
                content=_r.model_dump(),
                headers={"X-Cache": "HIT"},
            )
    except Exception as _ce:
        _api_logger.warning("SRC lookup error (ignored): %s", _ce)

    try:
        result = await _orch.ainfer(req.prompt)
    except Exception as exc:
        _api_logger.error("Inference failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # Store in semantic cache — safe fallback
    try:
        _sem_cache.store(req.prompt, result.text, result.sub_model)
    except Exception as _ce:
        _api_logger.warning("SRC store error (ignored): %s", _ce)

    # CIP: warm cache for predicted follow-ups (fire and forget)
    if _cache_warmer is not None:
        try:
            _cache_warmer.warm_async(req.prompt, result.text)
        except Exception:
            pass

    # RFV: validate response against KG — never breaks the response
    response_text = result.text
    try:
        if _rfv_validator is not None and len(response_text) > 30:
            rfv_result = _rfv_validator.validate(response_text)
            if rfv_result.has_contradictions:
                correction = _rfv_validator.format_correction_note(rfv_result)
                if correction:
                    response_text = response_text + "\n\n" + correction
    except Exception as _rfv_exc:
        _api_logger.warning("RFV validation error (ignored): %s", _rfv_exc)

    return InferResponse(
        text         = response_text,
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


_SYSTEM_PROMPT = (
    "Eres Cognia, un asistente de IA distribuido y local que corre en el dispositivo del usuario. "
    "Tienes memoria episodica y un grafo de conocimiento para recordar contexto entre sesiones. "
    "Responde siempre en el mismo idioma que el usuario. "
    "Usa Markdown para formatear tus respuestas: **negrita** para enfasis, `codigo inline` para variables y funciones, "
    "bloques de codigo con triple backtick para ejemplos de codigo (incluye el lenguaje, ej: ```python), "
    "y listas con guion para enumeraciones. "
    "Se conciso y directo. Si no sabes algo, dilo claramente en vez de inventar."
)


@app.post("/infer-stream-v2")
async def infer_stream_v2(req: ChatStreamRequest):
    """
    SSE streaming endpoint with full conversation history.
    Body: { prompt: str, history: [{role, content}, ...] }
    The history contains previous turns; prompt is the current user message.
    """
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for m in req.history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.prompt})

    async def generator():
        try:
            got_tokens = False
            async for token_text, _ in _orch.astream_chat(messages):
                if token_text is not None:
                    got_tokens = True
                    yield {"data": json.dumps({"token": token_text, "done": False})}
            if got_tokens:
                yield {"data": json.dumps({
                    "done": True, "sub_model": "llama", "confidence": 1.0,
                    "latency_ms": 0, "mode": "llama.cpp", "route_reason": "llama.cpp",
                })}
            else:
                yield {"data": json.dumps({"done": True, "error": "no output"})}
        except Exception as exc:
            _api_logger.error("stream_v2 failed: %s", exc, exc_info=True)
            yield {"data": json.dumps({"done": True, "error": str(exc)})}

    return EventSourceResponse(generator())


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

    # ITCS: score and set budget (astream path goes through shard pipeline, not LanguageEngine,
    # but set it anyway in case the engine is used downstream)
    _stream_complexity = _itcs_scorer.score(prompt)
    _api_logger.info(
        "ITCS stream score=%d budget=%s",
        _stream_complexity.score, _stream_complexity.budget,
    )
    try:
        from cognia.language_engine import set_pipeline_budget as _spb
        _spb(_stream_complexity.budget)
    except Exception:
        pass

    async def generator():
        try:
            result = None
            got_tokens = False
            async for token_text, final in _orch.astream(prompt):
                if token_text is not None:
                    got_tokens = True
                    yield {"data": json.dumps({"token": token_text, "done": False})}
                else:
                    result = final
            if result is None:
                if got_tokens:
                    # llama.cpp path: tokens delivered, no InferResult object — send clean done
                    yield {"data": json.dumps({"done": True, "sub_model": "llama", "confidence": 1.0, "latency_ms": 0, "mode": "llama.cpp", "route_reason": "llama.cpp"})}
                else:
                    yield {"data": json.dumps({"done": True, "error": "no output"})}
                return
            yield {
                "data": json.dumps({
                    "done":         True,
                    "sub_model":    result.sub_model,
                    "confidence":   result.confidence,
                    "latency_ms":   result.latency_ms,
                    "mode":         result.mode,
                    "route_reason": getattr(result, "route_reason", ""),
                })
            }
        except Exception as exc:
            _api_logger.error("Stream inference failed: %s", exc, exc_info=True)
            yield {"data": json.dumps({"done": True, "error": str(exc)})}

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


@app.get("/health/performance")
async def health_performance():
    """Measure real tok/s by running a short test inference."""
    import time
    backend_activo = "llama" if (
        hasattr(_orch, "_llama") and _orch._llama is not None
        and hasattr(_orch._llama, "stream_chat")
    ) else "numpy"
    nano_draft_activo = getattr(_orch, "_draft", None) is not None
    try:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "Hola"},
        ]
        tokens = 0
        t0 = time.perf_counter()
        async for token_text, _ in _orch.astream_chat(messages):
            if token_text is not None:
                tokens += 1
                if tokens >= 10:
                    break
        elapsed = time.perf_counter() - t0
        tok_s = round(tokens / elapsed, 2) if elapsed > 0 else 0.0
        return {
            "tok_s": tok_s,
            "latencia_total_ms": round(elapsed * 1000, 1),
            "backend_activo": backend_activo,
            "nano_draft_activo": nano_draft_activo,
        }
    except Exception as exc:
        return {"error": str(exc), "tok_s": 0}


class ChatHistoryRequest(BaseModel):
    session_id: str
    messages: list[ChatMessage]


@app.get("/chat/history")
def get_chat_history(session_id: str = Query(..., max_length=128)):
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return {"messages": [{"role": r, "content": c} for r, c in rows]}


@app.post("/chat/history")
def save_chat_history(req: ChatHistoryRequest):
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        conn.execute("DELETE FROM chat_history WHERE session_id = ?", (req.session_id,))
        conn.executemany(
            "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
            [(req.session_id, m.role, m.content) for m in req.messages],
        )
    return {"saved": len(req.messages)}


@app.delete("/chat/history")
def delete_chat_history(session_id: str = Query(..., max_length=128)):
    from storage.db_pool import get_pool
    with get_pool(_CHAT_DB).get() as conn:
        conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
    return {"deleted": True}


class AgentRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)


class AgentResponse(BaseModel):
    result: str
    latency_ms: float


@app.post("/agent", response_model=AgentResponse)
async def run_agent(req: AgentRequest):
    """Run a single agent task via the orchestrator."""
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task cannot be empty")
    t0 = _time.perf_counter()
    try:
        result = await _orch.ainfer(
            f"Eres un agente de IA. Ejecuta esta tarea de forma directa y concisa:\n\n{req.task}"
        )
        latency = (_time.perf_counter() - t0) * 1000
        return AgentResponse(result=result.text, latency_ms=round(latency, 1))
    except Exception as exc:
        _api_logger.error("Agent task failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


_SKILLS_DIR_API = _ROOT / "cognia_skills"


@app.get("/skills")
def list_skills():
    """List available skill files from cognia_skills/."""
    import pathlib, re as _re
    skills_dir = _SKILLS_DIR_API
    if not skills_dir.exists():
        return {"skills": []}
    result = []
    for f in sorted(skills_dir.glob("*.md")):
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        desc = ""
        in_front = False
        for line in lines:
            if line.strip() == "---":
                in_front = not in_front
                continue
            if in_front and line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
        result.append({"name": f.stem, "description": desc, "file": f.name})
    return {"skills": result}


@app.get("/skills/{name}")
def get_skill(name: str):
    """Return full content of a skill file."""
    import re as _re
    if not _re.match(r'^[\w\-]+$', name):
        raise HTTPException(status_code=400, detail="invalid skill name")
    f = _SKILLS_DIR_API / f"{name}.md"
    if not f.exists():
        raise HTTPException(status_code=404, detail="skill not found")
    return {"name": name, "content": f.read_text(encoding="utf-8", errors="replace")}


@app.get("/network/status")
async def network_status():
    """P2P network status: coordinator reachability + local backend info."""
    import urllib.request as _ur
    import json as _j

    local_backend = "llama" if (
        hasattr(_orch, "_llama") and _orch._llama is not None
        and hasattr(_orch._llama, "stream_chat")
    ) else "numpy"
    nano_draft = getattr(_orch, "_draft", None) is not None

    coordinator_url = os.environ.get("COGNIA_COORDINATOR_URL", "").rstrip("/")
    if not coordinator_url:
        return {"online": False, "error": "no coordinator configured",
                "local_backend": local_backend, "nano_draft": nano_draft}

    try:
        req = _ur.Request(f"{coordinator_url}/status", headers={"Accept": "application/json"})
        with _ur.urlopen(req, timeout=3) as r:
            data = _j.loads(r.read())
        data["local_backend"] = local_backend
        data["nano_draft"] = nano_draft
        data.setdefault("online", True)
        return data
    except Exception as exc:
        return {"online": False, "error": "coordinator unreachable",
                "local_backend": local_backend, "nano_draft": nano_draft}


@app.get("/api/cache/stats")
def cache_stats():
    """Return semantic response cache statistics (entries, hit_rate, total_hits)."""
    try:
        return _sem_cache.stats()
    except Exception as exc:
        _api_logger.warning("cache_stats error: %s", exc)
        return {"entries": 0, "total_hits": 0, "hit_rate": 0.0}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    return {"service": "Cognia Desktop API", "version": "1.0.0"}


# ── Ollama-compatible proxy endpoint (for remote cognia nodes) ─────────────
@app.post("/api/generate")
async def ollama_generate(req: dict):
    """Ollama-compatible /api/generate endpoint for remote cognia clients."""
    prompt = req.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    try:
        result = await infer(InferRequest(prompt=prompt, history=[]))
        return {
            "model": req.get("model", "cognia"),
            "response": result.text,
            "done": True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── File browser endpoints ─────────────────────────────────────────────

import re as _re_files

_WORKSPACE = Path.cwd()


@app.get("/files/list")
def list_files(path: str = "."):
    """List files in a directory relative to workspace."""
    target = (_WORKSPACE / path).resolve()
    if not str(target).startswith(str(_WORKSPACE)):
        raise HTTPException(status_code=403, detail="path outside workspace")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="not a directory")
    entries = []
    try:
        for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if e.name.startswith('.') and e.name not in ('.env',):
                continue
            entries.append({
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
                "size": e.stat().st_size if e.is_file() else None,
                "path": str(e.relative_to(_WORKSPACE)).replace("\\", "/"),
            })
    except PermissionError:
        pass
    return {"path": str(target.relative_to(_WORKSPACE)).replace("\\", "/"), "entries": entries[:100]}


@app.get("/files/read")
def read_file(path: str):
    """Read a text file relative to workspace. Max 100KB."""
    target = (_WORKSPACE / path).resolve()
    if not str(target).startswith(str(_WORKSPACE)):
        raise HTTPException(status_code=403, detail="path outside workspace")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not a file")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": content[:102400], "truncated": len(content) > 102400}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/files/write")
async def write_file(req: Request):
    """Write text to a file relative to workspace."""
    body = await req.json()
    path = body.get("path", "")
    content = body.get("content", "")
    if not path or not _re_files.match(r'^[\w\-./]+$', path):
        raise HTTPException(status_code=400, detail="invalid path")
    target = (_WORKSPACE / path).resolve()
    if not str(target).startswith(str(_WORKSPACE)):
        raise HTTPException(status_code=403, detail="path outside workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size": len(content)}


# ── Dev entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("COGNIA_DESKTOP_PORT", 8765))
    host = "0.0.0.0" if _LAN_MODE else "127.0.0.1"
    uvicorn.run("cognia_desktop_api:app", host=host, port=port, reload=False)

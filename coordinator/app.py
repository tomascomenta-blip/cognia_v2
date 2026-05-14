"""
coordinator/app.py
==================
FastAPI app del coordinador del swarm de Cognia.

Responsabilidades:
  - Registro y heartbeat de nodos
  - Asignación de shards
  - Routing de inferencia
  - Relay WebSocket de hidden states

Desplegable en Railway como servicio separado del main Cognia.
Variables de entorno:
  PORT           — puerto (Railway lo setea automáticamente)
  COORDINATOR_KEY — clave de admin opcional para endpoints sensibles
"""

import asyncio
import base64
import json
import logging
import os
import time
from contextlib import asynccontextmanager

_logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request, WebSocket, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from coordinator.registry import NodeRegistry, MODELS, DEFAULT_MODEL, SHATTERING_MODELS
from coordinator.relay import relay_manager, handle_relay_ws, INFER_TIMEOUT_S
from coordinator.contributor import ContributorLedger, generate_token, validate_token, TIERS
from coordinator.federated_store import FederatedStore
from coordinator.rate_limiter import SlidingWindowLimiter
from shattering.router import GlobalRouter

try:
    from prometheus_client import Counter as _PCounter
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator
    _SHATTERING_INFER = _PCounter(
        "shattering_infer_requests_total",
        "Shattering distributed inference requests",
        ["sub_model"],
    )
    _prom_enabled = True
except ImportError:
    _SHATTERING_INFER = None
    _prom_enabled = False


# ══════════════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Coordinator] Iniciando...")
    relay_manager.start_cleanup()
    yield
    relay_manager.cancel()
    print("[Coordinator] Cerrando.")

# ── Rate limiter (slowapi) ─────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Cognia Swarm Coordinator",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS restricted to known local origins; override via env var for cloud deploys
_cors_origins = json.loads(
    os.environ.get("COORDINATOR_ALLOWED_ORIGINS",
                   '["http://localhost:3000","http://localhost:8001","http://localhost:8765"]')
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

registry        = NodeRegistry()
ledger          = ContributorLedger()
_global_router  = GlobalRouter()
_fed_store      = FederatedStore()
_rate_limiter   = SlidingWindowLimiter()
COORDINATOR_KEY = os.environ.get("COORDINATOR_KEY", "")

if not COORDINATOR_KEY:
    _logger.warning(
        "COORDINATOR_KEY is not set. Admin endpoints (/api/node DELETE, "
        "/api/shattering/infer, /api/node/pending_sessions) are unprotected. "
        "Set the COORDINATOR_KEY environment variable before deploying."
    )

if _prom_enabled:
    _Instrumentator().instrument(app).expose(app)


# ══════════════════════════════════════════════════════════════════════
# MODELOS PYDANTIC
# ══════════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    hardware_info: str = ""
    model_name:    str = DEFAULT_MODEL

class HeartbeatRequest(BaseModel):
    node_id: str

class UnregisterRequest(BaseModel):
    node_id: str

class SessionRequest(BaseModel):
    model_name: str = DEFAULT_MODEL

class InferRequest(BaseModel):
    hidden_state_b64: str   # base64-encoded binary from encode_hidden_state()

class ShatteringInferRequest(BaseModel):
    prompt:    str
    sub_model: Optional[str] = None   # if None, auto-routed by GlobalRouter


# ══════════════════════════════════════════════════════════════════════
# AUTENTICACIÓN ADMIN (opcional)
# ══════════════════════════════════════════════════════════════════════

def require_admin(x_coordinator_key: Optional[str] = Header(None)):
    if COORDINATOR_KEY and x_coordinator_key != COORDINATOR_KEY:
        raise HTTPException(status_code=403, detail="Clave de coordinador inválida.")


def require_contributor_or_admin(
    x_coordinator_key:    Optional[str] = Header(None),
    x_contributor_token:  Optional[str] = Header(None),
) -> dict:
    """
    Accepts either the admin key (full access) or a valid contributor token
    with tier >= basic. Returns auth context dict consumed by the endpoint.

    When COORDINATOR_KEY is unset, passes through (existing behavior).
    Always includes tier_info for downstream enforcement.
    """
    if not COORDINATOR_KEY:
        return {"role": "anon", "node_id": None, "tier": "premium",
                "tier_info": TIERS["premium"]}

    if x_coordinator_key == COORDINATOR_KEY:
        return {"role": "admin", "node_id": None, "tier": "premium",
                "tier_info": TIERS["premium"]}

    if x_contributor_token:
        node_id = validate_token(COORDINATOR_KEY, x_contributor_token)
        if node_id:
            tier = ledger.get_tier_for_node(node_id)
            if tier != "none":
                return {"role": "contributor", "node_id": node_id, "tier": tier,
                        "tier_info": TIERS[tier]}

    raise HTTPException(
        status_code=403,
        detail="Admin key or valid contributor token required.",
    )


# ══════════════════════════════════════════════════════════════════════
# ENDPOINTS DE NODO
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/node/register")
@limiter.limit("200/minute")
def register_node(request: Request, req: RegisterRequest):
    """
    Registra un nodo nuevo en el swarm.
    Retorna el shard asignado, la configuración del modelo y,
    cuando COORDINATOR_KEY esta configurado, un contributor_token.
    """
    result = registry.register(
        hardware_info=req.hardware_info,
        model_name=req.model_name,
    )

    cfg       = result["model_config"]
    params_b  = cfg.get("params_b", 0.0) / max(cfg.get("n_shards", 1), 1)
    node_id   = result["node_id"]

    ledger.record_contribution(node_id, params_b)

    if COORDINATOR_KEY:
        result["contributor_token"] = generate_token(COORDINATOR_KEY, node_id)
        result["tier"] = ledger.get_tier_for_node(node_id)

    return result


@app.post("/api/node/heartbeat")
@limiter.limit("200/minute")
def node_heartbeat(request: Request, req: HeartbeatRequest):
    """
    El nodo avisa que sigue activo.
    Debe llamarse cada 30 segundos.
    Los nodos sin heartbeat por 60s se marcan inactivos.
    """
    result = registry.heartbeat(req.node_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.delete("/api/node/{node_id}", dependencies=[Depends(require_admin)])
def unregister_node(node_id: str):
    """El nodo avisa que se desconecta limpiamente."""
    registry.unregister(node_id)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
# ENDPOINTS DE SWARM
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/swarm/status")
def swarm_status(model_name: str = DEFAULT_MODEL):
    """
    Estado actual del swarm.
    Muestra cuántos nodos activos hay por shard y si el sistema está listo.
    """
    status = registry.status(model_name)

    # Añadir estimación de latencia con los nodos actuales
    active = status["active_nodes"]
    if active >= 2:
        from coordinator.registry import MODELS
        cfg = MODELS.get(model_name, {})
        hidden = cfg.get("hidden_dim", 3072)
        hs_kb  = hidden * 2 / 1024
        n_hops = min(active, cfg.get("n_shards", 4)) - 1
        net_ms = n_hops * (50 + (hs_kb / 1024 / 50 * 8 * 1000))
        status["estimated_latency_ms"] = round(net_ms, 1)
        status["estimated_tps"]        = round(1000 / max(1, net_ms + 100), 2)

    return status


@app.get("/api/swarm/route")
@limiter.limit("60/minute")
def get_route(request: Request, model_name: str = DEFAULT_MODEL,
              exclude_node: Optional[str] = None):
    """
    Devuelve la ruta óptima de inferencia.
    Un nodo activo por shard, ordenados 0 → N-1.

    Si falta algún shard, retorna error con shards faltantes.
    """
    result = registry.get_route(model_name=model_name,
                                exclude_node=exclude_node)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@app.get("/api/model/config")
def model_config(model_name: str = DEFAULT_MODEL):
    """Configuración del modelo: capas, dimensiones, shards."""
    cfg = MODELS.get(model_name)
    if not cfg:
        raise HTTPException(status_code=404,
                            detail=f"Modelo '{model_name}' no soportado. "
                                   f"Disponibles: {list(MODELS.keys())}")
    return {"model_name": model_name, **cfg}


@app.get("/api/models")
def list_models():
    """Lista todos los modelos soportados."""
    return {"models": list(MODELS.keys()), "default": DEFAULT_MODEL}


# ══════════════════════════════════════════════════════════════════════
# ENDPOINT DE SESIÓN (para relay)
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/session/create")
@limiter.limit("60/minute")
async def create_session(request: Request, req: SessionRequest):
    """
    Crea una sesión de inferencia.
    Retorna session_id para usar en el WebSocket relay.

    Flujo:
      1. Cliente llama este endpoint → obtiene session_id
      2. Cliente obtiene la ruta con /api/swarm/route
      3. Cada nodo en la ruta conecta a WS /ws/relay/{session_id}/{shard_index}
      4. El hidden state viaja por el relay hasta el último shard
    """
    cfg      = MODELS.get(req.model_name, MODELS[DEFAULT_MODEL])
    n_shards = cfg["n_shards"]
    session_id = await relay_manager.create_session(n_shards)
    return {
        "session_id": session_id,
        "n_shards":   n_shards,
        "expires_in": 120,
    }


# ══════════════════════════════════════════════════════════════════════
# INFERENCIA HTTP (cliente → coordinador → shards → coordinador → cliente)
# ══════════════════════════════════════════════════════════════════════

SHARD_CONNECT_TIMEOUT = 30   # segundos esperando a que conecten todos los shards

@app.post("/api/session/{session_id}/infer")
async def session_infer(session_id: str, req: InferRequest):
    """
    HTTP endpoint for distributed inference.

    Flow:
      1. Decode the initial hidden state (base64 FP16 tensor).
      2. Wait up to SHARD_CONNECT_TIMEOUT seconds for all shard nodes to connect
         their WebSockets to /ws/relay/{session_id}/{shard_index}.
      3. Forward the hidden state to shard 0 — it propagates through the chain.
      4. Wait for the last shard to call send_to_client(), which sets result_ready.
      5. Return the final hidden state / logits as base64.

    Between tokens: the caller must reset the result state by calling this
    endpoint again for each autoregressive step. The session stays open.
    """
    session = await relay_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404,
                            detail="Sesión no encontrada o expirada")

    t0 = time.time()

    # Wait for all shard nodes to connect their WebSockets
    deadline = t0 + SHARD_CONNECT_TIMEOUT
    while not session.is_complete():
        if time.time() > deadline:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Timeout: {len(session.sockets)}/{session.n_shards} "
                    f"shards conectados tras {SHARD_CONNECT_TIMEOUT}s"
                ),
            )
        await asyncio.sleep(0.05)

    # Decode and forward initial hidden state to shard 0
    try:
        hidden_bytes = base64.b64decode(req.hidden_state_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="hidden_state_b64 no es base64 válido")

    session.reset_result()
    sent = await session.send_to_shard0(hidden_bytes)
    if not sent:
        raise HTTPException(status_code=503, detail="Shard 0 desconectado")

    # Wait for the pipeline to complete (last shard fires result_ready)
    try:
        await asyncio.wait_for(
            session.result_ready.wait(),
            timeout=INFER_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Inferencia no completada en {INFER_TIMEOUT_S}s",
        )

    if session.failed:
        raise HTTPException(
            status_code=503,
            detail=f"Relay error: {session.fail_reason}",
        )

    result_b64 = base64.b64encode(session.result_data).decode()
    latency_ms = round((time.time() - t0) * 1000, 1)

    return {
        "hidden_state_b64": result_b64,
        "latency_ms":       latency_ms,
    }


# ══════════════════════════════════════════════════════════════════════
# SHATTERING ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/shattering/route")
def shattering_route(prompt: str):
    """
    Run GlobalRouter on the given prompt and return the recommended sub_model.

    Thin clients (mobile, embedded) can delegate routing to the coordinator
    instead of embedding the keyword table locally.
    """
    decision = _global_router.route(prompt)
    return {
        "sub_model":  decision.sub_model,
        "confidence": decision.confidence,
        "scores":     decision.scores,
        "reason":     decision.reason,
    }


@app.get("/api/shattering/status")
def shattering_status():
    """
    Aggregate swarm status for each Shattering sub-model.
    Shows which sub-model swarms are ready to serve inference.
    """
    result = {}
    for model_key in SHATTERING_MODELS:
        cfg     = MODELS[model_key]
        sm_status = registry.status(model_key)
        result[cfg["sub_model"]] = {
            "model_key":      model_key,
            "domain":         cfg.get("domain", ""),
            "ready":          sm_status["ready"],
            "active_nodes":   sm_status["active_nodes"],
            "shards_covered": sm_status["shards_covered"],
            "shards_total":   sm_status["shards_total"],
            "shard_replicas": sm_status["shard_replicas"],
        }
    any_ready = any(v["ready"] for v in result.values())
    return {"sub_models": result, "any_ready": any_ready}


@app.post("/api/shattering/infer")
@limiter.limit("10/minute")
async def shattering_infer(
    request: Request,
    req: ShatteringInferRequest,
    auth: dict = Depends(require_contributor_or_admin),
):
    """
    Route a text prompt to the appropriate sub-model swarm and run distributed inference.

    If sub_model is omitted, GlobalRouter picks it automatically.
    Internally: creates a session for the target model, waits for shards to connect,
    forwards a stub hidden state, and returns the session result.

    Note: real token generation requires the shard nodes to be running with actual
    weights. Without connected shard nodes this returns a 503.
    """
    if req.sub_model:
        sub_model = req.sub_model.lower()
    else:
        decision  = _global_router.route(req.prompt)
        sub_model = decision.sub_model

    if _SHATTERING_INFER is not None:
        _SHATTERING_INFER.labels(sub_model=sub_model).inc()

    model_name = f"{sub_model}-3.2-3b-q4"
    if model_name not in MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sub_model '{sub_model}'. Valid: logos, techne, rhetor",
        )

    # ── Tier enforcement ──────────────────────────────────────────────
    tier_info = auth["tier_info"]
    allowed   = tier_info["allowed_models"]
    if allowed != ["*"] and model_name not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Model '{model_name}' is not available for tier '{auth['tier']}'. "
                f"Contribute more shards to unlock it."
            ),
        )

    node_id = auth.get("node_id")
    if node_id:
        ok, retry_after = _rate_limiter.check(node_id, tier_info["rpm"])
        if not ok:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded for tier '{auth['tier']}' "
                    f"({tier_info['rpm']} RPM). Retry after {retry_after}s."
                ),
                headers={"Retry-After": str(retry_after)},
            )
    # ─────────────────────────────────────────────────────────────────

    cfg      = MODELS[model_name]
    n_shards = cfg["n_shards"]
    session_id = await relay_manager.create_session(n_shards)

    # Encode prompt as a stub FP16 hidden state so the relay has something to forward
    try:
        import numpy as np
        ids    = list(req.prompt.encode("utf-8"))[:128]
        hs_b64 = base64.b64encode(
            np.array(ids, dtype=np.float16).tobytes()
        ).decode()
    except Exception:
        # numpy may not be available on coordinator; fall through with zero tensor
        hs_b64 = base64.b64encode(bytes(256)).decode()

    session = await relay_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create relay session")

    t0 = time.time()
    deadline = t0 + SHARD_CONNECT_TIMEOUT
    while not session.is_complete():
        if time.time() > deadline:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Timeout: {len(session.sockets)}/{n_shards} shard nodes connected "
                    f"for sub_model '{sub_model}'. Start the node workers first."
                ),
            )
        await asyncio.sleep(0.05)

    session.reset_result()
    sent = await session.send_to_shard0(base64.b64decode(hs_b64))
    if not sent:
        raise HTTPException(status_code=503, detail="Shard 0 disconnected")

    try:
        await asyncio.wait_for(session.result_ready.wait(), timeout=INFER_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Inference timeout ({INFER_TIMEOUT_S}s) for sub_model '{sub_model}'",
        )

    if session.failed:
        raise HTTPException(
            status_code=503,
            detail=f"Relay error: {session.fail_reason}",
        )

    result_b64 = base64.b64encode(session.result_data).decode()
    latency_ms = round((time.time() - t0) * 1000, 1)
    decision   = _global_router.route(req.prompt)

    if auth.get("node_id"):
        ledger.increment_requests(auth["node_id"])

    return {
        "sub_model":        sub_model,
        "session_id":       session_id,
        "hidden_state_b64": result_b64,
        "latency_ms":       latency_ms,
        "route":            {
            "confidence": decision.confidence,
            "reason":     decision.reason,
        },
    }


# ══════════════════════════════════════════════════════════════════════
# CONTRIBUTOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/tiers")
def list_tiers():
    """
    Returns all contribution tiers with their thresholds and benefits.
    Nodes call this to understand what they earn by contributing shards.
    """
    return {"tiers": TIERS}


@app.get("/api/contribution/{node_id}")
def get_contribution(node_id: str):
    """
    Returns the ledger entry for node_id: total params contributed,
    current tier, allowed models, and requests served so far.
    """
    entry = ledger.get_contribution(node_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"node_id '{node_id}' not found in contributor ledger.",
        )
    return entry


# ══════════════════════════════════════════════════════════════════════
# FEDERATED LEARNING
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/federated/contribute")
@limiter.limit("10/hour")
async def federated_contribute(
    request: Request,
    x_contributor_token: Optional[str] = Header(None),
):
    """
    Submit a locally trained LoRA adapter for federated aggregation.

    Body: raw npz bytes (keys: k_A, k_B, v_A, v_B). Max 512 KB.
    Header: X-Contributor-Token issued at node registration.

    Clients should add Gaussian noise (sigma=0.01) to adapter matrices
    before submitting to avoid exposing personal episode patterns.
    FedAvg runs automatically every 5 contributions.
    """
    if not x_contributor_token:
        raise HTTPException(status_code=401, detail="X-Contributor-Token requerido.")
    node_id = validate_token(COORDINATOR_KEY, x_contributor_token)
    if not node_id:
        raise HTTPException(status_code=403, detail="Token invalido.")

    entry = ledger.get_contribution(node_id)
    if not entry or entry["tier"] == "none":
        raise HTTPException(status_code=403, detail="Sin contribucion registrada para este nodo.")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Body vacio.")

    contrib_id = _fed_store.add_contribution(
        node_id=node_id,
        total_params_b=entry["total_params_b"],
        adapter_blob=body,
    )
    if contrib_id is None:
        raise HTTPException(status_code=422, detail="Formato o tamanio de adapter invalido.")

    return {"status": "queued", "contribution_id": contrib_id, "tier": entry["tier"]}


@app.get("/api/federated/global")
@limiter.limit("30/hour")
async def federated_global(
    request: Request,
    x_contributor_token: Optional[str] = Header(None),
):
    """
    Download the current global LoRA adapter (FedAvg result).
    Returns 404 if no aggregation has occurred yet.
    Requires basic+ contributor tier.
    """
    if not x_contributor_token:
        raise HTTPException(status_code=401, detail="X-Contributor-Token requerido.")
    node_id = validate_token(COORDINATOR_KEY, x_contributor_token)
    if not node_id:
        raise HTTPException(status_code=403, detail="Token invalido.")

    entry = ledger.get_contribution(node_id)
    if not entry or entry["tier"] == "none":
        raise HTTPException(status_code=403, detail="Acceso de contribuidor requerido.")

    blob = _fed_store.get_global_adapter()
    if blob is None:
        raise HTTPException(status_code=404, detail="Adaptador global aun no disponible.")

    from fastapi.responses import Response
    return Response(content=blob, media_type="application/octet-stream")


@app.get("/api/federated/stats", dependencies=[Depends(require_admin)])
def federated_stats():
    """Aggregation statistics. Admin only."""
    return _fed_store.stats()


# ══════════════════════════════════════════════════════════════════════
# WEBSOCKET RELAY
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/node/{node_id}/pending_sessions", dependencies=[Depends(require_admin)])
def pending_sessions(node_id: str):
    """
    Retorna sesiones activas donde este nodo está en la ruta.
    El nodo hace polling cada 2s para saber cuándo unirse al relay.

    El coordinador lleva un registro de qué nodos están asignados
    a cada sesión activa via relay_manager.
    """
    # Por ahora: retornar sesiones activas donde el shard del nodo
    # está en la ruta. El nodo se une si no está ya conectado.
    try:
        node = registry._get_node(node_id)
        if not node:
            return {"sessions": []}
    except Exception:
        return {"sessions": []}

    # Listar sesiones activas del relay que necesitan este shard
    sessions_for_node = []
    for sid, session in list(relay_manager._sessions.items()):
        if not session.is_expired():
            # Si el shard del nodo no está conectado aún → notificar
            if node.shard not in session.sockets:
                sessions_for_node.append(sid)

    return {"sessions": sessions_for_node, "shard": node.shard}


@app.websocket("/ws/relay/{session_id}/{shard_index}")
async def websocket_relay(websocket: WebSocket,
                          session_id: str,
                          shard_index: int):
    """
    WebSocket relay entre nodos.

    Cada nodo conecta con su índice en la ruta:
      /ws/relay/{session_id}/0  → primer shard
      /ws/relay/{session_id}/1  → segundo shard
      ...

    El coordinador retransmite los bytes sin leerlos.
    Los hidden states están en FP16 (~6-16 KB por token).
    """
    await handle_relay_ws(websocket, session_id, shard_index)


# ══════════════════════════════════════════════════════════════════════
# HEALTH + READINESS
# ══════════════════════════════════════════════════════════════════════

@app.get("/ready")
def ready():
    """
    Readiness probe for Railway / k8s.
    Returns 200 only when:
      - The coordinator SQLite registry is reachable (SELECT 1)
      - The relay cleanup task is running
    """
    try:
        with registry._conn() as conn:
            conn.execute("SELECT 1")
    except Exception:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    if not relay_manager._cleanup_task or relay_manager._cleanup_task.done():
        raise HTTPException(status_code=503, detail="Cleanup task not running")

    return {"ready": True}


@app.get("/health")
def health():
    return {
        "ok":              True,
        "active_sessions": relay_manager.active_sessions(),
        "timestamp":       time.time(),
    }


@app.get("/")
def root():
    return {
        "service":  "Cognia Swarm Coordinator",
        "version":  "1.0.0",
        "docs":     "/docs",
        "status":   "/api/swarm/status",
    }


# ══════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("coordinator.app:app", host="0.0.0.0", port=port, reload=False)

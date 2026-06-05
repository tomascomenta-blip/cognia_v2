import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import inference_proxy
import key_store

DATA_DIR = os.environ.get("DATA_DIR", "/data")
VERSION = "1.0.0"


def _try_download_shard() -> bool:
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        return False
    shard_path = os.path.join(DATA_DIR, "shard_0.npz")
    if os.path.exists(shard_path):
        return True
    try:
        from huggingface_hub import hf_hub_download

        hf_hub_download(
            repo_id="Acua124298042/cognia-shards",
            filename="shard_0.npz",
            local_dir=DATA_DIR,
            token=hf_token,
        )
        return True
    except Exception as exc:
        print(f"[cognia_public_api] shard download failed: {exc}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(DATA_DIR, exist_ok=True)
    key_store.init_db()

    shard_path = os.path.join(DATA_DIR, "shard_0.npz")
    if os.path.exists(shard_path):
        inference_proxy.SHARD_LOADED = True
    else:
        inference_proxy.SHARD_LOADED = _try_download_shard()

    inference_proxy.startup_inference()

    # Start shard loading in background thread (takes ~10 min to download 1.2GB)
    import threading
    from cognia_inference import local_runner
    hf_token = os.environ.get("HF_TOKEN", "")
    threading.Thread(target=local_runner.startup, args=(hf_token,), daemon=True).start()
    print("[cognia_public_api] Shard loading started in background")

    admin_key = key_store.create_key()
    print(f"[cognia_public_api] ADMIN API KEY: {admin_key}")
    print(f"[cognia_public_api] shard_loaded={inference_proxy.SHARD_LOADED}")

    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Cognia Public API", version=VERSION, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*", "Authorization"],
    allow_credentials=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    prompt: str = Field(..., max_length=2000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "alive"}



@app.get("/v1/status")
async def status():
    from cognia_inference import local_runner
    return {
        "status": "ok",
        "shard_loaded": inference_proxy.SHARD_LOADED,
        "inference_ready": local_runner.is_ready(),
        "coordinator": "https://cognia-coordinator-production.up.railway.app",
        "version": VERSION,
    }


@app.post("/v1/keys/create")
@limiter.limit("5/hour")
async def create_key(request: Request):
    key = key_store.create_key()
    return {
        "api_key": key,
        "message": "Guarda esta key. No se puede recuperar si la pierdes.",
        "example_js": (
            f"fetch('/v1/generate', {{method:'POST', "
            f"headers:{{'Authorization':'Bearer {key}','Content-Type':'application/json'}}, "
            f"body: JSON.stringify({{prompt:'Hola Cognia!'}})}})"
            f".then(r=>r.json()).then(console.log)"
        ),
    }


def _key_by_api_key(request: Request) -> str:
    # Rate-limit bucket is the API key so each key gets its own 60/min window.
    auth = request.headers.get("authorization", "")
    key = _extract_bearer(auth)
    # Fall back to IP so unauthenticated probes are also bucketed.
    return key or get_remote_address(request)


@app.post("/v1/generate")
@limiter.limit("60/minute", key_func=_key_by_api_key)
async def generate(
    request: Request,
    body: GenerateRequest,
    authorization: str | None = Header(default=None),
):
    key = _extract_bearer(authorization)
    admin_key = os.environ.get("COGNIA_ADMIN_KEY", "")
    # admin key from env is always valid (survives container restarts)
    if not key or (key != admin_key and not key_store.validate_key(key)):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    result = await inference_proxy.generate(body.prompt, body.session_id, key)
    result["shard_loaded"] = inference_proxy.SHARD_LOADED
    return result

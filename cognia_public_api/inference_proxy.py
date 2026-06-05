import os
import time
import asyncio
from pathlib import Path

import httpx

COORDINATOR_URL = os.environ.get(
    "COGNIA_COORDINATOR_URL",
    "https://cognia-coordinator-production.up.railway.app",
)
COORDINATOR_KEY = os.environ.get("COORDINATOR_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

# Qwen2.5-Coder-3B-Instruct — mismo modelo que los shards locales
HF_MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct"
HF_INFERENCE_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

SHARD_LOADED: bool = False


def check_shard() -> bool:
    global SHARD_LOADED
    SHARD_LOADED = (DATA_DIR / "shard_0").exists() or (DATA_DIR / "shard_0.npz").exists()
    return SHARD_LOADED


def startup_inference() -> bool:
    """No-op — HF Serverless API needs no local setup."""
    print(f"[cognia_proxy] HF Serverless Inference ready — model: {HF_MODEL}")
    return bool(HF_TOKEN)


async def generate(prompt: str, session_id: str, api_key: str) -> dict:
    key = COORDINATOR_KEY or os.environ.get("COORDINATOR_KEY", "")

    # Level 1: coordinator shattering swarm (when nodes are online)
    if key:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{COORDINATOR_URL}/api/shattering/infer",
                    json={"prompt": prompt[:2000], "session_id": session_id},
                    headers={"X-Coordinator-Key": key},
                )
            if r.status_code == 200:
                data = r.json()
                return {
                    "text": data.get("text", data.get("response", str(data))),
                    "tokens_per_second": float(data.get("tokens_per_second", data.get("tok_s", 0))),
                    "source": "coordinator",
                }
        except Exception:
            pass

    # Level 2: local numpy inference (Qwen2.5-Coder-3B shards en RAM)
    from cognia_inference import local_runner
    if local_runner.is_ready():
        try:
            result = await asyncio.to_thread(local_runner.generate, prompt, 128)
            return result
        except Exception as exc:
            print(f"[cognia_proxy] local_runner error: {exc}")

    # Level 3: plain fallback
    words = prompt.split()[:10]
    return {
        "text": (
            f"[Cognia] '{' '.join(words)}...' "
            f"(coordinator no disponible, HF_TOKEN {'ok' if HF_TOKEN else 'no configurado'})"
        ),
        "tokens_per_second": 0.0,
        "source": "fallback",
    }

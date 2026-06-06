import os
import asyncio
from pathlib import Path

import httpx

COORDINATOR_URL = os.environ.get(
    "COGNIA_COORDINATOR_URL",
    "https://cognia-coordinator-production.up.railway.app",
)
COORDINATOR_KEY = os.environ.get("COORDINATOR_KEY", "")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

HF_MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct"
HF_ROUTER_URL = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}/v1/chat/completions"
HF_SERVERLESS_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

SHARD_LOADED: bool = False

_SYSTEM_PROMPT = (
    "You are Cognia, a helpful and concise AI assistant. "
    "Respond clearly and directly in the same language as the user."
)


def _tok() -> str:
    """Read HF_TOKEN at call time — picks up secrets injected after module import."""
    return os.environ.get("HF_TOKEN", "")


def check_shard() -> bool:
    global SHARD_LOADED
    SHARD_LOADED = (DATA_DIR / "shard_0").exists() or (DATA_DIR / "shard_0.npz").exists()
    return SHARD_LOADED


def startup_inference() -> bool:
    tok = _tok()
    print(f"[cognia_proxy] HF router ready — token={'ok' if tok else 'MISSING'}")
    return bool(tok)


async def _hf_router(prompt: str, max_tokens: int = 512) -> dict | None:
    tok = _tok()
    if not tok:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=50.0, write=5.0, pool=5.0)
        ) as client:
            r = await client.post(
                HF_ROUTER_URL,
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                json={
                    "model": HF_MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt[:1800]},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
            )
        if r.status_code == 200:
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()
            tokens = data.get("usage", {}).get("completion_tokens", 0)
            return {"text": text, "tokens_per_second": tokens, "source": "hf_router"}
        print(f"[cognia_proxy] hf_router {r.status_code}: {r.text[:200]}")
    except Exception as exc:
        print(f"[cognia_proxy] hf_router error: {exc}")
    return None


async def _hf_serverless(prompt: str) -> dict | None:
    tok = _tok()
    if not tok:
        return None
    try:
        chat_input = (
            f"<|im_start|>system\n{_SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=5.0)
        ) as client:
            r = await client.post(
                HF_SERVERLESS_URL,
                headers={"Authorization": f"Bearer {tok}"},
                json={"inputs": chat_input[:2000], "parameters": {"max_new_tokens": 256, "temperature": 0.7}},
            )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                raw = data[0].get("generated_text", "")
                text = raw.split("<|im_start|>assistant\n")[-1].split("<|im_end|>")[0].strip()
                if text:
                    return {"text": text, "tokens_per_second": 0, "source": "hf_serverless"}
        print(f"[cognia_proxy] hf_serverless {r.status_code}: {r.text[:200]}")
    except Exception as exc:
        print(f"[cognia_proxy] hf_serverless error: {exc}")
    return None


def _is_garbage(text: str) -> bool:
    """True when output is clearly wrong — CJK-heavy or too short."""
    if not text or len(text) < 4:
        return True
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    # >15% CJK in a Spanish/English response is garbage
    return cjk / max(len(text), 1) > 0.15


async def generate(prompt: str, session_id: str, api_key: str) -> dict:
    key = COORDINATOR_KEY or os.environ.get("COORDINATOR_KEY", "")

    # Level 1: coordinator shattering swarm
    if key:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=2.0)
            ) as client:
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

    # Level 2: HF Inference Providers router (free, fast, correct)
    result = await _hf_router(prompt)
    if result:
        return result

    # Level 3: HF Serverless classic (free fallback)
    result = await _hf_serverless(prompt)
    if result:
        return result

    # Level 4: local numpy runner (slow, may produce garbage — filtered)
    from cognia_inference import local_runner
    if local_runner.is_ready():
        try:
            result = await asyncio.to_thread(local_runner.generate, prompt, 256)
            if result and result.get("text") and not _is_garbage(result["text"]):
                return result
            print(f"[cognia_proxy] local_runner garbage discarded: {result.get('text','')[:60]!r}")
        except Exception as exc:
            print(f"[cognia_proxy] local_runner error: {exc}")

    return {
        "text": "[Cognia] Servicio no disponible temporalmente. Por favor reintenta.",
        "tokens_per_second": 0.0,
        "source": "fallback",
    }

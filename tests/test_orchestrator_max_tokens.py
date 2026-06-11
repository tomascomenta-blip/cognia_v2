"""
Regression tests: per-call max_tokens in ShatteringOrchestrator (FASE 1).

Before this change infer()/astream()/astream_chat() always used the
constructor-level self._max_tokens, so a caller could not request a long
answer without rebuilding the orchestrator (the desktop API shares ONE
instance across all requests). Now every entry point accepts an optional
max_tokens (None -> self._max_tokens).

The orchestrator is built directly from the manifest (no Cognia() singletons)
and the llama.cpp backend is replaced by a recording fake, same pattern as
tests/test_distributed_infer_arity.py: fast, no llama-server spawned, but the
REAL _local_infer / astream paths are exercised.
"""

import asyncio

from shattering.orchestrator import InferResult, ShatteringOrchestrator

_MANIFEST = "shattering/manifests/cognia_desktop.json"


class _FakeLlama:
    """Records every generate/stream call; mimics the LlamaBackend facade."""

    def __init__(self):
        self.calls = []
        self.last_tokens_predicted = 7
        self.last_stop_reason = "eos"

    def generate(self, prompt, max_tokens=256, temperature=0.7):
        self.calls.append({"method": "generate", "max_tokens": max_tokens})
        return "respuesta"

    def stream_generate(self, prompt, max_tokens=256, temperature=0.7):
        self.calls.append({"method": "stream_generate", "max_tokens": max_tokens})
        yield "tok"

    def stream_chat(self, messages, max_tokens=512, temperature=0.7):
        self.calls.append({"method": "stream_chat", "max_tokens": max_tokens})
        yield "tok"


def _make_orch(default_max=77):
    orch = ShatteringOrchestrator(manifest_path=_MANIFEST, max_new_tokens=default_max)
    fake = _FakeLlama()
    orch._llama = fake
    orch._llama_checked = True   # prevent _try_load_llama from replacing the fake
    return orch, fake


def test_infer_accepts_per_call_max_tokens():
    orch, fake = _make_orch()
    result = orch.infer("di hola", max_tokens=2048)

    assert isinstance(result, InferResult)
    assert result.text == "respuesta"
    assert fake.calls[0] == {"method": "generate", "max_tokens": 2048}


def test_infer_defaults_to_constructor_budget():
    orch, fake = _make_orch(default_max=77)
    orch.infer("di hola")
    assert fake.calls[0] == {"method": "generate", "max_tokens": 77}


def test_astream_accepts_per_call_max_tokens():
    orch, fake = _make_orch()

    async def _consume():
        async for tok, final in orch.astream("di hola", max_tokens=1234):
            if tok is None:
                break

    asyncio.run(_consume())
    assert fake.calls[0] == {"method": "stream_generate", "max_tokens": 1234}


def test_astream_chat_accepts_per_call_max_tokens():
    orch, fake = _make_orch()
    messages = [{"role": "user", "content": "hola"}]

    async def _consume():
        async for tok, final in orch.astream_chat(messages, max_tokens=999):
            if tok is None:
                break

    asyncio.run(_consume())
    assert fake.calls[0] == {"method": "stream_chat", "max_tokens": 999}


def test_astream_chat_defaults_to_constructor_budget():
    orch, fake = _make_orch(default_max=77)
    messages = [{"role": "user", "content": "hola"}]

    async def _consume():
        async for tok, final in orch.astream_chat(messages):
            if tok is None:
                break

    asyncio.run(_consume())
    assert fake.calls[0] == {"method": "stream_chat", "max_tokens": 77}

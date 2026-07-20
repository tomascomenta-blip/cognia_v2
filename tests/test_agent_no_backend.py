"""
Regression: when there is no code-generation backend (no llama.cpp, no shards,
no Ollama), orch.infer() returns the "No inference backend available" notice as
plain TEXT, not an exception. The notice has no 'ACCION:' line, so the agent
loop used to treat it as an unstructured response and `continue`, burning the
WHOLE step budget repeating the identical error (the user saw 8 wasted steps).

The agent must now detect the missing backend and stop after the first step
with an actionable message.
"""
import cognia.cli as cli


_NO_BACKEND = (
    "[QWEN-CODER] No inference backend available. Run the setup wizard to "
    "download model shards, or start Ollama: ollama serve && ollama pull llama3.2"
)


class _FakeOrch:
    def __init__(self):
        self.calls = 0

    def infer(self, prompt, *a, **k):
        self.calls += 1

        class _R:
            text = _NO_BACKEND

        return _R()


class _FakeAI:
    _orchestrator = None

    def observe(self, *a, **k):
        pass


def test_agent_fails_fast_without_backend(tmp_path, monkeypatch):
    orch = _FakeOrch()
    ai = _FakeAI()
    ai._orchestrator = orch

    # Keep the agent-state file out of the real home directory.
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)

    out = []
    result = cli._run_agent_task(ai, "hacer un juego de sumar dos numeros", out.append)
    text = "\n".join(out).lower()

    assert "backend" in text and "ollama" in text, text
    assert "sin backend de inferencia" in result.lower()
    # Budget estimation (1 call) + at most the first loop step (1 call). It must
    # NOT iterate the whole budget; a couple of calls of slack is plenty.
    assert orch.calls <= 3, f"agent kept calling infer ({orch.calls}x) instead of stopping"

"""
tests/test_generate_delegated.py
Tests for LlamaBackend.generate_delegated — long-form generation via DELEGATION
(orchestrator-workers with clean context + an aggregating head).

All tests use a deterministic fake impl; no real model / llama.cpp is required.
"""

from __future__ import annotations

from node.llama_backend import LlamaBackend


# ---------------------------------------------------------------------------
# Fake impls
# ---------------------------------------------------------------------------

class FakeImpl:
    """Deterministic impl: outline / head / section by prompt content.

    last_stop_reason='eos' makes generate_long stop after a single round, so
    each section produces exactly one chunk of section content.
    """

    def __init__(self):
        self.last_tokens_predicted = 10
        self.last_stop_reason = "eos"
        self.calls = []

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        self.calls.append(prompt)
        low = prompt.lower()
        if "esquema de exactamente" in low or "numeradas" in low:
            return "1. Introduccion\n2. Desarrollo\n3. Conclusion"   # outline
        if "introduccion breve" in low:
            return "Esta es la introduccion unificadora del documento."  # head
        return "Contenido generado para esta seccion con suficiente texto."  # seccion


class FakeImplNoOutline:
    """generate returns None for the outline request (and for everything)."""

    def __init__(self):
        self.last_tokens_predicted = 10
        self.last_stop_reason = "eos"
        self.calls = []

    def generate(self, prompt, max_tokens=256, temperature=0.7, **kw):
        self.calls.append(prompt)
        low = prompt.lower()
        if "esquema de exactamente" in low or "numeradas" in low:
            return None   # outline fails
        return "Contenido generado para esta seccion."


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_delegated_decomposes_and_concatena():
    be = LlamaBackend(FakeImpl())
    res = be.generate_delegated("escribe sobre X", n_tasks=3)
    assert res is not None
    assert res["sections"] == 3
    assert res["text"].count("## ") == 3
    assert "Contenido generado" in res["text"]


def test_delegated_workers_clean_context():
    be = LlamaBackend(FakeImpl())
    res = be.generate_delegated("escribe sobre X", n_tasks=3)
    assert res is not None
    sec_prompts = [c for c in be._impl.calls if "Escribe SOLO la seccion" in c]
    assert sec_prompts  # there were section prompts
    for sp in sec_prompts:
        # CLEAN CONTEXT: no rolling summary of previous sections (the key
        # difference vs generate_hierarchical).
        assert "Resumen de lo ya escrito" not in sp


def test_delegated_head_aggregates():
    be = LlamaBackend(FakeImpl())
    res = be.generate_delegated("escribe sobre X", n_tasks=3, aggregate=True)
    assert res is not None
    assert res["head"] != ""
    assert res["text"].startswith(res["head"])
    assert any("introduccion breve" in c.lower() for c in be._impl.calls)


def test_delegated_no_aggregate():
    be = LlamaBackend(FakeImpl())
    res = be.generate_delegated("x", n_tasks=2, aggregate=False)
    assert res is not None
    assert res["head"] == ""
    assert res["text"].startswith("## ")


def test_delegated_outline_fail_returns_none():
    be = LlamaBackend(FakeImplNoOutline())
    res = be.generate_delegated("escribe sobre X", n_tasks=3)
    assert res is None

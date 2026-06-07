"""
Regression test for Cognia's creator identity in the system prompt.

Bug (fixed this session):
    The CLI streaming path used a generic system prompt ("Eres Cognia, un sistema
    de IA...") that never named the creator, so the base Qwen weights hallucinated
    "creado por Anthropic" when asked. The articulated path already said "Tomas
    Montes", but streaming is the primary path when llama.cpp is loaded.

Fix:
    A single canonical COGNIA_SYSTEM_PROMPT in shattering/model_constants.py,
    naming Tomas Montes and explicitly ruling out Anthropic/Alibaba, used by the
    CLI streaming path, the orchestrator, and the node pipeline.

These tests pin the identity so the wrong creator can't creep back in.
"""

from shattering.model_constants import COGNIA_SYSTEM_PROMPT, COGNIA_CREATOR


def test_creator_is_tomas_montes():
    assert COGNIA_CREATOR == "Tomas Montes"
    assert "Tomas Montes" in COGNIA_SYSTEM_PROMPT


def test_prompt_rules_out_wrong_creators():
    lower = COGNIA_SYSTEM_PROMPT.lower()
    # The prompt must actively counter the base-model hallucinations.
    assert "anthropic" in lower  # mentioned only to negate it
    assert "no anthropic" in lower or "no anthropic ni alibaba" in lower


def test_prompt_is_ascii_for_cp1252_cli():
    # The CLI runs under Windows CP1252; the system string must stay ASCII-safe.
    COGNIA_SYSTEM_PROMPT.encode("ascii")


def test_cli_streaming_uses_adaptive_prompt_built_on_canonical():
    # The streaming fast-path now builds the system prompt via
    # build_adaptive_system_prompt(), which augments COGNIA_SYSTEM_PROMPT.
    import inspect
    from cognia import cli
    from cognia.agent import adaptive_prompt

    assert "build_adaptive_system_prompt" in inspect.getsource(cli)
    # And the builder is grounded in the canonical identity prompt.
    assert "COGNIA_SYSTEM_PROMPT" in inspect.getsource(adaptive_prompt)
    # Identity survives the augmentation even with no learned traits.
    import types
    assert adaptive_prompt.build_adaptive_system_prompt(types.SimpleNamespace()) == COGNIA_SYSTEM_PROMPT

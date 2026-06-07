"""
Regression test for the multi-turn conversation-memory bug in the CLI fast-path.

Bug (fixed this session):
    The interactive CLI streaming path (cognia/cli.py) formatted each prompt with
    `_apply_qwen_template(raw, system)` -- ONLY the current user message. The
    `_history` buffer was appended to AFTER generation but never read back into
    the prompt, so llama.cpp saw a fresh single-turn ChatML every time. Result:
    Cognia "lost context after one message" -- it could not follow a thread.

Fix:
    `_apply_qwen_template` gained an optional `history` param (list of prior
    {"role","content"} turns) rendered as ChatML blocks before the current
    prompt, and the CLI now passes the last N turns of `_history`.

These tests pin the contract: turn N+1's prompt MUST contain turn N's text, in
order, while the no-history call stays byte-for-byte the original single-turn
template (backward compat for the other 6 callers in shattering/orchestrator).
"""

from node.inference_pipeline import _apply_qwen_template


def test_no_history_is_unchanged_single_turn():
    """Without history, output is exactly the legacy single-turn template."""
    out = _apply_qwen_template("hola", system="SYS")
    assert out == (
        "<|im_start|>system\nSYS<|im_end|>\n"
        "<|im_start|>user\nhola<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def test_empty_history_equivalent_to_none():
    assert _apply_qwen_template("q", history=[]) == _apply_qwen_template("q")


def test_prior_turn_text_reaches_the_prompt():
    """The core guarantee: turn N's content appears in turn N+1's prompt."""
    history = [
        {"role": "user", "content": "me llamo Tomas"},
        {"role": "assistant", "content": "Encantado, Tomas."},
    ]
    out = _apply_qwen_template("como me llamo?", system="SYS", history=history)

    # Prior turns are present...
    assert "me llamo Tomas" in out
    assert "Encantado, Tomas." in out
    # ...and the current question is too.
    assert "como me llamo?" in out


def test_turns_render_in_chronological_order_before_current():
    history = [
        {"role": "user", "content": "PRIMERO"},
        {"role": "assistant", "content": "SEGUNDO"},
        {"role": "user", "content": "TERCERO"},
    ]
    out = _apply_qwen_template("ACTUAL", system="SYS", history=history)
    i1 = out.index("PRIMERO")
    i2 = out.index("SEGUNDO")
    i3 = out.index("TERCERO")
    i_now = out.index("ACTUAL")
    # Chronological, and the current prompt is last.
    assert i1 < i2 < i3 < i_now
    # The current turn sits in the final user block, right before assistant.
    assert out.rstrip().endswith("<|im_start|>assistant")
    assert "<|im_start|>user\nACTUAL<|im_end|>" in out


def test_roles_get_correct_chatml_tags():
    history = [
        {"role": "user", "content": "U1"},
        {"role": "assistant", "content": "A1"},
    ]
    out = _apply_qwen_template("now", history=history)
    assert "<|im_start|>user\nU1<|im_end|>" in out
    assert "<|im_start|>assistant\nA1<|im_end|>" in out


def test_malformed_turns_are_skipped_not_raised():
    """A noisy buffer (unknown role, empty/missing content) must not crash."""
    history = [
        {"role": "system", "content": "should be dropped"},   # unknown role
        {"role": "user", "content": ""},                       # empty
        {"role": "assistant"},                                 # missing content
        {"role": "user", "content": "kept"},                   # valid
    ]
    out = _apply_qwen_template("hi", history=history)
    assert "should be dropped" not in out
    assert "kept" in out
    # Exactly one history user block survived, plus the current 'hi' user block.
    assert out.count("<|im_start|>user\n") == 2


def test_single_system_block_regardless_of_history():
    """History must not inject extra system blocks."""
    history = [{"role": "user", "content": "x"}]
    out = _apply_qwen_template("y", system="ONLY", history=history)
    assert out.count("<|im_start|>system\n") == 1

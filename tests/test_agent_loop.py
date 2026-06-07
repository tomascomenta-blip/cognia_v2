"""
Tests for dynamic step budgeting (cognia/agent/loop.py).

Pins that the budget scales with the model's complexity rating, clamps to the
hard cap, and falls back to a heuristic when the model is unavailable.
"""

import types

from cognia.agent.loop import (
    estimate_step_budget, wants_more_steps, AGENT_HARD_CAP, _RATING_TO_BUDGET,
)


def _orch(text):
    """A fake orchestrator whose infer() returns a fixed text."""
    return types.SimpleNamespace(
        infer=lambda prompt: types.SimpleNamespace(text=text)
    )


def test_budget_scales_with_rating():
    assert estimate_step_budget("tarea", _orch("1")) == _RATING_TO_BUDGET[1]
    assert estimate_step_budget("tarea", _orch("5")) == _RATING_TO_BUDGET[5]


def test_budget_never_exceeds_hard_cap():
    assert estimate_step_budget("x", _orch("5")) <= AGENT_HARD_CAP


def test_budget_falls_back_to_heuristic_when_model_fails():
    def boom(prompt):
        raise RuntimeError("no model")
    orch = types.SimpleNamespace(infer=boom)
    # Trivial-looking task -> small heuristic budget.
    assert estimate_step_budget("hola", orch) == 2
    # Long task -> larger heuristic.
    assert estimate_step_budget("x" * 250, orch) == 8


def test_budget_is_at_least_one():
    assert estimate_step_budget("", _orch("garbage no number")) >= 1


def test_wants_more_steps_parses_number():
    assert wants_more_steps("t", "progreso", _orch("3")) == 3
    assert wants_more_steps("t", "progreso", _orch("0")) == 0


def test_wants_more_steps_zero_when_model_fails():
    def boom(prompt):
        raise RuntimeError("no model")
    assert wants_more_steps("t", "p", types.SimpleNamespace(infer=boom)) == 0

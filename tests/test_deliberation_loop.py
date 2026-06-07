"""
tests/test_deliberation_loop.py
===============================
Offline, real-component tests for the bounded Chimera Planner deliberation
loop (whitepaper 7.2/7.3) inside the DELIBERATE route of the Cognitive Loop.
No mocks: planner, self-critic, verifier and the world-model ActionSimulator
all run for real against the local store.
"""

import re

import pytest

from cognia.reasoning.cognitive_loop import (
    CognitiveLoop,
    LoopTrace,
    ROUTE_DELIBERATE,
    MAX_DELIBERATE_ITERS,
    CRITIQUE_REVISE_THRESHOLD,
    format_trace,
)

_DELIB_QUERY = "refactoriza este modulo paso a paso e implementa y prueba"


@pytest.fixture(scope="module")
def loop():
    return CognitiveLoop()


def _iters_in_output(output: str) -> int:
    m = re.search(r"(\d+) iteration", output)
    assert m, "DELIBERATE output must mention iteration count: " + output
    return int(m.group(1))


def test_deliberate_output_mentions_iterations_and_has_plan_and_critique(loop):
    trace = loop.process(_DELIB_QUERY)
    assert isinstance(trace, LoopTrace)
    assert trace.decision.route == ROUTE_DELIBERATE
    # Output summarizes the deliberation loop (iteration count present).
    assert "iteration" in trace.output
    iters = _iters_in_output(trace.output)
    assert iters >= 1
    # Non-None real plan with at least one SubTask.
    assert isinstance(trace.plan, list) and len(trace.plan) >= 1
    # Critique dict with a numeric overall.
    assert isinstance(trace.critique, dict)
    overall = trace.critique.get("scores", {}).get("overall")
    assert isinstance(overall, (int, float))


def test_deliberation_runs_at_most_max_iters(loop):
    trace = loop.process(_DELIB_QUERY)
    iters = _iters_in_output(trace.output)
    assert 1 <= iters <= MAX_DELIBERATE_ITERS


def test_plan_risk_is_populated_for_deliberate(loop):
    trace = loop.process(_DELIB_QUERY)
    # The world-model plan-risk score is folded into the trace.
    assert trace.plan_risk is not None
    assert isinstance(trace.plan_risk, dict)
    # predict_plan() shape: max_risk + recommendation are real, numeric/str.
    assert "max_risk" in trace.plan_risk
    assert isinstance(trace.plan_risk["max_risk"], (int, float))
    assert trace.plan_risk.get("recommendation") in (
        "PROCEED", "SANDBOX", "CONFIRM"
    )


def test_format_trace_shows_deliberation_and_plan_risk(loop):
    trace = loop.process(_DELIB_QUERY)
    rendered = format_trace(trace)
    rendered.encode("ascii")  # ASCII-only safety.
    assert "DELIBERATION:" in rendered
    assert "PLAN RISK:" in rendered


def test_revision_threshold_constants_are_sane():
    # WHY assert: the loop's bound + threshold are the documented invariants.
    assert MAX_DELIBERATE_ITERS == 2
    assert 0.0 < CRITIQUE_REVISE_THRESHOLD < 1.0

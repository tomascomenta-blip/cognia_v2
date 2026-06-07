"""
tests/test_cognitive_loop.py
============================
Offline, real-component tests for the Chimera Cognitive Loop orchestrator.
No mocks: every subsystem (HYDRA router, complexity scorer, planner, verifier,
self-critic, tool registry) runs for real against the local store.
"""

import pytest

from cognia.reasoning.cognitive_loop import (
    CognitiveLoop,
    LoopTrace,
    LoopDecision,
    ROUTE_FAST,
    ROUTE_RECALL,
    ROUTE_DELIBERATE,
    ROUTE_ACT,
    format_trace,
)

_ROUTES = {ROUTE_FAST, ROUTE_RECALL, ROUTE_DELIBERATE, ROUTE_ACT}


@pytest.fixture(scope="module")
def loop():
    return CognitiveLoop()


@pytest.mark.parametrize("query", [
    "hola",
    "calcula 2+2",
    "recuerda lo que dijiste antes sobre shards",
    "refactoriza este modulo paso a paso e implementa y prueba",
    "que tal todo por aca hoy amigo mio",
])
def test_classify_returns_a_valid_route(loop, query):
    decision = loop.classify(query)
    assert isinstance(decision, LoopDecision)
    assert decision.route in _ROUTES
    assert 0.0 <= decision.confidence <= 1.0
    assert isinstance(decision.reasons, list) and decision.reasons
    # ASCII-only reasons (Windows CP1252 safety).
    for r in decision.reasons:
        r.encode("ascii")


def test_act_route_for_tool_verb(loop):
    # Action verb + arithmetic matching a real registered tool -> ACT.
    assert loop.classify("ejecuta una calculadora: 2+2").route == ROUTE_ACT
    assert loop.classify("calcula 2+2").route == ROUTE_ACT


def test_recall_route(loop):
    assert loop.classify(
        "recuerda lo que dijiste antes sobre shards"
    ).route == ROUTE_RECALL


def test_deliberate_route(loop):
    assert loop.classify(
        "refactoriza este modulo paso a paso e implementa y prueba"
    ).route == ROUTE_DELIBERATE


def test_fast_route(loop):
    assert loop.classify("hola").route == ROUTE_FAST


@pytest.mark.parametrize("query", [
    "hola",
    "calcula 2+2",
    "recuerda lo que dijiste antes sobre shards",
    "refactoriza este modulo paso a paso e implementa y prueba",
])
def test_process_never_raises_and_has_output(loop, query):
    trace = loop.process(query)
    assert isinstance(trace, LoopTrace)
    assert trace.decision.route in _ROUTES
    assert isinstance(trace.output, str) and trace.output.strip()
    # format_trace must also be ASCII-clean and non-empty.
    rendered = format_trace(trace)
    assert rendered.strip()
    rendered.encode("ascii")


def test_act_actually_invokes_a_real_tool(loop):
    trace = loop.process("calcula 2+2")
    assert trace.decision.route == ROUTE_ACT
    assert trace.tools_invoked, "ACT must invoke at least one real tool"
    name, result = trace.tools_invoked[0]
    assert isinstance(name, str) and name
    # execute_python on '2+2' really returns 4.
    assert getattr(result, "success", False) is True
    assert "4" in str(getattr(result, "output", ""))


def test_deliberate_yields_plan_and_numeric_critique(loop):
    trace = loop.process(
        "refactoriza este modulo paso a paso e implementa y prueba"
    )
    assert trace.decision.route == ROUTE_DELIBERATE
    # Real deterministic plan: a non-empty list of SubTasks.
    assert isinstance(trace.plan, list) and len(trace.plan) >= 1
    for st in trace.plan:
        assert getattr(st, "description", None)
        assert getattr(st, "tool_required", None)
    # Real critique dict with a numeric overall score.
    assert isinstance(trace.critique, dict)
    overall = trace.critique.get("scores", {}).get("overall")
    assert isinstance(overall, (int, float))
    # Real verifier result.
    assert trace.verify is not None
    assert isinstance(trace.verify.passed, bool)


def test_recall_process_pulls_global_band(loop):
    trace = loop.process(
        "recuerda lo que dijiste antes sobre la arquitectura de shards"
    )
    assert trace.decision.route == ROUTE_RECALL
    assert trace.hydra is not None
    # The GLOBAL band exists in the hydra routing (active or not).
    band_names = {b.name for b in trace.hydra.bands}
    assert "GLOBAL" in band_names

"""
tests/test_action_simulator.py
==============================
Offline, real-component tests for the World-Model "simulate before act"
ActionSimulator (Chimera sections 6 + 8.2). No mocks: the real tool registry
and WorldModelModule are used. Tests cover read-only PROCEED, destructive
free-text CONFIRM, network-tool risk elevation, plan aggregation, and the
"never raises on missing DB" guarantee.
"""

import pytest

from cognia.reasoning.action_simulator import (
    ActionSimulator,
    Prediction,
    format_prediction,
    RISK_MED,
    RISK_HIGH,
)
from cognia.agents.planner import SubTask


@pytest.fixture(scope="module")
def sim():
    return ActionSimulator()


def test_readonly_tool_proceeds(sim):
    # validate_python is a read-only syntax check -> PROCEED, reversible, low risk.
    p = sim.predict_tool("validate_python", {"code": "x = 1\n"})
    assert isinstance(p, Prediction)
    assert p.recommendation == "PROCEED"
    assert p.reversible is True
    assert p.risk < RISK_MED


def test_calc_exec_is_low_risk_proceed(sim):
    # execute_python with a benign arithmetic payload must PROCEED (mirrors the
    # cognitive loop's "calcula 2+2" demo which must keep executing).
    p = sim.predict_tool("execute_python", {"code": "print(2+2)"})
    assert p.recommendation == "PROCEED"
    assert p.reversible is True
    assert p.risk < RISK_MED


def test_destructive_freetext_is_high_risk_confirm(sim):
    # A catastrophic free-text action -> high risk, CONFIRM, irreversible.
    p = sim.simulate("delete all files in C:/ and format disk")
    assert isinstance(p, Prediction)
    assert p.risk >= RISK_HIGH
    assert p.recommendation == "CONFIRM"
    assert p.reversible is False


def test_dangerous_exec_payload_is_confirm(sim):
    # execute_python whose code imports os and removes a file -> CONFIRM.
    p = sim.predict_tool("execute_python", {"code": "import os; os.remove('x')"})
    assert p.recommendation == "CONFIRM"
    assert p.reversible is False


def test_network_tool_risk_elevated(sim):
    # A registered network tool (requires_network=True) must carry elevated risk
    # relative to a purely local read-only tool.
    net = sim.predict_tool("search_wikipedia", {"query": "python"})
    local = sim.predict_tool("validate_python", {"code": "x = 1\n"})
    assert net.risk > local.risk
    assert net.risk >= RISK_MED
    # The network flag must be reflected in the reasons.
    assert any("network" in r.lower() for r in net.reasons)


def test_predict_plan_aggregates(sim):
    # A 2-step plan -> dict with max_risk, mean_risk, horizon, steps, recommendation.
    subtasks = [
        SubTask(id="t0", description="Validate syntax", tool_required="validate_python"),
        SubTask(id="t1", description="Search Wikipedia", tool_required="search_wikipedia"),
    ]
    agg = sim.predict_plan(subtasks)
    assert isinstance(agg, dict)
    assert agg["horizon"] == 2
    assert "max_risk" in agg and "mean_risk" in agg
    assert isinstance(agg["steps"], list) and len(agg["steps"]) == 2
    assert all(isinstance(s, Prediction) for s in agg["steps"])
    assert agg["recommendation"] in {"PROCEED", "SANDBOX", "CONFIRM"}
    # The network step elevates plan max_risk above the local-only floor.
    assert agg["max_risk"] >= RISK_MED


def test_unknown_tool_raises_uncertainty(sim):
    # An unregistered tool name -> higher uncertainty, never crashes.
    p = sim.predict_tool("totally_made_up_tool", {})
    assert isinstance(p, Prediction)
    assert p.uncertainty > 0.3
    assert any("unknown tool" in r.lower() for r in p.reasons)


def test_never_raises_on_missing_db():
    # Pointing at a non-existent DB must NOT raise during construction or use.
    s = ActionSimulator(db_path="this/path/does/not/exist.db")
    p1 = s.predict_tool("validate_python", {"code": "x=1"})
    p2 = s.simulate("read the manual")
    agg = s.predict_plan([
        SubTask(id="t0", description="x", tool_required="validate_python"),
    ])
    assert isinstance(p1, Prediction)
    assert isinstance(p2, Prediction)
    assert isinstance(agg, dict)


def test_format_prediction_is_ascii(sim):
    p = sim.simulate("delete everything")
    rendered = format_prediction(p)
    assert rendered.strip()
    rendered.encode("ascii")  # must not raise
    assert "RECOMMENDATION" in rendered

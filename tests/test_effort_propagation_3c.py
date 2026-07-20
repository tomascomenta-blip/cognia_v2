"""
tests/test_effort_propagation_3c.py
===================================
FASE 3c-resto: propagate the /esfuerzo level to /deliberar, /hipotesis and /razonar.

- /deliberar -> CognitiveLoop._run_deliberate now takes max_iters (offline/deterministic
  loop, so this is testable without the LLM).
- /hipotesis <problema> -> Cognia.generate_hypotheses_many(problem, n=alternativas).
- /razonar -> Cognia.investigate(problem, effort=...) scales n (alternativas) and the
  analogy depth k (profundidad).

The Cognia methods are exercised by BINDING the unbound method to a tiny stub (no heavy
Cognia construction / no LLM): a fake hypothesis engine records the n it received.
"""

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── /deliberar: _run_deliberate honors max_iters (offline, real components) ──

import re
from cognia.reasoning.cognitive_loop import CognitiveLoop, MAX_DELIBERATE_ITERS

_DELIB_QUERY = "refactoriza este modulo paso a paso e implementa y prueba"


def _iters(output: str) -> int:
    m = re.search(r"(\d+) iteration", output)
    assert m, "output must mention iteration count: " + output
    return int(m.group(1))


@pytest.fixture(scope="module")
def loop():
    return CognitiveLoop()


def test_run_deliberate_caps_at_one_iteration(loop):
    _, _, _, out, _ = loop._run_deliberate(_DELIB_QUERY, None, max_iters=1)
    assert _iters(out) == 1            # effort 'bajo' -> single pass, no revision


def test_run_deliberate_default_respects_module_cap(loop):
    _, _, _, out, _ = loop._run_deliberate(_DELIB_QUERY, None)   # max_iters=None
    assert 1 <= _iters(out) <= MAX_DELIBERATE_ITERS


def test_run_deliberate_higher_budget_is_allowed(loop):
    # A larger budget never runs fewer than the capped default; bounded by max_iters.
    _, _, _, out, _ = loop._run_deliberate(_DELIB_QUERY, None, max_iters=4)
    assert 1 <= _iters(out) <= 4


# ── /hipotesis & /razonar: n threads from the effort level ──

from cognia.cognia import Cognia


class _FakeHypothesis:
    def __init__(self):
        self.last_n = None

    def generate_many(self, problem, n, orchestrator=None, diversify=False):
        self.last_n = n
        return []          # empty -> callers short-circuit (no LLM/sub-engines needed)


def _stub():
    return types.SimpleNamespace(hypothesis=_FakeHypothesis(), _orchestrator=None)


def test_generate_hypotheses_many_threads_n():
    stub = _stub()
    Cognia.generate_hypotheses_many(stub, "como ahorrar agua", n=4)
    assert stub.hypothesis.last_n == 4


def test_investigate_threads_alternativas_as_n():
    stub = _stub()
    Cognia.investigate(stub, "como ahorrar agua",
                       effort={"alternativas": 5, "profundidad": 3})
    assert stub.hypothesis.last_n == 5


def test_investigate_without_effort_uses_default_n():
    stub = _stub()
    Cognia.investigate(stub, "como ahorrar agua")   # effort=None -> default n=3
    assert stub.hypothesis.last_n == 3

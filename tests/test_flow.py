"""
tests/test_flow.py — FASE 5: orquestador run_flow.
Fake orchestrator que cuenta inferencias (requisito critico: <=2 LLM por flujo).
Sin DB pesada (el fake AI no instancia memoria -> no dispara el seeder del KG).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeInfer:
    def __init__(self, text):
        self.text = text


class _FakeOrch:
    """Imita ShatteringOrchestrator.infer y cuenta llamadas."""
    def __init__(self, text="Respuesta sintetizada del flujo sobre el tema solicitado."):
        self.calls = 0
        self._text = text

    def infer(self, prompt, lpc_session_id=None, max_tokens=None, temperature=None):
        self.calls += 1
        return _FakeInfer(self._text)


class _FakeAI:
    def __init__(self, orch=None):
        self._orchestrator = orch


def _effort(name):
    from cognia.effort_levels import get_effort
    return get_effort(name)


def test_simple_goal_one_inference():
    """Goal trivial (saludo) -> ruta fast [ejecucion, informe] con 1 sola inferencia."""
    from cognia.agents.flow import run_flow
    orch = _FakeOrch()
    report = run_flow(_FakeAI(orch), "hola", _effort("bajo"), print_fn=lambda *_: None)
    assert orch.calls == 1
    assert "Respuesta sintetizada" in report
    assert "etapas=analisis>ejecucion>informe" in report   # fast: sin plan/verificacion


def test_complex_goal_runs_verification_stage():
    """Goal complejo + esfuerzo alto -> ruta deep con verificacion; <=2 inferencias."""
    from cognia.agents.flow import run_flow
    orch = _FakeOrch()
    goal = ("compara las ventajas y desventajas de async frente a threads en Python "
            "para un servidor concurrente de alta latencia")
    report = run_flow(_FakeAI(orch), goal, _effort("alto"), print_fn=lambda *_: None)
    assert "verificacion" in report
    assert 1 <= orch.calls <= 2
    assert "score=" in report


def test_degrades_without_backend(monkeypatch):
    """Sin backend (construccion del orquestador falla) -> informe determinista, no crashea."""
    import shattering.orchestrator as so

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no backend")

    monkeypatch.setattr(so, "ShatteringOrchestrator", _Boom)
    from cognia.agents.flow import run_flow
    report = run_flow(_FakeAI(None), "que es una lista enlazada", _effort("bajo"),
                      print_fn=lambda *_: None)
    assert report and "etapas=" in report   # produjo informe determinista sin excepcion


def test_analisis_route_differs_by_complexity():
    """Decision dinamica de etapas (0 LLM): simple vs complejo dan rutas distintas."""
    from cognia.agents.flow import _stage_analisis
    simple = _stage_analisis({"goal": "hola", "effort": {}, "print_fn": lambda *_: None})
    cplx = _stage_analisis({
        "goal": ("explica como se compara async vs threads en python con cache, latency y "
                 "memory en un sistema distribuido concurrent"),
        "effort": {}, "print_fn": lambda *_: None})
    assert simple["route"] == ["ejecucion", "informe"]
    assert "verificacion" in cplx["route"]
    assert simple["route"] != cplx["route"]


def test_empty_goal_returns_usage():
    from cognia.agents.flow import run_flow
    out = run_flow(_FakeAI(), "   ", _effort("medio"), print_fn=lambda *_: None)
    assert "vacio" in out.lower()

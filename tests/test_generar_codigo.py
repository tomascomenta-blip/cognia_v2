"""
Regresion de la tool generar_codigo (BoN expuesto al loop /hacer, corrida-2).

Verifica el wire de BoN sin el modelo real: un orch enlatado provee tests
visibles y candidatos; la EJECUCION que rankea es real (run_task_tests). El
candidato correcto gana y se escribe al workspace.
"""
from cognia.agent.tools import run_tool
from cognia.agent import structure


class _FakeInfer:
    def __init__(self, text): self.text = text


class _FakeOrch:
    """Devuelve respuestas enlatadas en orden: primero los asserts (test-gen),
    luego los candidatos de codigo. Ignora temperatura/max_tokens."""
    def __init__(self, responses):
        self._it = iter(responses)

    def infer(self, prompt, max_tokens=None, temperature=None, stop=None):
        try:
            return _FakeInfer(next(self._it))
        except StopIteration:
            return _FakeInfer("")


def _ctx(orch, tmp_path, monkeypatch):
    # confinar la escritura al tmp_path
    import cognia.agents.workers.dev_tools as dv
    monkeypatch.setattr(dv, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    class _AI:
        _orchestrator = orch
    return {"ai": _AI(), "agent_state": {}}


def test_generar_codigo_elige_mejor_y_escribe(tmp_path, monkeypatch):
    good = "```python\ndef doble(n):\n    return n * 2\n```"
    bad = "```python\ndef doble(n):\n    return n + 2\n```"
    orch = _FakeOrch([
        # 1) test-gen (asserts)
        "assert doble(2) == 4\nassert doble(5) == 10",
        # 2) candidato 0 (greedy): malo
        bad,
        # 3-7) candidatos: uno bueno
        bad, good, bad, good, good,
    ])
    ctx = _ctx(orch, tmp_path, monkeypatch)
    out = run_tool("generar_codigo", "doble.py | funcion `doble(n)` que devuelve el doble de n", ctx)
    assert "OK" in out and "rank=tests" in out
    written = (tmp_path / "doble.py").read_text(encoding="utf-8")
    assert "n * 2" in written  # el candidato correcto


def test_generar_codigo_sin_entry_point_error(tmp_path, monkeypatch):
    ctx = _ctx(_FakeOrch([]), tmp_path, monkeypatch)
    out = run_tool("generar_codigo", "x.py | hace algo con numeros", ctx)
    assert "ERROR" in out and "nombre" in out


def test_generar_codigo_formato_invalido(tmp_path, monkeypatch):
    ctx = _ctx(_FakeOrch([]), tmp_path, monkeypatch)
    out = run_tool("generar_codigo", "sin pipe", ctx)
    assert "ERROR" in out and "formato" in out


def test_rules_valida_generar_codigo():
    # la firma quedo registrada para el validador de args
    assert "generar_codigo" in structure.RULES
    assert structure.validate_action("generar_codigo", "f.py | desc") is None
    assert structure.validate_action("generar_codigo", "solo_una_parte") is not None

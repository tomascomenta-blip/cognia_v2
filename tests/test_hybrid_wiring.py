"""
tests/test_hybrid_wiring.py
Wire del perfil hibrido en generar_codigo / delegar_subtarea / loop /hacer:
los permisos del perfil (por /esfuerzo) gatean las etapas caras de la cascada
y los kill-switches env siguen mandando. Sin modelo real: orch enlatado +
recorders monkeypatcheados en los backends caros.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognia.agent.tools import run_tool, _bon_n            # noqa: E402
from cognia.agent.hybrid_router import route_profile       # noqa: E402

# Tarea DURA para el estimador de codigo calibrado (señales algoritmicas +
# tramposas): dif ~0.7 >= todos los umbrales; el candidato enlatado FALLA sus
# asserts -> la cascada quiere escalar; los permisos deciden si puede.
HARD = ("funcion `min_jumps(nums)` que usa dijkstra sobre un graph con "
        "binary search y dynamic program, in-place, sin importar librerias, "
        "edge case de overflow, O(n) eficiente. Ejemplos: "
        "min_jumps([2,3,1,1,4]) == 2, min_jumps([1]) == 0")

BAD = "```python\ndef min_jumps(nums):\n    return -1\n```"


class _FakeInfer:
    def __init__(self, text): self.text = text


class _FakeOrch:
    def __init__(self, responses):
        self._it = iter(responses)

    def infer(self, prompt, max_tokens=None, temperature=None, stop=None):
        try:
            return _FakeInfer(next(self._it))
        except StopIteration:
            return _FakeInfer("")


def _ctx(tmp_path, monkeypatch, profile):
    import cognia.agents.workers.dev_tools as dv
    monkeypatch.setattr(dv, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    orch = _FakeOrch(["assert min_jumps([2,3,1,1,4]) == 2"] + [BAD] * 12)

    class _AI:
        _orchestrator = orch
    return {"ai": _AI(), "agent_state": {}, "hybrid": profile}


def _recorders(monkeypatch):
    """Monkeypatchea los backends caros con recorders que devuelven None
    (= backend no disponible: la cascada sigue con fallback, cero modelo)."""
    calls = {"7b": 0, "q35": 0, "super": 0}
    import node.heavy_code as hc
    monkeypatch.setattr(hc, "heavy_code_backend",
                        lambda: calls.__setitem__("7b", calls["7b"] + 1))
    import node.fleet_registry as fr
    monkeypatch.setattr(fr, "fleet_backend",
                        lambda k: calls.__setitem__("q35", calls["q35"] + 1))
    import cognia.agent.superorganismo as so
    monkeypatch.setattr(so, "superorganismo_solve",
                        lambda *a, **kw: calls.__setitem__(
                            "super", calls["super"] + 1))
    return calls


def test_medio_intenta_colonia_y_superorganismo(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIA_SUPERORGANISMO", raising=False)
    calls = _recorders(monkeypatch)
    p = route_profile(HARD, "medio")
    assert p["colonia_7b"] and p["superorganismo"]
    out = run_tool("generar_codigo", f"j.py | {HARD}", _ctx(tmp_path, monkeypatch, p))
    # el candidato fallo sus asserts -> la cascada INTENTO cada etapa permitida
    assert calls["7b"] == 1, "7B no consultado a esfuerzo medio"
    assert calls["q35"] == 1, "q35 no consultado a esfuerzo medio"
    assert calls["super"] == 1, "superorganismo no consultado con perfil medio"
    # los backends devolvieron None -> se queda con el candidato del 3B
    assert "OK" in out


def test_bajo_niega_etapas_caras(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIA_SUPERORGANISMO", raising=False)
    calls = _recorders(monkeypatch)
    p = route_profile(HARD, "bajo")
    out = run_tool("generar_codigo", f"j.py | {HARD}", _ctx(tmp_path, monkeypatch, p))
    assert calls == {"7b": 0, "q35": 0, "super": 0}, calls
    assert "OK" in out          # el 3B entrega igual (acotado, sin escalar)


def test_env_superorganismo_off_gana_al_perfil(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_SUPERORGANISMO", "0")
    calls = _recorders(monkeypatch)
    p = route_profile(HARD, "medio")
    run_tool("generar_codigo", f"j.py | {HARD}", _ctx(tmp_path, monkeypatch, p))
    assert calls["7b"] == 1 and calls["super"] == 0


def test_bon_max_acota_el_pool():
    n_full, d = _bon_n(HARD)
    n_capped, _ = _bon_n(HARD, bon_max=3)
    assert d >= 0.50 and n_full == 10 and n_capped == 3


def test_delegacion_respetada_por_perfil():
    from cognia.agent.tools import TOOLS
    ctx = {"_delegation_depth": 0, "_delegation_max": 0,
           "_run_agent": lambda *a, **kw: "no deberia correr"}
    out = TOOLS["delegar_subtarea"]["fn"]("investigador | busca algo", ctx)
    assert "profundidad maxima" in out


def test_loop_hacer_inyecta_perfil():
    """Regresion a nivel de fuente (patron test_effort_levels): el loop /hacer
    calcula el perfil, lo pasa por ctx y escala el presupuesto."""
    import inspect
    import cognia.cli as cli_mod
    src = inspect.getsource(cli_mod._run_agent_task)
    assert "route_profile" in src
    assert 'ctx["hybrid"]' in src
    assert "pasos_factor" in src
    assert '_delegation_max' in src

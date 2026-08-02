"""
tests/test_web_app_autonomous_cycle.py
Regresion para web_app._basic_autonomous_cycle:

  1. Importaba `researcher` y `knowledge_integrator` como modulos top-level
     que no existen (viven en cognia.research_engine.*), y el
     `except Exception: pass` ancho tragaba el ImportError en silencio:
     el ciclo degradaba a sleep sin investigar NUNCA y sin dejar rastro.
  2. El fix corrige las rutas de import, estrecha el except a ImportError
     y lo loguea (patron "Cognia degrada en silencio").
"""

import ast
import importlib
import inspect
import logging
import textwrap
import types

import web_app


# ── fakes minimos ─────────────────────────────────────────────────────────────

class _FakeCuriosity:
    def __init__(self, pending):
        self._pending = pending

    def get_pending_proposals(self):
        return self._pending


class _FakeEpisodic:
    db = "fake_memory.db"


class _FakeAI:
    def __init__(self, curiosity):
        self.curiosity_engine = curiosity
        self.episodic = _FakeEpisodic()

    def _sleep_sync(self):
        pass


# ── tests ─────────────────────────────────────────────────────────────────────

def test_imports_del_ciclo_autonomo_resuelven():
    """Cada `from X import Y` dentro de _basic_autonomous_cycle debe resolver.

    Con el bug original (`from researcher import ...`) este test falla con
    ModuleNotFoundError porque `researcher` no existe como modulo top-level.
    """
    src = textwrap.dedent(inspect.getsource(web_app._basic_autonomous_cycle))
    tree = ast.parse(src)
    imports = [(node.module, [a.name for a in node.names])
               for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom)]

    assert imports, "la funcion debe importar los modulos de investigacion"
    for module, names in imports:
        mod = importlib.import_module(module)
        for name in names:
            assert hasattr(mod, name), f"{module} no expone {name}"


def test_ciclo_basico_llega_a_research(monkeypatch):
    """Con una propuesta pendiente, el ciclo debe ejecutar la via de research.

    Se parchean las funciones EN los modulos reales (el import dentro de la
    funcion los resuelve de sys.modules), asi el test ejercita la ruta de
    import verdadera: con el import roto la funcion caia a sleep/idle.
    """
    import cognia.research_engine.researcher as researcher_mod
    import cognia.research_engine.knowledge_integrator as integrator_mod

    fake_result = types.SimpleNamespace(topic="tema-de-prueba")
    fake_integration = types.SimpleNamespace(triples_added=3)
    monkeypatch.setattr(researcher_mod, "research_question",
                        lambda proposal, llm=None: fake_result)
    monkeypatch.setattr(integrator_mod, "integrate_research",
                        lambda result, ai, db: fake_integration)

    proposal = {"id": 1, "question": "que es un test", "topic": "tests",
                "type": "uncertainty", "score": 1.0, "rationale": ""}
    monkeypatch.setattr(web_app, "get_cognia",
                        lambda: _FakeAI(_FakeCuriosity([proposal])))

    out = web_app._basic_autonomous_cycle()

    assert out["action"] == "research"
    assert "tema-de-prueba" in out["message"]
    assert out["searches_done"] == 1


def test_import_error_se_loguea_y_degrada_a_sleep(monkeypatch, caplog):
    """Un ImportError dentro del ciclo ya no se traga en silencio: se loguea
    como ERROR y el ciclo degrada al fallback de sleep."""
    class _CuriosityRota:
        def get_pending_proposals(self):
            raise ImportError("modulo simulado roto")

    monkeypatch.setattr(web_app, "get_cognia",
                        lambda: _FakeAI(_CuriosityRota()))

    with caplog.at_level(logging.ERROR, logger="cognia.web_app"):
        out = web_app._basic_autonomous_cycle()

    assert out["action"] in ("sleep_cycle", "idle")
    assert any("import roto" in rec.getMessage() for rec in caplog.records), \
        "el ImportError debe quedar visible en el log"

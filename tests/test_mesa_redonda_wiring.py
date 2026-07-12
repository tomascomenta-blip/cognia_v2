# -*- coding: utf-8 -*-
"""Wiring de la mesa redonda en generar_codigo (FLEET-30).

Con FAKES para los modelos (best_of_n y 7B monkeypatcheados; el orch fake
hace de 3B reparador) pero ejecucion REAL de asserts en sandbox. Verifica la
POLICY del trigger (default OFF, requiere asserts visibles + tarea dura +
candidato fallando), no la calidad del modelo (eso lo mide el gate)."""
import types

import pytest

import cognia.agent.tools as tools

ASSERTS = ["assert doble(2) == 4", "assert doble(-3) == -6"]
CODE_MALO = "def doble(n):\n    return n + n + 1"
CODE_BUENO = "def doble(n):\n    return n * 2"


def _ctx(tmp_path, repara_con=CODE_BUENO):
    class _Orch:
        def infer(self, prompt, max_tokens=0, temperature=0.0):
            return types.SimpleNamespace(text=f"```python\n{repara_con}\n```")
    import cognia.agents.workers.dev_tools as dev
    dev.AGENT_WORKSPACE_ROOT = str(tmp_path)
    return {"ai": types.SimpleNamespace(_orchestrator=_Orch()),
            "agent_state": {}, "print_fn": lambda *a, **k: None}


def _patch_3b(monkeypatch, code_3b, score_3b, total, visible=None):
    def fake_bon(gen_fn, *a, **k):
        return {"code": code_3b, "n_generated": 3, "n_unique": 3,
                "rank_mode": "tests", "visible_tests": visible or [],
                "ranking": [{"idx": 0, "score": score_3b, "total": total}]}
    monkeypatch.setattr("cognia.agent.candidates.best_of_n", fake_bon)


@pytest.fixture(autouse=True)
def _sin_7b(monkeypatch):
    # El 7B nunca arranca en estos tests: la mesa queda solo con el 3B.
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: None)
    monkeypatch.setattr("node.heavy_code.close_heavy_code", lambda: None)
    monkeypatch.delenv("COGNIA_DELIBERACION", raising=False)
    yield


def test_default_off_no_delibera(monkeypatch, tmp_path):
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "mesa redonda" not in r
    hits = list(tmp_path.rglob("doble.py"))
    assert hits and "n + n + 1" in hits[0].read_text(encoding="utf-8")


def test_on_repara_y_declara(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_DELIBERACION", "1")
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "mesa redonda" in r
    hits = list(tmp_path.rglob("doble.py"))
    assert hits and "n * 2" in hits[0].read_text(encoding="utf-8")


def test_on_sin_asserts_no_delibera(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_DELIBERACION", "1")
    _patch_3b(monkeypatch, CODE_MALO, 0, 0, visible=[])
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "mesa redonda" not in r


def test_on_en_facil_no_delibera(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_DELIBERACION", "1")
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (3, 0.10))   # FACIL
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "mesa redonda" not in r


def test_on_candidato_ya_perfecto_no_delibera(monkeypatch, tmp_path):
    # El candidato inicial pasa los asserts en sandbox -> inicial_perfecto,
    # la mesa no cambia nada y no se declara mejora.
    monkeypatch.setenv("COGNIA_DELIBERACION", "1")
    _patch_3b(monkeypatch, CODE_BUENO, 2, 2, visible=ASSERTS)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "mesa redonda" not in r


def test_on_mesa_no_mejora_se_queda_el_previo(monkeypatch, tmp_path):
    # El reparador devuelve OTRA cosa sin la funcion -> keep-best: queda el malo.
    monkeypatch.setenv("COGNIA_DELIBERACION", "1")
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    ctx = _ctx(tmp_path, repara_con="def otra(n):\n    return 0")
    r = tools._generar_codigo("doble.py | funcion doble(n)", ctx)
    assert "mesa redonda" not in r
    hits = list(tmp_path.rglob("doble.py"))
    assert hits and "n + n + 1" in hits[0].read_text(encoding="utf-8")

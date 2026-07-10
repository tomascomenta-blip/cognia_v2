# -*- coding: utf-8 -*-
"""Escalado reactivo 3B->7B en generar_codigo (MoM fase 4).

Con FAKES: monkeypatchea heavy_code_backend + best_of_n (el 3B) + el 7B
(_heavy.generate GREEDY); NUNCA arranca el 7B. Verifica la POLICY del disparo
(reactivo + pre-filtro de dificultad) y de la seleccion (greedy del 7B, el fix
del probe 2026-07-10), no la calidad del modelo (eso lo mide el gate/probe)."""
import types

import pytest

import cognia.agent.tools as tools


def _ctx(tmp_path):
    class _Orch:
        def infer(self, prompt, max_tokens=0, temperature=0.0):
            return types.SimpleNamespace(text="```python\ndef f():\n return 1\n```")
    import cognia.agents.workers.dev_tools as dev
    dev.AGENT_WORKSPACE_ROOT = str(tmp_path)
    return {"ai": types.SimpleNamespace(_orchestrator=_Orch()),
            "agent_state": {}, "print_fn": lambda *a, **k: None}


def _patch_3b(monkeypatch, code_3b, score_3b, total):
    """best_of_n (el brazo 3B) devuelve este resultado. El 7B NO usa best_of_n."""
    calls = {"n": 0}

    def fake_bon(gen_fn, *a, **k):
        calls["n"] += 1
        return {"code": code_3b, "n_generated": 3, "n_unique": 3, "rank_mode": "tests",
                "ranking": [{"idx": 0, "score": score_3b, "total": total}]}
    monkeypatch.setattr("cognia.agent.candidates.best_of_n", fake_bon)
    return calls


class _FakeHeavy:
    """7B fake: .generate() devuelve un bloque ```python con el codigo dado."""
    def __init__(self, code7):
        self._c = code7
        self.gen_calls = 0

    def generate(self, prompt, **kw):
        self.gen_calls += 1
        return f"```python\n{self._c}\n```" if self._c is not None else ""


def _patch_7b(monkeypatch, code7):
    heavy = _FakeHeavy(code7)
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: heavy)
    monkeypatch.setattr("node.heavy_code.close_heavy_code", lambda: None)
    return heavy


def test_kill_switch_off_no_escala(monkeypatch, tmp_path):
    # heavy None (default OFF) => nunca escala; el 3B no confirma pero no hay 7B
    calls = _patch_3b(monkeypatch, "def resta(a,b):\n return a-b", 1, 2)
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: None)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))   # dura
    r = tools._generar_codigo("resta.py | funcion resta(a,b) que reste", _ctx(tmp_path))
    assert calls["n"] == 1
    assert "escalado a 7B" not in r


def test_no_escala_si_3b_confirma_exito(monkeypatch, tmp_path):
    # el 3B pasa TODOS sus tests visibles (2/2) => confirmado => no se escala
    _patch_3b(monkeypatch, "def suma(a,b):\n return a+b", 2, 2)
    heavy = _patch_7b(monkeypatch, "def suma(a,b):\n return a+b")
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    tools._generar_codigo("suma.py | funcion suma(a,b)", _ctx(tmp_path))
    assert heavy.gen_calls == 0                    # ni desperto el 7B


def test_no_escala_en_faciles_aunque_falle(monkeypatch, tmp_path):
    # el 3B FALLA pero la tarea es FACIL (dif<0.30) => pre-filtro corta
    _patch_3b(monkeypatch, "def f():\n return 0", 0, 2)
    heavy = _patch_7b(monkeypatch, "def f():\n return 1")
    monkeypatch.setattr(tools, "_bon_n", lambda d: (3, 0.10))   # FACIL
    tools._generar_codigo("f.py | funcion f()", _ctx(tmp_path))
    assert heavy.gen_calls == 0


def test_escala_greedy_7b_en_dura_fallida(monkeypatch, tmp_path):
    # 3B falla (1/2) en dura => escala; el 7B greedy produce la funcion => se usa
    _patch_3b(monkeypatch, "def dijkstra(g,s):\n return {}", 1, 2)
    heavy = _patch_7b(monkeypatch, "def dijkstra(g,s):\n return dict(s=0)")
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("dijkstra.py | funcion dijkstra(g,s) camino minimo",
                              _ctx(tmp_path))
    assert heavy.gen_calls == 1                     # UNA generacion greedy del 7B
    assert "escalado a 7B" in r
    # el archivo tiene el codigo del 7B
    hits = list((tmp_path).rglob("dijkstra.py"))
    assert hits and "dict(s=0)" in hits[0].read_text(encoding="utf-8")


def test_escala_sin_tests_visibles(monkeypatch, tmp_path):
    # 0 tests visibles (total=0) en dura => sin confirmacion => escala (fix e2e)
    _patch_3b(monkeypatch, "def dp(x):\n return 0", 0, 0)
    heavy = _patch_7b(monkeypatch, "def dp(x):\n return x*2")
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("dp.py | funcion dp(x)", _ctx(tmp_path))
    assert heavy.gen_calls == 1
    assert "escalado a 7B" in r


def test_7b_sin_funcion_se_queda_3b(monkeypatch, tmp_path):
    # el 7B greedy NO produce 'def entry' => se queda con el codigo del 3B
    _patch_3b(monkeypatch, "def g(x):\n return x", 1, 2)
    heavy = _patch_7b(monkeypatch, "no soy codigo valido")
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("g.py | funcion g(x)", _ctx(tmp_path))
    assert heavy.gen_calls == 1                     # intento el 7B
    assert "escalado a 7B" not in r                 # pero no produjo -> 3B

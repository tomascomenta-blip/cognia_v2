# -*- coding: utf-8 -*-
"""Escalado reactivo 3B->7B en generar_codigo (MoM fase 4).

Con FAKES: monkeypatchea heavy_code_backend + best_of_n; NUNCA arranca el 7B.
Verifica la POLICY del disparo (reactivo + pre-filtro de dificultad), no la
calidad del modelo (eso lo mide el gate pareado con el modelo real)."""
import types

import pytest

import cognia.agent.tools as tools


def _ctx(tmp_path):
    # ctx mínimo que _generar_codigo necesita; _orch(ctx) devuelve el orchestrator
    class _Orch:
        def infer(self, prompt, max_tokens=0, temperature=0.0):
            return types.SimpleNamespace(text="```python\ndef f():\n return 1\n```")
    import cognia.agents.workers.dev_tools as dev
    dev.AGENT_WORKSPACE_ROOT = str(tmp_path)
    return {"ai": types.SimpleNamespace(_orchestrator=_Orch()),
            "agent_state": {}, "print_fn": lambda *a, **k: None}


def _patch_bon(monkeypatch, code_3b, score_3b, total, code_7b=None, score_7b=None):
    """best_of_n devuelve el resultado del 3B; si se re-llama (7B) devuelve el 7B."""
    calls = {"n": 0}

    def fake_bon(gen_fn, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"code": code_3b, "n_generated": 3, "n_unique": 3,
                    "rank_mode": "tests",
                    "ranking": [{"idx": 0, "score": score_3b, "total": total}]}
        return {"code": code_7b or "", "n_generated": 3, "n_unique": 3,
                "rank_mode": "tests",
                "ranking": [{"idx": 0, "score": score_7b, "total": total}]}
    # best_of_n se importa DENTRO de _generar_codigo -> parchear el ORIGEN
    monkeypatch.setattr("cognia.agent.candidates.best_of_n", fake_bon)
    return calls


@pytest.fixture(autouse=True)
def _no_import_errors(monkeypatch):
    # make_raw_gen_fn/SYSTEM_PROMPT + extract_code se importan dentro de la tool;
    # dar stubs para no arrastrar el backend real.
    import cognia_v3.eval.benchmark_code as bc
    monkeypatch.setattr(bc, "make_raw_gen_fn", lambda *a, **k: (lambda *x, **y: ""))
    yield


def test_kill_switch_off_no_escala(monkeypatch, tmp_path):
    # heavy_code_backend None (default OFF) => nunca escala, 1 sola llamada a best_of_n
    calls = _patch_bon(monkeypatch, "def resta(a,b):\n return a-b", 1, 2)
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: None)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))   # dura
    r = tools._generar_codigo("resta.py | funcion resta(a,b) que reste", _ctx(tmp_path))
    assert calls["n"] == 1                       # no hubo 2da llamada (7B)
    assert "escalado a 7B" not in r


def test_no_escala_si_3b_pasa_sus_tests(monkeypatch, tmp_path):
    # el 3B pasa TODOS los tests visibles => no se escala aunque sea dura y 7B vivo
    calls = _patch_bon(monkeypatch, "def suma(a,b):\n return a+b", 2, 2)
    escala = {"c": 0}
    monkeypatch.setattr("node.heavy_code.heavy_code_backend",
                        lambda: escala.__setitem__("c", escala["c"] + 1) or object())
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    tools._generar_codigo("suma.py | funcion suma(a,b)", _ctx(tmp_path))
    assert calls["n"] == 1
    assert escala["c"] == 0                       # ni siquiera despertó el 7B


def test_no_escala_en_faciles_aunque_falle(monkeypatch, tmp_path):
    # el 3B FALLA pero la tarea es FACIL (dif<0.30) => pre-filtro corta, no 7B
    _patch_bon(monkeypatch, "def f():\n return 0", 0, 2)
    woke = {"c": 0}
    monkeypatch.setattr("node.heavy_code.heavy_code_backend",
                        lambda: woke.__setitem__("c", woke["c"] + 1) or object())
    monkeypatch.setattr(tools, "_bon_n", lambda d: (3, 0.10))   # FACIL
    tools._generar_codigo("f.py | funcion f()", _ctx(tmp_path))
    assert woke["c"] == 0                          # el pre-filtro de dificultad corta


def test_escala_en_dura_fallida_y_gana_el_7b(monkeypatch, tmp_path):
    # 3B falla (1/2) en tarea dura => escala; el 7B saca 2/2 => se queda con el 7B
    calls = _patch_bon(monkeypatch, "def dijkstra(g,s):\n return {}", 1, 2,
                       code_7b="def dijkstra(g,s):\n return dict(s=0)", score_7b=2)
    closed = {"c": 0}
    fake_heavy = object()
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: fake_heavy)
    monkeypatch.setattr("node.heavy_code.close_heavy_code",
                        lambda: closed.__setitem__("c", closed["c"] + 1))
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))   # dura
    r = tools._generar_codigo("dijkstra.py | funcion dijkstra(g,s) camino minimo",
                              _ctx(tmp_path))
    assert calls["n"] == 2                         # sí re-corrió con el 7B
    assert "escalado a 7B" in r
    assert closed["c"] == 1                        # cerró el 7B (lazy-load-usar-cerrar)


def test_escala_pero_7b_no_mejora_se_queda_3b(monkeypatch, tmp_path):
    # escala pero el 7B NO supera al 3B (mismo score) => se queda con el 3B, cierra igual
    calls = _patch_bon(monkeypatch, "def f(x):\n return x", 1, 2,
                       code_7b="def f(x):\n return x+0", score_7b=1)
    closed = {"c": 0}
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: object())
    monkeypatch.setattr("node.heavy_code.close_heavy_code",
                        lambda: closed.__setitem__("c", closed["c"] + 1))
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("f.py | funcion f(x)", _ctx(tmp_path))
    assert calls["n"] == 2
    assert "escalado a 7B" not in r                # el 7B no ganó -> no se marca
    assert closed["c"] == 1

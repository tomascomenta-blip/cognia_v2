# -*- coding: utf-8 -*-
"""Etapa 3 de la cascada (Qwen3.5-4B, COLONIA E2): policy del trigger y
keep-best estricto. FAKES para los modelos; ejecución REAL de asserts."""
import types

import pytest

import cognia.agent.tools as tools

ASSERTS = ["assert doble(2) == 4", "assert doble(-3) == -6"]
CODE_MALO = "def doble(n):\n    return n + n + 1"
CODE_PARCIAL = "def doble(n):\n    return n * 2 if n > 0 else 0"   # 1/2
CODE_BUENO = "def doble(n):\n    return n * 2"


def _ctx(tmp_path):
    class _Orch:
        def infer(self, prompt, max_tokens=0, temperature=0.0):
            return types.SimpleNamespace(text="")
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


class _FakeQ35:
    def __init__(self, code):
        self._c = code
        self.calls = 0

    def generate(self, prompt, **kw):
        self.calls += 1
        return f"```python\n{self._c}\n```" if self._c else ""


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: None)
    monkeypatch.setattr("node.heavy_code.close_heavy_code", lambda: None)
    monkeypatch.delenv("COGNIA_DELIBERACION", raising=False)
    yield


def _patch_q35(monkeypatch, code):
    q = _FakeQ35(code)
    monkeypatch.setattr("node.fleet_registry.fleet_backend",
                        lambda key: q if key == "qwen35_4b" else None)
    monkeypatch.setattr("node.fleet_registry.close_fleet_member",
                        lambda key: None)
    return q


def test_dispara_sin_funcion_y_usa_q35(monkeypatch, tmp_path):
    # ni el 3B ni el 7B produjeron 'def doble' -> etapa 3 entrega la funcion
    _patch_3b(monkeypatch, "print('nada')", 0, 0, visible=[])
    q = _patch_q35(monkeypatch, CODE_BUENO)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert q.calls == 1
    assert "etapa 3" in r
    hits = list(tmp_path.rglob("doble.py"))
    assert hits and "n * 2" in hits[0].read_text(encoding="utf-8")


def test_dispara_con_visibles_fallando_y_mejora_estricta(monkeypatch, tmp_path):
    # candidato 0/2 en visibles; q35 da 2/2 -> reemplaza
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    q = _patch_q35(monkeypatch, CODE_BUENO)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert q.calls == 1 and "etapa 3" in r
    hits = list(tmp_path.rglob("doble.py"))
    assert "n * 2" in hits[0].read_text(encoding="utf-8")


def test_no_reemplaza_si_no_mejora_estricto(monkeypatch, tmp_path):
    # candidato 1/2; q35 tambien 1/2 (mismo parcial) -> keep-best: queda el previo
    _patch_3b(monkeypatch, CODE_PARCIAL, 1, 2, visible=ASSERTS)
    q = _patch_q35(monkeypatch, CODE_PARCIAL.replace("n * 2", "(n + n)"))
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert q.calls == 1
    assert "etapa 3" not in r
    hits = list(tmp_path.rglob("doble.py"))
    assert "n * 2 if n > 0" in hits[0].read_text(encoding="utf-8")


def test_no_dispara_si_visibles_pasan_todos(monkeypatch, tmp_path):
    _patch_3b(monkeypatch, CODE_BUENO, 2, 2, visible=ASSERTS)
    q = _patch_q35(monkeypatch, CODE_BUENO)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert q.calls == 0


def test_no_dispara_en_facil(monkeypatch, tmp_path):
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    q = _patch_q35(monkeypatch, CODE_BUENO)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (3, 0.10))
    tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert q.calls == 0


def test_registry_none_no_rompe(monkeypatch, tmp_path):
    _patch_3b(monkeypatch, CODE_MALO, 0, 2, visible=ASSERTS)
    monkeypatch.setattr("node.fleet_registry.fleet_backend", lambda key: None)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "etapa 3" not in r          # fallback silencioso al candidato previo


def test_sin_visibles_sin_7b_reemplaza(monkeypatch, tmp_path):
    # 0 asserts visibles (sin confirmacion, rama burst_balloons) y sin 7B:
    # q35 reemplaza al greedy no-confirmado del 3B (E1: 17/40 > 15/40 RAW).
    # Gap cazado por el live check e2e DBG1.
    _patch_3b(monkeypatch, CODE_MALO, 0, 0, visible=[])
    q = _patch_q35(monkeypatch, CODE_BUENO)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert q.calls == 1 and "etapa 3" in r
    hits = list(tmp_path.rglob("doble.py"))
    assert "n * 2" in hits[0].read_text(encoding="utf-8")


def test_sin_visibles_con_7b_escalado_respeta_al_7b(monkeypatch, tmp_path):
    # Sin visibles pero el 7B YA tomo la tarea -> q35 NO dispara (se respeta
    # el gate del 7B, 8/8 con ocultos; no hay dato q35-vs-7B sin oraculo).
    _patch_3b(monkeypatch, "print('nada util')", 0, 0, visible=[])

    class _Heavy:
        def generate(self, prompt, **kw):
            return "```python\ndef doble(n):\n    return 2 * n\n```"

    monkeypatch.setattr("node.heavy_code.heavy_code_backend", lambda: _Heavy())
    q = _patch_q35(monkeypatch, CODE_BUENO)
    monkeypatch.setattr(tools, "_bon_n", lambda d: (5, 0.9))
    r = tools._generar_codigo("doble.py | funcion doble(n)", _ctx(tmp_path))
    assert "escalado a 7B" in r
    assert q.calls == 0
